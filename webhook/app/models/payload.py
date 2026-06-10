from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    MESSAGES_UPSERT = "MESSAGES_UPSERT"
    MESSAGES_UPDATE = "MESSAGES_UPDATE"
    MESSAGES_DELETE = "MESSAGES_DELETE"
    SEND_MESSAGE = "SEND_MESSAGE"
    CONNECTION_UPDATE = "CONNECTION_UPDATE"
    QRCODE_UPDATED = "QRCODE_UPDATED"
    PRESENCE_UPDATE = "PRESENCE_UPDATE"
    CHATS_UPSERT = "CHATS_UPSERT"
    CHATS_UPDATE = "CHATS_UPDATE"
    CHATS_DELETE = "CHATS_DELETE"
    CONTACTS_UPSERT = "CONTACTS_UPSERT"
    CONTACTS_UPDATE = "CONTACTS_UPDATE"
    GROUPS_UPSERT = "GROUPS_UPSERT"
    GROUPS_UPDATE = "GROUPS_UPDATE"
    GROUP_PARTICIPANTS_UPDATE = "GROUP_PARTICIPANTS_UPDATE"
    CALL = "CALL"
    TYPEBOT_START = "TYPEBOT_START"
    TYPEBOT_CHANGE_FLOW = "TYPEBOT_CHANGE_FLOW"
    LABELS_EDIT = "LABELS_EDIT"
    LABELS_ASSOCIATION = "LABELS_ASSOCIATION"


class MessageKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str
    participant: str | None = None


class MessageContent(BaseModel):
    conversation: str | None = None
    imageMessage: dict[str, Any] | None = None
    videoMessage: dict[str, Any] | None = None
    audioMessage: dict[str, Any] | None = None
    documentMessage: dict[str, Any] | None = None
    stickerMessage: dict[str, Any] | None = None
    extendedTextMessage: dict[str, Any] | None = None
    reactionMessage: dict[str, Any] | None = None
    locationMessage: dict[str, Any] | None = None
    contactMessage: dict[str, Any] | None = None
    buttonsResponseMessage: dict[str, Any] | None = None
    listResponseMessage: dict[str, Any] | None = None

    def text(self) -> str | None:
        if self.conversation:
            return self.conversation
        if self.extendedTextMessage:
            return self.extendedTextMessage.get("text")
        return None


class Message(BaseModel):
    key: MessageKey
    message: MessageContent | None = None
    messageTimestamp: int | None = None
    status: str | None = None
    pushName: str | None = None
    broadcast: bool | None = None


class MessageUpdate(BaseModel):
    key: MessageKey
    update: dict[str, Any]


class ConnectionUpdate(BaseModel):
    instance: str | None = None
    state: str | None = None
    statusReason: int | None = None


class QrcodeUpdate(BaseModel):
    instance: str | None = None
    pairingCode: str | None = None
    code: str | None = None
    base64: str | None = None
    count: int | None = None


class WebhookPayload(BaseModel):
    event: str
    instance: str | None = None
    destination: str | None = None
    date_time: str | None = None
    server_url: str | None = None
    apikey: str | None = None
    data: dict[str, Any] | list[Any] | None = Field(default=None)
