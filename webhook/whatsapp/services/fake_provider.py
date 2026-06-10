import logging

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class FakeWhatsAppProvider(WhatsAppProvider):
    """Stub provider for tests and development — does not call any external API."""

    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        logger.info("[FAKE] Mensagem para %s: %s", phone, message[:60])
        return WhatsAppSendResult(success=True, status="FAKE_SENT", code="0")
