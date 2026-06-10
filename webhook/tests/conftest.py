import os
import pytest

os.environ.setdefault("EVOLUTION_INSTANCE_NAME", "clinica")
os.environ.setdefault("EVOLUTION_API_URL", "http://localhost:8080")
os.environ.setdefault("EVOLUTION_API_KEY", "test_key")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as asyncio coroutine"
    )


def messages_upsert_payload(from_me: bool = False, text: str = "Hello") -> dict:
    return {
        "event": "MESSAGES_UPSERT",
        "instance": "clinica",
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
        "event": "CONNECTION_UPDATE",
        "instance": "clinica",
        "data": {"state": state, "statusReason": 200},
    }


def qrcode_payload() -> dict:
    return {
        "event": "QRCODE_UPDATED",
        "instance": "clinica",
        "data": {
            "qrcode": {
                "pairingCode": None,
                "code": "2@abc123",
                "base64": "data:image/png;base64,ABC==",
                "count": 1,
            }
        },
    }


def messages_update_payload() -> dict:
    return {
        "event": "MESSAGES_UPDATE",
        "instance": "clinica",
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
