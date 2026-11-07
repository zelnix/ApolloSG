"""Evidence model — server processing is never an evidence source (core/evidence_model.py).

Origin, evidence source, processing, completeness and privacy state are kept apart. Server Triage, TC Hawkeye / Magnum DI
projection, device sync and storage never write or imply the server as the answer to "Where did this evidence come
from?", and never change a source once it is recorded. Records stored with the old "server_projected" / "incomplete"
values are read into the separated model without being rewritten.

Run: cd /app/backend && python -m pytest tests/test_evidence_model.py -q
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from core.db import db, now_utc
from core.evidence_model import (EVIDENCE_SOURCES, INVESTIGATION_ADAPTER, SUMMARY_ADAPTER, TRIAGE_ADAPTER, evidence_model)
from core.models import PatrolEvent, PatrolEventIn
from services import patrol_records
from services.higgins import repository as repo
from services.investigation_projector import project_case_started
from services.patrol_policy import minimal_patrol, summary_narrative
from services.triage import evaluate, record_triage_history

AT = datetime(2026, 10, 26, 14, 10, tzinfo=timezone.utc)
SERVER = ("server_projected", "incomplete")


def _doc(**over) -> dict:
    return {"event_id": "e" * 12, "device_id": "d" * 12, "category": "message", "state": "growling", "status": "active",
            **summary_narrative("message", "growling", False), "indicator_host": None, "indicator_digest": None,
            "verified_block": False, "adapter_label": SUMMARY_ADAPTER, "occurred_at": AT, "resolved_at": None, **over}


def test_legacy_records_are_read_into_the_separated_model():
    # Server Triage of a mailbox email, server Triage of a text this device sent, an investigation from Gmail,
    # a device's privacy summary, and the truth gate's old "incomplete".
    cases = [
        (_doc(evidence_provenance="server_projected", adapter_label=TRIAGE_ADAPTER, category="email", triage_investigation={"coverageGaps": [1]}),
         ("connected_mailbox", "apollosg_servers", "partial", "privacy_protected_copy")),
        (_doc(evidence_provenance="server_projected", adapter_label=TRIAGE_ADAPTER, triage_investigation={}),
         ("device_submission", "apollosg_servers", "complete", "privacy_protected_copy")),
        (_doc(evidence_provenance="server_projected", adapter_label=INVESTIGATION_ADAPTER, investigation_case_id="c1", source_metadata={"provider": "Gmail"}),
         ("connected_mailbox", "apollosg_servers", None, "privacy_protected_copy")),
        (_doc(evidence_provenance="server_projected"), (None, "this_device", None, "privacy_summary")),
        (_doc(), (None, "this_device", None, "privacy_summary")),
        (_doc(evidence_provenance="incomplete", adapter_label="Apollo"), (None, "this_device", "partial", "full_record")),
    ]
    for doc, expected in cases:
        model = evidence_model(doc)
        assert tuple(model.values()) == expected, (doc.get("adapter_label"), model)
        parsed = PatrolEventIn.model_validate(doc)  # stored legacy values never fail validation
        assert parsed.evidence_provenance not in SERVER
        assert PatrolEvent.from_mongo({**doc, "created_at": AT, "updated_at": AT}).evidence_provenance not in SERVER


def test_a_device_sync_keeps_only_the_devices_own_source_and_never_names_the_server():
    for sent, kept in (("dns_observation", "dns_observation"), ("native_protection", "native_protection"),
                       ("connected_mailbox", None), (None, None)):
        payload = minimal_patrol(PatrolEventIn.model_validate(_doc(evidence_provenance=sent, processing_source="apollosg_servers")), False)
        assert payload["evidence_provenance"] == kept
        assert (payload["processing_source"], payload["evidence_representation"]) == ("this_device", "privacy_summary")


def test_the_patrol_record_wire_carries_the_model_and_never_the_server_as_source():
    row = {"record_id": "r1", "logical_issue_key": "k", "revision": 1, "source_event_id": "e1", "source_type": "investigation",
           "category": "message", "headline": "h", "summary": "s", "raw_state": "growling", "effective_state": "warning",
           "effective_reason": "x", "freshness": {}, "occurred_at": AT, "created_at": AT,
           "event": {"adapter_label": INVESTIGATION_ADAPTER, "investigation_case_id": "c1", "evidence_provenance": "server_projected"}}
    wire = patrol_records._wire(row)
    assert "evidence_provenance" not in {k for k in wire if k != "event"}
    assert wire["event"]["evidence_provenance"] == "device_submission"
    assert wire["event"]["processing_source"] == "apollosg_servers"


@pytest.mark.anyio
async def test_server_triage_projection_and_sync_never_alter_the_recorded_source():
    owner = f"test-evmodel-{uuid.uuid4().hex[:10]}"
    try:
        # Server Triage records what supplied the evidence; the server is only where it was processed.
        investigation = evaluate({"source_type": "message", "signals": {"gift_cards": True}})
        event_id = await record_triage_history(owner, investigation, category="email", evidence_source="connected_mailbox")
        stored = await db.patrol_events.find_one({"device_id": owner, "event_id": event_id})
        assert (stored["evidence_provenance"], stored["processing_source"]) == ("connected_mailbox", "apollosg_servers")
        with pytest.raises(ValueError):
            await record_triage_history(owner, investigation, category="email", evidence_source="server_projected")

        # An investigation the server files itself: the device sent it.
        case = await repo.create_case(owner, "text", None, initiator="apollo_automatic")
        assert await project_case_started({**case, "owner_id": owner})
        filed = await db.patrol_events.find_one({"device_id": owner, "investigation_case_id": case["case_id"]})
        assert filed["evidence_provenance"] == "device_submission"
        assert filed["evidence_representation"] == "privacy_protected_copy"

        # The device's copy of a record already filed with a source never changes that source.
        from routers.patrol import upsert_event
        body = PatrolEventIn.model_validate({**_doc(event_id=filed["event_id"], device_id=owner, occurred_at=now_utc()),
                                             "evidence_provenance": "local_device"})
        await upsert_event(body)
        after = await db.patrol_events.find_one({"device_id": owner, "event_id": filed["event_id"]})
        assert after["evidence_provenance"] == "device_submission"
        assert after["processing_source"] == "apollosg_servers"

        # No record this owner holds, nor its Patrol records, names the server as an evidence source.
        for doc in await db.patrol_events.find({"device_id": owner}).to_list(50):
            assert doc.get("evidence_provenance") in EVIDENCE_SOURCES
        for record in await patrol_records.current(owner):
            assert record["event"].get("evidence_provenance") in (*EVIDENCE_SOURCES, None)
            assert record["event"].get("evidence_provenance") not in SERVER
            assert record["event"]["device_id"] == owner
    finally:
        await db.patrol_events.delete_many({"device_id": owner})
        await db.patrol_records.delete_many({"owner_id": owner})
        await db.triage_investigations.delete_many({"device_id": owner})
        await db.investigation_cases.delete_many({"owner_id": owner})
