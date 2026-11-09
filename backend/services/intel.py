"""Reputation intelligence: external providers (Google Safe Browsing and the free threat lists in
services/threat_feeds.py), HMAC digest cache, redirect expansion.

Product decision: Apollo's internal blocklist (db.blocklist) is no longer used as an independent
verdict source. External specialist providers are the authoritative intelligence sources.
Historical blocklist data is preserved for audit but does not participate in verdicts."""
from __future__ import annotations

import asyncio
import hmac
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException

from core.config import SAFE_BROWSING_API_KEY, SB_ENDPOINT, SB_THREAT_TYPES, URL_HMAC_SECRET, logger
from core.db import db, now_utc
from core.models import BlocklistEntry, IntelCheckResponse, IntelSource, ReputationCache, Verdict
from services.rdap import lookup_domain_cached
from services.outbound import OutboundBlocked, public_stream, REDIRECTS

def digest(value: str) -> str:
    return hmac.new(URL_HMAC_SECRET.encode(), value.encode(), sha256).hexdigest()


def sanitize_url(raw: str) -> tuple[str, str]:
    """Strip credentials, fragments and secret query params; preserve path. Return (url, host).
    Validation only, no canonicalisation games. The path is kept so that reputation sources
    (e.g. Safe Browsing) can match page-specific threats, not just the origin."""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlparse(candidate)
        hostname, port = parsed.hostname, parsed.port
    except ValueError:
        raise HTTPException(status_code=422, detail="Only http/https links can be checked")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise HTTPException(status_code=422, detail="Only http/https links can be checked")
    host = hostname.lower()
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    # Preserve the path for page-specific reputation; strip credentials, fragments and secret
    # query parameters. An empty path normalises to "/".
    path = parsed.path or "/"
    # Strip query parameters that look like they may carry secrets (tokens, session IDs, etc.)
    secret_re = re.compile(r"token|code|otp|auth|session|password|pass|secret|key|signature|sig", re.I)
    safe_params = []
    if parsed.query:
        from urllib.parse import parse_qsl, urlencode
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if secret_re.search(k):
                continue  # drop secret-looking params entirely
            safe_params.append((k, v))
    clean_query = urlencode(safe_params) if safe_params else ""
    clean = urlunparse((parsed.scheme, netloc, path, "", clean_query, ""))
    return clean, host


def host_matches(host: str, entry_host: str) -> bool:
    return host == entry_host or host.endswith("." + entry_host)


async def blocklist_check(host: str) -> IntelSource:
    # Targeted query: check the exact host and all parent domains instead of loading up to N entries.
    # This removes the previous 5,000-entry cap that silently stopped checking on large lists.
    candidates = [host]
    parts = host.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[i:])
        if "." in parent:  # at least a second-level domain
            candidates.append(parent)
    entry_raw = await db.blocklist.find_one({"deleted_at": None, "host": {"$in": candidates}})
    if entry_raw:
        entry = BlocklistEntry.from_mongo(entry_raw)
        if host_matches(host, entry.host):
            return IntelSource(
                name="apollo_blocklist",
                status="match",
                detail=f"Domain is on Apollo's managed threat list ({entry.reason}).",
                threat_types=[entry.threat_type],
            )
    return IntelSource(name="apollo_blocklist", status="clear", detail="Not on Apollo's managed threat list.")


_sb_probe: dict[str, Any] = {"status": None, "checked_at": None, "detail": ""}


def _sb_unavailable(detail: str, failure: str) -> tuple[IntelSource, None]:
    return IntelSource(name="google_safe_browsing", status="unavailable", detail=detail, failure=failure), None


async def safe_browsing_lookup(url: str) -> tuple[IntelSource, Optional[datetime]]:
    if not SAFE_BROWSING_API_KEY:
        return IntelSource(name="google_safe_browsing", status="not_configured", detail="No Safe Browsing key configured.", failure="not_configured"), None
    # Short-circuit while the key is known-bad (re-probed every 10 minutes) to avoid hammering Google.
    if _sb_probe["status"] == "auth_error" and _sb_probe["checked_at"] and now_utc() - _sb_probe["checked_at"] < timedelta(minutes=10):
        return _sb_unavailable("Safe Browsing key was rejected; reputation check unavailable.", "auth_failure")
    payload = {
        "client": {"clientId": "apollo-v1", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": SB_THREAT_TYPES,
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(SB_ENDPOINT, params={"key": SAFE_BROWSING_API_KEY}, json=payload)
        if resp.status_code in (401, 403):
            _sb_probe.update(status="auth_error", checked_at=now_utc(), detail="Key rejected by Google Safe Browsing.")
            return _sb_unavailable("Safe Browsing key was rejected; reputation check unavailable.", "auth_failure")
        if resp.status_code == 429:
            _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing quota used up.")
            return _sb_unavailable("Safe Browsing's lookup quota is used up for now.", "quota_exhausted")
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing did not respond.")
        return _sb_unavailable("Safe Browsing did not respond in time.", "timeout")
    except httpx.HTTPStatusError as exc:
        _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing returned an error.")
        return _sb_unavailable("Safe Browsing returned an error.", "server_error" if exc.response.status_code >= 500 else "rejected")
    except httpx.HTTPError:
        _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing could not be reached.")
        return _sb_unavailable("Safe Browsing could not be reached.", "provider_unavailable")
    except ValueError:
        _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing answer was malformed.")
        return _sb_unavailable("Safe Browsing sent an unreadable answer.", "malformed")
    if not isinstance(data, dict) or not isinstance(data.get("matches", []), list):
        # Malformed answer (wrong shape) is rejected — degrade to "unavailable", never read it as "clear".
        _sb_probe.update(status="unreachable", checked_at=now_utc(), detail="Safe Browsing answer was malformed.")
        return _sb_unavailable("Safe Browsing sent an unreadable answer.", "malformed")
    _sb_probe.update(status="ok", checked_at=now_utc(), detail="Safe Browsing reachable.")
    matches = [m for m in data.get("matches", []) if isinstance(m, dict)]
    if matches:
        threats = sorted({str(m.get("threatType", "UNKNOWN")) for m in matches})
        seconds = 300
        try:
            seconds = max(60, int(str(matches[0].get("cacheDuration", "300s")).rstrip("s").split(".")[0]))
        except ValueError:
            pass
        return (
            IntelSource(name="google_safe_browsing", status="match", detail="Listed as unsafe by Google Safe Browsing.", threat_types=threats,
                        url=transparency_page(url)),
            now_utc() + timedelta(seconds=seconds),
        )
    return IntelSource(name="google_safe_browsing", status="clear", detail="No current Safe Browsing listing.", url=transparency_page(url)), None


async def google_url_lookup(url: str) -> tuple[IntelSource, Optional[datetime]]:
    """Staged provider switch; legacy Safe Browsing stays intact until acceptance passes."""
    import os
    if os.environ.get("GOOGLE_URL_PROVIDER", "safe_browsing") != "web_risk":
        return await safe_browsing_lookup(url)
    from services.google_web_risk import lookup
    result = await lookup(url)
    state = result.get("underlying_status", result.get("status"))
    cached = result.get("status") == "cached_result"
    expiry = None
    if result.get("expires_at"):
        try:
            expiry = datetime.fromisoformat(result["expires_at"])
        except (ValueError, TypeError):
            pass
    if state == "threat_match":
        return IntelSource(name="google_web_risk", status="match",
                           detail="Google Web Risk reported a threat match" + (" (cached)." if cached else "."),
                           threat_types=result.get("threat_types", [])), expiry
    if state == "no_match":
        return IntelSource(name="google_web_risk", status="clear",
                           detail="No listing found by Google Web Risk; this does not establish that the link is safe." +
                                  (" (cached)." if cached else ".")), expiry
    failure = result.get("reason") or state
    return IntelSource(name="google_web_risk", status="unavailable",
                       detail="Google Web Risk could not complete this check.",
                       failure=str(failure)), None


def transparency_page(url: str) -> str:
    """Google's own public page for a Safe Browsing listing (its Transparency Report site status)."""
    from urllib.parse import quote
    host = (urlparse(url).hostname or url).lower()
    return f"https://transparencyreport.google.com/safe-browsing/search?url={quote(host, safe='')}"


# How each list is named to a person.
SOURCE_LABELS = {"google_web_risk": "Google Web Risk", "google_safe_browsing": "Google Safe Browsing", "apollo_blocklist": "Apollo's blocklist", "phishtank": "PhishTank",
                 "openphish": "OpenPhish", "spamhaus_drop": "Spamhaus DROP", "asic_investor_alerts": "ASIC's investor alert list",
                 "acma_blocked_gambling": "ACMA's blocked gambling websites list"}


def label(name: str) -> str:
    return SOURCE_LABELS.get(name, name.replace("_", " "))


def _names(labels: list[str]) -> str:
    labels = list(dict.fromkeys(labels))
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1] if labels else ""


def listed_by(sources: list[dict] | None, default: str = "Google Safe Browsing") -> str:
    """The lists that list it ("PhishTank and Google Safe Browsing"), from a check's recorded sources."""
    return _names([label(s.get("name") or "") for s in sources or [] if s.get("status") == "match"]) or default


def answered(sources: list[dict] | None, default: str = "Google Safe Browsing") -> str:
    """The lists that answered (listed or not), for a "not listed by …" statement."""
    return _names([label(s.get("name") or "") for s in sources or [] if s.get("status") in ("match", "clear")]) or default


def combine(sources: list[IntelSource]) -> tuple[Verdict, list[str], str]:
    threats = sorted({t for s in sources for t in s.threat_types})
    if any(s.status == "match" for s in sources):
        return "malicious", threats, "full" if all(s.status in ("match", "clear") for s in sources) else "partial"
    clear = [s for s in sources if s.status == "clear"]
    if len(clear) == len(sources):
        return "clean", [], "full"
    if clear:
        return "unknown", [], "partial"
    return "unknown", [], "none"


def _expansion_failure(exc: BaseException) -> str:
    """Why the final destination couldn't be verified — a technically accurate code, never a guess."""
    if isinstance(exc, OutboundBlocked):
        code = str(exc)
        if code == "dns_failed":
            return "timeout" if isinstance(exc.__cause__, asyncio.TimeoutError) else "nonexistent_domain"
        return {"private_target": "unsafe_destination", "invalid_target": "unparseable_link",
                "too_many_redirects": "redirect_limit", "fetch_failed": "connection_failure"}.get(code, "redirect_failure")
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_failure"
    return "redirect_failure"


async def expand_redirects_detailed(url: str, max_hops: int = 5) -> tuple[list[str], bool, Optional[str], Optional[str]]:
    """Follow HTTP redirects without downloading bodies.

    Returns (chain, complete, reason, failure). `complete` is False when the chain was cut short by an error,
    a timeout, an unsafe hop or the hop limit — in that case the last element is NOT known to be the
    real destination, and callers must not treat it as one. `failure` is the code for why: nonexistent_domain,
    connection_failure, timeout, unsafe_destination, redirect_limit, unparseable_link or redirect_failure.

    Privacy: every URL (initial and each redirect destination) is sanitised before any
    outbound request is made, preventing PII or credentials embedded in URLs from leaking
    to remote servers during redirect expansion."""
    # Sanitise the initial URL before the first outbound request.
    try:
        sanitised_initial, _ = sanitize_url(url)
    except HTTPException:
        return [url], False, "the link could not be parsed, so no redirects were followed", "unparseable_link"
    chain = [sanitised_initial]
    complete, reason, failure = True, None, None
    try:
        async with asyncio.timeout(12):
            cur = sanitised_initial
            for _ in range(min(max_hops, 5)):
                async with public_stream("HEAD", cur) as resp:
                    status, loc = resp.status_code, resp.headers.get("location")
                if status in (405, 403, 400):
                    # Headers only; close without buffering any GET body.
                    async with public_stream("GET", cur) as resp:
                        status, loc = resp.status_code, resp.headers.get("location")
                if status not in REDIRECTS or not loc:
                    break
                raw_nxt = str(httpx.URL(cur).join(loc))
                # Sanitise every redirect destination before following it.
                try:
                    nxt, _ = sanitize_url(raw_nxt)
                except HTTPException:
                    complete, reason, failure = False, "the chain pointed at a destination ApolloSG could not safely follow", "unsafe_destination"
                    break
                if nxt in chain:
                    break
                chain.append(nxt)
                cur = nxt
            else:
                # The loop ran out of hops rather than reaching a final destination.
                complete, reason, failure = False, f"the link redirected more than {min(max_hops, 5)} times", "redirect_limit"
    except Exception as exc:  # noqa: BLE001
        logger.info("redirect expansion stopped: %s", type(exc).__name__)
        failure = _expansion_failure(exc)
        complete, reason = False, f"the redirect chain could not be followed to the end ({failure.replace('_', ' ')})"
    return chain, complete, reason, failure


async def expand_redirects(url: str, max_hops: int = 5) -> list[str]:
    """Chain only. Prefer expand_redirects_detailed when the caller reports coverage to a person."""
    chain, _complete, _reason, _failure = await expand_redirects_detailed(url, max_hops)
    return chain


async def run_intel_check(indicator_type: str, value: str) -> IntelCheckResponse:
    url, host = sanitize_url(value)
    indicator = host if indicator_type == "domain" else url
    import os
    provider = os.environ.get("GOOGLE_URL_PROVIDER", "safe_browsing")
    # Isolate legacy Safe Browsing entries from staged Web Risk entries.
    if provider == "web_risk":
        active = os.environ.get("GOOGLE_WEB_RISK_ENABLED", "").lower() == "true"
        dg = digest(f"google_web_risk:{'active' if active else 'disabled'}:{indicator}")
    else:
        dg = digest(indicator)
    ts = now_utc()
    cached = await db.reputation_cache.find_one({"indicator_digest": dg})
    if cached:
        rc = ReputationCache.from_mongo(cached)
        if rc.expires_at.replace(tzinfo=timezone.utc) > ts:
            return IntelCheckResponse(
                verdict=rc.verdict, threat_types=rc.threat_types, sources=[IntelSource(**s) for s in rc.sources],
                indicator_digest=dg, checked_at=rc.checked_at, cached=True, coverage=rc.coverage,  # type: ignore[arg-type]
            )
    # ── Intelligence sources: Apollo blocklist + external providers + the free threat lists ──
    from services import threat_feeds
    bl_source = await blocklist_check(host)
    (sb_source, sb_expiry), feed_sources = await asyncio.gather(
        google_url_lookup(url if indicator_type == "url" else f"http://{host}/"),
        threat_feeds.listing_sources(host, url if indicator_type == "url" else None))
    sources = [bl_source, sb_source, *feed_sources]
    verdict, threats, coverage = combine(sources)
    expires = sb_expiry or (ts + timedelta(minutes=5 if verdict != "unknown" else 1))
    record = ReputationCache(
        indicator_digest=dg, verdict=verdict, threat_types=threats, sources=[s.model_dump() for s in sources],
        coverage=coverage, checked_at=ts, expires_at=expires,
    )
    await db.reputation_cache.update_one({"indicator_digest": dg}, {"$set": record.to_mongo()}, upsert=True)
    return IntelCheckResponse(
        verdict=verdict, threat_types=threats, sources=sources, indicator_digest=dg, checked_at=ts, cached=False, coverage=coverage  # type: ignore[arg-type]
    )


async def assess_indicator(indicator_type: str, value: str, expand: bool) -> IntelCheckResponse:
    """The full check: blocklist + Safe Browsing verdict, optional redirect-chain expansion (URLs
    only), and a best-effort/parallel RDAP domain-info lookup (see services/rdap.py) — never gates
    the verdict. This is THE shared assessment used by both POST /intel/check (Check a Link) and
    POST /message/analyse (Email/Text Guard's automatic per-link pre-click assessment), so every
    link checked anywhere in the app gets the exact same treatment. Pure extraction of the previous
    /intel/check body — behaviour for that endpoint is unchanged."""
    if indicator_type == "url":
        try:
            initial_host: Optional[str] = sanitize_url(value)[1]
        except HTTPException:
            initial_host = None
    else:
        initial_host = value.strip().lower() or None
    domain_task = asyncio.create_task(lookup_domain_cached(initial_host)) if initial_host else None

    async def _await_domain():
        if not domain_task:
            return None
        try:
            return await asyncio.wait_for(domain_task, timeout=6.0)
        except Exception:  # noqa: BLE001
            return None

    if not expand or indicator_type != "url":
        result = await run_intel_check(indicator_type, value)
        return result.model_copy(update={"domain_info": await _await_domain()})
    # Bounded as a whole: a slow redirect chain must never hold the check hostage — judge the link as given instead.
    expansion_complete, expansion_reason, expansion_failure = True, None, None
    try:
        chain, expansion_complete, expansion_reason, expansion_failure = await asyncio.wait_for(expand_redirects_detailed(value), timeout=12)
    except asyncio.TimeoutError:
        chain = [value]
        expansion_complete, expansion_reason, expansion_failure = False, "the redirect check did not finish in time", "timeout"
    final = chain[-1]
    # Judge the final destination; any confirmed-malicious hop along the way also counts.
    result = await run_intel_check("url", final)
    threat_types, sources, verdict = list(result.threat_types), list(result.sources), result.verdict
    for hop in chain[:-1]:
        try:
            r = await run_intel_check("url", hop)
        except HTTPException:
            continue
        if r.verdict == "malicious":
            verdict = "malicious"; threat_types = sorted(set(threat_types + r.threat_types))
    hosts = []
    for u in chain:
        try:
            hosts.append(sanitize_url(u)[1])
        except HTTPException:
            hosts.append(urlparse(u).hostname or u)
    coverage = result.coverage
    if not expansion_complete:
        # The destination Apollo judged is not known to be the real one. Say so, and never report
        # this as full coverage.
        sources = [*sources, IntelSource(name="redirect_expansion", status="unavailable", check="final_destination",
                                         failure=expansion_failure or "redirect_failure",
                                         detail=f"Apollo couldn't confirm where this link ends up: {expansion_reason}.")]
        coverage = "partial" if coverage == "full" else coverage
    return IntelCheckResponse(verdict=verdict, threat_types=threat_types, sources=sources, indicator_digest=result.indicator_digest, checked_at=result.checked_at, cached=result.cached,
                              coverage=coverage, redirect_chain=hosts if len(chain) > 1 else [], final_url=final if len(chain) > 1 else None,
                              domain_info=await _await_domain())
