import csv
import json
import logging

import redis
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.decorators import empresa_required
from core.services.phone import mask_phone

from .forms import AtendimentoForm
from .models import Atendimento, StatusAtendimento

logger = logging.getLogger(__name__)

_MSG_DELAY_SECONDS = 3
_SEND_TEMPLATE_LOCK_PREFIX = "atendimento-send-template-lock:"
_SEND_TEMPLATE_LOCK_TIMEOUT = 30  # segundos -- folga acima do pior caso (1 chamada HTTP)


@login_required
@empresa_required
def atendimento_list(request):
    empresa = request.empresa
    qs = (
        Atendimento.objects.for_empresa(empresa)
        .select_related("situacao", "status_atendimento")
        .order_by("-criado_em")
    )

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
        Atendimento.objects.for_empresa(empresa)
        .exclude(exame_procedimento="")
        .values_list("exame_procedimento", flat=True)
        .distinct()
        .order_by("exame_procedimento")
    )

    status_options = StatusAtendimento.objects.for_empresa(empresa)

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
@empresa_required
def atendimento_update_status(request, pk):
    empresa = request.empresa
    obj = get_object_or_404(Atendimento.objects.for_empresa(empresa), pk=pk)
    status_id = request.POST.get("status_atendimento_id") or None
    if status_id:
        obj.status_atendimento = get_object_or_404(
            StatusAtendimento.objects.for_empresa(empresa), pk=status_id
        )
    else:
        obj.status_atendimento = None
    obj.save(update_fields=["status_atendimento"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        label = str(obj.status_atendimento) if obj.status_atendimento else "—"
        return JsonResponse({"ok": True, "label": label})
    return redirect("atendimento-list")


@login_required
@empresa_required
def atendimento_create(request):
    empresa = request.empresa
    if request.method == "POST":
        form = AtendimentoForm(request.POST, empresa=empresa)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.empresa = empresa
            obj.save()
            messages.success(request, "Atendimento criado com sucesso.")
            return redirect("atendimento-list")
    else:
        form = AtendimentoForm(empresa=empresa)
    return render(request, "atendimentos/form.html", {"form": form, "title": "Novo Atendimento"})


@login_required
@empresa_required
def atendimento_update(request, pk):
    empresa = request.empresa
    obj = get_object_or_404(Atendimento.objects.for_empresa(empresa), pk=pk)
    if request.method == "POST":
        form = AtendimentoForm(request.POST, instance=obj, empresa=empresa)
        if form.is_valid():
            form.save()
            messages.success(request, "Atendimento atualizado.")
            return redirect("atendimento-detail", pk=obj.pk)
    else:
        form = AtendimentoForm(instance=obj, empresa=empresa)
    return render(request, "atendimentos/form.html", {"form": form, "title": "Editar Atendimento", "object": obj})


@login_required
@empresa_required
def atendimento_detail(request, pk):
    empresa = request.empresa
    obj = get_object_or_404(
        Atendimento.objects.for_empresa(empresa).select_related("situacao"), pk=pk
    )
    logs = obj.whatsapp_logs.order_by("-enviado_em")[:20]
    return render(request, "atendimentos/detail.html", {"object": obj, "logs": logs})


@login_required
@empresa_required
@require_http_methods(["GET", "POST"])
def atendimento_send_template(request, pk):
    """Envio UNITÁRIO de template oficial (Cloud API) pra um Atendimento já
    salvo. Ação sempre EXPLÍCITA nesta tela -- nunca dispara a partir de
    save()/signal. Caminho totalmente separado do disparo em massa por texto
    livre (`atendimento_dispatch`, que continua intocado).

    Escopo desta etapa (aprovado com skill de arquitetura + Codex): só envio
    unitário; PDF/lote/agendamento/sincronização de template ficam fora.
    """
    from whatsapp.services.sender import (
        WhatsAppSendService,
        atendimento_template_variables,
        resolve_canal_business,
        resolve_credencial_configurada,
    )
    from whatsapp.services.template_registry import TEMPLATE_VARIABLE_ORDER, list_available_templates

    empresa = request.empresa
    obj = get_object_or_404(Atendimento.objects.for_empresa(empresa), pk=pk)

    templates_disponiveis = list_available_templates()
    default_name, default_language = templates_disponiveis[0] if templates_disponiveis else ("", "")

    def _parse_template_choice(valor_bruto):
        if valor_bruto and "::" in valor_bruto:
            nome, _, idioma = valor_bruto.partition("::")
            return nome, idioma
        return None

    # (template_name, language) sempre chegam JUNTOS num único campo
    # ("nome::idioma") -- nunca dois campos separados. Dois <option> com o
    # mesmo nome de template em idiomas diferentes teriam o mesmo `value` se
    # só o nome fosse usado, e o `selected`/POST ficaria ambíguo sobre qual
    # idioma foi escolhido de verdade (achado do Codex na revisão).
    #
    # GET sem escolha -> cai no padrão (é só a carga inicial da tela, uma
    # UX razoável). POST sem escolha, vazio ou sem "::" -> NUNCA cai no
    # padrão silenciosamente -- fica como par inválido e é recusado mais
    # abaixo (achado do Codex: um POST forjado sem separador não pode
    # acabar enviando o template padrão como se fosse o escolhido).
    if request.method == "POST":
        parsed = _parse_template_choice(request.POST.get("template_choice"))
        template_name, language = parsed if parsed else ("", "")
    else:
        parsed = _parse_template_choice(request.GET.get("template_choice"))
        template_name, language = parsed if parsed else (default_name, default_language)

    # Nunca aceitar um par (template_name, language) que não esteja
    # registrado -- inclusive vindo de POST, nunca confiar no valor bruto do
    # form. Único ponto de leitura da lista de templates: template_registry.py.
    chave_valida = (template_name, language) in TEMPLATE_VARIABLE_ORDER

    canal = resolve_canal_business(empresa)
    credencial = resolve_credencial_configurada(canal) if canal else None

    variaveis = atendimento_template_variables(obj)
    ordem_variaveis = TEMPLATE_VARIABLE_ORDER.get((template_name, language), []) if chave_valida else []
    variaveis_faltando = [nome for nome in ordem_variaveis if not variaveis.get(nome)]
    # Lista já pronta pra iterar no template (Django templates não fazem
    # lookup dinâmico de dict por variável) -- {{1}}/{{2}} são posicionais.
    parametros_preview = [
        {"posicao": i, "nome": nome, "valor": variaveis.get(nome, ""), "faltando": nome in variaveis_faltando}
        for i, nome in enumerate(ordem_variaveis)
    ]

    motivo_bloqueio = ""
    if not templates_disponiveis:
        motivo_bloqueio = "Nenhum template aprovado está registrado no sistema."
    elif not chave_valida:
        motivo_bloqueio = "Template selecionado é inválido."
    elif canal is None:
        motivo_bloqueio = (
            "Nenhum canal WHATSAPP-BUSINESS ativo/principal para esta empresa "
            "(envio por template exige Cloud API oficial, não Baileys)."
        )
    elif credencial is None:
        motivo_bloqueio = f"Credencial Meta Cloud API do canal '{canal.nome}' ausente ou não configurada."
    elif variaveis_faltando:
        motivo_bloqueio = f"Faltam dados no atendimento para: {', '.join(variaveis_faltando)}."

    pode_enviar = not motivo_bloqueio

    if request.method == "POST":
        from billing.utils import empresa_pode_disparar

        if not pode_enviar:
            messages.error(request, f"Envio recusado: {motivo_bloqueio}")
            return redirect("atendimento-send-template", pk=obj.pk)

        pode, motivo = empresa_pode_disparar(empresa)
        if not pode:
            messages.error(request, motivo)
            return redirect("atendimento-send-template", pk=obj.pk)

        lock_key = f"{_SEND_TEMPLATE_LOCK_PREFIX}{obj.pk}"
        lock = redis.Redis.from_url(settings.REDIS_URL).lock(lock_key, timeout=_SEND_TEMPLATE_LOCK_TIMEOUT)

        try:
            adquirido = lock.acquire(blocking=False)
        except redis.exceptions.RedisError as exc:
            logger.error(
                "Envio de template (lock) do atendimento %s: falha ao falar com o Redis (%s).",
                obj.pk, type(exc).__name__,
            )
            messages.error(request, "Não foi possível travar o envio (falha de infraestrutura). Tente novamente.")
            return redirect("atendimento-send-template", pk=obj.pk)

        if not adquirido:
            messages.warning(request, "Já existe um envio em andamento para este atendimento. Aguarde.")
            return redirect("atendimento-send-template", pk=obj.pk)

        try:
            sucesso = WhatsAppSendService().send_template_for_atendimento(obj, template_name, language)
        finally:
            # O envio em si (send_template_for_atendimento) já terminou aqui --
            # sucesso ou falha já foi decidido e persistido em EnvioWhatsAppLog.
            # Uma falha ao liberar o lock (ownership perdida ou erro de conexão
            # no Redis) NUNCA pode virar um 500 cru que esconda esse resultado
            # do operador e o leve a clicar Enviar de novo por engano.
            try:
                lock.release()
            except redis.exceptions.LockError:
                pass
            except redis.exceptions.RedisError as exc:
                logger.error(
                    "Envio de template (lock release) do atendimento %s: falha ao falar com o Redis (%s).",
                    obj.pk, type(exc).__name__,
                )

        if sucesso:
            messages.success(request, f"Template '{template_name}' enviado com sucesso.")
        else:
            ultimo_log = obj.whatsapp_logs.order_by("-enviado_em").first()
            detalhe = ultimo_log.status_retorno if ultimo_log else "Falha desconhecida."
            messages.error(request, f"Falha ao enviar template: {detalhe}")
        return redirect("atendimento-detail", pk=obj.pk)

    return render(request, "atendimentos/send_template.html", {
        "object": obj,
        "templates_disponiveis": templates_disponiveis,
        "template_name": template_name,
        "language": language,
        "canal": canal,
        "credencial": credencial,
        "parametros_preview": parametros_preview,
        "pode_enviar": pode_enviar,
        "motivo_bloqueio": motivo_bloqueio,
        "telefone_mascarado": mask_phone(obj.telefone) if obj.telefone else "—",
    })


@login_required
@empresa_required
def atendimento_delete(request, pk):
    empresa = request.empresa
    obj = get_object_or_404(Atendimento.objects.for_empresa(empresa), pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Atendimento excluído.")
        return redirect("atendimento-list")
    return render(request, "atendimentos/confirm_delete.html", {"object": obj})


@login_required
@empresa_required
def atendimento_dispatch(request):
    if request.method != "POST":
        return redirect("atendimento-list")

    empresa = request.empresa
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

    from billing.utils import empresa_pode_disparar
    from whatsapp.tasks import send_whatsapp_for_atendimento

    pode, motivo = empresa_pode_disparar(empresa)
    if not pode:
        messages.error(request, motivo)
        return redirect("atendimento-list")

    with transaction.atomic():
        if force == "all":
            Atendimento.objects.for_empresa(empresa).filter(
                pk__in=ids, status_enviado="S"
            ).update(status_enviado="N")

        enfileirados = list(
            Atendimento.objects.for_empresa(empresa)
            .select_for_update(skip_locked=True)
            .filter(pk__in=ids, status_enviado="N")
            .values_list("pk", flat=True)
        )
        if enfileirados:
            Atendimento.objects.for_empresa(empresa).filter(
                pk__in=enfileirados
            ).update(status_enviado="E")

    if not enfileirados:
        messages.warning(request, "Nenhum dos selecionados estava pendente para envio.")
    else:
        empresa_id = empresa.pk if empresa else None
        for i, pk in enumerate(enfileirados):
            send_whatsapp_for_atendimento.apply_async(
                args=[pk, empresa_id],
                countdown=i * _MSG_DELAY_SECONDS,
            )
        messages.success(request, f"{len(enfileirados)} mensagem(ns) enfileirada(s) para envio.")

    return redirect("atendimento-list")


@login_required
@empresa_required
def export_csv(request):
    empresa = request.empresa
    qs = (
        Atendimento.objects.for_empresa(empresa)
        .select_related("situacao")
        .order_by("-criado_em")
    )

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
