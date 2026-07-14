import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class EvolutionClient:
    def __init__(self, instance_name: str = None, api_url: str = None):
        self.base_url = (api_url or settings.EVOLUTION_API_URL).rstrip("/")
        self.api_key = settings.EVOLUTION_API_KEY
        self.instance = instance_name or settings.EVOLUTION_INSTANCE_NAME
        self._headers = {"apikey": self.api_key, "Content-Type": "application/json"}

    def send_text(self, phone: str, message: str) -> dict:
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = {"number": phone, "text": message}
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
            return response.json()

    def fetch_instances(self) -> list[dict]:
        url = f"{self.base_url}/instance/fetchInstances"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.json()

    def create_instance(
        self,
        instance_name: str,
        integration: str = "WHATSAPP-BAILEYS",
        number: str = "",
        token: str = "",
        business_id: str = "",
    ) -> dict:
        url = f"{self.base_url}/instance/create"
        if integration == "WHATSAPP-BUSINESS":
            payload = {
                "instanceName": instance_name,
                "integration": integration,
                "number": number,
                "token": token,
            }
            if business_id:
                payload["businessId"] = business_id
        else:
            payload = {
                "instanceName": instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
            }
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload, headers=self._headers)
            response.raise_for_status()
            return response.json()

    def connect_instance(self, instance_name: str) -> dict:
        url = f"{self.base_url}/instance/connect/{instance_name}"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.json()

    def delete_instance(self, instance_name: str) -> dict:
        url = f"{self.base_url}/instance/delete/{instance_name}"
        with httpx.Client(timeout=15.0) as client:
            response = client.delete(url, headers=self._headers)
            response.raise_for_status()
            return response.json()
