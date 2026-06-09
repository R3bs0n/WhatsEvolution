import re
import logging
from io import BytesIO

import pdfplumber

from ..models.pdf_models import PatientData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column header patterns – used to auto-detect table columns
# ---------------------------------------------------------------------------
_COL_NAME  = re.compile(r"nome|paciente|patient|name", re.I)
_COL_PHONE = re.compile(r"tel(?:efone)?|fone|cel(?:ular)?|whatsapp|phone|contato", re.I)
_COL_CPF   = re.compile(r"cpf|doc(?:umento)?|rg\b", re.I)
_COL_AGE   = re.compile(r"idade|age\b|nasc(?:imento)?|data.*nasc", re.I)
_COL_EXAM  = re.compile(r"exame|exam|procedimento|servi[çc]o|tipo", re.I)

# ---------------------------------------------------------------------------
# Fallback text-based regex patterns
# ---------------------------------------------------------------------------
_PHONE_RE = re.compile(
    r"(?:telefone|fone|cel(?:ular)?|whatsapp|tel|contato)\s*[:\-]?\s*"
    r"(\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4})"
    r"|(?<!\d)(\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4})(?!\d)",
    re.IGNORECASE,
)
_CPF_RE      = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2})\b")
_AGE_LABELED = re.compile(r"(?:idade|age)\s*[:\-]?\s*(\d{1,3})", re.IGNORECASE)
_AGE_ANOS    = re.compile(r"\b(\d{1,3})\s*anos\b", re.IGNORECASE)
_NAME_LABELED = re.compile(
    r"(?:paciente|nome|patient|name)\s*:\s*"        # requires ":"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ \t]{2,60})"
    r"(?=[ \t]*[\n,;/]|[ \t]*(?:CPF|Tel|Fone|Cel|Idade|Exame)\b|$)",
    re.IGNORECASE | re.MULTILINE,
)
_EXAM_LABELED = re.compile(
    r"(?:exame|tipo\s+de\s+exame|exam(?:ination)?|procedimento)\s*:\s*([^\n]{3,60})",
    re.IGNORECASE,
)
_KNOWN_EXAMS = [
    "Hemograma", "Glicemia", "Glicose", "Colesterol", "Triglicerídeos",
    "TSH", "T4 Livre", "T3", "Urina", "EAS", "Fezes", "EPF",
    "Creatinina", "Ureia", "PCR", "VHS", "Ferritina", "Vitamina D",
    "Vitamina B12", "Insulina", "Ácido Úrico", "Bilirrubina",
    "TGO", "AST", "TGP", "ALT", "Albumina", "Proteínas Totais",
    "Coagulograma", "Hepatite B", "Hepatite C", "HIV", "Sífilis",
    "VDRL", "Toxoplasmose", "Rubéola", "HBA1C", "Hemoglobina Glicada",
]
_KNOWN_EXAMS_RE = re.compile(
    r"\b(" + "|".join(re.escape(e) for e in _KNOWN_EXAMS) + r")\b",
    re.IGNORECASE,
)
_BLOCK_SEP = re.compile(r"\n{2,}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def _valid_phone(digits: str) -> bool:
    return len(digits) >= 12


# ---------------------------------------------------------------------------
# Strategy 1: pdfplumber table extraction
# ---------------------------------------------------------------------------

def _detect_col_map(header_row: list) -> dict | None:
    """Map field names to column indexes from a header row. Returns None if not a header."""
    result: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        cell = str(cell or "").strip()
        if not cell:
            continue
        if _COL_NAME.search(cell):
            result.setdefault("name", i)
        elif _COL_PHONE.search(cell):
            result.setdefault("phone", i)
        elif _COL_CPF.search(cell):
            result.setdefault("cpf", i)
        elif _COL_AGE.search(cell):
            result.setdefault("age", i)
        elif _COL_EXAM.search(cell):
            result.setdefault("exam_type", i)

    return result if ("name" in result or "phone" in result) else None


def _row_to_patient(row: list, col_map: dict) -> PatientData | None:
    def get(field: str) -> str:
        idx = col_map.get(field)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

    # Phone: try mapped column first, then scan every cell
    phone_raw = get("phone")
    if not phone_raw:
        for cell in row:
            m = re.search(r"\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4}", str(cell or ""))
            if m:
                phone_raw = m.group()
                break
    if not phone_raw:
        return None

    phone = _clean_phone(phone_raw)
    if not _valid_phone(phone):
        return None

    name = get("name") or "Desconhecido"
    # Skip rows where name looks like a header echo or is clearly not a person name
    if re.fullmatch(r"(nome|paciente|patient|name|todos?|all)", name, re.I):
        return None

    exam_type = get("exam_type") or "Não especificado"
    if re.fullmatch(r"(exame|exam|procedimento|tipo|todos?|all)", exam_type, re.I):
        exam_type = "Não especificado"

    cpf_raw = get("cpf")
    cpf_m = _CPF_RE.search(cpf_raw) if cpf_raw else None
    cpf = cpf_m.group(1) if cpf_m else None

    age: int | None = None
    age_raw = get("age")
    if age_raw:
        age_m = re.search(r"\d+", age_raw)
        age = int(age_m.group()) if age_m else None

    return PatientData(name=name, phone=phone, exam_type=exam_type, cpf=cpf, age=age)


def _try_table_extraction(pdf) -> list[PatientData]:
    patients: list[PatientData] = []
    seen_phones: set[str] = set()
    col_map: dict | None = None

    for page_num, page in enumerate(pdf.pages, 1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue

                # Attempt header detection on every row (headers repeat on each page)
                new_map = _detect_col_map(row)
                if new_map:
                    col_map = new_map
                    logger.debug("Page %d: detected columns %s", page_num, col_map)
                    continue

                if col_map is None:
                    continue

                try:
                    patient = _row_to_patient(row, col_map)
                except Exception as exc:
                    logger.debug("Row parse error: %s", exc)
                    continue

                if patient is None:
                    continue
                if patient.phone in seen_phones:
                    continue

                seen_phones.add(patient.phone)
                patients.append(patient)

    logger.info("Table strategy: %d patients", len(patients))
    return patients


# ---------------------------------------------------------------------------
# Strategy 2: text block extraction (fallback)
# ---------------------------------------------------------------------------

def _parse_block(block: str) -> PatientData | None:
    m = _PHONE_RE.search(block)
    if not m:
        return None
    phone = _clean_phone(m.group(1) or m.group(2) or "")
    if not _valid_phone(phone):
        return None

    name_m = _NAME_LABELED.search(block)
    name = name_m.group(1).strip() if name_m else "Desconhecido"
    if re.fullmatch(r"todos?|all", name, re.I):
        name = "Desconhecido"

    cpf_m = _CPF_RE.search(block)
    cpf = cpf_m.group(1) if cpf_m else None

    age_m = _AGE_LABELED.search(block) or _AGE_ANOS.search(block)
    age = int(age_m.group(1)) if age_m else None

    exam_m = _EXAM_LABELED.search(block)
    if exam_m:
        exam_type = exam_m.group(1).strip().rstrip(".,;")
    else:
        known = _KNOWN_EXAMS_RE.search(block)
        exam_type = known.group(1).title() if known else "Não especificado"

    return PatientData(exam_type=exam_type, phone=phone, name=name, cpf=cpf, age=age)


def _try_text_extraction(pdf) -> list[PatientData]:
    pages_text = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n".join(pages_text)
    if not full_text.strip():
        return []

    blocks = _BLOCK_SEP.split(full_text)
    patients: list[PatientData] = []
    seen_phones: set[str] = set()

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            patient = _parse_block(block)
        except Exception as exc:
            logger.debug("Block error: %s", exc)
            continue

        if patient is None:
            continue
        if patient.phone in seen_phones:
            continue

        seen_phones.add(patient.phone)
        patients.append(patient)

    logger.info("Text strategy: %d patients", len(patients))
    return patients


# ---------------------------------------------------------------------------
# Public API  (synchronous — call via run_in_executor in async context)
# ---------------------------------------------------------------------------

def extract_patients_from_pdf(content: bytes) -> list[PatientData]:
    """Parse raw PDF bytes and return PatientData records.

    Tries table extraction first (handles spreadsheet-style reports).
    Falls back to regex block parsing for labeled-field PDFs.
    """
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            patients = _try_table_extraction(pdf)
            if not patients:
                logger.info("No table data found, trying text extraction")
                patients = _try_text_extraction(pdf)
    except Exception as exc:
        logger.error("Failed to open PDF: %s", exc)
        raise ValueError(f"Não foi possível ler o PDF: {exc}") from exc

    if not patients:
        raise ValueError(
            "Nenhum paciente encontrado no PDF. "
            "Verifique se o arquivo contém dados de pacientes com telefone."
        )

    logger.info("Total extracted: %d patients", len(patients))
    return patients
