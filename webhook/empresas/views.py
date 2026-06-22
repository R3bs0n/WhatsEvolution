from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .models import Empresa, MembroEmpresa


@login_required
def selecionar_empresa(request):
    """Seletor de empresa para superadmin."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Acesso restrito ao superadmin.")

    empresas = Empresa.objects.filter(ativo=True).order_by("nome")
    empresa_ativa_id = request.session.get("active_empresa_id")

    if request.method == "POST":
        empresa_id = request.POST.get("empresa_id")
        if empresa_id:
            get_object_or_404(Empresa, pk=empresa_id, ativo=True)
            request.session["active_empresa_id"] = int(empresa_id)
        else:
            request.session.pop("active_empresa_id", None)
        next_url = request.POST.get("next") or "dashboard"
        return redirect(next_url)

    return render(
        request,
        "empresas/selecionar_empresa.html",
        {
            "empresas": empresas,
            "empresa_ativa_id": empresa_ativa_id,
        },
    )


@login_required
def sair_empresa(request):
    """Remove a empresa ativa da sessão (volta à visão global)."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Acesso restrito ao superadmin.")
    request.session.pop("active_empresa_id", None)
    return redirect("dashboard")
