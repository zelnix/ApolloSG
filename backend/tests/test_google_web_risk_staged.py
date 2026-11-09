"""Offline contract tests for staged Web Risk quota and provider parsing. No Google requests."""
from datetime import datetime, timezone
from unittest.mock import patch

from services import google_web_risk as wr


def test_month_boundary_utc():
    assert wr.period(datetime(2026, 11, 1, tzinfo=timezone.utc)) == "2026-11"
    assert wr.period(datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)) == "2026-10"


def test_limits():
    assert wr.OPERATIONAL_STOP == 95_000
    assert wr.HARD_CEILING == 100_000
    assert wr.OPERATIONAL_STOP < wr.HARD_CEILING


def test_provider_disabled_by_default():
    with patch.dict("os.environ", {"GOOGLE_WEB_RISK_ENABLED": "false"}):
        assert not wr.enabled()


def test_no_secret_embedded_in_module():
    import inspect
    source = inspect.getsource(wr)
    assert "GOOGLE_WEB_RISK_API_KEY" in source
    assert "SAFE_BROWSING_API_KEY" not in source


def test_reservation_contract_uses_atomic_increment():
    import inspect
    source = inspect.getsource(wr.reserve)
    assert "find_one_and_update" in source
    assert '"$lt"' in source
    assert '"$inc"' in source
    assert "return None" in source


def test_provider_never_enabled_by_default():
    with patch.dict("os.environ", {}, clear=True):
        assert not wr.enabled()


def test_no_retry_loop_in_external_lookup():
    import inspect
    source = inspect.getsource(wr._lookup_uncached)
    assert "for attempt" not in source
    assert "client.get(" in source


def test_cached_result_does_not_claim_safe():
    import inspect
    source = inspect.getsource(wr.lookup)
    assert '"cached_result"' in source
    assert '"underlying_status"' in source
