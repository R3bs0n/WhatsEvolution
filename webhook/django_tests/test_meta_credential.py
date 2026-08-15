"""Testes do modelo de credenciais Meta Cloud API (MetaCloudCredential) e do
campo cifrado (core.fields.EncryptedTextField).

Rodam como `app_role` de verdade (sem BYPASSRLS) contra um banco de teste com
RLS aplicado — por isso qualquer criação/leitura de dado em tabela protegida
precisa passar pelo contexto de tenant (core.tenant_context), exatamente como
uma request real passaria pelo TenantMiddleware.
"""
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase

from core.fields import TokenDecryptionError, validate_field_encryption_key
from core.tenant_context import reset_session_tenant, session_tenant_context, set_session_tenant
from empresas.models import Empresa
from whatsapp.models import CanalWhatsApp, MetaCloudCredential

PLAINTEXT_TOKEN = "EAAG-token-de-teste-nao-real-1234567890"


def _make_empresa(nome="Empresa Teste", slug="empresa-teste"):
    return Empresa.objects.create(nome=nome, slug=slug)


def _make_canal_business(empresa, instance_name="canal-business-teste"):
    return CanalWhatsApp.objects.create(
        empresa=empresa,
        nome="Canal Business",
        instance_name=instance_name,
        provider=CanalWhatsApp.PROVIDER_BUSINESS,
    )


class EncryptedTextFieldTests(TestCase):
    """Testa o campo isoladamente, via o próprio MetaCloudCredential."""

    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(reset_session_tenant)
        self.canal = _make_canal_business(self.empresa)

    def test_round_trip_save_and_read_back(self):
        cred = MetaCloudCredential.objects.create(
            canal=self.canal, empresa=self.empresa, meta_access_token=PLAINTEXT_TOKEN,
        )
        cred.refresh_from_db()
        self.assertEqual(cred.meta_access_token, PLAINTEXT_TOKEN)

    def test_raw_db_value_is_not_plaintext(self):
        MetaCloudCredential.objects.create(
            canal=self.canal, empresa=self.empresa, meta_access_token=PLAINTEXT_TOKEN,
        )
        with connection.cursor() as cur:
            cur.execute(
                "SELECT meta_access_token FROM whatsapp_metacloudcredential WHERE canal_id = %s",
                [self.canal.pk],
            )
            raw = cur.fetchone()[0]
        self.assertNotIn(PLAINTEXT_TOKEN, raw)
        self.assertTrue(raw.startswith("v1:"))

    def test_empty_token_stays_empty_not_encrypted(self):
        cred = MetaCloudCredential.objects.create(canal=self.canal, empresa=self.empresa)
        with connection.cursor() as cur:
            cur.execute(
                "SELECT meta_access_token FROM whatsapp_metacloudcredential WHERE canal_id = %s",
                [self.canal.pk],
            )
            raw = cur.fetchone()[0]
        self.assertEqual(raw, "")
        cred.refresh_from_db()
        self.assertEqual(cred.meta_access_token, "")

    def test_corrupted_ciphertext_raises_clear_error_on_read(self):
        MetaCloudCredential.objects.create(
            canal=self.canal, empresa=self.empresa, meta_access_token=PLAINTEXT_TOKEN,
        )
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE whatsapp_metacloudcredential SET meta_access_token = %s WHERE canal_id = %s",
                ["v1:isso-nao-e-um-token-fernet-valido", self.canal.pk],
            )
        # from_db_value decifra na hora que a linha é carregada do banco (não
        # é lazy no acesso ao atributo) — o .get() precisa estar dentro do
        # assertRaises.
        with self.assertRaises(TokenDecryptionError):
            MetaCloudCredential.objects.for_empresa(self.empresa).get(canal=self.canal)

    def test_wrong_key_id_raises_clear_error(self):
        MetaCloudCredential.objects.create(
            canal=self.canal, empresa=self.empresa, meta_access_token=PLAINTEXT_TOKEN,
        )
        with connection.cursor() as cur:
            cur.execute("SELECT meta_access_token FROM whatsapp_metacloudcredential WHERE canal_id = %s", [self.canal.pk])
            raw = cur.fetchone()[0]
            tampered = raw.replace("v1:", "v2:", 1)
            cur.execute(
                "UPDATE whatsapp_metacloudcredential SET meta_access_token = %s WHERE canal_id = %s",
                [tampered, self.canal.pk],
            )
        with self.assertRaises(TokenDecryptionError):
            MetaCloudCredential.objects.for_empresa(self.empresa).get(canal=self.canal)

    def test_bulk_create_encrypts_correctly(self):
        empresa2 = _make_empresa("Empresa Bulk", "empresa-bulk")
        with session_tenant_context(empresa2.pk):
            canal2 = _make_canal_business(empresa2, "canal-bulk-teste")
            MetaCloudCredential.objects.bulk_create([
                MetaCloudCredential(canal=canal2, empresa=empresa2, meta_access_token=PLAINTEXT_TOKEN),
            ])
            cred = MetaCloudCredential.objects.for_empresa(empresa2).get(canal=canal2)
            self.assertEqual(cred.meta_access_token, PLAINTEXT_TOKEN)
            with connection.cursor() as cur:
                cur.execute("SELECT meta_access_token FROM whatsapp_metacloudcredential WHERE canal_id = %s", [canal2.pk])
                raw = cur.fetchone()[0]
            self.assertNotIn(PLAINTEXT_TOKEN, raw)

    def test_queryset_update_encrypts_correctly(self):
        cred = MetaCloudCredential.objects.create(canal=self.canal, empresa=self.empresa)
        MetaCloudCredential.objects.filter(pk=cred.pk).update(meta_access_token=PLAINTEXT_TOKEN)
        cred.refresh_from_db()
        self.assertEqual(cred.meta_access_token, PLAINTEXT_TOKEN)
        with connection.cursor() as cur:
            cur.execute("SELECT meta_access_token FROM whatsapp_metacloudcredential WHERE canal_id = %s", [self.canal.pk])
            raw = cur.fetchone()[0]
        self.assertNotIn(PLAINTEXT_TOKEN, raw)


class FieldEncryptionKeyValidationTests(TestCase):
    """Testa a função de validação isoladamente — não reinicia o Django."""

    def test_missing_key_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_field_encryption_key("")

    def test_malformed_key_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_field_encryption_key("nao-e-uma-chave-fernet-valida")

    def test_valid_key_does_not_raise(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        validate_field_encryption_key(key)  # não deve levantar

    def test_error_message_never_includes_the_key_itself(self):
        bad_key = "chave-secreta-de-mentirinha-para-o-teste"
        try:
            validate_field_encryption_key(bad_key)
        except ImproperlyConfigured as exc:
            self.assertNotIn(bad_key, str(exc))
        else:
            self.fail("esperava ImproperlyConfigured")


class MetaCloudCredentialModelTests(TestCase):
    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(reset_session_tenant)

    def test_business_canal_with_full_credentials(self):
        canal = _make_canal_business(self.empresa)
        cred = MetaCloudCredential.objects.create(
            canal=canal,
            empresa=self.empresa,
            waba_id="123456789",
            phone_number_id="987654321",
            meta_access_token=PLAINTEXT_TOKEN,
            status=MetaCloudCredential.STATUS_CONFIGURADO,
        )
        cred.refresh_from_db()
        self.assertEqual(cred.waba_id, "123456789")
        self.assertEqual(cred.meta_access_token, PLAINTEXT_TOKEN)

    def test_empresa_can_have_multiple_canais(self):
        canal1 = CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Disparo", instance_name="canal-disparo-teste",
        )
        canal2 = CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Atendimento", instance_name="canal-atendimento-teste",
        )
        self.assertEqual(CanalWhatsApp.objects.for_empresa(self.empresa).count(), 2)
        self.assertNotEqual(canal1.pk, canal2.pk)

    def test_clean_rejects_business_fields_on_baileys_canal(self):
        canal = CanalWhatsApp.objects.create(
            empresa=self.empresa, nome="Baileys", instance_name="canal-baileys-teste",
        )
        cred = MetaCloudCredential(canal=canal, empresa=self.empresa, waba_id="123")
        with self.assertRaises(ValidationError):
            cred.clean()

    def test_clean_rejects_empresa_mismatch_with_canal(self):
        outra_empresa = _make_empresa("Outra Empresa", "outra-empresa")
        canal = _make_canal_business(self.empresa)
        cred = MetaCloudCredential(canal=canal, empresa=outra_empresa)
        with self.assertRaises(ValidationError):
            cred.clean()

    def test_phone_number_id_unique_when_set(self):
        canal1 = _make_canal_business(self.empresa, "canal-a")
        canal2 = _make_canal_business(self.empresa, "canal-b")
        MetaCloudCredential.objects.create(canal=canal1, empresa=self.empresa, phone_number_id="555")
        # savepoint próprio: sem isso, o IntegrityError deixa a transação do
        # TestCase inteira "quebrada" até o rollback final do teste, e até o
        # addCleanup (reset_session_tenant) falharia tentando rodar depois.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MetaCloudCredential.objects.create(canal=canal2, empresa=self.empresa, phone_number_id="555")

    def test_two_canais_with_blank_phone_number_id_allowed(self):
        canal1 = _make_canal_business(self.empresa, "canal-c")
        canal2 = _make_canal_business(self.empresa, "canal-d")
        MetaCloudCredential.objects.create(canal=canal1, empresa=self.empresa)
        MetaCloudCredential.objects.create(canal=canal2, empresa=self.empresa)  # não deve levantar


class MetaCloudCredentialAdminTests(TestCase):
    def setUp(self):
        self.empresa = _make_empresa()
        set_session_tenant(self.empresa.pk)
        self.addCleanup(reset_session_tenant)
        self.canal = _make_canal_business(self.empresa)
        self.cred = MetaCloudCredential.objects.create(
            canal=self.canal, empresa=self.empresa, meta_access_token=PLAINTEXT_TOKEN,
        )
        self.admin_user = User.objects.create_superuser("admin-teste", "a@a.com", "senha-teste-123")
        self.client = Client()
        self.client.login(username="admin-teste", password="senha-teste-123")
        # Superadmin precisa ter uma empresa "ativa" selecionada na sessão
        # pro TenantMiddleware configurar o RLS da request — sem isso toda
        # tabela protegida fica vazia mesmo pra superuser (comportamento
        # correto e documentado do TenantMiddleware, não um bug).
        session = self.client.session
        session["active_empresa_id"] = self.empresa.pk
        session.save()

    def test_token_never_rendered_in_change_form(self):
        url = f"/admin/whatsapp/metacloudcredential/{self.cred.pk}/change/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PLAINTEXT_TOKEN.encode(), response.content)
        self.assertIn(b"definido", response.content)

    def test_token_never_rendered_in_list_view(self):
        response = self.client.get("/admin/whatsapp/metacloudcredential/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PLAINTEXT_TOKEN.encode(), response.content)

    def test_leaving_novo_token_blank_keeps_existing_token(self):
        url = f"/admin/whatsapp/metacloudcredential/{self.cred.pk}/change/"
        response = self.client.post(url, {
            "canal": self.canal.pk,
            "empresa": self.empresa.pk,
            "status": MetaCloudCredential.STATUS_PENDENTE,
            "waba_id": "",
            "phone_number_id": "",
            "token_expires_at_0": "",
            "token_expires_at_1": "",
            "novo_token": "",
        })
        # TenantMiddleware reseta app.current_tenant no `finally` ao fim de
        # CADA request (mesma conexão do processo de teste) — precisa
        # reconfigurar antes de consultar de novo fora do ciclo de request.
        set_session_tenant(self.empresa.pk)
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.meta_access_token, PLAINTEXT_TOKEN)

    def test_filling_novo_token_replaces_it(self):
        novo = "novo-token-de-teste-substituto"
        self.client.post(f"/admin/whatsapp/metacloudcredential/{self.cred.pk}/change/", {
            "canal": self.canal.pk,
            "empresa": self.empresa.pk,
            "status": MetaCloudCredential.STATUS_PENDENTE,
            "waba_id": "",
            "phone_number_id": "",
            "token_expires_at_0": "",
            "token_expires_at_1": "",
            "novo_token": novo,
        })
        set_session_tenant(self.empresa.pk)
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.meta_access_token, novo)
        self.assertEqual(self.cred.updated_by_id, self.admin_user.pk)


class MetaCloudCredentialTenantIsolationTests(TestCase):
    """Isolamento em DUAS camadas: filtro de ORM (TenantManager.for_empresa)
    E o RLS de verdade do Postgres (rodando como app_role, sem BYPASSRLS,
    contra um banco de teste com as policies de db/rls_policies.sql
    aplicadas — ver db/bootstrap_test_db.sh)."""

    def setUp(self):
        self.empresa_a = _make_empresa("Empresa A", "empresa-a-cred")
        self.empresa_b = _make_empresa("Empresa B", "empresa-b-cred")
        with session_tenant_context(self.empresa_a.pk):
            self.canal_a = _make_canal_business(self.empresa_a, "canal-a-cred")
            MetaCloudCredential.objects.create(
                canal=self.canal_a, empresa=self.empresa_a, meta_access_token="token-empresa-a",
            )
        with session_tenant_context(self.empresa_b.pk):
            self.canal_b = _make_canal_business(self.empresa_b, "canal-b-cred")
            MetaCloudCredential.objects.create(
                canal=self.canal_b, empresa=self.empresa_b, meta_access_token="token-empresa-b",
            )
        self.addCleanup(reset_session_tenant)

    def test_for_empresa_does_not_leak_other_tenant(self):
        with session_tenant_context(self.empresa_a.pk):
            qs_a = MetaCloudCredential.objects.for_empresa(self.empresa_a)
            self.assertEqual(qs_a.count(), 1)
            self.assertEqual(qs_a.first().canal_id, self.canal_a.pk)

    def test_rls_blocks_cross_tenant_even_without_for_empresa_filter(self):
        """Prova que o isolamento é do Postgres (RLS), não só do filtro
        .for_empresa() do TenantManager — usa .objects.all() de propósito,
        sem nenhum filtro por empresa no código Python."""
        with session_tenant_context(self.empresa_a.pk):
            todos = list(MetaCloudCredential.objects.all())
            self.assertEqual(len(todos), 1)
            self.assertEqual(todos[0].canal_id, self.canal_a.pk)
        with session_tenant_context(self.empresa_b.pk):
            todos = list(MetaCloudCredential.objects.all())
            self.assertEqual(len(todos), 1)
            self.assertEqual(todos[0].canal_id, self.canal_b.pk)

    def test_rls_blocks_everything_without_any_tenant_context(self):
        reset_session_tenant()
        todos = list(MetaCloudCredential.objects.all())
        self.assertEqual(todos, [])
