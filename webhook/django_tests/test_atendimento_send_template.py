"""Testes da tela de envio UNITÁRIO de template oficial (Cloud API) a partir
do detalhe de um Atendimento (`atendimentos/views.py::atendimento_send_template`).

Escopo testado: só o envio unitário explícito (aprovado com skill de
arquitetura + Codex, 2026-08-18) — nunca em massa, nunca em save()/signal,
nunca via texto livre. Cobre: pré-visualização (canal/credencial/parâmetros),
recusa explícita quando faltar pré-condição, prevenção de disparo duplicado
via lock, e que o token/segredo nunca aparece na página nem na mensagem.
"""
from unittest.mock import MagicMock, patch

import redis
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from atendimentos.models import Atendimento, SituacaoAtendimento
from core.tenant_context import set_session_tenant
from empresas.models import Empresa, MembroEmpresa
from whatsapp.models import CanalWhatsApp, EnvioWhatsAppLog, MetaCloudCredential
from whatsapp.services.sender import WhatsAppSendService

from .auth_helpers import login_with_2fa

PLAINTEXT_TOKEN = "EAAG-token-de-teste-nao-real-1234567890"


def _make_empresa(nome="Empresa Envio Unitario", slug="empresa-envio-unitario"):
    return Empresa.objects.create(nome=nome, slug=slug)


def _make_canal_business(empresa, instance_name="canal-envio-unitario", **extra):
    extra.setdefault("principal", True)
    extra.setdefault("ativo", True)
    return CanalWhatsApp.objects.create(
        empresa=empresa, nome="Canal Business", instance_name=instance_name,
        provider=CanalWhatsApp.PROVIDER_BUSINESS, **extra,
    )


def _make_credencial(canal, empresa, status=MetaCloudCredential.STATUS_CONFIGURADO, token=PLAINTEXT_TOKEN):
    return MetaCloudCredential.objects.create(
        canal=canal, empresa=empresa, waba_id="123", phone_number_id="456",
        meta_access_token=token, status=status,
    )


def _make_atendimento(empresa, telefone="92999999999", paciente="Maria Teste", exame="Hemograma"):
    situacao, _ = SituacaoAtendimento.objects.get_or_create(nome="Agendado", empresa=empresa)
    return Atendimento.objects.create(
        empresa=empresa, situacao=situacao, paciente=paciente,
        telefone=telefone, exame_procedimento=exame, status_enviado="N",
    )


class AuthenticatedTestCase(TestCase):
    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(lambda: set_session_tenant(None))
        self.user = User.objects.create_user(username="operador-envio", password="pass123")
        MembroEmpresa.objects.create(usuario=self.user, empresa=self.empresa, papel="operador")
        self.client = Client()
        login_with_2fa(self.client, self.user, "pass123")


class SendTemplatePreviewTests(AuthenticatedTestCase):
    """GET — pré-visualização, sem disparar nada."""

    def test_shows_canal_credencial_e_parametros_quando_tudo_configurado(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa, paciente="João Marcos", exame="Radiografia de tórax")

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "João Marcos")
        self.assertContains(response, "Radiografia de tórax")
        self.assertContains(response, "confirmacao_sus")
        self.assertContains(response, "Canal Business")
        self.assertContains(response, "Configurada")
        # botão habilitado -- nao deve conter "disabled" perto do botao enviar
        self.assertNotContains(response, 'id="btn-enviar-template" class="btn btn-success" disabled')

    def test_telefone_aparece_mascarado_nunca_completo(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa, telefone="92999998888")

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertNotContains(response, "92999998888")

    def test_token_nunca_aparece_na_pagina(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa, token=PLAINTEXT_TOKEN)
        atend = _make_atendimento(self.empresa)

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertNotContains(response, PLAINTEXT_TOKEN)

    def test_bloqueia_quando_canal_e_baileys_nao_business(self):
        CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Canal Baileys", instance_name="canal-baileys-envio",
            principal=True, ativo=True,
        )  # provider default = WHATSAPP-BAILEYS
        atend = _make_atendimento(self.empresa)

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Envio bloqueado")
        self.assertContains(response, "WHATSAPP-BUSINESS")
        self.assertContains(response, 'disabled')

    def test_bloqueia_quando_nao_ha_canal_nenhum(self):
        atend = _make_atendimento(self.empresa)

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertContains(response, "Envio bloqueado")

    def test_bloqueia_quando_credencial_nao_configurada(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa, status=MetaCloudCredential.STATUS_PENDENTE)
        atend = _make_atendimento(self.empresa)

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertContains(response, "Envio bloqueado")
        self.assertContains(response, "Credencial")

    def test_bloqueia_e_mostra_faltando_quando_atendimento_sem_exame(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa, exame="")

        response = self.client.get(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertContains(response, "Envio bloqueado")
        self.assertContains(response, "faltando")


class SendTemplatePostTests(AuthenticatedTestCase):
    """POST — disparo explícito, sempre mockando o service (nunca rede real)."""

    def test_post_bem_sucedido_chama_service_e_redireciona_pro_detalhe(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento", return_value=True) as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "confirmacao_sus::pt_BR"},
            )

        mock_send.assert_called_once()
        args, _kwargs = mock_send.call_args
        self.assertEqual(args[0].pk, atend.pk)
        self.assertEqual(args[1], "confirmacao_sus")
        self.assertRedirects(response, reverse("atendimento-detail", kwargs={"pk": atend.pk}))

    def test_post_recusado_quando_falta_pre_condicao_nunca_chama_service(self):
        # sem canal nenhum -- recusa antes de chegar no service
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "confirmacao_sus::pt_BR"},
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_rejeita_template_name_nao_registrado_mesmo_com_canal_ok(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "template-inventado-no-post::pt_BR"},
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_sem_template_choice_nunca_cai_no_padrao_silenciosamente(self):
        """Achado do Codex na 3ª rodada: um POST sem o campo (ou vazio, ou
        sem "::") não pode acabar enviando o template padrão como se fosse
        uma escolha real -- só o GET (carga inicial da tela) tem esse
        fallback. Um POST forjado sem o campo tem que ser recusado."""
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}), {},
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_com_template_choice_sem_separador_e_recusado(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "confirmacao_sus-sem-separador"},
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_com_lock_ja_adquirido_nao_chama_service_duas_vezes(self):
        """Simula o cenário de clique duplo: um lock já detido pra este
        atendimento -- a segunda tentativa deve recusar, não enviar de novo."""
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        from django.conf import settings as dj_settings

        lock_key = f"atendimento-send-template-lock:{atend.pk}"
        redis_client = redis.Redis.from_url(dj_settings.REDIS_URL)
        redis_client.set(lock_key, "outro-processo", nx=True, ex=30)
        self.addCleanup(redis_client.delete, lock_key)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "confirmacao_sus::pt_BR"},
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_falha_do_service_mostra_mensagem_sem_expor_token(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa, token=PLAINTEXT_TOKEN)
        atend = _make_atendimento(self.empresa)

        with patch.object(WhatsAppSendService, "send_template_for_atendimento", return_value=False):
            response = self.client.post(
                reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                {"template_choice": "confirmacao_sus::pt_BR"},
                follow=True,
            )

        self.assertNotIn(PLAINTEXT_TOKEN.encode(), response.content)

    def test_post_falha_real_do_provider_com_token_ecoado_no_erro_http_nunca_vaza(self):
        """Achado do Codex na revisão (2ª rodada): a 1ª versão deste teste
        mockava o service inteiro E o stub nunca tentava ecoar o token de
        verdade, então a asserção "sem token" era trivial. Esta versão vai
        até o EvolutionWhatsAppProvider REAL (só o transporte HTTP mais
        baixo -- EvolutionClient.send_template -- é substituído por um erro
        HTTP cujo corpo ECOA o token, simulando o pior caso real) e confirma
        que a sanitização em evolution_provider.py (corrigida na mesma
        rodada: nunca mais persiste exc.response.text/raw cru) segura o
        vazamento antes dele chegar no EnvioWhatsAppLog ou na página."""
        import httpx

        from whatsapp.services.evolution_provider import EvolutionWhatsAppProvider

        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa, token=PLAINTEXT_TOKEN)
        atend = _make_atendimento(self.empresa)

        provider_real = EvolutionWhatsAppProvider(instance_name=canal.instance_name, api_url=canal.api_url)
        request = httpx.Request("POST", "http://evolution:8080/message/sendTemplate/x")
        response_http_evolution = httpx.Response(
            400, request=request, json={"error": f"payload invalido, token={PLAINTEXT_TOKEN}"},
        )

        with patch.object(
            provider_real._client, "send_template",
            side_effect=httpx.HTTPStatusError("bad request", request=request, response=response_http_evolution),
        ):
            with patch("whatsapp.services.sender.get_provider", return_value=provider_real):
                response = self.client.post(
                    reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                    {"template_choice": "confirmacao_sus::pt_BR"},
                    follow=True,
                )

        # TenantMiddleware reseta app.current_tenant no finally ao fim de
        # CADA request (mesma conexão do processo de teste) -- reconfigura
        # antes de consultar de novo fora do ciclo de request.
        set_session_tenant(self.empresa.pk)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atend).first()
        self.assertIsNotNone(log, "a view deveria ter acionado o service de verdade e persistido um log")
        self.assertFalse(log.sucesso)
        self.assertEqual(log.status_retorno, "HTTP_ERROR")
        self.assertNotIn(PLAINTEXT_TOKEN, log.detalhe_retorno)
        self.assertNotIn(PLAINTEXT_TOKEN.encode(), response.content)
        self.assertContains(response, "HTTP_ERROR")

    def test_post_redis_error_no_acquire_e_sanitizado_nao_derruba_a_view(self):
        """Achado do Codex: lock.acquire() sem tratar RedisError vira 500 cru
        se o Redis cair. Confirma que agora vira mensagem sanitizada + redirect."""
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        broken_lock = MagicMock()
        broken_lock.acquire.side_effect = redis.exceptions.ConnectionError("redis fora do ar (teste)")
        broken_client = MagicMock()
        broken_client.lock.return_value = broken_lock

        with patch("atendimentos.views.redis.Redis.from_url", return_value=broken_client):
            with patch.object(WhatsAppSendService, "send_template_for_atendimento") as mock_send:
                response = self.client.post(
                    reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                    {"template_choice": "confirmacao_sus::pt_BR"},
                )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_post_redis_error_no_release_nao_esconde_envio_bem_sucedido(self):
        """Achado do Codex: se o release() falhar por erro de conexão (não
        por perda de ownership), o resultado do envio -- que já aconteceu --
        não pode virar um 500 cru que confunda o operador e arrisque um
        segundo clique/envio duplicado."""
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        broken_lock = MagicMock()
        broken_lock.acquire.return_value = True
        broken_lock.release.side_effect = redis.exceptions.ConnectionError("redis caiu no release (teste)")
        broken_client = MagicMock()
        broken_client.lock.return_value = broken_lock

        with patch("atendimentos.views.redis.Redis.from_url", return_value=broken_client):
            with patch.object(WhatsAppSendService, "send_template_for_atendimento", return_value=True) as mock_send:
                response = self.client.post(
                    reverse("atendimento-send-template", kwargs={"pk": atend.pk}),
                    {"template_choice": "confirmacao_sus::pt_BR"},
                )

        mock_send.assert_called_once()
        self.assertRedirects(response, reverse("atendimento-detail", kwargs={"pk": atend.pk}))

    def test_disparo_em_massa_via_texto_livre_continua_intocado(self):
        """Confirma que a view nova não interferiu no fluxo existente de
        texto livre em massa -- rota e nome continuam os mesmos."""
        self.assertEqual(reverse("atendimento-dispatch"), "/atendimentos/disparar/")

    def test_get_ou_post_apenas__outros_metodos_recusados(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atend = _make_atendimento(self.empresa)

        response = self.client.delete(reverse("atendimento-send-template", kwargs={"pk": atend.pk}))

        self.assertEqual(response.status_code, 405)


class TemplateMensagemLabelTests(TestCase):
    """Confirma o ajuste de rótulo (não remoção) do model legado."""

    def test_verbose_name_desambiguado(self):
        from whatsapp.models import TemplateMensagem

        self.assertEqual(
            TemplateMensagem._meta.verbose_name,
            "Mensagem de texto da campanha (legado/Baileys)",
        )

    def test_model_e_tabela_continuam_intactos(self):
        # Nenhuma remoção real -- só rótulo. Confirma que o model ainda
        # aceita criação normal (campanhas continua funcional).
        from whatsapp.models import TemplateMensagem

        empresa = _make_empresa(nome="Empresa Campanha Legado", slug="empresa-campanha-legado")
        set_session_tenant(empresa.pk)
        obj = TemplateMensagem.objects.create(
            empresa=empresa, nome="Promo teste", categoria="promocional",
            corpo="Olá {nome}!",
        )
        self.assertEqual(obj.renderizar({"nome": "Fulano"}), "Olá Fulano!")
