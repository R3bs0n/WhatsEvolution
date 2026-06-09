from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    MESSAGES_UPSERT = "messages.upsert"
    MESSAGES_UPDATE = "messages.update"
    MESSAGES_DELETE = "messages.delete"
    SEND_MESSAGE = "send.message"
    CONNECTION_UPDATE = "connection.update"
    QRCODE_UPDATED = "qrcode.updated"
    PRESENCE_UPDATE = "presence.update"
    CHATS_UPSERT = "chats.upsert"
    CHATS_UPDATE = "chats.update"
    CHATS_DELETE = "chats.delete"
    CONTACTS_UPSERT = "contacts.upsert"
    CONTACTS_UPDATE = "contacts.update"
    GROUPS_UPSERT = "groups.upsert"
    GROUPS_UPDATE = "groups.update"
    GROUP_PARTICIPANTS_UPDATE = "group-participants.update"
    NEW_JWT_TOKEN = "new.jwt"
    CALL = "call"
    TYPEBOT_START = "typebot.start"
    TYPEBOT_CHANGE_FLOW = "typebot.changeFlow"
    LABELS_EDIT = "labels.edit"
    LABELS_ASSOCIATION = "labels.association"


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
