from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WhatsAppSendResult:
    success: bool
    status: str = ""
    code: Optional[str] = None
    detail: Optional[str] = None
    external_message_id: Optional[str] = None


class WhatsAppProvider(ABC):
    @abstractmethod
    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        ...

    @abstractmethod
    def send_template(
        self, phone: str, template_name: str, language: str, components: list
    ) -> WhatsAppSendResult:
        ...
