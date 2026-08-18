from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.fields import EncryptedTextField
from core.managers import TenantManager


class CanalWhatsApp(models.Model):
    PROVIDER_BAILEYS = "WHATSAPP-BAILEYS"
    PROVIDER_BUSINESS = "WHATSAPP-BUSINESS"
    PROVIDER_CHOICES = [
        (PROVIDER_BAILEYS, "WhatsApp (QR Code) — Baileys"),
        (PROVIDER_BUSINESS, "WhatsApp Business API — Meta (Cloud API oficial)"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="canais_whatsapp",
    )
    nome = models.CharField(max_length=100)
    instance_name = models.CharField(max_length=100, unique=True)
    api_url = models.CharField(max_length=255, blank=True)
    provider = models.CharField(
        max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_BAILEYS
    )
    principal = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Canal WhatsApp"
        verbose_name_plural = "Canais WhatsApp"
        ordering = ["empresa", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.instance_name})"

    def save(self, *args, **kwargs):
        # Garante apenas um canal principal por empresa
        if self.principal and self.empresa_id:
            CanalWhatsApp.objects.filter(
                empresa=self.empresa, principal=True
            ).exclude(pk=self.pk).update(principal=False)
        super().save(*args, **kwargs)


class MetaCloudCredential(models.Model):
    """Credenciais da Cloud API oficial (Meta) para um CanalWhatsApp.

    Separado de CanalWhatsApp de propósito: operações comuns sobre canais
    (listar, checar Chatwoot, etc.) não precisam carregar nem decifrar o
    token — só quem precisa mesmo das credenciais consulta este modelo.

    `empresa` é redundante em relação a `canal.empresa` (denormalizado de
    propósito) para que a policy de RLS filtre direto por empresa_id nesta
    tabela, sem depender de JOIN com whatsapp_canalwhatsapp.
    """

    STATUS_PENDENTE = "pendente"
    STATUS_CONFIGURADO = "configurado"
    STATUS_ERRO = "erro"
    STATUS_CHOICES = [
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_CONFIGURADO, "Configurado"),
        (STATUS_ERRO, "Erro"),
    ]

    canal = models.OneToOneField(
        CanalWhatsApp,
        on_delete=models.CASCADE,
        related_name="credencial_meta",
    )
    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="credenciais_meta",
    )
    waba_id = models.CharField(
        "WABA ID", max_length=50, blank=True,
        help_text="WhatsApp Business Account ID. Uma WABA pode ter vários números.",
    )
    phone_number_id = models.CharField(
        "Phone Number ID", max_length=50, blank=True,
    )
    meta_access_token = EncryptedTextField(
        "Token de acesso (Meta)", blank=True,
        help_text="Cifrado em repouso. Nunca exibido em texto puro pelo admin.",
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDENTE
    )
    detalhe_provisionamento = models.TextField(
        blank=True,
        help_text="Mensagem sanitizada do último provisionamento na Evolution "
        "(nunca contém o token). Preenchido por whatsapp/services/channel_provisioning.py.",
    )
    token_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Preencher só se a Meta informar expiração conhecida para este token.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
        help_text="Último usuário a definir/alterar este registro.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Credencial Meta Cloud API"
        verbose_name_plural = "Credenciais Meta Cloud API"
        ordering = ["empresa", "canal"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number_id"],
                condition=models.Q(phone_number_id__gt=""),
                name="uq_metacloudcredential_phone_number_id",
            ),
        ]

    def __str__(self):
        return f"Credencial Meta — {self.canal.nome} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.canal_id and self.empresa_id and self.canal.empresa_id != self.empresa_id:
            raise ValidationError("A empresa da credencial deve ser a mesma do canal vinculado.")
        if self.canal_id and self.canal.provider != CanalWhatsApp.PROVIDER_BUSINESS:
            if self.waba_id or self.phone_number_id or self.meta_access_token:
                raise ValidationError(
                    "waba_id/phone_number_id/token só fazem sentido para canais "
                    f"com provider={CanalWhatsApp.PROVIDER_BUSINESS!r}."
                )

    def save(self, *args, **kwargs):
        if not self.empresa_id and self.canal_id:
            self.empresa_id = self.canal.empresa_id
        super().save(*args, **kwargs)


class ConfiguracaoDisparo(models.Model):
    empresa = models.OneToOneField(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="configuracao_disparo",
    )
    limite_diario_mensagens = models.IntegerField(
        default=1000, verbose_name="Limite diário de mensagens"
    )
    tamanho_lote = models.IntegerField(default=300, verbose_name="Tamanho do lote")
    intervalo_segundos = models.IntegerField(
        default=3, verbose_name="Intervalo entre envios (segundos)"
    )
    mensagens_por_minuto = models.IntegerField(
        default=20, verbose_name="Mensagens por minuto por canal"
    )
    contato_url = models.CharField(max_length=255, blank=True)
    privacy_policy_url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de disparo"
        verbose_name_plural = "Configurações de disparo"

    def __str__(self):
        return f"Config disparo — {self.empresa.nome}"


class TemplateMensagem(models.Model):
    CATEGORIA_CHOICES = [
        ("clinico", "Clínico"),
        ("promocional", "Promocional"),
        ("transacional", "Transacional"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="templates_mensagem",
    )
    nome = models.CharField(max_length=100)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default="clinico")
    corpo = models.TextField(help_text="Use {variavel} para campos dinâmicos")
    variaveis_permitidas = models.JSONField(
        default=list, blank=True,
        help_text="Lista de nomes de variáveis esperadas, ex: ['nome_paciente', 'tipo_exame']"
    )
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Template de mensagem"
        verbose_name_plural = "Templates de mensagem"
        ordering = ["empresa", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.get_categoria_display()})"

    def renderizar(self, variaveis: dict) -> str:
        try:
            return self.corpo.format(**variaveis)
        except KeyError as e:
            raise ValueError(f"Variável ausente no template: {e}") from e


class ContatoBloqueado(models.Model):
    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE, related_name="contatos_bloqueados",
    )
    telefone = models.CharField(max_length=30)
    data_bloqueio = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-data_bloqueio"]
        verbose_name = "Contato bloqueado"
        verbose_name_plural = "Contatos bloqueados (opt-out)"
        db_table = "contatos_bloqueados"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "telefone"],
                name="uq_contato_bloqueado_empresa_telefone",
            )
        ]

    def __str__(self):
        return self.telefone


class ConfiguracaoSistema(models.Model):
    limite_diario_mensagens = models.IntegerField(
        default=1000,
        verbose_name="Limite diário de mensagens",
    )

    class Meta:
        verbose_name = "Configuração do sistema"
        verbose_name_plural = "Configuração do sistema"
        db_table = "configuracao_sistema"

    def __str__(self):
        return f"Configuração — limite diário: {self.limite_diario_mensagens}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EnvioMensagem(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("processando", "Processando"),
        ("enviado", "Enviado"),
        ("falha", "Falha"),
        ("cancelado", "Cancelado"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.CASCADE,
        related_name="envios_mensagem",
    )
    canal = models.ForeignKey(
        CanalWhatsApp, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="envios",
    )
    telefone_snapshot = models.CharField(max_length=30)
    conteudo_snapshot = models.TextField()
    variaveis_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente", db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    external_message_id = models.CharField(max_length=100, blank=True, db_index=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    agendado_para = models.DateTimeField(null=True, blank=True, db_index=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Envio de mensagem"
        verbose_name_plural = "Envios de mensagem"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.telefone_snapshot} — {self.status} ({self.created_at:%d/%m/%Y %H:%M})"


class TentativaEnvio(models.Model):
    STATUS_CHOICES = [
        ("sucesso", "Sucesso"),
        ("falha", "Falha"),
        ("timeout", "Timeout"),
    ]

    envio = models.ForeignKey(
        EnvioMensagem, on_delete=models.CASCADE, related_name="tentativas_envio"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    resposta = models.JSONField(default=dict, blank=True)
    tentado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tentativa de envio"
        verbose_name_plural = "Tentativas de envio"
        ordering = ["-tentado_em"]

    def __str__(self):
        return f"Tentativa {self.pk} — {self.status} — {self.tentado_em:%d/%m/%Y %H:%M}"


class EventoMensagem(models.Model):
    TIPO_CHOICES = [
        ("entregue", "Entregue"),
        ("lido", "Lido"),
        ("falhou", "Falhou"),
        ("devolvido", "Devolvido"),
        ("desconhecido", "Desconhecido"),
    ]

    envio = models.ForeignKey(
        EnvioMensagem, on_delete=models.CASCADE, related_name="eventos"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="desconhecido", db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    recebido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Evento de mensagem"
        verbose_name_plural = "Eventos de mensagem"
        ordering = ["-recebido_em"]

    def __str__(self):
        return f"{self.tipo} — {self.recebido_em:%d/%m/%Y %H:%M}"


class AtendimentoEnvio(models.Model):
    """Bridge: vincula um Atendimento (clínico) a um EnvioMensagem (mensageria)."""

    atendimento = models.OneToOneField(
        "atendimentos.Atendimento",
        on_delete=models.CASCADE,
        related_name="envio_mensagem",
    )
    envio = models.OneToOneField(
        EnvioMensagem,
        on_delete=models.CASCADE,
        related_name="atendimento_envio",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Envio de atendimento"
        verbose_name_plural = "Envios de atendimento"

    def __str__(self):
        return f"Atendimento {self.atendimento_id} → Envio {self.envio_id}"


class EnvioWhatsAppLog(models.Model):
    TIPO_ENVIO_CHOICES = [
        ("texto", "Texto livre"),
        ("template", "Template (HSM)"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE, related_name="envios_whatsapp",
    )
    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.CASCADE,
        related_name="whatsapp_logs",
    )
    telefone = models.CharField(max_length=20)
    mensagem = models.TextField()
    tipo_envio = models.CharField(max_length=10, choices=TIPO_ENVIO_CHOICES, default="texto")
    template_nome = models.CharField(max_length=100, blank=True)
    external_message_id = models.CharField(max_length=100, blank=True)
    status_retorno = models.CharField(max_length=100, blank=True)
    codigo_retorno = models.CharField(max_length=50, blank=True)
    detalhe_retorno = models.TextField(blank=True)
    enviado_em = models.DateTimeField(default=timezone.now)
    sucesso = models.BooleanField(default=False)

    objects = TenantManager()

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "Log de envio WhatsApp"
        verbose_name_plural = "Logs de envio WhatsApp"

    def __str__(self):
        status = "OK" if self.sucesso else "FALHA"
        return f"{self.telefone} — {status} — {self.enviado_em:%d/%m/%Y %H:%M}"
