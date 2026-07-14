from django.contrib import admin

from core.admin import TenantAdminMixin

from .models import Atendimento, SituacaoAtendimento, StatusAtendimento


@admin.register(StatusAtendimento)
class StatusAtendimentoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "empresa")
    search_fields = ("nome",)


@admin.register(SituacaoAtendimento)
class SituacaoAtendimentoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("nome", "empresa", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome",)


@admin.register(Atendimento)
class AtendimentoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = (
        "paciente", "empresa", "exame_procedimento", "telefone",
        "data_agendamento", "status_atendimento", "status_enviado", "criado_em",
    )
    list_filter = ("status_enviado", "status_atendimento", "situacao", "data_agendamento")
    search_fields = ("paciente", "telefone", "exame_procedimento")
    readonly_fields = ("criado_em", "atualizado_em", "data_envio")
    date_hierarchy = "criado_em"
