"""Module 3 — SSL / TLS Certificate Investigation.

Retrieves the TLS certificate presented by a hostname, extracts the subject CN, issuer
organisation, Subject Alternative Names (SANs), and expiry date, then returns a structured
result used by tc_flyby's official.py link checker.

Design:
  * Runs the blocking ssl/socket call in a thread executor so the FastAPI event loop is not
    blocked.
  * Results are cached in MongoDB (collection: ssl_cache) with a 7-day TTL so the same
    host is never checked more than once per week.
  * Failure modes are caught and returned as {"valid": False, "error": ...} — the caller
    degrades gracefully rather than crashing.

Pure network; no I/O besides the TLS handshake and MongoDB cache.
"""
from __future__ import annotations

import asyncio
import re
import socket
import ssl
from datetime import datetime, timezone
from typing import Any, Optional

from core.db import db, now_utc

_CACHE_TTL_DAYS = 7
_TIMEOUT = 6.0   # seconds for the TCP + TLS handshake


def _sync_check(hostname: str) -> dict[str, Any]:
    """Blocking TLS check — run via run_in_executor() from the async wrapper."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, 443), timeout=_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                subject = dict(x[0] for x in cert.get("subject", []))
                issuer = dict(x[0] for x in cert.get("issuer", []))
                sans = [v for t, v in cert.get("subjectAltName", []) if t == "DNS"]
                not_after_raw = cert.get("notAfter", "")
                # Parse "May 20 00:00:00 2026 GMT" → ISO string
                try:
                    exp = datetime.strptime(not_after_raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    not_after_iso = exp.isoformat()
                    days_remaining = (exp - now_utc()).days
                except Exception:
                    not_after_iso = not_after_raw
                    days_remaining = None
                return {
                    "valid": True,
                    "cn": subject.get("commonName"),
                    "org": subject.get("organizationName"),
                    "issuer_cn": issuer.get("commonName"),
                    "issuer_org": issuer.get("organizationName"),
                    "not_after": not_after_iso,
                    "days_remaining": days_remaining,
                    "sans": sans[:20],      # cap to avoid huge payloads
                    "covers_hostname": any(
                        _san_matches(san, hostname) for san in sans
                    ) or (subject.get("commonName") == hostname),
                    "error": None,
                }
    except ssl.CertificateError as exc:
        return {"valid": False, "error": f"Certificate error: {exc}"}
    except socket.timeout:
        return {"valid": False, "error": "Connection timed out"}
    except OSError as exc:
        return {"valid": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}"}


def _san_matches(san: str, hostname: str) -> bool:
    """True if `san` (which may be a wildcard like *.amazon.co.jp) covers `hostname`."""
    if san.startswith("*."):
        # Wildcard: *.amazon.co.jp matches sub.amazon.co.jp but NOT amazon.co.jp itself
        suffix = san[1:]   # ".amazon.co.jp"
        return hostname.endswith(suffix) and hostname.count(".") == san.count(".")
    return san.lower() == hostname.lower()


async def check_hostname(hostname: str) -> dict[str, Any]:
    """Return TLS certificate information for `hostname`, using the MongoDB cache.

    Returns a dict with at minimum {"valid": bool}. On cache hit the response also
    includes {"cached": True, "checked_at": <ISO>}. Never raises.
    """
    hostname = hostname.lower().strip()
    if not hostname or not re.match(r"^[a-z0-9.\-]+$", hostname):
        return {"valid": False, "error": "Invalid hostname"}

    # ── Cache read ──────────────────────────────────────────────────────────────────────
    try:
        cached = await db.ssl_cache.find_one({"hostname": hostname})
        if cached:
            age_days = (now_utc() - cached["checked_at"]).days
            if age_days < _CACHE_TTL_DAYS:
                result = {k: v for k, v in cached.items() if k not in ("_id", "hostname", "checked_at")}
                result["cached"] = True
                result["checked_at"] = cached["checked_at"].isoformat()
                return result
    except Exception:  # noqa: BLE001
        pass

    # ── Live check ───────────────────────────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _sync_check, hostname)

    # ── Cache write ──────────────────────────────────────────────────────────────────────
    try:
        await db.ssl_cache.replace_one(
            {"hostname": hostname},
            {"hostname": hostname, "checked_at": now_utc(), **result},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        pass

    return result
