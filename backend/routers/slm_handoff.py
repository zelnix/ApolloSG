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
    "case_finding": "Evaluate the supplied investigation evidence and produce Findings with cited reasons, not a legal verdict. Preserve source attribution and uncertainty; do not invent verification.",
}
OPERATION = {
    "higgins_triage": "investigation_readiness",
    "tc_hawkeye": "evidence_reasoning",
    "magnum_di": "evidence_reasoning",
    "luddish": "explanation",
    "case_finding": "case_finding",
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
    """Only user-submitted text/URLs are eligible. Never include prior cases or KB."""
    gathered = []
    total = 0
    for row in await repo.list_evidence(owner, case_id):
        submitted = row.get("origin") == "user_submission" and row.get("kind") in ("text", "url")
        checks = include_checks and row.get("client_item_id") in ("tc-flyby-di-checks", "magnum-di-external-investigation")
        if not (submitted or checks):
            continue
        if row.get("availability") != "available":
            continue
        raw = await repo.read_bytes(owner, case_id, row["evidence_id"])
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        total += len(text)
        if total > 10000 or len(gathered) >= 16:
            raise http(413, "budget_exhausted", "Too much material for this on-device pilot; nothing has been shortened.")
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
    evidence = await _source_evidence(owner, case_id, include_checks=(role == "case_finding"))
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
    if pending.get("submission"):
        raise http(409, "conflict", "This Luddish request has already been answered.")
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
    # Conditional single acceptance. Never call ingest_observation, never update
    # investigation evidence, jobs, findings, scores or Evidence Lock.
    claimed = await db.investigation_device_requests.find_one_and_update(
        {
            "owner_id": owner, "case_id": case_id, "request_id": body.request_id,
            "kind": "slm_advisory", "submission": None,
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
        raise http(409, "conflict", "The Luddish request was already answered or expired.")
    return JSONResponse({"accepted": True, "advisoryOnly": True, "caseId": case_id,
                         "requestId": body.request_id}, status_code=202, headers=NO_STORE)
