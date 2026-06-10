import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class EvolutionClient:
    def __init__(self):
        self.base_url = settings.EVOLUTION_API_URL.rstrip("/")
        self.api_key = settings.EVOLUTION_API_KEY
        self.instance = settings.EVOLUTION_INSTANCE_NAME
        self._headers = {"apikey": self.api_key, "Content-Type": "application/json"}

    def send_text(self, phone: str, message: str) -> dict:
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = {"number": phone, "text": message}
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
            return response.json()
