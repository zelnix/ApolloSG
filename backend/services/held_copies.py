"""ApolloSG's own server copies of what was checked are deleted 24 hours after they were made — but never before the
phone confirms it has saved its own (owner's rules, 2026-11-01). The phone's copies are not touched by this rule.

On the server that copy is a message's text held as `source_metadata.preview` on Patrol records and investigation
cases. Who sent it, its subject and the website are identifiers the case keeps; findings and reports are kept as
before. Counted from when the copy was made (`source_metadata.submitted_at`, else the record's own time), and waiting
for `device_saved_at`: set when the phone confirms a case (confirm-commit) or a Threats record (POST /patrol/saved).
If the phone is offline, the copy waits for it. Runs with every maintenance cycle (services/maintenance.py).
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
    return {"source_metadata.preview": {"$nin": [None, ""]}, "device_saved_at": {"$type": "date"},
            "$or": [{"source_metadata.submitted_at": {"$lte": cutoff}},
                    {"source_metadata.submitted_at": None, at_field: {"$lte": cutoff}}]}


async def sweep(now: datetime | None = None) -> dict[str, int]:
    """Delete every server-held copy older than 24 hours that the phone has confirmed it saved. Idempotent."""
    now = now or now_utc()
    out: dict[str, int] = {}
    for name, at_field in _HOLDERS:
        result = await db[name].update_many(due_filter(at_field, now), {"$unset": {"source_metadata.preview": ""}})
        out[name] = result.modified_count
    return out


async def saved_on_device(owner: str, event_ids: list[str]) -> int:
    """The phone saved these Threats records' text: their 24 hours may now end them on the server."""
    if not event_ids:
        return 0
    result = await db.patrol_events.update_many({"device_id": owner, "event_id": {"$in": event_ids}, "device_saved_at": None},
                                                {"$set": {"device_saved_at": now_utc()}})
    return result.modified_count
