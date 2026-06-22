from django.db import models


class Plano(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    limite_mensal_mensagens = models.IntegerField(default=1000)
    recursos = models.JSONField(default=dict, blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Assinatura(models.Model):
    STATUS_CHOICES = [
        ("ativa", "Ativa"),
        ("suspensa", "Suspensa"),
        ("cancelada", "Cancelada"),
        ("carencia", "Em carência"),
    ]

    empresa = models.OneToOneField(
        "empresas.Empresa", on_delete=models.CASCADE, related_name="assinatura"
    )
    plano = models.ForeignKey(
        Plano, on_delete=models.PROTECT, related_name="assinaturas"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ativa", db_index=True)
    inicio = models.DateField()
    vencimento = models.DateField()
    carencia_ate = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"

    def __str__(self):
        return f"{self.empresa.nome} — {self.plano.nome} ({self.status})"

    def esta_ativa(self):
        from django.utils import timezone
        hoje = timezone.localdate()
        if self.status == "ativa":
            return True
        if self.status == "carencia" and self.carencia_ate and hoje <= self.carencia_ate:
            return True
        return False
