import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AtendimentoForm
from .models import Atendimento


@login_required
def atendimento_list(request):
    qs = Atendimento.objects.select_related("situacao").order_by("-criado_em")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(paciente__icontains=q) | qs.filter(telefone__icontains=q)
    status = request.GET.get("status", "")
    if status in ("N", "S"):
        qs = qs.filter(status_enviado=status)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "atendimentos/list.html", {
        "page_obj": page_obj, "q": q, "status": status,
    })


@login_required
def atendimento_create(request):
    if request.method == "POST":
        form = AtendimentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Atendimento criado com sucesso.")
            return redirect("atendimento-list")
    else:
        form = AtendimentoForm()
    return render(request, "atendimentos/form.html", {"form": form, "title": "Novo Atendimento"})


@login_required
def atendimento_update(request, pk):
    obj = get_object_or_404(Atendimento, pk=pk)
    if request.method == "POST":
        form = AtendimentoForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Atendimento atualizado.")
            return redirect("atendimento-detail", pk=obj.pk)
    else:
        form = AtendimentoForm(instance=obj)
    return render(request, "atendimentos/form.html", {"form": form, "title": "Editar Atendimento", "object": obj})


@login_required
def atendimento_detail(request, pk):
    obj = get_object_or_404(Atendimento.objects.select_related("situacao"), pk=pk)
    logs = obj.whatsapp_logs.order_by("-enviado_em")[:20]
    return render(request, "atendimentos/detail.html", {"object": obj, "logs": logs})


@login_required
def atendimento_delete(request, pk):
    obj = get_object_or_404(Atendimento, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Atendimento excluído.")
        return redirect("atendimento-list")
    return render(request, "atendimentos/confirm_delete.html", {"object": obj})


@login_required
def export_csv(request):
    qs = Atendimento.objects.select_related("situacao").order_by("-criado_em")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(paciente__icontains=q) | qs.filter(telefone__icontains=q)
    status = request.GET.get("status", "")
    if status in ("N", "S"):
        qs = qs.filter(status_enviado=status)

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = 'attachment; filename="atendimentos.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "ID", "Paciente", "Telefone", "Exame/Procedimento",
        "Data Agendamento", "Horário", "Status Envio", "Data Envio", "Situação",
    ])
    for a in qs:
        writer.writerow([
            a.pk, a.paciente, a.telefone, a.exame_procedimento,
            a.data_agendamento or "", a.horario_agendamento or "",
            a.get_status_enviado_display(), a.data_envio or "", a.situacao,
        ])
    return response
