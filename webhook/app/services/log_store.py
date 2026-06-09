from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Optional

@dataclass
class LogEntry:
    id: int
    name: str
    phone: str
    status: str       # "sent" | "failed"
    code: int
    error: Optional[str]
    sent_at: str      # ISO-8601

_logs: list[LogEntry] = []
_counter = 0


def _http_code(error: Optional[str]) -> int:
    if error:
        parts = error.split()
        if len(parts) >= 2 and parts[0] == "HTTP":
            try:
                return int(parts[1])
            except ValueError:
                pass
    return 500


def append_batch(results) -> None:
    global _counter
    ts = datetime.now().isoformat()
    for r in results:
        _counter += 1
        code = 200 if r.status == "sent" else _http_code(r.error)
        _logs.insert(0, LogEntry(
            id=_counter,
            name=r.name,
            phone=r.phone,
            status=r.status,
            code=code,
            error=r.error,
            sent_at=ts,
        ))


def query(search: str = "", page: int = 1, page_size: int = 20):
    if search:
        s = search.lower()
        filtered = [
            l for l in _logs
            if s in l.phone
            or s in l.name.lower()
            or (l.error and s in l.error.lower())
        ]
    else:
        filtered = list(_logs)

    total = len(filtered)
    total_pages = max(1, ceil(total / page_size))
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return filtered[start : start + page_size], total, page, total_pages
