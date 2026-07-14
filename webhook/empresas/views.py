from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.tenant_context import session_tenant_context

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

    from whatsapp.models import CanalWhatsApp
    empresa = get_object_or_404(Empresa, pk=pk)
    membros = empresa.membros.select_related("usuario").order_by("usuario__username")
    with session_tenant_context(empresa.pk):
        canais = list(CanalWhatsApp.objects.filter(empresa=empresa).order_by("-principal", "nome"))
    return render(request, "empresas/empresa_detail.html", {
        "empresa": empresa,
        "membros": membros,
        "canais": canais,
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


# ── Gestão de canais WhatsApp por empresa ─────────────────────────────────────

@login_required
@require_POST
def canal_create(request, pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    from whatsapp.models import CanalWhatsApp
    empresa = get_object_or_404(Empresa, pk=pk)
    nome = request.POST.get("nome", "").strip()
    instance_name = request.POST.get("instance_name", "").strip()
    api_url = request.POST.get("api_url", "").strip() or "http://evolution-api:8080"
    principal = request.POST.get("principal") == "on"

    if not nome or not instance_name:
        messages.error(request, "Nome e Instance Name são obrigatórios.")
        return redirect("empresa-detail", pk=pk)

    try:
        with session_tenant_context(empresa.pk):
            CanalWhatsApp.objects.create(
                empresa=empresa,
                nome=nome,
                instance_name=instance_name,
                api_url=api_url,
                principal=principal,
                ativo=True,
            )
        messages.success(request, f"Canal '{nome}' vinculado com sucesso.")
    except IntegrityError:
        messages.error(request, f"Instance name '{instance_name}' já está em uso por outro canal.")

    return redirect("empresa-detail", pk=pk)


@login_required
@require_POST
def canal_set_principal(request, pk, canal_pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    from whatsapp.models import CanalWhatsApp
    empresa = get_object_or_404(Empresa, pk=pk)
    with session_tenant_context(empresa.pk):
        canal = get_object_or_404(CanalWhatsApp, pk=canal_pk, empresa=empresa)
        canal.principal = True
        canal.save()
    messages.success(request, f"'{canal.nome}' definido como canal principal.")
    return redirect("empresa-detail", pk=pk)


@login_required
@require_POST
def canal_toggle_ativo(request, pk, canal_pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    from whatsapp.models import CanalWhatsApp
    empresa = get_object_or_404(Empresa, pk=pk)
    with session_tenant_context(empresa.pk):
        canal = get_object_or_404(CanalWhatsApp, pk=canal_pk, empresa=empresa)
        canal.ativo = not canal.ativo
        canal.save(update_fields=["ativo"])
    estado = "ativado" if canal.ativo else "desativado"
    messages.success(request, f"Canal '{canal.nome}' {estado}.")
    return redirect("empresa-detail", pk=pk)


@login_required
@require_POST
def canal_delete(request, pk, canal_pk):
    guard = _superadmin_required(request)
    if guard:
        return guard

    from whatsapp.models import CanalWhatsApp
    empresa = get_object_or_404(Empresa, pk=pk)
    with session_tenant_context(empresa.pk):
        canal = get_object_or_404(CanalWhatsApp, pk=canal_pk, empresa=empresa)
        nome = canal.nome
        canal.delete()
    messages.success(request, f"Canal '{nome}' removido.")
    return redirect("empresa-detail", pk=pk)


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
