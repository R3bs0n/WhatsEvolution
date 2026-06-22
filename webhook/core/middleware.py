from django.shortcuts import redirect
from django.urls import reverse


class TenantMiddleware:
    """
    Resolve qual empresa está ativa no request.

    Lógica de resolução (ordem de precedência):
    1. Superadmin com sessão active_empresa_id → usa essa empresa
    2. Usuário comum com MembroEmpresa → usa a empresa do membro ativo
    3. Sem empresa resolvida → redireciona para seletor (se logado) ou login
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None

        if request.user.is_authenticated:
            request.empresa = self._resolve_empresa(request)

        return self.get_response(request)

    def _resolve_empresa(self, request):
        from empresas.models import Empresa, MembroEmpresa

        if request.user.is_superuser:
            empresa_id = request.session.get("active_empresa_id")
            if empresa_id:
                return Empresa.objects.filter(pk=empresa_id, ativo=True).first()
            return None

        membro = (
            MembroEmpresa.objects.select_related("empresa")
            .filter(usuario=request.user, ativo=True, empresa__ativo=True)
            .first()
        )
        if membro:
            return membro.empresa

        return None
