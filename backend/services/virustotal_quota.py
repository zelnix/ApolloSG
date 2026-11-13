"""Shared per-process VirusTotal request limiter for hash and URL lookups.

Both clients use the same API key and free-tier minute allowance. This limiter
coordinates requests within one Python process; deployments with multiple worker
processes still require a deployment-wide quota control.
"""
from __future__ import annotations

import asyncio
import time

MAX_REQUESTS_PER_MINUTE = 4
_request_times: list[float] = []
_lock = asyncio.Lock()


async def rate_limit() -> None:
    """Reserve one shared VirusTotal request slot within a rolling 60-second window."""
    async with _lock:
        now = time.monotonic()
        _request_times[:] = [t for t in _request_times if now - t < 60]
        if len(_request_times) >= MAX_REQUESTS_PER_MINUTE:
            wait = max(0.0, 60 - (now - _request_times[0]))
            if wait:
                await asyncio.sleep(wait)
            now = time.monotonic()
            _request_times[:] = [t for t in _request_times if now - t < 60]
        _request_times.append(time.monotonic())
