"""Tests for PDF upload/send flow.

Strategy:
- pdf_parser: mock pdfplumber so tests are fast and dependency-free.
- message_sender: mock httpx.AsyncClient to avoid real network calls.
- /pdf/upload: mock extract_patients_from_pdf + session_store.
- /pdf/send: mock send_whatsapp_text.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.pdf_models import PAGE_SIZE, PatientData, SendResultItem
from app.services.pdf_parser import (
    _clean_phone,
    _parse_block,
    extract_patients_from_pdf,
)

client = TestClient(app)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_patient(**kwargs) -> dict:
    defaults = {
        "exam_type": "Hemograma",
        "phone": "5592999999999",
        "name": "Maria da Silva",
        "cpf": "123.456.789-00",
        "age": 45,
    }
    return {**defaults, **kwargs}


def _make_patient_list(n: int) -> list[PatientData]:
    """Generate *n* distinct PatientData objects."""
    return [
        PatientData(
            exam_type="Hemograma",
            phone=f"5511{90000000 + i:08d}",
            name=f"Paciente {i}",
        )
        for i in range(n)
    ]


def _upload_patients(patients: list[PatientData]) -> dict:
    """Helper: mock upload and return parsed response body."""
    with patch("app.routers.pdf.extract_patients_from_pdf", return_value=patients):
        response = client.post(
            "/pdf/upload",
            files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert response.status_code == 200
    return response.json()


# ─── Phone normalisation ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        # Mobile (DDD 2 + 9-prefix + 8 digits = 11 digits → add 55 = 13)
        ("(92) 99999-9999", "5592999999999"),
        ("92999999999",     "5592999999999"),
        # Already normalised (13 digits)
        ("5592999999999",   "5592999999999"),
        # Landline (DDD 2 + 8 digits = 10 digits → add 55 = 12)
        ("(92)9999-9999",   "559299999999"),
        # Leading 0 stripped then 55 added (10 digits after strip)
        ("09299999999",     "559299999999"),
    ],
)
def test_clean_phone(raw, expected):
    assert _clean_phone(raw) == expected


# ─── PatientData phone validator ──────────────────────────────────────────────

def test_patient_data_normalises_phone():
    p = PatientData(exam_type="TSH", phone="(92) 99999-9999", name="João")
    assert p.phone == "5592999999999"


# ─── Block parser ─────────────────────────────────────────────────────────────

SAMPLE_BLOCK = """
Paciente: Maria da Silva
Telefone: (92) 99999-9999
CPF: 123.456.789-00
Idade: 45 anos
Exame: Hemograma
"""


def test_parse_block_extracts_all_fields():
    patient = _parse_block(SAMPLE_BLOCK)
    assert patient is not None
    assert patient.name == "Maria da Silva"
    assert patient.phone == "5592999999999"
    assert patient.cpf == "123.456.789-00"
    assert patient.age == 45
    assert patient.exam_type == "Hemograma"


def test_parse_block_returns_none_when_no_phone():
    block = "Paciente: Carlos Souza\nCPF: 000.000.000-00\nExame: Glicose"
    assert _parse_block(block) is None


def test_parse_block_returns_none_when_phone_too_short():
    block = "Telefone: 9999\nPaciente: Ana Lima\nExame: TSH"
    assert _parse_block(block) is None


def test_parse_block_falls_back_to_known_exam():
    block = "Paciente: Pedro Costa\nTelefone: (11) 98888-7777\nHemograma completo"
    patient = _parse_block(block)
    assert patient is not None
    assert "hemograma" in patient.exam_type.lower()


def test_parse_block_unknown_exam_label():
    block = "Paciente: Ana Lima\nTelefone: (11) 98888-7777"
    patient = _parse_block(block)
    assert patient is not None
    assert patient.exam_type == "Não especificado"


# ─── extract_patients_from_pdf ────────────────────────────────────────────────

def _mock_pdf_open(text: str):
    """Return a context-manager mock that yields a fake pdfplumber PDF."""
    page = MagicMock()
    page.extract_text.return_value = text
    pdf_mock = MagicMock()
    pdf_mock.__enter__ = MagicMock(return_value=pdf_mock)
    pdf_mock.__exit__ = MagicMock(return_value=False)
    pdf_mock.pages = [page]
    return pdf_mock


PDF_TEXT_TWO_PATIENTS = """
Paciente: Maria da Silva
Telefone: (92) 99999-9999
CPF: 123.456.789-00
Idade: 45 anos
Exame: Hemograma


Paciente: João Pereira
Telefone: (11) 98888-7777
CPF: 987.654.321-00
Idade: 32 anos
Exame: Glicemia
"""


def test_extract_patients_returns_list():
    with patch("app.services.pdf_parser.pdfplumber.open", return_value=_mock_pdf_open(PDF_TEXT_TWO_PATIENTS)):
        patients = extract_patients_from_pdf(b"fake-pdf")
    assert len(patients) == 2
    assert patients[0].name == "Maria da Silva"
    assert patients[1].name == "João Pereira"


def test_extract_patients_deduplicates_phone():
    duplicate_text = PDF_TEXT_TWO_PATIENTS.replace(
        "(11) 98888-7777", "(92) 99999-9999"
    )
    with patch("app.services.pdf_parser.pdfplumber.open", return_value=_mock_pdf_open(duplicate_text)):
        patients = extract_patients_from_pdf(b"fake-pdf")
    assert len(patients) == 1


def test_extract_patients_raises_on_empty_pdf():
    with patch("app.services.pdf_parser.pdfplumber.open", return_value=_mock_pdf_open("")):
        with pytest.raises(ValueError, match="Nenhum paciente encontrado"):
            extract_patients_from_pdf(b"fake-pdf")


def test_extract_patients_raises_on_bad_pdf():
    with patch(
        "app.services.pdf_parser.pdfplumber.open",
        side_effect=Exception("corrupted"),
    ):
        with pytest.raises(ValueError, match="Não foi possível"):
            extract_patients_from_pdf(b"bad-bytes")


# ─── Message template formatting ──────────────────────────────────────────────

def test_template_formatting():
    from app.models.pdf_models import DEFAULT_TEMPLATE

    patient = PatientData(**_make_patient())
    text = DEFAULT_TEMPLATE.format(
        name=patient.name,
        exam_type=patient.exam_type,
        phone=patient.phone,
    )
    assert "Maria da Silva" in text
    assert "Hemograma" in text


# ─── /pdf/upload — basic response ────────────────────────────────────────────

def test_upload_returns_patient_list_with_session():
    patients = [PatientData(**_make_patient())]
    data = _upload_patients(patients)
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["page_size"] == PAGE_SIZE
    assert data["total_pages"] == 1
    assert "session_id" in data
    assert data["patients"][0]["name"] == "Maria da Silva"


def test_upload_rejects_wrong_mime():
    response = client.post(
        "/pdf/upload",
        files={"file": ("data.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_rejects_empty_file():
    response = client.post(
        "/pdf/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_upload_returns_422_on_unreadable_pdf():
    with patch(
        "app.routers.pdf.extract_patients_from_pdf",
        side_effect=ValueError("PDF não contém texto legível"),
    ):
        response = client.post(
            "/pdf/upload",
            files={"file": ("scan.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 422


# ─── /pdf/upload — pagination (50 per page) ───────────────────────────────────

def test_upload_paginates_first_page_to_50():
    patients = _make_patient_list(120)
    data = _upload_patients(patients)
    assert data["total"] == 120
    assert data["total_pages"] == 3          # ceil(120/50)
    assert data["page"] == 1
    assert len(data["patients"]) == PAGE_SIZE  # exactly 50 on page 1


def test_upload_last_page_has_remainder():
    patients = _make_patient_list(120)
    data = _upload_patients(patients)
    sid = data["session_id"]
    # Page 3 should have 20 patients (120 - 50 - 50)
    resp = client.get(f"/pdf/patients/{sid}", params={"page": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 3
    assert len(body["patients"]) == 20


def test_upload_page_beyond_total_clamps_to_last():
    patients = _make_patient_list(10)
    data = _upload_patients(patients)
    sid = data["session_id"]
    # Requesting page 99 on a 1-page dataset should return page 1
    resp = client.get(f"/pdf/patients/{sid}", params={"page": 99})
    assert resp.status_code == 200
    assert resp.json()["page"] == 1


def test_upload_single_page_when_few_patients():
    patients = _make_patient_list(3)
    data = _upload_patients(patients)
    assert data["total_pages"] == 1
    assert len(data["patients"]) == 3


# ─── GET /pdf/patients/{session_id} ──────────────────────────────────────────

def test_get_patients_navigates_pages():
    patients = _make_patient_list(75)
    data = _upload_patients(patients)
    sid = data["session_id"]

    page2 = client.get(f"/pdf/patients/{sid}", params={"page": 2}).json()
    assert page2["page"] == 2
    assert len(page2["patients"]) == 25       # 75 - 50
    assert page2["total"] == 75
    assert page2["total_pages"] == 2


def test_get_patients_invalid_session_returns_404():
    resp = client.get("/pdf/patients/nao-existe-essa-sessao")
    assert resp.status_code == 404


def test_get_patients_preserves_all_pages_independently():
    """Each page request must return non-overlapping patient sets."""
    patients = _make_patient_list(100)
    data = _upload_patients(patients)
    sid = data["session_id"]

    page1_phones = {p["phone"] for p in data["patients"]}
    page2_phones = {p["phone"] for p in client.get(f"/pdf/patients/{sid}", params={"page": 2}).json()["patients"]}
    assert page1_phones.isdisjoint(page2_phones)


# ─── /pdf/send — batch e seleção ─────────────────────────────────────────────

def test_send_all_when_no_selection():
    sent_result = SendResultItem(name="Maria da Silva", phone="5592999999999", status="sent")
    with patch("app.routers.pdf.send_whatsapp_text", new_callable=AsyncMock, return_value=sent_result):
        response = client.post(
            "/pdf/send",
            json={
                "patients": [_make_patient()],
                "selected_phones": [],          # explicit empty → send to all
                "template": "Olá, {name}. Exame: {exam_type}.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["sent"] == 1


def test_send_dispatches_messages():
    sent_result = SendResultItem(name="Maria da Silva", phone="5592999999999", status="sent")
    with patch(
        "app.routers.pdf.send_whatsapp_text",
        new_callable=AsyncMock,
        return_value=sent_result,
    ):
        response = client.post(
            "/pdf/send",
            json={
                "patients": [_make_patient()],
                "template": "Olá, {name}. Exame: {exam_type}.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["sent"] == 1
    assert data["failed"] == 0
    assert data["results"][0]["status"] == "sent"


def test_send_only_selected_phones():
    """Only the phones listed in selected_phones should receive messages."""
    phone_a = "5592999999999"
    phone_b = "5511988887777"
    phone_c = "5521977776666"

    sent_result = SendResultItem(name="A", phone=phone_a, status="sent")
    with patch("app.routers.pdf.send_whatsapp_text", new_callable=AsyncMock, return_value=sent_result) as mock_send:
        response = client.post(
            "/pdf/send",
            json={
                "patients": [
                    _make_patient(phone=phone_a, name="A"),
                    _make_patient(phone=phone_b, name="B"),
                    _make_patient(phone=phone_c, name="C"),
                ],
                "selected_phones": [phone_a],   # send only to A
                "template": "Olá, {name}.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    # Only 1 message sent, B and C skipped
    assert data["total"] == 1
    assert data["sent"] == 1
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][0].phone == phone_a


def test_send_selected_subset_of_batch():
    """Two out of three patients selected."""
    phone_a = "5592111111111"
    phone_b = "5592222222222"
    phone_c = "5592333333333"

    sent = SendResultItem(name="X", phone=phone_a, status="sent")
    with patch("app.routers.pdf.send_whatsapp_text", new_callable=AsyncMock, return_value=sent):
        response = client.post(
            "/pdf/send",
            json={
                "patients": [
                    _make_patient(phone=phone_a, name="A"),
                    _make_patient(phone=phone_b, name="B"),
                    _make_patient(phone=phone_c, name="C"),
                ],
                "selected_phones": [phone_a, phone_b],
                "template": "Olá, {name}.",
            },
        )
    assert response.json()["total"] == 2


def test_send_records_failure_without_stopping_batch():
    results = [
        SendResultItem(name="Maria da Silva", phone="5592999999999", status="sent"),
        SendResultItem(name="João Pereira", phone="5511988887777", status="failed", error="HTTP 500"),
    ]
    with patch(
        "app.routers.pdf.send_whatsapp_text",
        new_callable=AsyncMock,
        side_effect=results,
    ):
        response = client.post(
            "/pdf/send",
            json={
                "patients": [_make_patient(), _make_patient(name="João Pereira", phone="5511988887777")],
                "template": "Olá, {name}.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["sent"] == 1
    assert data["failed"] == 1


def test_send_skips_invalid_phone():
    response = client.post(
        "/pdf/send",
        json={
            "patients": [_make_patient(phone="123")],
            "template": "Olá, {name}.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["failed"] == 1
    assert data["results"][0]["error"] == "Telefone inválido ou ausente"


def test_send_rejects_empty_list():
    response = client.post(
        "/pdf/send",
        json={"patients": [], "template": "Olá, {name}."},
    )
    assert response.status_code == 400


def test_send_zero_results_when_selection_matches_nothing():
    """If selected_phones has phones not in the patient list, nothing is sent."""
    with patch("app.routers.pdf.send_whatsapp_text", new_callable=AsyncMock) as mock_send:
        response = client.post(
            "/pdf/send",
            json={
                "patients": [_make_patient(phone="5592999999999")],
                "selected_phones": ["5500000000000"],   # not in patients
                "template": "Olá, {name}.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert mock_send.call_count == 0


# ─── message_sender unit tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_whatsapp_text_success():
    from app.services.message_sender import send_whatsapp_text

    patient = PatientData(**_make_patient())
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.message_sender.httpx.AsyncClient", return_value=mock_client):
        result = await send_whatsapp_text(patient, "Olá, {name}. Exame: {exam_type}.")

    assert result.status == "sent"
    assert result.phone == patient.phone


@pytest.mark.asyncio
async def test_send_whatsapp_text_http_error():
    import httpx
    from app.services.message_sender import send_whatsapp_text

    patient = PatientData(**_make_patient())

    http_error = httpx.HTTPStatusError(
        "500",
        request=MagicMock(),
        response=MagicMock(status_code=500),
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=http_error)

    with patch("app.services.message_sender.httpx.AsyncClient", return_value=mock_client):
        result = await send_whatsapp_text(patient, "Olá, {name}.")

    assert result.status == "failed"
    assert "500" in result.error
