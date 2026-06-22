from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .models import Empresa, MembroEmpresa


def _superadmin_required(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Acesso restrito ao superadmin.")
    return None


# ── Gestão de empresas ────────────────────────────────────────────────────────

@login_required
def empresa_list(request):
    guard = _superadmin_required(request)
    if guard:
        return guard

    empresas = Empresa.objects.order_by("nome")
    return render(request, "empresas/empresa_list.html", {"empresas": empresas})


@login_required
def empresa_create(request):
    guard = _superadmin_required(request)
    if guard:
        return guard

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        segmento = request.POST.get("segmento", "").strip()
        cor_primaria = request.POST.get("cor_primaria", "#0d6efd").strip()
        cor_secundaria = request.POST.get("cor_secundaria", "#6c757d").strip()
        tema = request.POST.get("tema", "light")
        ativo = request.POST.get("ativo") == "on"

        if not nome:
            messages.error(request, "O nome da empresa é obrigatório.")
            return render(request, "empresas/empresa_form.html", {
                "title": "Nova Empresa",
                "values": request.POST,
            })

        empresa = Empresa.objects.create(
            nome=nome,
            segmento=segmento,
            cor_primaria=cor_primaria,
            cor_secundaria=cor_secundaria,
            tema=tema,
            ativo=ativo,
        )
        messages.success(request, f"Empresa '{empresa.nome}' criada com sucesso.")
        return redirect("empresa-detail", pk=empresa.pk)

    return render(request, "empresas/empresa_form.html", {
        "title": "Nova Empresa",
        "values": {},
    })


@login_required
def empresa_detail(request, pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    empresa = get_object_or_404(Empresa, pk=pk)
    membros = empresa.membros.select_related("usuario").order_by("usuario__username")
    return render(request, "empresas/empresa_detail.html", {
        "empresa": empresa,
        "membros": membros,
    })


@login_required
def empresa_edit(request, pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    empresa = get_object_or_404(Empresa, pk=pk)

    if request.method == "POST":
        empresa.nome = request.POST.get("nome", "").strip() or empresa.nome
        empresa.segmento = request.POST.get("segmento", "").strip()
        empresa.cor_primaria = request.POST.get("cor_primaria", "#0d6efd").strip()
        empresa.cor_secundaria = request.POST.get("cor_secundaria", "#6c757d").strip()
        empresa.tema = request.POST.get("tema", "light")
        empresa.ativo = request.POST.get("ativo") == "on"
        empresa.save()
        messages.success(request, f"Empresa '{empresa.nome}' atualizada.")
        return redirect("empresa-detail", pk=empresa.pk)

    return render(request, "empresas/empresa_form.html", {
        "title": f"Editar — {empresa.nome}",
        "empresa": empresa,
        "values": {
            "nome": empresa.nome,
            "segmento": empresa.segmento,
            "cor_primaria": empresa.cor_primaria,
            "cor_secundaria": empresa.cor_secundaria,
            "tema": empresa.tema,
            "ativo": empresa.ativo,
        },
    })


# ── Seletor de empresa (superadmin) ──────────────────────────────────────────

@login_required
def selecionar_empresa(request):
    guard = _superadmin_required(request)
    if guard:
        return guard

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

    return render(request, "empresas/selecionar_empresa.html", {
        "empresas": empresas,
        "empresa_ativa_id": empresa_ativa_id,
    })


@login_required
def sair_empresa(request):
    guard = _superadmin_required(request)
    if guard:
        return guard
    request.session.pop("active_empresa_id", None)
    return redirect("dashboard")
