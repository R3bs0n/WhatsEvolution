"""Gateway de validação de assinatura para o webhook público da Meta.

A Evolution (dist/main.js, POST /webhook/meta) não valida X-Hub-Signature-256
— repassa o body direto pro processamento sem tocar em headers (confirmado
lendo o código real dentro do container). Esta view é o único ponto público
autorizado a receber esse caminho: valida o HMAC-SHA256 da Meta sobre os
bytes crus do corpo e só então repassa pra Evolution. Nunca decide sozinha
se algo "parece" válido sem a assinatura bater — sem bypass de DEBUG.
"""
import hashlib
import hmac
import logging

import httpx
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

_SIGNATURE_PREFIX = "sha256="
_MAX_BODY_BYTES = 1 * 1024 * 1024  # payloads da Meta são pequenos; margem generosa
_FORWARD_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


def _evolution_meta_url() -> str:
    return f"{settings.EVOLUTION_API_URL.rstrip('/')}/webhook/meta"


def _compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _valid_signature(secret: str, body: bytes, header_value: str) -> bool:
    if not header_value.startswith(_SIGNATURE_PREFIX):
        return False
    provided = header_value[len(_SIGNATURE_PREFIX):]
    expected = _compute_signature(secret, body)
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def _forward_response(resp: httpx.Response) -> HttpResponse:
    return HttpResponse(
        resp.content,
        status=resp.status_code,
        content_type=resp.headers.get("Content-Type"),
    )


def _handle_get(request):
    # Handshake de configuração do Meta App Dashboard (hub.verify_token /
    # hub.challenge). A Meta não assina esse GET — quem confere o
    # verify_token é a própria Evolution. Repassamos a query string CRUA
    # (não via request.GET, que perderia encoding/valores repetidos) e nunca
    # logamos o conteúdo dela, já que carrega o verify_token.
    query_string = request.META.get("QUERY_STRING", "")
    url = _evolution_meta_url() + (f"?{query_string}" if query_string else "")
    try:
        with httpx.Client(timeout=_FORWARD_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        # NUNCA logar `exc` inteiro aqui: a mensagem de exceção do httpx pode
        # incluir a URL da requisição, que carrega o hub.verify_token na
        # query string. Só o tipo da exceção, nunca o conteúdo dela.
        logger.error("Gateway Meta: erro ao repassar GET (handshake) pra Evolution (%s).", type(exc).__name__)
        return HttpResponse(status=502)
    logger.info("Gateway Meta: handshake GET repassado (status_evolution=%d).", resp.status_code)
    return _forward_response(resp)


def _handle_post(request):
    # Checa o Content-Length ANTES de tocar em request.body: ler request.body
    # materializa o corpo inteiro na memória, então uma checagem de tamanho
    # feita só depois de lê-lo não protege nada — o corpo grande já foi
    # alocado. Isso não cobre transferência chunked (sem Content-Length
    # declarado) de propósito: a defesa completa contra isso é no Caddy
    # (request_body/max_size), não aqui — ver plano de deploy.
    declared_size = request.META.get("CONTENT_LENGTH")
    if declared_size is not None:
        try:
            declared_size = int(declared_size)
        except (TypeError, ValueError):
            declared_size = None
        if declared_size is not None and declared_size > _MAX_BODY_BYTES:
            logger.warning(
                "Gateway Meta: Content-Length declarado (%s bytes, ip=%s) excede o limite — "
                "rejeitado sem ler o corpo.",
                declared_size, request.META.get("REMOTE_ADDR"),
            )
            return JsonResponse({"error": "payload too large"}, status=413)

    body = request.body  # bytes crus — nunca json.loads()+json.dumps() de novo

    if len(body) > _MAX_BODY_BYTES:
        # Defesa adicional pro caso de Content-Length ausente/mentiroso —
        # nesse ponto o corpo já foi lido, mas ainda rejeitamos antes de
        # repassar qualquer coisa pra Evolution.
        logger.warning(
            "Gateway Meta: corpo excede limite (%d bytes, ip=%s) — rejeitado sem repassar.",
            len(body), request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"error": "payload too large"}, status=413)

    secret = getattr(settings, "META_APP_SECRET", "")
    signature_header = request.headers.get("X-Hub-Signature-256", "")

    if not secret:
        # Fail-closed sempre — sem bypass de DEBUG (diferente do
        # EVOLUTION_WEBHOOK_SECRET). Log interno distingue a causa pra
        # facilitar alerta/diagnóstico, mas a resposta ao cliente é idêntica
        # à de assinatura inválida — não revelamos qual dos dois aconteceu.
        logger.error(
            "Gateway Meta: META_APP_SECRET nao configurado (ip=%s) — requisicao rejeitada.",
            request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"error": "unauthorized"}, status=401)

    if not signature_header or not _valid_signature(secret, body, signature_header):
        logger.warning(
            "Gateway Meta: assinatura ausente ou invalida (ip=%s, tamanho_corpo=%d) — requisicao rejeitada.",
            request.META.get("REMOTE_ADDR"), len(body),
        )
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        with httpx.Client(timeout=_FORWARD_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            resp = client.post(
                _evolution_meta_url(),
                content=body,
                headers={"Content-Type": request.META.get("CONTENT_TYPE", "application/json")},
            )
    except httpx.HTTPError as exc:
        # Mesma cautela do GET: só o tipo da exceção, nunca a mensagem
        # completa (evitar qualquer chance de vazar corpo/URL/headers).
        logger.error("Gateway Meta: erro ao repassar POST pra Evolution (%s).", type(exc).__name__)
        return JsonResponse({"error": "upstream error"}, status=502)

    logger.info(
        "Gateway Meta: mensagem com assinatura valida repassada (status_evolution=%d, tamanho_corpo=%d).",
        resp.status_code, len(body),
    )
    return _forward_response(resp)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def meta_webhook_gateway(request):
    if request.method == "GET":
        return _handle_get(request)
    return _handle_post(request)
