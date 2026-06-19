import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from atendimentos.models import Atendimento
from whatsapp.models import ContatoBloqueado, EnvioWhatsAppLog
from whatsapp.tasks import send_whatsapp_for_atendimento

logger = logging.getLogger(__name__)

_LOTE_SIZE = 300
# Delay entre mensagens consecutivas (segundos). Reduz risco de ban no WhatsApp.
_MSG_DELAY_SECONDS = 3


@login_required
def send_panel(request):
    pendentes_qs = Atendimento.objects.filter(status_enviado__in=["N"]).order_by("-criado_em")
    total_pendentes = pendentes_qs.count()
    total_lote = min(total_pendentes, _LOTE_SIZE)

    if request.method == "POST":
        # Marca atomicamente como "E" (Enfileirado) antes de despachar,
        # evitando que um segundo clique reenfileire os mesmos registros.
        with transaction.atomic():
            ids = list(
                Atendimento.objects
                .select_for_update(skip_locked=True)
                .filter(status_enviado="N")
                .order_by("-criado_em")
                .values_list("pk", flat=True)[:_LOTE_SIZE]
            )
            if ids:
                Atendimento.objects.filter(pk__in=ids).update(status_enviado="E")

        if not ids:
            messages.warning(request, "Nenhum atendimento pendente para envio.")
        else:
            for i, pk in enumerate(ids):
                # countdown espaça os envios: msg 0 parte imediatamente,
                # msg 1 parte em 3s, msg 2 em 6s, etc.
                send_whatsapp_for_atendimento.apply_async(
                    args=[pk],
                    countdown=i * _MSG_DELAY_SECONDS,
                )
            messages.success(request, f"{len(ids)} mensagens enfileiradas para envio.")

    return render(request, "whatsapp/send.html", {
        "total_pendentes": total_pendentes,
        "total_lote": total_lote,
    })


@login_required
def logs(request):
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "delete_selected":
            ids = request.POST.getlist("ids")
            if ids:
                deleted, _ = (
                    EnvioWhatsAppLog.objects
                    .filter(pk__in=ids, sucesso=False)
                    .exclude(status_retorno__iexact="BLOQUEADO")
                    .delete()
                )
                messages.success(request, f"{deleted} registro(s) de falha excluído(s).")
            else:
                messages.warning(request, "Nenhum registro selecionado.")
        elif action == "delete_all_falha":
            deleted, _ = (
                EnvioWhatsAppLog.objects
                .filter(sucesso=False)
                .exclude(status_retorno__iexact="BLOQUEADO")
                .delete()
            )
            messages.success(request, f"{deleted} registro(s) de falha excluído(s).")
        return redirect(request.get_full_path().split("?")[0] + "?" + request.POST.get("query_string", ""))

    qs = EnvioWhatsAppLog.objects.select_related("atendimento").order_by("-enviado_em")
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "todos").lower()

    if search:
        qs = qs.filter(telefone__icontains=search) | qs.filter(atendimento__paciente__icontains=search)

    if status_filter == "enviado":
        qs = qs.filter(sucesso=True)
    elif status_filter == "bloqueado":
        qs = qs.filter(sucesso=False, status_retorno__iexact="BLOQUEADO")
    elif status_filter == "falha":
        qs = qs.filter(sucesso=False).exclude(status_retorno__iexact="BLOQUEADO")

    total_count = qs.count()
    falha_count = (
        qs.filter(sucesso=False).exclude(status_retorno__iexact="BLOQUEADO").count()
        if status_filter in ("todos", "falha") else 0
    )

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    import urllib.parse
    query_string = urllib.parse.urlencode({k: v for k, v in request.GET.items() if k != "page"})

    return render(request, "whatsapp/logs.html", {
        "page_obj": page_obj,
        "search": search,
        "status_filter": status_filter,
        "total_count": total_count,
        "falha_count": falha_count,
        "query_string": query_string,
    })


@login_required
def optout_list(request):
    if request.method == "POST":
        telefone = request.POST.get("telefone", "").strip()
        if telefone:
            try:
                ContatoBloqueado.objects.create(telefone=telefone)
                messages.success(request, f"Número {telefone} adicionado à lista de bloqueados.")
            except IntegrityError:
                messages.warning(request, f"Número {telefone} já está na lista de bloqueados.")
        else:
            messages.error(request, "Informe um número de telefone válido.")
        return redirect("whatsapp-optout")

    qs = ContatoBloqueado.objects.order_by("-data_bloqueio")
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "whatsapp/optout_list.html", {"page_obj": page_obj})


@login_required
@require_POST
def optout_delete(request, pk):
    obj = get_object_or_404(ContatoBloqueado, pk=pk)
    obj.delete()
    messages.success(request, f"Número {obj.telefone} removido da lista de bloqueados.")
    return redirect("whatsapp-optout")
