from django.contrib.auth.models import User
from django.db import models

from core.managers import TenantManager


class Contato(models.Model):
    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.CASCADE, related_name="contatos"
    )
    nome = models.CharField(max_length=255)
    telefone = models.CharField(max_length=30, db_index=True)
    email = models.EmailField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Contato"
        verbose_name_plural = "Contatos"
        unique_together = [("empresa", "telefone")]
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.telefone})"


class Segmento(models.Model):
    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.CASCADE, related_name="segmentos"
    )
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    contatos = models.ManyToManyField(
        Contato, related_name="segmentos", blank=True
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Segmento"
        verbose_name_plural = "Segmentos"
        unique_together = [("empresa", "nome")]
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def total_contatos(self):
        return self.contatos.count()


class Campanha(models.Model):
    STATUS_CHOICES = [
        ("rascunho", "Rascunho"),
        ("agendada", "Agendada"),
        ("em_andamento", "Em andamento"),
        ("pausada", "Pausada"),
        ("concluida", "Concluída"),
        ("cancelada", "Cancelada"),
    ]

    empresa = models.ForeignKey(
        "empresas.Empresa", on_delete=models.CASCADE, related_name="campanhas"
    )
    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    segmento = models.ForeignKey(
        Segmento, on_delete=models.PROTECT, related_name="campanhas"
    )
    template = models.ForeignKey(
        "whatsapp.TemplateMensagem",
        on_delete=models.PROTECT,
        related_name="campanhas",
        null=True, blank=True,
    )
    canal = models.ForeignKey(
        "whatsapp.CanalWhatsApp",
        on_delete=models.PROTECT,
        related_name="campanhas",
        null=True, blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="rascunho", db_index=True)
    agendado_para = models.DateTimeField(null=True, blank=True)
    criado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="campanhas_criadas"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        verbose_name = "Campanha"
        verbose_name_plural = "Campanhas"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.nome} ({self.get_status_display()})"

    def total_destinatarios(self):
        return self.destinatarios.count()

    def total_enviados(self):
        return self.destinatarios.filter(status="enviado").count()


class DestinatarioCampanha(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("processando", "Processando"),
        ("enviado", "Enviado"),
        ("falha", "Falha"),
        ("optout", "Opt-out"),
        ("invalido", "Inválido"),
    ]

    campanha = models.ForeignKey(
        Campanha, on_delete=models.CASCADE, related_name="destinatarios"
    )
    contato = models.ForeignKey(
        Contato, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="destinatarios_campanha"
    )
    envio_mensagem = models.OneToOneField(
        "whatsapp.EnvioMensagem",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="destinatario_campanha",
    )
    nome_snapshot = models.CharField(max_length=255)
    telefone_snapshot = models.CharField(max_length=30)
    variaveis_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente", db_index=True)
    erro = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Destinatário da campanha"
        verbose_name_plural = "Destinatários da campanha"
        ordering = ["campanha", "nome_snapshot"]

    def __str__(self):
        return f"{self.nome_snapshot} ({self.telefone_snapshot}) — {self.status}"
