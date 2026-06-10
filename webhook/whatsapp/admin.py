from django.contrib import admin

from .models import EnvioWhatsAppLog


@admin.register(EnvioWhatsAppLog)
class EnvioWhatsAppLogAdmin(admin.ModelAdmin):
    list_display = ("atendimento", "telefone", "sucesso", "status_retorno", "enviado_em")
    list_filter = ("sucesso", "enviado_em")
    search_fields = ("telefone", "atendimento__paciente")
    readonly_fields = ("enviado_em",)
    date_hierarchy = "enviado_em"
