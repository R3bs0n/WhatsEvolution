from django.contrib import admin


class TenantAdminMixin:
    """
    Escopa querysets do Admin por empresa para usuários não-superusuários.

    Camada de defesa adicional ao RLS do PostgreSQL.
    Superusuários veem todos os dados (útil para suporte e diagnóstico).
    Usuários comuns (is_staff sem is_superuser) são restritos à sua empresa.
    """

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        empresa = getattr(request, "empresa", None)
        if empresa:
            return qs.filter(empresa=empresa)
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "empresa" and not request.user.is_superuser:
            from empresas.models import Empresa

            empresa = getattr(request, "empresa", None)
            kwargs["queryset"] = (
                Empresa.objects.filter(pk=empresa.pk)
                if empresa
                else Empresa.objects.none()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class SuperuserOnlyAdminMixin:
    """Restringe modelos globais/sensiveis do Django Admin ao superuser."""

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
