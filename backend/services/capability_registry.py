"""Authoritative runtime capability and Gate registry.

The registry combines immutable product declarations, server integration configuration, and the
latest bounded device observation.  It never turns configured/installed/requested into working.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.config import GEMINI_API_KEY, HIBP_API_KEY, IPQS_API_KEY
from core.db import db, now_utc
from routers.push import push_configured
from services.email import email_configured
from services.storage import storage_configured

GATES = {
    "site": ("Site protection", "native", "automatic"),
    "text": ("Text protection", "hybrid", "event_driven"),
    "call": ("Call protection", "native", "event_driven"),
    "email": ("Email checks", "server", "scheduled"),
    "link": ("Link checks", "hybrid", "on_demand"),
    "file": ("File checks", "hybrid", "on_demand"),
    "app": ("App checks", "hybrid", "on_demand"),
    "device": ("Device checks", "native", "on_demand"),
    "account": ("Account checks", "hybrid", "on_demand"),
    "network": ("Network checks", "native", "on_demand"),
}
STALE_AFTER = timedelta(hours=24)


async def ensure_indexes() -> None:
    await db.device_capability_snapshots.create_index("owner_id", unique=True)
    await db.device_capability_snapshots.create_index("expires_at", expireAfterSeconds=0)


def server_integrations() -> list[dict[str, Any]]:
    from services.google_web_risk import configured
    values = {
        "gemini": bool(GEMINI_API_KEY), "google_web_risk": configured(),
        "phone_reputation": bool(IPQS_API_KEY), "breach_lookup": bool(HIBP_API_KEY),
        "guardian_email": email_configured(), "push_delivery": push_configured(),
        "family_voice_storage": storage_configured(),
    }
    return [{"id": key, "configured": configured, "state": "configured" if configured else "unavailable",
             "reason": None if configured else "configuration_missing"} for key, configured in values.items()]


def declarations() -> list[dict[str, Any]]:
    return [{"id": gate, "title": title, "implementationOwner": owner, "mode": mode,
             "declared": True} for gate, (title, owner, mode) in GATES.items()]


async def save_snapshot(owner: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    now = now_utc()
    safe = {
        "owner_id": owner, "observed_at": now, "expires_at": now + STALE_AFTER,
        "platform": str(snapshot.get("platform") or "unknown")[:16],
        "adapter": str(snapshot.get("adapter") or "unknown")[:80],
        "online": snapshot.get("online") if isinstance(snapshot.get("online"), bool) else None,
        "gates": [item for item in snapshot.get("gates", []) if isinstance(item, dict)][:10],
        "capabilities": [item for item in snapshot.get("capabilities", []) if isinstance(item, dict)][:100],
        "protection": snapshot.get("protection") if isinstance(snapshot.get("protection"), dict) else None,
    }
    await db.device_capability_snapshots.update_one({"owner_id": owner}, {"$set": safe}, upsert=True)
    return safe


async def snapshot(owner: str) -> dict[str, Any] | None:
    return await db.device_capability_snapshots.find_one(
        {"owner_id": owner, "expires_at": {"$gt": now_utc()}}, {"_id": 0, "owner_id": 0, "expires_at": 0}
    )


async def touch_snapshot(owner: str) -> None:
    """Extend the snapshot expiry — proof the device is still active and online."""
    await db.device_capability_snapshots.update_one(
        {"owner_id": owner},
        {"$set": {"expires_at": now_utc() + STALE_AFTER}},
    )


async def product_capabilities(owner: str) -> dict[str, Any]:
    observed = await snapshot(owner)
    by_gate = {str(row.get("id")): row for row in (observed or {}).get("gates", [])}
    gates = []
    for gate_id, (title, implementation_owner, mode) in GATES.items():
        row = by_gate.get(gate_id)
        if not row:
            # On-demand / hybrid gates always accept manual checks even without a fresh device
            # observation — only purely native automatic gates are truly unavailable when unobserved.
            if mode == "on_demand" or implementation_owner in ("hybrid", "server"):
                state, reason = "ready", "manual_checks_available"
            else:
                state, reason = "unavailable", "no_fresh_device_observation"
        else:
            raw = str(row.get("state") or "unavailable")
            state = raw if raw in {"running", "ready", "permission_required", "degraded", "unavailable", "offline", "not_applicable"} else "unavailable"
            reason = row.get("reason")
        gates.append({"id": gate_id, "title": title, "implementationOwner": implementation_owner,
                      "mode": mode, "state": state, "reason": reason, "observedAt": (observed or {}).get("observed_at")})
    return {"schemaVersion": 1, "generatedAt": now_utc(), "deviceObservation": observed,
            "declarations": declarations(), "integrations": server_integrations(), "gates": gates}


async def gate_states(owner: str) -> dict[str, Any]:
    value = await product_capabilities(owner)
    return {"schemaVersion": 1, "generatedAt": value["generatedAt"], "items": value["gates"],
            "note": "States come from a fresh device observation; missing data remains unavailable."}
