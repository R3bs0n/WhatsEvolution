import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from math import ceil

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ..models.pdf_models import (
    LogRecord, LogsResponse, PAGE_SIZE,
    SendRequest, SendResponse, SendResultItem, UploadResponse,
)
from ..services.log_store import append_batch
from ..services.log_store import query as query_logs
from ..services.message_sender import send_whatsapp_text
from ..services.pdf_parser import extract_patients_from_pdf
from ..services.session_store import create_session, get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pdf", tags=["pdf"])
_executor = ThreadPoolExecutor(max_workers=2)

_ALLOWED_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


def _paginate(patients, session_id: str, page: int) -> UploadResponse:
    total = len(patients)
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = min(max(1, page), total_pages)
    start = (page - 1) * PAGE_SIZE
    return UploadResponse(
        session_id=session_id,
        patients=patients[start : start + PAGE_SIZE],
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        total_pages=total_pages,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    page: int = Query(1, ge=1),
) -> UploadResponse:
    """Recebe PDF, extrai pacientes e retorna a 1ª página (50 por página). Sem envio."""
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Tipo inválido '{file.content_type}'. Envie um PDF.")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Arquivo vazio.")

    try:
        loop = asyncio.get_event_loop()
        patients = await loop.run_in_executor(_executor, extract_patients_from_pdf, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    session_id = create_session(patients)
    logger.info("PDF '%s' — %d paciente(s), session=%s", file.filename, len(patients), session_id)
    return _paginate(patients, session_id, page)


@router.get("/patients/{session_id}", response_model=UploadResponse)
async def get_patients_page(
    session_id: str,
    page: int = Query(1, ge=1),
) -> UploadResponse:
    """Retorna uma página de pacientes de uma sessão existente."""
    patients = get_session(session_id)
    if patients is None:
        raise HTTPException(404, "Sessão não encontrada. Faça o upload novamente.")
    return _paginate(patients, session_id, page)


@router.post("/send", response_model=SendResponse)
async def send_messages(request: SendRequest) -> SendResponse:
    """Dispara mensagens WhatsApp. selected_phones vazio = envia para todos."""
    if not request.patients:
        raise HTTPException(400, "Lista de pacientes vazia.")

    if request.selected_phones:
        selected_set = set(request.selected_phones)
        to_send = [p for p in request.patients if p.phone in selected_set]
    else:
        to_send = list(request.patients)

    results: list[SendResultItem] = []
    for patient in to_send:
        if not patient.phone or len(patient.phone) < 12:
            results.append(SendResultItem(
                name=patient.name, phone=patient.phone,
                status="failed", error="Telefone inválido",
            ))
            continue
        result = await send_whatsapp_text(patient, request.template)
        results.append(result)

    sent = sum(1 for r in results if r.status == "sent")
    failed = len(results) - sent

    append_batch(results)

    logger.info("Batch — total=%d sent=%d failed=%d", len(results), sent, failed)
    return SendResponse(total=len(results), sent=sent, failed=failed, results=results)


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> LogsResponse:
    """Retorna histórico paginado de envios com filtro opcional."""
    logs, total, actual_page, total_pages = query_logs(search, page, page_size)
    return LogsResponse(
        logs=[
            LogRecord(id=l.id, name=l.name, phone=l.phone,
                      status=l.status, code=l.code, error=l.error, sent_at=l.sent_at)
            for l in logs
        ],
        total=total,
        page=actual_page,
        page_size=page_size,
        total_pages=total_pages,
    )
