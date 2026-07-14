import hmac
import json
import logging
import re
from functools import wraps

import httpx
from django.contrib import messages
from django.core.cache import cache
from django.db import connection
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


def _require_superuser(view_func):
    """Restringe a view a superusuarios."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _validate_webhook_secret(request) -> bool:
    from django.conf import settings

    secret = getattr(settings, "EVOLUTION_WEBHOOK_SECRET", "")
    if not secret:
        if getattr(settings, "DEBUG", False):
            logger.warning(
                "EVOLUTION_WEBHOOK_SECRET nao configurado; aceitando webhook apenas por DEBUG=True."
            )
            return True
        logger.error("EVOLUTION_WEBHOOK_SECRET nao configurado; webhook rejeitado.")
        return False

    provided = _provided_webhook_secret(request)
    return hmac.compare_digest(provided, secret)


def _provided_webhook_secret(request) -> str:
    provided = request.headers.get("apikey", "")
    if provided:
        return provided

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""

    provided = payload.get("apikey", "")
    return provided if isinstance(provided, str) else ""


def _resolve_empresa_by_instance(inst: str):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT canal_id, empresa_id FROM resolve_canal_by_instance(%s)",
                [inst],
            )
            row = cursor.fetchone()
    except Exception as exc:
        logger.error("Nao foi possivel resolver tenant do webhook para instancia '%s': %s", inst, exc)
        return None, None

    if not row:
        return None, None

    canal_id, empresa_id = row
    from empresas.models import Empresa

    empresa = Empresa.objects.filter(pk=empresa_id, ativo=True).first()
    return canal_id, empresa


@csrf_exempt
def webhook_receiver(request, instance=None):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    if not _validate_webhook_secret(request):
        logger.warning("Webhook recebido com secret invalido (ip=%s)", request.META.get("REMOTE_ADDR"))
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid json"}, status=400)

    event_type = payload.get("event")
    data = payload.get("data", {})
    inst = payload.get("instance", instance or "unknown")

    empresa = None
    if inst and inst != "unknown":
        _canal_id, empresa = _resolve_empresa_by_instance(inst)

    logger.info("Evento recebido: %s  instancia: %s  empresa: %s", event_type, inst, empresa)

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
            logger.info("Conexao '%s': %s", inst, state)
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
            logger.info(
                "Mensagem recebida de %s (%d caractere(s))",
                mask_phone(key.get("remoteJid", "")),
                len(text),
            )

    return JsonResponse({"status": "received"})


@_require_superuser
def qr_display(request, instance):
    base64_img = cache.get(f"{_QR_PREFIX}{instance}")
    if not base64_img:
        html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code - {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>QR Code nao disponivel</h2>
  <p>A instancia <b>{instance}</b> precisa estar no estado <b>connecting</b>.<br>
  Aguarde e a pagina recarrega automaticamente.</p>
  <script>setTimeout(()=>location.reload(),4000)</script>
</body></html>"""
        return HttpResponse(html, status=202, content_type="text/html")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code - {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>Escaneie com o WhatsApp - <b>{instance}</b></h2>
  <img src="{base64_img}"
       style="width:300px;height:300px;border:2px solid #ccc;border-radius:8px;
              display:block;margin:16px auto"/>
  <p>A pagina recarrega a cada 20 segundos.</p>
  <script>setTimeout(()=>location.reload(),20000)</script>
</body></html>"""
    return HttpResponse(html, content_type="text/html")


def _qr_page(instance: str, base64_img: str) -> HttpResponse:
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>QR Code - {instance}</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>Escaneie com o WhatsApp - <b>{instance}</b></h2>
  <img src="{base64_img}"
       style="width:300px;height:300px;border:2px solid #ccc;border-radius:8px;
              display:block;margin:16px auto"/>
  <p><a href="/instancias/">&larr; Voltar para Instancias</a></p>
</body></html>"""
    return HttpResponse(html, content_type="text/html")


@_require_superuser
def instance_list(request):
    instances = []
    try:
        instances = EvolutionClient().fetch_instances()
    except httpx.HTTPError as exc:
        logger.error("Erro ao buscar instancias na Evolution API: %s", exc)
        messages.error(request, "Nao foi possivel conectar a Evolution API.")

    return render(request, "evolution/instances.html", {"instances": instances})


@_require_superuser
@require_POST
def instance_create(request):
    name = (request.POST.get("instance_name") or "").strip()
    if not _INSTANCE_NAME_RE.match(name):
        messages.error(
            request,
            "Nome invalido. Use apenas letras, numeros, hifen ou underline (1-50 caracteres).",
        )
        return redirect("instance-list")

    integration = request.POST.get("integration") or "WHATSAPP-BAILEYS"
    if integration not in ("WHATSAPP-BAILEYS", "WHATSAPP-BUSINESS"):
        messages.error(request, "Tipo de integracao invalido.")
        return redirect("instance-list")

    number = (request.POST.get("number") or "").strip()
    token = (request.POST.get("token") or "").strip()
    business_id = (request.POST.get("business_id") or "").strip()

    if integration == "WHATSAPP-BUSINESS" and (not number or not token):
        messages.error(
            request,
            "Para a API oficial (Meta), informe o numero e o token de acesso.",
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
        logger.error("Erro ao criar instancia '%s': %s", name, detail)
        messages.error(request, f"Evolution API recusou a criacao: {detail}")
        return redirect("instance-list")
    except httpx.HTTPError as exc:
        logger.error("Erro ao criar instancia '%s': %s", name, exc)
        messages.error(request, "Nao foi possivel conectar a Evolution API.")
        return redirect("instance-list")

    base64_img = (result.get("qrcode") or {}).get("base64", "")
    if not base64_img:
        messages.success(request, f"Instancia '{name}' criada. Abra a conexao para gerar o QR Code.")
        return redirect("instance-list")

    return _qr_page(name, base64_img)


@_require_superuser
def instance_connect(request, instance):
    if not _INSTANCE_NAME_RE.match(instance):
        messages.error(request, "Nome de instancia invalido.")
        return redirect("instance-list")

    try:
        result = EvolutionClient().connect_instance(instance)
    except httpx.HTTPError as exc:
        logger.error("Erro ao conectar instancia '%s': %s", instance, exc)
        messages.error(request, "Nao foi possivel obter o QR Code desta instancia.")
        return redirect("instance-list")

    base64_img = result.get("base64", "")
    if not base64_img:
        messages.info(request, f"Instancia '{instance}' ja esta conectada.")
        return redirect("instance-list")

    return _qr_page(instance, base64_img)


@_require_superuser
@require_POST
def instance_delete(request, instance):
    if not _INSTANCE_NAME_RE.match(instance):
        messages.error(request, "Nome de instancia invalido.")
        return redirect("instance-list")

    try:
        EvolutionClient().delete_instance(instance)
        messages.success(request, f"Instancia '{instance}' excluida.")
    except httpx.HTTPError as exc:
        logger.error("Erro ao excluir instancia '%s': %s", instance, exc)
        messages.error(request, "Nao foi possivel excluir esta instancia.")

    return redirect("instance-list")
