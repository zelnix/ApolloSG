"""Per-device usage counts for the admin Devices list: how often each feature was used on a device.
Counts only. A Learn article or scam alert that was opened is kept as a short digest, so opening the same one again
does not count twice and no title or link is stored."""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from core.db import db
from services.higgins import outcomes

log = logging.getLogger(__name__)

COUNTERS = ("tc_flyby", "magnum_di", "ask_higgins", "device_checks")
READS = {"learn_read": "learn_read", "scam_alert_read": "scam_alerts_read"}

# One of Google's test phones (Play pre-launch reports): reported by the phone itself, or marked by an admin.
TEST_LAB = "google_test_lab"
# A real phone: the ApolloSG app on Android or iOS, using the phone's own protection (not a test or script
# registration, whose adapter is mock/unsupported/standard), and not one of Google's test phones.
REAL_PHONES = {"platform": {"$in": ["android", "ios"]}, "adapter_mode": {"$in": ["android", "ios", "native"]},
               "test_device": None}


def record_type(device: dict) -> str:
    """How the admin Devices list labels a record."""
    if device.get("test_device") == TEST_LAB:
        return "Google test phone"
    if device.get("platform") in ("android", "ios") and device.get("adapter_mode") in ("android", "ios", "native") and not device.get("test_device"):
        return "Phone"
    return "Web" if device.get("platform") == "web" and device.get("adapter_mode") == "web" else "Test or script"


async def bump(device_id: str, counter: str) -> None:
    """Adds one to a count. Never fails the feature that was used: a missed count is only logged."""
    try:
        await db.devices.update_one({"device_id": device_id}, {"$inc": {f"stats.{counter}": 1}})
    except Exception as exc:  # noqa: BLE001
        log.warning("device_stat_failed counter=%s error=%s", counter, type(exc).__name__)


async def mark_read(device_id: str, kind: str, item: str) -> None:
    digest = hashlib.sha256(item.encode("utf-8")).hexdigest()[:16]
    await db.devices.update_one({"device_id": device_id}, {"$addToSet": {f"stats.{READS[kind]}": digest}})


def investigator(answered_by: Optional[str]) -> Optional[str]:
    """Which count an investigation's first answer adds to: TC Hawkeye settled it, or Magnum DI answered it."""
    if answered_by == "magnum_di":
        return "magnum_di"
    if outcomes.settled_by_flyby(answered_by):
        return "tc_flyby"
    return None


def counts(device: dict) -> dict[str, int]:
    stats = device.get("stats") or {}
    out = {name: int(stats.get(name) or 0) for name in COUNTERS}
    out.update({name: len(stats.get(name) or []) for name in READS.values()})
    return out


async def totals(match: Optional[dict] = None) -> dict[str, int]:
    """The counts of every device (or of those matching `match`) added up."""
    group: dict = {"_id": None}
    group.update({name: {"$sum": {"$ifNull": [f"$stats.{name}", 0]}} for name in COUNTERS})
    group.update({name: {"$sum": {"$size": {"$ifNull": [f"$stats.{name}", []]}}} for name in READS.values()})
    rows = await db.devices.aggregate([{"$match": {**(match or {}), "stats": {"$exists": True}}}, {"$group": group}]).to_list(1)
    row = rows[0] if rows else {}
    return {name: int(row.get(name) or 0) for name in (*COUNTERS, *READS.values())}
