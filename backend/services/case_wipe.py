"""Remove every threat case and Patrol record, for every device (an administrator's one-off reset).

What goes: Patrol records, every investigation case and its parts (events, evidence, uploads, jobs, Magnum DI
transactions, Triage records), case history, saved reports, family-shared copies (shared events and incidents, notes,
shared scam alerts) and alerts still held for later.

Patrol events become delete markers holding only the event's id, its device and the reason, so:
  * every device drops its local copy through GET /api/patrol/removed (older app versions already do this);
  * a device that re-sends a deleted event is acknowledged without it being stored (`refuses` / `unsaved_ack`), so
    the cases can't come back from a device's delivery queue.
The reset itself is recorded in `case_wipes`; devices read it from GET /api/patrol/wipe and clear their remaining
local copies (saved checks, check history, device-held investigations, originals).

Kept: threat lists, Learn content, settings, devices and their sign-ins, family links, usage and cost records,
evidence receipts (ids only) and notification history.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from core.db import db, now_utc
from core.models import PatrolEvent, PatrolEventIn

REMOVED_REASON = "admin_case_wipe"
CONFIRM = "DELETE ALL CASES"

DELETED_COLLECTIONS = (
    "patrol_records",
    "investigation_cases", "investigation_events", "investigation_evidence", "investigation_content_chunks", "investigation_device_pickups",
    "investigation_reports", "investigation_jobs", "investigation_turn_commits", "investigation_uploads",
    "investigation_upload_chunks", "investigation_idempotency", "investigation_device_requests",
    "investigation_cleanup", "investigation_settings_plans", "di_transactions", "triage_investigations", "triage_results",
    "higgins_investigation_history", "device_case_history",
    "shared_events", "shared_incidents", "incident_notes", "threat_notes", "shared_scam_alerts",
    "held_alerts",
)


async def latest() -> Optional[dict[str, Any]]:
    return await db.case_wipes.find_one({}, {"_id": 0}, sort=[("at", -1)])


async def scan() -> dict[str, Any]:
    counts = {name: await db[name].count_documents({}) for name in DELETED_COLLECTIONS}
    events = await db.patrol_events.count_documents({"removed_reason": {"$ne": REMOVED_REASON}})
    return {"patrolEvents": events, "deleted": counts, "total": events + sum(counts.values()), "lastWipe": await latest()}


async def run(actor: str) -> dict[str, Any]:
    wipe = {"wipe_id": uuid.uuid4().hex, "at": now_utc(), "actor": actor}
    # Recorded first: from this moment devices can no longer re-send anything from before it.
    await db.case_wipes.insert_one(dict(wipe))
    events = await db.patrol_events.update_many({"removed_reason": {"$ne": REMOVED_REASON}}, [{"$replaceWith": {
        "_id": "$_id", "event_id": "$event_id", "device_id": "$device_id",
        "removed_reason": REMOVED_REASON, "deleted_at": wipe["at"],
    }}])
    deleted = {name: (await db[name].delete_many({})).deleted_count for name in DELETED_COLLECTIONS}
    result = {"patrolEvents": events.modified_count, "deleted": deleted}
    await db.case_wipes.update_one({"wipe_id": wipe["wipe_id"]}, {"$set": {"result": result, "finished_at": now_utc()}})
    return {"wipeId": wipe["wipe_id"], "at": wipe["at"].isoformat(), **result}


async def refuses(body: PatrolEventIn, existing: Optional[dict[str, Any]]) -> bool:
    """A deleted event is not stored again. (Matched by its id, never by its time: a device's clock can be wrong.)"""
    del body
    return bool(existing) and existing.get("removed_reason") == REMOVED_REASON


def unsaved_ack(body: PatrolEventIn, ts: datetime) -> PatrolEvent:
    """The device's own event echoed back (not stored), so its delivery queue counts it delivered and moves on."""
    return PatrolEvent(**body.model_dump(), created_at=ts, updated_at=ts)
