"""Internal pipeline submission for Higgins investigation intent.

When Higgins detects that the user wants an investigation (e.g. "Is this email
a scam?", "Check this URL"), this module creates a case in the shared pipeline
with initiator='higgins_user_request' — the same pipeline used by User Checks
and Apollo automatic detection.

NO separate pseudo-investigation is performed in chat.  Higgins simply submits
the Original Item and returns the case reference to the user.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from core.db import db
from core.redaction import redact_investigation_secrets
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.contracts import Submission, SubmitTurn

log = logging.getLogger("apollo.higgins.pipeline")

# ── Intent detection ─────────────────────────────────────────────────────────

# Clear investigation intent: the person explicitly asks to check/investigate
# a specific item.  Each pattern must be combined with the presence of a
# submittable artefact (URL, email, phone, or substantial text).
#
# Design rule: prefer false-negative (miss an investigation intent → normal chat)
# over false-positive (accidentally launch an investigation from conversational text).
_INTENT_PATTERNS = [
    # "Is this a scam / phishing / fraud / legit / safe?"
    re.compile(r"(?i)\b(?:is\s+(?:this|it)|could\s+this\s+be)\b.*\b(?:scam|phish|fraud|legit|legitimate|safe|fake|suspicious|malicious|dodgy)", re.S),
    # "Check / investigate / look into / scan this"
    re.compile(r"(?i)\b(?:check|investigate|look\s+(?:at|into)|scan|verify|inspect|analyse|analyze)\b", re.S),
    # "Should I click / open / trust this?"
    re.compile(r"(?i)\b(?:should\s+i|is\s+it\s+safe\s+to)\b.*\b(?:click|open|respond|reply|call|trust)\b", re.S),
]

# Artefact extractors
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# General international phone pattern — mirrors indicators.py PHONE_RE so both code paths
# (direct investigation submission and Higgins chat submission) extract the same numbers.
# Lookbehind/lookahead prevent matching partial digit runs inside email addresses or amounts.
_PHONE_RE = re.compile(r"(?<![\w@.+/])(\+?\d[\d\s().\-]{5,18}\d)(?![\w@])")


def detect_investigation_intent(message: str) -> bool:
    """Return True if the message signals a clear investigation request."""
    return any(p.search(message) for p in _INTENT_PATTERNS)


def extract_submittable_items(message: str) -> list[dict]:
    """Extract concrete artefacts (URLs, emails, phones) from the message.

    Returns a list of dicts: [{"kind": "url"|"email"|"phone"|"text", "value": ...}]
    If no specific artefact is found but the message is substantial enough,
    the whole message is submitted as text.
    """
    items: list[dict] = []
    seen: set[str] = set()

    for url in _URL_RE.findall(message):
        # Strip trailing punctuation
        url = url.rstrip(".,;:!?)")
        if url not in seen:
            items.append({"kind": "url", "value": url})
            seen.add(url)

    for email in _EMAIL_RE.findall(message):
        if email not in seen:
            items.append({"kind": "email", "value": email})
            seen.add(email)

    for phone in _PHONE_RE.findall(message):
        clean = phone.strip()
        digits = re.sub(r"\D", "", clean)
        if 7 <= len(digits) <= 15 and clean not in seen:
            items.append({"kind": "phone", "value": clean})
            seen.add(clean)

    # If no concrete artefact was found, submit the message text itself
    # (only if it's substantial — at least 20 chars beyond intent keywords)
    if not items and len(message.strip()) >= 30:
        items.append({"kind": "text", "value": message.strip()[:4000]})

    return items


# ── Pipeline submission ──────────────────────────────────────────────────────

def _infer_gate(items: list[dict]) -> str | None:
    """Infer the gate from extracted artefacts."""
    for item in items:
        if item["kind"] == "url":
            return "link"
        if item["kind"] == "email":
            return "email"
        if item["kind"] == "phone":
            return "call"
    return "text"


async def submit_to_investigation_pipeline(
    owner: str,
    message: str,
    items: list[dict],
    *,
    device_profile: Optional[dict] = None,
) -> dict:
    """Submit extracted items to the shared investigation pipeline.

    Uses the SAME case-creation and pre-gathering flow as User Checks and
    Apollo automatic detection.  The only difference is `initiator`.

    Returns: {"case_id": str, "status": str, "job_id": str|None}
    """
    from routers.investigations import (
        _pregather_specialist_evidence,
        _build_source_metadata,
        CHECK_CLAIM,
        first_job,
        same_evidence_case,
    )
    from services import work_dedupe

    # Build Submission objects
    submissions: list[Submission] = []
    for item in items:
        client_id = f"higgins-{uuid.uuid4().hex[:12]}"
        if item["kind"] == "url":
            submissions.append(Submission(client_item_id=client_id, kind="url", value=item["value"], label="Higgins-submitted link"))
        elif item["kind"] == "email":
            submissions.append(Submission(client_item_id=client_id, kind="text", value=item["value"], label="Higgins-submitted email address"))
        elif item["kind"] == "phone":
            submissions.append(Submission(client_item_id=client_id, kind="text", value=item["value"], label="Higgins-submitted phone number"))
        else:
            submissions.append(Submission(client_item_id=client_id, kind="text", value=item["value"], label="Higgins-submitted content"))

    question = redact_investigation_secrets(message)
    gate = _infer_gate(items)

    # The same evidence already checked on this device: that case, not a new one (rewording the question doesn't count).
    earlier, claim = await same_evidence_case(owner, [(s.kind, s.value) for s in submissions])
    if earlier:
        job = await first_job(owner, earlier["case_id"])
        return {"case_id": earlier["case_id"], "status": "existing", "job_id": job["job_id"] if job else None}

    # ── Create new case with shared pipeline ─────────────────────────────────
    case = await repo.create_case(owner, gate, device_profile, initiator="higgins_user_request")
    case_id = case["case_id"]
    if claim:
        await work_dedupe.attach(owner, CHECK_CLAIM, claim, case_id=case_id)

    # Source metadata
    update_fields: dict = {}
    source_meta = _build_source_metadata(gate, submissions, question)
    if source_meta:
        update_fields["source_metadata"] = source_meta

    if update_fields:
        await db.investigation_cases.update_one(
            {"owner_id": owner, "case_id": case_id},
            {"$set": update_fields},
        )

    # Ingest evidence items
    for sub in submissions:
        if sub.kind == "url":
            await ev.ingest_url(owner, case, sub.client_item_id, sub.value, label=sub.label)
        else:
            await ev.ingest_text(owner, case, sub.client_item_id, sub.value, label=sub.label or "submitted text")

    # ── Pre-gather specialist evidence ───────────────────────────────────────
    # Stored as triage_provider_evidence on the case; the coordinator delivers
    # it to Magnum DI as structured Apollo observations — not injected into the question.
    if question.strip():
        try:
            provider_evidence = await _pregather_specialist_evidence(gate, submissions)
            if provider_evidence:
                await db.investigation_cases.update_one(
                    {"owner_id": owner, "case_id": case_id},
                    {"$set": {"triage_provider_evidence": provider_evidence}},
                )
        except Exception as exc:
            log.warning("higgins_pregather_failed case=%s error=%s", case_id[:12], type(exc).__name__)

    # ── Submit first turn via canonical _submit_turn ────────────────────────
    job = None
    if question.strip():
        from routers.investigations import _submit_turn
        turn = SubmitTurn(expected_revision=0, turn_id=str(uuid.uuid4()), message=question)
        job = await _submit_turn(owner, case, turn, f"higgins-submit-{case_id}")

    log.info("higgins_pipeline_submit device=%s case=%s gate=%s", owner[:12], case_id[:12], gate)

    return {
        "case_id": case_id,
        "status": "queued",
        "job_id": job["job_id"] if job else None,
    }


def submitted_answer(items: list[dict]) -> str:
    """What Higgins tells the person when their message went to the investigation pipeline."""
    artefact = items[0]["value"][:80] if items else "your item"
    return (f"I've submitted that for investigation. Apollo is now investigating {artefact} through the same pipeline "
            "used for all security checks: TC FlyBy investigates it first, and Magnum DI looks deeper only if that could change the answer. "
            "You'll find the full briefing, evidence chain and recommended actions in your investigation history once it completes.")
