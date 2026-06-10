from django.contrib import admin

from .models import PdfImportLog


@admin.register(PdfImportLog)
class PdfImportLogAdmin(admin.ModelAdmin):
    list_display = ("filename", "user", "total_inseridos", "total_ignorados", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("filename",)
    readonly_fields = ("created_at", "updated_at")
