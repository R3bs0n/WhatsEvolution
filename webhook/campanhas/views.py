import csv
import io
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import empresa_required

from .models import Campanha, Contato, DestinatarioCampanha, Segmento

logger = logging.getLogger(__name__)


# ── Contatos ──────────────────────────────────────────────────────────────────

@login_required
@empresa_required
def contato_list(request):
    empresa = request.empresa
    qs = Contato.objects.for_empresa(empresa).order_by("nome")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(nome__icontains=q) | qs.filter(telefone__icontains=q)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "campanhas/contatos/list.html", {
        "page_obj": page_obj,
        "q": q,
        "total_count": paginator.count,
    })


@login_required
@empresa_required
def contato_import_csv(request):
    empresa = request.empresa
    if request.method == "POST":
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            messages.error(request, "Nenhum arquivo enviado.")
            return redirect("campanha-contato-list")

        try:
            content = arquivo.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            content = arquivo.read().decode("latin-1")

        reader = csv.DictReader(io.StringIO(content))
        criados = 0
        atualizados = 0
        erros = []

        for i, row in enumerate(reader, start=2):
            nome = (row.get("nome") or row.get("Nome") or "").strip()
            telefone = (row.get("telefone") or row.get("Telefone") or "").strip()
            email = (row.get("email") or row.get("Email") or "").strip()
            tags_raw = (row.get("tags") or row.get("Tags") or "").strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            if not nome or not telefone:
                erros.append(f"Linha {i}: nome e telefone são obrigatórios.")
                continue

            obj, created = Contato.objects.get_or_create(
                empresa=empresa,
                telefone=telefone,
                defaults={"nome": nome, "email": email, "tags": tags},
            )
            if created:
                criados += 1
            else:
                obj.nome = nome
                obj.email = email
                obj.tags = tags
                obj.save(update_fields=["nome", "email", "tags"])
                atualizados += 1

        if erros:
            for erro in erros[:5]:
                messages.warning(request, erro)
        messages.success(
            request,
            f"CSV importado: {criados} criados, {atualizados} atualizados.",
        )
        return redirect("campanha-contato-list")

    return render(request, "campanhas/contatos/import_csv.html")


# ── Segmentos ─────────────────────────────────────────────────────────────────

@login_required
@empresa_required
def segmento_list(request):
    empresa = request.empresa
    segmentos = Segmento.objects.for_empresa(empresa).order_by("nome")
    return render(request, "campanhas/segmentos/list.html", {"segmentos": segmentos})


@login_required
@empresa_required
def segmento_create(request):
    empresa = request.empresa
    contatos = Contato.objects.for_empresa(empresa).filter(ativo=True)

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        descricao = request.POST.get("descricao", "").strip()
        ids = request.POST.getlist("contatos")

        if not nome:
            messages.error(request, "Nome do segmento é obrigatório.")
        else:
            seg = Segmento.objects.create(
                empresa=empresa, nome=nome, descricao=descricao
            )
            if ids:
                seg.contatos.set(Contato.objects.for_empresa(empresa).filter(pk__in=ids))
            messages.success(request, f"Segmento '{nome}' criado com {seg.total_contatos()} contatos.")
            return redirect("campanha-segmento-list")

    return render(request, "campanhas/segmentos/form.html", {
        "contatos": contatos,
        "title": "Novo Segmento",
    })


@login_required
@empresa_required
def segmento_detail(request, pk):
    empresa = request.empresa
    seg = get_object_or_404(Segmento.objects.for_empresa(empresa), pk=pk)
    contatos = seg.contatos.all()
    return render(request, "campanhas/segmentos/detail.html", {
        "segmento": seg,
        "contatos": contatos,
    })


# ── Campanhas ─────────────────────────────────────────────────────────────────

@login_required
@empresa_required
def campanha_list(request):
    empresa = request.empresa
    qs = Campanha.objects.for_empresa(empresa).select_related("segmento").order_by("-criado_em")
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "campanhas/campanhas/list.html", {
        "page_obj": page_obj,
        "total_count": paginator.count,
    })


@login_required
@empresa_required
def campanha_create(request):
    empresa = request.empresa
    from whatsapp.models import CanalWhatsApp, TemplateMensagem
    segmentos = Segmento.objects.for_empresa(empresa)
    templates = TemplateMensagem.objects.filter(empresa=empresa, ativo=True)
    canais = CanalWhatsApp.objects.filter(empresa=empresa, ativo=True)

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        descricao = request.POST.get("descricao", "").strip()
        segmento_id = request.POST.get("segmento")
        template_id = request.POST.get("template") or None
        canal_id = request.POST.get("canal") or None
        agendado_para = request.POST.get("agendado_para") or None

        if not nome or not segmento_id:
            messages.error(request, "Nome e segmento são obrigatórios.")
        else:
            seg = get_object_or_404(Segmento.objects.for_empresa(empresa), pk=segmento_id)
            template = None
            if template_id:
                template = get_object_or_404(
                    TemplateMensagem.objects.filter(empresa=empresa, ativo=True),
                    pk=template_id,
                )
            canal = None
            if canal_id:
                canal = get_object_or_404(
                    CanalWhatsApp.objects.filter(empresa=empresa, ativo=True),
                    pk=canal_id,
                )
            campanha = Campanha.objects.create(
                empresa=empresa,
                nome=nome,
                descricao=descricao,
                segmento=seg,
                template=template,
                canal=canal,
                agendado_para=agendado_para,
                criado_por=request.user,
                status="rascunho",
            )
            messages.success(request, f"Campanha '{nome}' criada.")
            return redirect("campanha-detail", pk=campanha.pk)

    return render(request, "campanhas/campanhas/form.html", {
        "segmentos": segmentos,
        "templates": templates,
        "canais": canais,
        "title": "Nova Campanha",
    })


@login_required
@empresa_required
def campanha_detail(request, pk):
    empresa = request.empresa
    campanha = get_object_or_404(
        Campanha.objects.for_empresa(empresa).select_related("segmento", "template", "canal"),
        pk=pk,
    )
    destinatarios = campanha.destinatarios.select_related("contato").order_by("nome_snapshot")
    stats = {
        "total": destinatarios.count(),
        "enviado": destinatarios.filter(status="enviado").count(),
        "falha": destinatarios.filter(status="falha").count(),
        "pendente": destinatarios.filter(status="pendente").count(),
    }
    return render(request, "campanhas/campanhas/detail.html", {
        "campanha": campanha,
        "destinatarios": destinatarios[:100],
        "stats": stats,
    })


@login_required
@require_POST
@empresa_required
def campanha_dispatch(request, pk):
    empresa = request.empresa
    campanha = get_object_or_404(Campanha.objects.for_empresa(empresa), pk=pk)

    if campanha.status not in ("rascunho", "agendada"):
        messages.error(request, "Campanha não pode ser disparada neste status.")
        return redirect("campanha-detail", pk=pk)

    from billing.utils import empresa_pode_disparar
    from .tasks import dispatch_campanha

    pode, motivo = empresa_pode_disparar(empresa)
    if not pode:
        messages.error(request, motivo)
        return redirect("campanha-detail", pk=pk)
    campanha.status = "em_andamento"
    campanha.save(update_fields=["status"])
    dispatch_campanha.delay(campanha.pk, empresa.pk if empresa else None)
    messages.success(request, f"Disparo iniciado para campanha '{campanha.nome}'.")
    return redirect("campanha-detail", pk=pk)
