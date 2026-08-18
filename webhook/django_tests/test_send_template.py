"""Testes do envio por TEMPLATE (Cloud API oficial via Evolution).

Camadas testadas separadamente (recomendação do Codex na revisão da Etapa 1):
1. Montagem pura de `components` (sem rede/banco) — template_registry.py
2. EvolutionClient.send_template — mocka só o transporte HTTP
3. EvolutionWhatsAppProvider.send_template — mocka o client, testa a checagem
   defensiva de resposta (a Evolution não lança exceção em erro da Meta)
4. WhatsAppSendService.send_template_for_atendimento — provider fake,
   valida seleção de canal/credencial/tenant e que o token NUNCA é decifrado

Nenhum teste aqui alega envio real contra a Meta — não existe canal
WHATSAPP-BUSINESS real hoje (ver relatório da investigação).
"""
from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase

from atendimentos.models import Atendimento, SituacaoAtendimento
from core.tenant_context import session_tenant_context, set_session_tenant
from empresas.models import Empresa
from whatsapp.models import CanalWhatsApp, ContatoBloqueado, EnvioWhatsAppLog, MetaCloudCredential
from whatsapp.services.evolution_provider import EvolutionWhatsAppProvider
from whatsapp.services.fake_provider import FakeWhatsAppProvider
from whatsapp.services.providers import WhatsAppSendResult
from whatsapp.services.sender import WhatsAppSendService
from whatsapp.services.template_registry import TemplateVariableError, build_template_components

PLAINTEXT_TOKEN = "EAAG-token-de-teste-nao-real-1234567890"


def _make_empresa(nome="Empresa Template", slug="empresa-template"):
    return Empresa.objects.create(nome=nome, slug=slug)


def _make_canal_business(empresa, instance_name="canal-template-teste", **extra):
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


class BuildTemplateComponentsTests(TestCase):
    """Sem DB nem rede — só a lógica de mapeamento posicional."""

    def test_builds_components_in_correct_order_for_confirmacao_sus(self):
        components = build_template_components(
            "confirmacao_sus", "pt_BR",
            {"nome_paciente": "Maria da Silva", "tipo_exame": "Hemograma"},
        )
        self.assertEqual(components, [
            {"type": "body", "parameters": [
                {"type": "text", "text": "Maria da Silva"},
                {"type": "text", "text": "Hemograma"},
            ]},
        ])

    def test_order_is_positional_not_alphabetical_or_insertion(self):
        # tipo_exame inserido ANTES de nome_paciente no dict — a ordem do
        # resultado tem que seguir o registro (nome_paciente={{1}} sempre),
        # não a ordem de inserção do dict nem ordem alfabética.
        components = build_template_components(
            "confirmacao_sus", "pt_BR",
            {"tipo_exame": "TSH", "nome_paciente": "João"},
        )
        parametros = components[0]["parameters"]
        self.assertEqual(parametros[0]["text"], "João")
        self.assertEqual(parametros[1]["text"], "TSH")

    def test_raises_clear_error_when_variable_missing(self):
        with self.assertRaises(TemplateVariableError) as ctx:
            build_template_components("confirmacao_sus", "pt_BR", {"nome_paciente": "Maria"})
        self.assertIn("tipo_exame", str(ctx.exception))

    def test_raises_for_unregistered_template(self):
        with self.assertRaises(TemplateVariableError):
            build_template_components("template_inexistente", "pt_BR", {})

    def test_raises_for_wrong_language_of_known_template(self):
        with self.assertRaises(TemplateVariableError):
            build_template_components("confirmacao_sus", "en_US", {"nome_paciente": "x", "tipo_exame": "y"})

    def test_does_not_mutate_input_dict(self):
        variaveis = {"nome_paciente": "Maria", "tipo_exame": "TSH"}
        original = dict(variaveis)
        build_template_components("confirmacao_sus", "pt_BR", variaveis)
        self.assertEqual(variaveis, original)


class EvolutionClientSendTemplateTests(TestCase):
    """Mocka só o transporte HTTP — confirma URL/payload exatos."""

    def test_posts_to_correct_url_with_exact_payload(self):
        from core.integrations.evolution.client import EvolutionClient

        client = EvolutionClient(instance_name="minha-instancia", api_url="http://evolution:8080")
        components = [{"type": "body", "parameters": [{"type": "text", "text": "x"}]}]

        fake_response = MagicMock()
        fake_response.json.return_value = {"key": {"id": "wamid.ABC123"}}
        fake_response.raise_for_status.return_value = None

        with patch("httpx.Client.post", return_value=fake_response) as mock_post:
            result = client.send_template("5511999999999", "confirmacao_sus", "pt_BR", components)

        self.assertEqual(result, {"key": {"id": "wamid.ABC123"}})
        called_url = mock_post.call_args.args[0]
        called_kwargs = mock_post.call_args.kwargs
        self.assertEqual(called_url, "http://evolution:8080/message/sendTemplate/minha-instancia")
        self.assertEqual(called_kwargs["json"], {
            "number": "5511999999999", "name": "confirmacao_sus",
            "language": "pt_BR", "components": components,
        })
        self.assertIn("apikey", called_kwargs["headers"])


class EvolutionWhatsAppProviderSendTemplateTests(TestCase):
    """A Evolution não lança exceção em erro da Meta (confirmado lendo o
    código-fonte dela) — o provider precisa detectar isso sozinho, checando
    se veio um message id de verdade."""

    def _provider(self):
        return EvolutionWhatsAppProvider(instance_name="teste", api_url="http://evolution:8080")

    def test_success_when_response_has_real_message_id(self):
        provider = self._provider()
        with patch.object(provider._client, "send_template", return_value={"key": {"id": "wamid.XYZ"}}):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])
        self.assertTrue(resultado.success)
        self.assertEqual(resultado.external_message_id, "wamid.XYZ")

    def test_failure_when_response_has_no_message_id(self):
        """Simula o caso real encontrado no código da Evolution: erro de
        rede/Meta vira um retorno "vazio" ou parcial, sem lançar exceção."""
        provider = self._provider()
        with patch.object(provider._client, "send_template", return_value={"key": {"id": None}}):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])
        self.assertFalse(resultado.success)
        self.assertEqual(resultado.status, "RESPOSTA_SEM_MESSAGE_ID")

    def test_failure_when_response_is_none(self):
        provider = self._provider()
        with patch.object(provider._client, "send_template", return_value=None):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])
        self.assertFalse(resultado.success)

    def test_http_error_returns_failure_result(self):
        provider = self._provider()
        request = httpx.Request("POST", "http://evolution:8080/message/sendTemplate/teste")
        response = httpx.Response(400, request=request, json={"error": "template not approved"})
        with patch.object(
            provider._client, "send_template",
            side_effect=httpx.HTTPStatusError("bad request", request=request, response=response),
        ):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])
        self.assertFalse(resultado.success)
        self.assertEqual(resultado.status, "HTTP_ERROR")
        self.assertEqual(resultado.code, "400")

    def test_http_error_body_echoing_token_never_reaches_detail(self):
        """Achado do Codex na revisão do módulo de envio unitário: o `detail`
        persistido em EnvioWhatsAppLog vem direto do que este provider
        devolve. Se a Evolution/Meta ecoasse o token que acabamos de enviar
        no corpo de um erro HTTP (payload inválido, etc.), a versão antiga
        gravava `exc.response.text[:500]` cru -- vazamento real. Simula
        exatamente esse corpo e confirma que `detail` nunca contém o token,
        só o status code."""
        provider = self._provider()
        token_que_acabamos_de_enviar = "EAAG-token-real-nao-deve-vazar-1234567890"
        request = httpx.Request("POST", "http://evolution:8080/message/sendTemplate/teste")
        response = httpx.Response(
            400, request=request,
            json={"error": f"invalid parameter, payload was: token={token_que_acabamos_de_enviar}"},
        )
        with patch.object(
            provider._client, "send_template",
            side_effect=httpx.HTTPStatusError("bad request", request=request, response=response),
        ):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])

        self.assertFalse(resultado.success)
        self.assertNotIn(token_que_acabamos_de_enviar, resultado.detail)
        self.assertEqual(resultado.detail, "Evolution recusou o envio do template (HTTP 400).")

    def test_response_without_message_id_echoing_token_never_reaches_detail(self):
        """Mesmo achado, pro caminho 'resposta sem message id' -- a versão
        antiga gravava `str(raw)[:500]` cru, e a Evolution devolve o token
        em texto puro em outros endpoints dela (fetchInstances, confirmado
        ao vivo em sessão anterior) -- não dá pra confiar que este nunca
        ecoaria algo sensível também."""
        provider = self._provider()
        token_que_acabamos_de_enviar = "EAAG-token-real-nao-deve-vazar-9876543210"
        resposta_suspeita = {"key": {"id": None}, "debug": {"token_usado": token_que_acabamos_de_enviar}}
        with patch.object(provider._client, "send_template", return_value=resposta_suspeita):
            resultado = provider.send_template("5511999999999", "confirmacao_sus", "pt_BR", [])

        self.assertFalse(resultado.success)
        self.assertNotIn(token_que_acabamos_de_enviar, resultado.detail)
        self.assertEqual(resultado.status, "RESPOSTA_SEM_MESSAGE_ID")


class WhatsAppSendServiceSendTemplateTests(TestCase):
    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(lambda: set_session_tenant(None))

    def test_success_path_creates_log_and_updates_status(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atendimento = _make_atendimento(self.empresa)

        provider = FakeWhatsAppProvider()
        service = WhatsAppSendService(provider=provider)
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertTrue(ok)
        atendimento.refresh_from_db()
        self.assertEqual(atendimento.status_enviado, "S")

        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertIsNotNone(log)
        self.assertTrue(log.sucesso)
        self.assertEqual(log.tipo_envio, "template")
        self.assertEqual(log.template_nome, "confirmacao_sus")
        self.assertTrue(log.external_message_id)

    def test_blocks_when_canal_is_baileys_not_business(self):
        CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Canal Baileys", instance_name="canal-baileys-tpl",
            principal=True, ativo=True,
        )  # provider default = WHATSAPP-BAILEYS
        atendimento = _make_atendimento(self.empresa)

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "CANAL_NAO_BUSINESS")

    def test_blocks_when_no_credential_configured(self):
        _make_canal_business(self.empresa)  # sem MetaCloudCredential nenhuma
        atendimento = _make_atendimento(self.empresa)

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "CREDENCIAL_NAO_CONFIGURADA")

    def test_blocks_when_credential_status_is_pendente(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa, status=MetaCloudCredential.STATUS_PENDENTE)
        atendimento = _make_atendimento(self.empresa)

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "CREDENCIAL_NAO_CONFIGURADA")

    def test_blocks_when_required_variable_is_missing(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atendimento = _make_atendimento(self.empresa, exame="")  # tipo_exame vazio -> falta

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "VARIAVEL_FALTANDO")

    def test_blocks_when_phone_is_opted_out(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atendimento = _make_atendimento(self.empresa, telefone="92988887777")
        ContatoBloqueado.objects.create(empresa=self.empresa, telefone="5592988887777")

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "BLOQUEADO")

    def test_token_is_never_decrypted_even_if_corrupted(self):
        """Prova que o fluxo de envio NUNCA acessa .meta_access_token: grava
        um token CORROMPIDO direto no banco (que levantaria TokenDecryptionError
        se alguém tentasse decifrar) e confirma que o envio ainda funciona."""
        from django.db import connection

        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE whatsapp_metacloudcredential SET meta_access_token = %s WHERE id = %s",
                ["v1:isso-nao-e-um-token-fernet-valido", credencial.pk],
            )

        atendimento = _make_atendimento(self.empresa)
        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        # Se o código tentasse ler/decifrar o token em algum ponto, isso
        # levantaria TokenDecryptionError e o teste falharia aqui.
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")
        self.assertTrue(ok)

    def test_token_never_appears_in_log(self):
        canal = _make_canal_business(self.empresa)
        _make_credencial(canal, self.empresa)
        atendimento = _make_atendimento(self.empresa)

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        for campo in (log.mensagem, log.detalhe_retorno, log.status_retorno, log.codigo_retorno):
            self.assertNotIn(PLAINTEXT_TOKEN, campo)

    def test_uses_the_correct_tenant_canal_not_another_empresa(self):
        outra_empresa = _make_empresa("Outra Empresa Template", "outra-empresa-template")
        with session_tenant_context(outra_empresa.pk):
            canal_outra = _make_canal_business(outra_empresa, "canal-outra-empresa-tpl")
            _make_credencial(canal_outra, outra_empresa)

        # Empresa principal NÃO tem canal Business nenhum -- não pode
        # acidentalmente usar o canal/credencial da outra empresa.
        atendimento = _make_atendimento(self.empresa)
        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_template_for_atendimento(atendimento, "confirmacao_sus", "pt_BR")

        self.assertFalse(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.status_retorno, "CANAL_NAO_BUSINESS")

    def test_does_not_break_existing_free_text_send(self):
        """send_for_atendimento (texto livre) continua funcionando -- não
        foi quebrado pela adição do send_template."""
        _make_canal_business(self.empresa)  # nem precisa de credencial pro texto livre
        atendimento = _make_atendimento(self.empresa)

        service = WhatsAppSendService(provider=FakeWhatsAppProvider())
        ok = service.send_for_atendimento(atendimento)

        self.assertTrue(ok)
        log = EnvioWhatsAppLog.objects.filter(atendimento=atendimento).first()
        self.assertEqual(log.tipo_envio, "texto")
