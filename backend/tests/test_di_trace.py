"""The DI tab's decision path and Magnum DI record: recorded data only, Magnum DI named, never the provider or model.

Run: cd /app/backend && python -m pytest tests/test_di_trace.py -q
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from services.higgins import di_record
from services.record_classification import generate_higgins_briefing
from services.triage.catalogue import LIMITED_CAUTION, plain_codes
from services.triage.contract import Outcome
from services.triage.engine import evaluate

AT = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)


class _One:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, *_args, **_kwargs):
        return self.doc


def _routing(resolved: bool) -> dict:
    flyby = {"ranAt": AT, "answeredBy": "tc_flyby_official" if resolved else "magnum_di", "resolved": resolved,
             "outcome": "concerning" if resolved else None, "basis": "impersonation" if resolved else None, "messageType": "sms",
             "pattern": None, "checks": [{"kind": "claim", "status": "checked", "route": "google_search"}],
             "searchCalls": 1, "searchQueries": 2, "cacheHits": 0, "flybyTokens": {"input": 5}, "simulated": False,
             "searchModel": "gemini-3.1-flash-lite", "magnumNeeded": not resolved, "magnumSearch": False, "reusedOnRetry": 0,
             "gaps": [], "issues": [] if resolved else [{"capability": "reasoning", "text": "Weigh the request."}]}
    routing = {"tc_flyby": flyby, "answeredBy": flyby["answeredBy"], "outcome": "concerning", "completion": "complete",
               "fidelity": {"status": "PASS", "mode": "plain", "attempts": 1, "attemptFailures": [], "at": AT}}
    if not resolved:
        routing["magnum"] = {"search": True, "searchQueries": 3, "itemsSent": 4, "inputTokens": 10, "outputTokens": 5, "simulated": False, "at": AT}
    return routing


@pytest.fixture
def cases(monkeypatch):
    def setup(routing: dict, triage: dict | None = None):
        monkeypatch.setattr(di_record.db, "investigation_cases", _One({"routing": routing}), raising=False)
        monkeypatch.setattr(di_record.db, "triage_investigations", _One({"record": triage} if triage else None), raising=False)
    return setup


@pytest.mark.anyio
async def test_a_flyby_settled_case_records_every_stage_without_the_model(cases):
    triage = evaluate({"source_type": "message"}, investigation_id="tri-1").wire()
    cases(_routing(resolved=True), triage)
    trace = await di_record.decision_trace("owner-1", "case-1")
    assert trace["triage"]["investigationId"] == "tri-1"
    assert trace["flyby"]["resolved"] is True and trace["flyby"]["ranAt"] == AT.isoformat()
    assert trace["flyby"]["checks"][0]["route"] == "web_search"
    assert "searchModel" not in trace["flyby"] and "flybyTokens" not in trace["flyby"]
    assert trace["magnum"] is None
    assert trace["settledReason"]["by"] == "TC Hawkeye"
    assert trace["higgins"] == {"status": "PASS", "mode": "plain", "attempts": 1}
    shown = repr(trace).lower().replace("'geminicalls'", "")  # a field name on the Triage record, never displayed
    assert "gemini" not in shown and "google" not in shown


@pytest.mark.anyio
async def test_an_escalated_case_records_why_and_what_magnum_di_was_given(cases):
    cases(_routing(resolved=False))
    trace = await di_record.decision_trace("owner-1", "case-1")
    assert trace["triage"] is None
    assert trace["flyby"]["issues"] == [{"capability": "reasoning", "text": "Weigh the request."}]
    assert trace["magnum"] == {"webSearch": True, "searchQueries": 3, "itemsSent": 4, "simulated": False, "at": AT.isoformat()}
    assert trace["settledReason"]["by"] == "Magnum DI"


def test_the_di_record_never_carries_the_model_or_provider_tool_name():
    wired = di_record.wire({"correlation_id": "case-1", "model_requested": "gemini-3.1-flash-lite", "simulated": True,
                            "request": {"tools": ["google_search"], "investigationPrompt": "x"}, "created_at": AT})
    assert "modelRequested" not in wired
    assert wired["request"]["tools"] == ["web_search"]
    assert wired["notice"] == "SIMULATED — the preview stood in for the outside service Magnum DI calls; everything else ran exactly as in production"
    assert "gemini" not in repr(wired).lower() and "AI call" not in repr(wired)


def test_the_app_gets_no_tokens_cost_prompts_or_reply():
    """Token counts, cost, timings, the prompts and the full reply are the Admin Portal's, never the phone's."""
    wired = di_record.wire({"correlation_id": "case-1", "simulated": False, "status": "success", "created_at": AT,
                            "request": {"systemPrompt": "sys", "investigationPrompt": "the evidence", "requestBytes": 900, "tools": ["web_search"],
                                        "attachmentCount": 1, "attachments": [{"mimeType": "image/png", "sizeBytes": 10, "privacyScreening": "completed_before_boundary",
                                                                               "redactionStatus": "post_redaction_derivative", "transmittedForm": "image/png"}]},
                            "response": {"text": "{\"verdict\": 1}", "finishReason": "STOP"},
                            "processing": {"promptTokens": 10, "outputTokens": 5, "totalTokens": 15, "cost": {"amountUsd": 0.1}, "durationMs": 9}})
    assert set(wired) == {"investigationId", "engine", "environment", "mode", "simulated", "status", "failureCode", "occurredAt", "request", "notice"}
    assert set(wired["request"]) == {"attachments", "attachmentCount", "tools"}
    assert wired["request"]["attachmentCount"] == 1 and wired["request"]["attachments"][0]["mimeType"] == "image/png"
    shown = repr(wired)
    for hidden in ("the evidence", "sys", "verdict", "Tokens", "cost", "900", "durationMs"):
        assert hidden not in shown


@pytest.mark.anyio
async def test_the_settling_rule_reaches_the_app_without_its_rule_book_code(cases):
    cases(_routing(resolved=False))
    reason = (await di_record.decision_trace("owner-1", "case-1"))["settledReason"]
    assert set(reason) == {"rule", "by", "sentence"}


def test_the_admin_portal_shows_tokens_cost_prompt_and_reply_in_full():
    from routers.admin_portal import _di_transactions_html, _triage_rules_html
    page = _di_transactions_html([{"created_at": AT, "status": "success", "simulated": False, "environment": "Production", "model_requested": "m-1",
                                   "request": {"investigationPrompt": "the <evidence>", "requestBytes": 900},
                                   "response": {"text": "full reply", "finishReason": "STOP"},
                                   "processing": {"promptTokens": 1200, "outputTokens": 30, "totalTokens": 1230, "cost": {"amountUsd": 0.0004, "basis": "estimated"}}}])
    assert "prompt 1,200" in page and "US$0.000400" in page and "full reply" in page and "the &lt;evidence&gt;" in page
    assert "not engaged" in _di_transactions_html([])
    triage = evaluate({"source_type": "message", "unresolved_concern": True}, investigation_id="tri-2").wire()
    rules = _triage_rules_html(triage)
    assert triage["outcome"] in rules and f"v{triage['catalogueVersion']}" in rules


@pytest.mark.anyio
async def test_tc_flybys_search_call_is_never_shown_as_magnum_di(monkeypatch):
    seen = {}

    class _Cursor:
        def __init__(self, docs):
            self.docs = docs

        def sort(self, *_a):
            return self

        def __aiter__(self):
            async def gen():
                for d in self.docs:
                    yield d
            return gen()

    class _Coll:
        def find(self, query, *_a):
            seen["query"] = query
            return _Cursor([])

    monkeypatch.setattr(di_record.db, "di_transactions", _Coll(), raising=False)
    assert await di_record.get_di_records("owner-1", "case-1") == []
    assert seen["query"] == {"correlation_id": "case-case-1", "purpose": {"$ne": "tc_flyby_search"}}


def test_a_limited_triage_is_plain_english_and_never_nothing_to_worry_about():
    investigation = evaluate({"source_type": "message", "unresolved_concern": True})
    assert investigation.outcome is Outcome.LIMITED
    assert not re.search(r"\b[A-Z]+_[A-Z]+", investigation.reason)
    record = {"category": "message", "raw_state": "ears_up", "headline": "Triage: limited — ApolloSG couldn't reach a reliable decision",
              "summary": "ApolloSG couldn't obtain enough evidence to decide: EMAIL_HEADERS_UNAVAILABLE",
              "event": {"why": ["Coverage gap: EMAIL_HEADERS_UNAVAILABLE"], "triage_investigation": investigation.wire()}}
    briefing = generate_higgins_briefing(record, "informational")
    assert briefing["meaning"] == LIMITED_CAUTION
    assert "EMAIL_HEADERS_UNAVAILABLE" not in repr(briefing)
    assert briefing["evidence_points"] == ["Couldn't check: The technical sender information wasn't available."]
    assert "nothing to worry" not in repr(briefing).lower()


def test_plain_codes_translates_lists_of_gap_codes():
    assert plain_codes("Coverage gap: EMAIL_HEADERS_UNAVAILABLE, BROWSER_VISIBILITY_UNAVAILABLE") == (
        "Couldn't check: The technical sender information wasn't available. ApolloSG can't observe the page itself: its content, or the website an installed web app or notification came from.")
    assert plain_codes("Nothing coded here.") == "Nothing coded here."
