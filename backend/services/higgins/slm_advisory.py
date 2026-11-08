"""Read previously accepted on-device Luddish advice for a live investigation.

This is a read-only, optional checkpoint inside the existing coordinator.
No network/model call, job wait, new collection or evidence ingestion.
The existing case controls remain authoritative. SLM hypotheses are never
trusted as facts, scores, findings or final-case verdicts.
"""
from __future__ import annotations

import os
from datetime import datetime

from core.db import db, now_utc
from services.higgins import repository as repo
from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning,
)

ROLES = frozenset(("higgins_triage", "tc_hawkeye", "magnum_di", "luddish"))


def enabled() -> bool:
    return os.getenv("APOLLO_SLM_HANDOFF", "").strip().lower() == "on"


async def accepted_for_stage(owner: str, case: dict, job: dict, role: str) -> dict | None:
    """Return only revalidated advisory suggestions for this active job.

    The result is an advisory snapshot for diagnostics/controlled verification
    planning, NOT a new evidence source. Expiry, cancellation or errors produce
    no advice rather than silently restoring stale cross-case data.
    """
    if not enabled() or role not in ROLES:
        return None
    case_id = case.get("case_id")
    job_id = job.get("job_id")
    revision = case.get("revision")
    if not case_id or not job_id or not isinstance(revision, int):
        return None
    if case.get("active_job_id") != job_id or case.get("status") not in ("queued", "investigating"):
        return None
    if job.get("status") not in ("queued", "investigating") or job.get("epoch") != case.get("epoch"):
        return None
    candidate = await db.investigation_device_requests.find_one({
        "owner_id": owner, "case_id": case_id, "job_id": job_id,
        "kind": "slm_advisory", "fulfilled": True,
        "submission.state": "advisory_received",
        "expires_at": {"$gt": now_utc()},
    }, {"_id": 0}, sort=[("created_at", -1)])
    if not candidate:
        return None
    try:
        original = SLMReasoningRequest.model_validate(repo.dec_json(candidate["request_ciphertext"]))
        if original.role != role or original.case_id != case_id or original.case_revision != revision:
            return None
        if candidate.get("epoch") != case.get("epoch"):
            return None
        response = SLMReasoningResult.model_validate({
            "caseId": case_id, "caseRevision": revision,
            "requestId": original.request_id,
            "execution": "on_device",
            "modelId": candidate["submission"]["model_id"],
            "answer": repo.dec_json(candidate["submission"]["result_ciphertext"]),
        })
        answer = accept_advisory_reasoning(original, response)
        return {
            "role": role,
            "requestId": original.request_id,
            "modelId": response.model_id,
            "observations": [item.wire() for item in answer.observations],
            "contradictions": [item.wire() for item in answer.contradictions],
            "alternativeExplanations": [item.wire() for item in answer.alternative_explanations],
            "verificationSuggestions": [item.wire() for item in answer.verification_suggestions],
            "draftExplanation": answer.draft_explanation,
            "classification": "unverified_slm_advisory",
        }
    except (KeyError, TypeError, ValueError):
        return None


def advisory_verification_questions(snapshot: dict | None) -> list[str]:
    """Unverified questions only. Cannot be scored or cited as verified facts."""
    if not snapshot:
        return []
    return [
        item["text"] for item in snapshot.get("verificationSuggestions", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ][:8]
