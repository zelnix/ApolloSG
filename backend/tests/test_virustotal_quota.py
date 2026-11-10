"""VirusTotal quota handling must never turn an unavailable lookup into 'clean'."""
import time
from unittest.mock import AsyncMock, patch

import pytest

from services import virustotal as vt
from services import virustotal_url as vtu


@pytest.mark.asyncio
async def test_429_cooldown_skips_url_and_hash_network_calls():
    previous = vt._vt_cooldown_until
    try:
        vt.note_quota_failure("120")
        assert vt.quota_wait_seconds() > 0
        with patch.object(vtu, "VT_API_KEY", "test"), patch.object(vt, "VT_API_KEY", "test"):
            with patch.object(vtu.httpx, "AsyncClient") as client:
                url = await vtu.check_url("https://example.org/")
                assert url.verdict == "error"
                assert "not checked" in url.detail.lower()
                client.assert_not_called()
            with patch.object(vt, "resilient_get", new_callable=AsyncMock) as get:
                result = await vt.lookup_hash("a" * 64)
                assert result.status == "error"
                assert "not checked" in result.detail.lower()
                get.assert_not_awaited()
    finally:
        vt._vt_cooldown_until = previous


def test_quota_cooldown_uses_retry_after_and_bounds_it():
    previous = vt._vt_cooldown_until
    try:
        vt._vt_cooldown_until = 0
        vt.note_quota_failure("90")
        assert 0 < vt.quota_wait_seconds() <= 91
        vt.note_quota_failure("bad")
        assert 200 < vt.quota_wait_seconds() <= 301
    finally:
        vt._vt_cooldown_until = previous
