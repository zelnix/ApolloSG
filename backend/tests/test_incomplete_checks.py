"""Incomplete checks, granular lookup failures, number caching and callback-scam detection.

A check Apollo needed but couldn't finish is recorded as incomplete — with how it failed — and a No Threat result
with one is "No threat found by available checks", never the unqualified "No threat identified" and never Limited
unless the missing answer could change the result.

Run: cd /app/backend && python -m pytest tests/test_incomplete_checks.py -q
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from core.db import db, now_utc
from services import phonerisk as pr
from services.intel import _expansion_failure
from services.outbound import OutboundBlocked
from services.triage import evaluate, telemetry
from services.triage.completeness import AVAILABLE_CHECKS, from_sources, incomplete_check, incomplete_plain
from services.triage_engine import _link_evidence_from_providers, _rule_evidence, alleged_charge, callback_request

NO_BROWSER = {"browser": False, "websocket": False}


# ── 6. Incomplete-check policy ────────────────────────────────────────────────

def test_no_threat_with_an_incomplete_check_is_no_threat_found_by_available_checks():
    record = evaluate({"source_type": "link", "local_level": "clean", "visibility": NO_BROWSER,
                       "reputation": {"status": "ok", "verdict": "clean"},
                       "incomplete_checks": [incomplete_check("reputation", "quota_exhausted", source="google_safe_browsing")]})
    wire = record.wire()
    assert wire["outcome"] == "NO_THREAT_IDENTIFIED"
    assert wire["reason"].startswith(AVAILABLE_CHECKS)
    assert "Website threat checking could not be checked (its lookup allowance is used up for now)." in wire["reason"]
    assert wire["coverage"] == "incomplete" and wire["incompleteChecks"][0]["failure"] == "quota_exhausted"
    # The wording follows the kind of check, never the provider.
    assert "Google" not in wire["reason"] and "Safe Browsing" not in wire["reason"]


def test_every_check_completed_stays_the_unqualified_no_threat():
    wire = evaluate({"source_type": "link", "local_level": "clean", "visibility": NO_BROWSER,
                     "reputation": {"status": "ok", "verdict": "clean"}}).wire()
    assert wire["outcome"] == "NO_THREAT_IDENTIFIED" and wire["coverage"] == "complete"
    assert wire["reason"] == "No deterministic threat rule was met and every applicable check completed."


def test_safe_browsing_down_with_blocklist_answering_is_available_checks_not_limited():
    sources = [{"name": "apollo_blocklist", "status": "clear", "detail": ""},
               {"name": "google_safe_browsing", "status": "unavailable", "detail": "x", "failure": "timeout", "check": "reputation"}]
    providers = {"safe_browsing": {"urls": {"https://a.example/": {"status": "ok", "verdict": "clean", "coverage": "partial", "sources": sources}}}}
    link = _link_evidence_from_providers({}, providers)
    assert link["reputation"] == {"status": "ok", "verdict": "clean"}
    assert [(c["check"], c["status"], c["failure"]) for c in link["incomplete_checks"]] == [("reputation", "unavailable", "timeout")]
    wire = evaluate({"source_type": "link", "local_level": "clean", "visibility": NO_BROWSER, **link}).wire()
    assert wire["outcome"] == "NO_THREAT_IDENTIFIED" and wire["reason"].startswith(AVAILABLE_CHECKS)


def test_no_source_answering_is_still_limited_with_the_failure_kind():
    sources = [{"name": "google_safe_browsing", "status": "unavailable", "failure": "auth_failure"}]
    providers = {"safe_browsing": {"urls": {"https://a.example/": {"status": "ok", "verdict": "unknown", "coverage": "none", "sources": sources}}}}
    link = _link_evidence_from_providers({}, providers)
    assert link["reputation"]["status"] == "unavailable" and link["reputation"]["failure"] == "auth_failure"
    wire = evaluate({"source_type": "link", "local_level": "clean", "visibility": NO_BROWSER, **link}).wire()
    assert wire["outcome"] == "LIMITED_UNABLE_TO_DETERMINE"
    gap = next(g for g in wire["coverageGaps"] if g["code"] == "INTELLIGENCE_PROVIDER_UNAVAILABLE")
    assert gap["failure"] == "auth_failure"
    assert telemetry.causes_for(wire) == ["reputation_auth_failure"]


def test_unverified_final_destination_is_an_incomplete_check_not_a_gap():
    providers = {
        "redirects": {"urls": {"https://short.example/x": {"status": "incomplete", "hops": 1, "final_url": None,
                                                           "failure": "nonexistent_domain", "detail": "dns"}}},
        "safe_browsing": {"urls": {"https://short.example/x": {"status": "ok", "verdict": "clean", "coverage": "full", "sources": []}}},
    }
    link = _link_evidence_from_providers({}, providers)
    assert [(c["check"], c["status"], c["failure"]) for c in link["incomplete_checks"]] == [("final_destination", "unresolved", "nonexistent_domain")]
    record = evaluate({"source_type": "link", "local_level": "clean", "visibility": NO_BROWSER, **link})
    link02 = next(r for r in record.rules if r.rule_id == "LINK-02")
    assert link02.result.value == "not_met" and not record.coverage_gaps
    assert record.outcome.value == "NO_THREAT_IDENTIFIED"
    assert "Apollo couldn't verify where this link finally leads (the website's address doesn't exist)." in record.reason


def test_incomplete_plain_and_from_sources():
    assert incomplete_plain(incomplete_check("number_reputation", "timeout", status="stale")) == (
        "The phone number's reputation check didn't complete: the live lookup failed (it timed out), "
        "so Apollo used the result of its last check.")
    assert incomplete_plain(incomplete_check("reputation", None)) == "A reputation check didn't complete."
    found = from_sources([{"name": "b", "status": "clear"}, {"name": "redirect_expansion", "status": "unavailable",
                                                             "check": "final_destination", "failure": "redirect_limit"}])
    assert [(c["check"], c["status"], c["failure"]) for c in found] == [("final_destination", "unresolved", "redirect_limit")]


# ── 2. Ordinary message with a failed number lookup ───────────────────────────

def _message(text: str, ipqs: dict) -> dict:
    return _rule_evidence({"source_type": "text", "text_preview": text}, [], {"ipqs": {"phones": {"+61412345678": ipqs}}})


def test_ordinary_message_with_a_failed_number_lookup_is_not_limited():
    ev = _message("Hi, it's Sam from the gym. Call me back on 0412 345 678 when you're free.",
                  {"status": "unavailable", "failure": "quota_exhausted"})
    assert ev["signals"]["callback_request"] is True and ev["signals"]["alleged_charge"] is False
    wire = evaluate(ev).wire()
    assert wire["outcome"] == "NO_THREAT_IDENTIFIED", wire["coverageGaps"]
    assert wire["reason"].startswith(AVAILABLE_CHECKS)
    assert wire["incompleteChecks"][0]["check"] == "number_reputation"
    assert wire["incompleteChecks"][0]["failure"] == "quota_exhausted"


def test_stale_number_score_is_recorded_as_incomplete():
    ev = _message("Your table is booked for 7pm. Call 0412 345 678 to change it.",
                  {"status": "ok", "fraud_score": 10, "freshness": "stale", "failure": "timeout", "checked_at": "2026-06-01T00:00:00+00:00"})
    wire = evaluate(ev).wire()
    assert wire["outcome"] == "NO_THREAT_IDENTIFIED"
    assert wire["incompleteChecks"][0]["status"] == "stale"
    assert telemetry.incomplete_codes(wire) == ["number_reputation_stale"]


# ── 5. Callback-scam detection ────────────────────────────────────────────────

def test_unexpected_charge_with_urgency_and_a_callback_number_is_a_possible_threat():
    text = "Your account has been charged $899 for an Apple order. Call 1800 123 456 now to cancel."
    blob = text.lower()
    assert callback_request(blob) and alleged_charge(blob)
    ev = _message(text, {"status": "unavailable", "failure": "timeout"})
    wire = evaluate(ev).wire()
    assert wire["outcome"] == "POSSIBLE_THREAT_IDENTIFIED"
    assert "CB-01" in wire["rulesMet"]


def test_charge_claim_with_dispute_wording_and_13_number():
    assert alleged_charge("a payment of $450 was made. if this wasn't you call 13 22 21")
    assert callback_request("a payment of $450 was made. if this wasn't you call 13 22 21")


def test_a_phone_number_or_a_charge_on_its_own_is_not_a_callback_scam():
    assert not alleged_charge("your order of $45 has shipped. track it in the app.")
    assert not callback_request("my number is 0412 345 678")
    assert not callback_request("call me later")


# ── 3. Number-result caching and last-known-good ──────────────────────────────

def _cached_doc(phone: str, *, expired: bool) -> dict:
    ts = now_utc() - timedelta(days=2 if expired else 0, minutes=5)
    return {"phone_e164": phone, "fraud_score": 20, "valid": True, "active": True, "recent_abuse": False, "risky": False,
            "voip": False, "line_type": "Wireless", "carrier": "Telstra", "country": "AU", "checked_at": ts,
            "expires_at": ts + timedelta(hours=24)}


@pytest.fixture
def ipqs_key(monkeypatch):
    monkeypatch.setattr(pr, "IPQS_API_KEY", "test-key")


async def test_a_current_saved_score_is_used_before_a_lookup_credit_is_spent(ipqs_key):
    phone = f"+6141{uuid.uuid4().int % 10**7:07d}"
    await db.phone_risk_cache.insert_one(_cached_doc(phone, expired=False))
    try:
        with patch("services.phonerisk._query_ipqs", new_callable=AsyncMock) as query:
            result = await pr.check_phone_risk(phone, "AU", persist_cache=False)
        query.assert_not_called()
        assert result.freshness == "cached" and result.decision == "allow" and result.cached
    finally:
        await db.phone_risk_cache.delete_many({"phone_e164": phone})


async def test_a_failed_lookup_falls_back_to_the_last_known_score_marked_stale(ipqs_key):
    phone = f"+6141{uuid.uuid4().int % 10**7:07d}"
    await db.phone_risk_cache.insert_one(_cached_doc(phone, expired=True))
    try:
        with patch("services.phonerisk._query_ipqs", new_callable=AsyncMock,
                   side_effect=pr.PhoneLookupFailed("quota_exhausted", "x")):
            result = await pr.check_phone_risk(phone, "AU")
        assert result.freshness == "stale" and result.failure == "quota_exhausted"
        assert result.decision == "allow" and result.fraud_score == 20
    finally:
        await db.phone_risk_cache.delete_many({"phone_e164": phone})


async def test_no_earlier_score_is_unknown_with_the_failure_kind(ipqs_key):
    phone = f"+6141{uuid.uuid4().int % 10**7:07d}"
    with patch("services.phonerisk._query_ipqs", new_callable=AsyncMock, side_effect=pr.PhoneLookupFailed("auth_failure", "x")):
        result = await pr.check_phone_risk(phone, "AU")
    assert result.decision == "unknown" and result.source == "unavailable" and result.failure == "auth_failure"


# ── 4. Granular failure kinds ─────────────────────────────────────────────────

def test_ipqs_answer_failures_are_classified():
    assert pr._answer_failure("You have insufficient credits to make this request.") == "quota_exhausted"
    assert pr._answer_failure("Invalid or unauthorized key.") == "auth_failure"
    assert pr._answer_failure("Invalid phone number.") == "rejected"


def test_redirect_failures_are_classified():
    dns = OutboundBlocked("dns_failed")
    dns.__cause__ = OSError("nodename nor servname")
    assert _expansion_failure(dns) == "nonexistent_domain"
    slow = OutboundBlocked("dns_failed")
    slow.__cause__ = asyncio.TimeoutError()
    assert _expansion_failure(slow) == "timeout"
    assert _expansion_failure(OutboundBlocked("private_target")) == "unsafe_destination"
    assert _expansion_failure(OutboundBlocked("too_many_redirects")) == "redirect_limit"
    assert _expansion_failure(asyncio.TimeoutError()) == "timeout"


# ── 1. Telemetry counts incomplete checks for every outcome ───────────────────

async def test_telemetry_records_incomplete_checks_for_any_outcome(monkeypatch):
    collection = f"test_triage_telemetry_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(telemetry, "COLLECTION", collection)
    phone = {"device_id": "p1", "platform": "android", "adapter_mode": "native"}
    try:
        await telemetry.record(phone, origin="device", source_type="call", outcome="NO_THREAT_IDENTIFIED", causes=[], gap_codes=[],
                               incomplete=["number_reputation_stale"])
        await telemetry.record(phone, origin="device", source_type="call", outcome="NO_THREAT_IDENTIFIED", causes=[], gap_codes=[])
        await telemetry.record(phone, origin="device", source_type="link", outcome="NO_THREAT_IDENTIFIED", causes=[], gap_codes=[],
                               incomplete=["final_destination_nonexistent_domain", "not a code"])
        stats = await telemetry.limited_by_cause(phones_only=True)
        assert stats["outcomes"]["NO_THREAT_IDENTIFIED"] == 3
        assert sorted(stats["incomplete"]) == [("final_destination_nonexistent_domain", "NO_THREAT_IDENTIFIED", 1),
                                               ("number_reputation_stale", "NO_THREAT_IDENTIFIED", 1)]
    finally:
        await db[collection].drop()
