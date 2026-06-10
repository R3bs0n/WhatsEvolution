from django.db import models
from django.utils import timezone


class EnvioWhatsAppLog(models.Model):
    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.CASCADE,
        related_name="whatsapp_logs",
    )
    telefone = models.CharField(max_length=20)
    mensagem = models.TextField()
    status_retorno = models.CharField(max_length=100, blank=True)
    codigo_retorno = models.CharField(max_length=50, blank=True)
    detalhe_retorno = models.TextField(blank=True)
    enviado_em = models.DateTimeField(default=timezone.now)
    sucesso = models.BooleanField(default=False)

    class Meta:
        ordering = ["-enviado_em"]
        verbose_name = "Log de envio WhatsApp"
        verbose_name_plural = "Logs de envio WhatsApp"

    def __str__(self):
        status = "OK" if self.sucesso else "FALHA"
        return f"{self.telefone} — {status} — {self.enviado_em:%d/%m/%Y %H:%M}"
