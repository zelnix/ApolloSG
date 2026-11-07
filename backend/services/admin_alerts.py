"""Admin alerts — a durable log of technical failures surfaced to the admin console.

Today's only producer: a reputation-check provider (IPQualityScore) that failed or timed out after
retrying, forcing an investigation to stop as "investigation unable to progress" instead of reaching
a Findings score (Apollo PRD v2.2 §2.5). Kept separate from services/admin_health.py's point-in-time
computed checks — this is an append-only record of individual incidents, each tied to a case.
"""
from __future__ import annotations

from core.db import db, now_utc


async def log_technical_failure(*, owner: str, case_id: str, checks: list[str], subjects: list[str], reason: str) -> None:
    """Record one investigation that could not progress past a failed reputation check."""
    await db.admin_alerts.insert_one({
        "type": "technical_failure",
        "owner_id": owner,
        "case_id": case_id,
        "checks": checks,
        "subjects": subjects,
        "reason": reason,
        "created_at": now_utc(),
        "acknowledged": False,
    })


async def list_alerts(*, limit: int = 200, unacknowledged_only: bool = False) -> list[dict]:
    query: dict = {"acknowledged": False} if unacknowledged_only else {}
    cursor = db.admin_alerts.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [row async for row in cursor]


async def count_unacknowledged() -> int:
    return await db.admin_alerts.count_documents({"acknowledged": False})


async def acknowledge(case_id: str, created_at) -> bool:
    res = await db.admin_alerts.update_one({"case_id": case_id, "created_at": created_at}, {"$set": {"acknowledged": True}})
    return res.modified_count > 0
