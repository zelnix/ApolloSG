"""The person deletes chosen cases and Patrol records from their phone (Threats or Patrol history → Select → Delete).

Every copy ApolloSG's server holds of them goes too:
  * the Patrol events and their Patrol records;
  * each linked investigation: its content (evidence, uploads, jobs, turns, device requests), the copy held for the
    phone, saved reports, Magnum DI transactions, its Triage record and its case history;
  * family-shared copies and notes, and alerts still held for the end of quiet hours.

A deleted Patrol event becomes a delete marker holding only its id, its device and the reason, so a copy still in the
phone's delivery queue is acknowledged without being stored (routers/patrol.upsert_event → case_wipe.refuses), and
GET /api/patrol/removed lists it. Kept: usage and cost records (no content) and ApolloSG's anonymous previous-report
marks (one-way codes, services/observed_intel.py).

Only this device's own records are ever touched.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

from core.db import db, now_utc
from services import case_wipe, device_pickup
from services.higgins import repository as repo

REMOVED_REASON = case_wipe.OWNER_DELETED
MAX_IDS = 500


def _ids(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and 0 < len(v) <= 128))[:MAX_IDS]


async def delete(owner: str, event_ids: Iterable[Any], case_ids: Iterable[Any] = ()) -> dict[str, Any]:
    events = _ids(event_ids)
    found = await db.patrol_events.find({"device_id": owner, "event_id": {"$in": events}},
                                        {"_id": 0, "investigation_case_id": 1}).to_list(None) if events else []
    wanted = set(_ids(case_ids)) | {d["investigation_case_id"] for d in found if isinstance(d.get("investigation_case_id"), str)}
    cases = [c["case_id"] for c in await db.investigation_cases.find(
        {"owner_id": owner, "case_id": {"$in": sorted(wanted)}}, {"_id": 0, "case_id": 1}).to_list(None)] if wanted else []
    # Every other record of this device filed for the same investigations is part of the same case.
    linked = await db.patrol_events.distinct("event_id", {"device_id": owner, "investigation_case_id": {"$in": cases},
                                                          "removed_reason": {"$ne": REMOVED_REASON}}) if cases else []
    all_events = list(dict.fromkeys([*events, *linked]))

    at = now_utc()
    for event_id in all_events:
        # A marker even for a record the server never received, so a late delivery from the phone isn't stored.
        await db.patrol_events.replace_one({"device_id": owner, "event_id": event_id},
                                           {"event_id": event_id, "device_id": owner, "removed_reason": REMOVED_REASON, "deleted_at": at},
                                           upsert=True)
    deleted: dict[str, int] = {}

    async def drop(name: str, query: dict[str, Any]) -> None:
        deleted[name] = deleted.get(name, 0) + (await db[name].delete_many(query)).deleted_count

    record_match: list[dict[str, Any]] = [{"source_event_id": {"$in": all_events}}]
    if cases:
        record_match.append({"investigation_case_id": {"$in": cases}})
    await drop("patrol_records", {"owner_id": owner, "$or": record_match})

    for case_id in cases:
        await repo.revoke(owner, case_id, "deleted")
        await device_pickup.release(owner, case_id)
        await repo.run_cleanup(owner, case_id)
    if cases:
        await drop("investigation_reports", {"owner_id": owner, "case_id": {"$in": cases}})
        await drop("di_transactions", {"owner": owner, "$or": [{"investigation_id": {"$in": cases}},
                                                               {"correlation_id": {"$in": [f"case-{c}" for c in cases]}}]})
        await drop("triage_investigations", {"device_id": owner, "investigation_case_id": {"$in": cases}})
        await drop("higgins_investigation_history", {"owner_id": owner, "case_id": {"$in": cases}})
        await drop("device_case_history", {"owner_id": owner, "case_id": {"$in": cases}})
    if all_events:
        await drop("device_case_history", {"owner_id": owner, "event_id": {"$in": all_events}})
        await drop("shared_events", {"protected_device_id": owner, "event_id": {"$in": all_events}})
        await drop("threat_notes", {"protected_device_id": owner, "event_id": {"$in": all_events}})
        await drop("held_alerts", {"device_id": owner, "event_key": {"$in": [f"owner-{e}" for e in all_events]}})
        # A Triage record the server filed itself is named by its record's id (services/triage/store.py).
        chosen = set(all_events)
        filed = [d["investigation_id"] async for d in db.triage_investigations.find({"device_id": owner}, {"_id": 0, "investigation_id": 1})
                 if triage_event_id(owner, d.get("investigation_id")) in chosen]
        if filed:
            await drop("triage_investigations", {"device_id": owner, "investigation_id": {"$in": filed}})
    return {"eventIds": all_events, "caseIds": cases, "deleted": deleted}


def triage_event_id(owner: str, investigation_id: Any) -> str | None:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-triage:{owner}:{investigation_id}")) if isinstance(investigation_id, str) else None
