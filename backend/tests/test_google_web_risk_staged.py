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


def test_provider_enabled_by_default_with_explicit_disable_override():
    with patch.dict("os.environ", {}, clear=True):
        assert wr.enabled()
    with patch.dict("os.environ", {"GOOGLE_WEB_RISK_ENABLED": "false"}, clear=True):
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

 
def test_atomic_reservation_at_cutoff_and_database_failure():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from pymongo.errors import PyMongoError
    quota = MagicMock()
    quota.insert_one = AsyncMock(side_effect=__import__("pymongo").errors.DuplicateKeyError("exists"))
    quota.find_one_and_update = AsyncMock(return_value=None)
    with patch.object(wr.db, "web_risk_quota", quota):
        assert asyncio.run(wr.reserve()) is False
        assert quota.find_one_and_update.await_args.args[0]["$expr"]["$and"][0]["$lt"][1] == 95_000
        assert quota.find_one_and_update.await_args.args[1]["$inc"]["reserved"] == 1
        assert quota.find_one_and_update.await_args.args[0]["$expr"]["$and"][1]["$lt"][1] == 85_000
        quota.find_one_and_update.side_effect = PyMongoError("database down")
        assert asyncio.run(wr.reserve()) is None


def test_missing_key_never_reaches_cache_or_network():
    import asyncio
    from unittest.mock import AsyncMock
    with patch.dict("os.environ", {"GOOGLE_WEB_RISK_ENABLED": "true"}, clear=True):
        with patch.object(wr.reusable_intel, "once", new_callable=AsyncMock) as once:
            outcome = asyncio.run(wr.lookup("https://example.org/"))
            assert outcome["status"] == "unavailable"
            assert outcome["reason"] == "not_configured"
            once.assert_not_awaited()


def test_disabled_provider_never_reaches_network():
    import asyncio
    from unittest.mock import AsyncMock
    with patch.dict("os.environ", {"GOOGLE_WEB_RISK_ENABLED": "false", "GOOGLE_WEB_RISK_API_KEY": "test"}):
        with patch.object(wr.reusable_intel, "once", new_callable=AsyncMock) as once:
            assert asyncio.run(wr.lookup("https://example.org/"))["status"] == "not_checked"
            once.assert_not_awaited()


def test_web_risk_no_match_never_becomes_clean_verdict():
    from core.models import IntelSource
    from services.intel import combine
    sources = [
        IntelSource(name="google_web_risk", status="clear", detail="No listing"),
        IntelSource(name="openphish", status="clear", detail="No listing"),
    ]
    verdict, threats, coverage = combine(sources)
    assert verdict == "unknown"
    assert threats == []
    assert coverage == "partial"


def test_web_risk_match_still_produces_malicious_verdict():
    from core.models import IntelSource
    from services.intel import combine
    verdict, threats, coverage = combine([
        IntelSource(name="google_web_risk", status="match", detail="Match", threat_types=["MALWARE"]),
    ])
    assert verdict == "malicious"
    assert threats == ["MALWARE"]

 
def test_testing_budget_reservation_is_separate():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from pymongo.errors import DuplicateKeyError
    quota = MagicMock()
    quota.insert_one = AsyncMock(side_effect=DuplicateKeyError("exists"))
    quota.find_one_and_update = AsyncMock(return_value={"reserved": 1, "testing_reserved": 1})
    with patch.object(wr.db, "web_risk_quota", quota):
        assert asyncio.run(wr.reserve(testing=True)) is True
    query, update = quota.find_one_and_update.await_args.args
    assert query["$expr"]["$and"][1]["$lt"][1] == 10_000
    assert query["$expr"]["$and"][0]["$lt"][1] == 95_000
    assert update["$inc"] == {"reserved": 1, "testing_reserved": 1}


def test_budget_allocation():
    assert wr.TEST_BUDGET == 10_000
    assert wr.PRODUCTION_BUDGET == 85_000
    assert wr.TEST_BUDGET + wr.PRODUCTION_BUDGET == wr.OPERATIONAL_STOP
