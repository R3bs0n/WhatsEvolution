from django.db import models


class StatusAtendimento(models.Model):
    nome = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Status do atendimento"
        verbose_name_plural = "Status do atendimento"
        ordering = ["nome"]
        db_table = "status_atendimento"

    def __str__(self):
        return self.nome


class SituacaoAtendimento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Situação do atendimento"
        verbose_name_plural = "Situações do atendimento"
        ordering = ["nome"]
        db_table = "situacoes_atendimento"

    def __str__(self):
        return self.nome


class Atendimento(models.Model):
    STATUS_CHOICES = [
        ("N", "Não enviado"),
        ("E", "Enfileirado"),
        ("S", "Enviado"),
        ("L", "Limitado"),
    ]

    situacao = models.ForeignKey(
        SituacaoAtendimento,
        on_delete=models.PROTECT,
        related_name="atendimentos",
    )
    exame_procedimento = models.CharField(max_length=255, blank=True)
    paciente = models.CharField(max_length=255, blank=True, db_index=True)
    idade = models.PositiveIntegerField(null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True, db_index=True)
    tp_procedimento = models.CharField(max_length=255, blank=True)
    un_executante = models.CharField(max_length=255, blank=True)
    data_hora = models.DateTimeField(null=True, blank=True, db_index=True)
    profissional_executante = models.CharField(max_length=255, blank=True)
    un_solicitante = models.CharField(max_length=255, blank=True)
    data_agendamento = models.DateField(null=True, blank=True, db_index=True)
    horario_agendamento = models.TimeField(null=True, blank=True, db_index=True)
    observacao = models.TextField(blank=True)
    status_atendimento = models.ForeignKey(
        StatusAtendimento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="atendimentos",
        verbose_name="Status clínico",
    )
    status_enviado = models.CharField(
        max_length=1, choices=STATUS_CHOICES, default="N", db_index=True
    )
    data_extracao = models.DateTimeField(null=True, blank=True)
    data_envio = models.DateTimeField(null=True, blank=True)
    pdf_nome_arquivo = models.CharField(max_length=255, blank=True)
    pdf_import = models.ForeignKey(
        "pdf_import.PdfImportLog",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="atendimentos",
        verbose_name="Importação PDF",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Atendimento"
        verbose_name_plural = "Atendimentos"
        indexes = [
            # Acelera o filtro principal do send_panel e da listagem
            models.Index(fields=["status_enviado", "-criado_em"], name="idx_atend_status_criado"),
        ]

    def __str__(self):
        return f"{self.paciente} — {self.exame_procedimento}"

    def telefone_normalizado(self):
        from django.conf import settings
        from core.services.phone import normalize_phone, PhoneValidationError
        try:
            return normalize_phone(self.telefone, settings.DEFAULT_COUNTRY_CODE)
        except PhoneValidationError:
            return self.telefone
