import uuid
from ..models.pdf_models import PatientData

# Simple in-memory store — entries persist for the process lifetime.
# Acceptable for a dev/test environment; replace with Redis for production.
_store: dict[str, list[PatientData]] = {}


def create_session(patients: list[PatientData]) -> str:
    sid = str(uuid.uuid4())
    _store[sid] = list(patients)
    return sid


def get_session(sid: str) -> list[PatientData] | None:
    return _store.get(sid)
