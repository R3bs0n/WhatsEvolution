from __future__ import annotations

import logging
import re
from datetime import date, time
from typing import Iterator, NamedTuple

from django.db import transaction
from django.utils import timezone

from atendimentos.models import Atendimento, SituacaoAtendimento
from core.services.pdf_extractor import ExtractedRecord

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


class ImportResult(NamedTuple):
    total_extraidos: int
    total_inseridos: int
    total_ignorados: int


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    m = re.search(r"(\d{2})[/\-](\d{2})[/\-](\d{2,4})", raw)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2), m.group(3)
    if len(year) == 2:
        year = "20" + year
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _parse_time(raw: str) -> time | None:
    if not raw:
        return None
    m = re.match(r'^(\d{1,2}):(\d{2})$', raw.strip())
    if not m:
        return None
    try:
        return time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _dedup_key(rec: ExtractedRecord, data_agend: date | None) -> tuple:
    return (
        rec.telefone.strip(),
        rec.paciente.strip().upper(),
        rec.exame_procedimento.strip().upper(),
        data_agend,
    )


def _process_batch(
    batch: list[ExtractedRecord],
    situacao: SituacaoAtendimento,
    filename: str,
    now,
    pdf_import_log=None,
    empresa=None,
) -> tuple[int, int]:
    if not batch:
        return 0, 0

    parsed: list[tuple[ExtractedRecord, date | None, time | None]] = [
        (rec, _parse_date(rec.data_agendamento_raw), _parse_time(rec.horario_agendamento_raw))
        for rec in batch
    ]

    seen_keys: set[tuple] = set()
    unique: list[tuple[ExtractedRecord, date | None, time | None]] = []
    for rec, data_agend, horario in parsed:
        key = _dedup_key(rec, data_agend)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append((rec, data_agend, horario))

    intra_dupes = len(batch) - len(unique)

    telefones = [rec.telefone for rec, _, _ in unique]
    base_qs = Atendimento.objects.for_empresa(empresa) if empresa is not None else Atendimento.objects
    existing_qs = (
        base_qs
        .filter(telefone__in=telefones)
        .values_list("telefone", "paciente", "exame_procedimento", "data_agendamento")
    )
    existing_set: set[tuple] = {
        (t.strip(), p.strip().upper(), e.strip().upper(), d)
        for t, p, e, d in existing_qs
    }

    to_create: list[Atendimento] = []
    ignored_db = 0
    for rec, data_agend, horario in unique:
        norm_key = (
            rec.telefone.strip(),
            rec.paciente.strip().upper(),
            rec.exame_procedimento.strip().upper(),
            data_agend,
        )
        if norm_key in existing_set:
            ignored_db += 1
            continue
        to_create.append(Atendimento(
            empresa=empresa,
            situacao=situacao,
            paciente=rec.paciente,
            telefone=rec.telefone,
            exame_procedimento=rec.exame_procedimento,
            idade=rec.idade,
            data_agendamento=data_agend,
            horario_agendamento=horario,
            pdf_nome_arquivo=filename,
            pdf_import=pdf_import_log,
            data_extracao=now,
            status_enviado="N",
        ))

    inserted = 0
    if to_create:
        with transaction.atomic():
            Atendimento.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        inserted = len(to_create)

    logger.info(
        "Lote: %d inseridos, %d ignorados (%d intra-lote, %d já no DB)",
        inserted, intra_dupes + ignored_db, intra_dupes, ignored_db,
    )
    return inserted, intra_dupes + ignored_db


def bulk_import_records(
    records_iter: Iterator[ExtractedRecord],
    situacao: SituacaoAtendimento,
    filename: str,
    pdf_import_log=None,
    empresa=None,
) -> ImportResult:
    now = timezone.now()
    total_extraidos = 0
    total_inseridos = 0
    total_ignorados = 0
    batch: list[ExtractedRecord] = []

    for rec in records_iter:
        total_extraidos += 1

        if not rec.telefone:
            total_ignorados += 1
            continue

        batch.append(rec)

        if len(batch) >= BATCH_SIZE:
            ins, ign = _process_batch(batch, situacao, filename, now, pdf_import_log, empresa)
            total_inseridos += ins
            total_ignorados += ign
            batch.clear()

    if batch:
        ins, ign = _process_batch(batch, situacao, filename, now, pdf_import_log, empresa)
        total_inseridos += ins
        total_ignorados += ign

    logger.info(
        "Importação concluída: %d extraídos, %d inseridos, %d ignorados",
        total_extraidos, total_inseridos, total_ignorados,
    )
    return ImportResult(total_extraidos, total_inseridos, total_ignorados)
