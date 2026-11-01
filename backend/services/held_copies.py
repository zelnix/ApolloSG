"""ApolloSG's own copies of what was checked are kept for 24 hours, then deleted (owner's rule, 2026-11-01).

On the server that copy is a message's text held as `source_metadata.preview` on Patrol records and investigation
cases. Who sent it, its subject and the website are identifiers the case keeps; findings and reports are kept as
before. Counted from when the copy was made (`source_metadata.submitted_at`, else the record's own time). Runs with
every maintenance cycle (services/maintenance.py). Mirror: frontend src/domain/heldCopies.ts (the phone's copies).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core.db import db, now_utc
from services.higgins.capacity import EVIDENCE_RETENTION_SECONDS

HELD_COPY_SECONDS = EVIDENCE_RETENTION_SECONDS  # 24 hours

# Each collection that holds a copy, with the field that says when the record was made.
_HOLDERS = (("patrol_events", "occurred_at"), ("investigation_cases", "created_at"))


def due_filter(at_field: str, now: datetime) -> dict:
    cutoff = now - timedelta(seconds=HELD_COPY_SECONDS)
    return {"source_metadata.preview": {"$nin": [None, ""]},
            "$or": [{"source_metadata.submitted_at": {"$lte": cutoff}},
                    {"source_metadata.submitted_at": None, at_field: {"$lte": cutoff}}]}


async def sweep(now: datetime | None = None) -> dict[str, int]:
    """Delete every server-held copy older than 24 hours. Idempotent."""
    now = now or now_utc()
    out: dict[str, int] = {}
    for name, at_field in _HOLDERS:
        result = await db[name].update_many(due_filter(at_field, now), {"$unset": {"source_metadata.preview": ""}})
        out[name] = result.modified_count
    return out
