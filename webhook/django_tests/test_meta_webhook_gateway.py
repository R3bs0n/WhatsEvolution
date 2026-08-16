"""Tests for evolution/meta_gateway.py — o único receptor público autorizado
de POST /webhook/meta (Meta -> Evolution). Cobre validação de HMAC-SHA256,
fail-closed sem segredo, repasse do handshake GET, e ausência de vazamento
de segredo/assinatura/payload nos logs.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import RequestFactory, override_settings

from evolution.meta_gateway import meta_webhook_gateway

SECRET = "test-app-secret"


def _signature(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(body: bytes, signature_header: str | None = "__auto__", content_type="application/json"):
    factory = RequestFactory()
    headers = {}
    if signature_header == "__auto__":
        headers["HTTP_X_HUB_SIGNATURE_256"] = _signature(body)
    elif signature_header is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature_header
    request = factory.post(
        "/webhook/meta-gateway/", data=body, content_type=content_type, **headers,
    )
    return meta_webhook_gateway(request)


class _FakeUpstreamResponse:
    def __init__(self, status_code=200, content=b'{"status":"ok"}', headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}


def _mock_client(get_return=None, post_return=None, post_side_effect=None):
    """Constrói um patcher de evolution.meta_gateway.httpx.Client com um
    client mockado (context manager), retornando (patcher, mock_client_instance)."""
    mock_client_instance = MagicMock()
    if get_return is not None:
        mock_client_instance.get.return_value = get_return
    if post_return is not None:
        mock_client_instance.post.return_value = post_return
    if post_side_effect is not None:
        mock_client_instance.post.side_effect = post_side_effect
    mock_client_cm = MagicMock()
    mock_client_cm.__enter__.return_value = mock_client_instance
    mock_client_cm.__exit__.return_value = False
    patcher = patch("evolution.meta_gateway.httpx.Client", return_value=mock_client_cm)
    return patcher, mock_client_instance


@pytest.fixture
def mock_evolution_client():
    """Mocka o httpx.Client usado no gateway; retorna o mock do client todo,
    pra podermos afirmar 'nenhuma chamada foi feita' nos casos de rejeição."""
    fake_response = _FakeUpstreamResponse()
    patcher, mock_client_instance = _mock_client(get_return=fake_response, post_return=fake_response)
    patcher.start()
    yield mock_client_instance
    patcher.stop()


# ──────────────────────────────────────────────────────────────────────────
# POST — assinatura válida
# ──────────────────────────────────────────────────────────────────────────

@override_settings(META_APP_SECRET=SECRET)
def test_post_valid_signature_is_forwarded_and_evolution_response_returned(mock_evolution_client):
    body = json.dumps({"entry": [{"id": "waba-1"}]}).encode()
    response = _post(body)
    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'
    mock_evolution_client.post.assert_called_once()
    _args, kwargs = mock_evolution_client.post.call_args
    assert kwargs["content"] == body  # bytes crus, sem reserializar


@override_settings(META_APP_SECRET=SECRET)
def test_post_valid_signature_forwards_exact_content_type(mock_evolution_client):
    body = b'{"a":1}'
    _post(body, content_type="application/json; charset=utf-8")
    _args, kwargs = mock_evolution_client.post.call_args
    assert kwargs["headers"]["Content-Type"] == "application/json; charset=utf-8"


@override_settings(META_APP_SECRET=SECRET)
def test_post_empty_body_with_correct_signature_passes(mock_evolution_client):
    response = _post(b"")
    assert response.status_code == 200
    mock_evolution_client.post.assert_called_once()


@override_settings(META_APP_SECRET=SECRET)
def test_post_unicode_body_signature_validated_over_exact_bytes(mock_evolution_client):
    body = json.dumps({"nome": "José Ñoño 日本語"}, ensure_ascii=False).encode("utf-8")
    response = _post(body)
    assert response.status_code == 200
    _args, kwargs = mock_evolution_client.post.call_args
    assert kwargs["content"] == body


@override_settings(META_APP_SECRET=SECRET)
def test_post_evolution_non_2xx_status_is_propagated():
    fake_response = _FakeUpstreamResponse(status_code=500, content=b"internal error")
    patcher, _mock = _mock_client(post_return=fake_response)
    with patcher:
        response = _post(b'{"x":1}')
    assert response.status_code == 500
    assert response.content == b"internal error"


@override_settings(META_APP_SECRET=SECRET)
def test_post_evolution_timeout_returns_502_without_leaking_internals():
    patcher, _mock = _mock_client(post_side_effect=httpx.ConnectTimeout("timed out"))
    with patcher:
        response = _post(b'{"x":1}')
    assert response.status_code == 502
    assert b"timed out" not in response.content


# ──────────────────────────────────────────────────────────────────────────
# POST — rejeições (nenhuma delas deve chamar a Evolution)
# ──────────────────────────────────────────────────────────────────────────

@override_settings(META_APP_SECRET=SECRET)
def test_post_missing_signature_header_rejected_401(mock_evolution_client):
    response = _post(b'{"x":1}', signature_header=None)
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_malformed_signature_no_prefix_rejected_401(mock_evolution_client):
    body = b'{"x":1}'
    bad_header = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()  # sem "sha256="
    response = _post(body, signature_header=bad_header)
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_malformed_signature_wrong_length_hex_rejected_401(mock_evolution_client):
    response = _post(b'{"x":1}', signature_header="sha256=abc123")
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_malformed_signature_invalid_hex_chars_rejected_401(mock_evolution_client):
    body = b'{"x":1}'
    valid = _signature(body)
    bad_header = valid.replace(valid[-1], "z" if valid[-1] != "z" else "y")
    response = _post(body, signature_header=bad_header)
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_wrong_signature_value_rejected_401(mock_evolution_client):
    response = _post(b'{"x":1}', signature_header=_signature(b"other-body"))
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_body_altered_after_signing_rejected_401(mock_evolution_client):
    """Assina um corpo, mas envia outro -- prova que valida o corpo exato recebido."""
    signature_for_original = _signature(b'{"amount": 100}')
    response = _post(b'{"amount": 999999}', signature_header=signature_for_original)
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_empty_body_with_wrong_signature_rejected_401(mock_evolution_client):
    response = _post(b"", signature_header=_signature(b"not-empty"))
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET="", DEBUG=True)
def test_post_missing_app_secret_fails_closed_even_with_debug_true(mock_evolution_client):
    """Sem bypass de DEBUG neste segredo -- diferente do EVOLUTION_WEBHOOK_SECRET."""
    body = b'{"x":1}'
    fake_secret_signature = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    response = _post(body, signature_header=fake_secret_signature)
    assert response.status_code == 401
    mock_evolution_client.post.assert_not_called()


@override_settings(META_APP_SECRET=SECRET)
def test_post_body_over_size_limit_rejected_without_forwarding(mock_evolution_client):
    from evolution.meta_gateway import _MAX_BODY_BYTES
    oversized = b"a" * (_MAX_BODY_BYTES + 1)
    response = _post(oversized, signature_header=_signature(oversized))
    assert response.status_code == 413
    mock_evolution_client.post.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# GET — handshake da Meta (hub.verify_token / hub.challenge)
# ──────────────────────────────────────────────────────────────────────────

@override_settings(META_APP_SECRET=SECRET)
def test_get_handshake_forwarded_without_signature_check():
    fake_response = _FakeUpstreamResponse(status_code=200, content=b"CHALLENGE123",
                                           headers={"Content-Type": "text/plain"})
    patcher, mock_client_instance = _mock_client(get_return=fake_response)
    with patcher:
        factory = RequestFactory()
        request = factory.get(
            "/webhook/meta-gateway/?hub.mode=subscribe&hub.verify_token=evolution&hub.challenge=CHALLENGE123"
        )
        response = meta_webhook_gateway(request)

    assert response.status_code == 200
    assert response.content == b"CHALLENGE123"
    called_url = mock_client_instance.get.call_args[0][0]
    assert "hub.verify_token=evolution" in called_url
    assert "hub.challenge=CHALLENGE123" in called_url


@override_settings(META_APP_SECRET=SECRET)
def test_get_handshake_preserves_repeated_query_params_raw():
    """A query encaminhada tem que ser EXATAMENTE a mesma string crua recebida
    -- não só conter os fragmentos, senão um re-parse/re-encode que mude a
    ordem ou duplique valores passaria despercebido."""
    fake_response = _FakeUpstreamResponse()
    patcher, mock_client_instance = _mock_client(get_return=fake_response)
    raw_query = "a=1&a=2&b=x%20y"
    with patcher:
        factory = RequestFactory()
        request = factory.get(f"/webhook/meta-gateway/?{raw_query}")
        meta_webhook_gateway(request)

    called_url = mock_client_instance.get.call_args[0][0]
    assert called_url.endswith(f"?{raw_query}")


@override_settings(META_APP_SECRET=SECRET)
def test_get_network_error_never_logs_verify_token(caplog):
    """A URL do GET carrega o hub.verify_token -- se a mensagem de exceção do
    httpx incluir a URL (comportamento real de vários erros httpx), logar o
    `exc` inteiro vazaria o token. Só o tipo da exceção pode aparecer."""
    verify_token_value = "SEGREDO_VERIFY_TOKEN_NUNCA_DEVE_VAZAR"
    patcher, _mock = _mock_client(
        get_return=None,
    )
    with patcher as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError(
            f"connection failed for url with hub.verify_token={verify_token_value}"
        )
        factory = RequestFactory()
        request = factory.get(f"/webhook/meta-gateway/?hub.verify_token={verify_token_value}")
        with caplog.at_level("DEBUG"):
            response = meta_webhook_gateway(request)

    assert response.status_code == 502
    assert verify_token_value not in caplog.text
    assert "ConnectError" in caplog.text


@override_settings(META_APP_SECRET=SECRET)
def test_get_forwards_with_expected_httpx_client_options():
    """Trava por regressão: timeout curto, sem seguir redirect, sem herdar
    variaveis de proxy do ambiente -- exatamente o que foi combinado."""
    fake_response = _FakeUpstreamResponse()
    with patch("evolution.meta_gateway.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.return_value = fake_response
        factory = RequestFactory()
        request = factory.get("/webhook/meta-gateway/?hub.challenge=x")
        meta_webhook_gateway(request)

    _args, kwargs = mock_client_cls.call_args
    assert kwargs["follow_redirects"] is False
    assert kwargs["trust_env"] is False
    assert kwargs["timeout"] is not None


@override_settings(META_APP_SECRET=SECRET)
def test_post_content_length_over_limit_rejected_before_reading_body(mock_evolution_client):
    """Corpo real pequeno, mas Content-Length declarado mentindo que é
    enorme -- tem que rejeitar usando o header, sem depender do tamanho real
    do corpo lido (a checagem por len(body) sozinha materializaria o corpo
    inteiro antes de rejeitar num ataque de verdade)."""
    from evolution.meta_gateway import _MAX_BODY_BYTES

    factory = RequestFactory()
    small_body = b'{"x":1}'
    request = factory.post(
        "/webhook/meta-gateway/", data=small_body, content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_signature(small_body),
    )
    request.META["CONTENT_LENGTH"] = str(_MAX_BODY_BYTES + 1)

    response = meta_webhook_gateway(request)
    assert response.status_code == 413
    mock_evolution_client.post.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Métodos não suportados
# ──────────────────────────────────────────────────────────────────────────

@override_settings(META_APP_SECRET=SECRET)
def test_unsupported_method_returns_405(mock_evolution_client):
    factory = RequestFactory()
    request = factory.put("/webhook/meta-gateway/", data=b"{}", content_type="application/json")
    response = meta_webhook_gateway(request)
    assert response.status_code == 405
    mock_evolution_client.post.assert_not_called()
    mock_evolution_client.get.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────
# Nenhum segredo/assinatura/payload vaza nos logs
# ──────────────────────────────────────────────────────────────────────────

@override_settings(META_APP_SECRET=SECRET)
def test_rejected_request_never_logs_secret_signature_or_payload(mock_evolution_client, caplog):
    sensitive_payload = b'{"paciente": "SEGREDO_CLINICO_SENSIVEL_XYZ"}'
    wrong_signature = _signature(b"corpo-diferente")

    with caplog.at_level("DEBUG"):
        _post(sensitive_payload, signature_header=wrong_signature)

    log_text = caplog.text
    assert SECRET not in log_text
    assert wrong_signature not in log_text
    assert "SEGREDO_CLINICO_SENSIVEL_XYZ" not in log_text


@override_settings(META_APP_SECRET=SECRET)
def test_accepted_request_never_logs_secret_signature_or_payload(mock_evolution_client, caplog):
    sensitive_payload = b'{"paciente": "OUTRO_SEGREDO_CLINICO_ABC"}'

    with caplog.at_level("DEBUG"):
        _post(sensitive_payload)

    log_text = caplog.text
    assert SECRET not in log_text
    assert "OUTRO_SEGREDO_CLINICO_ABC" not in log_text
