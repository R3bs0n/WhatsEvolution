from django import forms
from django.contrib import admin

from core.admin import SuperuserOnlyAdminMixin, TenantAdminMixin

from .models import (
    CanalWhatsApp,
    ConfiguracaoDisparo,
    ConfiguracaoSistema,
    ContatoBloqueado,
    EnvioWhatsAppLog,
    MetaCloudCredential,
    TemplateMensagem,
)
from .services.channel_provisioning import ChannelProvisioningError, provision_meta_channel


@admin.register(EnvioWhatsAppLog)
class EnvioWhatsAppLogAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("atendimento", "empresa", "telefone", "sucesso", "status_retorno", "codigo_retorno", "enviado_em")
    list_filter = ("sucesso", "empresa", "enviado_em")
    search_fields = ("telefone", "atendimento__paciente")
    readonly_fields = ("enviado_em",)
    date_hierarchy = "enviado_em"


@admin.register(ContatoBloqueado)
class ContatoBloqueadoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("telefone", "empresa", "data_bloqueio")
    list_filter = ("empresa",)
    search_fields = ("telefone",)
    readonly_fields = ("data_bloqueio",)
    date_hierarchy = "data_bloqueio"


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("limite_diario_mensagens",)

    def has_add_permission(self, request):
        return request.user.is_superuser and not ConfiguracaoSistema.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CanalWhatsApp)
class CanalWhatsAppAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "instance_name", "empresa", "provider", "principal", "ativo", "created_at")
    list_filter = ("empresa", "provider", "principal", "ativo")
    search_fields = ("nome", "instance_name")
    fieldsets = (
        (None, {"fields": ("empresa", "nome", "instance_name", "api_url", "provider")}),
        ("Config", {"fields": ("principal", "ativo")}),
    )


class MetaCloudCredentialForm(forms.ModelForm):
    """Token é write-only: nunca é pré-preenchido nem reexibido. Deixar o
    campo 'novo_token' em branco ao salvar mantém o token atual intacto."""

    novo_token = forms.CharField(
        label="Definir/substituir token de acesso",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Deixe em branco para manter o token atual sem alteração.",
    )

    class Meta:
        model = MetaCloudCredential
        exclude = ("meta_access_token", "updated_by")

    def clean(self):
        cleaned_data = super().clean()
        # Aplica o novo token à instância ANTES do full_clean() do model
        # (chamado em _post_clean(), logo depois deste clean()), para que a
        # validação de consistência provider/token em MetaCloudCredential.clean()
        # veja o valor que está de fato sendo gravado.
        novo_token = cleaned_data.get("novo_token")
        if novo_token:
            self.instance.meta_access_token = novo_token
        return cleaned_data


@admin.register(MetaCloudCredential)
class MetaCloudCredentialAdmin(TenantAdminMixin, admin.ModelAdmin):
    form = MetaCloudCredentialForm
    list_display = ("canal", "empresa", "status", "token_status", "updated_by", "updated_at")
    list_filter = ("empresa", "status")
    search_fields = ("canal__nome", "waba_id", "phone_number_id")
    readonly_fields = ("token_status", "detalhe_provisionamento", "updated_by", "created_at", "updated_at")
    actions = ["provisionar_canal_evolution"]
    fieldsets = (
        (None, {"fields": ("empresa", "canal", "status")}),
        ("Cloud API (Meta)", {"fields": ("waba_id", "phone_number_id", "token_expires_at")}),
        ("Token", {"fields": ("token_status", "novo_token")}),
        ("Provisionamento na Evolution", {"fields": ("detalhe_provisionamento",)}),
        ("Auditoria", {"fields": ("updated_by", "created_at", "updated_at")}),
    )

    @admin.display(description="Token")
    def token_status(self, obj):
        if obj is None or not obj.pk:
            return "não definido"
        return "•••• definido" if obj.meta_access_token else "não definido"

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("novo_token"):
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    _MAX_PROVISIONAMENTO_POR_ACAO = 10

    @admin.action(description="Provisionar canal na Evolution (só cria se ainda não existir)")
    def provisionar_canal_evolution(self, request, queryset):
        """Ação EXPLÍCITA — nunca dispara sozinha a partir de um save comum.
        Escopo desta etapa: só provisionamento inicial, sem delete/recreate.

        Processa cada credencial de forma síncrona (chamada HTTP real pra
        Evolution) dentro da própria request do admin -- limita a quantidade
        selecionada de uma vez pra não arriscar timeout de request com
        seleções grandes (achado do Codex na revisão)."""
        if queryset.count() > self._MAX_PROVISIONAMENTO_POR_ACAO:
            self.message_user(
                request,
                f"Selecione no máximo {self._MAX_PROVISIONAMENTO_POR_ACAO} credenciais por vez "
                "(evita timeout da requisição — cada uma é uma chamada síncrona à Evolution).",
                level="ERROR",
            )
            return
        for credencial in queryset:
            try:
                provision_meta_channel(credencial.pk)
            except ChannelProvisioningError as exc:
                self.message_user(request, f"{credencial}: {exc}", level="ERROR")
            else:
                self.message_user(request, f"{credencial}: provisionamento concluído.", level="SUCCESS")


@admin.register(ConfiguracaoDisparo)
class ConfiguracaoDisparoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("empresa", "limite_diario_mensagens", "mensagens_por_minuto", "tamanho_lote", "intervalo_segundos")
    search_fields = ("empresa__nome",)

    def has_add_permission(self, request):
        if not request.user.is_superuser:
            return False
        from empresas.models import Empresa
        empresas_sem_config = Empresa.objects.exclude(
            pk__in=ConfiguracaoDisparo.objects.values_list("empresa_id", flat=True)
        )
        return empresas_sem_config.exists()


@admin.register(TemplateMensagem)
class TemplateMensagemAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "empresa", "categoria", "ativo", "created_at")
    list_filter = ("empresa", "categoria", "ativo")
    search_fields = ("nome", "empresa__nome")
    fieldsets = (
        (None, {"fields": ("empresa", "nome", "categoria", "ativo")}),
        ("Conteúdo", {"fields": ("corpo", "variaveis_permitidas")}),
    )
