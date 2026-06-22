from django.contrib import admin

from .models import Campanha, Contato, DestinatarioCampanha, Segmento


class DestinatarioCampanhaInline(admin.TabularInline):
    model = DestinatarioCampanha
    extra = 0
    readonly_fields = ("nome_snapshot", "telefone_snapshot", "status", "erro", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "telefone", "email", "ativo", "criado_em")
    list_filter = ("empresa", "ativo")
    search_fields = ("nome", "telefone", "email")


@admin.register(Segmento)
class SegmentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "total_contatos", "criado_em")
    list_filter = ("empresa",)
    search_fields = ("nome", "empresa__nome")
    filter_horizontal = ("contatos",)

    def total_contatos(self, obj):
        return obj.total_contatos()
    total_contatos.short_description = "Total de contatos"


@admin.register(Campanha)
class CampanhaAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "status", "segmento", "agendado_para", "criado_em")
    list_filter = ("empresa", "status")
    search_fields = ("nome", "empresa__nome")
    inlines = [DestinatarioCampanhaInline]
    readonly_fields = ("criado_em", "atualizado_em")
    date_hierarchy = "criado_em"


@admin.register(DestinatarioCampanha)
class DestinatarioCampanhaAdmin(admin.ModelAdmin):
    list_display = ("nome_snapshot", "telefone_snapshot", "campanha", "status", "created_at")
    list_filter = ("status", "campanha__empresa")
    search_fields = ("nome_snapshot", "telefone_snapshot")
    readonly_fields = ("created_at", "updated_at")
