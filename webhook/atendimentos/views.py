import csv
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AtendimentoForm
from .models import Atendimento, StatusAtendimento

logger = logging.getLogger(__name__)

_MSG_DELAY_SECONDS = 3


@login_required
def atendimento_list(request):
    qs = Atendimento.objects.select_related("situacao", "status_atendimento").order_by("-criado_em")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(paciente__icontains=q) | Q(telefone__icontains=q))

    status = request.GET.get("status", "")
    if status in ("N", "E", "S", "L"):
        qs = qs.filter(status_enviado=status)

    tipo = request.GET.get("tipo", "").strip()
    if tipo:
        qs = qs.filter(exame_procedimento__icontains=tipo)

    status_clinico = request.GET.get("status_clinico", "").strip()
    if status_clinico:
        if status_clinico == "sem_status":
            qs = qs.filter(status_atendimento__isnull=True)
        else:
            qs = qs.filter(status_atendimento__pk=status_clinico)

    tipos_exame = (
        Atendimento.objects
        .exclude(exame_procedimento="")
        .values_list("exame_procedimento", flat=True)
        .distinct()
        .order_by("exame_procedimento")
    )

    status_options = StatusAtendimento.objects.all()

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "atendimentos/list.html", {
        "page_obj": page_obj,
        "q": q,
        "status": status,
        "tipo": tipo,
        "status_clinico": status_clinico,
        "tipos_exame": tipos_exame,
        "status_options": status_options,
        "total_count": paginator.count,
    })


@login_required
@require_POST
def atendimento_update_status(request, pk):
    obj = get_object_or_404(Atendimento, pk=pk)
    status_id = request.POST.get("status_atendimento_id") or None
    if status_id:
        obj.status_atendimento = get_object_or_404(StatusAtendimento, pk=status_id)
    else:
        obj.status_atendimento = None
    obj.save(update_fields=["status_atendimento"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        label = str(obj.status_atendimento) if obj.status_atendimento else "—"
        return JsonResponse({"ok": True, "label": label})
    return redirect("atendimento-list")


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
def atendimento_dispatch(request):
    if request.method != "POST":
        return redirect("atendimento-list")

    force = request.POST.get("force", "pending")
    raw_ids = request.POST.getlist("ids")
    if not raw_ids:
        messages.warning(request, "Nenhum atendimento selecionado.")
        return redirect("atendimento-list")
    try:
        ids = [int(i) for i in raw_ids]
    except ValueError:
        messages.error(request, "Seleção inválida.")
        return redirect("atendimento-list")

    from whatsapp.tasks import send_whatsapp_for_atendimento

    with transaction.atomic():
        if force == "all":
            # Reseta registros já enviados para "N" para que possam ser reenviados
            Atendimento.objects.filter(pk__in=ids, status_enviado="S").update(status_enviado="N")

        enfileirados = list(
            Atendimento.objects
            .select_for_update(skip_locked=True)
            .filter(pk__in=ids, status_enviado="N")
            .values_list("pk", flat=True)
        )
        if enfileirados:
            Atendimento.objects.filter(pk__in=enfileirados).update(status_enviado="E")

    if not enfileirados:
        messages.warning(request, "Nenhum dos selecionados estava pendente para envio.")
    else:
        for i, pk in enumerate(enfileirados):
            send_whatsapp_for_atendimento.apply_async(
                args=[pk],
                countdown=i * _MSG_DELAY_SECONDS,
            )
        messages.success(request, f"{len(enfileirados)} mensagem(ns) enfileirada(s) para envio.")

    return redirect("atendimento-list")



@login_required
def export_csv(request):
    qs = Atendimento.objects.select_related("situacao").order_by("-criado_em")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(paciente__icontains=q) | Q(telefone__icontains=q))
    status = request.GET.get("status", "")
    if status in ("N", "E", "S", "L"):
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
