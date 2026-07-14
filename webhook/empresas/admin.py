from django.contrib import admin

from core.admin import SuperuserOnlyAdminMixin

from .models import Empresa, MembroEmpresa


class MembroEmpresaInline(admin.TabularInline):
    model = MembroEmpresa
    extra = 1
    fields = ("usuario", "papel", "ativo")


@admin.register(Empresa)
class EmpresaAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "slug", "segmento", "ativo", "created_at")
    list_filter = ("ativo", "tema")
    search_fields = ("nome", "slug", "segmento")
    prepopulated_fields = {"slug": ("nome",)}
    inlines = [MembroEmpresaInline]
    fieldsets = (
        (None, {"fields": ("nome", "slug", "segmento", "ativo")}),
        ("Branding", {"fields": ("logo", "cor_primaria", "cor_secundaria", "tema")}),
    )


@admin.register(MembroEmpresa)
class MembroEmpresaAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("usuario", "empresa", "papel", "ativo", "criado_em")
    list_filter = ("papel", "ativo", "empresa")
    search_fields = ("usuario__username", "empresa__nome")
