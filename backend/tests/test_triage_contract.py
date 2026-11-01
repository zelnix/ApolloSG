"""Triage & Magnum DI cost contract — acceptance tests.

Proves the 2-tier model: deterministic Triage (0 Gemini calls) and exactly one
automatic Magnum DI call per correlated POSSIBLE THREAT case.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.triage import Outcome, evaluate, record_triage_history  # noqa: E402
from services.triage.catalogue import CATALOGUE, RULES  # noqa: E402
from services.triage.contract import RuleResult, legacy_outcome  # noqa: E402
from services.triage.engine import BROWSER_OBSERVATION_NA, run_with_retries  # noqa: E402


# ── Catalogue integrity ─────────────────────────────────────────────────────

def test_catalogue_ids_unique_and_categorised():
    ids = [row["id"] for row in CATALOGUE["rules"]]
    assert len(ids) == len(set(ids))
    assert {row["category"] for row in CATALOGUE["rules"]} == {
        "link", "message", "call", "email", "account", "app", "file", "device", "network", "correlation"}
    for row in CATALOGUE["rules"]:
        assert row["title"] and row["id"] in RULES
        if row.get("gapCode"):
            assert row["gapCode"] in {g["code"] for g in CATALOGUE["coverageGapCodes"]}


def test_legacy_verdicts_map_without_rewriting_history():
    assert legacy_outcome("SAFE") is Outcome.NO_THREAT
    assert legacy_outcome("SUSPICIOUS") is Outcome.POSSIBLE_THREAT
    assert legacy_outcome("UNCERTAIN") is Outcome.LIMITED
    assert legacy_outcome("") is Outcome.LIMITED  # unknown never becomes "no threat"


# ── 1-3. Triage itself never spends tokens ──────────────────────────────────

@pytest.fixture
def no_gemini(monkeypatch):
    """Any attempt to reach the model provider during Triage fails the test."""
    calls: list[str] = []

    async def _boom(*args, **kwargs):
        calls.append("generate")
        raise AssertionError("Triage must never call Gemini")

    from services.higgins import provider
    monkeypatch.setattr(provider, "generate", _boom)
    return calls


def test_no_threat_makes_zero_gemini_calls(no_gemini):
    investigation = evaluate({
        "source_type": "link", "local_level": "clean", "local_signals": [], "indicator_match": False,
        "credentials_in_url": False, "credential_interaction": False,
        "reputation": {"status": "ok", "verdict": "clean"},
        "domain_age": {"status": "ok", "newly_registered": False},
    })
    assert investigation.outcome is Outcome.NO_THREAT
    assert investigation.gemini_calls == 0 and no_gemini == []
    assert investigation.wire()["rulesChecked"], "No Threat must still record the rules it checked"


def test_limited_makes_zero_gemini_calls_and_never_escalates(no_gemini):
    investigation = evaluate({
        "source_type": "link", "local_level": "uncertain", "local_signals": ["risky_tld"],
        "indicator_match": False, "credentials_in_url": False,
        "reputation": {"status": "unavailable"},
    })
    assert investigation.outcome is Outcome.LIMITED
    assert investigation.gemini_calls == 0 and no_gemini == []
    assert [g.code for g in investigation.coverage_gaps] == ["INTELLIGENCE_PROVIDER_UNAVAILABLE"]
    assert investigation.recoverable is True  # a provider timeout is worth re-checking


def test_possible_threat_is_deterministic_and_spends_nothing_in_triage(no_gemini):
    investigation = evaluate({"source_type": "message", "signals": {"code_request": True}})
    assert investigation.outcome is Outcome.POSSIBLE_THREAT
    assert investigation.should_escalate is True
    assert investigation.gemini_calls == 0 and no_gemini == []
    assert [r.rule_id for r in investigation.met_rules] == ["MSG-01"]


# ── 4-5. One correlated case = one Magnum DI call ───────────────────────────

def test_multiple_met_rules_across_gates_remain_one_case_and_one_escalation():
    investigation = evaluate({
        "source_type": "message",
        "signals": {"code_request": True, "gift_cards": True, "urgency": True, "threat": True,
                    "payment_request": True, "claimed_brand": "CommBank", "brand_kind": "bank"},
        "brand_mismatch": True,
        "link_outcome": Outcome.POSSIBLE_THREAT.value,
        "correlation": {"related": [{"category": "call", "event_id": "e1"}], "supporting_evidence": True,
                        "mechanics": ["remote_access"], "case_key": "scent-1"},
    })
    assert investigation.outcome is Outcome.POSSIBLE_THREAT
    assert len(investigation.met_rules) > 1, "several rules should be met"
    # One investigation record → the caller starts exactly one Magnum DI case.
    assert investigation.should_escalate is True
    assert investigation.correlation.get("case_key") == "scent-1"
    assert investigation.gemini_calls == 0


# ── 8. Deterministic retries, no AI involvement ─────────────────────────────

@pytest.mark.asyncio
async def test_transient_check_retries_bounded_and_free(no_gemini):
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("provider timeout")
        return {"status": "ok"}

    value, record = await run_with_retries("safe_browsing", flaky)
    assert value == {"status": "ok"}
    assert record.attempts == 3 and record.outcome == "recovered"
    assert no_gemini == []


@pytest.mark.asyncio
async def test_permanent_capability_limitation_is_never_retried():
    async def never_called():
        raise AssertionError("permanent limitations must not be retried")

    value, record = await run_with_retries("private_dns_state", never_called, permanent=True)
    assert value is None and record.attempts == 0 and record.outcome == "not_retried_permanent"


@pytest.mark.asyncio
async def test_exhausted_retries_do_not_escalate(no_gemini):
    async def always_fails():
        raise ConnectionError("network down")

    value, record = await run_with_retries("reputation", always_fails)
    assert value is None and record.attempts == 3 and record.outcome == "failed"
    investigation = evaluate({"source_type": "link", "local_level": "uncertain", "indicator_match": False,
                              "credentials_in_url": False, "reputation": {"status": "unavailable"}},
                             retries=[record])
    assert investigation.outcome is Outcome.LIMITED and investigation.should_escalate is False
    assert investigation.wire()["retries"][0]["attempts"] == 3


# ── 9-11. Coverage-gap semantics ────────────────────────────────────────────

def test_coverage_gap_cannot_silently_become_no_threat():
    investigation = evaluate({"source_type": "file", "filename": "statement.zip",
                              "archive": {"encrypted": True, "entries": []}})
    assert investigation.outcome is Outcome.LIMITED
    assert "ENCRYPTED_CONTENT" in [g.code for g in investigation.coverage_gaps]


def test_missing_headers_are_an_incomplete_check_never_a_threat_or_a_gap():
    from services.triage_engine import _rule_evidence
    investigation = evaluate(_rule_evidence({"source_type": "email", "sender": "", "subject": "Hello", "body": "See you soon.",
                                             "auth_results": {}}, [], {}))
    assert investigation.outcome is Outcome.NO_THREAT
    assert investigation.met_rules == []
    assert not investigation.coverage_gaps
    assert [c["check"] for c in investigation.incomplete_checks] == ["sender_authentication"]


def test_positive_evidence_is_not_downgraded_by_an_unavailable_check():
    investigation = evaluate({
        "source_type": "email", "claimed_brand": "CommBank", "sender_domain": "secure-cba-alerts.com",
        "sender_domain_mismatch": True, "consequential_action": True, "credential_request": True,
        "findings": ["Links point to different domains than the sender"],
        "auth_results": {}, "reply_to_mismatch": None,  # headers unavailable
    })
    assert investigation.outcome is Outcome.POSSIBLE_THREAT
    assert investigation.met_rules, "existing threat evidence must still stand"


def test_concerning_but_unmatched_evidence_returns_limited_not_possible_threat():
    investigation = evaluate({
        "source_type": "link", "local_level": "uncertain", "local_signals": ["risky_tld", "long_host"],
        "indicator_match": False, "credentials_in_url": False,
        "reputation": {"status": "ok", "verdict": "clean"},
        "domain_age": {"status": "ok", "newly_registered": False},
        "unresolved_concern": True,
        "unresolved_concern_detail": "Several structural indicators, no deception evidence.",
    })
    assert investigation.outcome is Outcome.LIMITED
    assert [g.code for g in investigation.coverage_gaps] == ["INSUFFICIENT_EVIDENCE"]
    assert investigation.recoverable is False  # nothing a re-check could fix


def test_browser_observation_rules_are_not_applicable_without_the_platform_signal():
    investigation = evaluate({
        "source_type": "link", "credential_interaction": True, "local_level": "uncertain",
        "indicator_match": False, "credentials_in_url": False,
        "reputation": {"status": "ok", "verdict": "clean"},
        "visibility": {"browser": False, "websocket": False},
    })
    bitm = [r for r in investigation.rules if r.rule_id.startswith("BITM-") and r.rule_id != "BITM-05"]
    assert len(bitm) == 4 and all(r.result is RuleResult.NOT_APPLICABLE for r in bitm)
    assert all(r.evidence == [BROWSER_OBSERVATION_NA] for r in bitm), "the reason stays visible in the DI"
    assert "BROWSER_VISIBILITY_UNAVAILABLE" not in [g.code for g in investigation.coverage_gaps]
    assert investigation.outcome is not Outcome.LIMITED


def test_never_alone_indicators_do_not_create_a_threat():
    for evidence in (
        {"source_type": "link", "local_level": "uncertain", "local_signals": ["risky_tld", "shortener", "punycode"],
         "indicator_match": False, "credentials_in_url": False,
         "reputation": {"status": "ok", "verdict": "clean"}, "domain_age": {"status": "ok", "newly_registered": True}},
        {"source_type": "message", "signals": {"unknown_sender": True, "instant_payment": True}},
        {"source_type": "call", "asks": ["nothing"], "claim": "unknown",
         "phone_reputation": {"status": "ok", "verdict": "clean"}},
    ):
        investigation = evaluate(evidence)
        assert investigation.outcome is not Outcome.POSSIBLE_THREAT, evidence


# ── 12. Every outcome is retained in Patrol History ─────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("evidence,expected", [
    ({"source_type": "link", "local_level": "clean", "indicator_match": False, "credentials_in_url": False,
      "reputation": {"status": "ok", "verdict": "clean"}}, Outcome.NO_THREAT),
    ({"source_type": "link", "local_level": "uncertain", "indicator_match": False, "credentials_in_url": False,
      "reputation": {"status": "unavailable"}}, Outcome.LIMITED),
    ({"source_type": "message", "signals": {"gift_cards": True}}, Outcome.POSSIBLE_THREAT),
])
async def test_every_triage_outcome_is_saved_to_patrol_history(evidence, expected):
    from core.db import db
    device_id = f"test-triage-{uuid.uuid4().hex[:10]}"
    investigation = evaluate(evidence)
    assert investigation.outcome is expected
    event_id = await record_triage_history(device_id, investigation, category="link", subject="example.com",
                                           evidence_source="device_submission")
    try:
        event = await db.patrol_events.find_one({"device_id": device_id, "event_id": event_id}, {"_id": 0})
        assert event is not None
        # The separated evidence model: the source is what supplied the evidence, never the server that checked it.
        assert event["evidence_provenance"] == "device_submission"
        assert event["processing_source"] == "apollosg_servers"
        assert event["evidence_representation"] == "privacy_protected_copy"
        assert event["evidence_completeness"] in ("complete", "partial")
        record = event["triage_investigation"]
        assert record["outcome"] == expected.value
        assert record["geminiCalls"] == 0
        for key in ("rulesApplicable", "rulesChecked", "rulesMet", "coverageGaps", "retries", "correlation", "reason"):
            assert key in record
        stored = await db.triage_investigations.find_one({"device_id": device_id}, {"_id": 0})
        assert stored and stored["outcome"] == expected.value
    finally:
        await db.patrol_events.delete_many({"device_id": device_id})
        await db.triage_investigations.delete_many({"device_id": device_id})
