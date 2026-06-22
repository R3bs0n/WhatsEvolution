from django.contrib import admin

from .models import (
    CanalWhatsApp,
    ConfiguracaoDisparo,
    ConfiguracaoSistema,
    ContatoBloqueado,
    EnvioWhatsAppLog,
    TemplateMensagem,
)


@admin.register(EnvioWhatsAppLog)
class EnvioWhatsAppLogAdmin(admin.ModelAdmin):
    list_display = ("atendimento", "empresa", "telefone", "sucesso", "status_retorno", "codigo_retorno", "enviado_em")
    list_filter = ("sucesso", "empresa", "enviado_em")
    search_fields = ("telefone", "atendimento__paciente")
    readonly_fields = ("enviado_em",)
    date_hierarchy = "enviado_em"


@admin.register(ContatoBloqueado)
class ContatoBloqueadoAdmin(admin.ModelAdmin):
    list_display = ("telefone", "empresa", "data_bloqueio")
    list_filter = ("empresa",)
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


@admin.register(CanalWhatsApp)
class CanalWhatsAppAdmin(admin.ModelAdmin):
    list_display = ("nome", "instance_name", "empresa", "principal", "ativo", "created_at")
    list_filter = ("empresa", "principal", "ativo")
    search_fields = ("nome", "instance_name")
    fieldsets = (
        (None, {"fields": ("empresa", "nome", "instance_name", "api_url")}),
        ("Config", {"fields": ("principal", "ativo")}),
    )


@admin.register(ConfiguracaoDisparo)
class ConfiguracaoDisparoAdmin(admin.ModelAdmin):
    list_display = ("empresa", "limite_diario_mensagens", "tamanho_lote", "intervalo_segundos")
    search_fields = ("empresa__nome",)

    def has_add_permission(self, request):
        from empresas.models import Empresa
        empresas_sem_config = Empresa.objects.exclude(
            pk__in=ConfiguracaoDisparo.objects.values_list("empresa_id", flat=True)
        )
        return empresas_sem_config.exists()


@admin.register(TemplateMensagem)
class TemplateMensagemAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "categoria", "ativo", "created_at")
    list_filter = ("empresa", "categoria", "ativo")
    search_fields = ("nome", "empresa__nome")
    fieldsets = (
        (None, {"fields": ("empresa", "nome", "categoria", "ativo")}),
        ("Conteúdo", {"fields": ("corpo", "variaveis_permitidas")}),
    )
