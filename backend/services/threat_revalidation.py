"""Threat indicator revalidation — scheduled re-verification against original sources.

Corrected dual-timestamp design:
  next_scheduled_check — soft boundary: when to re-query the source. Missing it flags the
      indicator as check_overdue but does NOT expire it.
  evidence_expiry_deadline — hard boundary: if exceeded without successful re-verification,
      the indicator is moved to "expired" and excluded from active use.

Provider timeout ≠ proof of delisting. A timeout/error increments consecutive_check_failures
and schedules a retry with backoff, but NEVER moves the indicator to "expired". Only an
explicit "not found" / "clear" response from the source constitutes delisting evidence.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from core.config import logger
from core.db import db, now_utc
from core.models import (
    RevalidationOutcome,
    ThreatIndicator,
    ThreatIndicatorStatus,
    ThreatRevalidationLog,
)

# ── Configuration ──────────────────────────────────────────────────────────────

# Source-specific freshness intervals
SOURCE_CHECK_INTERVALS: dict[str, timedelta] = {
    "google_safe_browsing": timedelta(hours=4),
    "google_web_risk": timedelta(hours=4),
    "apollo_manual": timedelta(days=7),
    "apollo_blocklist": timedelta(days=7),
    "migration": timedelta(days=7),
}
DEFAULT_CHECK_INTERVAL = timedelta(hours=6)

SOURCE_EXPIRY_DEADLINES: dict[str, timedelta] = {
    "google_safe_browsing": timedelta(hours=24),
    "google_web_risk": timedelta(hours=24),
    "apollo_manual": timedelta(days=30),
    "apollo_blocklist": timedelta(days=30),
    "migration": timedelta(days=30),
}
DEFAULT_EXPIRY_DEADLINE = timedelta(hours=48)

# Retry backoff after provider failure (capped at 2 hours)
MAX_RETRY_BACKOFF = timedelta(hours=2)
BATCH_SIZE = 50  # max indicators to revalidate per cycle


def check_interval_for(source: str) -> timedelta:
    return SOURCE_CHECK_INTERVALS.get(source, DEFAULT_CHECK_INTERVAL)


def expiry_deadline_for(source: str) -> timedelta:
    return SOURCE_EXPIRY_DEADLINES.get(source, DEFAULT_EXPIRY_DEADLINE)


def _retry_backoff(consecutive_failures: int) -> timedelta:
    """Exponential backoff capped at MAX_RETRY_BACKOFF."""
    seconds = min(MAX_RETRY_BACKOFF.total_seconds(), 60 * (2 ** min(consecutive_failures, 7)))
    return timedelta(seconds=seconds)


# ── Source re-query ────────────────────────────────────────────────────────────

async def _revalidate_against_safe_browsing(hostname: str) -> RevalidationOutcome:
    """Historical provider is no longer connected; let its evidence expire.

    A different provider's negative result cannot prove this source delisted it.
    """
    return "source_unavailable"


async def _revalidate_against_web_risk(hostname: str) -> RevalidationOutcome:
    """Use the canonical quota-controlled provider, never a parallel transport."""
    from services.intel import google_url_lookup

    result, _expiry = await google_url_lookup(f"https://{hostname}/")
    if result.status == "match":
        return "confirmed"
    if result.status == "clear":
        return "source_delisted"
    return "source_unavailable"


async def _revalidate_against_blocklist(hostname: str) -> RevalidationOutcome:
    """Legacy Apollo blocklist check — DISABLED as independent verdict source.
    Product decision: Apollo does not maintain its own threat catalogue.
    Indicators sourced from 'apollo_blocklist' or 'migration' are not revalidated
    against the internal list. They expire naturally via evidence_expiry_deadline."""
    return "source_unavailable"


async def _revalidate_indicator(indicator: ThreatIndicator) -> RevalidationOutcome:
    """Dispatch revalidation to the appropriate source."""
    source = indicator.source
    if source == "google_safe_browsing":
        return await _revalidate_against_safe_browsing(indicator.hostname)
    elif source == "google_web_risk":
        return await _revalidate_against_web_risk(indicator.hostname)
    elif source in ("apollo_manual", "apollo_blocklist", "migration"):
        return await _revalidate_against_blocklist(indicator.hostname)
    else:
        logger.warning("threat_revalidation_unknown_source source=%s indicator=%s", source, indicator.indicator_id)
        return "source_unavailable"


# ── State transition logic ─────────────────────────────────────────────────────

async def _apply_revalidation_outcome(
    indicator: ThreatIndicator,
    outcome: RevalidationOutcome,
) -> ThreatIndicatorStatus:
    """Apply outcome to the indicator and return the new status.

    Rules:
    - "confirmed" → refresh both timestamps, reset failure count, status → "active"
    - "source_delisted" → explicit evidence the source no longer lists it → status → "expired"
    - "source_timeout" / "source_error" / "source_unavailable" →
        - increment consecutive_check_failures
        - schedule retry with backoff
        - NEVER expire (timeout ≠ delisting)
        - if was "active" → "check_overdue"
    """
    ts = now_utc()
    previous_status = indicator.status

    if outcome == "confirmed":
        # Source still lists it — refresh everything
        new_status: ThreatIndicatorStatus = "active"
        update: dict = {
            "status": new_status,
            "last_verified_at": ts,
            "last_revalidation_at": ts,
            "last_revalidation_outcome": outcome,
            "next_scheduled_check": ts + check_interval_for(indicator.source),
            "evidence_expiry_deadline": ts + expiry_deadline_for(indicator.source),
            "verification_count": indicator.verification_count + 1,
            "consecutive_check_failures": 0,
            "updated_at": ts,
        }

    elif outcome == "source_delisted":
        # Source explicitly confirmed it's no longer listed
        new_status = "expired"
        update = {
            "status": new_status,
            "last_revalidation_at": ts,
            "last_revalidation_outcome": outcome,
            "withdrawal_reason": "source_delisted",
            "withdrawn_at": ts,
            "updated_at": ts,
        }

    else:
        # Timeout, error, unavailable — NOT evidence of delisting
        failures = indicator.consecutive_check_failures + 1
        backoff = _retry_backoff(failures)
        new_status = "check_overdue" if previous_status == "active" else previous_status
        update = {
            "status": new_status,
            "last_revalidation_at": ts,
            "last_revalidation_outcome": outcome,
            "consecutive_check_failures": failures,
            "next_scheduled_check": ts + backoff,
            "updated_at": ts,
        }
        # Note: evidence_expiry_deadline is NOT extended on failure — it continues counting down

    await db.threat_indicators.update_one(
        {"indicator_id": indicator.indicator_id},
        {"$set": update},
    )

    # Write immutable audit log
    log_entry = ThreatRevalidationLog(
        indicator_id=indicator.indicator_id,
        hostname=indicator.hostname,
        attempted_at=ts,
        source=indicator.source,
        outcome=outcome,
        source_response_summary=f"{outcome} after {indicator.consecutive_check_failures} prior failures",
        previous_status=previous_status,
        new_status=new_status,
        next_scheduled_check=update.get("next_scheduled_check"),
        evidence_expiry_deadline=update.get("evidence_expiry_deadline", indicator.evidence_expiry_deadline),
    )
    await db.threat_revalidation_log.insert_one(log_entry.to_mongo())

    return new_status


# ── Hard expiry enforcement ────────────────────────────────────────────────────

async def _enforce_hard_expiry() -> int:
    """Expire indicators whose evidence_expiry_deadline has passed without re-verification.

    This is the safety boundary: even if scheduled checks keep failing due to provider
    outages, the hard deadline ensures stale indicators don't persist forever.
    """
    ts = now_utc()
    result = await db.threat_indicators.update_many(
        {
            "scope": "hostname",  # the free threat feeds' listings expire with their feed (services/threat_feeds.py)
            "status": {"$in": ["active", "check_overdue"]},
            "evidence_expiry_deadline": {"$lte": ts},
        },
        {
            "$set": {
                "status": "expired",
                "withdrawal_reason": "expired_unverified",
                "withdrawn_at": ts,
                "updated_at": ts,
            },
        },
    )
    expired_count = result.modified_count
    if expired_count:
        logger.info("threat_hard_expiry expired=%d", expired_count)
        # Log each expiry
        async for doc in db.threat_indicators.find({"status": "expired", "withdrawn_at": ts}):
            log_entry = ThreatRevalidationLog(
                indicator_id=doc["indicator_id"],
                hostname=doc["hostname"],
                attempted_at=ts,
                source=doc.get("source", "unknown"),
                outcome="source_unavailable",
                source_response_summary="hard evidence_expiry_deadline exceeded without re-verification",
                previous_status="check_overdue",
                new_status="expired",
            )
            await db.threat_revalidation_log.insert_one(log_entry.to_mongo())
    return expired_count


# ── Main revalidation cycle ────────────────────────────────────────────────────

async def revalidate_due_indicators() -> dict:
    """Run one revalidation cycle. Called by the maintenance loop.

    1. Select indicators where next_scheduled_check <= now AND status is active or check_overdue
    2. Re-query each against its original source
    3. Apply outcome (refresh, expire, or retry with backoff)
    4. Enforce hard expiry deadline on all indicators
    """
    ts = now_utc()
    stats = {"checked": 0, "confirmed": 0, "delisted": 0, "failures": 0, "hard_expired": 0}

    # 1. Select due indicators
    cursor = db.threat_indicators.find(
        {
            "scope": "hostname",  # the free threat feeds' listings are re-confirmed by their feed, not here
            "status": {"$in": ["active", "check_overdue"]},
            "next_scheduled_check": {"$lte": ts},
        },
    ).sort("next_scheduled_check", 1).limit(BATCH_SIZE)

    indicators = [ThreatIndicator.from_mongo(doc) async for doc in cursor]
    stats["checked"] = len(indicators)

    # 2-3. Revalidate each
    for indicator in indicators:
        try:
            outcome = await _revalidate_indicator(indicator)
            new_status = await _apply_revalidation_outcome(indicator, outcome)
            if outcome == "confirmed":
                stats["confirmed"] += 1
            elif outcome == "source_delisted":
                stats["delisted"] += 1
            else:
                stats["failures"] += 1
            logger.info(
                "threat_revalidation indicator=%s hostname=%s outcome=%s new_status=%s",
                indicator.indicator_id, indicator.hostname, outcome, new_status,
            )
        except Exception as exc:  # noqa: BLE001
            stats["failures"] += 1
            logger.error(
                "threat_revalidation_error indicator=%s type=%s",
                indicator.indicator_id, type(exc).__name__,
            )

    # 4. Enforce hard expiry
    stats["hard_expired"] = await _enforce_hard_expiry()

    if stats["checked"] or stats["hard_expired"]:
        logger.info("threat_revalidation_cycle %s", stats)

    return stats


# ── Index setup ────────────────────────────────────────────────────────────────

async def ensure_indexes() -> None:
    await db.threat_indicators.create_index("indicator_id", unique=True)
    await db.threat_indicators.create_index("hostname")
    await db.threat_indicators.create_index([("status", 1), ("next_scheduled_check", 1)])
    await db.threat_indicators.create_index("evidence_expiry_deadline")
    await db.threat_revalidation_log.create_index("indicator_id")
    await db.threat_revalidation_log.create_index("attempted_at")


# ── Migration helper ───────────────────────────────────────────────────────────

async def migrate_blocklist_entries() -> int:
    """One-time migration: convert existing BlocklistEntry records to ThreatIndicator format.

    Only migrates entries that don't already have a corresponding ThreatIndicator.
    Marks migrated entries as review_status: "legacy_migrated".
    """
    ts = now_utc()
    migrated = 0

    async for entry in db.blocklist.find({"deleted_at": None}):
        hostname = entry.get("host", "").strip().lower()
        if not hostname:
            continue

        # Skip if already migrated
        existing = await db.threat_indicators.find_one({"hostname": hostname, "scope": "hostname", "status": {"$ne": "withdrawn"}})
        if existing:
            continue

        indicator_id = f"ti-{secrets.token_hex(8)}"
        indicator = ThreatIndicator(
            indicator_id=indicator_id,
            hostname=hostname,
            scope="hostname",
            source="migration",
            source_reference=None,
            original_evidence=f"Migrated from BlocklistEntry: {entry.get('reason', 'no reason recorded')}",
            original_scope="hostname",
            first_seen_at=entry.get("added_at", ts),
            last_verified_at=ts,
            next_scheduled_check=ts + timedelta(days=1),  # Check within 24h
            evidence_expiry_deadline=ts + timedelta(days=30),  # 30-day grace for legacy entries
            verification_count=0,
            status="active",
            review_status="legacy_migrated",
            added_at=ts,
            updated_at=ts,
            added_by="migration",
        )
        await db.threat_indicators.update_one(
            {"indicator_id": indicator_id},
            {"$set": indicator.to_mongo()},
            upsert=True,
        )
        migrated += 1

    if migrated:
        logger.info("threat_indicator_migration migrated=%d", migrated)
    return migrated
