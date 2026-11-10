"""VirusTotal URL/domain reputation check for the investigation pipeline (Finding G).

Uses the VirusTotal v3 URL endpoint. Each URL is base64url-encoded before the lookup
— only the identifier is sent, never page content.

Free-tier budget: 4 requests / minute, 500 / day across *all* VT modules
(both modules now share the same per-process limiter; account-wide enforcement is not yet established).
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

VT_API_KEY: str = os.getenv("VIRUSTOTAL_API_KEY", "")
VT_API_URL = "https://www.virustotal.com/api/v3"

# Share the existing in-process VirusTotal limiter with file-hash lookups.
# This is NOT a cross-worker or account-wide quota guarantee.
from services.virustotal import _rate_limit, quota_wait_seconds, note_quota_failure


@dataclass
class URLRepResult:
    """Reputation verdict for one URL from VirusTotal."""
    url: str
    # verdict: clean | suspicious | malicious | unknown | error | not_configured
    verdict: str
    detection_count: int = 0
    total_engines: int = 0
    categories: list[str] = field(default_factory=list)
    community_score: int = 0
    detail: str = ""


def _url_id(url: str) -> str:
    """Base64url-encode a URL for the VirusTotal v3 URL endpoint (no padding)."""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


async def check_url(url: str) -> URLRepResult:
    """Look up *url* in the VirusTotal analysis database.

    Returns a URLRepResult with the aggregate verdict. 404 (URL not analysed
    yet) is returned as verdict='unknown', not as an error.
    """
    if not VT_API_KEY:
        return URLRepResult(url=url, verdict="not_configured",
                            detail="VIRUSTOTAL_API_KEY is not set.")

    if quota_wait_seconds() > 0:
        return URLRepResult(url=url, verdict="error",
                            detail="VirusTotal quota temporarily unavailable (previous HTTP 429); URL not checked.")
    await _rate_limit()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{VT_API_URL}/urls/{_url_id(url)}",
                headers={"x-apikey": VT_API_KEY, "Accept": "application/json"},
            )

        if resp.status_code == 404:
            return URLRepResult(url=url, verdict="unknown",
                                detail="URL not yet analysed by VirusTotal.")
        if resp.status_code == 429:
            note_quota_failure(resp.headers.get("Retry-After"))
            return URLRepResult(url=url, verdict="error",
                                detail="VirusTotal returned HTTP 429 (rate or daily quota exhausted); URL not checked.")
        if resp.status_code != 200:
            return URLRepResult(url=url, verdict="error",
                                detail=f"VirusTotal returned HTTP {resp.status_code}.")

        attrs = resp.json().get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        undetected = stats.get("undetected", 0)
        harmless = stats.get("harmless", 0)
        total = malicious + suspicious + undetected + harmless

        # Site category tags supplied by AV engines (e.g. "phishing", "malware")
        raw_cats = attrs.get("categories") or {}
        categories = sorted({v for v in raw_cats.values() if v})[:5]

        community_score = attrs.get("reputation", 0)

        if malicious >= 3:
            return URLRepResult(
                url=url, verdict="malicious",
                detection_count=malicious, total_engines=total,
                categories=categories, community_score=community_score,
                detail=f"Flagged by {malicious}/{total} VirusTotal engines.",
            )
        if malicious > 0 or suspicious > 0:
            return URLRepResult(
                url=url, verdict="suspicious",
                detection_count=malicious + suspicious, total_engines=total,
                categories=categories, community_score=community_score,
                detail=f"Flagged as suspicious by {malicious + suspicious}/{total} engines.",
            )
        return URLRepResult(
            url=url, verdict="clean",
            detection_count=0, total_engines=total,
            categories=categories, community_score=community_score,
            detail=f"Not flagged by {total} VirusTotal engines.",
        )

    except httpx.TimeoutException:
        return URLRepResult(url=url, verdict="error",
                            detail="VirusTotal request timed out.")
    except Exception as exc:
        return URLRepResult(url=url, verdict="error",
                            detail=f"VirusTotal lookup failed ({type(exc).__name__}).")
