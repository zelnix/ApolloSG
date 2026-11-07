"""Ended investigations never stay on "Apollo is investigating this": project_ended_cases gives them a final state.

Run: cd /app/backend && python -m pytest tests/test_ended_projection.py -q
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.db import db
from services.investigation_projector import _RUNNING, ended_view, project_ended_cases

AT = datetime(2020, 1, 1, 9, 0, tzinfo=timezone.utc)  # older than anything real, so the oldest-first scan reaches it
CLEAR_ROUTING = {"answeredBy": "tc_flyby_search", "tc_flyby": {"resolved": True, "outcome": "no_scam_indicators", "basis": "clear"}}


def test_recorded_outcome_is_the_final_result():
    view = ended_view({"status": "expired", "response_revision": 1, "routing": CLEAR_ROUTING})
    # The four PRD tiers use unified wording — a legacy "no_scam_indicators" record is shown with the
    # current "not_scam" tier's headline (outcomes.LEGACY_LABELS), not its own historical wording.
    assert view["outcome"] == "no_scam_indicators" and view["headline"] == "This is not a scam"
    assert view["state"] == "resting" and view["status"] == "resolved"
    assert view["what_happened"].startswith("Settled by TC Hawkeye")


def test_finished_without_a_kept_result_never_claims_a_verdict():
    view = ended_view({"status": "expired", "response_revision": 1, "routing": {}})
    assert view["outcome"] is None and view["headline"] == "Investigation finished" and "state" not in view


def test_never_answered_says_so():
    assert ended_view({"status": "cancelled", "response_revision": 0})["what_happened"].startswith("This investigation was cancelled before")
    assert ended_view(None)["headline"] == "Investigation no longer available"


@pytest.fixture
async def owner():
    device = f"test-ended-{uuid.uuid4().hex[:12]}"
    yield device
    for name, field in (("patrol_events", "device_id"), ("investigation_cases", "owner_id"), ("higgins_investigation_history", "owner_id")):
        await db[name].delete_many({field: device})


def _placeholder(owner: str, case_id: str, minutes: int) -> dict:
    return {"event_id": f"evt-{uuid.uuid4().hex[:10]}", "device_id": owner, "category": "call", "state": "sniffing", "status": "active",
            "headline": _RUNNING["headline"], "what_happened": _RUNNING["what_happened"], "why": list(_RUNNING["why"]),
            "what_to_do": _RUNNING["what_to_do"], "investigation_case_id": case_id, "investigation_completed_at": None,
            "deleted_at": None, "occurred_at": AT + timedelta(minutes=minutes)}


async def test_ended_cases_get_their_final_state_and_live_ones_are_left(owner):
    settled, empty, live = (str(uuid.uuid4()) for _ in range(3))
    await db.investigation_cases.insert_many([
        {"owner_id": owner, "case_id": settled, "status": "expired", "deleted": True, "response_revision": 1, "routing": CLEAR_ROUTING,
         "gates": ["call"], "created_at": AT, "updated_at": AT + timedelta(seconds=2)},
        {"owner_id": owner, "case_id": empty, "status": "expired", "deleted": True, "gates": ["call"], "created_at": AT, "updated_at": AT},
        {"owner_id": owner, "case_id": live, "status": "investigating", "deleted": False, "gates": ["call"], "created_at": AT, "updated_at": AT},
    ])
    await db.patrol_events.insert_many([_placeholder(owner, settled, 0), _placeholder(owner, empty, 1), _placeholder(owner, live, 2)])

    await project_ended_cases(limit=5000)

    by_case = {e["investigation_case_id"]: e async for e in db.patrol_events.find({"device_id": owner}, {"_id": 0})}
    done = by_case[settled]
    assert done["headline"] == "This is not a scam" and done["state"] == "resting" and done["status"] == "resolved"
    assert done["investigation_completed_at"] and done["resolved_at"]
    history = await db.higgins_investigation_history.find_one({"owner_id": owner, "case_id": settled})
    assert history and history["deleted"] is False and history["attention"] == "none"

    ended = by_case[empty]
    assert ended["headline"] == "Investigation ended without a result" and ended["state"] == "ears_up"
    assert ended["why"] == [] and ended["investigation_completed_at"]
    assert not await db.higgins_investigation_history.find_one({"owner_id": owner, "case_id": empty})

    assert by_case[live]["investigation_completed_at"] is None and by_case[live]["headline"] == _RUNNING["headline"]
