import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (
    messages_upsert_payload,
    connection_update_payload,
    qrcode_payload,
    messages_update_payload,
)

client = TestClient(app)


# ─── Health ───────────────────────────────────────────────────────

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ─── Webhook endpoint ─────────────────────────────────────────────

def test_incoming_text_message():
    response = client.post("/webhook/", json=messages_upsert_payload(from_me=False))
    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_outgoing_text_message():
    response = client.post("/webhook/", json=messages_upsert_payload(from_me=True))
    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_connection_open():
    response = client.post("/webhook/", json=connection_update_payload("open"))
    assert response.status_code == 200


def test_connection_close():
    response = client.post("/webhook/", json=connection_update_payload("close"))
    assert response.status_code == 200


def test_qrcode_updated_stores_base64():
    from app.services.message_handler import qr_store
    response = client.post("/webhook/", json=qrcode_payload())
    assert response.status_code == 200
    assert qr_store.get("clinica") == "data:image/png;base64,ABC=="


def test_connection_open_clears_qr():
    from app.services.message_handler import qr_store
    qr_store["clinica"] = "data:image/png;base64,FAKE=="
    response = client.post("/webhook/", json=connection_update_payload("open"))
    assert response.status_code == 200
    assert "clinica" not in qr_store


def test_messages_update():
    response = client.post("/webhook/", json=messages_update_payload())
    assert response.status_code == 200


def test_unknown_event_is_ignored():
    payload = {"event": "UNKNOWN_EVENT", "instance": "clinica", "data": {}}
    response = client.post("/webhook/", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_webhook_by_instance_path():
    response = client.post("/webhook/clinica", json=messages_upsert_payload())
    assert response.status_code == 200


def test_webhook_by_instance_path_mismatch():
    response = client.post("/webhook/outra_instancia", json=messages_upsert_payload())
    assert response.status_code == 400


def test_missing_event_field_returns_200_and_ignores():
    response = client.post("/webhook/", json={"instance": "clinica", "data": {}})
    assert response.status_code == 200
