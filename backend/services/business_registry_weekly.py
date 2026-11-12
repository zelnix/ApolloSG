"""Weekly business-registry evidence refresh using the existing backend lifecycle.

No discovery of arbitrary businesses and no automatic approval of new numbers or
domains. Only previously reviewed registry entries are refreshed. Failed or
contradictory evidence withdraws logos; no untrusted source can re-approve them.
"""
from __future__ import annotations

import asyncio
import logging\nimport re\nfrom urllib.parse import urlsplit\nimport httpx
from datetime import datetime, timedelta, timezone

from core.db import db
from services.business_provider_adapters import (
    ProviderUnavailable, fetch_abn_lookup, fetch_brandfetch, fetch_twilio_lookup,
)
from services.verified_businesses import VerifiedBusiness, _digits, BusinessSource

log = logging.getLogger("apollo.business_registry_weekly")
INTERVAL = timedelta(days=7)\n\n\nasync def official_numbers_still_published(business: VerifiedBusiness) -> bool:\n    """Recheck the curator-approved HTTPS contact page; no arbitrary URL crawling."""\n    source_urls = [src.reference for src in business.sources\n                   if src.provider == "official_business_site" and src.supports == "number_association"]\n    if not source_urls or not business.official_domain:\n        return False\n    domain = business.official_domain.lower().strip(".")\n    async with httpx.AsyncClient(follow_redirects=False, timeout=8) as client:\n        for url in source_urls:\n            parsed = urlsplit(url)\n            if parsed.scheme != "https" or parsed.hostname not in (domain, "www." + domain) or parsed.port not in (None, 443):\n                continue\n            try:\n                response = await client.get(url, headers={"Accept": "text/html"}, follow_redirects=False)\n                response.raise_for_status()\n                if len(response.content) > 1_000_000:\n                    continue\n                page_digits = re.sub(r"\\D", "", response.text)\n                # Avoid concatenated unrelated numbers by matching each printed number separately.\n                number_tokens = re.findall(r"\\+?\\d[\\d\\s().-]{3,22}\\d", response.text)\n                published = { _digits(n) for n in number_tokens }\n                if all(_digits(n) in published for n in business.published_numbers):\n                    return True\n            except (httpx.HTTPError, UnicodeError, ValueError):\n                continue\n    return False\n
LEASE = timedelta(minutes=5)


async def refresh_one(record: dict) -> bool:
    """Only a full successful corroboration refresh extends the logo's seven-day life."""
    try:
        business = VerifiedBusiness.model_validate(record)
        if not business.abn or not business.official_domain or not business.published_numbers:
            return False
        abn, brand = await asyncio.gather(
            fetch_abn_lookup(business.abn), fetch_brandfetch(business.official_domain)
        )
        if not abn.get("registration_confirmed"):
            return False
        if str(abn.get("entity_name") or "").casefold().strip() != business.legal_name.casefold().strip():
            return False
        if brand.get("domain_queried") != business.official_domain.lower():
            return False
        if str(business.logo_url or "") not in brand.get("logo_candidates", []):
            return False
        # Twilio validates metadata only; it does NOT prove a business owns the number.
        # Failed lookups must not turn an unknown or invalid number into a verified one.
        results = await asyncio.gather(
            *(fetch_twilio_lookup(n) for n in business.published_numbers),
            return_exceptions=True,
        )
        if any(isinstance(r, Exception) or r.get("valid") is not True for r in results):
            return False
        # The original independently reviewed official-business-site number association
        # remains necessary; provider data alone never creates that evidence.
        if not any(s.provider == "official_business_site" and s.supports == "number_association"
                   for s in business.sources):
            return False
        return True
    except (ProviderUnavailable, ValueError, TypeError, KeyError):
        return False


async def run_due_once(*, now: datetime | None = None, limit: int = 50) -> int:
    """Atomic per-record claims prevent concurrent app workers from duplicating requests."""
    now = now or datetime.now(timezone.utc)
    processed = 0
    for _ in range(limit):
        record = await db.verified_businesses.find_one_and_update(
            {"$and": [
                {"$or": [{"next_refresh_at": {"$lte": now}}, {"next_refresh_at": {"$exists": False}}]},
                {"$or": [{"refresh_lease_until": {"$lte": now}}, {"refresh_lease_until": {"$exists": False}}]},
            ]},
            {"$set": {"refresh_lease_until": now + LEASE, "next_refresh_at": now + INTERVAL}},
            return_document=True,
        )
        if not record:
            break
        approved = await refresh_one(record)
        changes = {
            "last_refresh_attempt_at": now,
            "last_refresh_status": "verified" if approved else "withdrawn",
            "refresh_lease_until": now,
        }
        if approved:
            changes["last_reviewed_at"] = now
        else:
            # Withdraw branding immediately, even on provider outage. Do not delete
            # the record or its original evidence: allow review and later recovery.
            changes["logo_domain_confirmed"] = False
        await db.verified_businesses.update_one(
            {"_id": record["_id"], "refresh_lease_until": now + LEASE},
            {"$set": changes},
        )
        processed += 1
    return processed


async def supervise_weekly() -> None:
    """Cheap periodic due check; each record is refreshed no more than weekly."""
    while True:
        try:
            await run_due_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("weekly business registry refresh failed", exc_info=False)
        await asyncio.sleep(3600)
