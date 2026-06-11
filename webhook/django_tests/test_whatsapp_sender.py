"""Tests for whatsapp send service, provider factory and Celery task."""
import pytest
from unittest.mock import MagicMock, patch
from django.test import TestCase, override_settings

from atendimentos.models import Atendimento, SituacaoAtendimento
from whatsapp.models import EnvioWhatsAppLog
from whatsapp.services.fake_provider import FakeWhatsAppProvider
from whatsapp.services.providers import WhatsAppSendResult
from whatsapp.services.provider_factory import get_provider
from whatsapp.services.sender import WhatsAppSendService
from whatsapp.services.message_builder import build_message


# ──────────────────────────────────────────────────────────────────────────────
# provider_factory
# ──────────────────────────────────────────────────────────────────────────────

class ProviderFactoryTest(TestCase):
    @override_settings(WHATSAPP_PROVIDER="fake")
    def test_fake_provider_returned(self):
        from whatsapp.services.fake_provider import FakeWhatsAppProvider
        p = get_provider()
        assert isinstance(p, FakeWhatsAppProvider)

    @override_settings(WHATSAPP_PROVIDER="evolution")
    def test_evolution_provider_returned(self):
        from whatsapp.services.evolution_provider import EvolutionWhatsAppProvider
        p = get_provider()
        assert isinstance(p, EvolutionWhatsAppProvider)

    @override_settings(WHATSAPP_PROVIDER="unknown_xyz")
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="desconhecido"):
            get_provider()


# ──────────────────────────────────────────────────────────────────────────────
# FakeWhatsAppProvider
# ──────────────────────────────────────────────────────────────────────────────

class FakeProviderTest(TestCase):
    def test_always_succeeds(self):
        p = FakeWhatsAppProvider()
        result = p.send_message("5511999999999", "Teste")
        assert result.success is True
        assert result.status == "FAKE_SENT"

    def test_returns_whatsapp_send_result_type(self):
        p = FakeWhatsAppProvider()
        result = p.send_message("5511999999999", "Mensagem")
        assert isinstance(result, WhatsAppSendResult)


# ──────────────────────────────────────────────────────────────────────────────
# message_builder
# ──────────────────────────────────────────────────────────────────────────────

class MessageBuilderTest(TestCase):
    def test_builds_with_name_and_exam(self):
        msg = build_message("Maria da Silva", "Hemograma")
        assert "Maria da Silva" in msg
        assert "Hemograma" in msg

    def test_fallback_for_empty_name(self):
        msg = build_message("", "TSH")
        assert "Paciente" in msg

    def test_fallback_for_empty_exam(self):
        msg = build_message("João", "")
        assert "procedimento" in msg

    def test_message_is_non_empty_string(self):
        msg = build_message("Ana", "Glicemia")
        assert isinstance(msg, str)
        assert len(msg) > 10


# ──────────────────────────────────────────────────────────────────────────────
# WhatsAppSendService
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(WHATSAPP_PROVIDER="fake", DEFAULT_COUNTRY_CODE="55")
class SendServiceTest(TestCase):
    def _make_atendimento(self, telefone="92999999999", status="N"):
        situacao, _ = SituacaoAtendimento.objects.get_or_create(nome="Agendado")
        return Atendimento.objects.create(
            situacao=situacao,
            paciente="Maria Teste",
            telefone=telefone,
            exame_procedimento="Hemograma",
            status_enviado=status,
        )

    def test_success_updates_status_to_S(self):
        atend = self._make_atendimento()
        service = WhatsAppSendService()
        result = service.send_for_atendimento(atend)
        assert result is True
        atend.refresh_from_db()
        assert atend.status_enviado == "S"
        assert atend.data_envio is not None

    def test_success_creates_log_entry(self):
        atend = self._make_atendimento()
        service = WhatsAppSendService()
        service.send_for_atendimento(atend)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atend).first()
        assert log is not None
        assert log.sucesso is True
        assert log.telefone.startswith("55")

    def test_invalid_phone_creates_failed_log_and_returns_false(self):
        atend = self._make_atendimento(telefone="123")
        service = WhatsAppSendService()
        result = service.send_for_atendimento(atend)
        assert result is False
        log = EnvioWhatsAppLog.objects.filter(atendimento=atend).first()
        assert log is not None
        assert log.sucesso is False
        assert log.status_retorno == "TELEFONE_INVALIDO"

    def test_invalid_phone_does_not_change_status(self):
        atend = self._make_atendimento(telefone="999")
        service = WhatsAppSendService()
        service.send_for_atendimento(atend)
        atend.refresh_from_db()
        assert atend.status_enviado == "N"

    def test_provider_failure_creates_failed_log(self):
        atend = self._make_atendimento()
        mock_provider = MagicMock()
        mock_provider.send_message.return_value = WhatsAppSendResult(
            success=False, status="HTTP_ERROR", code="500", detail="Internal Server Error"
        )
        service = WhatsAppSendService()
        service.provider = mock_provider
        result = service.send_for_atendimento(atend)
        assert result is False
        log = EnvioWhatsAppLog.objects.filter(atendimento=atend).first()
        assert log.sucesso is False
        assert log.codigo_retorno == "500"

    def test_phone_normalised_before_send(self):
        """Raw phone '(92) 99999-9999' must be normalised to '5592999999999'."""
        atend = self._make_atendimento(telefone="(92) 99999-9999")
        service = WhatsAppSendService()
        service.send_for_atendimento(atend)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atend).first()
        assert log.telefone == "5592999999999"


# ──────────────────────────────────────────────────────────────────────────────
# Celery task — unit (no real Celery broker)
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(WHATSAPP_PROVIDER="fake", DEFAULT_COUNTRY_CODE="55")
class CeleryTaskTest(TestCase):
    def _make_atendimento(self, status="N"):
        situacao, _ = SituacaoAtendimento.objects.get_or_create(nome="Agendado")
        return Atendimento.objects.create(
            situacao=situacao,
            paciente="Celery Paciente",
            telefone="92999999999",
            exame_procedimento="TSH",
            status_enviado=status,
        )

    def test_task_returns_true_for_nonexistent_id(self):
        # Non-existent ID is treated as "already handled" → True (no retry)
        from whatsapp.tasks import send_whatsapp_for_atendimento
        result = send_whatsapp_for_atendimento.run(99999999)
        assert result is True

    def test_task_skips_already_sent(self):
        from whatsapp.tasks import send_whatsapp_for_atendimento
        atend = self._make_atendimento(status="S")
        result = send_whatsapp_for_atendimento.run(atend.pk)
        assert result is True
        # No new log should be created for an already-sent atendimento
        assert EnvioWhatsAppLog.objects.filter(atendimento=atend).count() == 0

    def test_task_sends_pending_atendimento(self):
        from whatsapp.tasks import send_whatsapp_for_atendimento
        atend = self._make_atendimento(status="N")
        result = send_whatsapp_for_atendimento.run(atend.pk)
        assert result is True
        atend.refresh_from_db()
        assert atend.status_enviado == "S"

    def test_task_sends_enfileirado_atendimento(self):
        """Task must also process status='E' (Enfileirado by send_panel)."""
        from whatsapp.tasks import send_whatsapp_for_atendimento
        atend = self._make_atendimento(status="E")
        result = send_whatsapp_for_atendimento.run(atend.pk)
        assert result is True
        atend.refresh_from_db()
        assert atend.status_enviado == "S"

    def test_task_idempotent_on_double_call(self):
        """Calling the task twice on the same atendimento must not double-log."""
        from whatsapp.tasks import send_whatsapp_for_atendimento
        atend = self._make_atendimento(status="N")
        send_whatsapp_for_atendimento.run(atend.pk)
        send_whatsapp_for_atendimento.run(atend.pk)
        log_count = EnvioWhatsAppLog.objects.filter(atendimento=atend).count()
        # First call creates 1 log; second call is skipped (already "S")
        assert log_count == 1
