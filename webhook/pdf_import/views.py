import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from atendimentos.models import SituacaoAtendimento
from core.services.pdf_extractor import PDFExtractorService
from pdf_import.repository import bulk_import_records

from .forms import PdfUploadForm
from .models import PdfImportLog

MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def get_periodo_choices():
    """Gera opções de mês/ano: 24 meses atrás até 3 meses à frente."""
    today = date.today()
    choices = []
    year, month = today.year, today.month - 24
    while month <= 0:
        month += 12
        year -= 1
    for _ in range(28):
        choices.append((f"{year}-{month:02d}", f"{MESES_PT[month - 1]} {year}"))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return choices


logger = logging.getLogger(__name__)

_extractor = PDFExtractorService()


def _get_or_create_situacao(nome: str, empresa=None) -> SituacaoAtendimento:
    obj, _ = SituacaoAtendimento.objects.get_or_create(
        nome=nome, empresa=empresa, defaults={"ativo": True}
    )
    return obj


@login_required
def upload_pdf(request):
    empresa = request.empresa
    logs_recentes = (
        PdfImportLog.objects.for_empresa(empresa)
        .select_related("user")
        .order_by("-created_at")[:10]
    )
    imported_filenames = list(
        PdfImportLog.objects.for_empresa(empresa)
        .values_list("filename", flat=True)
        .distinct()
    )

    if request.method == "POST":
        form = PdfUploadForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES["arquivo"]
            filename = arquivo.name
            content = arquivo.read()

            log = PdfImportLog.objects.create(
                empresa=empresa,
                filename=filename,
                user=request.user,
                status="PARCIAL",
            )
            try:
                records_iter = _extractor.iter_records(content)
                situacao = _get_or_create_situacao("Agendado", empresa=empresa)
                result = bulk_import_records(
                    records_iter, situacao, filename, pdf_import_log=log, empresa=empresa
                )
            except ValueError as exc:
                log.delete()
                messages.error(request, str(exc))
                return render(request, "pdf_import/upload.html", {
                    "form": form,
                    "logs_recentes": logs_recentes,
                    "imported_filenames": imported_filenames,
                })

            status = (
                "SUCESSO" if result.total_ignorados == 0
                else ("PARCIAL" if result.total_inseridos > 0 else "ERRO")
            )
            log.total_extraidos = result.total_extraidos
            log.total_inseridos = result.total_inseridos
            log.total_ignorados = result.total_ignorados
            log.status = status
            log.save()

            messages.success(
                request,
                f"PDF importado: {result.total_inseridos} atendimentos criados, "
                f"{result.total_ignorados} ignorados.",
            )
            return redirect("atendimento-list")
    else:
        form = PdfUploadForm()

    return render(request, "pdf_import/upload.html", {
        "form": form,
        "logs_recentes": logs_recentes,
        "imported_filenames": imported_filenames,
    })


@login_required
def edit_pdf_log(request, pk):
    empresa = request.empresa
    log = get_object_or_404(PdfImportLog.objects.for_empresa(empresa), pk=pk)
    periodo_choices = get_periodo_choices()
    periodo_atual = log.periodo.strftime("%Y-%m") if log.periodo else ""

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        periodo_raw = request.POST.get("periodo", "").strip()
        periodo_date = None
        if periodo_raw:
            try:
                year, month = map(int, periodo_raw.split("-"))
                periodo_date = date(year, month, 1)
            except (ValueError, AttributeError):
                messages.error(request, "Período inválido.")
                return render(request, "pdf_import/edit_log.html", {
                    "log": log,
                    "periodo_choices": periodo_choices,
                    "periodo_atual": periodo_atual,
                })
        log.nome = nome
        log.periodo = periodo_date
        log.save(update_fields=["nome", "periodo", "updated_at"])
        messages.success(request, "PDF atualizado com sucesso.")
        return redirect("pdf-upload")

    return render(request, "pdf_import/edit_log.html", {
        "log": log,
        "periodo_choices": periodo_choices,
        "periodo_atual": periodo_atual,
    })
