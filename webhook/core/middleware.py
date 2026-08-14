from django.db import connection
from django.shortcuts import redirect
from django.urls import reverse
from django_otp import devices_for_user


# URLs que não precisam de 2FA configurado (login, setup, static, media, admin)
_OTP_EXEMPT_PREFIXES = (
    "/account/",
    "/logout/",
    "/static/",
    "/media/",
    "/admin/",
)


class ForceOTPSetupMiddleware:
    """
    Redireciona usuários autenticados que ainda não configuraram 2FA para a
    tela de setup. Sem isso, o django-two-factor-auth deixa entrar direto.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not any(request.path.startswith(p) for p in _OTP_EXEMPT_PREFIXES)
        ):
            if not list(devices_for_user(request.user, confirmed=True)):
                return redirect(reverse("two_factor:setup"))

        return self.get_response(request)


class TenantMiddleware:
    """
    Resolve qual empresa está ativa no request e configura o contexto RLS no PostgreSQL.

    Lógica de resolução (ordem de precedência):
    1. Superadmin com sessão active_empresa_id → usa essa empresa
    2. Usuário comum com MembroEmpresa → usa a empresa do membro ativo
    3. Sem empresa resolvida → request.empresa = None, tenant = '' (RLS bloqueia tudo)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None

        if request.user.is_authenticated:
            request.empresa = self._resolve_empresa(request)

        empresa_id = str(request.empresa.pk) if request.empresa else ''
        self._set_pg_tenant(empresa_id)

        try:
            return self.get_response(request)
        finally:
            # Resetar ao final do request — evita vazamento entre requests
            # no mesmo pool de conexão (CONN_MAX_AGE > 0).
            self._set_pg_tenant('')

    def _set_pg_tenant(self, empresa_id: str):
        try:
            with connection.cursor() as cursor:
                # set_config(name, value, is_local=false) → sessão (não apenas transação)
                cursor.execute(
                    "SELECT set_config('app.current_tenant', %s, false)",
                    [empresa_id],
                )
        except Exception:
            pass  # Não quebrar o request se o DB estiver indisponível no startup

    def _resolve_empresa(self, request):
        from empresas.models import Empresa, MembroEmpresa

        if request.user.is_superuser:
            empresa_id = request.session.get("active_empresa_id")
            if empresa_id:
                return Empresa.objects.filter(pk=empresa_id, ativo=True).first()
            return None

        membro = (
            MembroEmpresa.objects
            .select_related("empresa")
            .filter(usuario=request.user, ativo=True, empresa__ativo=True)
            .first()
        )
        if membro:
            return membro.empresa

        return None
