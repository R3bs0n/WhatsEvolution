from django.contrib.auth.models import User
from django.db import models


class PdfImportLog(models.Model):
    STATUS_CHOICES = [
        ("SUCESSO", "Sucesso"),
        ("PARCIAL", "Parcial"),
        ("ERRO", "Erro"),
    ]

    filename = models.CharField(max_length=255)
    nome = models.CharField(max_length=255, blank=True, verbose_name="Nome")
    periodo = models.DateField(
        null=True, blank=True, verbose_name="Período",
        help_text="Mês/ano a que este PDF se refere (armazenado como 1º dia do mês)"
    )
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    total_extraidos = models.PositiveIntegerField(default=0)
    total_inseridos = models.PositiveIntegerField(default=0)
    total_ignorados = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="SUCESSO")
    mensagem = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Log de importação PDF"
        verbose_name_plural = "Logs de importação PDF"

    def __str__(self):
        return f"{self.filename} — {self.status} ({self.created_at:%d/%m/%Y %H:%M})"
