from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone


@login_required
def dashboard(request):
    from atendimentos.models import Atendimento
    from whatsapp.models import ConfiguracaoSistema, EnvioWhatsAppLog

    today = timezone.localdate()
    total = Atendimento.objects.count()
    enviados = Atendimento.objects.filter(status_enviado="S").count()
    nao_enviados = Atendimento.objects.filter(status_enviado="N").count()
    limitados = Atendimento.objects.filter(status_enviado="L").count()
    falhas = EnvioWhatsAppLog.objects.filter(sucesso=False).count()
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
    })
