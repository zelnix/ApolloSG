"""Google Web Risk Lookup: enabled by default on slm when configured. No caller may bypass the shared Mongo quota reservation.
Only uris.search is permitted; never hashes.search / computeDiff.
No URL, API key, or case content is written to shared cache or logs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc
from services.intel import sanitize_url, digest
from services import reusable_intel

PROVIDER = "google_web_risk"
ENDPOINT = "https://webrisk.googleapis.com/v1/uris:search"
THREATS = ("MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE")
OPERATIONAL_STOP = 95_000
HARD_CEILING = 100_000
TEST_BUDGET = 10_000
PRODUCTION_BUDGET = OPERATIONAL_STOP - TEST_BUDGET
# Billing period is calendar month in UTC; production activation requires Cloud billing verification.
CACHE_NO_MATCH = timedelta(minutes=5)


def enabled() -> bool:
    return os.environ.get("GOOGLE_WEB_RISK_ENABLED", "true").lower() == "true"


def period(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m")


async def reserve(*, testing: bool = False) -> bool | None:
    """Atomic cross-worker reservation, including uncertain outcomes. Fail closed on Mongo errors.

    A single quota document is shared across backend instances. Reservations are never
    refunded on timeout, cancellation or transport failure. Monthly documents are retained.
    """
    month = period(now_utc())
    collection = db.web_risk_quota
    try:
        try:
            await collection.insert_one({"_id": month, "reserved": 0, "testing_reserved": 0, "production_reserved": 0, "created_at": now_utc()})
        except DuplicateKeyError:
            pass
        field = "testing_reserved" if testing else "production_reserved"
        limit = TEST_BUDGET if testing else PRODUCTION_BUDGET
        result = await collection.find_one_and_update(
            {"_id": month, "$expr": {"$and": [{"$lt": [{"$ifNull": ["$reserved", 0]}, min(OPERATIONAL_STOP, HARD_CEILING)]}, {"$lt": [{"$ifNull": ["$" + field, 0]}, limit]}]}},
            {"$inc": {"reserved": 1, field: 1}, "$set": {"last_reserved_at": now_utc()}},
            return_document=ReturnDocument.AFTER,
        )
        return result is not None
    except Exception:
        return None


async def _lookup_uncached(url: str, *, testing: bool = False) -> dict:
    """Provider result is non-authoritative until mapped through existing intel contracts."""
    result = {"provider": PROVIDER, "status": "not_checked", "threat_types": []}
    if not enabled():
        return {**result, "reason": "production_disabled"}
    key = os.environ.get("GOOGLE_WEB_RISK_API_KEY", "")
    if not key:
        return {**result, "status": "unavailable", "reason": "not_configured"}
    try:
        clean, _ = sanitize_url(url)
    except Exception:
        return {**result, "status": "unavailable", "reason": "invalid_url"}
    identity = digest(("google_web_risk:test:" if testing else "google_web_risk:") + clean)
    now = now_utc()
    try:
        cached = await db.web_risk_cache.find_one({"_id": identity, "expires_at": {"$gt": now}})
        if cached:
            return {"provider": PROVIDER, "status": "cached_result",
                    "underlying_status": cached["status"], "threat_types": cached["threat_types"],
                    "checked_at": cached["checked_at"].isoformat(), "expires_at": cached["expires_at"].isoformat()}
    except Exception:
        return {**result, "status": "unavailable", "reason": "cache_unavailable"}
    reservation = await reserve(testing=testing)
    if reservation is None:
        return {**result, "status": "unavailable", "reason": "accounting_unavailable"}
    if not reservation:
        return {**result, "status": "quota_exhausted", "reason": "application_cutoff"}
    # No automatic retries: each attempt is potentially billable.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), follow_redirects=False) as client:
            response = await client.get(ENDPOINT, params=[("uri", clean), *[("threatTypes", t) for t in THREATS], ("key", key)])
        if response.status_code == 429:
            return {**result, "status": "quota_exhausted", "reason": "provider_quota"}
        if response.status_code != 200:
            return {**result, "status": "unavailable", "reason": "provider_error"}
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("threat", {}), dict):
            return {**result, "status": "unavailable", "reason": "malformed_response"}
        threat = payload.get("threat", {})
        types = threat.get("threatTypes") if threat else []
        if not isinstance(types, list) or (threat and not types) or any(t not in THREATS for t in types):
            return {**result, "status": "unavailable", "reason": "malformed_response"}
        status = "threat_match" if types else "no_match"
        expires = now + CACHE_NO_MATCH
        if types:
            raw_expiry = threat.get("expireTime")
            try:
                expires = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
                if expires <= now: return {**result, "status": "unavailable", "reason": "expired_provider_result"}
            except (AttributeError, ValueError, TypeError):
                return {**result, "status": "unavailable", "reason": "missing_expiry"}
        await db.web_risk_cache.update_one({"_id": identity}, {"$set": {
            "status": status, "threat_types": types, "checked_at": now, "expires_at": expires,
        }}, upsert=True)
        return {"provider": PROVIDER, "status": status, "threat_types": types,
                "checked_at": now.isoformat(), "expires_at": expires.isoformat()}
    except (httpx.HTTPError, ValueError, TypeError):
        return {**result, "status": "unavailable", "reason": "request_failed"}
    except Exception:
        return {**result, "status": "unavailable", "reason": "persistence_or_provider_error"}

async def lookup(url: str, *, testing: bool = False) -> dict:
    """Coalesce equivalent requests across workers via existing Mongo in-flight claims."""
    if not enabled():
        return {"provider": PROVIDER, "status": "not_checked", "threat_types": [], "reason": "production_disabled"}
    try:
        clean, _ = sanitize_url(url)
    except Exception:
        return {"provider": PROVIDER, "status": "unavailable", "threat_types": [], "reason": "invalid_url"}
    if not os.environ.get("GOOGLE_WEB_RISK_API_KEY"):
        return {"provider": PROVIDER, "status": "unavailable", "threat_types": [], "reason": "not_configured"}
    identity = digest(("google_web_risk:test:" if testing else "google_web_risk:") + clean)
    async def reuse():
        try:
            row = await db.web_risk_cache.find_one({"_id": identity, "expires_at": {"$gt": now_utc()}})
            if row:
                return {"provider": PROVIDER, "status": "cached_result", "underlying_status": row["status"],
                        "threat_types": row["threat_types"], "checked_at": row["checked_at"].isoformat(),
                        "expires_at": row["expires_at"].isoformat()}
        except Exception:
            return {"provider": PROVIDER, "status": "unavailable", "threat_types": [], "reason": "cache_unavailable"}
        return None
    try:
        existing = await reuse()
        if existing is not None: return existing
        result = await reusable_intel.once("web_risk:" + identity, lambda: _lookup_uncached(clean, testing=testing), reuse=reuse)
        return result if result is not None else {"provider": PROVIDER, "status": "unavailable",
                                                   "threat_types": [], "reason": "concurrent_lookup_unresolved"}
    except Exception:
        return {"provider": PROVIDER, "status": "unavailable", "threat_types": [], "reason": "accounting_or_coalescing_unavailable"}
