import re
from typing import Optional
from pydantic import BaseModel, field_validator

DEFAULT_TEMPLATE = (
    "Olá, {name}. Identificamos seu exame: {exam_type}. "
    "Por favor, entre em contato conosco para mais informações."
)

PAGE_SIZE = 50


class PatientData(BaseModel):
    exam_type: str
    phone: str
    name: str
    cpf: Optional[str] = None
    age: Optional[int] = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if digits.startswith("0"):
            digits = digits[1:]
        if len(digits) in (10, 11):
            digits = "55" + digits
        return digits


class UploadResponse(BaseModel):
    session_id: str
    patients: list[PatientData]
    total: int
    page: int
    page_size: int
    total_pages: int


class SendRequest(BaseModel):
    patients: list[PatientData]
    selected_phones: list[str] = []
    template: str = DEFAULT_TEMPLATE


class SendResultItem(BaseModel):
    name: str
    phone: str
    status: str
    error: Optional[str] = None


class SendResponse(BaseModel):
    total: int
    sent: int
    failed: int
    results: list[SendResultItem]


class LogRecord(BaseModel):
    id: int
    name: str
    phone: str
    status: str
    code: int
    error: Optional[str] = None
    sent_at: str


class LogsResponse(BaseModel):
    logs: list[LogRecord]
    total: int
    page: int
    page_size: int
    total_pages: int
