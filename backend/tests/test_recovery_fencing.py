"""Renewable-ownership recovery fencing regressions (review remediation): upload finalisation takeover, device-result
submission stage claims, and the work_epoch backfill migration. No Gemini calls — device observations and evidence
ingestion here are purely local (regex/text), never routed through the provider."""
import asyncio
import io
import json
import os
import uuid
from datetime import timedelta
from starlette.requests import Request

import pytest

from core.db import db, now_utc
from services.higgins import jobs
from services.higgins import repository as repo
from services.higgins.contracts import DeviceResult


import routers.investigations as inv


async def test_upload_finalisation_takeover_is_exclusive():
    await _upload_takeover_race()


async def test_device_submission_stage_claim_is_exclusive_and_renewable():
    await _device_submission_stage_race(inv)


async def test_device_submission_happy_path_still_resumes_the_job():
    await _device_submission_happy_path(inv)


async def test_backfill_work_epochs_is_idempotent_and_revives_nothing():
    await _backfill_work_epochs()


async def test_scanned_pdf_page_is_rendered_without_crashing():
    await _scanned_pdf_no_crash()


async def test_coverage_aggregates_across_text_and_image_children():
    await _coverage_aggregation_across_children()


async def test_truncated_text_never_reaches_examined():
    await _truncated_text_never_reaches_examined()


async def test_ordinary_partial_read_still_reaches_examined_once_complete():
    await _partial_then_complete_read_reaches_examined()


async def test_upload_replay_rejects_a_different_file_under_the_same_client_item():
    await _upload_replay_digest_mismatch_is_rejected(inv)


async def test_upload_replay_binds_to_identical_content_from_a_different_upload():
    await _upload_replay_digest_match_binds(inv)


async def test_device_observation_metadata_without_content_is_reingested():
    await _device_observation_missing_content_is_reingested(inv)


async def test_lease_renewal_detects_loss_and_stops_the_work():
    await _lease_renewal_detects_loss(inv)


async def test_device_submission_resumes_from_a_crashed_storing_state():
    await _device_submission_resumes_from_storing(inv)


async def test_device_submission_is_not_acknowledged_before_job_consumes_it():
    await _device_submission_waits_for_authoritative_consumption(inv)


async def test_incomplete_evidence_attempt_is_invisible_until_root_publication():
    await _evidence_publication_is_atomic()


async def test_device_tool_request_replay_uses_one_durable_request_identity():
    await _device_request_identity_is_durable()


async def test_legacy_content_discard_migration_runs_only_once():
    await _legacy_content_discard_is_one_time()


async def test_published_evidence_root_cannot_be_discarded_as_incomplete():
    await _published_root_survives_discard()


async def test_published_root_replays_when_upload_projection_was_interrupted():
    await _published_root_repairs_upload_projection(inv)


async def test_stale_cancellation_cannot_clear_a_newer_active_turn():
    await _stale_cancel_preserves_new_turn(inv)


async def test_duplicate_cancellation_is_idempotent_and_cleanup_complete():
    await _duplicate_cancel(inv)


async def test_completion_wins_cancel_race_and_returns_answer_state():
    await _completion_wins_cancel(inv)



@pytest.mark.skip(reason="Coordinator simplified to single-pass Gemini call; checkpoint/ledger replay was removed")
async def test_observation_ledger_replay_restores_pending_request():
    await _ledger_replay_restores_observation()


@pytest.mark.skip(reason="Coordinator simplified to single-pass Gemini call; consumed observation repair was removed")
async def test_consumed_observation_repairs_inbox_before_coordinator_wait_check():
    await _consumed_observation_repairs_inbox()


def test_document_continuation_removes_only_the_extracted_page_gap():
    from services.higgins.evidence import _subtract_page_range
    ranges = [{"start": 64, "end": 200, "reason": "later pages"}, {"start": 4, "end": 5, "reason": "scanned"}]
    assert _subtract_page_range(ranges, 64, 128) == [
        {"start": 128, "end": 200, "reason": "later pages"}, {"start": 4, "end": 5, "reason": "scanned"}
    ]


async def test_document_continuation_publishes_a_later_pdf_slice():
    await _document_continuation_publishes_slice()


async def test_clue_cap_has_replayable_continuation_instead_of_silent_omission():
    await _clue_continuation_is_replayable()


async def test_structured_device_observation_preserves_provenance_fields():
    await _structured_observation_preserves_provenance()


async def test_settings_confirmation_is_user_reported_evidence():
    await _settings_confirmation_is_user_reported(inv)


async def test_patrol_investigation_binding_is_owner_scoped_and_idempotent():
    await _patrol_investigation_binding()


async def test_background_text_intake_is_idempotent_without_live_provider():
    await _background_text_intake(inv)


async def test_gmail_manual_and_monitored_scans_share_one_cursor_lease():
    await _gmail_shared_cursor()


async def test_url_continuation_reads_retained_snapshot_without_refetch():
    await _url_snapshot_continuation()


async def test_committed_case_projects_once_into_patrol_without_model_call():
    await _committed_case_projector()


async def test_document_continuation_replay_repairs_manifest_and_delivers_images():
    await _document_continuation_replay_delivers_images()


async def test_publication_manifest_excludes_late_or_wrong_attempt_children():
    await _publication_manifest_is_attempt_isolated()


async def test_concurrent_device_results_merge_under_checkpoint_revision():
    await _concurrent_device_results_merge(inv)


async def test_upload_control_document_fences_publication_takeover():
    await _upload_control_fences_publication()


async def test_bounded_tests_prohibit_provider_calls():
    await _provider_call_guard()


async def test_ordinary_higgins_chat_creates_no_investigation_records():
    await _ordinary_chat_has_no_case_side_effect(inv)


async def test_explicit_investigation_endpoint_is_the_separate_transition():
    await _explicit_investigation_transition(inv)


async def test_higgins_context_is_owner_scoped_redacted_and_fresh_only():
    await _higgins_context_boundaries()


async def test_higgins_history_is_owner_scoped_and_redacted():
    await _higgins_history_boundaries()


def test_government_alert_parser_accepts_only_allowlisted_official_links():
    from urllib.parse import urlparse
    from services import learning_feeds
    raw = b'''<?xml version="1.0"?><rss><channel>
    <item><title>Official warning</title><link>https://www.cyber.gov.au/warning</link><guid>one</guid><pubDate>Mon, 21 Sep 2026 01:00:00 GMT</pubDate></item>
    <item><title>Not government</title><link>https://news.example/warning</link><guid>two</guid></item>
    </channel></rss>'''
    items = learning_feeds._xml_items(raw)
    accepted = [item for item in items if urlparse(item["url"]).hostname in {"www.cyber.gov.au", "cyber.gov.au"}]
    assert len(accepted) == 1
    assert accepted[0]["url"] == "https://www.cyber.gov.au/warning"


@pytest.mark.asyncio
async def test_image_secret_preflight_replaced_by_ondevice_privacy_gate():
    """Package 4: _image_secret_preflight was removed; all privacy screening now happens
    on-device via ImagePrivacyGate before network transmission. The backend validates
    client-supplied sanitization assertions instead of running Gemini preflight."""
    from services.higgins import evidence as ev
    # Confirm the old function no longer exists (product decision: on-device screening only)
    assert not hasattr(ev, "_image_secret_preflight"), \
        "_image_secret_preflight should have been removed by Package 4 (on-device privacy screening)"
    # Confirm the replacement comment exists in the source
    import inspect
    source = inspect.getsource(ev)
    assert "On-device privacy screening replaces Gemini preflight" in source


async def _upload_takeover_race():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    upload_id = str(uuid.uuid4())
    stale_fence, started_at = "fence-A", now_utc() - timedelta(seconds=200)  # well past the 120s exclusivity window
    await db.investigation_uploads.insert_one({"owner_id": owner, "case_id": "case-x", "upload_id": upload_id,
        "metadata": {"declaredBytes": 1, "clientItemId": "item-1"}, "chunks": {}, "expires_at": now_utc() + timedelta(minutes=10),
        "finalisation": {"state": "ingesting", "digest": "d", "started_at": started_at, "fence": stale_fence, "evidence_id": None}})
    # Two concurrent takeover attempts against the SAME stale claim — this is the exact CAS shape `complete_upload` uses.
    fence_b, fence_c = str(uuid.uuid4()), str(uuid.uuid4())
    taken_b = await db.investigation_uploads.find_one_and_update(
        {"owner_id": owner, "upload_id": upload_id, "finalisation.state": "ingesting", "finalisation.fence": stale_fence, "finalisation.started_at": started_at},
        {"$set": {"finalisation.fence": fence_b, "finalisation.started_at": now_utc()}})
    taken_c = await db.investigation_uploads.find_one_and_update(
        {"owner_id": owner, "upload_id": upload_id, "finalisation.state": "ingesting", "finalisation.fence": stale_fence, "finalisation.started_at": started_at},
        {"$set": {"finalisation.fence": fence_c, "finalisation.started_at": now_utc()}})
    assert taken_b is not None and taken_c is None  # only the first CAS wins; the second never matches the (already moved) stale value
    # The superseded (original) fence can never commit again, even though it "started ingesting" first.
    stale_commit = await db.investigation_uploads.find_one_and_update(
        {"owner_id": owner, "upload_id": upload_id, "finalisation.fence": stale_fence},
        {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": "wrong-item"}})
    assert stale_commit is None
    current = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
    assert current["finalisation"]["fence"] == fence_b and current["finalisation"]["state"] == "ingesting"
    # The winner's own commit, fenced on its own (current) fence, succeeds.
    won_commit = await db.investigation_uploads.find_one_and_update(
        {"owner_id": owner, "upload_id": upload_id, "finalisation.fence": fence_b},
        {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": "right-item", "evidence_id": "right-item"}})
    assert won_commit is not None


async def _device_submission_stage_race(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    request_id = str(uuid.uuid4())
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": "case-x", "request_id": request_id, "job_id": "job-x",
        "request": {"capabilityId": "cap.x", "fields": []}, "fulfilled": False,
        "submission": {"state": "claimed", "digest": "d1", "result_ciphertext": repo.enc_json({}), "evidence_id": None, "claimed_at": now_utc(), "fence": "f0"}})
    fence1 = await inv._claim_submission_stage(owner, "case-x", request_id, "claimed", "storing")
    assert fence1
    # A second attempt can neither claim "storing" from "claimed" (state already moved) nor take over immediately (not stale).
    fence2 = await inv._claim_submission_stage(owner, "case-x", request_id, "claimed", "storing")
    assert fence2 is None
    # Force the in-flight claim stale, then confirm a fresh attempt takes over with a NEW fence.
    await db.investigation_device_requests.update_one({"owner_id": owner, "request_id": request_id},
                                                       {"$set": {"submission.stage_started_at": now_utc() - timedelta(seconds=200)}})
    fence3 = await inv._claim_submission_stage(owner, "case-x", request_id, "claimed", "storing")
    assert fence3 and fence3 != fence1
    # The original (superseded) fence can never commit the stage again.
    stale_commit = await db.investigation_device_requests.find_one_and_update(
        {"owner_id": owner, "case_id": "case-x", "request_id": request_id, "submission.fence": fence1},
        {"$set": {"submission.state": "stored", "submission.evidence_id": "wrong-item"}})
    assert stale_commit is None
    won_commit = await db.investigation_device_requests.find_one_and_update(
        {"owner_id": owner, "case_id": "case-x", "request_id": request_id, "submission.fence": fence3},
        {"$set": {"submission.state": "stored", "submission.evidence_id": "right-item"}})
    assert won_commit is not None


async def _device_submission_happy_path(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("k2"), repo.digest("p2"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "waiting_device"}})
    request_id = str(uuid.uuid4())
    result = DeviceResult(request_id=request_id, case_revision=1, capability_id="cap.x", status="observed", values={"state": True})
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
        "request": {"id": request_id, "caseId": case["case_id"], "caseRevision": 1, "capabilityId": "cap.x", "fields": [], "reason": "test",
                    "expiresAt": repo.utc(case["expires_at"]).isoformat()},
        "fulfilled": False, "submission": {"state": "claimed", "digest": "d1", "result_ciphertext": repo.enc_json(result.wire()), "evidence_id": None,
                                            "claimed_at": now_utc(), "fence": str(uuid.uuid4())}, "created_at": now_utc()})
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id}, {"_id": 0})
    original_launch = inv.jobs.launch
    inv.jobs.launch = lambda *a, **k: None  # do not actually spawn the real coordinator/Gemini run from a unit test
    try:
        item_id = await inv._finish_device_submission(owner, case, pending)
    finally:
        inv.jobs.launch = original_launch
    assert item_id
    fresh_job = await repo.get_job(owner, case["case_id"], job["job_id"])
    assert fresh_job["status"] == "queued"
    checkpoint = repo.dec_json(fresh_job["checkpoint_ciphertext"])
    assert any(r["evidenceId"] == item_id for r in checkpoint["deviceResults"])
    final = await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0})
    assert final["submission"]["state"] == "resumed" and final["fulfilled"] is True
    # Idempotent replay from the sweeper/a retry after full completion returns the same evidence, no double work.
    again = await inv._finish_device_submission(owner, case, final)
    assert again == item_id


async def _backfill_work_epochs():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    job = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("k3"), repo.digest("p3"), "turn", {})
    # Simulate pre-migration documents: `work_epoch` never existed.
    await db.investigation_cases.update_one({"case_id": case["case_id"]}, {"$unset": {"work_epoch": ""}})
    await db.investigation_jobs.update_one({"job_id": job["job_id"]}, {"$unset": {"work_epoch": ""}})
    stale_case = await db.investigation_cases.find_one({"case_id": case["case_id"]}, {"_id": 0})
    assert "work_epoch" not in stale_case
    await repo.backfill_work_epochs()
    fixed_case = await db.investigation_cases.find_one({"case_id": case["case_id"]}, {"_id": 0})
    fixed_job = await db.investigation_jobs.find_one({"job_id": job["job_id"]}, {"_id": 0})
    assert fixed_case["work_epoch"] == fixed_case["epoch"]
    assert fixed_job["work_epoch"] == fixed_job["epoch"]
    assert fixed_case["status"] == case["status"] and fixed_job["status"] == job["status"]  # nothing revived, only the field was set
    # Idempotent and harmless on a case that was already migrated (or a cancelled one): running it again changes nothing.
    await db.investigation_cases.update_one({"case_id": case["case_id"]}, {"$set": {"status": "cancelled"}})
    await repo.backfill_work_epochs()
    untouched = await db.investigation_cases.find_one({"case_id": case["case_id"]}, {"_id": 0})
    assert untouched["status"] == "cancelled" and untouched["work_epoch"] == fixed_case["work_epoch"]


async def _scanned_pdf_no_crash():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    from services.higgins import evidence as ev
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)  # no text layer at all -> "unreadable"/scanned page
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    item = await ev.ingest_file(owner, case, {"clientItemId": "doc-1", "mediaType": "application/pdf", "kind": "document", "filename": "scan.pdf"}, data)
    row = await repo.get_evidence(owner, case["case_id"], item.id)
    # Before the fix, rendering a scanned page raised a NameError (undefined `expires`), silently caught by the
    # broad handler and downgraded to "parser failed; content not examined" — this asserts that no longer happens.
    assert row["coverage"]["status"] != "unavailable"
    assert row["coverage"].get("reason") != "parser failed; content not examined"
    children = await db.investigation_evidence.find({"owner_id": owner, "case_id": case["case_id"], "parent_id": item.id}, {"_id": 0}).to_list(None)
    assert any(c["kind"] == "image" for c in children)  # the scanned page was rasterised and stored as its own evidence


async def _coverage_aggregation_across_children():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    from services.higgins import evidence as ev
    from services.higgins.contracts import EvidenceItem, Coverage
    expires = repo.utc(case["expires_at"])
    # A 2-page PDF: page 1 has a text layer, page 2 is scanned (rendered as its own image child) — mirrors _derive's shape.
    parent = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id="doc-1", origin="user_submission", kind="document",
                          parent_id=None, collected_at=now_utc(), expires_at=expires, media_type="application/pdf", byte_length=100,
                          coverage=Coverage(status="partial", unit="pages", total=2, examined=0), transformations=[], label="doc")
    attempt_id = uuid.uuid4().hex
    await repo.insert_evidence(owner, parent, {"filename": "doc.pdf"}, publication_root_id=parent.id, ingestion_attempt_id=attempt_id)
    text_child = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id="doc-1.text", origin="user_submission", kind="text",
                              parent_id=parent.id, collected_at=now_utc(), expires_at=expires, media_type="text/plain", byte_length=20,
                              coverage=Coverage(status="not_started", unit="characters", total=20, examined=0), transformations=[], label="text")
    await repo.insert_evidence(owner, text_child, {"pages": [{"page": 1, "start": 0, "end": 10, "readable": True}, {"page": 2, "start": 10, "end": 20, "readable": False}]},
                               publication_root_id=parent.id, ingestion_attempt_id=attempt_id)
    await repo.store_bytes(owner, case["case_id"], text_child.id, b"page one text.......", expires, publish_root=False)
    image_child = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id="doc-1.page2", origin="user_submission", kind="image",
                               parent_id=parent.id, collected_at=now_utc(), expires_at=expires, media_type="image/png", byte_length=5,
                               coverage=Coverage(status="not_started", unit="items", total=1, examined=0), transformations=[], label="page 2 image")
    await repo.insert_evidence(owner, image_child, {"page": 2, "derivedFrom": parent.id}, publication_root_id=parent.id, ingestion_attempt_id=attempt_id)
    await repo.store_bytes(owner, case["case_id"], image_child.id, b"PNG!!", expires, publish_root=False)
    assert await repo.publish_evidence_root(owner, case["case_id"], parent.id, attempt_id)

    # Reading the rendered page-2 image FIRST must not, by itself, mark the WHOLE parent PDF "examined" — page 1 is still unread.
    await ev.mark_examined(owner, case["case_id"], image_child.id, 0, 5, 5)
    parent_row = await repo.get_evidence(owner, case["case_id"], parent.id)
    assert parent_row["coverage"]["status"] == "partial" and parent_row["coverage"]["examined"] == 1

    # Reading page-2's EMPTY extracted-text span (it has no text layer) must not double-count or fabricate examination of page 2.
    await ev.mark_examined(owner, case["case_id"], text_child.id, 10, 20, 20)
    parent_row = await repo.get_evidence(owner, case["case_id"], parent.id)
    assert parent_row["coverage"]["examined"] == 1

    # Reading page-1's readable text completes the document (both of its pages are now genuinely covered).
    await ev.mark_examined(owner, case["case_id"], text_child.id, 0, 10, 20)
    parent_row = await repo.get_evidence(owner, case["case_id"], parent.id)
    assert parent_row["coverage"]["examined"] == 2 and parent_row["coverage"]["status"] == "examined" and parent_row["coverage"]["materialGap"] is False


async def _truncated_text_never_reaches_examined():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    from services.higgins import evidence as ev
    from services.higgins.contracts import EvidenceItem, Coverage
    expires = repo.utc(case["expires_at"])
    item = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id="shot-1.redacted", origin="apollo_inference", kind="text",
                        parent_id=None, collected_at=now_utc(), expires_at=expires, media_type="text/plain", byte_length=60000,
                        coverage=Coverage(status="not_started", unit="characters", total=60000, examined=0, material_gap=True, permanent_gap=True,
                                          reason="the transcription exceeded the 60,000-character processing budget and was truncated"),
                        transformations=[], label="redacted transcription")
    await repo.insert_evidence(owner, item, {})
    await repo.store_bytes(owner, case["case_id"], item.id, b"A" * 60000, expires)
    await ev.mark_examined(owner, case["case_id"], item.id, 0, 60000, 60000)  # the model reads EVERYTHING that was actually retained
    row = await repo.get_evidence(owner, case["case_id"], item.id)
    assert row["coverage"]["status"] == "partial"  # never "examined" — the untruncated remainder was never retained to read
    assert row["coverage"]["materialGap"] is True


async def _device_submission_resumes_from_storing(inv):
    """Simulates the sweeper picking up a claim that crashed mid-"storing" (never reached the "stored" commit)."""
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("k4"), repo.digest("p4"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "waiting_device"}})
    request_id = str(uuid.uuid4())
    result = DeviceResult(request_id=request_id, case_revision=1, capability_id="cap.x", status="observed", values={"state": True})
    stale_started = now_utc() - timedelta(seconds=200)
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
        "request": {"id": request_id, "caseId": case["case_id"], "caseRevision": 1, "capabilityId": "cap.x", "fields": [], "reason": "test",
                    "expiresAt": repo.utc(case["expires_at"]).isoformat()},
        "fulfilled": False, "submission": {"state": "storing", "digest": "d1", "result_ciphertext": repo.enc_json(result.wire()), "evidence_id": None,
                                            "claimed_at": stale_started, "fence": "crashed-fence", "stage_started_at": stale_started}, "created_at": now_utc()})
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id}, {"_id": 0})
    assert pending["submission"]["state"] == "storing"  # this is what the sweeper's query would hand to _finish_device_submission
    original_launch = inv.jobs.launch
    inv.jobs.launch = lambda *a, **k: None  # do not actually spawn the real coordinator/Gemini run from a unit test
    try:
        item_id = await inv._finish_device_submission(owner, case, pending)
    finally:
        inv.jobs.launch = original_launch
    assert item_id  # the crashed claim was taken over and completed, not silently ignored
    final = await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0})
    assert final["submission"]["state"] == "resumed" and final["fulfilled"] is True


async def _partial_then_complete_read_reaches_examined():
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    from services.higgins import evidence as ev
    from services.higgins.contracts import EvidenceItem, Coverage
    expires = repo.utc(case["expires_at"])
    item = EvidenceItem(id=str(uuid.uuid4()), case_id=case["case_id"], client_item_id="note-1", origin="user_submission", kind="text",
                        parent_id=None, collected_at=now_utc(), expires_at=expires, media_type="text/plain", byte_length=5000,
                        coverage=Coverage(status="not_started", unit="characters", total=5000, examined=0), transformations=[], label="note")
    await repo.insert_evidence(owner, item, {})
    await repo.store_bytes(owner, case["case_id"], item.id, b"B" * 5000, expires)
    # An ordinary, genuinely in-progress partial read (no ingestion-time gap at all).
    await ev.mark_examined(owner, case["case_id"], item.id, 0, 2000, 5000)
    row = await repo.get_evidence(owner, case["case_id"], item.id)
    assert row["coverage"]["status"] == "partial" and row["coverage"]["materialGap"] is True  # correctly not yet fully read
    # Reading the remainder must complete it — an ordinary in-progress read is NOT a permanent gap and must resolve.
    await ev.mark_examined(owner, case["case_id"], item.id, 2000, 5000, 5000)
    row = await repo.get_evidence(owner, case["case_id"], item.id)
    assert row["coverage"]["status"] == "examined" and row["coverage"]["materialGap"] is False


def _request(owner: str):
    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.device = {"device_id": owner}
    return request


async def _upload_replay_digest_mismatch_is_rejected(inv):
    from fastapi import HTTPException
    from services.higgins.contracts import CreateUpload

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    first = CreateUpload(expected_revision=0, client_item_id="shared-item", parent_id=None, kind="document", filename="a.txt", media_type="text/plain", declared_bytes=3)
    await inv.create_upload(case["case_id"], first, _request(owner))
    changed = CreateUpload(expected_revision=0, client_item_id="shared-item", parent_id=None, kind="document", filename="b.txt", media_type="text/plain", declared_bytes=4)
    with pytest.raises(HTTPException) as exc:
        await inv.create_upload(case["case_id"], changed, _request(owner))
    assert exc.value.status_code == 409
    assert await db.investigation_uploads.count_documents({"owner_id": owner, "case_id": case["case_id"], "metadata.clientItemId": "shared-item"}) == 1


async def _upload_replay_digest_match_binds(inv):
    from services.higgins.contracts import CreateUpload

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    first = CreateUpload(expected_revision=0, client_item_id="shared-item-2", parent_id=None, kind="document", filename="a.txt", media_type="text/plain", declared_bytes=3)
    one = json.loads((await inv.create_upload(case["case_id"], first, _request(owner))).body)
    replay = first.model_copy(update={"expected_revision": 999})
    two = json.loads((await inv.create_upload(case["case_id"], replay, _request(owner))).body)
    assert two["replayed"] is True
    assert two["uploadId"] == one["uploadId"] and two["evidenceRootId"] == one["evidenceRootId"]


async def _device_observation_missing_content_is_reingested(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("k5"), repo.digest("p5"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "waiting_device"}})
    request_id = str(uuid.uuid4())
    # A metadata-only evidence row: mimics a crash between repo.insert_evidence and repo.store_bytes — no content chunk exists.
    orphan_id = str(uuid.uuid4())
    from services.higgins.contracts import EvidenceItem, Coverage
    orphan = EvidenceItem(id=orphan_id, case_id=case["case_id"], client_item_id=f"observation-{request_id}", origin="device_observation", kind="observation",
                          parent_id=None, collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="text/plain", byte_length=10,
                          coverage=Coverage(status="not_started", unit="characters", total=10, examined=0), transformations=[], label="observation")
    await repo.insert_evidence(owner, orphan, {})
    result = DeviceResult(request_id=request_id, case_revision=1, capability_id="cap.x", status="observed", values={"state": True})
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
        "request": {"id": request_id, "caseId": case["case_id"], "caseRevision": 1, "capabilityId": "cap.x", "fields": [], "reason": "test",
                    "expiresAt": repo.utc(case["expires_at"]).isoformat()},
        "fulfilled": False, "submission": {"state": "claimed", "digest": "d1", "result_ciphertext": repo.enc_json(result.wire()), "evidence_id": None,
                                            "claimed_at": now_utc(), "fence": str(uuid.uuid4())}, "created_at": now_utc()})
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id}, {"_id": 0})
    original_launch = inv.jobs.launch
    inv.jobs.launch = lambda *a, **k: None
    try:
        item_id = await inv._finish_device_submission(owner, case, pending)
    finally:
        inv.jobs.launch = original_launch
    assert item_id and item_id != orphan_id  # the content-less orphan was discarded, never reused as "already ingested"
    assert await db.investigation_evidence.find_one({"owner_id": owner, "case_id": case["case_id"], "evidence_id": orphan_id}) is None
    fresh_row = await db.investigation_content_chunks.find_one({"owner_id": owner, "case_id": case["case_id"], "evidence_id": item_id})
    assert fresh_row is not None  # the replacement evidence has actual durable content


async def _lease_renewal_detects_loss(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    selector = {"owner_id": owner, "case_id": "case-x", "request_id": "req-x"}
    fence = "fence-1"
    await db.investigation_device_requests.insert_one({**selector, "job_id": "job-x", "request": {}, "fulfilled": False,
                                                       "submission": {"state": "storing", "fence": fence, "stage_started_at": now_utc()}})
    original_interval = inv.LEASE_RENEWAL_SECONDS
    inv.LEASE_RENEWAL_SECONDS = 0.05  # fast heartbeat for the test
    started, stopped = asyncio.Event(), asyncio.Event()

    async def _long_running_work():
        started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            stopped.set()
            raise
    try:
        work = inv._with_lease_renewal(db.investigation_device_requests, selector, "submission.fence", fence, "submission.stage_started_at", _long_running_work())
        task = asyncio.ensure_future(work)
        await started.wait()
        await asyncio.sleep(0.02)
        # Steal the fence from underneath the in-flight work — simulating a takeover by another attempt.
        await db.investigation_device_requests.update_one(selector, {"$set": {"submission.fence": "fence-2"}})
        with pytest.raises(inv.LeaseLost):
            await task
        assert stopped.is_set()  # the wrapped work was actually cancelled, not left running after ownership was lost
    finally:
        inv.LEASE_RENEWAL_SECONDS = original_interval


async def _device_submission_waits_for_authoritative_consumption(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "device", None)
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("consume-key"), repo.digest("consume-payload"), "turn", {"message": "q", "turnId": turn_id})
    request_id = str(uuid.uuid4())
    await db.investigation_jobs.update_one({"job_id": job["job_id"]}, {"$set": {"status": "waiting_device", "lease_until": now_utc() + timedelta(seconds=60)}})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id,
                                                                                  "status": "waiting_device", "pending_device_request_ids": [request_id]}})
    result = DeviceResult(request_id=request_id, case_revision=1, capability_id="cap.x", status="observed", values={"state": True})
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
        "request": {"id": request_id, "caseId": case["case_id"], "caseRevision": 1, "capabilityId": "cap.x", "fields": [], "reason": "test",
                    "expiresAt": repo.utc(case["expires_at"]).isoformat()}, "fulfilled": False,
        "submission": {"state": "claimed", "digest": "d1", "result_ciphertext": repo.enc_json(result.wire()), "evidence_id": None,
                       "claimed_at": now_utc(), "fence": str(uuid.uuid4())}, "created_at": now_utc()})
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0})
    item_id = await inv._finish_device_submission(owner, await repo.get_case(owner, case["case_id"]), pending)
    assert item_id
    final = await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0})
    assert final["submission"]["state"] == "stored"
    assert final["fulfilled"] is False
    fresh_job = await repo.get_job(owner, case["case_id"], job["job_id"])
    assert request_id not in fresh_job.get("consumed_device_request_ids", [])


async def _evidence_publication_is_atomic():
    from services.higgins.contracts import EvidenceItem, Coverage
    from fastapi import HTTPException

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    root_id, attempt_id = str(uuid.uuid4()), uuid.uuid4().hex
    item = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="atomic-file", origin="user_submission", kind="document",
                        parent_id=None, collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="application/pdf", byte_length=4,
                        coverage=Coverage(status="not_started", unit="bytes", total=4), transformations=[], label="document")
    await repo.insert_evidence(owner, item, {}, publication_root_id=root_id, ingestion_attempt_id=attempt_id)
    await repo.store_bytes(owner, case["case_id"], root_id, b"data", item.expires_at, publish_root=False)
    assert await repo.list_evidence(owner, case["case_id"]) == []
    with pytest.raises(HTTPException) as exc:
        await repo.get_evidence(owner, case["case_id"], root_id)
    assert exc.value.status_code == 409
    assert await repo.publish_evidence_root(owner, case["case_id"], root_id, attempt_id)
    assert [row["evidence_id"] for row in await repo.list_evidence(owner, case["case_id"])] == [root_id]


async def _device_request_identity_is_durable():
    from services.higgins import tools

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "device", {"platform": "android", "capabilityIds": ["cap.x"]})
    job = {"job_id": str(uuid.uuid4())}
    first = tools.ToolContext(owner, case, job, {"platform": "android", "capabilityIds": ["cap.x"]})
    first.tool_call_key = "1:0:request_device_observation:abc"
    result_one = await tools.request_device_observation(first, {"capabilityId": "cap.x", "fields": ["state"], "reason": "test"})
    replay = tools.ToolContext(owner, case, job, {"platform": "android", "capabilityIds": ["cap.x"]})
    replay.tool_call_key = first.tool_call_key
    result_two = await tools.request_device_observation(replay, {"capabilityId": "cap.x", "fields": ["state"], "reason": "test"})
    assert result_one["requestId"] == result_two["requestId"]
    assert await db.investigation_device_requests.count_documents({"owner_id": owner, "job_id": job["job_id"]}) == 1


async def _legacy_content_discard_is_one_time():
    from services.higgins.retention import _discard_legacy_content_once, migrate_and_index

    migration_id = f"test-retention-{uuid.uuid4().hex}"
    owner = f"retention-{uuid.uuid4().hex}"
    await db.ask_messages.insert_one({"device_id": owner, "scope_id": "before", "content_version": 0})
    await migrate_and_index()
    assert await db.ask_messages.count_documents({"device_id": owner}) == 1
    assert await _discard_legacy_content_once(migration_id) is True
    assert await db.ask_messages.count_documents({"device_id": owner}) == 0
    await db.ask_messages.insert_one({"device_id": owner, "scope_id": "after", "content_version": 0})
    assert await _discard_legacy_content_once(migration_id) is False
    assert await db.ask_messages.count_documents({"device_id": owner, "scope_id": "after"}) == 1
    await db.ask_messages.delete_many({"device_id": owner})


async def _published_root_survives_discard():
    from services.higgins.contracts import Coverage, EvidenceItem

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    root_id, attempt_id = str(uuid.uuid4()), uuid.uuid4().hex
    item = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="immutable-file", origin="user_submission", kind="document",
                        parent_id=None, collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="text/plain", byte_length=4,
                        coverage=Coverage(status="not_started", unit="bytes", total=4), transformations=[], label="document")
    await repo.insert_evidence(owner, item, {"contentDigest": "same"}, publication_root_id=root_id, ingestion_attempt_id=attempt_id)
    await repo.store_bytes(owner, case["case_id"], root_id, b"data", item.expires_at, publish_root=False)
    assert await repo.publish_evidence_root(owner, case["case_id"], root_id, attempt_id)
    assert await repo.discard_incomplete_ingestion(owner, case["case_id"], root_id, attempt_id=attempt_id) is False
    assert (await repo.get_evidence(owner, case["case_id"], root_id))["publication_state"] == "committed"


async def _published_root_repairs_upload_projection(inv):
    from services.higgins import evidence as ev
    from services.higgins.contracts import CreateUpload, ExpectedRevision
    from services.higgins.encryption import encrypt

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    body = CreateUpload(expected_revision=0, client_item_id="projection-replay", parent_id=None, kind="document",
                        filename="proof.txt", media_type="text/plain", declared_bytes=3)
    created = json.loads((await inv.create_upload(case["case_id"], body, _request(owner))).body)
    root_id, upload_id = created["evidenceRootId"], created["uploadId"]
    data = b"abc"; digest = __import__("hashlib").sha256(data).hexdigest()
    await ev.ingest_file(owner, case, body.wire(), data, evidence_root_id=root_id, ingestion_attempt_id="published-before-projection", content_digest=digest)
    await db.investigation_upload_chunks.insert_one({"owner_id": owner, "case_id": case["case_id"], "upload_id": upload_id,
        "chunk_index": 0, "digest": repo.digest(data.hex()), "ciphertext": encrypt(data), "length": len(data), "expires_at": repo.utc(case["expires_at"])})
    response = await inv.complete_upload(case["case_id"], upload_id, ExpectedRevision(expected_revision=0), _request(owner))
    payload = json.loads(response.body)
    assert payload["replayed"] is True and payload["evidence"]["id"] == root_id
    upload = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
    assert upload["evidence_id"] == root_id and upload["finalisation"]["state"] == "committed"


async def _stale_cancel_preserves_new_turn(inv):
    from fastapi import HTTPException
    from services.higgins.contracts import ExpectedRevision

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    first = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("cancel-1"), repo.digest("p1"), "turn", {"message": "first"})
    second = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("cancel-2"), repo.digest("p2"), "turn", {"message": "second"})
    active = await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": second["job_id"], "active_turn_id": second["turn_id"], "status": "queued"}})
    superseded = await inv.cancel_job(case["case_id"], first["job_id"], ExpectedRevision(expected_revision=active["revision"]), _request(owner))
    assert json.loads(superseded.body)["outcome"] == "superseded"
    fresh_case = await repo.get_case(owner, case["case_id"])
    assert fresh_case["active_job_id"] == second["job_id"]
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": first["job_id"]}, {"$set": {"status": "completed"}})
    response = await inv.cancel_job(case["case_id"], first["job_id"], ExpectedRevision(expected_revision=fresh_case["revision"]), _request(owner))
    payload = json.loads(response.body)
    assert payload["status"] == "completed" and payload["outcome"] == "completed" and payload["cancelled"] is False


async def _duplicate_cancel(inv):
    from services.higgins.contracts import ExpectedRevision
    owner = f"cancel-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "text", None)
    job = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("cancel-key"), repo.digest("cancel-payload"), "turn", {"message": "q"})
    case = await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": job["turn_id"], "status": "queued"}})
    first = json.loads((await inv.cancel_job(case["case_id"], job["job_id"], ExpectedRevision(expectedRevision=case["revision"]), _request(owner))).body)
    second = json.loads((await inv.cancel_job(case["case_id"], job["job_id"], ExpectedRevision(expectedRevision=case["revision"]), _request(owner))).body)
    assert first["cancelled"] is True and second["cancelled"] is True
    assert first["cleanupStatus"] == second["cleanupStatus"] == "complete"


async def _completion_wins_cancel(inv):
    from services.higgins.contracts import ExpectedRevision, HigginsResponse, ProviderResult, TurnCommit
    owner = f"complete-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "text", None)
    turn_id = str(uuid.uuid4()); job = await repo.create_job(owner, case, turn_id, repo.digest("complete-key"), repo.digest("complete-payload"), "turn", {"message": "q"})
    case = await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "investigating"}})
    leased = await repo.acquire_lease(owner, job["job_id"]); case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": leased["fence"]}}, bump=False)
    response = HigginsResponse(revision=1, overview="Finished first", explanationMarkdown="Answer", assessment="uncertain", attention="review",
                               findings=[], uncertainties=[], scope="submitted text", sourceIds=[], remainingEvidenceIds=[], actions=[], completion="complete")
    commit = TurnCommit(turnId=turn_id, caseId=case["case_id"], inputRevision=1, committedRevision=1, question="q", response=response,
                        provider=ProviderResult(model="pinned-test", finishReason="STOP", providerComplete=True), committedAt=now_utc())
    commit_id = await repo.stage_turn(owner, commit, leased, repo.utc(case["expires_at"])); assert await repo.accept_turn(owner, case, leased, commit, commit_id, "complete", "none", None)
    fresh = await repo.get_case(owner, case["case_id"])
    result = json.loads((await inv.cancel_job(case["case_id"], job["job_id"], ExpectedRevision(expectedRevision=fresh["revision"]), _request(owner))).body)
    assert result["cancelled"] is False and result["outcome"] == "completed" and result["responseRevision"] == 1


async def _cancelled_narration_cleanup(inv):
    owner = f"speech-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "text", None)
    job = await repo.create_job(owner, case, "speech-1-overview", repo.digest("speech-key"), repo.digest("speech"), "speech", {"section": "overview"})
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"work_epoch": uuid.uuid4().hex}})
    assert (await repo.get_job(owner, case["case_id"], job["job_id"]))["status"] in ("investigating", "cancelled", "complete")


async def _ledger_replay_restores_observation():
    from services.higgins import coordinator

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "device", {"platform": "android", "capabilityIds": ["cap.x"]})
    job = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("ledger"), repo.digest("payload"), "turn", {"message": "q"})
    request_id = str(uuid.uuid4())
    checkpoint = {"contents": [], "rounds": 1, "toolLedger": {"tool-key": {"output": {"status": "pending", "requestId": request_id}, "researchCalls": 0}},
                  "pendingBatch": [{"key": "tool-key", "name": "request_device_observation", "args": {"capabilityId": "cap.x"}}],
                  "pendingNextIndex": 0, "pendingOutputs": [], "pendingMarks": [], "deviceResults": []}
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job["job_id"]}, {"$set": {"checkpoint_ciphertext": repo.enc_json(checkpoint)}})
    request = {"id": request_id, "caseId": case["case_id"], "caseRevision": 0, "capabilityId": "cap.x", "fields": [], "reason": "test",
               "expiresAt": repo.utc(case["expires_at"]).isoformat()}
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
                                                        "request": request, "fulfilled": False, "submission": None, "created_at": now_utc()})
    async def progress(*_args):
        return None
    outcome = await coordinator.run_turn(owner, await repo.get_case(owner, case["case_id"]), await repo.get_job(owner, case["case_id"], job["job_id"]), progress)
    assert outcome.kind == "waiting_device" and outcome.request["id"] == request_id


async def _consumed_observation_repairs_inbox():
    from services.higgins import coordinator

    class ProviderReached(Exception):
        pass

    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "device", {"platform": "android", "capabilityIds": ["cap.x"]})
    job = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("consumed"), repo.digest("payload"), "turn", {"message": "q"})
    request_id = str(uuid.uuid4())
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job["job_id"]}, {"$set": {"consumed_device_request_ids": [request_id]}})
    await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
        "request": {"id": request_id}, "fulfilled": False, "submission": {"state": "stored"}, "created_at": now_utc()})
    original = coordinator.provider.generate
    async def reached(*_args, **_kwargs):
        raise ProviderReached()
    coordinator.provider.generate = reached
    async def progress(*_args):
        return None
    try:
        with pytest.raises(ProviderReached):
            await coordinator.run_turn(owner, await repo.get_case(owner, case["case_id"]), await repo.get_job(owner, case["case_id"], job["job_id"]), progress)
    finally:
        coordinator.provider.generate = original
    repaired = await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0})
    assert repaired["fulfilled"] is True and repaired["submission"]["state"] == "resumed"


async def _document_continuation_publishes_slice():
    from pypdf import PdfWriter
    from services.higgins import evidence as ev
    from services.higgins.contracts import Coverage, EvidenceItem

    buffer = io.BytesIO(); writer = PdfWriter()
    for _ in range(3): writer.add_blank_page(width=100, height=100)
    writer.add_uri(1, "https://later.example/path", [0, 0, 80, 20])
    writer.write(buffer); data = buffer.getvalue()
    owner = f"persist-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None)
    root_id = str(uuid.uuid4())
    item = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="long-pdf", origin="user_submission", kind="document",
                        parent_id=None, collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="application/pdf", byte_length=len(data),
                        coverage=Coverage(status="partial", unit="pages", total=3, omitted_ranges=[{"start": 0, "end": 3, "reason": "not extracted"}], material_gap=True),
                        transformations=[], label="PDF")
    await repo.insert_evidence(owner, item, {})
    await repo.store_bytes(owner, case["case_id"], root_id, data, item.expires_at)
    stale_id, stale_attempt = str(uuid.uuid4()), uuid.uuid4().hex
    stale = EvidenceItem(id=stale_id, case_id=case["case_id"], client_item_id="long-pdf.pages.2-3", origin="apollo_inference", kind="text", parent_id=root_id,
                         collected_at=now_utc(), expires_at=item.expires_at, media_type="text/plain", byte_length=5,
                         coverage=Coverage(status="not_started", unit="characters", total=5), transformations=[], label="interrupted slice")
    await repo.insert_evidence(owner, stale, {}, publication_root_id=stale_id, ingestion_attempt_id=stale_attempt)
    await repo.store_bytes(owner, case["case_id"], stale_id, b"stale", stale.expires_at, publish_root=False)
    result = await ev.continue_document(owner, case, root_id, 2, 2)
    assert result["startPage"] == 2 and result["endPage"] == 3 and result["replayed"] is False
    assert any("https://later.example/path" in link for link in result["links"])
    assert result["evidenceId"] != stale_id
    parent = await repo.get_evidence(owner, case["case_id"], root_id)
    assert result["evidenceId"] in parent["related_evidence_ids"]
    assert parent["coverage"]["permanentGap"] is False


async def _clue_continuation_is_replayable():
    from services.higgins import evidence as ev
    owner = f"clues-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    text = " ".join(f"https://clue-{index}.example.test/path" for index in range(ev.MAX_CLUES + 9))
    parent = await ev.ingest_text(owner, case, "many-clues", text)
    before = await repo.get_evidence(owner, case["case_id"], parent.id)
    assert before["clue_inventory"]["remaining"] == 9
    assert before["clue_inventory"]["nextCursor"] == 0
    first = await ev.continue_clues(owner, case, parent.id, 0)
    assert len(first["registered"]) == 9 and first["remaining"] == 0 and first["nextCursor"] is None
    replay = await ev.continue_clues(owner, case, parent.id, 0)
    assert replay["replayed"] is True
    assert await db.investigation_evidence.count_documents({"owner_id": owner, "case_id": case["case_id"]}) == 1 + ev.MAX_CLUES + 9


async def _structured_observation_preserves_provenance():
    from services.higgins import evidence as ev
    owner = f"observation-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "device", None)
    result = {"requestId": "request-1", "caseId": case["case_id"], "caseRevision": 4, "capabilityId": "app.identity",
              "status": "unavailable", "unavailableReason": "os_restricted", "observedAt": now_utc().isoformat(),
              "values": {"packageName": "app.example.safe", "publisher": "Example"}, "simulation": None}
    item = await ev.ingest_observation(owner, case, "observation-1", result)
    stored = json.loads((await repo.read_bytes(owner, case["case_id"], item.id)).decode())
    assert stored == result


async def _settings_confirmation_is_user_reported(inv):
    from services.higgins.contracts import DeviceProfile, SettingsPlan
    owner = f"settings-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "device", None)
    plan = SettingsPlan(id="plan-user-confirm", case_id=case["case_id"], target="Disable unknown app installation",
                        device=DeviceProfile(platform="android", manufacturer="Example", model="Phone", os_version="1", form_factor="phone", locale="en", evidence_origin="native", capability_ids=[]),
                        match="platform_only", mode="instructions", instructions=["Open Settings"], source_ids=[], execution_descriptor_id=None, expected_observation=None)
    await db.investigation_settings_plans.insert_one({"owner_id": owner, "case_id": case["case_id"], "plan_id": plan.id,
                                                       "plan_ciphertext": repo.enc_json(plan.wire()), "created_at": now_utc(), "expires_at": case["expires_at"]})
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}); request.state.device = {"device_id": owner}
    response = json.loads((await inv.confirm_settings_plan(case["case_id"], plan.id, request, True)).body)
    assert response["verification"] == "user_reported"
    stored = await db.investigation_evidence.find_one({"owner_id": owner, "case_id": case["case_id"], "evidence_id": response["evidenceId"]}, {"_id": 0})
    assert stored["origin"] == "user_submission" and stored["label"] == "user-reported settings confirmation"


async def _patrol_investigation_binding():
    from fastapi import HTTPException
    from routers import patrol
    owner, stranger = f"owner-{uuid.uuid4().hex}", f"stranger-{uuid.uuid4().hex}"
    event_id, case_id = uuid.uuid4().hex, uuid.uuid4().hex
    await db.patrol_events.insert_one({"event_id": event_id, "device_id": owner, "deleted_at": None})
    epoch = uuid.uuid4().hex
    await db.investigation_cases.insert_one({"case_id": case_id, "owner_id": owner, "deleted": False, "epoch": epoch, "work_epoch": epoch})
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}); request.state.device = {"device_id": owner}
    body = patrol.InvestigationBindingIn(case_id=case_id)
    first = await patrol.bind_event_investigation(event_id, body, request)
    second = await patrol.bind_event_investigation(event_id, body, request)
    assert first == second == {"eventId": event_id, "caseId": case_id}
    request.state.device = {"device_id": stranger}
    with pytest.raises(HTTPException) as denied:
        await patrol.bind_event_investigation(event_id, body, request)
    assert denied.value.status_code == 404


async def _background_text_intake(inv):
    owner = f"text-bg-{uuid.uuid4().hex[:8]}"
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}); request.state.device = {"device_id": owner}
    submission_id = uuid.uuid4().hex
    body = inv.BackgroundTextIn(submissionId=submission_id, sourceKey="notification:key", revisionDigest=uuid.uuid4().hex,
                                # Deterministic Triage must reach POSSIBLE THREAT (MSG-01) for a case to exist at all.
                                sender="Sender", text="Reply with the 6-digit verification code to unlock your account",
                                capturedAt=now_utc(), expiresAt=now_utc() + timedelta(minutes=15),
                                contentComplete=True, originalCharacters=62)
    launched = inv.jobs.launch; inv.jobs.launch = lambda *args, **kwargs: None
    try:
        first = json.loads((await inv.background_text_intake(body, request)).body)
        second = json.loads((await inv.background_text_intake(body, request)).body)
    finally:
        inv.jobs.launch = launched
    assert first["caseId"] == second["caseId"]
    assert await db.investigation_cases.count_documents({"owner_id": owner}) == 1
    assert await db.investigation_jobs.count_documents({"owner_id": owner}) == 1


async def _gmail_shared_cursor():
    from services import mailbox_monitor
    owner = f"gmail-{uuid.uuid4().hex[:8]}"
    await db.gmail_connections.insert_one({"device_id": owner, "monitoring_enabled": True})
    cursors, modes = [], []
    original_scan, original_submit = mailbox_monitor.gmail.scan_inbox_page, mailbox_monitor._submit_shared_case
    async def fake_scan(device_id, cursor=None, limit=15, email=None):
        cursors.append(cursor)
        return ([{"id": f"message-{len(cursors)}", "from": "sender", "subject": "subject", "body": "body", "links": []}], "next-token" if cursor is None else None)
    async def fake_submit(provider, device_id, message, mode, **kwargs):
        modes.append(mode); return True
    mailbox_monitor.gmail.scan_inbox_page, mailbox_monitor._submit_shared_case = fake_scan, fake_submit
    try:
        first = await mailbox_monitor.scan_gmail_through_shared_pipeline(owner, "manual")
        second = await mailbox_monitor.scan_gmail_through_shared_pipeline(owner, "monitored")
    finally:
        mailbox_monitor.gmail.scan_inbox_page, mailbox_monitor._submit_shared_case = original_scan, original_submit
        await db.gmail_connections.delete_one({"device_id": owner})
    assert first["accepted"] == second["accepted"] == 1
    assert cursors == [None, "next-token"] and modes == ["manual", "monitored"]


async def _url_snapshot_continuation():
    from services import webcrawl
    from services.higgins import evidence as evidence_service, tools
    owner = f"snapshot-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "link", None)
    url_item = await evidence_service.ingest_url(owner, case, "url-item", "https://example.com/page")
    ctx = tools.ToolContext(owner, case, {"job_id": "job"}, None)
    calls = {"fetch": 0}
    original_expand, original_fetch = tools.intel.expand_redirects, tools.webcrawl.fetch_page
    async def fake_expand(url): return [url]
    async def fake_fetch(url):
        calls["fetch"] += 1
        return webcrawl.CrawledPage(final_url=url, title="Stable", text="A" * 7000, coverage={"complete": True})
    tools.intel.expand_redirects, tools.webcrawl.fetch_page = fake_expand, fake_fetch
    try:
        first = await tools.inspect_url(ctx, {"urlEvidenceId": url_item.id})
        second = await tools.inspect_url(ctx, {"urlEvidenceId": url_item.id, "cursor": first["nextCursor"]})
    finally:
        tools.intel.expand_redirects, tools.webcrawl.fetch_page = original_expand, original_fetch
    assert calls["fetch"] == 1 and first["sourceSnapshotId"] == second["sourceSnapshotId"]
    assert len(first["text"]) == 4000 and len(second["text"]) == 3000


async def _committed_case_projector():
    from services import investigation_projector
    from services.higgins.contracts import HigginsResponse, ProviderResult, TurnCommit
    owner = f"project-{uuid.uuid4().hex[:8]}"; case = await repo.create_case(owner, "text", None)
    turn_id = str(uuid.uuid4()); job = await repo.create_job(owner, case, turn_id, repo.digest("key"), repo.digest("payload"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id}})
    job = await repo.acquire_lease(owner, job["job_id"]); case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": job["fence"]}}, bump=False)
    response = HigginsResponse(revision=1, overview="Background message needs review", explanationMarkdown="Explanation", assessment="uncertain", attention="review",
                               findings=[], uncertainties=[], scope="submitted message", sourceIds=[], remainingEvidenceIds=[], actions=[], completion="complete")
    commit = TurnCommit(turnId=turn_id, caseId=case["case_id"], inputRevision=1, committedRevision=1, question="q", response=response,
                        provider=ProviderResult(model="pinned-test-model", finishReason="STOP", providerComplete=True), committedAt=now_utc())
    commit_id = await repo.stage_turn(owner, commit, job, repo.utc(case["expires_at"])); assert await repo.accept_turn(owner, case, job, commit, commit_id, "complete", "none", None)
    first = await investigation_projector.project_committed_cases(); second = await investigation_projector.project_committed_cases()
    event = await db.patrol_events.find_one({"device_id": owner, "investigation_case_id": case["case_id"]}, {"_id": 0})
    assert first >= 1 and second == 0 and event and event["state"] == "growling"


async def _document_continuation_replay_delivers_images():
    from pypdf import PdfWriter
    from services.higgins import coordinator
    from services.higgins import evidence as ev
    from services.higgins.contracts import Coverage, EvidenceItem

    buffer = io.BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.write(buffer)
    data = buffer.getvalue(); owner = f"persist-{uuid.uuid4().hex[:8]}"; await repo.ensure_indexes()
    case = await repo.create_case(owner, "file", None); root_id = str(uuid.uuid4())
    item = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="visual-pdf", origin="user_submission", kind="document",
                        parent_id=None, collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="application/pdf", byte_length=len(data),
                        coverage=Coverage(status="partial", unit="pages", total=1, omitted_ranges=[{"start": 0, "end": 1, "reason": "not extracted"}], material_gap=True),
                        transformations=[], label="PDF")
    await repo.insert_evidence(owner, item, {}); await repo.store_bytes(owner, case["case_id"], root_id, data, item.expires_at)
    first = await ev.continue_document(owner, case, root_id, 1, 1)
    assert first["visualEvidenceIds"] and first["delivery"] == "committed_manifest"
    await repo.update_evidence(owner, case["case_id"], root_id, {"$set": {"related_evidence_ids": [], "coverage.omittedRanges": [{"start": 0, "end": 1, "reason": "not extracted"}]}})
    replay = await ev.continue_document(owner, case, root_id, 1, 1)
    repaired = await repo.get_evidence(owner, case["case_id"], root_id)
    assert replay["replayed"] is True and set(replay["visualEvidenceIds"]).issubset(set(repaired["related_evidence_ids"]))

    captured = {}
    original_generate = coordinator.provider.generate
    async def capture(_system, contents, **_kwargs):
        captured["contents"] = contents
        raise RuntimeError("stop after payload capture")
    coordinator.provider.generate = capture
    job = await repo.create_job(owner, case, str(uuid.uuid4()), repo.digest("visual-ledger"), repo.digest("payload"), "turn", {"message": "q"})
    checkpoint = {"contents": [], "rounds": 1, "toolLedger": {"visual-call": {"output": replay, "researchCalls": 0}},
                  "pendingBatch": [{"key": "visual-call", "name": "continue_document", "args": {"evidenceId": root_id, "startPage": 1}}],
                  "pendingMarks": [], "deviceResults": []}
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job["job_id"]}, {"$set": {"checkpoint_ciphertext": repo.enc_json(checkpoint)}})
    async def progress(*_args): return None
    try:
        with pytest.raises(RuntimeError, match="payload capture"):
            await coordinator.run_turn(owner, await repo.get_case(owner, case["case_id"]), await repo.get_job(owner, case["case_id"], job["job_id"]), progress)
    finally:
        coordinator.provider.generate = original_generate
    delivered = [part for content in captured["contents"] for part in (content.parts or []) if part.data is not None]
    assert delivered and delivered[0].data and delivered[0].mime_type


async def _publication_manifest_is_attempt_isolated():
    from fastapi import HTTPException
    from services.higgins.contracts import Coverage, EvidenceItem

    owner = f"persist-{uuid.uuid4().hex[:8]}"; await repo.ensure_indexes(); case = await repo.create_case(owner, "file", None)
    root_id, winning = str(uuid.uuid4()), uuid.uuid4().hex
    root = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="manifest-root", origin="user_submission", kind="document", parent_id=None,
                        collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="text/plain", byte_length=4,
                        coverage=Coverage(status="not_started", unit="bytes", total=4), transformations=[], label="root")
    await repo.insert_evidence(owner, root, {}, publication_root_id=root_id, ingestion_attempt_id=winning)
    await repo.store_bytes(owner, case["case_id"], root_id, b"root", root.expires_at, publish_root=False)
    assert await repo.publish_evidence_root(owner, case["case_id"], root_id, winning)
    late_id = str(uuid.uuid4())
    late = root.model_copy(update={"id": late_id, "client_item_id": "late-child", "parent_id": root_id, "label": "late"})
    await repo.insert_evidence(owner, late, {}, publication_root_id=root_id, ingestion_attempt_id="abandoned-attempt")
    await repo.store_bytes(owner, case["case_id"], late_id, b"late", late.expires_at, publish_root=False)
    assert late_id not in [row["evidence_id"] for row in await repo.list_evidence(owner, case["case_id"])]
    with pytest.raises(HTTPException) as exc:
        await repo.get_evidence(owner, case["case_id"], late_id)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        await repo.update_evidence(owner, case["case_id"], root_id, {"$set": {"label": "wrong"}}, attempt_id="abandoned-attempt")


async def _concurrent_device_results_merge(inv):
    owner = f"persist-{uuid.uuid4().hex[:8]}"; await repo.ensure_indexes(); case = await repo.create_case(owner, "device", None)
    turn_id = str(uuid.uuid4()); job = await repo.create_job(owner, case, turn_id, repo.digest("multi-device"), repo.digest("payload"), "turn", {"message": "q"})
    request_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job["job_id"]}, {"$set": {"status": "waiting_device", "lease_until": None}})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id,
        "status": "waiting_device", "pending_device_request_ids": request_ids}})
    pending_rows = []
    for index, request_id in enumerate(request_ids):
        result = DeviceResult(request_id=request_id, case_revision=1, capability_id=f"cap.{index}", status="observed", values={"index": index})
        await db.investigation_device_requests.insert_one({"owner_id": owner, "case_id": case["case_id"], "request_id": request_id, "job_id": job["job_id"],
            "request": {"id": request_id}, "fulfilled": False, "submission": {"state": "claimed", "digest": f"d{index}",
            "result_ciphertext": repo.enc_json(result.wire()), "evidence_id": None, "claimed_at": now_utc(), "fence": str(uuid.uuid4())}, "created_at": now_utc()})
        pending_rows.append(await db.investigation_device_requests.find_one({"owner_id": owner, "request_id": request_id}, {"_id": 0}))
    original_launch = inv.jobs.launch; inv.jobs.launch = lambda *_args: None
    try:
        current_case = await repo.get_case(owner, case["case_id"])
        await asyncio.gather(*[inv._finish_device_submission(owner, current_case, row) for row in pending_rows])
    finally:
        inv.jobs.launch = original_launch
    merged = await repo.get_job(owner, case["case_id"], job["job_id"])
    checkpoint = repo.dec_json(merged["checkpoint_ciphertext"])
    assert set(merged["consumed_device_request_ids"]) == set(request_ids)
    assert {result["requestId"] for result in checkpoint["deviceResults"]} == set(request_ids)


async def _upload_control_fences_publication():
    from services.higgins.contracts import Coverage, EvidenceItem

    owner = f"persist-{uuid.uuid4().hex[:8]}"; await repo.ensure_indexes(); case = await repo.create_case(owner, "file", None)
    upload_id, root_id, old_fence, new_fence = str(uuid.uuid4()), str(uuid.uuid4()), "old-fence", "new-fence"
    await db.investigation_uploads.insert_one({"owner_id": owner, "case_id": case["case_id"], "upload_id": upload_id,
        "evidence_root_id": root_id, "metadata": {"clientItemId": "controlled-root"}, "chunks": {}, "expires_at": repo.utc(case["expires_at"]),
        "finalisation": {"state": "ingesting", "fence": old_fence}})
    old = EvidenceItem(id=root_id, case_id=case["case_id"], client_item_id="controlled-root", origin="user_submission", kind="document", parent_id=None,
                       collected_at=now_utc(), expires_at=repo.utc(case["expires_at"]), media_type="text/plain", byte_length=3,
                       coverage=Coverage(status="not_started", unit="bytes", total=3), transformations=[], label="old")
    old_owner = {"upload_id": upload_id, "fence": old_fence}
    await repo.insert_evidence(owner, old, {}, publication_root_id=root_id, ingestion_attempt_id=old_fence, publication_owner=old_owner)
    await repo.store_bytes(owner, case["case_id"], root_id, b"old", old.expires_at, publish_root=False)
    await db.investigation_uploads.update_one({"owner_id": owner, "upload_id": upload_id, "finalisation.fence": old_fence},
                                               {"$set": {"finalisation.fence": new_fence}})
    assert await repo.publish_evidence_root(owner, case["case_id"], root_id, old_fence, publication_owner=old_owner) is False
    assert await repo.discard_incomplete_ingestion(owner, case["case_id"], root_id, attempt_id=old_fence, publication_owner=old_owner)
    current = old.model_copy(update={"label": "new"}); new_owner = {"upload_id": upload_id, "fence": new_fence}
    await repo.insert_evidence(owner, current, {}, publication_root_id=root_id, ingestion_attempt_id=new_fence, publication_owner=new_owner)
    await repo.store_bytes(owner, case["case_id"], root_id, b"new", current.expires_at, publish_root=False)
    assert await repo.publish_evidence_root(owner, case["case_id"], root_id, new_fence, publication_owner=new_owner)
    authority = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
    assert authority["finalisation"]["published_attempt_id"] == new_fence
    assert authority["finalisation"]["publication_manifest"] == [root_id]


async def _provider_call_guard():
    """A bounded test can never reach live Gemini: no preview handler is installed in the test
    process, and the live path refuses while APOLLO_FORBID_PROVIDER_CALLS=1 (set by conftest)."""
    from services.higgins import provider
    assert provider.get_provider_mode() == "live", "the test process installs no preview handler"
    assert os.getenv("APOLLO_FORBID_PROVIDER_CALLS") == "1"
    with pytest.raises(AssertionError, match="prohibited"):
        await provider.generate("system", "prompt", purpose="investigation")


async def _ordinary_chat_has_no_case_side_effect(_inv):
    from types import SimpleNamespace
    from routers import ask as ask_router
    from services.higgins import chat, context

    owner = f"chat-{uuid.uuid4().hex}"
    await context.ensure_indexes()
    before = {name: await db[name].count_documents({"owner_id": owner}) for name in ("investigation_cases", "investigation_jobs", "investigation_events", "investigation_evidence")}
    from services.higgins import provider
    assert not hasattr(chat, "provider"), "Ask Higgins makes no AI call"
    original = provider.generate
    async def must_not_call(*_args, **_kwargs):
        raise AssertionError("Ask Higgins must never call an AI model")
    provider.generate = must_not_call
    try:
        response = await ask_router.higgins_chat(ask_router.ChatRequest(message="What does growling mean?", conversationId="conversation-1234"), _request(owner))
    finally:
        provider.generate = original
    payload = json.loads(response.body)
    assert payload["investigativeWorkStarted"] is False
    assert {name: await db[name].count_documents({"owner_id": owner}) for name in before} == before
    assert await db.higgins_chat_messages.count_documents({"owner_id": owner}) == 2
    await db.higgins_chat_messages.delete_many({"owner_id": owner})


async def _explicit_investigation_transition(inv):
    from services.higgins.contracts import CreateCase
    owner = f"explicit-{uuid.uuid4().hex}"
    response = await inv.create_case(CreateCase(question=""), _request(owner), idempotency_key="explicit-transition-1")
    payload = json.loads(response.body)
    assert payload["case"]["id"]
    assert await db.investigation_cases.count_documents({"owner_id": owner}) == 1
    await repo.revoke(owner, payload["case"]["id"], "deleted")
    await repo.run_cleanup(owner, payload["case"]["id"])
    await db.investigation_cases.delete_many({"owner_id": owner})
    await db.investigation_idempotency.delete_many({"owner_id": owner})


async def _higgins_context_boundaries():
    from services.higgins import context
    owner, other = f"context-{uuid.uuid4().hex}", f"other-{uuid.uuid4().hex}"
    await context.ensure_indexes()
    await context.put(owner, context.ContextWrite(category="goal", provenance="user_report", summary="My password is secret123 and I want safer banking"))
    foreign = await context.put(other, context.ContextWrite(category="preference", provenance="user_preference", summary="Use a different tone"))
    stale = await context.put(owner, context.ContextWrite(category="permission", provenance="device_observation", summary="Notification permission was granted"))
    await db.higgins_context.update_one({"owner_id": owner, "context_id": stale.id}, {"$set": {"expires_at": now_utc() - timedelta(seconds=1)}})
    items = await context.current(owner)
    assert len(items) == 1
    assert "secret123" not in items[0].summary and "[redacted]" in items[0].summary
    assert all(item.id != foreign.id and item.id != stale.id for item in items)
    await db.higgins_context.delete_many({"owner_id": {"$in": [owner, other]}})


async def _higgins_history_boundaries():
    from routers import ask as ask_router
    owner, other = f"history-{uuid.uuid4().hex}", f"other-{uuid.uuid4().hex}"
    now = now_utc()
    await db.higgins_investigation_history.insert_many([
        {"owner_id": owner, "history_id": "history-owner", "case_id": "case-owner", "case_start": now, "last_update": now, "status": "completed", "gates": ["text"], "attention": "none", "conclusion": "Use code 123456 and password secret123", "deleted": False},
        {"owner_id": other, "history_id": "history-other", "case_id": "case-other", "case_start": now, "last_update": now, "status": "completed", "gates": ["email"], "attention": "none", "conclusion": "Other owner's private answer", "deleted": False},
    ])
    response = await ask_router.higgins_history(_request(owner), limit=20)
    payload = json.loads(response.body)
    assert len(payload["items"]) == 1
    assert "123456" not in payload["items"][0]["summary"] and "secret123" not in payload["items"][0]["summary"]
    assert "Other owner" not in response.body.decode()
    await db.higgins_investigation_history.delete_many({"owner_id": {"$in": [owner, other]}})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
