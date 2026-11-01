# The person deletes chosen cases on their phone (services/case_delete.py): every copy ApolloSG's server holds of them
# goes, another device's records are never touched, and a deleted record can't come back from the phone's queue.
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from services.case_delete import REMOVED_REASON, triage_event_id
from tests.test_enforcement_evidence_gate import API, _device

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
NOW = datetime.now(timezone.utc)


def _event(did: str, eid: str, case_id: str | None = None) -> dict:
    return {"event_id": eid, "device_id": did, "category": "message", "state": "growling", "status": "active",
            "headline": "Message worth a second look", "what_happened": "Asks for a code", "why": [], "what_to_do": "",
            "indicator_host": None, "indicator_digest": None, "verified_block": False, "adapter_label": "web",
            "occurred_at": "2026-06-01T00:00:00Z", "resolved_at": None, **({"investigation_case_id": case_id} if case_id else {})}


def _seed_case(owner: str, case_id: str, event_ids: list[str]) -> None:
    DB.investigation_cases.insert_one({"owner_id": owner, "case_id": case_id, "status": "complete", "deleted": False, "revision": 1,
                                       "epoch": "e1", "created_at": NOW, "updated_at": NOW, "expires_at": NOW,
                                       "accepted_commits": [], "pending_device_request_ids": [], "cleanup_status": "not_due",
                                       "response_ciphertext": "secret"})
    DB.investigation_evidence.insert_one({"owner_id": owner, "case_id": case_id, "text": "the message itself"})
    DB.investigation_device_pickups.insert_one({"owner_id": owner, "case_id": case_id})
    DB.di_transactions.insert_one({"owner": owner, "investigation_id": case_id, "correlation_id": f"case-{case_id}", "request": "x"})
    DB.triage_investigations.insert_one({"device_id": owner, "investigation_id": f"t-{case_id}", "investigation_case_id": case_id, "record": {}})
    DB.higgins_investigation_history.insert_one({"owner_id": owner, "case_id": case_id, "history_id": f"h-{case_id}"})
    DB.device_case_history.insert_one({"owner_id": owner, "case_id": case_id, "event_id": event_ids[0], "expires_at": NOW})
    for eid in event_ids:
        DB.shared_events.insert_one({"event_id": eid, "protected_device_id": owner, "guardian_device_id": "g1", "headline": "x"})
        DB.threat_notes.insert_one({"event_id": eid, "protected_device_id": owner, "text": "note"})
        DB.held_alerts.insert_one({"device_id": owner, "event_key": f"owner-{eid}", "data": {"message": "x"}})


def _counts(owner: str, case_id: str, eids: list[str]) -> dict[str, int]:
    return {
        "evidence": DB.investigation_evidence.count_documents({"owner_id": owner, "case_id": case_id}),
        "pickups": DB.investigation_device_pickups.count_documents({"owner_id": owner, "case_id": case_id}),
        "di": DB.di_transactions.count_documents({"owner": owner, "investigation_id": case_id}),
        "triage": DB.triage_investigations.count_documents({"device_id": owner, "investigation_case_id": case_id}),
        "history": DB.higgins_investigation_history.count_documents({"owner_id": owner, "case_id": case_id}),
        "case_history": DB.device_case_history.count_documents({"owner_id": owner, "case_id": case_id}),
        "shared": DB.shared_events.count_documents({"protected_device_id": owner, "event_id": {"$in": eids}}),
        "notes": DB.threat_notes.count_documents({"protected_device_id": owner, "event_id": {"$in": eids}}),
        "held": DB.held_alerts.count_documents({"device_id": owner, "event_key": {"$in": [f"owner-{e}" for e in eids]}}),
        "records": DB.patrol_records.count_documents({"owner_id": owner, "source_event_id": {"$in": eids}}),
    }


def test_deleting_cases_removes_every_server_copy_and_only_this_devices():
    did, auth = _device()
    other, other_auth = _device()
    case_id, other_case = f"case_{uuid.uuid4().hex[:10]}", f"case_{uuid.uuid4().hex[:10]}"
    chosen, linked, kept, never_sent = (f"evt_{uuid.uuid4().hex[:10]}" for _ in range(4))
    for eid, cid in ((chosen, case_id), (linked, case_id), (kept, None)):
        assert requests.post(f"{API}/patrol/events", json=_event(did, eid, cid), headers=auth, timeout=15).status_code == 200
    theirs = f"evt_{uuid.uuid4().hex[:10]}"
    assert requests.post(f"{API}/patrol/events", json=_event(other, theirs, other_case), headers=other_auth, timeout=15).status_code == 200
    _seed_case(did, case_id, [chosen, linked])
    _seed_case(other, other_case, [theirs])
    # The server's own binding of each record to its investigation (POST /patrol/events/{id}/investigation).
    DB.patrol_events.update_many({"device_id": did, "event_id": {"$in": [chosen, linked]}}, {"$set": {"investigation_case_id": case_id}})
    DB.patrol_events.update_one({"device_id": other, "event_id": theirs}, {"$set": {"investigation_case_id": other_case}})
    requests.get(f"{API}/patrol/records", headers=auth, timeout=15)  # projects the Patrol records
    assert _counts(did, case_id, [chosen, linked])["records"] >= 2

    r = requests.post(f"{API}/patrol/delete", json={"eventIds": [chosen, never_sent, theirs], "caseIds": [other_case]}, headers=auth, timeout=30)
    assert r.status_code == 200, r.text
    # `theirs` only gets a marker under this device's id: the other device's record is never touched (checked below).
    assert set(r.json()["eventIds"]) == {chosen, linked, never_sent, theirs} and r.json()["caseIds"] == [case_id]

    # Every copy of the chosen case is gone, its linked record with it.
    assert all(v == 0 for v in _counts(did, case_id, [chosen, linked]).values()), _counts(did, case_id, [chosen, linked])
    case = DB.investigation_cases.find_one({"owner_id": did, "case_id": case_id})
    assert case["deleted"] is True and "response_ciphertext" not in case
    for eid in (chosen, linked, never_sent):
        assert set(DB.patrol_events.find_one({"device_id": did, "event_id": eid}, {"_id": 0})) == {"event_id", "device_id", "removed_reason", "deleted_at"}
    # The rest of this device, and the other device's case (even when named), are untouched.
    for owner, eid in ((did, kept), (other, theirs)):
        doc = DB.patrol_events.find_one({"device_id": owner, "event_id": eid})
        assert doc.get("headline") and "removed_reason" not in doc and doc.get("deleted_at") is None
    assert all(v > 0 for k, v in _counts(other, other_case, [theirs]).items() if k != "records")
    assert DB.investigation_cases.find_one({"owner_id": other, "case_id": other_case})["deleted"] is False

    listed = {e["sourceEventId"] for e in requests.get(f"{API}/patrol/records", headers=auth, timeout=15).json()}
    assert kept in listed and not listed & {chosen, linked}
    removed = set(requests.get(f"{API}/patrol/removed", headers=auth, timeout=15).json()["eventIds"])
    assert {chosen, linked, never_sent} <= removed and kept not in removed

    # A copy still in the phone's delivery queue is acknowledged, never stored again.
    again = requests.post(f"{API}/patrol/events", json=_event(did, never_sent), headers=auth, timeout=15)
    assert again.status_code == 200 and again.json()["event_id"] == never_sent
    assert DB.patrol_events.find_one({"device_id": did, "event_id": never_sent})["removed_reason"] == REMOVED_REASON


def test_a_triage_record_the_server_filed_goes_with_its_patrol_record():
    did, auth = _device()
    DB.triage_investigations.insert_one({"device_id": did, "investigation_id": "inv-1", "subject": "Bank <a@b.co>", "record": {}})
    eid = triage_event_id(did, "inv-1")
    r = requests.post(f"{API}/patrol/delete", json={"eventIds": [eid]}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    assert DB.triage_investigations.count_documents({"device_id": did}) == 0


def test_delete_needs_the_devices_own_sign_in():
    r = requests.post(f"{API}/patrol/delete", json={"eventIds": ["x"]}, headers={"User-Agent": "apollo-tests", "X-Apollo-Raw": "1"}, timeout=15)
    assert r.status_code == 401
