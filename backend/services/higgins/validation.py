"""Interface validation of Gemini's structured response (spec §7/§9): references, actions, completion.

Package 5 extends validation with INVESTIGATE → ASSESS → DIRECT → GUIDE → VERIFY structural enforcement.

No keyword/style filters. Violations are returned to the model for one targeted repair.

Structural rules:
- INVESTIGATE: Findings must reference registered evidence/source IDs; observation basis requires evidence
- ASSESS: Assessment must be supported by findings when concern is found
- DIRECT: Action-needed/urgent attention requires at least one action with a non-empty instruction
- GUIDE: When actions exist, recommendedActionIndex must be set; instructions must be actionable
- VERIFY: Completion 'complete' requires all material evidence examined; fabricated evidence rejected
- FLOOR: a result never contradicts established threat evidence; it goes below TC Hawkeye's provisional concern only
  with a finding that cites the evidence resolving it and names the provisional finding (supersedesFindingIds)

Findings that make the same point are merged before the response is returned, so the same fact is
never stated twice in one result.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from pydantic import ValidationError

from services.higgins import outcomes
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse, ModelFinding, ModelResponse, Question

log = logging.getLogger("apollo.validation")

# An action whose instruction carries a contact identifier (email, phone) cannot belong to an
# unable_to_determine result: Apollo hasn't established whose brand it is, so a specific address
# or number is a hallucination and must never reach the person.
_CONTACT_RE = re.compile(
    r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'    # email address  (e.g. phish@nab.com.au)
    r'|\+?\d[\d ()-]{6,16}\d(?![\w.%])',  # phone number
    re.I,
)

CAPABILITY_ACTIONS = {"open_settings", "request_permission", "recheck"}
# How far each outcome goes — the four Findings plus legacy codes for backward compatibility.
_RANK = {
    # Current four Findings
    "not_scam": 0, "unlikely_scam": 0, "likely_scam": 2, "scam": 3,
    # Legacy codes (backward compat for floor checks against historical records)
    "no_scam_indicators": 0, "unable_to_determine": 0, "concerning": 1, "confirmed_threat": 3,
}


def floor_errors(model: ModelResponse, floor: Optional[dict]) -> list[str]:
    """Established threat evidence is never overridden; a provisional concern is lowered only with resolving evidence."""
    if not floor or not model.outcome:
        return []
    got, errors = _RANK[model.outcome], []
    outcome, minimum = floor.get("outcome"), floor.get("minimum")
    if outcome and floor.get("established") and got < _RANK[outcome]:
        errors.append(f"outcome '{model.outcome}' contradicts established threat evidence (TC Hawkeye: '{outcome}'); it can't be lowered")
    if minimum and got < _RANK[minimum]:
        errors.append(f"outcome '{model.outcome}' contradicts established threat evidence: the material asks for a secret, so the outcome can't be below '{minimum}'")
    if outcome and not floor.get("established") and got < _RANK[outcome]:
        provisional = {f["id"] for f in floor.get("findings") or [] if f["id"].startswith("P")}
        if not any(set(f.supersedes_finding_ids) & provisional and (f.evidence_ids or f.source_ids) for f in model.findings):
            errors.append(f"outcome '{model.outcome}' is below TC Hawkeye's provisional '{outcome}': add the finding that corrects it, citing the "
                          f"evidence that resolves it, with the provisional finding's id ({', '.join(sorted(provisional)) or 'P1'}) in supersedesFindingIds")
    return errors

# ── Finding de-duplication ───────────────────────────────────────────────────
# Two findings that make the same point are one finding. The person reads the result once, so the
# same fact restated in slightly different words reads as padding and buries what is actually new.
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*")
_FILLER = {"a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "does", "for", "from",
           "has", "have", "in", "is", "it", "its", "not", "of", "on", "or", "that", "the", "this", "to",
           "was", "were", "which", "with", "you", "your"}


def _signature(text: str) -> frozenset[str]:
    """The meaning-bearing words of a finding. Equivalent hostnames reduce to the same token."""
    low = text.lower().replace("www.", "")
    return frozenset(w for w in (word.strip(".-") for word in _WORD_RE.findall(low)) if w and w not in _FILLER)


def _weight(finding: ModelFinding) -> tuple[int, int]:
    """How much a finding carries: cited evidence first, then how much it actually says."""
    return (len(finding.evidence_ids) + len(finding.source_ids), len(finding.text))


def deduplicate_findings(findings: list[ModelFinding]) -> list[ModelFinding]:
    """Merge findings describing the same underlying issue, keeping the most informative one.

    Two findings are one only when they have the same finding identity (explain.facts.identity): the same subject,
    and the same check and result — or one of them reports no check at all and names nothing the other doesn't.
    Two material findings about different subjects, or with different results, are never merged however alike their
    sentences look. Within one identity, a finding is a duplicate when its meaning-bearing words are contained in (or
    almost identical to) one already kept. The more informative version survives in the original position, so
    ordering and the "at least one finding" guarantee are both preserved.
    """
    from services.higgins.explain.facts import identity
    kept: list[ModelFinding] = []
    signatures: list[frozenset[str]] = []
    identities: list[tuple[frozenset[str], str, str]] = []
    for finding in findings:
        signature = _signature(finding.text)
        ident = identity(finding.text)
        if not signature:
            kept.append(finding)
            signatures.append(signature)
            identities.append(ident)
            continue
        replaced = False
        for index, existing in enumerate(signatures):
            if not _same_identity(ident, identities[index]):
                continue
            overlap = len(signature & existing)
            if not overlap:
                continue
            same_point = (overlap == len(signature) or overlap == len(existing)
                          or overlap / len(signature | existing) >= 0.8)
            if not same_point:
                continue
            if _weight(finding) > _weight(kept[index]):
                kept[index], signatures[index], identities[index] = finding, signature, ident
            replaced = True
            break
        if not replaced:
            kept.append(finding)
            signatures.append(signature)
            identities.append(ident)
    return kept


def _same_identity(a: tuple[frozenset[str], str, str], b: tuple[frozenset[str], str, str]) -> bool:
    """Same identifiers, check and result; or one reports no check and names nothing the other doesn't."""
    if a == b:
        return True
    (ids_a, check_a, _), (ids_b, check_b, _) = a, b
    if check_a == "stated" and ids_a <= ids_b:
        return bool(ids_a) or check_b == "stated"
    if check_b == "stated" and ids_b <= ids_a:
        return bool(ids_b) or check_a == "stated"
    return False


def validate(data: dict, *, revision: int, evidence_ids: set[str], source_ids: set[str], capability_ids: set[str],
             pending_question: Optional[dict], provider_complete: bool, material_gaps: Optional[set[str]] = None,
             floor: Optional[dict] = None) -> tuple[Optional[HigginsResponse], list[str]]:
    errors: list[str] = []
    try:
        model = ModelResponse.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {e['loc']} {e['msg']}" for e in exc.errors()[:8]]
    if not provider_complete:
        errors.append("provider finish was not normal termination; the response is incomplete")
    errors.extend(floor_errors(model, floor))
    if model.outcome == "not_scam" and material_gaps:
        errors.append("outcome 'not_scam' requires examination of all material evidence; coverage gaps remain")

    # ── INVESTIGATE: evidence and source reference integrity ──
    for idx, finding in enumerate(model.findings):
        unknown = [e for e in finding.evidence_ids if e not in evidence_ids] + [s for s in finding.source_ids if s not in source_ids]
        if unknown:
            errors.append(f"findings[{idx}] references unknown ids {unknown[:3]}; use only registered evidenceIds/sourceIds or leave the lists empty")
        if finding.basis == "observation" and not finding.evidence_ids:
            errors.append(f"findings[{idx}] basis 'observation' requires at least one evidenceId; otherwise label it 'inference'")
    unknown_sources = [s for s in model.source_ids if s not in source_ids]
    if unknown_sources:
        errors.append(f"sourceIds contains unknown ids {unknown_sources[:3]}")
    unknown_remaining = [e for e in model.remaining_evidence_ids if e not in evidence_ids]
    if unknown_remaining:
        errors.append(f"remainingEvidenceIds contains unknown ids {unknown_remaining[:3]}")

    # ── ASSESS: assessment must be supported by findings ──
    if model.assessment == "concern_found" and not model.findings:
        errors.append("assessment 'concern_found' requires at least one finding; add the finding that supports the concern")
    if model.assessment == "no_concern_found_within_scope" and model.attention in ("action_needed", "urgent"):
        errors.append("assessment 'no_concern_found_within_scope' is contradicted by attention 'action_needed'/'urgent'; reconcile the assessment with the attention level")
    # The investigator's outcome is authoritative over a redundant assessment
    # label. Repair the label without changing the conclusion or evidence.
    # TC Hawkeye's earlier score is context, not a veto on deeper reasoning.
    if model.outcome and model.assessment != outcomes.ASSESSMENT[model.outcome]:
        log.info("investigation_assessment_normalized outcome=%s previous=%s",
                 model.outcome, model.assessment)
        model.assessment = outcomes.ASSESSMENT[model.outcome]

    # Findings are assessed against the actual evidence, not rejected because a
    # confidence label is "low" or because an unrelated check was incomplete.
    # Preserve the declared confidence and completion for transparent display.
    # Reference integrity and verified-check requirements remain enforced below.

    # ── DIRECT: actionable concerns must have specific instructions ──
    for idx, action in enumerate(model.actions):
        if action.kind in CAPABILITY_ACTIONS and (not action.capability_id or action.capability_id not in capability_ids):
            errors.append(f"actions[{idx}] kind '{action.kind}' needs a capabilityId advertised by the device profile {sorted(capability_ids)[:6]}; otherwise use kind 'instruction'")
        if action.kind == "open_verified_source" and not all(s in source_ids for s in action.source_ids):
            errors.append(f"actions[{idx}] open_verified_source must cite registered sourceIds")
        if action.kind == "open_verified_source" and not action.source_ids:
            errors.append(f"actions[{idx}] open_verified_source requires a sourceId")
        if not action.instruction or not action.instruction.strip():
            errors.append(f"actions[{idx}] must have a non-empty instruction explaining what the person does")
        if not action.label or not action.label.strip():
            errors.append(f"actions[{idx}] must have a non-empty label for the action button")
    if model.attention in ("action_needed", "urgent") and not model.actions:
        errors.append("attention 'action_needed'/'urgent' requires at least one action telling the person what to do; add an action or lower the attention level")
    if model.attention in ("action_needed", "urgent") and not model.attention_reason:
        errors.append("attention 'action_needed'/'urgent' requires attentionReason tied to findings")

    # ── GUIDE: when actions exist, recommended index must be set ──
    if model.recommended_action_index is not None and not (0 <= model.recommended_action_index < len(model.actions)):
        errors.append("recommendedActionIndex is out of range")
    if model.actions and model.recommended_action_index is None:
        errors.append("actions are present but recommendedActionIndex is not set; set it to the index of the primary instruction")

    # ── VERIFY: completion must match examination state ──
    if model.completion == "waiting_user" and not (model.question or pending_question):
        errors.append("completion 'waiting_user' requires a question")
    if model.question and model.completion != "waiting_user":
        errors.append("a question requires completion 'waiting_user'")
    # Material unexamined evidence blocks 'complete' whether or not it appears in remainingEvidenceIds.
    if model.completion == "complete" and material_gaps:
        listed = set(model.remaining_evidence_ids)
        unlisted = sorted(material_gaps - listed)
        if unlisted:
            errors.append(f"completion 'complete' is not supported: evidence {unlisted[:4]} has unexamined material content. Set completion 'partial' and list it in remainingEvidenceIds")
        else:
            errors.append(f"completion 'complete' is not supported: evidence listed in remainingEvidenceIds {sorted(material_gaps)[:4]} still has unexamined material content. Set completion 'partial'")

    if errors:
        return None, errors

    # ── Construct validated response ──
    actions = [ActionProposal(id=str(uuid.uuid4()), kind=a.kind, label=a.label[:120], instruction=a.instruction, capability_id=a.capability_id,
                              execution_descriptor_id=None, requires_user_gesture=a.kind != "instruction", source_ids=a.source_ids,
                              desired_field=a.desired_field, desired_value=a.desired_value) for a in model.actions]

    # ── UNDETERMINED GUARD: strip brand-specific contact instructions ──
    # An unlikely_scam result (ordinary, unverified — the merged unable_to_determine/unlikely_scam
    # case) means Apollo hasn't established whose brand it is.  Any action whose instruction carries a
    # contact identifier (email or phone number) is therefore a hallucinated address the person should
    # never see.  Generic advice (no identifier) is kept.
    if model.outcome in ("unlikely_scam", "unable_to_determine") and actions:
        clean = [a for a in actions if not _CONTACT_RE.search(a.instruction)]
        if len(clean) < len(actions):
            log.warning("undetermined_action_sanitized case_actions=%d dropped=%d",
                        len(actions), len(actions) - len(clean))
            actions = clean

    # Recalculate the recommended action after any sanitization: keep the original choice if it
    # survived; otherwise fall back to the first remaining action (or None when all were stripped).
    recommended_action_id: Optional[str] = None
    if actions:
        orig_idx = model.recommended_action_index
        # Map original index → surviving action id (actions list may have shrunk)
        orig_ids = [a.id for a in actions]  # these are the surviving actions in order
        # Find the originally-recommended action by matching its label+instruction fingerprint
        # against the surviving list; fall back to index 0 when it was stripped.
        if orig_idx is not None and orig_idx < len(model.actions):
            orig_label = model.actions[orig_idx].label
            orig_instr = model.actions[orig_idx].instruction
            match = next((a for a in actions if a.label == orig_label[:120] and a.instruction == orig_instr), None)
            recommended_action_id = match.id if match else actions[0].id
        else:
            recommended_action_id = actions[0].id

    question = None
    if model.question:
        question = Question(id=(pending_question or {}).get("id", str(uuid.uuid4())), text=model.question.text, reason_needed=model.question.reason_needed,
                            answer_type=model.question.answer_type, choices=model.question.choices)
    elif model.completion == "waiting_user" and pending_question:
        question = Question.model_validate(pending_question)
    response = HigginsResponse(revision=revision, overview=model.overview, explanation_markdown=model.explanation_markdown, assessment=model.assessment,
                               outcome=model.outcome, attention=model.attention, attention_reason=model.attention_reason,
                               findings=[Finding(id=str(uuid.uuid4()), **f.model_dump()) for f in deduplicate_findings(model.findings)], uncertainties=model.uncertainties,
                               scope=model.scope, source_ids=model.source_ids, remaining_evidence_ids=model.remaining_evidence_ids, actions=actions,
                               recommended_action_id=recommended_action_id,
                               question=question, completion=model.completion,
                               findings_rating=model.findings_rating, findings_rating_breakdown=model.findings_rating_breakdown,
                               technical_failure=model.technical_failure, taxonomy=model.taxonomy, findings_brief=model.findings_brief,
                               mechanisms=model.mechanisms, playbooks=model.playbooks)
    return response, []
