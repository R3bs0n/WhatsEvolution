from django.db import models
from django.utils import timezone


class ContatoBloqueado(models.Model):
    telefone = models.CharField(max_length=30, unique=True)
    data_bloqueio = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_bloqueio"]
        verbose_name = "Contato bloqueado"
        verbose_name_plural = "Contatos bloqueados (opt-out)"
        db_table = "contatos_bloqueados"

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
