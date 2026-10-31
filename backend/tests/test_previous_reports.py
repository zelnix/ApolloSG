"""ApolloSG's previous reports (services/observed_intel.py): cross-device intelligence through the KB only.

The owner's rules, proved:
- A device is told only an approved assertion — a statement and its confidence, or "mixed previous reports" — never a
  count, a time, which device, or anyone's case or verdict. Its own marks are never part of what it is told.
- Unanimity: one contradicting finding removes it at once; inconclusive and insufficient findings never break it.
- No artificial consensus: a finding made while ApolloSG already asserted the same thing to the case is dependent and
  never counts; a dependent repeat never replaces a device's own independent finding. Case A → assertion → Case B can
  never grow the same assertion.

Run: cd /app/backend && python -m pytest tests/test_previous_reports.py -q
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.db import now_utc
from services import observed_intel as oi
from services.higgins import repository as repo

SITE = "scam-example-parcel.top"


def _run(body):
    async def go():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"reports_test_{uuid.uuid4().hex[:8]}"]
        mp = pytest.MonkeyPatch()
        mp.setattr(oi, "db", scratch)
        try:
            await body(scratch)
        finally:
            mp.undo()
            await client.drop_database(scratch.name)
            client.close()
    asyncio.run(go())


async def _mark(device: str, stance: str = "supporting", independent: bool = True, at=None):
    key, name = oi.subject("domain", SITE)
    await oi._add("observed", key, device, at or now_utc(), {"subject_kind": "domain", "readable": name}, stance=stance, independent=independent)


async def _level(exclude: str | None = "asker"):
    said = await oi.assertion("domain", SITE, exclude=exclude)
    return said and said["level"]


def test_an_assertion_is_a_level_and_a_confidence_only():
    async def body(_db):
        for d in ("a", "b", "c"):
            await _mark(d)
        said = await oi.assertion("domain", SITE, exclude="asker")
        assert set(said) == {"level", "confidence", "key"}
        assert (said["level"], said["confidence"]) == ("known_malicious", "high")
        assert oi.SAID[said["level"]] == "has been previously reported as malicious — High confidence"
        assert not any(ch.isdigit() for ch in oi.SAID.values().__str__())   # never a count
    _run(body)


def test_confidence_grows_with_independent_unanimous_findings_and_the_asker_never_counts():
    async def body(_db):
        await _mark("a")
        assert await _level() is None                       # one report asserts nothing
        await _mark("b")
        assert await _level() == "suspected_malicious"
        await _mark("asker")
        assert await _level() == "suspected_malicious"      # the asking device's own finding is never part of it
        await _mark("c")
        assert await _level() == "known_malicious"
        assert await _level(exclude="c") == "known_malicious"   # to device c: a, b and the earlier asker are the others
    _run(body)


def test_one_contradicting_finding_removes_unanimity_at_once():
    async def body(_db):
        for d in ("a", "b", "c", "d"):
            await _mark(d)
        assert await _level() == "known_malicious"
        await _mark("e", "contradicting")
        assert await _level() == "mixed"
        assert (await oi.assertion("domain", SITE, exclude="asker"))["confidence"] is None
        assert oi.SAID["mixed"] == "has mixed previous reports"
    _run(body)


def test_inconclusive_and_insufficient_findings_never_break_unanimity_or_count_as_support():
    async def body(_db):
        for d in ("a", "b", "c"):
            await _mark(d)
        await _mark("x", "inconclusive")
        await _mark("y", "insufficient")
        assert await _level() == "known_malicious"
        doc = await _db.threat_indicators.find_one({"source": oi.SOURCE})
        assert doc["consensus"] == {"supporting": 3, "contradicting": 0, "inconclusive": 1, "insufficient": 1, "dependent": 0}
        assert doc["unanimous"] is True
    _run(body)


def test_mixed_needs_enough_reports_before_anything_is_said():
    async def body(_db):
        await _mark("a")
        await _mark("b", "contradicting")
        assert await _level() is None                       # two reports: nothing, so no one's verdict can be inferred
        await _mark("c", "contradicting")
        assert await _level() == "mixed"
    _run(body)


def test_a_devices_latest_finding_replaces_its_earlier_one():
    async def body(_db):
        for d in ("a", "b", "c"):
            await _mark(d)
        await _mark("c", "contradicting")                   # device c now found it clean
        assert await _level() == "mixed"
        doc = await _db.threat_indicators.find_one({"source": oi.SOURCE})
        assert (doc["consensus"]["supporting"], doc["consensus"]["contradicting"], len(doc["marks"])) == (2, 1, 3)
    _run(body)


def test_dependent_findings_never_count_as_independent_confirmation():
    async def body(_db):
        await _mark("a")
        await _mark("b")
        for d in ("c", "d", "e", "f"):
            await _mark(d, independent=False)
        assert await _level() == "suspected_malicious"      # four dependent findings add nothing
        doc = await _db.threat_indicators.find_one({"source": oi.SOURCE})
        assert doc["devices_30d"] == 2 and doc["consensus"]["dependent"] == 4 and doc["hostname"] == ""
    _run(body)


def test_a_dependent_repeat_never_replaces_a_devices_own_independent_finding():
    async def body(_db):
        for d in ("a", "b", "c"):
            await _mark(d)
        await _mark("a", independent=False)
        assert await _level() == "known_malicious"
        doc = await _db.threat_indicators.find_one({"source": oi.SOURCE})
        assert doc["consensus"]["supporting"] == 3 and doc["consensus"]["dependent"] == 0
    _run(body)


def test_old_marks_stop_counting():
    async def body(_db):
        old = now_utc() - oi.WINDOW - timedelta(days=1)
        for d in ("a", "b"):
            await _mark(d, at=old)
        await _mark("c")
        assert await _level() is None
    _run(body)


async def _case(db, owner: str, case_id: str, asserted: list[str]):
    record = {"checks": [{"kind": "link", "subject": SITE}], "kbAsserted": asserted}
    await db.investigation_cases.insert_one({"owner_id": owner, "case_id": case_id, "tc_flyby_ciphertext": repo.enc_json(record)})


def test_case_a_to_assertion_to_case_b_never_grows_the_same_assertion():
    async def body(db):
        key = oi.subject("domain", SITE)[0]
        for d in ("a", "b", "c"):                            # three independent cases make it High
            await _case(db, d, f"case-{d}", [])
            assert await oi.record_case(d, f"case-{d}", "likely_scam") == 1
        assert await _level() == "known_malicious"
        # Device d's case was told "previously reported as malicious": its concern is dependent on that assertion.
        await _case(db, "d", "case-d", [key])
        await oi.record_case("d", "case-d", "likely_scam")
        doc = await db.threat_indicators.find_one({"source": oi.SOURCE, "scope": "observed"})
        assert doc["devices_30d"] == 3 and doc["consensus"]["dependent"] == 1
        # Device a's own earlier independent finding stays; a told-again repeat doesn't replace it.
        await _case(db, "a", "case-a2", [key])
        await oi.record_case("a", "case-a2", "concerning")
        doc = await db.threat_indicators.find_one({"source": oi.SOURCE, "scope": "observed"})
        assert doc["devices_30d"] == 3
        # Once one of the independent findings is contradicted, the dependent ones can't hold the assertion up.
        await _case(db, "c", "case-c2", [key])
        await oi.record_case("c", "case-c2", "no_scam_indicators", completion="complete")
        assert await _level() == "mixed"
    _run(body)


@pytest.mark.parametrize("outcome,completion,stance", [
    ("likely_scam", "complete", "supporting"), ("concerning", "partial", "supporting"),
    ("no_scam_indicators", "complete", "contradicting"), ("no_scam_indicators", "partial", "insufficient"),
    ("unable_to_determine", "complete", "inconclusive"), ("unable_to_determine", "partial", "insufficient"),
    (None, "complete", None),
])
def test_each_outcome_is_one_stance(outcome, completion, stance):
    assert oi.stance_of(outcome, completion) == stance


def test_a_simulated_result_or_a_case_already_recorded_is_never_recorded():
    async def body(db):
        await _case(db, "a", "case-a", [])
        assert await oi.record_case("a", "case-a", "likely_scam", simulated=True) == 0
        assert await oi.record_case("a", "case-a", "likely_scam") == 1
        assert await oi.record_case("a", "case-a", "likely_scam") == 0
    _run(body)


def test_relations_never_carry_a_count():
    async def body(db):
        other = "parcel-fee-pay.top"
        for d in ("a", "b", "c"):
            record = {"checks": [{"kind": "link", "subject": SITE}, {"kind": "link", "subject": other}]}
            await db.investigation_cases.insert_one({"owner_id": d, "case_id": f"rel-{d}", "tc_flyby_ciphertext": repo.enc_json(record)})
            await oi.record_case(d, f"rel-{d}", "likely_scam")
        rows = await oi.related("domain", SITE)
        assert [set(r) for r in rows] == [{"key", "kind", "name"}] and rows[0]["name"] == other
    _run(body)
