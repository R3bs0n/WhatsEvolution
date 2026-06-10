import logging

import httpx
from django.conf import settings

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class EvolutionWhatsAppProvider(WhatsAppProvider):
    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        base_url = settings.EVOLUTION_API_URL.rstrip("/")
        instance = settings.EVOLUTION_INSTANCE_NAME
        url = f"{base_url}/message/sendText/{instance}"
        headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
        payload = {"number": phone, "text": message}

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            logger.info("Mensagem enviada para %s", phone)
            return WhatsAppSendResult(success=True, status="SENT", code="200")
        except httpx.HTTPStatusError as exc:
            code = str(exc.response.status_code)
            detail = exc.response.text[:200]
            logger.error("HTTP %s ao enviar para %s: %s", code, phone, detail)
            return WhatsAppSendResult(
                success=False,
                status="HTTP_ERROR",
                code=code,
                detail=detail,
            )
        except Exception as exc:
            logger.error("Erro ao enviar para %s: %s", phone, exc)
            return WhatsAppSendResult(
                success=False,
                status="ERROR",
                detail=str(exc),
            )
