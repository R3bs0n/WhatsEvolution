import os
import logging

import httpx

from ..models.pdf_models import PatientData, SendResultItem

logger = logging.getLogger(__name__)

_EVOLUTION_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
_EVOLUTION_KEY = os.getenv("EVOLUTION_API_KEY", "")
_EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE_NAME", "TESTE")


async def send_whatsapp_text(patient: PatientData, template: str) -> SendResultItem:
    """Send a personalised message to *patient* via the Evolution API."""
    text = template.format(
        name=patient.name,
        exam_type=patient.exam_type,
        phone=patient.phone,
    )
    url = f"{_EVOLUTION_URL}/message/sendText/{_EVOLUTION_INSTANCE}"
    payload = {"number": patient.phone, "text": text}
    headers = {"apikey": _EVOLUTION_KEY}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        logger.info("Message sent to %s", patient.phone)
        return SendResultItem(name=patient.name, phone=patient.phone, status="sent")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.error("HTTP %d sending to %s", code, patient.phone)
        return SendResultItem(
            name=patient.name,
            phone=patient.phone,
            status="failed",
            error=f"HTTP {code}",
        )
    except Exception as exc:
        logger.error("Error sending to %s: %s", patient.phone, type(exc).__name__)
        return SendResultItem(
            name=patient.name,
            phone=patient.phone,
            status="failed",
            error=str(exc),
        )
