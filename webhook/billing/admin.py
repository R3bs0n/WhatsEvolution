from django.contrib import admin

from core.admin import SuperuserOnlyAdminMixin

from .models import Assinatura, Plano


@admin.register(Plano)
class PlanoAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "limite_mensal_mensagens", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome",)


@admin.register(Assinatura)
class AssinaturaAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("empresa", "plano", "status", "inicio", "vencimento", "carencia_ate")
    list_filter = ("status", "plano")
    search_fields = ("empresa__nome",)
    date_hierarchy = "vencimento"
