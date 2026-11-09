"""Explicit opt-in live Web Risk smoke check. Never runs in ordinary CI.

Run only after verifying Cloud billing and quota safeguards:
  GOOGLE_WEB_RISK_LIVE_TEST=1 GOOGLE_WEB_RISK_ENABLED=true GOOGLE_WEB_RISK_API_KEY=... \
  python -m pytest tests/test_google_web_risk_live.py -q -m credentialed_integration

Uses exactly one Google-documented malware test URL; the second lookup must be cached.
No real-world suspicious URLs or private case evidence are sent.
"""
import os
import pytest
from services import google_web_risk as wr

@pytest.mark.asyncio
@pytest.mark.credentialed_integration
async def test_official_google_malware_sample_and_cache():
    if os.getenv("GOOGLE_WEB_RISK_LIVE_TEST") != "1":
        pytest.skip("Live provider test requires explicit opt-in")
    if not wr.enabled() or not os.getenv("GOOGLE_WEB_RISK_API_KEY"):
        pytest.fail("Live testing requires explicit enablement and API key")
    sample = "http://testsafebrowsing.appspot.com/s/malware.html"
    first = await wr.lookup(sample, testing=True)
    assert first["status"] in ("threat_match", "cached_result"), first.get("reason")
    assert "MALWARE" in first["threat_types"]
    second = await wr.lookup(sample, testing=True)
    assert second["status"] == "cached_result", second.get("reason")
    assert "MALWARE" in second["threat_types"]
