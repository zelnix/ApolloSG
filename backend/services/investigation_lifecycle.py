"""Shared investigation lifecycle helpers (Finding C).

Functions previously scattered between routers/investigations.py that are also
imported by services/higgins/pipeline_submit.py.  Moving them here eliminates
the service-imports-router antipattern and places them at the correct
architectural layer.

All callers (investigations.py, pipeline_submit.py) import from here.
No FastAPI types anywhere in this module — it is framework-agnostic.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from core.db import db, now_utc
from core.redaction import redact_investigation_secrets
from services import work_dedupe
from services.higgins import evidence as ev
from services.higgins import jobs
from services.higgins import repository as repo
from services.higgins.contracts import Submission, SubmitTurn
from services.higgins.repository import http


# ── Constants ─────────────────────────────────────────────────────────────────

CHECK_CLAIM = "check"


# ── Gate inference (unified — replaces the two separate functions) ────────────

def infer_gate(items: list, question: str = "") -> str | None:
    """Deterministically infer the canonical Gate from evidence items.

    Accepts both Submission objects (pydantic/dataclass with .kind/.value
    attributes) and plain dicts ({"kind": ..., "value": ...}).  Returns None
    when genuinely ambiguous.
    """
    def _kind(s) -> str:
        return getattr(s, "kind", None) or (s.get("kind", "") if isinstance(s, dict) else "")

    def _value(s) -> str:
        v = getattr(s, "value", None)
        if v is None and isinstance(s, dict):
            v = s.get("value", "")
        return v or ""

    if any(_kind(s) == "url" for s in items):
        return "link"

    all_text = " ".join(_value(s) for s in items if _kind(s) in ("text", "email", "phone")) + " " + question
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", all_text):
        return "email"
    if re.search(r"(?:\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}", all_text):
        return "call"
    if any(_kind(s) in ("text", "email", "phone") for s in items):
        return "text"
    return None


# ── Deduplication ─────────────────────────────────────────────────────────────

async def same_evidence_case(
    owner: str, items: list[tuple[str, str]]
) -> tuple[Optional[dict], Optional[str]]:
    """Identical evidence already taken on by this device → (that case, None);
    otherwise (None, the claim to attach the new case to). Claimed atomically,
    so two identical checks arriving together start one case.
    """
    if not items:
        return None, None
    value = work_dedupe.digest(owner, *sorted(f"{kind}:{text}" for kind, text in items))
    for _ in range(3):
        earlier = await work_dedupe.claim(owner, CHECK_CLAIM, value)
        if earlier is None:
            return None, value
        if not earlier.get("case_id"):
            earlier = await work_dedupe.wait_for(owner, CHECK_CLAIM, value, "case_id")
            if earlier is None:
                if await db.work_claims.find_one(
                    {"owner_id": owner, "kind": CHECK_CLAIM, "digest": value}, {"_id": 1}
                ):
                    raise http(409, "conflict",
                               "The same check is already starting on this device. "
                               "Open it from Threats in a moment.")
                continue
        case = await db.investigation_cases.find_one(
            {"owner_id": owner, "case_id": earlier["case_id"], "deleted": False}, {"_id": 0}
        )
        if case and repo.utc(case["expires_at"]) > now_utc():
            return case, None
        await work_dedupe.release(owner, CHECK_CLAIM, value)
    raise http(409, "conflict",
               "The same check is already starting on this device. Open it from Threats in a moment.")


async def first_job(owner: str, case_id: str) -> Optional[dict]:
    """The earliest investigation job for a case, or None."""
    return await db.investigation_jobs.find_one(
        {"owner_id": owner, "case_id": case_id}, {"_id": 0}, sort=[("created_at", 1)]
    )


# ── Turn submission ────────────────────────────────────────────────────────────

async def _submit_turn(owner: str, case: dict, body: SubmitTurn, key: str) -> dict:
    """Create and launch one investigation job for a turn.

    Idempotent: a second call with the same *key* returns the existing job.
    Raises 409 when a concurrent turn is already active or when the same
    idempotency key was used for a different payload.
    """
    payload = {
        "message": redact_investigation_secrets(body.message),
        "answerToQuestionId": body.answer_to_question_id,
        "evidenceIds": body.evidence_ids,
        "turnId": body.turn_id,
    }
    key_digest = repo.digest(f"{owner}:turn:{key}")
    payload_digest = repo.digest(json.dumps(payload, sort_keys=True))

    existing = await db.investigation_jobs.find_one(
        {"owner_id": owner, "case_id": case["case_id"], "idempotency_key_digest": key_digest},
        {"_id": 0},
    )
    if existing:
        if existing["payload_digest"] != payload_digest:
            raise http(409, "conflict",
                       "This Idempotency-Key was already used for a different question.")
        return existing

    if case.get("active_job_id"):
        raise http(409, "conflict",
                   "Higgins is still working on this investigation. "
                   "Wait for the current turn or cancel it.")

    for evidence_id in body.evidence_ids:
        await repo.get_evidence(owner, case["case_id"], evidence_id)

    job = await repo.create_job(owner, case, body.turn_id, key_digest, payload_digest, "turn", payload)
    updated = await repo.cas(
        owner, case["case_id"],
        {"revision": case["revision"], "active_job_id": None},
        {"$set": {"status": "queued", "active_job_id": job["job_id"], "active_turn_id": body.turn_id}},
    )
    if not updated:
        await db.investigation_jobs.delete_one({"owner_id": owner, "job_id": job["job_id"]})
        raise http(409, "conflict", "Another turn was submitted first. Reload the investigation.")

    jobs.launch(owner, case["case_id"], job["job_id"])
    return job


# ── Specialist evidence pre-gathering ────────────────────────────────────────

async def _pregather_specialist_evidence(gate: str | None, submissions: list) -> dict:
    """Gather free/already-paid specialist provider evidence for user-initiated
    checks BEFORE Magnum DI starts reasoning.  Stored as `triage_provider_evidence`
    on the case document and forwarded to Magnum DI as structured Apollo observations.

    Does NOT gate or triage the submission — the full investigation always proceeds.
    """
    from services.triage_engine import gather_provider_evidence, _extract_indicators

    indicators: dict = {"urls": [], "domains": [], "phones": [], "emails": []}

    for item in submissions:
        kind = getattr(item, "kind", None) or (item.get("kind", "") if isinstance(item, dict) else "")
        value = getattr(item, "value", None) or (item.get("value", "") if isinstance(item, dict) else "")
        if kind == "url":
            url_val = value.strip()
            if url_val:
                # Normalise before provider lookups: strip tracking params etc.
                from services.url_normalise import normalise_url
                url_val = normalise_url(url_val)
                indicators["urls"].append(url_val)
                try:
                    from urllib.parse import urlparse
                    host = urlparse(url_val).hostname or ""
                    if host:
                        indicators["domains"].append(host)
                except Exception:
                    pass
        elif kind == "text":
            text_indicators = _extract_indicators(value)
            for k in ("urls", "domains", "phones", "emails"):
                indicators[k].extend(text_indicators.get(k, []))

    for k in indicators:
        indicators[k] = list(dict.fromkeys(indicators[k]))[:10]

    if not any(indicators.values()):
        return {}

    evidence = {
        "urls": indicators["urls"],
        "domains": indicators["domains"],
        "phones": indicators["phones"],
        "emails": indicators["emails"],
        "auth_results": {},
    }
    # Also pass link_urls so gather_provider_evidence can run redirect expansion.
    evidence["link_urls"] = indicators["urls"]
    evidence["link_domains"] = indicators["domains"]
    return await gather_provider_evidence(evidence)


# ── Source metadata builder (Original Item Summary) ───────────────────────────

def _build_source_metadata(gate: str | None, submissions: list, question: str) -> dict | None:
    """Build source_metadata from user-submitted evidence.

    Returns a compact dict of *actual recorded identifiers* — never Gemini-inferred.
    Returns None when the gate is unknown or there are no useful identifiers.
    """
    if not submissions:
        return None

    def _kind(s) -> str:
        return getattr(s, "kind", None) or (s.get("kind", "") if isinstance(s, dict) else "")

    def _value(s) -> str:
        v = getattr(s, "value", None)
        if v is None and isinstance(s, dict):
            v = s.get("value", "")
        return v or ""

    kinds = [_kind(s) for s in submissions]
    has_image = "image" in kinds
    has_url = "url" in kinds
    has_text = "text" in kinds

    if has_image:
        return {
            "type": "screenshot",
            "submitted_at": now_utc(),
            "image_count": kinds.count("image"),
            "user_question": question[:300] if question else None,
        }
    if has_url:
        first_url = next((_value(s) for s in submissions if _kind(s) == "url"), None)
        return {
            "type": "link",
            "url": first_url[:500] if first_url else None,
            "submitted_at": now_utc(),
            "user_question": question[:300] if question else None,
        }
    if has_text:
        first_text = next((_value(s) for s in submissions if _kind(s) == "text"), None)
        src_type = gate if gate in ("text", "call", "app", "file", "account", "device", "network") else "text"
        return {
            "type": src_type,
            "preview": first_text or None,
            "submitted_at": now_utc(),
            "user_question": question[:300] if question else None,
        }
    return None
