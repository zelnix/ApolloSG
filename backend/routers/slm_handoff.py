"""Opt-in Luddish advisory handoff inside the existing authenticated investigation API.

A request is created from server-owned, owner-scoped case evidence. A device
may return advisory reasoning once for that request. This path NEVER writes
investigation evidence, mutates scores or verdicts, or resumes a job.
It is deliberately disabled unless APOLLO_SLM_HANDOFF=on is set.
"""
from __future__ import annotations

import os
import uuid
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from pymongo import ReturnDocument

from core.db import db, now_utc
from services.higgins import repository as repo
from services.higgins.repository import http
from services.higgins.contracts import Wire
from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, SLMReference,
    accept_advisory_reasoning,
)

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}
CAPABILITY = "apollo.slm.advisory.v1"
ACTIVE_JOB = frozenset(("queued", "investigating"))
QUESTIONS = {
    "higgins_triage": "Identify what information is missing for investigation. Do not make a scam verdict.",
    "tc_hawkeye": "Identify contradictions, alternative explanations and specific corroboration to pursue. Do not invent facts.",
    "magnum_di": "Analyse unresolved evidence gaps and propose independent verification. Do not decide a verdict.",
    "luddish": "Draft a plain-English explanation limited to supplied material, retaining all uncertainty.",
    "higgins_escalation_assessment": "Sanity-check Hawkeye evidence: provenance, coverage, contradictions, unsupported claims and material gaps. Decide proceed_local only when the supplied evidence is sufficient; escalate only when independent deeper investigation can materially help; otherwise additional_evidence_required. Cite evidence IDs. Do not produce a scam verdict.",
    "case_finding": "Evaluate the supplied investigation evidence and produce Findings with cited reasons, not a legal verdict. Preserve source attribution and uncertainty; do not invent verification.",
}
OPERATION = {
    "higgins_triage": "investigation_readiness",
    "tc_hawkeye": "evidence_reasoning",
    "magnum_di": "evidence_reasoning",
    "luddish": "explanation",
    "case_finding": "case_finding",
    "higgins_escalation_assessment": "escalation_assessment",
}


class AdvisoryStart(Wire):
    job_id: str = Field(min_length=4, max_length=80)
    case_revision: int = Field(ge=0)
    role: str


def _enabled() -> None:
    if os.getenv("APOLLO_SLM_HANDOFF", "on").strip().lower() != "on":
        raise http(404, "not_found", "Luddish on-device pilot is not enabled.")


async def _active_case_job(owner: str, case_id: str, job_id: str, revision: int):
    case = await repo.get_case(owner, case_id, for_mutation=True)
    if case.get("revision") != revision or case.get("active_job_id") != job_id:
        raise http(409, "conflict", "The investigation has changed. Reload before requesting Luddish reasoning.")
    if case.get("status") not in ACTIVE_JOB:
        raise http(409, "conflict", "The investigation is not running.")
    job = await repo.get_job(owner, case_id, job_id)
    if job.get("status") not in ACTIVE_JOB or job.get("epoch") != case.get("epoch"):
        raise http(409, "conflict", "The investigation job is no longer active.")
    return case, job


async def _source_evidence(owner: str, case_id: str, *, include_checks: bool = False) -> list[SLMReference]:
    """Case-scoped evidence for the on-device Finding, including retained investigative results."""
    gathered = []
    total = 0
    rows = await repo.list_evidence(owner, case_id)
    # The current SLM wire format accepts text only. Never pretend that an
    # unrepresented original image/document/audio was examined by Luddish.
    unsupported = [row for row in rows
                   if row.get("origin") == "user_submission"
                   and row.get("kind") in ("image", "document", "audio", "attachment")
                   and row.get("availability") == "available"]
    if unsupported and include_checks:
        raise http(422, "unsupported_evidence",
                   "This on-device Finding cannot examine original image, document or audio evidence; a text-only Finding would be incomplete.")
    texts = {}
    for row in rows:
        readable = row.get("kind") in ("text", "url", "observation", "source_snapshot")
        investigative = row.get("origin") in ("apollo_inference", "external_source")
        if not readable or (investigative and not include_checks):
            continue
        if row.get("availability") != "available":
            continue
        text = (await repo.read_bytes(owner, case_id, row["evidence_id"])).decode("utf-8", errors="replace").strip()
        if text:
            texts[row["evidence_id"]] = text
    for row in rows:
        text = texts.get(row["evidence_id"])
        if not text:
            continue
        parent_text = texts.get(row.get("parent_id"))
        if parent_text and text in parent_text:
            continue  # Exact derived clue already present in the parent.
        total += len(text)
        if total > 120000 or len(gathered) >= 64:
            raise http(413, "budget_exhausted", "The on-device evidence limit was exceeded; nothing has been shortened or silently omitted.")
        parent = next((item for item in rows if item.get("evidence_id") == row.get("parent_id")), None)
        if parent and parent.get("kind") in ("image", "document", "audio", "attachment"):
            # This is derived text, NOT direct inspection of the parent binary.
            # Retain the source relationship in the material sent to the SLM.
            text = (f"[Derived text from {parent['kind']} evidence "
                    f"{parent['evidence_id']}; original binary not examined by SLM]\n" + text)
        gathered.append(SLMReference(evidence_id=row["evidence_id"], text=text))
    return gathered


async def issue_stage_request(owner: str, case_id: str, job_id: str, revision: int, role: str) -> dict | None:
    """Issue one optional server-authored, case-scoped advisory per job/role.

    The coordinator calls this only with the existing authenticated case owner
    and active job. No device event is published if the pilot is disabled, the
    device is not native or there is no admissible submitted evidence.
    """
    if os.getenv("APOLLO_SLM_HANDOFF", "on").strip().lower() != "on" or role not in QUESTIONS:
        return None
    case, _job = await _active_case_job(owner, case_id, job_id, revision)
    device = repo.device_profile(case) or {}
    if device.get("evidenceOrigin") != "native" or device.get("platform") not in ("android", "ios"):
        return None
    existing = await db.investigation_device_requests.find_one({
        "owner_id": owner, "case_id": case_id, "job_id": job_id,
        "kind": "slm_advisory", "role": role, "epoch": case.get("epoch"),
    }, {"_id": 0, "request_ciphertext": 1, "expires_at": 1})
    if existing:
        if repo.utc(existing["expires_at"]) <= now_utc():
            return None
        return {"request": repo.dec_json(existing["request_ciphertext"]),
                "expiresAt": repo.utc(existing["expires_at"]).isoformat()}
    evidence = await _source_evidence(owner, case_id, include_checks=(role in ("case_finding", "higgins_escalation_assessment")))
    if not evidence:
        return None
    issued = SLMReasoningRequest(
        case_id=case_id, case_revision=revision, request_id=str(uuid.uuid4()),
        role=role, operation=OPERATION[role], question=QUESTIONS[role],
        evidence=evidence,
    )
    expires = min(repo.utc(case["expires_at"]), now_utc() + timedelta(minutes=5))
    if expires <= now_utc():
        return None
    await db.investigation_device_requests.insert_one({
        "owner_id": owner, "case_id": case_id, "job_id": job_id,
        "request_id": issued.request_id, "kind": "slm_advisory", "role": role,
        "request": {"capabilityId": CAPABILITY, "expiresAt": expires.isoformat()},
        "request_ciphertext": repo.enc_json(issued.wire()),
        "expires_at": expires, "submission": None, "fulfilled": False,
        "created_at": now_utc(), "epoch": case.get("epoch"),
    })
    return {"request": issued.wire(), "expiresAt": expires.isoformat()}


@router.post("/investigations/{case_id}/slm/requests", status_code=201)
async def request_advisory(case_id: str, body: AdvisoryStart, request: Request):
    """Manual pilot request, using the same server-owned stage issuer."""
    _enabled()
    owner = request.state.device["device_id"]
    if body.role not in QUESTIONS:
        raise http(422, "invalid_input", "Unsupported Luddish reasoning role.")
    issued = await issue_stage_request(owner, case_id, body.job_id, body.case_revision, body.role)
    if not issued:
        raise http(409, "conflict", "No current native-device Luddish request is available.")
    return JSONResponse(issued, status_code=201, headers=NO_STORE)


def _same_slm_submission(record: dict | None, model_id: str, expected: dict) -> bool:
    """Compare a replay to the stored accepted payload, without re-accepting it."""
    submission = (record or {}).get("submission") or {}
    if submission.get("state") != "advisory_received" or submission.get("model_id") != model_id:
        return False
    try:
        return repo.dec_json(submission["result_ciphertext"]) == expected
    except (KeyError, TypeError, ValueError):
        return False


@router.post("/investigations/{case_id}/slm/results", status_code=202)
async def receive_advisory(case_id: str, body: SLMReasoningResult, request: Request):
    """Validate and accept advisory output, NEVER as evidence or a case verdict."""
    _enabled()
    owner = request.state.device["device_id"]
    if body.case_id != case_id:
        raise http(409, "conflict", "Luddish reply belongs to a different investigation.")
    pending = await db.investigation_device_requests.find_one({
        "owner_id": owner, "case_id": case_id, "request_id": body.request_id,
        "kind": "slm_advisory",
    })
    if not pending:
        raise http(409, "conflict", "No matching Luddish request is outstanding.")
    if repo.utc(pending["expires_at"]) <= now_utc():
        raise http(409, "conflict", "The Luddish request has expired.")
    case, _job = await _active_case_job(
        owner, case_id, pending["job_id"], body.case_revision,
    )
    if pending.get("epoch") != case.get("epoch"):
        raise http(409, "conflict", "The investigation was restarted or replaced.")
    original = SLMReasoningRequest.model_validate(repo.dec_json(pending["request_ciphertext"]))
    try:
        accepted = accept_advisory_reasoning(original, body)
    except ValueError:
        raise http(422, "invalid_input", "Luddish reasoning failed case or evidence-reference checks.")

    # A lost HTTP receipt can be replayed safely. Only the identical validated
    # result is acknowledged; conflicting retries remain rejected.
    if pending.get("submission"):
        if _same_slm_submission(pending, body.model_id, accepted.wire()):
            return JSONResponse({"accepted": True, "advisoryOnly": True,
                                 "caseId": case_id, "requestId": body.request_id},
                                status_code=202, headers=NO_STORE)
        raise http(409, "conflict", "This Luddish request has already been answered.")
    # Conditional single acceptance. Never call ingest_observation, never update
    # investigation evidence, jobs, Findings or scores.
    claimed = await db.investigation_device_requests.find_one_and_update(
        {
            "owner_id": owner, "case_id": case_id, "request_id": body.request_id,
            "kind": "slm_advisory", "submission": None,
            "job_id": pending["job_id"], "epoch": case.get("epoch"),
            "expires_at": {"$gt": now_utc()},
        },
        {"$set": {
            "submission": {
                "state": "advisory_received",
                "result_ciphertext": repo.enc_json(accepted.wire()),
                "model_id": body.model_id,
                "received_at": now_utc(),
            },
            "fulfilled": True,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        latest = await db.investigation_device_requests.find_one({
            "owner_id": owner, "case_id": case_id, "request_id": body.request_id,
            "kind": "slm_advisory", "epoch": case.get("epoch"),
            "expires_at": {"$gt": now_utc()},
        })
        if not _same_slm_submission(latest, body.model_id, accepted.wire()):
            raise http(409, "conflict", "The Luddish request was already answered or expired.")
    return JSONResponse({"accepted": True, "advisoryOnly": True, "caseId": case_id,
                         "requestId": body.request_id}, status_code=202, headers=NO_STORE)
