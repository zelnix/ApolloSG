"""Remove the preview data that was copied into production.

Production's database began as a copy of the preview database (about 2026-09-22 01:05 UTC; see
memory/DEVICE_INVESTIGATION_2026-10-27.md). Production did not exist before that copy, so in production every
record whose server-set time is at or before the copy is preview data. Content and settings that came with the copy
(Learn, the knowledge base, threat lists, the Official Organisation Directory, ApolloSG settings, migrations, caches)
are what production runs on and are kept.

Rules, per collection:
- time:   a server-set time field at or before the cutoff (string-typed values never match, so nothing is guessed);
- owner:  collections with no reliable time: rows not owned by a device production created itself;
- day:    daily counters before the copy's day;
- devices: identities created at or before the cutoff.
Nothing created after the cutoff is ever deleted.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core.db import db, now_utc

log = logging.getLogger("apollo.preview_purge")

TIME_RULES: dict[str, tuple[str, ...]] = {
    "admin_audit": ("at", "timestamp"), "admin_sessions": ("created_at",), "gemini_usage": ("timestamp",),
    "trusted_search_usage": ("timestamp",), "di_transactions": ("created_at",), "delivery_receipts": ("created_at",),
    "held_alerts": ("created_at",), "push_deliveries": ("created_at",), "feedback": ("created_at",),
    "triage_results": ("created_at",), "triage_investigations": ("created_at",), "triage_outcome_telemetry": ("at",),
    "patrol_events": ("created_at",), "patrol_records": ("created_at",), "investigation_cases": ("created_at",),
    "higgins_investigation_history": ("created_at",), "higgins_chat_receipts": ("created_at",),
    "higgins_chat_messages": ("created_at",), "ask_messages": ("created_at",), "investigation_reports": ("saved_at",),
    "investigation_scopes": ("created_at",), "family_links": ("created_at",), "pair_codes": ("created_at",),
    "pair_link_misses": ("at",), "family_acks": ("acknowledged_at",), "guardians": ("created_at",),
    "incident_notes": ("created_at",), "shared_events": ("created_at",), "shared_incidents": ("shared_at",),
    "shared_scam_alerts": ("shared_at",), "threat_notes": ("created_at",), "weekly_checkins": ("created_at",),
    "weekly_checkin_sends": ("sent_at",), "weekly_nudge_sends": ("sent_at",), "trust_entries": ("created_at",),
    "gmail_oauth_states": ("created_at",), "mailbox_assessment_receipts": ("created_at",),
    "family_audio_cleanup": ("created_at",), "learning_feed_runs": ("started_at",), "apollo_kb_runs": ("started_at",),
    "apollo_kb_rejections": ("at",), "threat_revalidation_log": ("attempted_at",),
}
OWNER_RULES: dict[str, str] = {
    "evidence_receipts": "device_id", "investigation_owners": "owner_id", "investigation_device_requests": "owner_id",
    "investigation_cleanup": "owner_id", "device_posture": "device_id", "device_capability_snapshots": "owner_id",
    "gmail_connections": "device_id", "health_checks": "owner_id", "learning_preferences": "owner_id",
}
DAY_RULES: dict[str, str] = {"intel_reuse_metrics": "day"}
KEPT = ("learning_*", "higgins_knowledge", "kb_benchmark_corpus", "apollo_kb_state", "apollo_kb_history", "threat_indicators",
        "blocklist", "caller_id_numbers", "reusable_intelligence", "government_alerts", "government_feed_state",
        "apollo_settings", "gemini_model_choices", "apollo_migrations", "migration_reports", "rule_bundle_state",
        "rule_bundle_publications", "reputation_cache", "domain_info_cache", "phone_risk_cache", "url_risk_cache",
        "voice_cache", "worker_heartbeats")
CONFIRM = "DELETE PREVIEW DATA"
_TASKS: set = set()


def parse_cutoff(value: str) -> datetime:
    cutoff = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    cutoff = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    if not datetime(2026, 1, 1, tzinfo=timezone.utc) < cutoff < now_utc():
        raise ValueError("cutoff out of range")
    return cutoff


def _time_filter(fields: tuple[str, ...], cutoff: datetime) -> dict:
    return {fields[0]: {"$lte": cutoff}} if len(fields) == 1 else {"$or": [{f: {"$lte": cutoff}} for f in fields]}


async def _native(cutoff: datetime) -> list[str]:
    """Devices production created itself (after the copy)."""
    return [d["device_id"] async for d in db.devices.find({"created_at": {"$gt": cutoff}}, {"_id": 0, "device_id": 1})]


async def _filters(cutoff: datetime) -> dict[str, dict]:
    native = await _native(cutoff)
    out = {name: _time_filter(fields, cutoff) for name, fields in TIME_RULES.items()}
    out.update({name: {field: {"$nin": native}} for name, field in OWNER_RULES.items()})
    out.update({name: {field: {"$lt": cutoff.strftime("%Y-%m-%d")}} for name, field in DAY_RULES.items()})
    out["devices"] = {"created_at": {"$lte": cutoff}}
    return out


async def scan(cutoff: datetime) -> dict:
    """What a purge would remove, per collection, and the evidence that the cutoff sits at the copy. Read-only."""
    filters = await _filters(cutoff)
    names = set(await db.list_collection_names())
    counts = {name: await db[name].count_documents(f) for name, f in filters.items() if name in names}
    newest = await db.devices.find_one({"created_at": {"$lte": cutoff}}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    oldest_after = await db.devices.find_one({"created_at": {"$gt": cutoff}}, {"_id": 0, "created_at": 1}, sort=[("created_at", 1)])
    by_platform = {r["_id"] or "none": r["n"] async for r in db.devices.aggregate([
        {"$match": filters["devices"]}, {"$group": {"_id": "$platform", "n": {"$sum": 1}}}])}
    covered = set(filters) | {n for n in names if any(n == k or (k.endswith("*") and n.startswith(k[:-1])) for k in KEPT)}
    return {"cutoff": cutoff.isoformat(), "devices": counts.get("devices", 0), "devicesByPlatform": by_platform,
            "newestCopiedDevice": newest and newest["created_at"].isoformat(),
            "firstProductionDevice": oldest_after and oldest_after["created_at"].isoformat(),
            "productionDevicesKept": await db.devices.count_documents({"created_at": {"$gt": cutoff}}),
            "toDelete": {k: v for k, v in sorted(counts.items()) if v}, "kept": list(KEPT),
            "notCovered": sorted(n for n in names - covered if not n.startswith("system.") and n != "preview_purge_runs")}


async def _run(run_id: str, cutoff: datetime) -> None:
    removed: dict[str, int] = {}
    try:
        filters = await _filters(cutoff)
        devices = filters.pop("devices")
        for name, f in filters.items():
            removed[name] = (await db[name].delete_many(f)).deleted_count
            await db.preview_purge_runs.update_one({"run_id": run_id}, {"$set": {"removed": removed}})
        removed["devices"] = (await db.devices.delete_many(devices)).deleted_count
        await db.preview_purge_runs.update_one({"run_id": run_id}, {"$set": {"state": "done", "removed": removed, "finished_at": now_utc()}})
    except Exception as exc:  # noqa: BLE001 — recorded for the admin; a re-run continues where it stopped
        log.warning("preview_purge_failed run=%s", run_id, exc_info=True)
        await db.preview_purge_runs.update_one({"run_id": run_id}, {"$set": {"state": "failed", "error": type(exc).__name__,
                                                                             "removed": removed, "finished_at": now_utc()}})


async def start(cutoff: datetime, expected: tuple[int, int]) -> dict:
    """Start the purge when the copied devices are within the expected range; otherwise nothing is deleted.
    Never on the preview server: there, records before the cutoff are the preview's own."""
    from services.higgins.provider import preview_environment
    found = await scan(cutoff)
    if preview_environment():
        return {"started": False, "reason": "this is the preview server; the purge runs only in production", "scan": found}
    if not expected[0] <= found["devices"] <= expected[1]:
        return {"started": False, "reason": "device count outside the expected range", "scan": found}
    if await db.preview_purge_runs.find_one({"state": "running"}, {"_id": 1}):
        return {"started": False, "reason": "a purge is already running", "scan": found}
    import asyncio
    run_id = uuid.uuid4().hex[:16]
    await db.preview_purge_runs.insert_one({"run_id": run_id, "cutoff": cutoff, "state": "running", "started_at": now_utc(),
                                            "scan": found, "removed": {}})
    task = asyncio.create_task(_run(run_id, cutoff))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"started": True, "run_id": run_id, "scan": found}


async def status(run_id: str) -> dict | None:
    return await db.preview_purge_runs.find_one({"run_id": run_id}, {"_id": 0})
