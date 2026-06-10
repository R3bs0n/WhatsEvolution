from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone


@login_required
def dashboard(request):
    from atendimentos.models import Atendimento
    from whatsapp.models import EnvioWhatsAppLog

    today = timezone.localdate()
    total = Atendimento.objects.count()
    enviados = Atendimento.objects.filter(status_enviado="S").count()
    nao_enviados = Atendimento.objects.filter(status_enviado="N").count()
    falhas = EnvioWhatsAppLog.objects.filter(sucesso=False).count()
    importados_hoje = Atendimento.objects.filter(criado_em__date=today).count()
    mensagens_hoje = Atendimento.objects.filter(
        status_enviado="S", data_envio__date=today
    ).count()
    mensagens_mes = Atendimento.objects.filter(
        status_enviado="S",
        data_envio__year=today.year,
        data_envio__month=today.month,
    ).count()

    return render(request, "dashboard.html", {
        "total": total,
        "enviados": enviados,
        "nao_enviados": nao_enviados,
        "falhas": falhas,
        "importados_hoje": importados_hoje,
        "mensagens_hoje": mensagens_hoje,
        "mensagens_mes": mensagens_mes,
    })
