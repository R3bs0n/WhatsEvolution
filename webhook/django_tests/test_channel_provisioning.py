"""Testes do provisionamento INICIAL do canal WHATSAPP-BUSINESS na Evolution
(whatsapp/services/channel_provisioning.py) -- a "unificação de canal".

Escopo testado: só criação quando não existe instância ainda. Nunca
delete/recreate (fora de escopo desta etapa). Proteções obrigatórias: nunca
tocar em instância que não seja WHATSAPP-BUSINESS (proteção contra atingir a
instância Baileys da clínica), idempotência (não duplica), token só decifrado
no momento exato do uso, trava contra provisionamento concorrente.
"""
from unittest.mock import MagicMock, patch

import httpx
import redis
from django.db import connection
from django.test import TestCase

from core.tenant_context import set_session_tenant
from empresas.models import Empresa
from whatsapp.models import CanalWhatsApp, MetaCloudCredential
from whatsapp.services.channel_provisioning import (
    ChannelProvisioningError,
    _lock_key,
    _redis_client,
    provision_meta_channel,
)

PLAINTEXT_TOKEN = "EAAG-token-de-teste-nao-real-1234567890"


def _make_empresa(nome="Empresa Provisionamento", slug="empresa-provisionamento"):
    return Empresa.objects.create(nome=nome, slug=slug)


def _make_canal_business(empresa, instance_name="canal-provisionamento-teste", **extra):
    extra.setdefault("principal", True)
    extra.setdefault("ativo", True)
    return CanalWhatsApp.objects.create(
        empresa=empresa, nome="Canal Business", instance_name=instance_name,
        provider=CanalWhatsApp.PROVIDER_BUSINESS, **extra,
    )


def _make_credencial(canal, empresa, token=PLAINTEXT_TOKEN, phone_number_id="456", waba_id="123", **extra):
    return MetaCloudCredential.objects.create(
        canal=canal, empresa=empresa, waba_id=waba_id, phone_number_id=phone_number_id,
        meta_access_token=token, **extra,
    )


def _corrupt_stored_token(credencial):
    """Escreve um ciphertext inválido direto via SQL, sem passar pelo campo
    cifrado -- se algum caminho decifrar o token à toa, isso levanta
    TokenDecryptionError na hora de ler, denunciando o vazamento de decifra."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE whatsapp_metacloudcredential SET meta_access_token = %s WHERE id = %s",
            ["v1:isto-nao-e-um-ciphertext-fernet-valido", credencial.pk],
        )


class ProvisionMetaChannelTests(TestCase):
    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(lambda: set_session_tenant(None))

    def _patched_client(self, fetch_return=None, create_return=None, fetch_side_effect=None,
                         create_side_effect=None):
        mock_client = MagicMock()
        if fetch_side_effect is not None:
            mock_client.fetch_instances.side_effect = fetch_side_effect
        else:
            mock_client.fetch_instances.return_value = fetch_return if fetch_return is not None else []
        if create_side_effect is not None:
            mock_client.create_instance.side_effect = create_side_effect
        else:
            mock_client.create_instance.return_value = create_return or {"instance": {"status": "created"}}
        return patch("whatsapp.services.channel_provisioning.EvolutionClient", return_value=mock_client), mock_client

    # ── caminho feliz: cria quando não existe ──────────────────────────────

    def test_provisions_when_no_existing_instance(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            result = provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_called_once_with(
            "canal-provisionamento-teste",
            integration=CanalWhatsApp.PROVIDER_BUSINESS,
            number="456",
            token=PLAINTEXT_TOKEN,
            business_id="123",
        )
        self.assertEqual(result.status, MetaCloudCredential.STATUS_CONFIGURADO)
        self.assertIn("criada", result.detalhe_provisionamento)

    def test_never_passes_client_supplied_url_to_evolution_client(self):
        """EvolutionClient sempre monta a URL a partir de settings -- o
        serviço nunca deve instanciá-lo com api_url vindo de fora (SSRF)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher as mock_cls:
            provision_meta_channel(credencial.pk)

        _args, kwargs = mock_cls.call_args
        self.assertNotIn("api_url", kwargs)

    # ── idempotência: não duplica ───────────────────────────────────────────

    def test_does_not_duplicate_when_number_business_id_and_token_all_match(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "456", "businessId": "123", "token": PLAINTEXT_TOKEN,
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            result = provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        self.assertEqual(result.status, MetaCloudCredential.STATUS_CONFIGURADO)
        self.assertIn("já existe", result.detalhe_provisionamento.lower())

    def test_aborts_when_existing_instance_token_diverges_from_django(self):
        """number/businessId batendo não basta -- sem endpoint de update na
        Evolution, o token de lá pode ter ficado desatualizado em relação ao
        token atual do Django (rotacionado sem reprovisionar). Sem essa
        comparação, o status seria marcado CONFIGURADO incorretamente e a
        Evolution continuaria mandando com o token antigo (achado do Codex
        na segunda revisão)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "456", "businessId": "123", "token": "TOKEN-ANTIGO-DIFERENTE-NA-EVOLUTION",
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertLogs("whatsapp.services.channel_provisioning", level="ERROR") as logs:
                with self.assertRaises(ChannelProvisioningError) as ctx:
                    provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)
        for texto in (str(ctx.exception), credencial.detalhe_provisionamento, *logs.output):
            self.assertNotIn(PLAINTEXT_TOKEN, texto)
            self.assertNotIn("TOKEN-ANTIGO-DIFERENTE-NA-EVOLUTION", texto)

    def test_aborts_when_existing_business_instance_has_different_number_or_business_id(self):
        """Nome + integration batendo não basta -- se number/businessId da
        instância existente não conferem com a credencial, é sinal de que a
        instância pertence a outro tenant/credencial. Nunca adotar
        silenciosamente (achado do Codex na revisão)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, phone_number_id="456", waba_id="123")

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "999-nao-eh-desta-credencial", "businessId": "123",
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)

    def test_aborts_when_existing_business_instance_has_different_business_id_only(self):
        """Mesmo teste acima, mas isolando o campo businessId divergente com
        number igual -- o código compara os dois com `or`, então cada campo
        precisa de um teste próprio provando que sozinho já é suficiente pra
        abortar (achado do Codex: só havia cobertura de number divergente)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, phone_number_id="456", waba_id="123")

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "456", "businessId": "999-nao-eh-desta-credencial",
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)

    def test_token_never_decrypted_when_existing_instance_number_mismatches(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, phone_number_id="456", waba_id="123")
        _corrupt_stored_token(credencial)

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "999-nao-eh-desta-credencial", "businessId": "123",
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)  # não deve levantar TokenDecryptionError

    # ── proteção obrigatória: nunca tocar instância não-Business (Baileys) ──

    def test_never_touches_instance_with_same_name_but_different_integration(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        existing = [{"name": "canal-provisionamento-teste", "integration": "WHATSAPP-BAILEYS"}]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)
        self.assertIn("BAILEYS", credencial.detalhe_provisionamento)

    def test_token_never_decrypted_when_name_collides_with_non_business_instance(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)
        _corrupt_stored_token(credencial)

        existing = [{"name": "canal-provisionamento-teste", "integration": "WHATSAPP-BAILEYS"}]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)  # não deve levantar TokenDecryptionError

    def test_blocks_when_canal_is_not_business(self):
        canal = CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Canal Baileys", instance_name="canal-baileys-provisionamento",
            principal=True, ativo=True,
        )  # provider default = WHATSAPP-BAILEYS
        credencial = MetaCloudCredential.objects.create(
            canal=canal, empresa=self.empresa, status=MetaCloudCredential.STATUS_PENDENTE,
        )  # sem waba_id/token -- clean() do model normalmente bloquearia isso via admin,
           # mas o serviço não deve confiar cegamente nisso

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.fetch_instances.assert_not_called()
        mock_client.create_instance.assert_not_called()

    # ── token do tenant correto ──────────────────────────────────────────────

    def test_uses_token_of_the_correct_tenant(self):
        outra_empresa = _make_empresa(nome="Outra Empresa", slug="outra-empresa-prov")
        set_session_tenant(outra_empresa.pk)
        outro_canal = _make_canal_business(outra_empresa, instance_name="canal-outra-empresa")
        _make_credencial(outro_canal, outra_empresa, token="TOKEN-DA-OUTRA-EMPRESA", phone_number_id="789")

        set_session_tenant(self.empresa.pk)
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, token="TOKEN-DA-EMPRESA-CERTA", phone_number_id="456")

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            provision_meta_channel(credencial.pk)

        _args, kwargs = mock_client.create_instance.call_args
        self.assertEqual(kwargs["token"], "TOKEN-DA-EMPRESA-CERTA")

    # ── validações que impedem chamar a Evolution à toa ─────────────────────

    def test_error_when_missing_phone_number_id(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, phone_number_id="")

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.fetch_instances.assert_not_called()
        mock_client.create_instance.assert_not_called()

    def test_error_when_missing_token(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, token="")

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()
        credencial.refresh_from_db()
        # Falha de validação local também é persistida como erro (rastro de
        # auditoria em detalhe_provisionamento), não só devolvida na resposta
        # transiente da action do admin (achado do Codex na revisão).
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)
        self.assertIn("Token de acesso", credencial.detalhe_provisionamento)

    def test_corrupted_token_marks_erro_instead_of_leaking_raw_decryption_error(self):
        """TokenDecryptionError (ciphertext corrompido/chave errada) precisa
        ser sanitizado igual a qualquer outro erro deste serviço -- nunca
        deixar a exceção crua do core.fields subir até o admin (achado do
        Codex na terceira revisão)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)
        _corrupt_stored_token(credencial)

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)  # nunca TokenDecryptionError

        mock_client.create_instance.assert_not_called()
        # refresh_from_db() comum recarregaria TODOS os campos, inclusive o
        # ciphertext corrompido -- EncryptedTextField decifra no from_db_value
        # (na hora que a LINHA é carregada), não só quando o atributo é lido.
        # Precisa do mesmo .defer() usado pelo próprio serviço.
        credencial = MetaCloudCredential.objects.defer("meta_access_token").get(pk=credencial.pk)
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)

    def test_corrupted_token_marks_erro_when_comparing_against_existing_instance(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)
        _corrupt_stored_token(credencial)

        existing = [{
            "name": "canal-provisionamento-teste", "integration": "WHATSAPP-BUSINESS",
            "number": "456", "businessId": "123", "token": "qualquer-coisa",
        }]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)  # nunca TokenDecryptionError

        credencial = MetaCloudCredential.objects.defer("meta_access_token").get(pk=credencial.pk)
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)

    # ── tratamento de erro sem vazar segredo ────────────────────────────────

    def test_evolution_http_error_marks_erro_without_leaking_token(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        fake_response = MagicMock(status_code=400, text=f"token invalido: {PLAINTEXT_TOKEN}")
        error = httpx.HTTPStatusError("bad request", request=MagicMock(), response=fake_response)
        patcher, mock_client = self._patched_client(fetch_return=[], create_side_effect=error)
        with patcher:
            with self.assertLogs("whatsapp.services.channel_provisioning", level="ERROR") as logs:
                with self.assertRaises(ChannelProvisioningError) as ctx:
                    provision_meta_channel(credencial.pk)

        self.assertNotIn(PLAINTEXT_TOKEN, str(ctx.exception))
        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)
        self.assertNotIn(PLAINTEXT_TOKEN, credencial.detalhe_provisionamento)
        # Confere o STREAM de log de verdade (não só a exceção/campo persistido)
        # -- é isso que garante que nada vaza em nenhum log real emitido.
        self.assertTrue(logs.output)
        for record in logs.output:
            self.assertNotIn(PLAINTEXT_TOKEN, record)

    def test_fetch_instances_raw_response_never_logged(self):
        """A Evolution devolve o token de TODAS as instâncias em texto puro
        em fetchInstances (confirmado ao vivo) -- o serviço nunca pode logar
        essa lista inteira, nem quando encontra uma colisão de nome."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        outro_token_em_texto_puro = "TOKEN-DE-OUTRA-INSTANCIA-QUALQUER-NAO-DEVE-VAZAR"
        existing = [
            {"name": "canal-provisionamento-teste", "integration": "WHATSAPP-BAILEYS",
             "token": outro_token_em_texto_puro},
        ]
        patcher, mock_client = self._patched_client(fetch_return=existing)
        with patcher:
            with self.assertLogs("whatsapp.services.channel_provisioning", level="ERROR") as logs:
                with self.assertRaises(ChannelProvisioningError):
                    provision_meta_channel(credencial.pk)

        self.assertTrue(logs.output)
        for record in logs.output:
            self.assertNotIn(outro_token_em_texto_puro, record)
        credencial.refresh_from_db()
        self.assertNotIn(outro_token_em_texto_puro, credencial.detalhe_provisionamento)

    def test_evolution_network_error_marks_erro(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        patcher, mock_client = self._patched_client(
            fetch_return=[], create_side_effect=httpx.ConnectTimeout("timed out"),
        )
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        credencial.refresh_from_db()
        self.assertEqual(credencial.status, MetaCloudCredential.STATUS_ERRO)

    def test_fetch_instances_error_marks_erro_without_calling_create(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        patcher, mock_client = self._patched_client(fetch_side_effect=httpx.ConnectError("down"))
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.create_instance.assert_not_called()

    # ── trava contra provisionamento concorrente ────────────────────────────

    def test_concurrent_provisioning_blocked_by_lock(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        # Simula operação já em andamento: SET NX é exatamente o que o Lock
        # do redis-py faz internamente pra adquirir -- não importa quem
        # segura a chave, só que ela já existe.
        redis_client = _redis_client()
        redis_client.set(_lock_key(credencial.pk), "1", nx=True, ex=60)
        self.addCleanup(redis_client.delete, _lock_key(credencial.pk))

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        mock_client.fetch_instances.assert_not_called()

    def test_lock_released_after_provisioning_even_on_error(self):
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa, token="")

        patcher, mock_client = self._patched_client(fetch_return=[])
        with patcher:
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)

        self.assertIsNone(_redis_client().get(_lock_key(credencial.pk)))

    def test_stale_lock_release_never_deletes_a_newer_owners_lock(self):
        """Reproduz o cenário descrito pelo Codex: se o lock desta operação já
        expirou e outra operação (dono novo) já adquiriu a mesma chave, o
        release desta chamada NUNCA pode apagar o lock do dono novo -- senão
        um terceiro provisionamento concorrente conseguiria entrar. O Lock do
        redis-py resolve isso com um script Lua que compara o token do dono
        ANTES de apagar, no próprio servidor Redis -- não é um get()+delete()
        em duas chamadas separadas (que teria uma janela de corrida real)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)
        lock_key = _lock_key(credencial.pk)
        redis_client = _redis_client()

        # Simula: o lock desta chamada já "expirou" e foi substituído por um
        # dono novo (outra operação concorrente) antes do release rodar.
        outro_dono_token = "dono-de-outra-operacao-concorrente"

        def fetch_and_simulate_takeover(*_args, **_kwargs):
            redis_client.set(lock_key, outro_dono_token, ex=60)
            return []

        patcher, mock_client = self._patched_client(fetch_return=[])
        mock_client.fetch_instances.side_effect = fetch_and_simulate_takeover
        with patcher:
            provision_meta_channel(credencial.pk)

        # O lock ainda deve pertencer ao "outro dono" -- não foi apagado.
        self.assertEqual(redis_client.get(lock_key), outro_dono_token.encode())
        self.addCleanup(redis_client.delete, lock_key)

    def test_redis_connection_error_on_acquire_is_sanitized(self):
        """Erro de conexão com o Redis no acquire() do lock não pode
        propagar cru -- vira ChannelProvisioningError como qualquer outro
        erro deste serviço (endurecimento sugerido pelo Codex)."""
        canal = _make_canal_business(self.empresa)
        credencial = _make_credencial(canal, self.empresa)

        broken_lock = MagicMock()
        broken_lock.acquire.side_effect = redis.exceptions.ConnectionError("redis fora do ar")
        broken_client = MagicMock()
        broken_client.lock.return_value = broken_lock

        with patch(
            "whatsapp.services.channel_provisioning._redis_client", return_value=broken_client,
        ):
            with self.assertRaises(ChannelProvisioningError):
                provision_meta_channel(credencial.pk)
