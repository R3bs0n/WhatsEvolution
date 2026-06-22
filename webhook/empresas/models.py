from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify


class Empresa(models.Model):
    TEMA_CHOICES = [("light", "Claro"), ("dark", "Escuro")]

    nome = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    segmento = models.CharField(max_length=100, blank=True)
    logo = models.ImageField(upload_to="empresas/logos/", null=True, blank=True)
    cor_primaria = models.CharField(max_length=7, default="#0d6efd")
    cor_secundaria = models.CharField(max_length=7, default="#6c757d")
    tema = models.CharField(max_length=10, choices=TEMA_CHOICES, default="light")
    ativo = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)


class MembroEmpresa(models.Model):
    PAPEL_CHOICES = [
        ("administrador", "Administrador"),
        ("operador", "Operador"),
        ("leitura", "Somente leitura"),
    ]

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="membros"
    )
    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="membros_empresa"
    )
    papel = models.CharField(max_length=20, choices=PAPEL_CHOICES, default="operador")
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Membro da empresa"
        verbose_name_plural = "Membros da empresa"
        unique_together = [("empresa", "usuario")]
        ordering = ["empresa", "usuario__username"]

    def __str__(self):
        return f"{self.usuario.username} — {self.empresa.nome} ({self.papel})"
