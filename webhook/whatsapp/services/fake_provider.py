import logging

from core.services.phone import mask_phone

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class FakeWhatsAppProvider(WhatsAppProvider):
    """Stub provider for tests and development — does not call any external API."""

    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        logger.info("[FAKE] Mensagem para %s (%d caractere(s))", mask_phone(phone), len(message))
        return WhatsAppSendResult(success=True, status="FAKE_SENT", code="0")
