"""TC Hawkeye — executes a Verification Playbook's steps against a real investigation (PRD v2.3 §7.5).

Never invents a result. A step only reports "completed" when ApolloSG already has a real, already-
integrated check (link/company/abn/acn/licence/phone/email/person) or KB signal (a matched scam
pattern, an extracted claim or urgency phrase, a consequential request) that answers it — the exact
same `Plan`/`IPDMCChecks` data `scoring.score_plan()` already uses, read here rather than recomputed.
A step with no real source behind it today (a blockchain explorer, a government portal, a land
registry, a marketplace seller API) is honestly reported `unavailable`, per PRD §8.5: "a lookup that
fails is recorded as unavailable — never as safe." This module never changes the Findings Rating.
"""
from __future__ import annotations

from services.higgins.tc_flyby import playbooks as pb
from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import CONSEQUENTIAL, Plan


def _facts_of(plan: Plan, kinds: tuple[str, ...]) -> tuple[list[dict], list]:
    checks = [c for c in plan.checks if c.kind in kinds]
    facts = [f for c in checks for f in c.facts if f.get("class") == "live_evidence"]
    return facts, checks


def _registry_like(plan: Plan, ipdmc: IPDMCChecks, kinds: tuple[str, ...]) -> tuple[str, str | None]:
    facts, checks = _facts_of(plan, kinds)
    if facts:
        return "completed", "; ".join(f["text"] for f in facts)
    if not checks:
        return "not_applicable", None
    if any(c.status == "unavailable" for c in checks):
        return "unavailable", None
    return "inconclusive", None


def _company_registry(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    return _registry_like(plan, ipdmc, ("company", "abn", "acn"))


def _link_reputation(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    return _registry_like(plan, ipdmc, ("link",))


def _contact_crossref(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    return _registry_like(plan, ipdmc, ("phone", "email"))


def _licence_check(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    return _registry_like(plan, ipdmc, ("licence",))


def _person_crossref(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    return _registry_like(plan, ipdmc, ("person",))


def _scam_pattern_match(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    if plan.pattern:
        return "completed", f"Matches Apollo's \u201c{plan.pattern.get('name')}\u201d scam pattern ({plan.pattern.get('stage')})."
    return "inconclusive", None


def _claims_and_urgency(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    found = list(plan.entities.claims or []) + list(plan.entities.urgency or [])
    if found:
        return "completed", "; ".join(found)
    return "inconclusive", None


def _consequential_request(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    reqs = [r for r in plan.entities.requests if r["type"] in CONSEQUENTIAL]
    if reqs:
        return "completed", "; ".join(r["quote"] for r in reqs)
    return "not_applicable", None


def _otp_request_check(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    key = (plan.pattern or {}).get("key") if plan.pattern else None
    if key in ("otp_bypass", "bank_code_call"):
        return "completed", f"Matches Apollo's \u201c{plan.pattern.get('name')}\u201d OTP-request scam pattern."
    req = next((r for r in plan.entities.requests if r["type"] == "credentials"), None)
    if req:
        return "completed", req["quote"]
    return "not_applicable", None


def _unavailable_source(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    """No source ApolloSG has today (a paid/live blockchain explorer, government portal, land
    registry, marketplace seller API, etc.) answers this step — honestly `unavailable`, never
    guessed from pattern-matching standing in for real verification."""
    return "unavailable", None


_STEP_RESOLVERS = {
    "company_registry": _company_registry, "link_reputation": _link_reputation, "contact_crossref": _contact_crossref,
    "licence_check": _licence_check, "person_crossref": _person_crossref, "scam_pattern_match": _scam_pattern_match,
    "claims_and_urgency": _claims_and_urgency, "consequential_request": _consequential_request,
    "otp_request_check": _otp_request_check, "unavailable_source": _unavailable_source,
}


def run_step(step: pb.PlaybookStep, plan: Plan, ipdmc: IPDMCChecks) -> dict:
    status, evidence = _STEP_RESOLVERS[step.resolver](plan, ipdmc)
    return {"order": step.order, "description": step.description, "sourceIds": list(step.source_ids),
            "status": status, "evidence": evidence}


def run_playbook(playbook: pb.Playbook, plan: Plan, ipdmc: IPDMCChecks) -> dict:
    """Runs every step of one playbook against this investigation, per its own fallback behaviour
    (`playbook.fallback_behaviour` — a step that can't be answered never blocks the rest)."""
    steps_run = [run_step(s, plan, ipdmc) for s in playbook.steps]
    unavailable_or_inconclusive = [s for s in steps_run if s["status"] in ("unavailable", "inconclusive")]
    unresolved_request = bool(ipdmc.consequential_requests) and (bool(ipdmc.unverified_destinations) or ipdmc.destinations_verified != "passed")
    # §7.5's own escalation language: "if primary sources are unavailable ... and the investigation is
    # critical" — critical here means a consequential, unverified request is actually in play.
    escalate = unresolved_request and len(unavailable_or_inconclusive) >= len(steps_run) - 1
    evidence_output = {}
    for i, field_name in enumerate(playbook.evidence_output_fields):
        step = steps_run[min(i, len(steps_run) - 1)]
        evidence_output[field_name] = step["evidence"]
    return {"id": playbook.id, "title": playbook.title, "purpose": playbook.purpose, "steps": steps_run,
            "evidenceOutput": evidence_output, "escalationRecommended": escalate,
            "escalationReason": playbook.escalation_conditions if escalate else None}


def run_applicable(plan: Plan, ipdmc: IPDMCChecks, variant_code: str | None) -> list[dict]:
    """Every Verification Playbook that applies to this case's taxonomy variant code, each run
    against the real investigation data — PRD §4.5's "which playbooks ran" structured requirement."""
    return [run_playbook(p, plan, ipdmc) for p in pb.applicable(variant_code)]
