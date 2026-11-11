"""TC Hawkeye — executes a Verification Playbook's steps against a real investigation (PRD v2.3 §7.5).

Never invents a result, and never represents a detection result — or a weak/incomplete lookup — as
independent external verification. Two different kinds of answer back a step, and each step's
`status` says honestly which one it got:
  - `verified`   — an already-integrated, independent, authoritative check (company/abn/acn registry,
                   link/domain reputation, phone/email/licence/person cross-reference) actually
                   produced a meaningful, evidence-backed result: one of `official.py`'s own facts
                   (`class == "live_evidence"`) whose `signal` is `concern`, `anomaly`, `clear` or
                   `neutral` — a real determination, favourable or not. `clear` and `concern` keep
                   their own meaning here: `verified` only says the check ran and produced a real
                   answer, never that the answer was reassuring. Every live-evidence fact found
                   (not only the ones that qualified the step as `verified`) is joined into the
                   evidence text, so a genuine authoritative contradiction — one source clearing an
                   item while another flags it — stays fully visible rather than collapsed into a
                   single, possibly reassuring, line.
  - `inferred`   — ApolloSG's own detection logic (a matched KB scam pattern, an extracted claim/
                   urgency phrase, a consequential request, an OTP-style ask) found a hit. This is a
                   real signal TC Hawkeye's own scoring already uses, but it is Apollo's pattern-match
                   or text extraction — not a third party confirming anything — and must never be
                   presented as if an external source verified it.
  - `inconclusive` — the relevant check or detector ran and found nothing meaningful either way. This
                   also covers a check that only produced `weak` or `missing` signal facts: by
                   `official.py`'s own signal vocabulary, `weak` "alone ... never [settles anything],
                   only the corroboration a warning sign or impersonation needs" and `missing` means
                   "looked up, not established" — neither is a completed verification by itself, so
                   neither is ever promoted to `verified`. Their text is still surfaced here (nothing
                   is thrown away), just never mislabelled as a successful check.
  - `unavailable`  — no source ApolloSG has today answers this step at all (PRD §8.5: "a lookup that
                   fails is recorded as unavailable — never as safe").
  - `not_applicable` — this case has nothing of the kind this step looks at (e.g. no links at all for
                   `link_reputation`), so the step was never run.
Every step also carries `evidenceSource` (`external_verification`, `internal_detection` or `none`),
derived from the step's own `status` — never from which resolver ran — so a step that found nothing
can never imply external verification occurred just because its resolver belongs to the external-
lookup family. This module never changes the Findings Rating — it reads the exact same
`Plan`/`IPDMCChecks` data `scoring.score_plan()` already gathered, never recomputes it.
"""
from __future__ import annotations

from services.higgins.tc_hawkeye import playbooks as pb
from services.higgins.tc_hawkeye.finding_rules import IPDMCChecks
from services.higgins.tc_hawkeye.triage import CONSEQUENTIAL, Plan

# official.py's own signal vocabulary: a fact carrying one of these signals is real evidence that was
# already read, but is explicitly never a standalone, completed verification outcome — `weak` only
# corroborates something else, `missing` means a lookup ran and found nothing to report. Everything
# else (`concern`, `anomaly`, `clear`, `neutral`) is a genuine, evidence-backed determination.
_NON_VERIFYING_SIGNALS = {"weak", "missing"}


def _facts_of(plan: Plan, kinds: tuple[str, ...]) -> tuple[list[dict], list]:
    checks = [c for c in plan.checks if c.kind in kinds]
    facts = [f for c in checks for f in c.facts if f.get("class") == "live_evidence"]
    return facts, checks


def _registry_like(plan: Plan, ipdmc: IPDMCChecks, kinds: tuple[str, ...]) -> tuple[str, str | None]:
    """External, authoritative sources only (`official.py`'s own lookups) — never Apollo's own
    pattern-matching. `verified` requires at least one fact with a meaningful signal (`concern`,
    `anomaly`, `clear` or `neutral`); `weak`/`missing`-only evidence is real but inconclusive on its
    own, so it is reported as `inconclusive`, not promoted to a completed verification."""
    facts, checks = _facts_of(plan, kinds)
    meaningful = [f for f in facts if f.get("signal") not in _NON_VERIFYING_SIGNALS]
    if meaningful:
        # All live-evidence facts are joined, not just the meaningful ones — a weak corroborating
        # detail next to a real finding, or a contradictory second finding, is never hidden.
        return "verified", "; ".join(f["text"] for f in facts)
    if facts:
        return "inconclusive", "; ".join(f["text"] for f in facts)
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
    """A matched KB scam pattern is Apollo's own detection, not an external party confirming the
    scam — `inferred`, never `verified`."""
    if plan.pattern:
        return "inferred", f"Matches Apollo's \u201c{plan.pattern.get('name')}\u201d scam pattern ({plan.pattern.get('stage')})."
    return "inconclusive", None


def _claims_and_urgency(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    """Text extraction (claims/urgency phrases) is Apollo's own NLP detection — `inferred`."""
    found = list(plan.entities.claims or []) + list(plan.entities.urgency or [])
    if found:
        return "inferred", "; ".join(found)
    return "inconclusive", None


def _consequential_request(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    """Detecting a consequential request's wording is Apollo's own extraction — `inferred`, not an
    external party confirming the request is genuine or illegitimate."""
    reqs = [r for r in plan.entities.requests if r["type"] in CONSEQUENTIAL]
    if reqs:
        return "inferred", "; ".join(r["quote"] for r in reqs)
    return "not_applicable", None


def _otp_request_check(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, str | None]:
    """Matching an OTP-style KB pattern or extracting a credentials request is Apollo's own detection
    — `inferred`, never `verified` (no external source is consulted here)."""
    key = (plan.pattern or {}).get("key") if plan.pattern else None
    if key in ("otp_bypass", "bank_code_call"):
        return "inferred", f"Matches Apollo's \u201c{plan.pattern.get('name')}\u201d OTP-request scam pattern."
    req = next((r for r in plan.entities.requests if r["type"] == "credentials"), None)
    if req:
        return "inferred", req["quote"]
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

# Evidence provenance by the step's own *outcome*, never by which resolver ran: a step that found
# nothing (not_applicable/inconclusive/unavailable) must never claim external verification or
# internal detection just because its resolver belongs to that family.
_EVIDENCE_SOURCE_BY_STATUS = {"verified": "external_verification", "inferred": "internal_detection"}


def run_step(step: pb.PlaybookStep, plan: Plan, ipdmc: IPDMCChecks) -> dict:
    status, evidence = _STEP_RESOLVERS[step.resolver](plan, ipdmc)
    return {"order": step.order, "description": step.description, "sourceIds": list(step.source_ids),
            "status": status, "evidenceSource": _EVIDENCE_SOURCE_BY_STATUS.get(status, "none"), "evidence": evidence}


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
