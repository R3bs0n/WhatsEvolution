import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render

from atendimentos.models import Atendimento
from whatsapp.models import EnvioWhatsAppLog
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
    qs = EnvioWhatsAppLog.objects.select_related("atendimento").order_by("-enviado_em")
    search = request.GET.get("q", "").strip()
    if search:
        qs = (
            qs.filter(telefone__icontains=search)
            | qs.filter(atendimento__paciente__icontains=search)
        )
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "whatsapp/logs.html", {"page_obj": page_obj, "search": search})
