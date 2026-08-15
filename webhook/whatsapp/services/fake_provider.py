import logging

from core.services.phone import mask_phone

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class FakeWhatsAppProvider(WhatsAppProvider):
    """Stub provider for tests and development — does not call any external API."""

    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        logger.info("[FAKE] Mensagem para %s (%d caractere(s))", mask_phone(phone), len(message))
        return WhatsAppSendResult(success=True, status="FAKE_SENT", code="0")

    def send_template(
        self, phone: str, template_name: str, language: str, components: list
    ) -> WhatsAppSendResult:
        logger.info(
            "[FAKE] Template '%s' (%s) para %s, %d component(s)",
            template_name, language, mask_phone(phone), len(components),
        )
        return WhatsAppSendResult(
            success=True, status="FAKE_SENT", code="0", external_message_id="fake-wamid-0000",
        )
