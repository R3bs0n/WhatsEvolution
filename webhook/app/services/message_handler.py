import logging

logger = logging.getLogger(__name__)

# Stores the latest QR code per instance: { "BAILEYS": "data:image/png;base64,..." }
qr_store: dict[str, str] = {}


async def handle_incoming_message(payload: dict):
    """Central event handler for Evolution API webhook events."""
    event_type = payload.get("event")
    data = payload.get("data", {})
    instance = payload.get("instance", "unknown")

    logger.info("Evento recebido: %s  instância: %s", event_type, instance)

    if event_type == "QRCODE_UPDATED":
        base64_img = data.get("qrcode", {}).get("base64") or ""
        if base64_img:
            qr_store[instance] = base64_img
            logger.info("QR Code atualizado para instância '%s' — acesse /qr/%s", instance, instance)

    elif event_type == "CONNECTION_UPDATE":
        state = data.get("state", "")
        logger.info("Conexão '%s': %s", instance, state)
        if state == "open":
            qr_store.pop(instance, None)

    elif event_type == "MESSAGES_UPSERT":
        messages = data if isinstance(data, list) else [data]
        for msg in messages:
            key = msg.get("key", {})
            if key.get("fromMe"):
                continue
            message = msg.get("message", {})
            sender = key.get("remoteJid", "desconhecido")
            text = (
                message.get("conversation")
                or message.get("extendedTextMessage", {}).get("text", "")
            )
            logger.info("Mensagem de %s: %s", sender, text)
