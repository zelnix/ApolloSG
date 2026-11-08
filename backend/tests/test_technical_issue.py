"""Reputation-check timeout handling: a provider (IPQualityScore) that fails or times out after
retrying must not let TC Hawkeye proceed to a Findings score on that incomplete evidence — the
investigation surfaces instead as a technical failure ("investigation unable to progress"), logged to
the admin Alerts console, never read as a Finding (Apollo PRD v2.2 §2.5).

Run: cd /app/backend && python -m pytest tests/test_technical_issue.py -q
"""
import uuid

import pytest

from services.higgins import validation
from services.higgins.tc_flyby import decide, official, report, triage

pytestmark = pytest.mark.anyio


async def _plan_with_failed_ipqs(monkeypatch, *, host="fresh-deals.shop", sb_returns=None, age_days=4000) -> triage.Plan:
    """A link check where Safe Browsing found nothing (sb_returns) and IPQualityScore never answered."""
    async def url(_u):
        return sb_returns

    async def domain(_d):
        return {"registeredAt": "2015-01-01T00:00:00+00:00", "ageDays": age_days, "registrar": "Example", "newlyRegistered": False}

    monkeypatch.setattr(official, "lookup_url", url)
    monkeypatch.setattr(official, "lookup_domain", domain)
    from services import ssl_check
    async def no_ssl(_h):
        return {"valid": False, "error": "connection timeout"}
    monkeypatch.setattr(ssl_check, "check_hostname", no_ssl)

    plan_ = triage.plan("Is this real?", [f"Check this out: https://{host}/deal"])
    pre_gathered = {"ipqs": {"urls": {f"https://{host}/": {"status": "unavailable"}}}}
    await official.run(plan_, pre_gathered, f"https://{host}/deal")
    return plan_


# ── Check-level tracking ───────────────────────────────────────────────────
async def test_a_provider_timeout_is_tracked_on_the_check_not_silently_dropped(monkeypatch):
    plan_ = await _plan_with_failed_ipqs(monkeypatch)
    link = next(c for c in plan_.checks if c.kind == "link")
    assert link.provider_failures == ["ipqs"]


async def test_a_provider_timeout_with_nothing_else_resolving_it_is_a_technical_issue(monkeypatch):
    plan_ = await _plan_with_failed_ipqs(monkeypatch)
    failed = decide.technical_issue(plan_)
    assert len(failed) == 1 and failed[0].kind == "link"


async def test_a_provider_timeout_never_blocks_a_decisive_finding(monkeypatch):
    """IPQualityScore failing is irrelevant once Safe Browsing itself names the link as a scam."""
    plan_ = await _plan_with_failed_ipqs(monkeypatch, sb_returns={
        "verdict": "malicious", "threatTypes": ["SOCIAL_ENGINEERING"], "coverage": "full",
        "sources": [{"name": "google_safe_browsing", "status": "match"}], "checkedAt": None})
    assert decide.technical_issue(plan_) == [], "a decisive concern already resolved this check"


async def test_a_provider_timeout_never_blocks_a_clear_result_from_another_source(monkeypatch):
    """IPQualityScore failing is irrelevant once Safe Browsing itself clears the link."""
    plan_ = await _plan_with_failed_ipqs(monkeypatch, sb_returns={
        "verdict": "clean", "threatTypes": [], "coverage": "full",
        "sources": [{"name": "google_safe_browsing", "status": "clear"}], "checkedAt": None})
    assert decide.technical_issue(plan_) == [], "Safe Browsing clearing it is itself a usable result"


# ── decide.evaluate() mandates Magnum DI escalation instead of halting ──────
async def test_evaluate_escalates_to_magnum_di_instead_of_halting_when_a_check_timed_out(monkeypatch):
    """ApolloSG Developer Instructions §3 — "Mandatory Magnum DI Escalation": a genuine Criterion 1
    investigation failure (a provider that timed out after retrying, with nothing else resolving it)
    no longer lets TC Hawkeye resolve the case alone as an unexplained "technical issue" — it always
    hands the case to Magnum DI, with the full case evidence, not scope-limited to the failed check."""
    plan_ = await _plan_with_failed_ipqs(monkeypatch)
    decision, issues = decide.evaluate(plan_, ["Check this out: https://fresh-deals.shop/deal"], final=True)
    assert decision is None, "TC Hawkeye must not resolve this case on its own"
    assert len(issues) == 1 and issues[0].capability == "reasoning"
    assert "IPQualityScore" in issues[0].text and "timed out" in issues[0].text
    assert issues[0].evidence_ids == ["Check this out: https://fresh-deals.shop/deal"], "the whole case's evidence, not just the failed check"


async def test_evaluate_does_not_halt_mid_investigation(monkeypatch):
    """Only the final settlement attempt halts — Higgins Triage may still be gathering evidence."""
    plan_ = await _plan_with_failed_ipqs(monkeypatch)
    decision, issues = decide.evaluate(plan_, ["Check this out: https://fresh-deals.shop/deal"], final=False)
    assert decision is None and issues == []


# ── report.technical_issue_result() is a valid, committable response ───────
async def test_the_technical_issue_response_passes_validation(monkeypatch):
    plan_ = await _plan_with_failed_ipqs(monkeypatch)
    failed = decide.technical_issue(plan_)
    result = report._with_gaps(report.technical_issue_result(plan_, plan_.checks, failed), plan_)
    assert result["technicalFailure"] is True and result["outcome"] is None and "findingsRating" not in result

    response, errors = validation.validate(
        result, revision=1, evidence_ids=set(), source_ids=set(), capability_ids=set(),
        pending_question=None, provider_complete=True)
    assert errors == [], errors
    assert response is not None and response.technical_failure is True
    assert response.outcome is None and response.findings_rating is None
    assert "couldn't finish" in response.overview.lower()


# ── Admin alert is logged ───────────────────────────────────────────────────
async def test_a_technical_failure_logs_an_admin_alert():
    from services import admin_alerts
    owner, case_id = f"test-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:12]
    await admin_alerts.log_technical_failure(owner=owner, case_id=case_id, checks=["link"], subjects=["fresh-deals.shop"],
                                             reason="IPQualityScore did not answer after retrying.")
    alerts = await admin_alerts.list_alerts(limit=10)
    mine = next(a for a in alerts if a["case_id"] == case_id)
    assert mine["owner_id"] == owner and mine["checks"] == ["link"] and mine["acknowledged"] is False
    assert await admin_alerts.count_unacknowledged() >= 1
