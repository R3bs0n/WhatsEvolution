"""Tests for whatsapp/views.py — send_panel double-click protection and rate limiting."""
import pytest
from unittest.mock import patch, call
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from atendimentos.models import Atendimento, SituacaoAtendimento
from core.tenant_context import set_session_tenant
from empresas.models import Empresa, MembroEmpresa
from whatsapp.services.message_builder import build_message

from .auth_helpers import login_with_2fa


def _make_situacao(empresa):
    set_session_tenant(empresa.pk)
    obj, _ = SituacaoAtendimento.objects.get_or_create(nome="Agendado", empresa=empresa)
    return obj


def _make_atendimento(empresa, n=1, status="N"):
    situacao = _make_situacao(empresa)
    return [
        Atendimento.objects.create(
            empresa=empresa,
            situacao=situacao,
            paciente=f"Paciente {i}",
            telefone=f"559200000{i:04d}",
            exame_procedimento="Hemograma",
            status_enviado=status,
        )
        for i in range(n)
    ]


class SendPanelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op", password="pass")
        self.empresa = Empresa.objects.create(nome="Empresa Teste", slug="empresa-teste")
        MembroEmpresa.objects.create(usuario=self.user, empresa=self.empresa, papel="operador")
        self.client = Client()
        login_with_2fa(self.client, self.user, "pass")

    def test_get_returns_200(self):
        response = self.client.get(reverse("whatsapp-send"))
        assert response.status_code == 200

    def test_post_no_pending_shows_warning(self):
        response = self.client.post(reverse("whatsapp-send"))
        assert response.status_code == 200

    def test_post_marks_atendimentos_as_enfileirado(self):
        records = _make_atendimento(self.empresa, 3)
        with patch("whatsapp.views.send_whatsapp_for_atendimento") as mock_task:
            mock_task.apply_async = lambda args, countdown: None
            self.client.post(reverse("whatsapp-send"))

        # TenantMiddleware reseta o tenant no finally ao fim da request.
        set_session_tenant(self.empresa.pk)
        for r in records:
            r.refresh_from_db()
            assert r.status_enviado == "E"

    def test_double_click_does_not_re_enqueue_same_records(self):
        """Second POST must not re-enqueue records already marked 'E'."""
        _make_atendimento(self.empresa, 5)
        dispatched_ids = []

        def fake_apply_async(args, countdown):
            dispatched_ids.append(args[0])

        with patch("whatsapp.views.send_whatsapp_for_atendimento") as mock_task:
            mock_task.apply_async = fake_apply_async
            self.client.post(reverse("whatsapp-send"))  # first click
            first_count = len(dispatched_ids)

        dispatched_ids_second = []

        def fake_apply_async2(args, countdown):
            dispatched_ids_second.append(args[0])

        with patch("whatsapp.views.send_whatsapp_for_atendimento") as mock_task2:
            mock_task2.apply_async = fake_apply_async2
            self.client.post(reverse("whatsapp-send"))  # second click

        # First click dispatched 5; second click must dispatch 0 (all are "E")
        assert first_count == 5
        assert len(dispatched_ids_second) == 0

    def test_rate_limiting_uses_countdown(self):
        """Each task must have countdown = index * _MSG_DELAY_SECONDS."""
        _make_atendimento(self.empresa, 3)
        countdowns = []

        def fake_apply_async(args, countdown):
            countdowns.append(countdown)

        with patch("whatsapp.views.send_whatsapp_for_atendimento") as mock_task:
            mock_task.apply_async = fake_apply_async
            self.client.post(reverse("whatsapp-send"))

        assert countdowns == [0, 3, 6]  # 0s, 3s, 6s


class MessageBuilderConfigurableTest(TestCase):
    def test_default_template_uses_contact_url_setting(self):
        with override_settings(WHATSAPP_CONTACT_URL="https://wa.me/TEST"):
            msg = build_message("Ana", "TSH")
        assert "https://wa.me/TEST" in msg

    def test_custom_template_from_settings(self):
        custom = "Oi {nome_paciente}, seu exame {tipo_exame} está pronto. {contato_url}"
        with override_settings(WHATSAPP_MESSAGE_TEMPLATE=custom, WHATSAPP_CONTACT_URL="http://x"):
            msg = build_message("João", "Hemograma")
        assert msg == "Oi João, seu exame Hemograma está pronto. http://x"

    def test_empty_template_setting_uses_default(self):
        with override_settings(WHATSAPP_MESSAGE_TEMPLATE=""):
            msg = build_message("Maria", "Glicemia")
        # Deve conter o texto padrão
        assert "Maria" in msg
        assert "Glicemia" in msg

    def test_fallback_for_empty_name_in_custom_template(self):
        custom = "Olá {nome_paciente}, exame: {tipo_exame}. {contato_url}"
        with override_settings(WHATSAPP_MESSAGE_TEMPLATE=custom, WHATSAPP_CONTACT_URL="http://x"):
            msg = build_message("", "TSH")
        assert "Paciente" in msg

    def test_contact_url_not_hardcoded(self):
        """The default message must read WHATSAPP_CONTACT_URL from settings, not hardcode."""
        with override_settings(WHATSAPP_CONTACT_URL="https://custom.url/contato"):
            msg = build_message("Carlos", "PCR")
        assert "https://custom.url/contato" in msg
        assert "5548988762025" not in msg
