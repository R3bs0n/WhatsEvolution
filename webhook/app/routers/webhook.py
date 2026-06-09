from fastapi import APIRouter, Request, HTTPException, Query
from app.services.message_handler import handle_incoming_message
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "meu_token_verificacao")

@router.get("/")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Endpoint de verificação do webhook exigido pela Meta."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Webhook verificado com sucesso.")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificação inválido")

@router.post("/")
async def receive_message(request: Request):
    """Recebe payloads da Evolution API."""
    payload = await request.json()
    logger.debug(f"Payload recebido: {payload}")
    await handle_incoming_message(payload)
    return {"status": "received"}
