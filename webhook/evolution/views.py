import json
import logging

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

_QR_PREFIX = "evo_qr_"
_QR_TTL = 180


@csrf_exempt
def webhook_receiver(request, instance=None):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid json"}, status=400)

    event_type = payload.get("event")
    data = payload.get("data", {})
    inst = payload.get("instance", instance or "unknown")

    logger.info("Evento recebido: %s  instância: %s", event_type, inst)

    if event_type == "QRCODE_UPDATED":
        if isinstance(data, dict):
            base64_img = (data.get("qrcode") or {}).get("base64", "")
            if base64_img:
                cache.set(f"{_QR_PREFIX}{inst}", base64_img, timeout=_QR_TTL)
                logger.info("QR Code armazenado para '%s'", inst)

    elif event_type == "CONNECTION_UPDATE":
        if isinstance(data, dict):
            state = data.get("state", "")
            logger.info("Conexão '%s': %s", inst, state)
            if state == "open":
                cache.delete(f"{_QR_PREFIX}{inst}")

    elif event_type == "MESSAGES_UPSERT":
        msgs = data if isinstance(data, list) else [data]
        for msg in msgs:
            key = msg.get("key", {})
            if key.get("fromMe"):
                continue
            text = (
                (msg.get("message") or {}).get("conversation")
                or ((msg.get("message") or {}).get("extendedTextMessage") or {}).get("text", "")
            )
            logger.info("Mensagem de %s: %s", key.get("remoteJid"), text)

    return JsonResponse({"status": "received"})


def qr_display(request, instance):
    base64_img = cache.get(f"{_QR_PREFIX}{instance}")
    if not base64_img:
        html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code — {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>QR Code não disponível</h2>
  <p>A instância <b>{instance}</b> precisa estar no estado <b>connecting</b>.<br>
  Aguarde e a página recarrega automaticamente.</p>
  <script>setTimeout(()=>location.reload(),4000)</script>
</body></html>"""
        return HttpResponse(html, status=202, content_type="text/html")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code — {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>Escaneie com o WhatsApp &mdash; <b>{instance}</b></h2>
  <img src="{base64_img}"
       style="width:300px;height:300px;border:2px solid #ccc;border-radius:8px;
              display:block;margin:16px auto"/>
  <p>A página recarrega a cada 20 segundos.</p>
  <script>setTimeout(()=>location.reload(),20000)</script>
</body></html>"""
    return HttpResponse(html, content_type="text/html")
