"""PDF extraction service for 'Relação dos Agendamentos' SUS scheduling format.

Uses PyMuPDF (fitz) for memory-safe, page-by-page extraction.

Two sources for procedure data:
  1. Page header  → "Exame Procedimento: <name>" line — valid for all records that
                    follow until the next such header appears (across pages).
  2. Per-record   → lines between Idade and Telefone, split by split_proc_prof().

When the header provides a concrete procedure (not "Todos"), it takes priority and
both exame_procedimento and tp_procedimento receive the same header value.

Real SISREG column order as read by PyMuPDF (left → right per table row):
  Un. Executante | Data e Hora | Paciente | Idade | Tp. Procedimento |
  Profissional Executante | Telefone | Situação | Un. Solicitante
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Iterator, Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

_RE_DATE         = re.compile(r'^\s*(\d{2}/\d{2}/\d{4})\s*-\s*$')
_RE_TIME         = re.compile(r'^\s*(\d{2}:\d{2})\s*$')
_RE_PATIENT      = re.compile(r'^\s*\(?\s*(\d+)\s*\)?\s*\)\s*(.+)\s*$')
_RE_AGE          = re.compile(r'^\s*(\d{1,3})\s*$')
_RE_PHONE        = re.compile(r'(\+?\d[\d\s().-]{8,}\d)')

# Header line: "Exame Procedimento: <value>"  (standalone line, not embedded in a filter row)
_RE_EXAME_HEADER = re.compile(r'^\s*Exame\s+Procedimento\s*:\s*(.+)\s*$', re.IGNORECASE)

# Generic label patterns for non-SMS PDFs
_RE_LABEL_TP     = re.compile(r'^\s*tp\.?\s*procedimento\s*:\s*(.+)\s*$', re.IGNORECASE)
_RE_LABEL_TIPO   = re.compile(r'^\s*tipo\s+procedimento\s*:\s*(.+)\s*$', re.IGNORECASE)

# Pure letters + spaces → Profissional Executante name lines
_RE_PURE_ALPHA   = re.compile(r'^[A-ZÁÉÍÓÚÂÊÔÃÕÀÇÊ\s]+$')


@dataclass
class ExtractedRecord:
    paciente: str = ""
    telefone: str = ""
    exame_procedimento: str = ""
    idade: Optional[int] = None
    data_agendamento_raw: str = ""
    horario_agendamento_raw: str = ""


@dataclass
class _State:
    """Mutable state that persists across pages within a single PDF."""
    current_exame: str = ""


def _clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def _valid_phone(digits: str) -> bool:
    return 12 <= len(digits) <= 13


def split_proc_prof(mid_lines: list[str]) -> tuple[str, str]:
    """Split lines between Idade and Telefone into (tp_procedimento, profissional).

    Strategy:
      • The procedure block starts at the first line containing "/" (SISREG
        "Category / Type -" prefix).
      • Lines before that "/" line are treated as additional patient-name
        continuation (should not happen in practice, but handled defensively).
      • After isolating the procedure block, trailing lines that are purely
        alphabetic (letters + spaces only) belong to Profissional Executante
        and are removed ONLY IF the remaining block still has content — this
        avoids stripping a single-word procedure like "HEMOGRAMA".
    """
    if not mid_lines:
        return "Não especificado", ""

    # Prefer label-based detection first (generic PDFs)
    for ln in mid_lines:
        m = _RE_LABEL_TP.match(ln)
        if m:
            return m.group(1).strip(), ""
        m = _RE_LABEL_TIPO.match(ln)
        if m:
            return m.group(1).strip(), ""

    # SMS-format: find first "/" line
    proc_start = next((i for i, ln in enumerate(mid_lines) if '/' in ln), None)
    if proc_start is None:
        return " ".join(mid_lines), ""

    proc_lines = list(mid_lines[proc_start:])

    # Strip trailing pure-alpha lines ONLY when at least one non-pure-alpha
    # line will remain — ensures we do not erase a purely alphabetic procedure.
    stripped = []
    while proc_lines and _RE_PURE_ALPHA.match(proc_lines[-1]):
        stripped.insert(0, proc_lines.pop())

    # If stripping would leave nothing, restore — the "profissional" we
    # identified is actually the procedure name itself.
    if not proc_lines:
        proc_lines = stripped
        stripped = []

    profissional = " ".join(stripped)
    return " ".join(proc_lines), profissional


def _parse_page_lines(
    lines: list[str],
    page_num: int,
    state: _State,
) -> Iterator[ExtractedRecord]:
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # --- Capture page-level "Exame Procedimento:" header ---
        m_header = _RE_EXAME_HEADER.match(line)
        if m_header:
            value = m_header.group(1).strip()
            # "Todos" means no specific filter — fall back to per-record parsing
            if value.lower() != "todos":
                state.current_exame = value
                logger.debug("Página %d: Exame Procedimento = %r", page_num, value)
            i += 1
            continue

        # --- Anchor: date line ---
        m_date = _RE_DATE.match(line)
        if not m_date:
            i += 1
            continue

        j = i + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n:
            break

        m_time = _RE_TIME.match(lines[j])
        if not m_time:
            i += 1
            continue

        date_str = m_date.group(1)
        time_str = m_time.group(1)
        i = j + 1

        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break

        # --- Patient line ---
        m_patient = _RE_PATIENT.match(lines[i])
        if not m_patient:
            continue

        patient_name_start = m_patient.group(2).strip()
        i += 1

        # --- Lines before age → name continuation ---
        name_extra: list[str] = []
        age: Optional[int] = None
        telefone = ""
        while i < n:
            ln = lines[i].strip()
            if not ln:
                i += 1
                continue
            if _RE_DATE.match(ln):
                break
            m_age = _RE_AGE.match(ln)
            if m_age:
                age = int(m_age.group(1))
                i += 1
                break
            m_phone = _RE_PHONE.search(ln)
            if m_phone:
                cleaned = _clean_phone(m_phone.group(1))
                if _valid_phone(cleaned):
                    telefone = cleaned
                    i += 1
                    break
            name_extra.append(ln)
            i += 1

        patient_name = (
            patient_name_start + " " + " ".join(name_extra)
            if name_extra else patient_name_start
        )

        # --- Pre-phone block: Tp. Procedimento + Profissional Executante ---
        mid_lines: list[str] = []
        while i < n and not telefone:
            ln = lines[i].strip()
            if not ln:
                i += 1
                continue
            if _RE_DATE.match(ln):
                break
            m_phone = _RE_PHONE.search(ln)
            if m_phone:
                cleaned = _clean_phone(m_phone.group(1))
                if _valid_phone(cleaned):
                    telefone = cleaned
                    i += 1
                    break
            mid_lines.append(ln)
            i += 1

        if not telefone:
            logger.debug("Página %d: registro sem telefone ignorado", page_num)
            continue

        # Determine procedure: header takes priority over per-record parsing
        if state.current_exame:
            exame = state.current_exame
        else:
            exame, _ = split_proc_prof(mid_lines)

        yield ExtractedRecord(
            paciente=patient_name,
            telefone=telefone,
            exame_procedimento=exame,
            idade=age,
            data_agendamento_raw=date_str,
            horario_agendamento_raw=time_str,
        )


class PDFExtractorService:
    """Memory-safe PDF extractor for SUS scheduling format using PyMuPDF."""

    def iter_records(self, content: bytes) -> Iterator[ExtractedRecord]:
        """Generator: yields ExtractedRecord one at a time, page by page."""
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            logger.error("Falha ao abrir PDF: %s", exc)
            raise ValueError(f"Não foi possível ler o PDF: {exc}") from exc

        total_pages = len(doc)
        logger.info("Iniciando extração: %d páginas", total_pages)
        state = _State()

        try:
            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                try:
                    text = page.get_text("text")
                    lines = [line.strip() for line in text.splitlines()]
                    page_count = 0
                    for record in _parse_page_lines(lines, page_num + 1, state):
                        page_count += 1
                        yield record
                    logger.debug(
                        "Página %d/%d: %d registros", page_num + 1, total_pages, page_count
                    )
                except Exception as exc:
                    logger.error("Erro ao processar página %d: %s", page_num + 1, exc)
                finally:
                    del page
        finally:
            doc.close()

    def extract(self, content: bytes) -> list[ExtractedRecord]:
        """Consume the generator and return a flat list. Raises ValueError if empty."""
        records = list(self.iter_records(content))
        if not records:
            raise ValueError(
                "Nenhum paciente encontrado no PDF. "
                "Verifique se o arquivo contém dados no formato esperado."
            )
        logger.info("Total extraído: %d registros", len(records))
        return records
