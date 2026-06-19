from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


@login_required
def dashboard(request):
    from atendimentos.models import Atendimento
    from pdf_import.models import PdfImportLog
    from whatsapp.models import ConfiguracaoSistema, EnvioWhatsAppLog

    today = timezone.localdate()

    # Period filter
    periodo_param = request.GET.get("periodo", "")
    periodo_date = None
    if periodo_param:
        try:
            year, month = map(int, periodo_param.split("-"))
            periodo_date = date(year, month, 1)
        except (ValueError, AttributeError):
            periodo_date = None

    periodos_disponiveis = (
        PdfImportLog.objects
        .filter(periodo__isnull=False)
        .values_list("periodo", flat=True)
        .distinct()
        .order_by("-periodo")
    )
    periodos_choices = [
        (p.strftime("%Y-%m"), f"{MESES_PT[p.month - 1]} {p.year}")
        for p in periodos_disponiveis
    ]

    # Summary cards (affected by period filter)
    qs = Atendimento.objects
    if periodo_date:
        qs = qs.filter(pdf_import__periodo=periodo_date)

    total = qs.count()
    enviados = qs.filter(status_enviado="S").count()
    nao_enviados = qs.filter(status_enviado="N").count()
    limitados = qs.filter(status_enviado="L").count()

    falhas_qs = EnvioWhatsAppLog.objects.filter(sucesso=False)
    if periodo_date:
        falhas_qs = falhas_qs.filter(atendimento__pdf_import__periodo=periodo_date)
    falhas = falhas_qs.count()

    # Today / month — always global (not filtered by period)
    importados_hoje = Atendimento.objects.filter(criado_em__date=today).count()
    mensagens_hoje = EnvioWhatsAppLog.objects.filter(
        enviado_em__date=today, sucesso=True
    ).count()
    mensagens_mes = Atendimento.objects.filter(
        status_enviado="S",
        data_envio__year=today.year,
        data_envio__month=today.month,
    ).count()

    config = ConfiguracaoSistema.get()
    limite_diario = config.limite_diario_mensagens
    percentual_limite = min(round((mensagens_hoje / limite_diario) * 100), 100) if limite_diario else 0

    return render(request, "dashboard.html", {
        "total": total,
        "enviados": enviados,
        "nao_enviados": nao_enviados,
        "limitados": limitados,
        "falhas": falhas,
        "importados_hoje": importados_hoje,
        "mensagens_hoje": mensagens_hoje,
        "mensagens_mes": mensagens_mes,
        "limite_diario": limite_diario,
        "percentual_limite": percentual_limite,
        "periodos_choices": periodos_choices,
        "periodo_atual": periodo_param,
        "today": today,
    })
