"""Tests for evolution/views.py — webhook receiver and QR code display."""
import json
import pytest
from unittest.mock import patch, MagicMock
from django.test import RequestFactory, TestCase
from django.core.cache import cache

from evolution.views import webhook_receiver, qr_display, _QR_PREFIX, _QR_TTL


def _post(view, payload, instance=None):
    factory = RequestFactory()
    body = json.dumps(payload).encode()
    request = factory.post(
        "/webhook/",
        data=body,
        content_type="application/json",
    )
    return view(request, instance=instance)


# ──────────────────────────────────────────────────────────────────────────────
# Basic routing
# ──────────────────────────────────────────────────────────────────────────────

class WebhookReceiverMethodTest(TestCase):
    def test_get_returns_405(self):
        factory = RequestFactory()
        request = factory.get("/webhook/")
        response = webhook_receiver(request)
        assert response.status_code == 405

    def test_post_with_valid_json_returns_200(self):
        response = _post(webhook_receiver, {"event": "UNKNOWN", "instance": "test", "data": {}})
        assert response.status_code == 200
        assert json.loads(response.content) == {"status": "received"}

    def test_post_with_invalid_json_returns_400(self):
        factory = RequestFactory()
        request = factory.post("/webhook/", data=b"not-json", content_type="application/json")
        response = webhook_receiver(request)
        assert response.status_code == 400

    def test_unknown_event_ignored_gracefully(self):
        response = _post(webhook_receiver, {
            "event": "COMPLETELY_UNKNOWN_EVENT",
            "instance": "clinica",
            "data": {},
        })
        assert response.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Event name normalisation (lowercase dot vs UPPERCASE_UNDERSCORE)
# ──────────────────────────────────────────────────────────────────────────────

class EventNormalisationTest(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _qrcode_payload(self, event_name: str) -> dict:
        return {
            "event": event_name,
            "instance": "clinica",
            "data": {
                "qrcode": {"base64": "data:image/png;base64,TEST=="}
            },
        }

    def test_qrcode_updated_uppercase_underscore_stored(self):
        _post(webhook_receiver, self._qrcode_payload("QRCODE_UPDATED"))
        assert cache.get(f"{_QR_PREFIX}clinica") == "data:image/png;base64,TEST=="

    def test_qrcode_updated_lowercase_dot_stored(self):
        """Evolution API v2 sends 'qrcode.updated' — must be handled."""
        _post(webhook_receiver, self._qrcode_payload("qrcode.updated"))
        assert cache.get(f"{_QR_PREFIX}clinica") == "data:image/png;base64,TEST=="

    def test_connection_open_clears_qr(self):
        cache.set(f"{_QR_PREFIX}clinica", "data:image/png;base64,OLD==", _QR_TTL)
        _post(webhook_receiver, {
            "event": "CONNECTION_UPDATE",
            "instance": "clinica",
            "data": {"state": "open"},
        })
        assert cache.get(f"{_QR_PREFIX}clinica") is None

    def test_connection_open_lowercase_dot_clears_qr(self):
        cache.set(f"{_QR_PREFIX}clinica", "data:image/png;base64,OLD==", _QR_TTL)
        _post(webhook_receiver, {
            "event": "connection.update",
            "instance": "clinica",
            "data": {"state": "open"},
        })
        assert cache.get(f"{_QR_PREFIX}clinica") is None

    def test_connection_connecting_does_not_clear_qr(self):
        cache.set(f"{_QR_PREFIX}clinica", "data:image/png;base64,VALID==", _QR_TTL)
        _post(webhook_receiver, {
            "event": "CONNECTION_UPDATE",
            "instance": "clinica",
            "data": {"state": "connecting"},
        })
        # QR should still be there while connecting
        assert cache.get(f"{_QR_PREFIX}clinica") == "data:image/png;base64,VALID=="

    def test_qrcode_without_base64_field_not_stored(self):
        _post(webhook_receiver, {
            "event": "QRCODE_UPDATED",
            "instance": "clinica",
            "data": {"qrcode": {}},  # no base64 key
        })
        assert cache.get(f"{_QR_PREFIX}clinica") is None

    def test_qrcode_with_empty_base64_not_stored(self):
        _post(webhook_receiver, {
            "event": "QRCODE_UPDATED",
            "instance": "clinica",
            "data": {"qrcode": {"base64": ""}},
        })
        assert cache.get(f"{_QR_PREFIX}clinica") is None


# ──────────────────────────────────────────────────────────────────────────────
# QR display view
# ──────────────────────────────────────────────────────────────────────────────

class QrDisplayTest(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _get_qr(self, instance="clinica"):
        factory = RequestFactory()
        request = factory.get(f"/qr/{instance}/")
        return qr_display(request, instance=instance)

    def test_qr_not_available_returns_202(self):
        response = self._get_qr("clinica")
        assert response.status_code == 202
        assert b"QR Code n" in response.content  # "não disponível"

    def test_qr_available_returns_200_with_img(self):
        b64 = "data:image/png;base64,TESTQR=="
        cache.set(f"{_QR_PREFIX}clinica", b64, _QR_TTL)
        response = self._get_qr("clinica")
        assert response.status_code == 200
        assert b64.encode() in response.content

    def test_qr_page_auto_reloads_when_not_available(self):
        response = self._get_qr("clinica")
        assert b"setTimeout" in response.content

    def test_qr_page_has_instance_name(self):
        b64 = "data:image/png;base64,TESTQR=="
        cache.set(f"{_QR_PREFIX}myinstance", b64, _QR_TTL)
        response = self._get_qr("myinstance")
        assert b"myinstance" in response.content
