"""PDF extraction service for 'Relação dos Agendamentos' SUS format.

Tries pdfplumber table extraction first, falls back to text-block regex.
Returns a list of dicts ready to feed into Atendimento model creation.
"""
from __future__ import annotations

import re
import logging
from io import BytesIO
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

_COL_NAME = re.compile(r"nome|paciente|patient|name", re.I)
_COL_PHONE = re.compile(r"tel(?:efone)?|fone|cel(?:ular)?|whatsapp|phone|contato", re.I)
_COL_AGE = re.compile(r"idade|age\b|nasc(?:imento)?|data.*nasc", re.I)
_COL_EXAM = re.compile(r"exame|exam|procedimento|servi[çc]o|tipo", re.I)
_COL_DATE = re.compile(r"data|date|agend(?:amento)?", re.I)
_COL_TIME = re.compile(r"hor(?:ario|a)\b|time\b", re.I)

_PHONE_RE = re.compile(
    r"(?:telefone|fone|cel(?:ular)?|whatsapp|tel|contato)\s*[:\-]?\s*"
    r"(\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4})"
    r"|(?<!\d)(\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4})(?!\d)",
    re.IGNORECASE,
)
_NAME_LABELED = re.compile(
    r"(?:paciente|nome|patient|name)\s*:\s*"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ \t]{2,60})"
    r"(?=[ \t]*[\n,;/]|[ \t]*(?:CPF|Tel|Fone|Cel|Idade|Exame)\b|$)",
    re.IGNORECASE | re.MULTILINE,
)
_EXAM_LABELED = re.compile(
    r"(?:exame|tipo\s+de\s+exame|exam(?:ination)?|procedimento)\s*:\s*([^\n]{3,60})",
    re.IGNORECASE,
)
_AGE_LABELED = re.compile(r"(?:idade|age)\s*[:\-]?\s*(\d{1,3})", re.IGNORECASE)
_AGE_ANOS = re.compile(r"\b(\d{1,3})\s*anos\b", re.IGNORECASE)
_BLOCK_SEP = re.compile(r"\n{2,}")


@dataclass
class ExtractedRecord:
    paciente: str = ""
    telefone: str = ""
    exame_procedimento: str = ""
    idade: Optional[int] = None
    data_agendamento_raw: str = ""
    horario_agendamento_raw: str = ""


def _clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def _valid_phone(digits: str) -> bool:
    return 12 <= len(digits) <= 13


def _detect_col_map(row: list) -> dict | None:
    result: dict[str, int] = {}
    for i, cell in enumerate(row):
        cell = str(cell or "").strip()
        if not cell:
            continue
        if _COL_NAME.search(cell):
            result.setdefault("name", i)
        elif _COL_PHONE.search(cell):
            result.setdefault("phone", i)
        elif _COL_AGE.search(cell):
            result.setdefault("age", i)
        elif _COL_EXAM.search(cell):
            result.setdefault("exam", i)
        elif _COL_DATE.search(cell):
            result.setdefault("date", i)
        elif _COL_TIME.search(cell):
            result.setdefault("time", i)
    return result if ("name" in result or "phone" in result) else None


def _row_to_record(row: list, col_map: dict) -> ExtractedRecord | None:
    def get(key: str) -> str:
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

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
    if re.fullmatch(r"(nome|paciente|patient|name|todos?|all)", name, re.I):
        return None

    exam = get("exam") or "Não especificado"
    if re.fullmatch(r"(exame|exam|procedimento|tipo|todos?|all)", exam, re.I):
        exam = "Não especificado"

    age_raw = get("age")
    age: int | None = None
    if age_raw:
        m = re.search(r"\d+", age_raw)
        age = int(m.group()) if m else None

    return ExtractedRecord(
        paciente=name,
        telefone=phone,
        exame_procedimento=exam,
        idade=age,
        data_agendamento_raw=get("date"),
        horario_agendamento_raw=get("time"),
    )


def _try_table_extraction(pdf) -> list[ExtractedRecord]:
    records: list[ExtractedRecord] = []
    seen: set[str] = set()
    col_map: dict | None = None

    for page_num, page in enumerate(pdf.pages, 1):
        for table in (page.extract_tables() or []):
            for row in table:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                new_map = _detect_col_map(row)
                if new_map:
                    col_map = new_map
                    logger.debug("Page %d: columns %s", page_num, col_map)
                    continue
                if col_map is None:
                    continue
                try:
                    rec = _row_to_record(row, col_map)
                except Exception as exc:
                    logger.debug("Row error: %s", exc)
                    continue
                if rec and rec.telefone not in seen:
                    seen.add(rec.telefone)
                    records.append(rec)

    logger.info("Table strategy: %d records", len(records))
    return records


def _parse_block(block: str) -> ExtractedRecord | None:
    m = _PHONE_RE.search(block)
    if not m:
        return None
    phone = _clean_phone(m.group(1) or m.group(2) or "")
    if not _valid_phone(phone):
        return None

    name_m = _NAME_LABELED.search(block)
    name = name_m.group(1).strip() if name_m else "Desconhecido"

    exam_m = _EXAM_LABELED.search(block)
    exam = exam_m.group(1).strip().rstrip(".,;") if exam_m else "Não especificado"

    age_m = _AGE_LABELED.search(block) or _AGE_ANOS.search(block)
    age = int(age_m.group(1)) if age_m else None

    return ExtractedRecord(paciente=name, telefone=phone, exame_procedimento=exam, idade=age)


def _try_text_extraction(pdf) -> list[ExtractedRecord]:
    full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if not full_text.strip():
        return []

    records: list[ExtractedRecord] = []
    seen: set[str] = set()
    for block in _BLOCK_SEP.split(full_text):
        block = block.strip()
        if not block:
            continue
        try:
            rec = _parse_block(block)
        except Exception as exc:
            logger.debug("Block error: %s", exc)
            continue
        if rec and rec.telefone not in seen:
            seen.add(rec.telefone)
            records.append(rec)

    logger.info("Text strategy: %d records", len(records))
    return records


class PDFExtractorService:
    def extract(self, content: bytes) -> list[ExtractedRecord]:
        try:
            with pdfplumber.open(BytesIO(content)) as pdf:
                records = _try_table_extraction(pdf)
                if not records:
                    logger.info("No tables found, falling back to text extraction")
                    records = _try_text_extraction(pdf)
        except Exception as exc:
            logger.error("PDF open failed: %s", exc)
            raise ValueError(f"Não foi possível ler o PDF: {exc}") from exc

        if not records:
            raise ValueError(
                "Nenhum paciente encontrado no PDF. "
                "Verifique se o arquivo contém dados com telefone."
            )

        logger.info("Total extracted: %d records", len(records))
        return records
