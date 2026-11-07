"""Related history (services/higgins/history.py): this device's own earlier cases and ApolloSG's previous encounters.

The owner's rules, proved:
- Devices are mutually exclusive: a related case is only ever one of this device's own; another device's case is never
  found, and nothing on screen says which device or how many devices encountered something.
- History never becomes evidence for the current case: TC Hawkeye's checks never receive it, so it can't make or change
  the outcome; it is never a finding.
- It only adds weight: agreeing history raises the confidence of the concern findings about the same subject, one step.

Run: cd /app/backend && python -m pytest tests/test_related_history.py -q
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.db import now_utc
from services import correlation, observed_intel
from services.higgins import history
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse
from services.higgins.tc_flyby import decide, report, triage
from services.higgins.tc_flyby.official import fact

TEXT = "CommBank: your card is locked. Unlock it now at https://commbank-unlock.top/login"
MATERIAL = {"item-0": TEXT}
ROWS = [{"evidence_id": "item-0", "kind": "text", "origin": "user_submission"},
        {"evidence_id": "file-1", "kind": "document", "origin": "user_submission", "integrity_hash": "ab" * 32}]


def response(outcome: str = "concerning", attention: str = "review") -> HigginsResponse:
    return HigginsResponse(
        revision=1, overview="It uses CommBank's name, but its link isn't CommBank's.", explanation_markdown="**What was found**\n- x",
        assessment="concern_found" if outcome in history.CONCERN else "uncertain", outcome=outcome, attention=attention,
        findings=[Finding(id="f1", text="commbank-unlock.top carries CommBank's name, but it isn't CommBank's domain.", basis="observation",
                          confidence="medium", evidence_ids=["item-0"]),
                  Finding(id="f2", text="The message asks you to unlock your card.", basis="observation", confidence="low", evidence_ids=["item-0"]),
                  Finding(id="f3", text="commbank.com.au is CommBank's official domain.", basis="observation", confidence="high")],
        uncertainties=["Apollo can't confirm who actually sent this."], scope="TC Hawkeye checked the submitted material.",
        actions=[ActionProposal(id="a1", kind="instruction", label="Don't open the link", instruction="Do not open commbank-unlock.top.")],
        recommended_action_id="a1", completion="complete")


def note(match: str, subject: str | None, agrees: bool = True, kind: str = "related_case") -> dict:
    return {"kind": kind, "match": match, "subject": subject, "agrees": agrees, "text": f"An earlier case on this device ({match}).",
            "source": history.DEVICE_SOURCE, "eventId": "ev-earlier", "outcome": "likely_scam" if agrees else "no_scam_indicators"}


# ── It only adds weight ─────────────────────────────────────────────────────────────────────────────────────────────

def test_agreeing_history_raises_only_the_concern_findings_about_the_same_subject_one_step():
    before = response()
    after = history.weigh(before, [note("website", "commbank-unlock.top"), note("organisation", "CommBank")])
    conf = {f.id: f.confidence for f in after.findings}
    assert conf == {"f1": "high", "f2": "low", "f3": "high"}          # f1 once, not twice; f2 isn't about it
    assert [n.finding_ids for n in after.history] == [["f1"], ["f1"]]  # where the weight came from stays visible


def test_a_shared_message_or_connected_event_is_about_the_whole_case_but_never_a_contrary_finding():
    after = history.weigh(response(), [note("connected", None)])
    assert {f.id: f.confidence for f in after.findings} == {"f1": "high", "f2": "medium", "f3": "high"}
    assert after.history[0].finding_ids == ["f1", "f2"]               # "CommBank's official domain" points the other way


@pytest.mark.parametrize("outcome", ["no_scam_indicators", "unable_to_determine"])
def test_history_never_raises_anything_when_the_case_itself_found_no_concern(outcome):
    after = history.weigh(response(outcome, "none"), [note("website", "commbank-unlock.top"), note("message", None)])
    assert [f.confidence for f in after.findings] == [f.confidence for f in response(outcome, "none").findings]
    assert all(n.finding_ids == [] for n in after.history) and len(after.history) == 2


def test_history_that_disagrees_raises_nothing():
    after = history.weigh(response(), [note("website", "commbank-unlock.top", agrees=False)])
    assert [f.confidence for f in after.findings] == ["medium", "low", "high"]


@pytest.mark.parametrize("outcome", list(history.CONCERN) + ["no_scam_indicators", "unable_to_determine"])
@pytest.mark.parametrize("attention", ["urgent", "action_needed", "review", "none"])
def test_history_never_changes_the_verdict_or_anything_but_confidence(outcome, attention):
    before = response(outcome, attention)
    after = history.weigh(before, [note("website", "commbank-unlock.top"), note("message", None), note("organisation", "CommBank")])
    keep = {"findings", "history"}
    assert after.model_dump(exclude=keep) == before.model_dump(exclude=keep)
    assert [(f.id, f.text, f.basis, f.evidence_ids, f.source_ids) for f in after.findings] == \
           [(f.id, f.text, f.basis, f.evidence_ids, f.source_ids) for f in before.findings]


# ── History never becomes evidence ──────────────────────────────────────────────────────────────────────────────────

def _plan():
    plan = triage.plan("Is this real?", [TEXT])
    link = next(c for c in plan.checks if c.kind == "link")
    link.facts.append(fact("commbank-unlock.top is not listed by Google Safe Browsing or Apollo's blocklist.", "clear", topic="listing"))
    link.facts.append(fact("commbank-unlock.top was registered 2 years ago.", "neutral", topic="registration"))
    for c in plan.checks:
        c.status = "resolved"
    return plan


def test_the_cross_source_record_adds_nothing_to_the_checks_and_never_names_devices(monkeypatch):
    async def assertion(*_a, **_k):
        return {"level": "known_malicious", "confidence": "high", "key": "domain:abc"}

    async def related(*_a, **_k):
        return [{"key": "k", "kind": "domain", "name": "listed-elsewhere.top"}]

    async def none(*_a, **_k):
        return []

    async def fresh():
        return set()
    monkeypatch.setattr(observed_intel, "assertion", assertion)
    monkeypatch.setattr(observed_intel, "related", related)
    monkeypatch.setattr(correlation.threat_feeds, "matches", none)
    monkeypatch.setattr(correlation.threat_feeds, "fresh_feeds", fresh)
    plan = _plan()
    before = [list(c.facts) for c in plan.checks]
    decision_before = decide.evaluate(plan, MATERIAL, final=True)[0]
    record = asyncio.run(correlation.cross_source(plan, {}, "owner-a"))
    assert [list(c.facts) for c in plan.checks] == before            # nothing reaches TC Hawkeye's checks
    assert decide.evaluate(plan, MATERIAL, final=True)[0] == decision_before
    rows = [r for e in record for r in e["sources"] if r["source"] == observed_intel.LABEL]
    assert [r["status"] for r in rows][0] == "has been previously reported as malicious — High confidence"
    assert not any("device" in r["status"] or "case" in r["status"] for r in rows)
    assert not any(k in r for r in rows for k in ("firstSeen", "lastConfirmed", "expires"))   # never another device's time
    assert "domain:abc" in correlation.asserted(record)
    assert "domain:abc" not in correlation.brief_lines(record)          # the one-way code never reaches Magnum DI


def test_previous_reports_say_a_statement_and_its_confidence_never_which_device_how_many_or_when(monkeypatch):
    async def assertion(kind, value, exclude=None):
        assert exclude == "owner-a"                                    # this device's own cases are its related cases
        return {"level": "known_malicious", "confidence": "high", "key": f"{kind}:code"}

    async def none(*_a, **_k):
        return []
    monkeypatch.setattr(observed_intel, "assertion", assertion)
    monkeypatch.setattr(observed_intel, "related", none)
    subs = history.subjects(_plan(), MATERIAL, ROWS)
    notes = asyncio.run(history._previously_reported("owner-a", subs))
    texts = [n["text"] for n in notes]
    assert "This link, commbank-unlock.top, has been previously reported as malicious — High confidence." in texts
    assert "This message has been previously reported as malicious — High confidence." in texts
    assert "This file has been previously reported as malicious — High confidence." in texts
    assert all("device" not in t and "case" not in t and "KB" not in t and "knowledge base" not in t for t in texts)
    assert all("at" not in n for n in notes) and all(n["agrees"] for n in notes)
    assert sorted(history.asserted(notes)) == ["domain:code", "file:code", "message:code"]
    shown = history.weigh(response(), notes).history
    assert all("key" not in n.model_dump() for n in shown)             # the one-way code never reaches the phone


@pytest.mark.parametrize("level,text,agrees", [
    ("suspected_malicious", "This link, commbank-unlock.top, has been previously reported as concerning — Medium confidence.", True),
    ("mixed", "This link, commbank-unlock.top, has mixed previous reports.", False),
])
def test_medium_and_mixed_previous_reports(monkeypatch, level, text, agrees):
    async def assertion(kind, value, exclude=None):
        return {"level": level, "confidence": None if level == "mixed" else "medium", "key": "domain:code"} if kind == "domain" else None

    async def related(*_a, **_k):
        raise AssertionError("a disputed subject is never linked to anything else")
    monkeypatch.setattr(observed_intel, "assertion", assertion)
    monkeypatch.setattr(observed_intel, "related", related if level == "mixed" else (lambda *_a, **_k: _empty()))
    notes = asyncio.run(history._previously_reported("owner-a", [s for s in history.subjects(_plan(), MATERIAL, ROWS) if s["match"] == "website"]))
    assert [(n["text"], n["agrees"]) for n in notes] == [(text, agrees)]
    assert history.asserted(notes) == (["domain:code"] if agrees else [])
    after = history.weigh(response(), notes)
    assert (after.findings[0].confidence == "high") is agrees          # mixed previous reports add no weight


async def _empty():
    return []


def test_magnum_di_gets_history_as_labelled_context_never_as_a_signal():
    notes = [note("website", "commbank-unlock.top")]
    brief = report.magnum_brief(_plan().checks, [], {}, None, None, None, notes)
    assert "Related history (context only, never evidence for this case" in brief
    assert f"[{history.DEVICE_SOURCE}]" in brief and "Established signals" not in brief
    assert "Related history" not in report.magnum_brief([], [], {}, None, None, None, [])


def test_the_case_subjects_cover_link_number_address_message_file_and_organisation():
    subs = history.subjects(_plan(), MATERIAL, ROWS)
    assert {s["match"] for s in subs} >= {"website", "organisation", "message", "file"}
    assert all(TEXT not in str(s["value"]) for s in subs)                 # the message is a one-way code, never its text


# ── Devices are mutually exclusive ──────────────────────────────────────────────────────────────────────────────────

def test_a_related_case_is_only_ever_this_devices_own(monkeypatch):
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"history_test_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(history, "db", scratch)
        try:
            subs = history.subjects(_plan(), MATERIAL, ROWS)
            keys_a = [history.device_key("device-a", s) for s in subs]
            keys_b = [history.device_key("device-b", s) for s in subs]
            assert not set(keys_a) & set(keys_b)                          # the same subject can't be linked across devices
            await scratch.patrol_events.insert_one({"device_id": "device-a", "event_id": "ev-a1", "investigation_case_id": "case-a1",
                                                    "scent_id": "sc-1", "state": "barking", "occurred_at": now_utc() - timedelta(hours=1)})
            await scratch.patrol_events.insert_one({"device_id": "device-b", "event_id": "ev-b1", "scent_id": "sc-1", "state": "barking",
                                                    "occurred_at": now_utc()})
            await history.record("device-a", {"case_id": "case-a1", "created_at": now_utc() - timedelta(hours=1)}, "likely_scam", keys_a)
            # Device B has the very same material, and even the same connection id: it finds nothing of device A's.
            found_b = await history._related_cases("device-b", {"case_id": "case-b2"}, subs, {"event_id": "ev-b2", "scent_id": "sc-1"})
            assert [(n["eventId"], n["match"]) for n in found_b] == [("ev-b1", "connected")]       # only its own connected event
            found_a = await history._related_cases("device-a", {"case_id": "case-a2"}, subs, None)
            assert [n["eventId"] for n in found_a] == ["ev-a1"] and found_a[0]["match"] == "message"
            assert found_a[0]["outcome"] == "likely_scam" and found_a[0]["agrees"] is True
            assert await history._related_cases("device-a", {"case_id": "case-a1"}, subs, None) == []   # never the case itself
            stored = await scratch.device_case_history.find_one({"owner_id": "device-a"})
            assert TEXT not in str(stored) and "commbank-unlock" not in str(stored)                 # one-way codes, never content
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())
