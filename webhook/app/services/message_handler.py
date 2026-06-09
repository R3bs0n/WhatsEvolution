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

    if event_type == "qrcode.updated":
        base64_img = data.get("base64") or ""
        if base64_img:
            qr_store[instance] = base64_img
            logger.info("QR Code atualizado para instância '%s' — acesse /qr/%s", instance, instance)

    elif event_type == "connection.update":
        state = data.get("state", "")
        logger.info("Conexão '%s': %s", instance, state)
        if state == "open":
            # Remove QR once connected — it's no longer valid
            qr_store.pop(instance, None)

    elif event_type == "messages.upsert":
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
