"""Regression checks for the shared VirusTotal hash/URL request budget."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import virustotal, virustotal_url, virustotal_quota


@pytest.mark.asyncio
async def test_hash_and_url_use_same_limiter():
    """Both client modules must import the exact same quota reservation function."""
    assert virustotal._rate_limit is virustotal_quota.rate_limit
    assert virustotal_url._rate_limit is virustotal_quota.rate_limit


@pytest.mark.asyncio
async def test_shared_limit_waits_on_fifth_request():
    """A fifth request, regardless of caller, cannot bypass the rolling minute budget."""
    with patch.object(virustotal_quota, "_request_times", []), \
         patch.object(virustotal_quota.time, "monotonic", return_value=100.0), \
         patch.object(virustotal_quota.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        for _ in range(4):
            await virustotal_quota.rate_limit()
        assert len(virustotal_quota._request_times) == 4
        await virustotal_quota.rate_limit()
        sleep.assert_awaited_once_with(60.0)


@pytest.mark.asyncio
async def test_shared_limit_removes_expired_reservations():
    with patch.object(virustotal_quota, "_request_times", [10.0] * 4), \
         patch.object(virustotal_quota.time, "monotonic", return_value=71.0), \
         patch.object(virustotal_quota.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        await virustotal_quota.rate_limit()
        sleep.assert_not_awaited()
        assert len(virustotal_quota._request_times) == 1
