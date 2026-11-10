"""VirusTotal hash-based malware scanning for email attachments.

Uses the VirusTotal v3 API in hash-only mode: only the SHA-256 hash of a file is sent —
the file content never leaves Apollo's backend. This catches all previously-known malware
while preserving attachment privacy.

The 4/minute limit below is an in-process safeguard, not a verified\naccount-wide quota or a commercial-use licence. Production usage requires\nindependent account-wide enforcement and licence verification.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from dotenv import load_dotenv
from core.config import logger
from core.resilience import resilient_get

load_dotenv()

VT_API_KEY = os.getenv("VIRUSTOTAL_API_KEY", "")
VT_API_URL = "https://www.virustotal.com/api/v3"

# Rate limiter for free tier (4 requests/minute)
_last_request_times: list[float] = []
_rate_lock = asyncio.Lock()
MAX_REQUESTS_PER_MINUTE = 4
# A 429 can mean minute, daily, or account quota exhaustion. Respect Retry-After
# when provided and fail closed for the cooldown; never report a reputation verdict.
_vt_cooldown_until = 0.0

def quota_wait_seconds() -> float:
    return max(0.0, _vt_cooldown_until - time.monotonic())

def note_quota_failure(retry_after: str | None) -> None:
    global _vt_cooldown_until
    try:
        seconds = float(retry_after or "")
    except ValueError:
        seconds = 300.0
    _vt_cooldown_until = max(_vt_cooldown_until, time.monotonic() + max(60.0, min(seconds, 86400.0)))


@dataclass
class ScanResult:
    """Result of a VirusTotal hash lookup."""
    filename: str
    sha256: str
    status: str  # "clean" | "malicious" | "suspicious" | "unknown" | "error" | "not_configured"
    detection_count: int = 0
    total_engines: int = 0
    malware_names: list[str] = field(default_factory=list)
    detail: str = ""


async def _rate_limit() -> None:
    """Enforce free-tier rate limit: max 4 requests per 60 seconds."""
    async with _rate_lock:
        now = time.monotonic()
        # Remove requests older than 60 seconds
        _last_request_times[:] = [t for t in _last_request_times if now - t < 60]
        if len(_last_request_times) >= MAX_REQUESTS_PER_MINUTE:
            wait = 60 - (now - _last_request_times[0])
            if wait > 0:
                logger.info("VirusTotal rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)
        _last_request_times.append(time.monotonic())


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(data).hexdigest()


async def lookup_hash(sha256: str, filename: str = "") -> ScanResult:
    """Look up a file hash in VirusTotal's database.

    Returns scan results without uploading any file content.
    If the hash is unknown to VirusTotal, returns status="unknown".
    """
    if not VT_API_KEY:
        return ScanResult(
            filename=filename, sha256=sha256, status="not_configured",
            detail="Malware scanning is not configured. Set VIRUSTOTAL_API_KEY to enable.",
        )

    if quota_wait_seconds() > 0:
        return ScanResult(filename=filename, sha256=sha256, status="error",
                          detail="VirusTotal quota temporarily unavailable (previous HTTP 429); this attachment was not checked.")
    await _rate_limit()

    try:
        resp = await resilient_get(
            f"{VT_API_URL}/files/{sha256}",
            timeout=15.0,
            headers={"x-apikey": VT_API_KEY, "Accept": "application/json"},
            label="virustotal",
        )

        if resp.status_code == 404:
            return ScanResult(
                filename=filename, sha256=sha256, status="unknown",
                detail=f"File hash not in VirusTotal database. This does not confirm the file is safe — "
                       f"it means this specific file has not been previously analyzed by VirusTotal.",
            )

        if resp.status_code == 429:
            note_quota_failure(resp.headers.get("Retry-After"))
            return ScanResult(
                filename=filename, sha256=sha256, status="error",
                detail="VirusTotal returned HTTP 429 (rate or daily quota exhausted). The attachment was not checked.",
            )

        if resp.status_code != 200:
            return ScanResult(
                filename=filename, sha256=sha256, status="error",
                detail=f"VirusTotal returned status {resp.status_code}. The attachment could not be checked.",
            )

        data = resp.json().get("data", {}).get("attributes", {})
        stats = data.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        undetected = stats.get("undetected", 0)
        total = malicious + suspicious + undetected + stats.get("harmless", 0)

        # Collect malware names from engines that detected it
        malware_names = []
        results = data.get("last_analysis_results", {})
        for engine_name, result in results.items():
            if result.get("category") == "malicious" and result.get("result"):
                malware_names.append(f"{engine_name}: {result['result']}")
        malware_names = sorted(malware_names)[:10]  # Limit to top 10

        if malicious >= 3:  # Threshold: 3+ engines flagging = malicious
            return ScanResult(
                filename=filename, sha256=sha256, status="malicious",
                detection_count=malicious, total_engines=total,
                malware_names=malware_names,
                detail=f"Malware detected: {malicious}/{total} antivirus engines flagged this file. "
                       f"Do not open this attachment.",
            )
        elif malicious > 0 or suspicious > 0:
            return ScanResult(
                filename=filename, sha256=sha256, status="suspicious",
                detection_count=malicious + suspicious, total_engines=total,
                malware_names=malware_names,
                detail=f"Suspicious file: {malicious + suspicious}/{total} engines flagged this file. "
                       f"Exercise caution — some engines may produce false positives.",
            )
        else:
            return ScanResult(
                filename=filename, sha256=sha256, status="clean",
                detection_count=0, total_engines=total,
                detail=f"No malware detected by {total} antivirus engines. "
                       f"This checks against known malware signatures — it does not guarantee the file is safe.",
            )

    except httpx.TimeoutException:
        return ScanResult(
            filename=filename, sha256=sha256, status="error",
            detail="VirusTotal request timed out. The attachment could not be checked.",
        )
    except Exception as exc:
        logger.warning("VirusTotal lookup failed: %s", exc)
        return ScanResult(
            filename=filename, sha256=sha256, status="error",
            detail=f"VirusTotal lookup failed ({type(exc).__name__}). The attachment could not be checked.",
        )


async def scan_attachments(attachment_data: list[tuple[str, bytes]]) -> list[ScanResult]:
    """Scan multiple attachments by hash lookup.

    Args:
        attachment_data: list of (filename, file_bytes) tuples

    Returns:
        List of ScanResult for each attachment
    """
    results = []
    for filename, data in attachment_data:
        sha256 = compute_sha256(data)
        result = await lookup_hash(sha256, filename)
        results.append(result)
    return results
