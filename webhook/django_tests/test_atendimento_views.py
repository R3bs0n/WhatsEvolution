"""Tests for atendimentos views — list, detail, create, delete, CSV export."""
import pytest
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from atendimentos.models import Atendimento, SituacaoAtendimento
from empresas.models import Empresa, MembroEmpresa


def _make_empresa():
    return Empresa.objects.get_or_create(
        slug="empresa-teste",
        defaults={"nome": "Empresa Teste"},
    )[0]


def _make_situacao(nome="Agendado", empresa=None):
    empresa = empresa or _make_empresa()
    obj, _ = SituacaoAtendimento.objects.get_or_create(nome=nome, empresa=empresa)
    return obj


def _make_atendimento(**kwargs):
    empresa = kwargs.pop("empresa", None) or _make_empresa()
    defaults = dict(
        empresa=empresa,
        situacao=_make_situacao(empresa=empresa),
        paciente="Fulano da Silva",
        telefone="92999999999",
        exame_procedimento="Hemograma",
        status_enviado="N",
    )
    defaults.update(kwargs)
    return Atendimento.objects.create(**defaults)


class AuthenticatedTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass123")
        self.empresa = _make_empresa()
        MembroEmpresa.objects.create(usuario=self.user, empresa=self.empresa, papel="operador")
        self.client = Client()
        self.client.login(username="testuser", password="pass123")


class AtendimentoListTest(AuthenticatedTestCase):
    def test_list_returns_200(self):
        _make_atendimento()
        response = self.client.get(reverse("atendimento-list"))
        assert response.status_code == 200

    def test_unauthenticated_redirects_to_login(self):
        anon = Client()
        response = anon.get(reverse("atendimento-list"))
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_search_by_paciente(self):
        _make_atendimento(paciente="Maria Especial")
        _make_atendimento(paciente="João Comum")
        response = self.client.get(reverse("atendimento-list"), {"q": "Especial"})
        assert response.status_code == 200
        assert b"Maria Especial" in response.content
        assert b"Jo" not in response.content or b"Comum" not in response.content

    def test_filter_by_status_N(self):
        _make_atendimento(status_enviado="N")
        _make_atendimento(status_enviado="S")
        response = self.client.get(reverse("atendimento-list"), {"status": "N"})
        assert response.status_code == 200

    def test_filter_by_status_S(self):
        _make_atendimento(status_enviado="S")
        response = self.client.get(reverse("atendimento-list"), {"status": "S"})
        assert response.status_code == 200


class AtendimentoDetailTest(AuthenticatedTestCase):
    def test_detail_returns_200(self):
        atend = _make_atendimento()
        response = self.client.get(reverse("atendimento-detail", kwargs={"pk": atend.pk}))
        assert response.status_code == 200

    def test_detail_404_for_nonexistent(self):
        response = self.client.get(reverse("atendimento-detail", kwargs={"pk": 99999}))
        assert response.status_code == 404


class AtendimentoDeleteTest(AuthenticatedTestCase):
    def test_delete_post_removes_record(self):
        atend = _make_atendimento()
        pk = atend.pk
        response = self.client.post(reverse("atendimento-delete", kwargs={"pk": pk}))
        assert response.status_code == 302
        assert not Atendimento.objects.filter(pk=pk).exists()

    def test_delete_get_shows_confirmation_page(self):
        atend = _make_atendimento()
        response = self.client.get(reverse("atendimento-delete", kwargs={"pk": atend.pk}))
        assert response.status_code == 200


class ExportCsvTest(AuthenticatedTestCase):
    def test_csv_export_returns_csv_content_type(self):
        _make_atendimento()
        response = self.client.get(reverse("atendimento-export-csv"))
        assert response.status_code == 200
        assert "text/csv" in response["Content-Type"]

    def test_csv_has_header_row(self):
        response = self.client.get(reverse("atendimento-export-csv"))
        content = response.content.decode("utf-8-sig")
        assert "Paciente" in content
        assert "Telefone" in content

    def test_csv_contains_atendimento_data(self):
        _make_atendimento(paciente="CSV Paciente", telefone="5592111111111")
        response = self.client.get(reverse("atendimento-export-csv"))
        content = response.content.decode("utf-8-sig")
        assert "CSV Paciente" in content


class AtendimentoModelTest(TestCase):
    def test_telefone_normalizado_returns_e164(self):
        atend = _make_atendimento(telefone="(92) 99999-9999")
        assert atend.telefone_normalizado() == "5592999999999"

    def test_telefone_normalizado_returns_raw_on_invalid(self):
        atend = _make_atendimento(telefone="invalido")
        # Should return the raw value without raising
        result = atend.telefone_normalizado()
        assert result == "invalido"

    def test_str_representation(self):
        atend = _make_atendimento(paciente="Ana Lima", exame_procedimento="TSH")
        assert "Ana Lima" in str(atend)
        assert "TSH" in str(atend)
