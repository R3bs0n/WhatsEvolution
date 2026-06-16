from django.contrib import admin

from .models import ContatoBloqueado, ConfiguracaoSistema, EnvioWhatsAppLog


@admin.register(EnvioWhatsAppLog)
class EnvioWhatsAppLogAdmin(admin.ModelAdmin):
    list_display = ("atendimento", "telefone", "sucesso", "status_retorno", "codigo_retorno", "enviado_em")
    list_filter = ("sucesso", "enviado_em")
    search_fields = ("telefone", "atendimento__paciente")
    readonly_fields = ("enviado_em",)
    date_hierarchy = "enviado_em"


@admin.register(ContatoBloqueado)
class ContatoBloqueadoAdmin(admin.ModelAdmin):
    list_display = ("telefone", "data_bloqueio")
    search_fields = ("telefone",)
    readonly_fields = ("data_bloqueio",)
    date_hierarchy = "data_bloqueio"


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
    list_display = ("limite_diario_mensagens",)

    def has_add_permission(self, request):
        return not ConfiguracaoSistema.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
