"""URL threat intelligence — IPQS malicious-URL scoring + download-link detection.

Complements the existing redirect-expansion and Google Safe Browsing checks with:
1. IPQS URL fraud scoring (phishing, malware, parking, suspicious indicators).
2. Static download-link detection for URLs pointing to dangerous file types.

IPQS key is shared with the phone-risk module (single IPQS_API_KEY env var).
Results are cached in `url_risk_cache` (Mongo) with the same TTL-at-read pattern
used by phone_risk_cache and rdap_cache.
"""
from __future__ import annotations

import asyncio
import re
from datetime import timezone
from typing import Optional
from urllib.parse import urlparse, unquote

import httpx

from core.config import IPQS_API_KEY, IPQS_URL_ENDPOINT, logger
from core.db import db, now_utc
from services import reusable_intel

CACHE_TTL = reusable_intel.TTL["url_reputation"]  # URL risk signals change; refresh twice a day
SITE = "ipqs_url"  # this call site, in the reuse counters
MAX_RETRIES = 2                  # retry up to 2 more times on transient failure, then surface "unavailable"
RETRY_BACKOFF = 1.0

# ── Download-link detection ─────────────────────────────────────────────────
# File extensions commonly associated with malware delivery, exploit kits, or
# social-engineering payloads. This list intentionally covers both desktop and
# mobile attack vectors (Android .apk, macOS .dmg, Windows .exe/.msi etc.).
DANGEROUS_EXTENSIONS = frozenset({
    # Executables / installers
    ".exe", ".msi", ".msp", ".scr", ".com", ".pif", ".bat", ".cmd", ".ps1",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".reg",
    # macOS
    ".dmg", ".pkg", ".app",
    # Mobile
    ".apk", ".xapk", ".ipa",
    # Archives (often used to bypass email filters)
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".cab", ".iso", ".img",
    # Office macros / exploits
    ".docm", ".xlsm", ".pptm", ".dotm", ".xltm",
    # Other dangerous
    ".hta", ".cpl", ".inf", ".lnk", ".jar", ".dll", ".sys",
})

# URL shorteners whose domains should always trigger redirect expansion before
# any reputation check runs on the final destination.
SHORTENER_DOMAINS = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "adf.ly", "cutt.ly", "rb.gy", "shorturl.at", "tiny.cc", "v.gd", "clck.ru",
    "bl.ink", "lnkd.in", "surl.li", "rebrand.ly",
})

_EXT_RE = re.compile(r"\.([a-zA-Z0-9]{2,5})(?:\?|#|$)")


def detect_download_links(urls: list[str]) -> list[dict]:
    """Return metadata for URLs whose path ends in a dangerous file extension."""
    results = []
    for url in urls:
        try:
            parsed = urlparse(url)
            path = unquote(parsed.path).lower()
            match = _EXT_RE.search(path)
            if match:
                ext = f".{match.group(1)}"
                if ext in DANGEROUS_EXTENSIONS:
                    results.append({
                        "url": url[:300],
                        "filename": path.rsplit("/", 1)[-1] if "/" in path else path,
                        "extension": ext,
                        "dangerous": True,
                        "category": _ext_category(ext),
                    })
        except Exception:
            continue
    return results


def _ext_category(ext: str) -> str:
    if ext in {".exe", ".msi", ".msp", ".scr", ".com", ".pif", ".bat", ".cmd", ".ps1", ".dll", ".sys"}:
        return "windows_executable"
    if ext in {".dmg", ".pkg", ".app"}:
        return "macos_installer"
    if ext in {".apk", ".xapk", ".ipa"}:
        return "mobile_app"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".cab", ".iso", ".img"}:
        return "archive"
    if ext in {".docm", ".xlsm", ".pptm", ".dotm", ".xltm"}:
        return "office_macro"
    if ext in {".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta"}:
        return "script"
    return "other_dangerous"


def is_shortener(url: str) -> bool:
    """Check if a URL is from a known URL shortener service."""
    try:
        host = urlparse(url).hostname or ""
        return host.lower() in SHORTENER_DOMAINS
    except Exception:
        return False


# ── IPQS URL reputation ─────────────────────────────────────────────────────

async def check_url_risk(url: str) -> Optional[dict]:
    """Query IPQS URL reputation API and return structured result.

    Returns None if IPQS is not configured or the query fails after retries.
    """
    if not IPQS_API_KEY:
        return {"status": "not_configured", "url": url[:300]}

    ts = now_utc()

    # Cache lookup
    cached = await db.url_risk_cache.find_one({"url": url[:500]})
    if cached:
        expires = cached.get("expires_at")
        if expires and expires.replace(tzinfo=timezone.utc) > ts:
            logger.debug("url_risk cache hit url=%s", url[:60])
            await reusable_intel.count(SITE, "cache_hit", "sufficiency_known", "external_call_avoided")
            result = dict(cached)
            result.pop("_id", None)
            result["cached"] = True
            return result
    await reusable_intel.count(SITE, *(("cache_expired", "sufficiency_partial") if cached else ("sufficiency_unknown",)), "external_call_required")

    # Live query
    last_exc: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
                resp = await http.post(
                    f"{IPQS_URL_ENDPOINT}/{IPQS_API_KEY}",
                    data={"url": url, "strictness": 1},
                )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or data.get("success") is not True:
                logger.warning("IPQS URL check returned non-success: %s", data.get("message", "unknown"))
                return {"status": "error", "url": url[:300], "detail": data.get("message", "Unknown error")}

            result = {
                "url": url[:300],
                "domain": data.get("domain", ""),
                "risk_score": data.get("risk_score"),
                "suspicious": data.get("suspicious", False),
                "phishing": data.get("phishing", False),
                "malware": data.get("malware", False),
                "parking": data.get("parking", False),
                "spamming": data.get("spamming", False),
                "adult": data.get("adult", False),
                "unsafe": data.get("unsafe", False),
                "domain_age_days": data.get("domain_age", {}).get("human") if isinstance(data.get("domain_age"), dict) else None,
                "category": data.get("category", ""),
                "status": "ok",
                "queried_at": ts.isoformat(),
                "decision": _url_decision(data),
            }

            # Cache
            await db.url_risk_cache.update_one(
                {"url": url[:500]},
                {"$set": {**result, "expires_at": ts + CACHE_TTL}},
                upsert=True,
            )
            await reusable_intel.count(SITE, "cache_write")
            logger.info("url_risk checked url=%s score=%s decision=%s", url[:60], result["risk_score"], result["decision"])
            return result

        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            else:
                logger.error("IPQS URL all attempts failed for %s: %s", url[:60], type(exc).__name__)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            else:
                logger.error("IPQS URL returned %d for %s", resp.status_code, url[:60])
                break

    # Stale cache fallback
    stale = await db.url_risk_cache.find_one({"url": url[:500]})
    if stale:
        result = dict(stale)
        result.pop("_id", None)
        result["cached"] = True
        result["stale"] = True
        return result

    return {"status": "unavailable", "url": url[:300], "detail": type(last_exc).__name__ if last_exc else "unknown"}


def _url_decision(data: dict) -> str:
    """Conservative URL risk decision matching IPQS recommended thresholds."""
    if data.get("malware") is True or data.get("phishing") is True:
        return "dangerous"
    if data.get("unsafe") is True or (data.get("risk_score") or 0) >= 85:
        return "high_risk"
    if data.get("suspicious") is True or (data.get("risk_score") or 0) >= 75:
        return "suspicious"
    if data.get("parking") is True:
        return "parking"
    return "clean"
