import logging

from core.services.phone import mask_phone

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class EvolutionWhatsAppProvider(WhatsAppProvider):
    def __init__(self, instance_name: str = None, api_url: str = None):
        from core.integrations.evolution.client import EvolutionClient
        self._client = EvolutionClient(instance_name=instance_name, api_url=api_url)

    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        import httpx
        try:
            self._client.send_text(phone, message)
            logger.info("Mensagem enviada para %s via instância '%s'", mask_phone(phone), self._client.instance)
            return WhatsAppSendResult(success=True, status="SENT", code="200")
        except httpx.HTTPStatusError as exc:
            code = str(exc.response.status_code)
            detail = exc.response.text[:200]
            logger.error("HTTP %s ao enviar para %s: %s", code, mask_phone(phone), detail)
            return WhatsAppSendResult(success=False, status="HTTP_ERROR", code=code, detail=detail)
        except Exception as exc:
            logger.error("Erro ao enviar para %s: %s", mask_phone(phone), exc)
            return WhatsAppSendResult(success=False, status="ERROR", detail=str(exc))
