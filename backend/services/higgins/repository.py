"""Owner-scoped encrypted persistence for investigation cases (spec §5).

Case control record is authoritative: revision, lifecycle epoch, active job and lease fence.
All content-bearing fields are Fernet ciphertext under the dedicated investigation key.
Expiry is enforced on every read; Mongo TTL is only a backstop.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

from core.db import db, now_utc
from services import rulebook
from services.higgins.capacity import (
    LIFETIME_SECONDS, TEMPORARY_RETENTION, WORK_SECONDS,
    EVIDENCE_RETENTION_SECONDS,
)
from services.higgins.contracts import (Coverage, EvidenceItem, EvidenceProvenance, Failure, HigginsResponse, Inventory, InvestigationCase, Job,
                                        RetryAttempt, SourceReference, TurnCommit, failure_body)
from services.higgins.encryption import decrypt, encrypt

CHUNK_BYTES = 1024 * 1024
CLOCK_INDEX = "submitted_content_24h_after_finish"
CLOCKED = ("investigation_content_chunks", "investigation_upload_chunks", "investigation_uploads")  # where submitted bytes live
CONTENT = ("investigation_evidence", "investigation_content_chunks", "investigation_events", "investigation_turn_commits",
           "investigation_jobs", "investigation_device_requests", "investigation_settings_plans", "investigation_uploads", "investigation_upload_chunks",
           "magnum_di_window_calls")


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def enc_json(value: Any) -> str:
    return encrypt(json.dumps(value, default=str, ensure_ascii=False))


def dec_json(value: str) -> Any:
    return json.loads(decrypt(value).decode("utf-8"))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def http(status: int, code: str, message: str, **kw) -> HTTPException:
    return HTTPException(status, failure_body(code, message, **kw))


async def _ttl(collection, seconds: int) -> None:
    """Idempotent TTL backstop on expires_at; replaces an older definition with different options (R02: no extra hour)."""
    try:
        await collection.create_index("expires_at", expireAfterSeconds=seconds)
    except OperationFailure:
        await collection.drop_index("expires_at_1")
        await collection.create_index("expires_at", expireAfterSeconds=seconds)


async def ensure_indexes() -> None:
    await db.investigation_cases.create_index([("owner_id", 1), ("case_id", 1)], unique=True)
    await db.investigation_cases.create_index("expires_at")
    await db.investigation_cases.create_index([("cleanup_status", 1), ("expires_at", 1)])
    await db.investigation_idempotency.create_index([("owner_id", 1), ("operation", 1), ("key_digest", 1)], unique=True)
    await _ttl(db.investigation_idempotency, 0)
    await db.investigation_evidence.create_index([("owner_id", 1), ("case_id", 1), ("evidence_id", 1)], unique=True)
    await db.investigation_evidence.create_index([("owner_id", 1), ("case_id", 1), ("client_item_id", 1)], unique=True)
    await db.investigation_evidence.create_index([("owner_id", 1), ("case_id", 1), ("publication_root_id", 1)])
    await _ttl(db.investigation_evidence, 0)
    await db.investigation_content_chunks.create_index([("owner_id", 1), ("case_id", 1), ("evidence_id", 1), ("chunk_index", 1)], unique=True)
    await _ttl(db.investigation_content_chunks, 0)
    await db.investigation_jobs.create_index([("owner_id", 1), ("case_id", 1), ("idempotency_key_digest", 1)], unique=True)
    await db.investigation_jobs.create_index([("owner_id", 1), ("job_id", 1)], unique=True)
    await db.investigation_jobs.create_index([("status", 1), ("lease_until", 1)])
    await _ttl(db.investigation_jobs, 0)
    await _ttl(db.investigation_turn_commits, 0)
    await db.investigation_events.create_index([("owner_id", 1), ("job_id", 1), ("sequence", 1)], unique=True)
    await _ttl(db.investigation_events, 0)
    await db.investigation_cleanup.create_index([("owner_id", 1), ("case_id", 1), ("target_type", 1), ("target_id", 1)], unique=True)
    await db.investigation_cleanup.create_index("next_attempt_at")
    await db.investigation_device_requests.create_index([("owner_id", 1), ("case_id", 1), ("request_id", 1)], unique=True)
    await db.investigation_device_requests.create_index(
        [("owner_id", 1), ("job_id", 1), ("tool_call_key", 1)], unique=True,
        partialFilterExpression={"tool_call_key": {"$type": "string"}},
    )
    await db.investigation_settings_plans.create_index([("owner_id", 1), ("case_id", 1), ("plan_id", 1)], unique=True)
    await db.investigation_uploads.create_index([("owner_id", 1), ("case_id", 1), ("upload_id", 1)], unique=True)
    await db.investigation_uploads.create_index(
        [("owner_id", 1), ("case_id", 1), ("metadata.clientItemId", 1)], unique=True,
        partialFilterExpression={"metadata.clientItemId": {"$type": "string"}},
    )
    await _ttl(db.investigation_uploads, 0)
    await db.investigation_upload_chunks.create_index([("owner_id", 1), ("upload_id", 1), ("chunk_index", 1)], unique=True)
    await _ttl(db.investigation_upload_chunks, 0)
    await db.magnum_di_calls.create_index("correlation_id", unique=True)
    await db.magnum_di_calls.create_index("owner_id")
    for name in CLOCKED:
        # MongoDB itself removes submitted content at its `delete_by` moment, even if Apollo's sweep has stopped.
        # Content of a check still running carries no `delete_by`, so this never touches it.
        await db[name].create_index("delete_by", expireAfterSeconds=0, name=CLOCK_INDEX)
    try:
        await db.investigation_turn_commits.drop_index("owner_id_1_case_id_1_turn_id_1")
    except OperationFailure:
        pass
    await db.investigation_turn_commits.create_index([("owner_id", 1), ("case_id", 1), ("commit_id", 1)], unique=True)
    await db.higgins_investigation_history.create_index([("owner_id", 1), ("last_update", -1)])
    await db.higgins_investigation_history.create_index([("owner_id", 1), ("history_id", 1)], unique=True)


async def backfill_work_epochs() -> None:
    """One-time, idempotent reconciliation for cases/jobs created before `work_epoch` existed. The field is missing
    entirely on old documents, so the exact-match Mongo filters used throughout this module (e.g. `cas(...,
    {"work_epoch": job.get("work_epoch", job["epoch"])}, ...)`) never match them even though the Python-side fallback
    treats a missing `work_epoch` as equal to `epoch`. This sets the DB field itself to the case's/job's own current
    `epoch`, which changes no behaviour (a case/job whose `work_epoch` already equals its `epoch` is exactly the
    pre-migration invariant) and revives nothing: status, leases and history are left untouched."""
    async for case in db.investigation_cases.find({"work_epoch": {"$exists": False}, "epoch": {"$exists": True}}, {"_id": 1, "epoch": 1}):
        if not isinstance(case.get("epoch"), str):
            continue
        await db.investigation_cases.update_one({"_id": case["_id"], "work_epoch": {"$exists": False}},
                                                {"$set": {"work_epoch": case["epoch"]}})
    async for job in db.investigation_jobs.find({"work_epoch": {"$exists": False}, "epoch": {"$exists": True}}, {"_id": 1, "epoch": 1}):
        if not isinstance(job.get("epoch"), str):
            continue
        await db.investigation_jobs.update_one({"_id": job["_id"], "work_epoch": {"$exists": False}},
                                               {"$set": {"work_epoch": job["epoch"]}})


# ------------------------------------------------------------------ idempotency
async def idempotent(owner: str, operation: str, key: str, payload: str) -> tuple[Optional[dict], str]:
    """Returns (existing record or None, payload digest). Changed payload under the same key → 409."""
    key_digest, payload_digest = digest(f"{owner}:{operation}:{key}"), digest(payload)
    existing = await db.investigation_idempotency.find_one({"owner_id": owner, "operation": operation, "key_digest": key_digest}, {"_id": 0})
    if existing and existing["payload_digest"] != payload_digest:
        raise http(409, "conflict", "This Idempotency-Key was already used for a different request. Send a new key for a new submission.")
    return existing, payload_digest


async def remember(owner: str, operation: str, key: str, payload_digest: str, result: dict, expires_at: datetime) -> None:
    try:
        await db.investigation_idempotency.insert_one({"owner_id": owner, "operation": operation, "key_digest": digest(f"{owner}:{operation}:{key}"),
                                                       "payload_digest": payload_digest, "result": result, "expires_at": expires_at})
    except DuplicateKeyError:
        pass


# ------------------------------------------------------------------ lifecycle guard (R02)
async def live_epoch(owner: str, case_id: str) -> Optional[str]:
    """Current epoch of a live (not deleted/expired) case, or None. Writers call this immediately before and after awaited work."""
    doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id, "deleted": False, "expires_at": {"$gt": now_utc()},
                                                 "status": {"$nin": ["expired"]}}, {"_id": 0, "epoch": 1})
    return doc["epoch"] if doc else None


async def assert_live(owner: str, case_id: str, epoch: Optional[str] = None) -> str:
    current = await live_epoch(owner, case_id)
    if not current or (epoch and current != epoch):
        raise http(410, "evidence_expired", "This investigation was deleted, cancelled or expired before the operation finished; nothing was stored.")
    return current


# ------------------------------------------------------------------ cases
# The initiators that say outright who started a case. "user_check" is also the default for any case opened through the
# public API, so on its own it records nothing about who started it.
_ORIGIN_OF_INITIATOR = {"higgins_user_request": "user", "apollo_automatic": "apollo"}


async def create_case(owner: str, gate: Optional[str], device_profile: Optional[dict], client_submission_id: Optional[str] = None,
                      initiator: str = "user_check", origin: Optional[str] = None) -> dict:
    device_profile = device_profile or await registered_device_profile(owner)
    now = now_utc()
    doc = {"owner_id": owner, "case_id": str(uuid.uuid4()), "revision": 0, "epoch": uuid.uuid4().hex, "work_epoch": uuid.uuid4().hex, "gates": [gate] if gate else [], "status": "queued",
           "created_at": now, "updated_at": now, "expires_at": now + timedelta(seconds=LIFETIME_SECONDS),
           "retention_class": TEMPORARY_RETENTION, "active_job_id": None,
           "active_turn_id": None, "lease_fence": None, "response_ciphertext": None, "response_revision": None,
           "sources_ciphertext": enc_json([]), "device_profile_ciphertext": enc_json(device_profile) if device_profile else None,
           "pending_device_request_ids": [], "accepted_commits": [], "open_question_ciphertext": None,
           "cleanup_status": "not_due", "deleted": False, "attention": "none",
           "client_submission_id": client_submission_id,
           "initiator": initiator, "origin": origin or _ORIGIN_OF_INITIATOR.get(initiator)}
    await db.investigation_cases.insert_one(dict(doc))
    return doc


async def get_case(owner: str, case_id: str, *, for_mutation: bool = False) -> dict:
    doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0})
    if not doc:
        raise http(404, "not_found", "No investigation with that reference belongs to this device.")
    if doc["deleted"] or doc["status"] == "expired":
        raise http(410, "evidence_expired", "This investigation's server working copy has been cleaned up. The saved report may still be available on your device.")
    # Check if the case has expired by time — but never expire a case with an active job
    if utc(doc["expires_at"]) <= now_utc() and not doc.get("active_job_id"):
        await expire_case(owner, case_id)
        raise http(410, "evidence_expired", "The server working copy of this investigation has expired. The saved report may still be available on your device.")
    if for_mutation and doc["status"] in ("cancelled",):
        raise http(409, "conflict", "This investigation was cancelled. Start a new check.")
    return doc


async def cas(owner: str, case_id: str, expected: dict, update: dict, *, bump: bool = True) -> Optional[dict]:
    """Compare-and-swap on the authoritative case control record; None when the expectation no longer holds."""
    now = now_utc()
    update = {**update}
    update.setdefault("$set", {})["updated_at"] = now
    if bump:
        update["$inc"] = {**update.get("$inc", {}), "revision": 1}
    return await db.investigation_cases.find_one_and_update(
        {"owner_id": owner, "case_id": case_id, "deleted": False, "expires_at": {"$gt": now}, **expected}, update,
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)


async def inventory(owner: str, case_id: str) -> Inventory:
    counts = Inventory()
    for row in await list_evidence(owner, case_id):
        counts.total += 1
        status = row.get("coverage", {}).get("status")
        availability = row.get("availability", "available")
        if availability == "purged":
            counts.purged += 1
        elif availability == "content_expired":
            counts.content_expired += 1
        elif availability != "available" or status == "unavailable":
            counts.unavailable += 1
        elif status == "examined":
            counts.examined += 1
        elif status == "partial":
            counts.partial += 1
    return counts


async def case_view(doc: dict) -> InvestigationCase:
    response = HigginsResponse.model_validate(dec_json(doc["response_ciphertext"])) if doc.get("response_ciphertext") else None
    routing = doc.get("routing") or {}
    simulated = bool((routing.get("tc_hawkeye") or {}).get("simulated") or (routing.get("magnum") or {}).get("simulated"))
    return InvestigationCase(id=doc["case_id"], revision=doc["revision"], gates=doc["gates"], status=doc["status"], created_at=utc(doc["created_at"]),
                             updated_at=utc(doc["updated_at"]), expires_at=utc(doc["expires_at"]), response=response, active_job_id=doc.get("active_job_id"),
                             evidence_expires_at=utc(doc["evidence_expires_at"]) if doc.get("evidence_expires_at") else None,
                             retention_class=doc.get("retention_class", ""),
                             pending_device_request_ids=doc.get("pending_device_request_ids", []), inventory=await inventory(doc["owner_id"], doc["case_id"]),
                             cleanup_status=doc.get("cleanup_status", "not_due"), answered_by=routing.get("answeredBy"),
                             settled_reason=rulebook.settled_reason(doc.get("routing")) if response else None,
                             content_delete_by=utc(doc["content_delete_by"]) if doc.get("content_delete_by") else None,
                             simulated=simulated, origin=doc.get("origin"))


def device_profile(doc: dict) -> Optional[dict]:
    return dec_json(doc["device_profile_ciphertext"]) if doc.get("device_profile_ciphertext") else None


async def registered_device_profile(owner: str) -> Optional[dict]:
    """Resolve metadata for the authenticated device; never borrow another case's profile.

    Native metadata remains a client claim, not hardware attestation. The SLM
    runtime and result validation are still mandatory on every request.
    """
    device = await db.devices.find_one({"device_id": owner, "revoked_at": None}, {"_id": 0})
    if not device:
        return None
    platform = device.get("platform")
    if platform not in ("android", "ios", "windows", "macos", "web"):
        return None
    return {"platform": platform, "manufacturer": device.get("manufacturer"), "model": device.get("model"),
            "locale": device.get("locale") or "en-AU", "capabilityIds": [],
            "evidenceOrigin": "native" if device.get("adapter_mode") == platform and platform != "web" else "browser"}


# ------------------------------------------------------------------ sources (bounded list inside the case record)
async def sources(owner: str, case_id: str) -> list[dict]:
    doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "sources_ciphertext": 1})
    return dec_json(doc["sources_ciphertext"]) if doc and doc.get("sources_ciphertext") else []


async def add_sources(owner: str, case_id: str, new: list[SourceReference]) -> dict[str, str]:
    """Canonical registration: returns {proposed id: stored id}; a repeated URL keeps its first ID."""
    current = await sources(owner, case_id)
    by_url = {s["url"]: s["id"] for s in current}
    mapping = {}
    for source in new:
        if source.url in by_url:
            mapping[source.id] = by_url[source.url]
        else:
            current.append(source.wire()); by_url[source.url] = source.id; mapping[source.id] = source.id
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id, "deleted": False}, {"$set": {"sources_ciphertext": enc_json(current)}})
    return mapping


# ------------------------------------------------------------------ evidence + chunks
async def insert_evidence(
    owner: str,
    item: EvidenceItem,
    meta: dict,
    *,
    publication_root_id: Optional[str] = None,
    ingestion_attempt_id: Optional[str] = None,
    publication_owner: Optional[dict] = None,
) -> None:
    epoch = await assert_live(owner, item.case_id)
    root_id = publication_root_id or item.id
    doc = {"epoch": epoch, "owner_id": owner, "case_id": item.case_id, "evidence_id": item.id, "client_item_id": item.client_item_id,
           "display_id": item.display_id, "origin": item.origin,
           "kind": item.kind, "parent_id": item.parent_id, "related_evidence_ids": item.related_evidence_ids, "collected_at": item.collected_at,
           "observed_at": item.observed_at, "expires_at": item.expires_at, "availability": item.availability, "media_type": item.media_type,
           "byte_length": item.byte_length, "integrity_hash": item.integrity_hash,
           "provenance": item.provenance.wire() if item.provenance else None,
           "coverage": item.coverage.wire(), "simulation": item.simulation.wire() if item.simulation else None,
           "transformations": [t.wire() for t in item.transformations], "label": item.label, "meta_ciphertext": enc_json(meta),
           "publication_root_id": root_id, "publication_state": "staging", "ingestion_attempt_id": ingestion_attempt_id or root_id,
           **({"publication_owner": publication_owner} if publication_owner else {})}
    try:
        await db.investigation_evidence.insert_one(doc)
    except DuplicateKeyError as exc:
        raise http(409, "conflict", "That client item ID was already submitted to this investigation with different content.") from exc
    await settle_write(owner, item.case_id, epoch, db.investigation_evidence, {"owner_id": owner, "case_id": item.case_id, "evidence_id": item.id})


async def discard_incomplete_ingestion(owner: str, case_id: str, evidence_id: str, *, attempt_id: Optional[str] = None,
                                       publication_owner: Optional[dict] = None) -> bool:
    """Marks one exact staging attempt abandoned, then removes only that attempt. Published/competing roots survive."""
    root = await db.investigation_evidence.find_one(
        {"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id},
        {"_id": 0, "publication_root_id": 1, "ingestion_attempt_id": 1, "publication_owner": 1},
    )
    if not root:
        return False
    root_id = (root or {}).get("publication_root_id", evidence_id)
    exact_attempt = attempt_id or root.get("ingestion_attempt_id", root_id)
    owner_ref = publication_owner or root.get("publication_owner")
    if owner_ref:
        published = await db.investigation_uploads.find_one(
            {"owner_id": owner, "case_id": case_id, "upload_id": owner_ref["upload_id"],
             "finalisation.state": "committed", "finalisation.published_attempt_id": exact_attempt},
            {"_id": 0, "upload_id": 1},
        )
        if published:
            return False
    selector = {"owner_id": owner, "case_id": case_id, "evidence_id": root_id,
                "publication_state": "staging", "ingestion_attempt_id": exact_attempt}
    if publication_owner:
        selector["publication_owner"] = publication_owner
    abandoned = await db.investigation_evidence.find_one_and_update(selector, {"$set": {"publication_state": "abandoned", "abandoned_at": now_utc()}})
    if not abandoned:
        return False
    ids = [r["evidence_id"] async for r in db.investigation_evidence.find(
        {"owner_id": owner, "case_id": case_id, "publication_root_id": root_id, "ingestion_attempt_id": exact_attempt},
        {"_id": 0, "evidence_id": 1},
    )]
    await db.investigation_content_chunks.delete_many({"owner_id": owner, "case_id": case_id, "evidence_id": {"$in": ids}})
    await db.investigation_evidence.delete_many({"owner_id": owner, "case_id": case_id, "evidence_id": {"$in": ids}})
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$pull": {"evidence_ids": {"$in": ids}}})
    return True


async def publish_evidence_root(owner: str, case_id: str, root_id: str, attempt_id: str, *, publication_owner: Optional[dict] = None) -> bool:
    """Atomically publishes one completed ingestion manifest.

    Every row created by an ingestion attempt points at its root. Readers treat the entire tree as invisible until
    this single root-document transition commits, so a crash cannot expose metadata or children from an incomplete
    attempt as completed evidence.
    """
    rows = await db.investigation_evidence.find(
        {"owner_id": owner, "case_id": case_id, "publication_root_id": root_id, "ingestion_attempt_id": attempt_id},
        {"_id": 0, "evidence_id": 1},
    ).to_list(None)
    manifest = [row["evidence_id"] for row in rows]
    authority = None
    if publication_owner:
        # The upload control document is the single publication authority. Takeover changes this same fence, so an
        # old attempt cannot pass a preliminary check and publish after ownership moved.
        authority = await db.investigation_uploads.find_one_and_update(
            {"owner_id": owner, "case_id": case_id, "upload_id": publication_owner["upload_id"],
             "finalisation.state": "ingesting", "finalisation.fence": publication_owner["fence"]},
            {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": root_id,
                      "finalisation.published_attempt_id": attempt_id, "finalisation.publication_manifest": manifest,
                      "finalisation.published_at": now_utc(), "evidence_id": root_id}},
            return_document=ReturnDocument.AFTER,
        )
        if not authority:
            return False
    selector = {"owner_id": owner, "case_id": case_id, "evidence_id": root_id, "publication_state": "staging", "ingestion_attempt_id": attempt_id}
    if publication_owner:
        selector["publication_owner"] = publication_owner
    result = await db.investigation_evidence.update_one(
        selector,
        {"$set": {"publication_state": "committed", "published_attempt_id": attempt_id,
                  "publication_manifest": manifest, "published_at": now_utc()}},
    )
    # For upload-owned evidence, authority already committed atomically above. Root fields are a repairable projection.
    return authority is not None if publication_owner else result.matched_count == 1


async def _published_rows(owner: str, case_id: str) -> list[dict]:
    rows = await db.investigation_evidence.find({"owner_id": owner, "case_id": case_id}, {"_id": 0}).sort("collected_at", 1).to_list(None)
    upload_ids = {row["publication_owner"]["upload_id"] for row in rows if row.get("publication_owner")}
    uploads = await db.investigation_uploads.find(
        {"owner_id": owner, "case_id": case_id, "upload_id": {"$in": list(upload_ids)}, "finalisation.state": "committed"},
        {"_id": 0, "upload_id": 1, "finalisation.published_attempt_id": 1, "finalisation.publication_manifest": 1},
    ).to_list(None) if upload_ids else []
    authorities = {u["upload_id"]: u["finalisation"] for u in uploads}
    roots = {row["evidence_id"]: row for row in rows if row.get("publication_root_id", row["evidence_id"]) == row["evidence_id"]}
    visible: list[dict] = []
    for row in rows:
        owner_ref = row.get("publication_owner")
        if owner_ref:
            authority = authorities.get(owner_ref["upload_id"])
            if authority and row.get("ingestion_attempt_id") == authority.get("published_attempt_id") and row["evidence_id"] in authority.get("publication_manifest", []):
                visible.append(row)
            continue
        root = roots.get(row.get("publication_root_id", row["evidence_id"]))
        if not root or root.get("publication_state", "committed") != "committed":
            continue
        manifest = root.get("publication_manifest")
        winning_attempt = root.get("published_attempt_id", root.get("ingestion_attempt_id"))
        if manifest is None or (row["evidence_id"] in manifest and row.get("ingestion_attempt_id") == winning_attempt):
            visible.append(row)
    return visible


async def settle_write(owner: str, case_id: str, epoch: str, collection, selector: dict) -> None:
    """Writer-lease/tombstone protocol (S05). Every content write carries the case epoch observed BEFORE the awaited insert. After the
    insert the epoch is re-read: if the case was deleted/expired/regenerated meanwhile, the row is a late write and is removed here
    (compensation). If this process dies before compensating, `sweep_tombstones` removes any row whose epoch is not the live epoch."""
    if await live_epoch(owner, case_id) != epoch:
        await collection.delete_many(selector)
        raise http(410, "evidence_expired", "This investigation was deleted, cancelled or expired while the write was in flight; the write was rolled back.")


_TOMBSTONE_CONTENT = ("investigation_evidence", "investigation_content_chunks", "investigation_events")


async def sweep_tombstones() -> int:
    """Removes content rows whose case epoch no longer matches a live case (late writers that never compensated).

    Driven by the content that EXISTS, not by the case table. Content lives minutes, so the set of
    (owner, case, epoch) groups holding rows stays small, while deleted-case tombstones accumulate forever:
    the old scan of the 200 oldest cases re-visited the same long-deleted cases every cycle with up to 600
    round trips — instant on a local MongoDB, a 15-second timeout on every cycle against Atlas. Now: one
    grouping query per content collection, one case lookup per 200 groups, and a delete only where an
    orphan actually exists.
    """
    held: dict[tuple[str, str], dict[str, set]] = {}
    for name in _TOMBSTONE_CONTENT:
        async for group in db[name].aggregate([{"$group": {"_id": {"o": "$owner_id", "c": "$case_id", "e": "$epoch"}}}, {"$limit": 5000}]):
            key = group["_id"]
            if isinstance(key.get("o"), str) and isinstance(key.get("c"), str):
                held.setdefault((key["o"], key["c"]), {}).setdefault(name, set()).add(key.get("e"))
    if not held:
        return 0

    removed = 0
    complete = {"owner_id": {"$type": "string"}, "case_id": {"$type": "string"}, "epoch": {"$type": "string"}, "expires_at": {"$exists": True}}
    pairs = list(held)
    for start in range(0, len(pairs), 200):
        batch = pairs[start:start + 200]
        query = {"$or": [{"owner_id": owner, "case_id": case_id} for owner, case_id in batch], **complete}
        async for case in db.investigation_cases.find(query, {"_id": 0, "owner_id": 1, "case_id": 1, "epoch": 1, "deleted": 1, "expires_at": 1}):
            live = not case.get("deleted") and utc(case["expires_at"]) > now_utc()
            scope = {"owner_id": case["owner_id"], "case_id": case["case_id"]}
            for name, epochs in held[(case["owner_id"], case["case_id"])].items():
                if not live:
                    removed += (await db[name].delete_many(scope)).deleted_count
                elif name != "investigation_events" and any(e is not None and e != case["epoch"] for e in epochs):
                    removed += (await db[name].delete_many({**scope, "epoch": {"$exists": True, "$ne": case["epoch"]}})).deleted_count
    return removed


def evidence_view(row: dict) -> EvidenceItem:
    prov = row.get("provenance")
    return EvidenceItem(id=row["evidence_id"], case_id=row["case_id"], client_item_id=row["client_item_id"],
                        display_id=row.get("display_id", ""),
                        origin=row["origin"], kind=row["kind"],
                        parent_id=row.get("parent_id"), related_evidence_ids=row.get("related_evidence_ids", []), collected_at=utc(row["collected_at"]),
                        observed_at=utc(row["observed_at"]) if row.get("observed_at") else None, expires_at=utc(row["expires_at"]),
                        availability=row["availability"], media_type=row.get("media_type"), byte_length=row.get("byte_length"),
                        integrity_hash=row.get("integrity_hash"),
                        provenance=EvidenceProvenance.model_validate(prov) if prov else None,
                        coverage=Coverage.model_validate(row["coverage"]), simulation=row.get("simulation"), transformations=row.get("transformations", []),
                        label=row.get("label", ""))


async def get_evidence(owner: str, case_id: str, evidence_id: str, *, content_required: bool = True) -> dict:
    row = await db.investigation_evidence.find_one({"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id}, {"_id": 0})
    if not row:
        raise http(404, "not_found", "Unknown evidence reference for this investigation.")
    availability = row.get("availability", "available")
    expired_by_time = utc(row["expires_at"]) <= now_utc() if row.get("expires_at") else False
    if availability == "purged":
        raise http(410, "evidence_expired", "The temporary copy of that item has been deleted. Select it again to continue checking its contents.", missing=[evidence_id])
    # Auto-transition: if evidence time-expired but not yet marked, update availability
    if expired_by_time and availability not in ("content_expired", "purged"):
        await db.investigation_evidence.update_one(
            {"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id, "availability": {"$nin": ["purged", "content_expired"]}},
            {"$set": {"availability": "content_expired"}})
        row["availability"] = "content_expired"
    # If content is required (e.g. for byte serving) and it's expired, raise 410
    if content_required and row["availability"] == "content_expired":
        raise http(410, "evidence_content_expired",
                   "This evidence was automatically deleted after 24 hours to protect your privacy. "
                   "The investigation findings remain available in your saved report.",
                   missing=[evidence_id])
    # Existing publication verification
    owner_ref = row.get("publication_owner")
    if owner_ref:
        authority = await db.investigation_uploads.find_one(
            {"owner_id": owner, "case_id": case_id, "upload_id": owner_ref["upload_id"], "finalisation.state": "committed",
             "finalisation.published_attempt_id": row.get("ingestion_attempt_id"), "finalisation.publication_manifest": evidence_id},
            {"_id": 0, "upload_id": 1},
        )
        if not authority:
            raise http(409, "conflict", "This upload attempt is not the published evidence authority.")
    else:
        root_id = row.get("publication_root_id", row["evidence_id"])
        root = row if root_id == row["evidence_id"] else await db.investigation_evidence.find_one(
            {"owner_id": owner, "case_id": case_id, "evidence_id": root_id},
            {"_id": 0, "publication_state": 1, "published_attempt_id": 1, "ingestion_attempt_id": 1, "publication_manifest": 1},
        )
        manifest = root.get("publication_manifest") if root else None
        winning_attempt = root.get("published_attempt_id", root.get("ingestion_attempt_id")) if root else None
        if not root or root.get("publication_state", "committed") != "committed" or (manifest is not None and (evidence_id not in manifest or row.get("ingestion_attempt_id") != winning_attempt)):
            raise http(409, "conflict", "This evidence attempt is not in the published manifest.")
    return row


async def list_evidence(owner: str, case_id: str) -> list[dict]:
    rows = await _published_rows(owner, case_id)
    # Auto-assign display_id (E-001, E-002, ...) for evidence without one
    counter = 1
    for row in rows:
        if not row.get("display_id"):
            row["display_id"] = f"E-{counter:03d}"
        counter += 1
    return rows


async def evidence_meta(row: dict) -> dict:
    return dec_json(row["meta_ciphertext"]) if row.get("meta_ciphertext") else {}


async def update_evidence(owner: str, case_id: str, evidence_id: str, update: dict, *, attempt_id: Optional[str] = None) -> None:
    selector = {"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id}
    if attempt_id is not None:
        selector["ingestion_attempt_id"] = attempt_id
    result = await db.investigation_evidence.update_one(selector, update)
    if attempt_id is not None and result.matched_count != 1:
        raise http(409, "conflict", "This evidence ingestion attempt no longer owns the item.")


async def store_bytes(owner: str, case_id: str, evidence_id: str, data: bytes, expires_at: datetime, *, publish_root: bool = True) -> int:
    epoch = await assert_live(owner, case_id)
    count = 0
    for index in range(0, max(len(data), 1), CHUNK_BYTES):
        chunk = data[index:index + CHUNK_BYTES]
        await db.investigation_content_chunks.update_one(
            {"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id, "chunk_index": count},
            {"$set": {"ciphertext": encrypt(chunk), "length": len(chunk), "expires_at": expires_at, "epoch": epoch}}, upsert=True)
        count += 1
    if await live_epoch(owner, case_id) != epoch:  # scope ended during the write: undo, never leave publishable content
        await db.investigation_content_chunks.delete_many({"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id})
        raise http(410, "evidence_expired", "This investigation ended while content was being stored; nothing was kept.")
    if publish_root:
        row = await db.investigation_evidence.find_one(
            {"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id},
            {"_id": 0, "publication_root_id": 1, "ingestion_attempt_id": 1},
        )
        if row:
            await publish_evidence_root(
                owner,
                case_id,
                row.get("publication_root_id", evidence_id),
                row.get("ingestion_attempt_id", row.get("publication_root_id", evidence_id)),
            )
    return count


async def read_bytes(owner: str, case_id: str, evidence_id: str) -> bytes:
    # Never served once its deletion moment has passed, even in the seconds before the sweep or the database removes it.
    now = now_utc()
    rows = await db.investigation_content_chunks.find({"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id, "expires_at": {"$gt": now},
                                                       "$or": [{"delete_by": {"$exists": False}}, {"delete_by": {"$gt": now}}]},
                                                      {"_id": 0}).sort("chunk_index", 1).to_list(None)
    if not rows:
        raise http(410, "evidence_expired", "The temporary content copy is no longer available.", missing=[evidence_id])
    return b"".join(decrypt(row["ciphertext"]) for row in rows)


async def load_bytes(owner: str, case_id: str, evidence_id: str) -> bytes:
    """Parser-facing alias: loading retained bytes does not claim semantic examination."""
    await get_evidence(owner, case_id, evidence_id)
    return await read_bytes(owner, case_id, evidence_id)


async def purge_evidence_content(owner: str, case_id: str, evidence_id: str) -> None:
    await db.investigation_content_chunks.delete_many({"owner_id": owner, "case_id": case_id, "evidence_id": evidence_id})
    await update_evidence(owner, case_id, evidence_id, {"$set": {"availability": "purged"}, "$unset": {"meta_ciphertext": ""}})


# ── Server retention removal ────────────────────────────────────────────
# Completed investigations are stored on the phone that detected the case, not on the server.
# promote_to_saved(), enforce_storage_limit(), sweep_expired_reports(),
# report_storage_used(), check_storage_before_save(), migrate_legacy_retention()
# have been removed.  The server keeps temporary working data only while
# Magnum DI is active; the device confirms local commit and the server purges.

async def start_deletion_clock(owner: str, case_id: str) -> datetime:
    """The investigation has finished (answered, failed or cancelled): everything submitted for it must be gone from
    the server within 24 hours of this moment. Each finish restarts the clock from that finish."""
    deadline = now_utc() + timedelta(seconds=EVIDENCE_RETENTION_SECONDS)
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {"content_delete_by": deadline}})
    for name in CLOCKED:
        await db[name].update_many({"owner_id": owner, "case_id": case_id}, {"$set": {"delete_by": deadline}})
    # The phone's own copy is kept apart from this clock until the phone confirms it saved it (services/device_pickup.py).
    from services import device_pickup
    await device_pickup.hold(owner, case_id)
    return deadline


async def stop_deletion_clock(owner: str, case_id: str) -> None:
    """A new turn is checking again: nothing submitted is cut off while a check runs; the clock restarts when it finishes."""
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$unset": {"content_delete_by": ""}})
    for name in CLOCKED:
        await db[name].update_many({"owner_id": owner, "case_id": case_id}, {"$unset": {"delete_by": ""}})


async def sweep_evidence_content() -> int:
    """Delete submitted content (pictures, files and text) when its investigation's copy expires, and never later than
    24 hours after the investigation finished. A check still running is never cut off. Returns the items cleaned."""
    now = now_utc()
    expired_count = 0
    # Finished investigations whose 24 hours are up: the whole server copy goes (revoke + cleanup of every content row).
    async for case in db.investigation_cases.find({"content_delete_by": {"$lte": now}, "active_job_id": None, "deleted": False},
                                                  {"_id": 0, "owner_id": 1, "case_id": 1}).limit(500):
        await expire_case(case["owner_id"], case["case_id"])
        expired_count += 1
    # Evidence whose content expired with its case and isn't cleaned yet: content goes, the metadata row is kept
    async for row in db.investigation_evidence.find(
        {"expires_at": {"$lte": now}, "availability": {"$nin": ["purged", "content_expired"]}},
        {"_id": 0, "owner_id": 1, "case_id": 1, "evidence_id": 1}
    ).limit(500):
        # Delete content chunks
        await db.investigation_content_chunks.delete_many(
            {"owner_id": row["owner_id"], "case_id": row["case_id"], "evidence_id": row["evidence_id"]})
        # Mark evidence as content_expired (metadata preserved)
        await db.investigation_evidence.update_one(
            {"owner_id": row["owner_id"], "case_id": row["case_id"], "evidence_id": row["evidence_id"]},
            {"$set": {"availability": "content_expired"}, "$unset": {"meta_ciphertext": ""}})
        expired_count += 1
    return expired_count



# ------------------------------------------------------------------ jobs / events
async def create_job(owner: str, case: dict, turn_id: str, key_digest: str, payload_digest: str, kind: str, payload: dict, *, source: str = "user_initiated") -> dict:
    from services.higgins import ai_settings
    now = now_utc()
    deadline = now + timedelta(seconds=WORK_SECONDS)  # job deadline is always from now; never cut short by case expiry
    doc = {"owner_id": owner, "case_id": case["case_id"], "job_id": str(uuid.uuid4()), "turn_id": turn_id, "idempotency_key_digest": key_digest,
           "payload_digest": payload_digest, "kind": kind, "status": "queued", "attempt": 0, "created_at": now, "started_at": None, "deadline_at": deadline,
           "retry_at": None, "lease_until": None, "fence": None, "epoch": case["epoch"], "work_epoch": case.get("work_epoch", case["epoch"]), "input_revision": case["revision"], "last_sequence": 0,
           "failure": None, "payload_ciphertext": enc_json(payload), "checkpoint_ciphertext": None, "checkpoint_revision": 0,
           # Fixed for this investigation: Magnum DI and TC Hawkeye both use the model selected in ApolloSG Settings
           # when it starts, even if an admin changes the selection meanwhile.
           "provider_model": await ai_settings.investigation_model(),
           "consumed_device_request_ids": [],
           "expires_at": utc(case["expires_at"]),
           "auto_resume_count": 0,
           "retry_history": [],
           # Gemini calls this investigation has made: at most one per correlated case, never retried.
           "gemini_calls": 0,
           "source": source}
    await stop_deletion_clock(owner, case["case_id"])
    await db.investigation_jobs.insert_one(dict(doc))
    return doc


def correlation_id(case_id: str) -> str:
    return f"case-{case_id}"


async def claim_magnum_call(owner: str, case_id: str, job_id: str) -> bool:
    """The correlated case's ONE Magnum DI call, taken atomically before anything is sent (`magnum_di_calls`, unique
    per correlation id). False when the case already used it: a follow-up, retry, Resubmit, new job, recovered job or
    restart never resets it. Held apart from the case and job records, so nothing that rewrites them can reset it."""
    try:
        await db.magnum_di_calls.insert_one({"correlation_id": correlation_id(case_id), "owner_id": owner, "case_id": case_id,
                                             "job_id": job_id, "claimed_at": now_utc()})
        return True
    except DuplicateKeyError:
        return False


async def release_magnum_call(owner: str, case_id: str) -> None:
    """Only for a call the gateway refused before anything was sent (the daily spending limit): no call was made."""
    await db.magnum_di_calls.delete_one({"correlation_id": correlation_id(case_id), "owner_id": owner})


async def magnum_call_used(owner: str, case_id: str) -> bool:
    return (await legacy_magnum_call_used(owner, case_id)
            or await db.magnum_di_window_calls.count_documents({"owner_id": owner, "case_id": case_id}, limit=1) > 0)


async def legacy_magnum_call_used(owner: str, case_id: str) -> bool:
    return await db.magnum_di_calls.count_documents({"correlation_id": correlation_id(case_id), "owner_id": owner}, limit=1) > 0


async def job_is_current(owner: str, case_id: str, job: dict) -> bool:
    """Fence every external dispatch/checkpoint, including cancellation and recovery."""
    current = await db.investigation_cases.find_one({
        "owner_id": owner, "case_id": case_id, "deleted": False,
        "active_job_id": job["job_id"], "epoch": job["epoch"],
        "work_epoch": job.get("work_epoch", job["epoch"]),
        "lease_fence": job.get("fence"), "expires_at": {"$gt": now_utc()},
    }, {"_id": 1})
    live_job = await db.investigation_jobs.find_one({
        "owner_id": owner, "job_id": job["job_id"], "fence": job.get("fence"),
        "status": "investigating", "deadline_at": {"$gt": now_utc()},
    }, {"_id": 1})
    return bool(current and live_job)


async def claim_magnum_window(owner: str, case_id: str, job_id: str, index: int,
                              digest: str, *, max_windows: int = 4) -> bool:
    """Atomic, irreversible per-case/window claim. Never retry a possibly sent call.

    Uses a unique _id rather than relying on a new index migration. The legacy
    single-call claim remains reserved for the old single-call path.
    """
    if not 0 <= index < max_windows or not digest:
        return False
    job = await get_job(owner, case_id, job_id)
    if not await job_is_current(owner, case_id, job):
        return False
    try:
        await db.magnum_di_window_calls.insert_one({
            "_id": f"{correlation_id(case_id)}:window:{index}",
            "correlation_id": correlation_id(case_id), "owner_id": owner,
            "case_id": case_id, "job_id": job_id, "window_index": index,
            "digest": digest, "claimed_at": now_utc(), "status": "claimed",
            "epoch": job["epoch"], "work_epoch": job.get("work_epoch", job["epoch"]), "fence": job.get("fence"),
        })
        if not await job_is_current(owner, case_id, job):
            await db.magnum_di_window_calls.delete_one({"_id": f"{correlation_id(case_id)}:window:{index}", "fence": job.get("fence")})
            return False
        return True
    except DuplicateKeyError:
        return False


async def complete_magnum_window(owner: str, case_id: str, job_id: str, index: int,
                                 digest: str, result: dict) -> bool:
    """Checkpoint the actual provider result only for the owning claim."""
    job = await get_job(owner, case_id, job_id)
    if not await job_is_current(owner, case_id, job):
        return False
    outcome = await db.magnum_di_window_calls.update_one(
        {"_id": f"{correlation_id(case_id)}:window:{index}",
         "owner_id": owner, "job_id": job_id, "digest": digest, "status": "claimed", "fence": job.get("fence")},
        {"$set": {"status": "completed", "result_ciphertext": enc_json(result),
                  "completed_at": now_utc()}})
    if not await job_is_current(owner, case_id, job):
        # The external call already happened. Remove a late payload but retain
        # its irreversible claim, so recovery cannot send this window again.
        await db.magnum_di_window_calls.update_one(
            {"_id": f"{correlation_id(case_id)}:window:{index}", "fence": job.get("fence")},
            {"$set": {"status": "abandoned"}, "$unset": {"result_ciphertext": "", "completed_at": ""}},
        )
        return False
    return outcome.modified_count == 1


async def magnum_window_checkpoints(owner: str, case_id: str) -> list[dict]:
    """Only the current device's checkpoints; no cross-device exposure."""
    cursor = db.magnum_di_window_calls.find(
        {"owner_id": owner, "case_id": case_id}, {"_id": 0})
    return [row async for row in cursor]


async def get_job(owner: str, case_id: str, job_id: str) -> dict:
    doc = await db.investigation_jobs.find_one({"owner_id": owner, "case_id": case_id, "job_id": job_id}, {"_id": 0})
    if not doc:
        raise http(404, "not_found", "Unknown job for this investigation.")
    return doc


def job_view(doc: dict) -> Job:
    failure = Failure.model_validate(doc["failure"]) if doc.get("failure") else None
    # Merge retry_history from job document into the failure if present
    if failure and doc.get("retry_history"):
        failure.retry_history = [RetryAttempt.model_validate(rh) if isinstance(rh, dict) else rh for rh in doc["retry_history"]]
    return Job(id=doc["job_id"], case_id=doc["case_id"], turn_id=doc["turn_id"], status=doc["status"], started_at=utc(doc["started_at"]) if doc.get("started_at") else None,
               deadline_at=utc(doc["deadline_at"]), retry_at=utc(doc["retry_at"]) if doc.get("retry_at") else None, attempt=doc["attempt"],
               last_event_sequence=doc.get("last_sequence", 0), failure=failure)


async def acquire_lease(owner: str, job_id: str) -> Optional[dict]:
    """Take the job if queued/retry_wait or its lease expired. Returns the fenced job or None."""
    now = now_utc()
    fence = uuid.uuid4().hex
    return await db.investigation_jobs.find_one_and_update(
        {"owner_id": owner, "job_id": job_id, "status": {"$in": ["queued", "investigating", "retry_wait", "waiting_device"]},
         "$or": [{"lease_until": None}, {"lease_until": {"$lte": now}}], "deadline_at": {"$gt": now}},
        {"$set": {"status": "investigating", "lease_until": now + timedelta(seconds=30), "fence": fence, "started_at": now}, "$inc": {"attempt": 1}},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)


async def heartbeat(owner: str, job_id: str, fence: str) -> bool:
    result = await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job_id, "fence": fence, "status": {"$in": ["investigating", "retry_wait"]}},
                                                    {"$set": {"lease_until": now_utc() + timedelta(seconds=30)}})
    return result.matched_count == 1


async def set_job(owner: str, job_id: str, fence: Optional[str], update: dict) -> bool:
    query = {"owner_id": owner, "job_id": job_id}
    if fence:
        query["fence"] = fence
    result = await db.investigation_jobs.update_one(query, update)
    return result.matched_count == 1


async def emit(owner: str, case_id: str, job_id: str, kind: str, payload: dict, revision: int, expires_at: datetime) -> int:
    job = await db.investigation_jobs.find_one_and_update({"owner_id": owner, "job_id": job_id}, {"$inc": {"last_sequence": 1}},
                                                          projection={"last_sequence": 1}, return_document=ReturnDocument.AFTER)
    if not job:  # job removed by cleanup: nothing may be published for it
        return 0
    sequence = job["last_sequence"]
    epoch = await live_epoch(owner, case_id)
    if not epoch:  # case ended between sequence allocation and insert: publish nothing
        return 0
    await db.investigation_events.insert_one({"owner_id": owner, "case_id": case_id, "job_id": job_id, "sequence": sequence, "type": kind, "revision": revision,
                                              "epoch": epoch, "at": now_utc(), "payload_ciphertext": enc_json(payload), "expires_at": expires_at})
    if await live_epoch(owner, case_id) != epoch:  # late write after cleanup: remove it (sweep_tombstones is the backstop)
        await db.investigation_events.delete_many({"owner_id": owner, "job_id": job_id, "sequence": sequence})
        return 0
    return sequence


async def events_after(owner: str, job_id: str, after: int) -> list[dict]:
    rows = await db.investigation_events.find({"owner_id": owner, "job_id": job_id, "sequence": {"$gt": after}}, {"_id": 0}).sort("sequence", 1).to_list(None)
    return [{"sequence": r["sequence"], "jobId": r["job_id"], "caseId": r["case_id"], "revision": r["revision"], "at": utc(r["at"]).isoformat(),
             "type": r["type"], "payload": dec_json(r["payload_ciphertext"])} for r in rows]


# ------------------------------------------------------------------ authoritative turn commit (R01)
async def stage_turn(owner: str, commit: TurnCommit, job: dict, expires_at: datetime) -> str:
    """Immutable bundle per attempt: commit_id + payload digest. Never overwritten; visibility comes only from the case reference."""
    commit_id = uuid.uuid4().hex
    body = commit.wire()
    await db.investigation_turn_commits.insert_one({"owner_id": owner, "case_id": commit.case_id, "turn_id": commit.turn_id, "commit_id": commit_id,
                                                    "digest": digest(json.dumps(body, sort_keys=True, default=str)), "job_id": job["job_id"], "fence": job["fence"],
                                                    "epoch": job["epoch"], "commit_ciphertext": enc_json(body), "committed_at": commit.committed_at, "expires_at": expires_at})
    return commit_id


async def accept_turn(owner: str, case: dict, job: dict, commit: TurnCommit, commit_id: str, status: str, attention: str, open_question: Optional[dict]) -> Optional[dict]:
    """Single CAS on the case control record makes answer + history authoritative together (spec §5)."""
    if any(ref["turn_id"] == commit.turn_id for ref in case.get("accepted_commits", [])):
        await db.investigation_turn_commits.delete_one({"owner_id": owner, "case_id": case["case_id"], "commit_id": commit_id})
        return None  # logical turn already accepted by another attempt; this attempt removes only its own bundle
    updated = await cas(owner, case["case_id"], {"epoch": job["epoch"], "work_epoch": job.get("work_epoch", job["epoch"]), "active_job_id": job["job_id"], "lease_fence": job["fence"],
                                                 "accepted_commits.turn_id": {"$ne": commit.turn_id}},
                        {"$set": {"response_ciphertext": enc_json(commit.response.wire()), "response_revision": commit.committed_revision, "status": status,
                                  "active_job_id": None, "active_turn_id": None, "lease_fence": None, "attention": attention,
                                  "open_question_ciphertext": enc_json(open_question) if open_question else None},
                         "$push": {"accepted_commits": {"turn_id": commit.turn_id, "commit_id": commit_id, "job_id": job["job_id"], "revision": commit.committed_revision}}})
    if not updated:  # losing attempt removes only its own unaccepted bundle
        await db.investigation_turn_commits.delete_one({"owner_id": owner, "case_id": case["case_id"], "commit_id": commit_id})
    elif status in ("complete", "partial"):  # finished (a Magnum question still waits for the person, so it isn't)
        await start_deletion_clock(owner, case["case_id"])
        # Queue privacy-safe KB contribution — survives case deletion, retries without AI
        await _queue_kb_contribution(owner, case["case_id"], commit)
    return updated


async def accepted_commit_for(owner: str, case: dict, turn_id: str) -> Optional[dict]:
    ref = next((r for r in case.get("accepted_commits", []) if r["turn_id"] == turn_id), None)
    if not ref:
        return None
    return await db.investigation_turn_commits.find_one({"owner_id": owner, "case_id": case["case_id"], "commit_id": ref["commit_id"]}, {"_id": 0})


async def accepted_turns(owner: str, case: dict) -> list[TurnCommit]:
    ids = [r["commit_id"] for r in case.get("accepted_commits", [])]
    rows = await db.investigation_turn_commits.find({"owner_id": owner, "case_id": case["case_id"], "commit_id": {"$in": ids}, "expires_at": {"$gt": now_utc()}}, {"_id": 0}).to_list(None)
    by_id = {r["commit_id"]: r for r in rows}
    return [TurnCommit.model_validate(dec_json(by_id[i]["commit_ciphertext"])) for i in ids if i in by_id]



async def _queue_kb_contribution(owner: str, case_id: str, commit: TurnCommit) -> None:
    """Queue a privacy-safe KB contribution from a qualifying completed investigation.
    The contribution contains only the public-safe assessment, no personal evidence.
    Queued entries survive case deletion and retry failed writes without AI calls.
    
    ISOLATION: Sample Checks (origin="sample_check") are excluded — they must never
    contribute to genuine KB intelligence, threat prevalence, or consensus."""
    try:
        from services.higgins import kb_queue
        resp = commit.response
        if not resp or not resp.assessment or commit.provider.simulated or resp.completion != "complete":
            return
        # ISOLATION: Never contribute sample check evidence to real-world intelligence
        case_doc = await db.investigation_cases.find_one(
            {"case_id": case_id}, {"_id": 0, "origin": 1}
        )
        if case_doc and case_doc.get("origin") == "sample_check":
            return
        # Only contribute if the result is definitive (not inconclusive/limited)
        if resp.attention in ("ears_up",):
            return
        # Privacy-safe body: assessment + what_to_do only — no personal evidence
        body = f"Assessment: {resp.assessment}\n"
        if resp.what_to_do:
            body += f"Recommendation: {resp.what_to_do}\n"
        if resp.overview:
            body += f"Overview: {resp.overview[:500]}\n"
        await kb_queue.enqueue(
            case_id=case_id, owner_id=owner, kind="investigation_finding",
            title=f"Investigation finding: {resp.assessment[:200]}",
            body=body[:5000], publisher="Apollo investigation",
            authority_tier="apollo_investigated", jurisdiction="INTL",
        )
    except Exception:
        pass  # Non-fatal: queue will retry on next cycle


# ------------------------------------------------------------------ lifecycle: cancel / delete / expire / cleanup
async def revoke(owner: str, case_id: str, status: str, *, expected: Optional[dict] = None) -> Optional[dict]:
    """Deletion/expiry ONLY: change the content lifecycle epoch (all content rows become tombstones) and schedule cleanup.
    Cancelling a turn never calls this; cancellation rotates `work_epoch` (worker fence) and leaves submitted evidence intact."""
    doc = await db.investigation_cases.find_one_and_update({**(expected or {}), "owner_id": owner, "case_id": case_id},
        {"$set": {"status": status, "epoch": uuid.uuid4().hex, "active_job_id": None, "lease_fence": None, "cleanup_status": "pending",
                  "deleted": status == "expired" or status == "deleted", "updated_at": now_utc()},
         "$unset": {"response_ciphertext": "", "sources_ciphertext": "", "device_profile_ciphertext": "", "open_question_ciphertext": "",
                    "tc_hawkeye_ciphertext": "", "tc_flyby_ciphertext": "", "triage_provider_evidence": "", "source_metadata": ""}, "$inc": {"revision": 1}},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if doc:
        await db.investigation_jobs.update_many({"owner_id": owner, "case_id": case_id, "status": {"$in": ["queued", "investigating", "retry_wait", "waiting_device", "waiting_user"]}},
                                                {"$set": {"status": "cancelled", "lease_until": None}})
        await db.investigation_cleanup.update_one({"owner_id": owner, "case_id": case_id, "target_type": "case", "target_id": case_id},
                                                  {"$set": {"next_attempt_at": now_utc(), "attempts": 0, "state": "pending"}}, upsert=True)
    return doc


async def run_cleanup(owner: str, case_id: str) -> str:
    try:
        for name in CONTENT:
            await db[name].delete_many({"owner_id": owner, "case_id": case_id})
        await db.di_transactions.delete_many({"owner": owner, "$or": [
            {"investigation_id": case_id}, {"correlation_id": correlation_id(case_id)},
        ]})
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {"cleanup_status": "complete", "accepted_commits": [], "pending_device_request_ids": []}})
        await db.investigation_cleanup.update_one({"owner_id": owner, "case_id": case_id, "target_type": "case", "target_id": case_id}, {"$set": {"state": "complete"}})
        return "complete"
    except Exception:  # noqa: BLE001 — retried by the sweeper; never logs content
        await db.investigation_cleanup.update_one({"owner_id": owner, "case_id": case_id, "target_type": "case", "target_id": case_id},
                                                  {"$set": {"next_attempt_at": now_utc() + timedelta(seconds=60), "state": "pending"}, "$inc": {"attempts": 1}})
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {"cleanup_status": "failed"}})
        return "failed"


async def expire_case(owner: str, case_id: str) -> None:
    if await revoke(owner, case_id, "expired"):
        await run_cleanup(owner, case_id)


async def sweep() -> None:
    now = now_utc()
    # ── Phase 1: Evidence content cleanup (24 hours after the investigation finished, at the latest) ──
    await sweep_evidence_content()
    # ── Phase 2: Temporary cases past their lifetime ──
    retention_filter = {"retention_class": {"$in": [TEMPORARY_RETENTION, "apollo_15_minute_temporary"]}}
    async for doc in db.investigation_cases.find({**retention_filter, "expires_at": {"$lte": now}, "active_job_id": None, "cleanup_status": {"$in": ["not_due"]}}, {"_id": 0, "owner_id": 1, "case_id": 1}):
        await expire_case(doc["owner_id"], doc["case_id"])
    # ── Phase 3: Retry pending cleanups ──
    async for task in db.investigation_cleanup.find({"state": {"$in": ["pending", "failed"]}, "next_attempt_at": {"$lte": now}}, {"_id": 0}):
        await run_cleanup(task["owner_id"], task["case_id"])
    # ── Phase 5: Unreferenced bundles ──
    async for stale in db.investigation_turn_commits.find({"committed_at": {"$lte": now - timedelta(seconds=WORK_SECONDS)}}, {"_id": 0, "owner_id": 1, "case_id": 1, "commit_id": 1}):
        case = await db.investigation_cases.find_one({"owner_id": stale["owner_id"], "case_id": stale["case_id"], "accepted_commits.commit_id": stale["commit_id"]}, {"_id": 1})
        if not case:
            await db.investigation_turn_commits.delete_one({"owner_id": stale["owner_id"], "case_id": stale["case_id"], "commit_id": stale["commit_id"]})
    # ── Phase 6: Late-writer cleanup ──
    async for gone in db.investigation_cases.find({"deleted": True, "cleanup_status": "complete", "updated_at": {"$gte": now - timedelta(hours=1)}}, {"_id": 0, "owner_id": 1, "case_id": 1}):
        for name in CONTENT:
            await db[name].delete_many({"owner_id": gone["owner_id"], "case_id": gone["case_id"]})
