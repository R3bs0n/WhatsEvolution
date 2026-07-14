from django.contrib import admin

from core.admin import TenantAdminMixin

from .models import PdfImportLog


@admin.register(PdfImportLog)
class PdfImportLogAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("filename", "empresa", "user", "total_inseridos", "total_ignorados", "status", "created_at")
    list_filter = ("status", "empresa", "created_at")
    search_fields = ("filename",)
    readonly_fields = ("created_at", "updated_at")
