"""The Higgins Case Briefing: one authoritative summary of a case, built from the facts and the checked plain English.

Every surface that talks about the case — Home, Threats, the Overview, notifications — shows a projection of this one
briefing, so they can't drift apart. The DI tab stays the technical trace and Evidence the original material.
Deterministic: no AI. The briefing gets its own Fidelity Check (fidelity.check_briefing); if its short summary fails,
the summary falls back to the findings in full.
"""
from __future__ import annotations

from typing import Optional

from services.higgins import outcomes
from services.higgins.contracts import BriefingFinding, BriefingSubject, CaseBriefing, FidelityResult, HigginsResponse
from services.higgins.explain import fidelity
from services.higgins.explain import words as W
from services.higgins.explain.facts import Facts, classify
from services.higgins.explain.render import Draft, plain

# How many findings the short summary names (the rest are in the Overview).
SUMMARY_FINDINGS = 2
_GATE_NOUN = {"email": "email", "link": "link", "site": "website", "text": "message", "call": "call", "file": "file", "app": "app",
              "account": "account", "network": "connection", "device": "device"}


def headline(f: Facts, gates: list[str] | tuple[str, ...]) -> str:
    """ "Stoko email checked": the organisation and what was checked, in Apollo's fixed words."""
    noun = next((_GATE_NOUN[g] for g in gates if g in _GATE_NOUN), None) or (W.HEADLINE[f.subject["type"]] if f.subject else None)
    if not noun:
        return W.HEADLINE_NO_SUBJECT
    org = (f.subject or {}).get("organisation")
    template = (W.HEADLINE_CLAIMED_ORG if (f.subject or {}).get("organisation_claimed") else W.HEADLINE_WITH_ORG) if org else W.HEADLINE_NO_ORG
    text = template.format(org=org, noun=noun)
    return text[0].upper() + text[1:]


def _short(sf: dict, shown: str) -> str:
    """A finding in fewer words — only where Apollo's fixed short form keeps its subject, check and result exactly."""
    template = W.SUMMARY.get((sf["check"], sf["result"]))
    if template and sf["subject"] and ("{org}" not in template or sf["organisation"]):
        text = template.format(subject=sf["subject"], org=sf["organisation"])
        if classify(text) == (sf["check"], sf["result"]):
            return text
    return shown


def _summary(f: Facts, draft: Draft, unresolved: list[str], *, short: bool) -> str:
    texts = {item.finding_id: item.text for item in draft.established}
    material = [sf for sf in f.findings if sf["materiality"] == "material"]
    lead = (f.subject or {}).get("value")
    # Findings about what the case is about first, then the rest, each in Apollo's order.
    ordered = [sf for sf in material if sf["subject"] == lead] + [sf for sf in material if sf["subject"] != lead]
    lines = [(_short(sf, texts[sf["id"]]) if short else texts[sf["id"]]) for sf in ordered[:SUMMARY_FINDINGS]]
    if unresolved:
        lines.append(W.UNRESOLVED_LINE.format(reason=unresolved[0]))
    return " ".join(lines) or draft.result.text


def build(f: Facts, draft: Draft, response: HigginsResponse, gates: list[str] | tuple[str, ...] = ()) -> CaseBriefing:
    texts = {item.finding_id: item.text for item in draft.established}
    findings = [BriefingFinding(id=sf["id"], subject=sf["subject"], subject_type=sf["subjectType"], organisation=sf["organisation"],
                                organisation_claimed=sf["organisationClaimed"], check=sf["check"], result=sf["result"], finding=texts[sf["id"]], evidence_ids=sf["evidenceIds"],
                                source_ids=sf["sourceIds"], materiality=sf["materiality"], confidence=sf["confidence"], basis=sf["basis"],
                                stance=sf["stance"]) for sf in f.findings]
    unresolved = [item.text for item in draft.uncertain]
    label = f"{outcomes.label(f.outcome)}." if f.outcome else ""
    verdict = draft.result.text[len(label):].strip() if label and draft.result.text.startswith(label) else draft.result.text
    status_reason = draft.matters[0].text if draft.matters else verdict
    # "Needs you" only with a concrete reason Apollo recorded: an action-level attention with its reason, or the
    # question Magnum DI is waiting on. A review, or "keep watching", is never a decision the person owes.
    action_reason: Optional[str] = None
    if f.attention in ("action_needed", "urgent") and f.attention_reason and draft.matters:
        action_reason = draft.matters[0].text
    elif response.completion == "waiting_user" and response.question and response.question.reason_needed.strip():
        action_reason = plain(response.question.reason_needed)
    recommended = None
    if f.recommended:
        index = next(i for i, a in enumerate(f.actions) if a["id"] == f.recommended["id"])
        recommended = {"label": f.recommended["label"], "instruction": draft.todo[index].text if index < len(draft.todo) else f.recommended["instruction"]}
    briefing = CaseBriefing(
        subject=BriefingSubject(**f.subject) if f.subject else None, headline=headline(f, gates),
        summary=_summary(f, draft, unresolved, short=True), findings=findings,
        supporting=[b.id for b in findings if b.stance == "supporting"], contrary=[b.id for b in findings if b.stance == "contrary"],
        unresolved=unresolved, status=outcomes.label(f.outcome) or "", status_code=f.outcome, attention=f.attention,
        status_reason=status_reason, user_action_required=action_reason is not None, action_reason=action_reason,
        recommended_action=recommended, fidelity=FidelityResult(status="PASS"))
    result = fidelity.check_briefing(f, draft, briefing)
    if result.status == "FAIL":
        # The short forms didn't hold: say the findings in full instead, and check again.
        briefing = briefing.model_copy(update={"summary": _summary(f, draft, unresolved, short=False)})
        result = fidelity.check_briefing(f, draft, briefing)
    return briefing.model_copy(update={"fidelity": result})

