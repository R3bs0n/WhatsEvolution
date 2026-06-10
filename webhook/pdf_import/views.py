import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from atendimentos.models import Atendimento, SituacaoAtendimento
from core.services.pdf_extractor import PDFExtractorService

from .forms import PdfUploadForm
from .models import PdfImportLog

logger = logging.getLogger(__name__)

_extractor = PDFExtractorService()


def _get_or_create_situacao(nome: str) -> SituacaoAtendimento:
    obj, _ = SituacaoAtendimento.objects.get_or_create(
        nome=nome, defaults={"ativo": True}
    )
    return obj


@login_required
def upload_pdf(request):
    logs_recentes = PdfImportLog.objects.select_related("user").order_by("-created_at")[:10]

    if request.method == "POST":
        form = PdfUploadForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES["arquivo"]
            filename = arquivo.name
            content = arquivo.read()

            try:
                records = _extractor.extract(content)
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(request, "pdf_import/upload.html", {
                    "form": form, "logs_recentes": logs_recentes
                })

            situacao_padrao = _get_or_create_situacao("Agendado")
            inseridos = 0
            ignorados = 0

            for rec in records:
                if not rec.telefone:
                    ignorados += 1
                    continue

                data_agend = None
                if rec.data_agendamento_raw:
                    import re as _re
                    m = _re.search(r"(\d{2})[/\-](\d{2})[/\-](\d{2,4})", rec.data_agendamento_raw)
                    if m:
                        day, month, year = m.group(1), m.group(2), m.group(3)
                        if len(year) == 2:
                            year = "20" + year
                        try:
                            from datetime import date
                            data_agend = date(int(year), int(month), int(day))
                        except ValueError:
                            pass

                Atendimento.objects.create(
                    situacao=situacao_padrao,
                    paciente=rec.paciente,
                    telefone=rec.telefone,
                    exame_procedimento=rec.exame_procedimento,
                    idade=rec.idade,
                    data_agendamento=data_agend,
                    pdf_nome_arquivo=filename,
                    data_extracao=timezone.now(),
                    status_enviado="N",
                )
                inseridos += 1

            status = "SUCESSO" if ignorados == 0 else ("PARCIAL" if inseridos > 0 else "ERRO")
            PdfImportLog.objects.create(
                filename=filename,
                user=request.user,
                total_extraidos=len(records),
                total_inseridos=inseridos,
                total_ignorados=ignorados,
                status=status,
            )

            messages.success(
                request,
                f"PDF importado: {inseridos} atendimentos criados, {ignorados} ignorados.",
            )
            return redirect("atendimento-list")
    else:
        form = PdfUploadForm()

    return render(request, "pdf_import/upload.html", {
        "form": form, "logs_recentes": logs_recentes
    })
