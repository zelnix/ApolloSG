"""Explicit curator-triggered enrichment; never auto-approves branding or publishes a registry record."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.business_provider_adapters import (
    ProviderUnavailable, fetch_abn_lookup, fetch_brandfetch, fetch_twilio_lookup,
)


async def research_business_candidate(*, abn: str, official_domain: str, published_number: str) -> dict[str, Any]:
    """Collect independent provider observations for manual review.

    The supplied domain and phone number must already come from an independently
    reviewed official business source. ABN Lookup and Brandfetch cannot prove them.
    Provider failures remain visible; no candidate becomes verified automatically.
    """
    observations: dict[str, Any] = {}
    for name, fetch in (
        ("abn_lookup", lambda: fetch_abn_lookup(abn)),
        ("brandfetch", lambda: fetch_brandfetch(official_domain)),
        ("twilio_lookup_v2", lambda: fetch_twilio_lookup(published_number)),
    ):
        try:
            observations[name] = {"status": "ok", "data": await fetch()}
        except (ProviderUnavailable, ValueError) as exc:
            observations[name] = {"status": "unavailable", "reason": type(exc).__name__}
    return {
        "candidate": {"abn": abn, "official_domain": official_domain, "published_number": published_number},
        "observations": observations,
        "researched_at": datetime.now(timezone.utc).isoformat(),
        "review_required": True,
        "registry_approved": False,
        "caller_authenticated": False,
    }
