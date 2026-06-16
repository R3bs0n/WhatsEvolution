import json
import logging
import re

import httpx
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.integrations.evolution.client import EvolutionClient
from core.services.phone import mask_phone

logger = logging.getLogger(__name__)

_QR_PREFIX = "evo_qr_"
_QR_TTL = 180
_INSTANCE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


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

    # Evolution API v2 sends events as "qrcode.updated" or "QRCODE_UPDATED" depending on config
    event_normalized = event_type.upper().replace(".", "_") if event_type else ""

    if event_normalized == "QRCODE_UPDATED":
        if isinstance(data, dict):
            base64_img = (data.get("qrcode") or {}).get("base64", "")
            if base64_img:
                cache.set(f"{_QR_PREFIX}{inst}", base64_img, timeout=_QR_TTL)
                logger.info("QR Code armazenado para '%s'", inst)

    elif event_normalized == "CONNECTION_UPDATE":
        if isinstance(data, dict):
            state = data.get("state", "")
            logger.info("Conexão '%s': %s", inst, state)
            if state == "open":
                cache.delete(f"{_QR_PREFIX}{inst}")

    elif event_normalized == "MESSAGES_UPSERT":
        msgs = data if isinstance(data, list) else [data]
        for msg in msgs:
            key = msg.get("key", {})
            if key.get("fromMe"):
                continue
            text = (
                (msg.get("message") or {}).get("conversation")
                or ((msg.get("message") or {}).get("extendedTextMessage") or {}).get("text", "")
            )
            # Não logar o conteúdo da mensagem do paciente (pode conter dados
            # sensíveis); registrar apenas o tamanho para fins de depuração.
            logger.info(
                "Mensagem recebida de %s (%d caractere(s))",
                mask_phone(key.get("remoteJid", "")),
                len(text),
            )

    return JsonResponse({"status": "received"})


@staff_member_required(login_url="login")
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


def _qr_page(instance: str, base64_img: str) -> HttpResponse:
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code — {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>Escaneie com o WhatsApp &mdash; <b>{instance}</b></h2>
  <img src="{base64_img}"
       style="width:300px;height:300px;border:2px solid #ccc;border-radius:8px;
              display:block;margin:16px auto"/>
  <p><a href="/instancias/">&larr; Voltar para Instâncias</a></p>
</body></html>"""
    return HttpResponse(html, content_type="text/html")


@staff_member_required(login_url="login")
def instance_list(request):
    """Lista instâncias direto da Evolution API (sem cópia local) para
    garantir que o painel sempre espelhe o estado real."""
    instances = []
    try:
        instances = EvolutionClient().fetch_instances()
    except httpx.HTTPError as exc:
        logger.error("Erro ao buscar instâncias na Evolution API: %s", exc)
        messages.error(request, "Não foi possível conectar à Evolution API.")

    return render(request, "evolution/instances.html", {"instances": instances})


@staff_member_required(login_url="login")
@require_POST
def instance_create(request):
    name = (request.POST.get("instance_name") or "").strip()
    if not _INSTANCE_NAME_RE.match(name):
        messages.error(
            request,
            "Nome inválido. Use apenas letras, números, hífen ou underline (1-50 caracteres).",
        )
        return redirect("instance-list")

    integration = request.POST.get("integration") or "WHATSAPP-BAILEYS"
    if integration not in ("WHATSAPP-BAILEYS", "WHATSAPP-BUSINESS"):
        messages.error(request, "Tipo de integração inválido.")
        return redirect("instance-list")

    number = (request.POST.get("number") or "").strip()
    token = (request.POST.get("token") or "").strip()
    business_id = (request.POST.get("business_id") or "").strip()

    if integration == "WHATSAPP-BUSINESS" and (not number or not token):
        messages.error(
            request,
            "Para a API oficial (Meta), informe o número e o token de acesso.",
        )
        return redirect("instance-list")

    try:
        result = EvolutionClient().create_instance(
            name,
            integration=integration,
            number=number,
            token=token,
            business_id=business_id,
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200]
        logger.error("Erro ao criar instância '%s': %s", name, detail)
        messages.error(request, f"Evolution API recusou a criação: {detail}")
        return redirect("instance-list")
    except httpx.HTTPError as exc:
        logger.error("Erro ao criar instância '%s': %s", name, exc)
        messages.error(request, "Não foi possível conectar à Evolution API.")
        return redirect("instance-list")

    base64_img = (result.get("qrcode") or {}).get("base64", "")
    if not base64_img:
        messages.success(request, f"Instância '{name}' criada. Abra a conexão para gerar o QR Code.")
        return redirect("instance-list")

    return _qr_page(name, base64_img)


@staff_member_required(login_url="login")
def instance_connect(request, instance):
    if not _INSTANCE_NAME_RE.match(instance):
        messages.error(request, "Nome de instância inválido.")
        return redirect("instance-list")

    try:
        result = EvolutionClient().connect_instance(instance)
    except httpx.HTTPError as exc:
        logger.error("Erro ao conectar instância '%s': %s", instance, exc)
        messages.error(request, "Não foi possível obter o QR Code desta instância.")
        return redirect("instance-list")

    base64_img = result.get("base64", "")
    if not base64_img:
        messages.info(request, f"Instância '{instance}' já está conectada.")
        return redirect("instance-list")

    return _qr_page(instance, base64_img)


@staff_member_required(login_url="login")
@require_POST
def instance_delete(request, instance):
    if not _INSTANCE_NAME_RE.match(instance):
        messages.error(request, "Nome de instância inválido.")
        return redirect("instance-list")

    try:
        EvolutionClient().delete_instance(instance)
        messages.success(request, f"Instância '{instance}' excluída.")
    except httpx.HTTPError as exc:
        logger.error("Erro ao excluir instância '%s': %s", instance, exc)
        messages.error(request, "Não foi possível excluir esta instância.")

    return redirect("instance-list")
