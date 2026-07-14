from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from atendimentos.models import Atendimento, SituacaoAtendimento
from empresas.models import Empresa, MembroEmpresa


class TenantIsolationTest(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nome="Empresa A", slug="empresa-a")
        self.empresa_b = Empresa.objects.create(nome="Empresa B", slug="empresa-b")
        self.user_a = User.objects.create_user(username="user-a", password="pass")
        MembroEmpresa.objects.create(
            usuario=self.user_a,
            empresa=self.empresa_a,
            papel="operador",
        )
        self.situacao_a = SituacaoAtendimento.objects.create(
            empresa=self.empresa_a,
            nome="Agendado",
        )
        self.situacao_b = SituacaoAtendimento.objects.create(
            empresa=self.empresa_b,
            nome="Agendado",
        )
        self.atendimento_a = Atendimento.objects.create(
            empresa=self.empresa_a,
            situacao=self.situacao_a,
            paciente="Paciente Empresa A",
            telefone="92999999999",
            exame_procedimento="Hemograma",
        )
        self.atendimento_b = Atendimento.objects.create(
            empresa=self.empresa_b,
            situacao=self.situacao_b,
            paciente="Paciente Empresa B",
            telefone="92988888888",
            exame_procedimento="TSH",
        )
        self.client = Client()
        self.client.login(username="user-a", password="pass")

    def test_list_does_not_show_other_tenant_data(self):
        response = self.client.get(reverse("atendimento-list"))
        assert response.status_code == 200
        assert b"Paciente Empresa A" in response.content
        assert b"Paciente Empresa B" not in response.content

    def test_direct_pk_access_to_other_tenant_returns_404(self):
        response = self.client.get(
            reverse("atendimento-detail", kwargs={"pk": self.atendimento_b.pk})
        )
        assert response.status_code == 404
