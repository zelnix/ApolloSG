"""Complete, device-scoped data deletion ("Delete My Apollo Data").

This is the authoritative server-side inventory + purge for everything Apollo holds
for one anonymous device identity. It is driven by the device's OWN explicit request;
it only ever selects records that belong to this device_id / owner_id (owner_id == device_id).

Design:
- `inventory(device_id)` returns an honest, category-grouped count of what Apollo currently
  stores for this device. Zero counts are reported truthfully (never hidden).
- `purge_device(device_id)` first invalidates the investigation generation so any late/in-flight
  worker cannot publish new content, then deletes every category, then revokes + removes the
  device identity itself. It returns a per-category count of what was removed.

No historical data for OTHER devices is ever touched.
"""
from __future__ import annotations

import uuid
from typing import Any

from core.db import db, now_utc

# Each category maps to a human label + the collections (and the id fields to match) it covers.
# A record is matched when ANY listed field equals the device_id (owner_id == device_id throughout).
CATEGORIES: dict[str, dict[str, Any]] = {
    "higgins_conversations": {
        "label": "Higgins conversations",
        "collections": [
            ("higgins_chat_messages", ["owner_id"]),
            ("higgins_chat_receipts", ["owner_id"]),
            ("higgins_context", ["owner_id"]),
            ("ask_messages", ["device_id"]),
            ("ask_handoffs", ["device_id"]),
        ],
    },
    "investigations": {
        "label": "Investigations & saved reports",
        "collections": [
            ("higgins_investigation_history", ["owner_id"]),
            ("investigation_cases", ["owner_id", "device_id"]),
            ("investigation_events", ["owner_id"]),
            ("investigation_evidence", ["owner_id"]),
            ("investigation_content_chunks", ["owner_id"]),
            ("investigation_device_pickups", ["owner_id"]),
            ("investigation_pickup_chunks", ["owner_id"]),
            ("investigation_reports", ["owner_id"]),
            ("investigation_jobs", ["owner_id", "device_id"]),
            ("investigation_owners", ["owner_id"]),
            ("investigation_scopes", ["owner_id"]),
            ("investigation_settings_plans", ["owner_id"]),
            ("investigation_turn_commits", ["owner_id"]),
            ("investigation_uploads", ["owner_id"]),
            ("investigation_upload_chunks", ["owner_id"]),
            ("investigation_idempotency", ["owner_id"]),
            ("investigation_device_requests", ["owner_id"]),
            ("device_case_history", ["owner_id"]),
            ("magnum_di_calls", ["owner_id"]),
            ("magnum_di_window_calls", ["owner_id"]),
            ("di_transactions", ["owner"]),
            ("work_claims", ["owner_id"]),
        ],
    },
    "patrol_activity": {
        "label": "Patrol activity & records",
        "collections": [
            ("patrol_events", ["device_id", "owner_id"]),
            ("patrol_records", ["device_id", "owner_id"]),
            ("shared_events", ["device_id"]),
            ("shared_incidents", ["device_id"]),
            ("incident_notes", ["device_id"]),
        ],
    },
    "trusted_links": {
        "label": "Trusted links",
        "collections": [
            ("trust_entries", ["device_id"]),
        ],
    },
    "email_monitoring": {
        "label": "Email & account monitoring",
        "collections": [
            ("gmail_connections", ["device_id"]),
            ("gmail_oauth_states", ["device_id"]),
            ("mailbox_assessment_receipts", ["device_id"]),
            ("weekly_checkins", ["device_id"]),
            ("weekly_checkin_sends", ["device_id"]),
            ("weekly_nudge_sends", ["device_id"]),
        ],
    },
    "family": {
        "label": "Family links & guardians",
        "collections": [
            ("guardians", ["device_id"]),
            ("family_links", ["protected_device_id", "guardian_device_id"]),
            ("pair_codes", ["protected_device_id"]),
            ("pair_link_misses", ["device_id"]),
            ("family_acks", ["guardian_device_id"]),
            ("family_assist_sessions", ["owner_device_id", "helper_device_id", "device_id"]),
            ("family_assist_events", ["owner_device_id", "device_id"]),
            ("family_assist_outbox", ["device_id", "recipient_id"]),
            ("family_assist_tickets", ["device_id"]),
        ],
    },
    "diagnostics": {
        "label": "Diagnostics & app signals",
        "collections": [
            ("device_capability_snapshots", ["owner_id", "device_id"]),
            ("health_checks", ["owner_id"]),
            ("health_report_artifacts", ["owner_id"]),
            ("learning_preferences", ["owner_id"]),
            ("learning_feedback", ["device_id", "owner_id"]),
            ("push_registrations", ["device_id", "recipient_id"]),
            ("push_deliveries", ["recipient_id", "owner_id"]),
            ("feedback", ["device_id", "owner_id"]),
        ],
    },
}


def _match(device_id: str, fields: list[str]) -> dict[str, Any]:
    if len(fields) == 1:
        return {fields[0]: device_id}
    return {"$or": [{f: device_id} for f in fields]}


async def inventory(device_id: str) -> dict[str, Any]:
    """Honest, category-grouped count of everything Apollo currently stores for this device."""
    categories: list[dict[str, Any]] = []
    total = 0
    for key, spec in CATEGORIES.items():
        count = 0
        for name, fields in spec["collections"]:
            try:
                count += await db[name].count_documents(_match(device_id, fields))
            except Exception:
                # A missing collection or transient error must not hide the rest of the inventory.
                continue
        total += count
        categories.append({"key": key, "label": spec["label"], "count": count})
    return {"device_id": device_id, "total": total, "categories": categories}


async def purge_device(device_id: str) -> dict[str, Any]:
    """Delete EVERYTHING Apollo holds for this device, then revoke + remove the device identity."""
    # 1) Invalidate the investigation generation first. Any late worker keeps the old generation
    #    and therefore cannot publish new content after we begin deleting.
    await db.investigation_owners.update_one(
        {"owner_id": device_id}, {"$set": {"generation": uuid.uuid4().hex}}, upsert=True
    )
    # Invalidate the controls actually used by case workers before any table is
    # removed. The legacy owner-generation marker alone does not fence them.
    await db.investigation_cases.update_many({"owner_id": device_id}, {"$set": {
        "deleted": True, "epoch": uuid.uuid4().hex, "work_epoch": uuid.uuid4().hex,
        "active_job_id": None, "lease_fence": None,
    }})
    await db.investigation_jobs.update_many({"owner_id": device_id}, {"$set": {"status": "cancelled", "lease_until": None}})

    # 2) Delete every category.
    removed: dict[str, int] = {}
    total = 0
    failures = []
    for key, spec in CATEGORIES.items():
        count = 0
        for name, fields in spec["collections"]:
            try:
                result = await db[name].delete_many(_match(device_id, fields))
                count += result.deleted_count
            except Exception:
                failures.append(name)
        removed[key] = count
        total += count

    if failures:
        from fastapi import HTTPException
        raise HTTPException(503, "Some Apollo data could not be deleted. Your sign-in was kept so you can retry.")

    # 3) Revoke family-assist sessions, then revoke + delete the device identity itself.
    try:
        from services.family_assist.sessions import revoke_for_device
        await revoke_for_device(device_id, "owner_deleted_data")
    except Exception:
        pass
    await db.devices.delete_one({"device_id": device_id})

    return {"device_id": device_id, "total": total, "removed": removed, "deleted_at": now_utc().isoformat()}
