import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ─── Fixtures ─────────────────────────────────────────────────────

def messages_upsert_payload(from_me: bool = False, text: str = "Hello") -> dict:
    return {
        "event": "messages.upsert",
        "instance": "test",
        "data": [
            {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": from_me,
                    "id": "ABCDEF123456",
                },
                "message": {"conversation": text},
                "messageTimestamp": 1700000000,
                "pushName": "Test User",
                "status": "DELIVERY_ACK",
            }
        ],
    }


def connection_update_payload(state: str = "open") -> dict:
    return {
        "event": "connection.update",
        "instance": "test",
        "data": {"state": state, "statusReason": 200},
    }


def qrcode_payload() -> dict:
    return {
        "event": "qrcode.updated",
        "instance": "test",
        "data": {
            "pairingCode": None,
            "code": "2@abc123",
            "base64": "data:image/png;base64,ABC==",
            "count": 1,
        },
    }


def messages_update_payload() -> dict:
    return {
        "event": "messages.update",
        "instance": "test",
        "data": [
            {
                "key": {
                    "remoteJid": "5511999999999@s.whatsapp.net",
                    "fromMe": True,
                    "id": "ABCDEF123456",
                },
                "update": {"status": "READ"},
            }
        ],
    }


# ─── Health ───────────────────────────────────────────────────────

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ─── Webhook endpoint ─────────────────────────────────────────────

def test_incoming_text_message():
    response = client.post("/webhook", json=messages_upsert_payload(from_me=False))
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_outgoing_text_message():
    response = client.post("/webhook", json=messages_upsert_payload(from_me=True))
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_connection_open():
    response = client.post("/webhook", json=connection_update_payload("open"))
    assert response.status_code == 200


def test_connection_close():
    response = client.post("/webhook", json=connection_update_payload("close"))
    assert response.status_code == 200


def test_qrcode_updated():
    response = client.post("/webhook", json=qrcode_payload())
    assert response.status_code == 200


def test_messages_update():
    response = client.post("/webhook", json=messages_update_payload())
    assert response.status_code == 200


def test_unknown_event_is_ignored():
    payload = {"event": "unknown.event", "instance": "test", "data": {}}
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"received": True}


def test_webhook_by_instance_path():
    response = client.post("/webhook/test", json=messages_upsert_payload())
    assert response.status_code == 200


def test_webhook_by_instance_path_mismatch():
    response = client.post("/webhook/other_instance", json=messages_upsert_payload())
    assert response.status_code == 400


def test_missing_event_field_returns_422():
    response = client.post("/webhook", json={"instance": "test", "data": {}})
    assert response.status_code == 422
