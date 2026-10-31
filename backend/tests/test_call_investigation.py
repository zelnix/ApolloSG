"""A call check gets a real scam assessment, never a library answer.

- A case opened from a call check is a call to assess, never a general question for the knowledge base.
- The call as the person describes it is compared with Scamwatch's phone-scam patterns (bank or card provider asking
  for a code, fake police / tax office / government, fake tech support, delivery or parcel fees): a full match is
  Likely scam, settled by TC FlyBy with no AI call.
- Those patterns are for calls only: the same words in a message are compared with the message patterns.

Run: cd /app/backend && python -m pytest tests/test_call_investigation.py -q
"""
import uuid

import pytest

from core.db import db
from services.higgins import jobs
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.tc_flyby import patterns, triage
from tests.test_tc_flyby_routing import _gateway, _lookups

pytestmark = pytest.mark.anyio


async def _call_case(details: str | None, *, message="Investigate this phone call."):
    """A case opened from a call check (gate "call"), run through the real job."""
    owner = f"call-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "call", None)
    if details:
        await ev.ingest_text(owner, case, "item-0", details, kind="text", origin="user_submission", label="Call details")
    case = await repo.get_case(owner, case["case_id"])
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest(turn_id), repo.digest("p"), "turn", {"message": message, "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": case["revision"]}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "queued"}})
    await jobs.run(owner, case["case_id"], job["job_id"])
    events = await repo.events_after(owner, job["job_id"], 0)
    response = next((e["payload"]["response"] for e in events if e["type"] == "response"), None)
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0})
    return stored, response


def test_a_call_check_is_never_a_general_question():
    question = "About the phone call I just checked. Verification code request. Can you walk me through what Apollo found and what I should do?"
    assert triage.plan(question, []).general, "the same words outside a call check are a general question"
    plan = triage.plan(question, [], gate="call")
    assert not plan.general and plan.channel == "call"


@pytest.mark.parametrize("details,key", [
    ("bank wants my code", "bank_code_call"),
    ("The caller said they were from my bank (CommBank).\nThey asked me to give a verification code.", "bank_code_call"),
    ("CommBank rang and asked me to read out the code they just texted me", "bank_code_call"),
    ("The caller said they were from the government, the police or the ATO.\nThey asked me to buy gift cards.", "government_call"),
    ("ATO called saying I owe tax and must pay $3,000 today", "government_call"),
    ("The caller said they were from tech support (Microsoft, Apple…).\nThey asked me to allow remote access.", "tech_support_call"),
    ("The caller said they were from my telco or the NBN.\nThey asked me to install an app.", "tech_support_call"),
    ("The caller said they were from a delivery or parcel company.\nThey asked me to give my bank or card details.", "delivery_call"),
    ("They said my parcel is stuck and I need to pay a $4.50 redelivery fee", "delivery_call"),
])
async def test_each_phone_scam_pattern_matches_the_call_as_described(details, key):
    found = await patterns.best(details, has_link=False, has_brand=False, offsite=None, channel="call")
    assert found and found.stage == "full" and found.entry["pattern"]["key"] == key, details
    assert "$3" not in (found.ask[1] if found.ask else "") or "$3,000" in found.ask[1], "an amount is quoted whole"


async def test_call_patterns_never_match_a_message():
    for text in ("bank wants my code", "The caller said they were from tech support.\nThey asked me to allow remote access."):
        found = await patterns.best(text, has_link=False, has_brand=False, offsite=None)
        assert not found or found.entry["pattern"].get("channel") is None


async def test_nothing_risky_asked_is_not_a_pattern_match():
    assert await patterns.best("The caller said they were from my bank.\nThey didn't ask me to do anything unusual.",
                               has_link=False, has_brand=False, offsite=None, channel="call") is None


async def test_bank_wants_my_code_gets_a_scam_assessment_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    case, response = await _call_case("The caller said they were from my bank (CommBank).\nThey asked me to give a verification code.\n"
                                      "What the caller said, in my words: bank wants my code")
    assert calls == [], "a full phone-scam pattern match is settled by TC FlyBy"
    assert response["outcome"] == "likely_scam" and response["attention"] == "action_needed"
    assert response["findings"], "a scam assessment, not a library answer"
    assert "bank call scam" in response["overview"] and "Scamwatch" in response["overview"]
    assert any(a["label"] == "Call your bank yourself" for a in response["actions"])
    assert "who actually called" in " ".join(response["uncertainties"])
    assert "general information" not in response["explanationMarkdown"]
    assert case["routing"]["tc_flyby"]["pattern"] == {"key": "bank_code_call", "stage": "full"}
    assert case["routing"]["tc_flyby"]["messageType"] != "general_question"


async def test_a_call_described_only_in_the_question_goes_to_magnum_not_the_library(monkeypatch):
    from services.higgins.provider import Purpose
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    case, response = await _call_case(None, message="About the phone call I just checked. The bank wants my code. What should I do?")
    assert [c["purpose"] for c in calls] == [Purpose.INVESTIGATION]
    assert case["routing"]["tc_flyby"]["messageType"] != "general_question" and case["routing"]["answeredBy"] == "magnum_di"
    assert response["outcome"], "an assessment of the call, with an outcome"
