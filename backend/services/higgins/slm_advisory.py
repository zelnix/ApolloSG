"""Read previously accepted on-device Luddish advice for a live investigation.

This is the read-only result reader for the coordinator's required native stages.
No network/model call, job wait, new collection or evidence ingestion.
The existing case controls remain authoritative. SLM hypotheses are never
trusted as facts, scores, findings or final-case verdicts.
"""
from __future__ import annotations

from core.db import db, now_utc
from services.higgins import repository as repo
from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning,
)

ROLES = frozenset(("wright_triage", "higgins_triage", "tc_hawkeye", "magnum_di", "luddish", "case_finding", "higgins_escalation_assessment"))


async def accepted_for_stage(owner: str, case: dict, job: dict, role: str) -> dict | None:
    """Return only revalidated advisory suggestions for this active job.

    The result is an advisory snapshot for diagnostics/controlled verification
    planning, NOT a new evidence source. Expiry, cancellation or errors produce
    no advice rather than silently restoring stale cross-case data.
    """
    if role not in ROLES:
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
    cursor = db.investigation_device_requests.find({
        "owner_id": owner, "case_id": case_id, "job_id": job_id,
        "kind": "slm_advisory", "fulfilled": True,
        "expires_at": {"$gt": now_utc()},
    }, {"_id": 0}).sort("created_at", -1).limit(16)
    for candidate in await cursor.to_list(16):
        try:
            original = SLMReasoningRequest.model_validate(repo.dec_json(candidate["request_ciphertext"]))
            if original.role != role or original.case_id != case_id or original.case_revision != revision:
                continue
            if candidate.get("epoch") != case.get("epoch"):
                continue
            if candidate.get("work_epoch", job.get("work_epoch")) != job.get("work_epoch"):
                continue
            if candidate.get("submission", {}).get("state") == "advisory_failed":
                return {"stageFailure": candidate["submission"]["reason"], "role": role}
            if candidate.get("submission", {}).get("state") != "advisory_received":
                continue
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
                "wrightSemantic": answer.wright_semantic.wire() if answer.wright_semantic else None,
                "wrightReadiness": answer.wright_readiness.wire() if answer.wright_readiness else None,
                "caseFinding": answer.case_finding.wire() if answer.case_finding else None,
                "escalationAssessment": answer.escalation_assessment.wire() if answer.escalation_assessment else None,
                "classification": "unverified_slm_advisory",
            }
        except (KeyError, TypeError, ValueError):
            continue
    return None


def advisory_verification_questions(snapshot: dict | None) -> list[str]:
    """Unverified questions only. Cannot be scored or cited as verified facts."""
    if not snapshot:
        return []
    if snapshot.get("role") == "wright_triage" or snapshot.get("wrightReadiness") or snapshot.get("wrightSemantic"):
        return []
    questions = [
        item["text"] for item in snapshot.get("verificationSuggestions", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ][:8]
    return questions


def prioritise_existing_checks(checks: list, *advice_snapshots: dict | None) -> None:
    """Stable prioritisation only; never adds checks or treats SLM text as evidence."""
    import re
    suggestions = [
        question for snapshot in advice_snapshots
        for question in advisory_verification_questions(snapshot)
    ]
    if not suggestions:
        return
    terms = [set(re.findall(r"[a-z0-9]{4,}", question.casefold())) for question in suggestions]

    def relevant(check) -> bool:
        words = set(re.findall(r"[a-z0-9]{4,}", f"{check.subject} {check.question or ''}".casefold()))
        return any(len(words & suggestion) >= 2 for suggestion in terms)

    checks.sort(key=lambda check: not relevant(check))
