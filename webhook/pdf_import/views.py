import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from atendimentos.models import SituacaoAtendimento
from core.services.pdf_extractor import PDFExtractorService
from pdf_import.repository import bulk_import_records

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
    imported_filenames = list(PdfImportLog.objects.values_list("filename", flat=True).distinct())

    if request.method == "POST":
        form = PdfUploadForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = request.FILES["arquivo"]
            filename = arquivo.name
            content = arquivo.read()

            try:
                records_iter = _extractor.iter_records(content)
                situacao = _get_or_create_situacao("Agendado")
                result = bulk_import_records(records_iter, situacao, filename)
            except ValueError as exc:
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
            PdfImportLog.objects.create(
                filename=filename,
                user=request.user,
                total_extraidos=result.total_extraidos,
                total_inseridos=result.total_inseridos,
                total_ignorados=result.total_ignorados,
                status=status,
            )

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
