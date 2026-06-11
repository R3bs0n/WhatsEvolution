"""Tests for core.services.pdf_extractor — PyMuPDF-based PDFExtractorService.

Test data format matches the REAL SISREG PDF text stream (verified from production PDF debug):
  Un. Executante lines (before date, skipped)
  DD/MM/YYYY -
  HH:MM
  ( ID ) PATIENT NAME
  [name continuation lines]
  AGE
  Exames / SMS -        ← Tp. Procedimento start (has "/")
  PROCEDURE NAME LINE
  PROCEDURE NAME LINE
  PROFISSIONAL NAME     ← pure-alpha trailing lines (stripped from procedure)
  PROFISSIONAL NAME
  (DD) DDDDD-DDDD
  Agendado
  CS UNIDADE
"""
import pytest
from unittest.mock import MagicMock, patch
from django.test import TestCase

from core.services.pdf_extractor import (
    PDFExtractorService,
    ExtractedRecord,
    _clean_phone,
    _valid_phone,
    split_proc_prof,
    _parse_page_lines,
    _State,
)


# ──────────────────────────────────────────────────────────────────────────────
# _clean_phone / _valid_phone
# ──────────────────────────────────────────────────────────────────────────────

class CleanPhoneTest(TestCase):
    def test_formats_mobile(self):
        assert _clean_phone("(92) 99999-9999") == "5592999999999"

    def test_strips_leading_zero(self):
        assert _clean_phone("09299999999") == "559299999999"

    def test_no_change_when_already_normalised(self):
        assert _clean_phone("5592999999999") == "5592999999999"

    def test_valid_phone_12_digits(self):
        assert _valid_phone("559299999999") is True

    def test_valid_phone_13_digits(self):
        assert _valid_phone("5592999999999") is True

    def test_invalid_phone_too_short(self):
        assert _valid_phone("9999") is False

    def test_invalid_phone_too_long(self):
        assert _valid_phone("1" * 14) is False


# ──────────────────────────────────────────────────────────────────────────────
# _extract_procedure
# ──────────────────────────────────────────────────────────────────────────────

class SplitProcProfTest(TestCase):
    def test_strips_profissional_trailing_lines(self):
        lines = [
            "Exames / SMS -",
            "ULTRASSONOGRAFIA DE",
            "PROSTATA (TRANSRETAL)",   # has "()" → not pure-alpha → stop stripping
            "MARIANA LAZARA DE",        # pure-alpha → profissional
            "OLIVEIRA SANTOS",          # pure-alpha → profissional
        ]
        proc, prof = split_proc_prof(lines)
        assert proc == "Exames / SMS - ULTRASSONOGRAFIA DE PROSTATA (TRANSRETAL)"
        assert prof == "MARIANA LAZARA DE OLIVEIRA SANTOS"

    def test_header_value_takes_priority_over_split(self):
        # In SMS PDFs the header always provides current_exame, so split_proc_prof
        # is a fallback; when all post-slash lines are pure-alpha the prefix is returned.
        lines = ["Exames / SMS -", "HEMOGRAMA", "DR JOSE DA SILVA"]
        proc, _ = split_proc_prof(lines)
        # "Exames / SMS -" is the surviving non-pure-alpha anchor
        assert proc == "Exames / SMS -"

    def test_no_slash_returns_joined_lines(self):
        proc, _ = split_proc_prof(["NOME SEM BARRA", "OUTRO CAMPO"])
        assert proc == "NOME SEM BARRA OUTRO CAMPO"

    def test_empty_list_returns_nao_especificado(self):
        proc, _ = split_proc_prof([])
        assert proc == "Não especificado"

    def test_procedure_with_parentheses_preserved(self):
        lines = ["Exames / SMS -", "PROSTATA (TRANSRETAL)", "PROFISSIONAL NOME"]
        proc, _ = split_proc_prof(lines)
        assert proc == "Exames / SMS - PROSTATA (TRANSRETAL)"


# ──────────────────────────────────────────────────────────────────────────────
# _parse_page_lines — real SISREG format
# ──────────────────────────────────────────────────────────────────────────────

def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.strip().splitlines()]


# Real format from production PDF debug output
REAL_SINGLE_RECORD = """
CLINICA MEDICA SAUDE
POPULAR
01/03/2026 -
00:00
( 761635 ) SAULO BAYER
62
Exames / SMS -
ULTRASSONOGRAFIA DE
PROSTATA (TRANSRETAL)
MARIANA LAZARA DE
OLIVEIRA SANTOS
(48) 99138-9174
Agendado
CS LAGOA DA
CONCEICAO
"""

REAL_TWO_RECORDS = """
CLINICA MEDICA SAUDE
POPULAR
01/03/2026 -
00:00
( 761635 ) SAULO BAYER
62
Exames / SMS -
ULTRASSONOGRAFIA DE
PROSTATA (TRANSRETAL)
MARIANA LAZARA DE
OLIVEIRA SANTOS
(48) 99138-9174
Agendado
CS LAGOA DA
CONCEICAO
CLINICA MEDICA SAUDE
POPULAR
01/03/2026 -
00:00
( 50944 ) NELSON ALEJANDRO
HERRERA GOMEZ
51
Exames / SMS -
ULTRASSONOGRAFIA DE
PROSTATA (TRANSRETAL)
MARIANA LAZARA DE
OLIVEIRA SANTOS
(47) 99971-3403
Agendado
CS
CANASVIEIRAS
"""

REAL_MULTILINE_NAME = """
01/03/2026 -
00:00
( 50944 ) NELSON ALEJANDRO
HERRERA GOMEZ
51
Exames / SMS -
ULTRASSONOGRAFIA DE
PROSTATA (TRANSRETAL)
MARIANA LAZARA DE
OLIVEIRA SANTOS
(47) 99971-3403
Agendado
CS CANASVIEIRAS
"""


class ParsePageLinesTest(TestCase):
    def test_single_record_all_fields(self):
        records = list(_parse_page_lines(_lines(REAL_SINGLE_RECORD), page_num=1, state=_State()))
        assert len(records) == 1
        r = records[0]
        assert r.paciente == "SAULO BAYER"
        assert r.telefone == "5548991389174"
        assert r.exame_procedimento == "Exames / SMS - ULTRASSONOGRAFIA DE PROSTATA (TRANSRETAL)"
        assert r.idade == 62
        assert r.data_agendamento_raw == "01/03/2026"
        assert r.horario_agendamento_raw == "00:00"

    def test_two_records_in_sequence(self):
        records = list(_parse_page_lines(_lines(REAL_TWO_RECORDS), page_num=1, state=_State()))
        assert len(records) == 2
        assert records[0].paciente == "SAULO BAYER"
        assert records[0].exame_procedimento == "Exames / SMS - ULTRASSONOGRAFIA DE PROSTATA (TRANSRETAL)"
        assert records[1].paciente == "NELSON ALEJANDRO HERRERA GOMEZ"
        assert records[1].telefone == "5547999713403"
        assert records[1].exame_procedimento == "Exames / SMS - ULTRASSONOGRAFIA DE PROSTATA (TRANSRETAL)"

    def test_multiline_patient_name(self):
        records = list(_parse_page_lines(_lines(REAL_MULTILINE_NAME), page_num=1, state=_State()))
        assert len(records) == 1
        assert records[0].paciente == "NELSON ALEJANDRO HERRERA GOMEZ"
        assert records[0].idade == 51

    def test_record_without_phone_is_skipped(self):
        text = """
01/03/2026 -
00:00
( 99999 ) SEM TELEFONE
35
Exames / SMS -
HEMOGRAMA
DR JOAO DA SILVA
"""
        records = list(_parse_page_lines(_lines(text), page_num=1, state=_State()))
        assert len(records) == 0

    def test_un_executante_lines_before_date_are_ignored(self):
        # Un. Executante garbage lines before the date anchor must not break parsing
        records = list(_parse_page_lines(_lines(REAL_SINGLE_RECORD), page_num=1, state=_State()))
        assert len(records) == 1

    def test_empty_page_yields_nothing(self):
        assert list(_parse_page_lines([], page_num=1, state=_State())) == []

    def test_page_with_only_headers_yields_nothing(self):
        lines = ["SECRETARIA MUNICIPAL DE SAÚDE", "Relação dos Agendamentos", "", "Paciente"]
        assert list(_parse_page_lines(lines, page_num=1, state=_State())) == []


# ──────────────────────────────────────────────────────────────────────────────
# PDFExtractorService — mocked fitz (PyMuPDF)
# ──────────────────────────────────────────────────────────────────────────────

def _mock_fitz_doc(page_texts: list[str]):
    mock_pages = []
    for text in page_texts:
        page = MagicMock()
        page.get_text.return_value = text
        mock_pages.append(page)

    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=len(mock_pages))
    doc.load_page.side_effect = lambda i: mock_pages[i]
    doc.close = MagicMock()
    return doc


class PDFExtractorServiceTest(TestCase):
    def test_iter_records_yields_all(self):
        svc = PDFExtractorService()
        doc = _mock_fitz_doc([REAL_TWO_RECORDS])
        with patch("core.services.pdf_extractor.fitz.open", return_value=doc):
            records = list(svc.iter_records(b"fake-pdf"))
        assert len(records) == 2
        assert isinstance(records[0], ExtractedRecord)

    def test_extract_returns_list(self):
        svc = PDFExtractorService()
        doc = _mock_fitz_doc([REAL_SINGLE_RECORD])
        with patch("core.services.pdf_extractor.fitz.open", return_value=doc):
            records = svc.extract(b"fake-pdf")
        assert len(records) == 1
        assert records[0].paciente == "SAULO BAYER"
        assert records[0].exame_procedimento == "Exames / SMS - ULTRASSONOGRAFIA DE PROSTATA (TRANSRETAL)"

    def test_extract_raises_on_empty_pdf(self):
        svc = PDFExtractorService()
        doc = _mock_fitz_doc([""])
        with patch("core.services.pdf_extractor.fitz.open", return_value=doc):
            with pytest.raises(ValueError, match="Nenhum paciente"):
                svc.extract(b"empty-pdf")

    def test_extract_raises_on_corrupted_pdf(self):
        svc = PDFExtractorService()
        with patch("core.services.pdf_extractor.fitz.open", side_effect=Exception("corrupted")):
            with pytest.raises(ValueError, match="Não foi possível"):
                svc.extract(b"bad-bytes")

    def test_multipage_pdf_yields_all_records(self):
        svc = PDFExtractorService()
        doc = _mock_fitz_doc([REAL_SINGLE_RECORD, REAL_MULTILINE_NAME])
        with patch("core.services.pdf_extractor.fitz.open", return_value=doc):
            records = list(svc.iter_records(b"fake-pdf"))
        assert len(records) == 2
        assert records[0].paciente == "SAULO BAYER"
        assert records[1].paciente == "NELSON ALEJANDRO HERRERA GOMEZ"

    def test_page_error_is_skipped_not_fatal(self):
        bad_page = MagicMock()
        bad_page.get_text.side_effect = RuntimeError("fitz page error")
        good_page = MagicMock()
        good_page.get_text.return_value = REAL_SINGLE_RECORD

        doc = MagicMock()
        doc.__len__ = MagicMock(return_value=2)
        doc.load_page.side_effect = [bad_page, good_page]
        doc.close = MagicMock()

        svc = PDFExtractorService()
        with patch("core.services.pdf_extractor.fitz.open", return_value=doc):
            records = list(svc.iter_records(b"fake-pdf"))
        assert len(records) == 1
