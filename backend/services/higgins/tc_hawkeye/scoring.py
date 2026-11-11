"""TC Hawkeye — Findings Rating: the 0-100 weighted scoring engine behind the four Findings.

finding_rules.py's S1-S4 / N1-N4 / L1-L3 rules still gather and explain the evidence — their
``deciding_rules`` / ``rules_passed`` keep feeding Higgins' narrative and decide.py's routing — but
which of the four Findings applies is now decided here, from a 0-100 score across six investigative
dimensions (Apollo PRD v2.2 §2):

    dimension                  max
    scam_mechanism              25
    requested_action            20
    identity_destination        20
    manipulation_behaviour      15
    knowledge_base               10
    evidence_corroboration       10
                                ---
                                100

Final rating = bounded(0, 100, benign_baseline_or(dimension_sum) - legitimacy_credit), then a
decisive-mechanism floor of 85 is applied last — established critical scam evidence always outranks
a legitimacy credit (PRD §2.3.D: "Decisive scam evidence takes precedence over general
sender-authentication credits").

Classification bands (exact, inclusive boundaries — PRD §2.1):
    85-100  scam            "This is a Scam"
    60-84   likely_scam     "This is Likely a Scam"
    25-59   unlikely_scam   "This is Unlikely a Scam"
    0-24    not_scam        "This is Not a Scam"

Note on calibration: the dimensions below are driven entirely by what Higgins Triage and TC Hawkeye's own
checks already established (IPDMCChecks, the Plan's pattern match, entities and live evidence) — never
by new keyword scoring on raw text. A message this scorer has no verified legitimacy evidence for (no
confirmed identity, no confirmed destination, no matched transaction) gets the ordinary "unlikely a
scam" baseline, never a false "not a scam": that requires Triage to have actually captured positive
verification, not just the absence of a request.

Correction (ApolloSG Developer Instructions — "Correct Benign Baseline Invocation and Mandatory Magnum
DI Escalation"): the benign floor is restricted to exactly two approved, evidence-backed criteria
(`benign_trigger()` below) — never merely an absence of positive verification:

  1. Investigation failure — a technical, verification-service, evidence-processing, evidence-integrity
     or investigation-execution failure genuinely prevented a required check from completing or being
     processed reliably (`_investigation_failure()`): a check TC Hawkeye planned stayed "unavailable",
     an optional provider failed on something nothing else already resolved (the same test
     decide.technical_issue() applies), or submitted evidence couldn't be extracted/processed at all
     (`plan.gaps`).
  2. Conflicting investigative results — materially contradictory findings TC Hawkeye could not
     reliably reconcile (`ipdmc.has_contradictions`, already gathered by finding_rules.gather_ipdmc from
     an unresolved "Conflict" open_issue or a scam-pattern match beside the organisation's own routes).

A successfully completed check that simply found nothing (`not_found`), or an ordinary message with
nothing to check and nothing wrong, never qualifies on its own — that's an informational vacuum, not a
failure, and is scored on its own (ordinarily calculated) merits. Decisive scam evidence is never diluted
by the floor either way: the floor only ever raises a lower calculated score, never lowers a higher one
(`score < BENIGN_BASELINE` below), so an established threat always still wins.

Whenever the floor actually fires, decide.py mandates handing the case to Magnum DI (never resolving it
at TC Hawkeye alone) — see decide.evaluate()'s use of this module's `benign_trigger`/`ScoreBreakdown.
benign_baseline_applied`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.higgins.tc_hawkeye.checks import corroborated_impersonation
from services.higgins.tc_hawkeye.finding_rules import IPDMCChecks, established_scam_rules
from services.higgins.tc_hawkeye.triage import Plan

# ── Constants ────────────────────────────────────────────────────────────────

BENIGN_BASELINE = 28   # PRD §2.3.C — the ordinary, unverified default. Nothing concerning found is not
                        # the same as positively verified, so this never rounds down to "not a scam".
DECISIVE_FLOOR = 85    # PRD §2.3.A — an established critical scam mechanism is never scored below this.
IMPERSONATION_FLOOR = 65  # a confirmed false identity (lookalike domain / corroborated impersonation)
                           # is, on its own, already "substantial evidence of fraud" (PRD §2.1's "likely
                           # a scam" bar) — matches the old L1 rule's guarantee that strong impersonation
                           # alone settles at "likely", never softened down by the benign baseline logic.

DIMENSION_MAXIMA = {
    "scam_mechanism": 25, "requested_action": 20, "identity_destination": 20,
    "manipulation_behaviour": 15, "knowledge_base": 10, "evidence_corroboration": 10,
}

# Decisive scam-mechanism overrides (PRD §2.3.A) — matched against the request's own quoted text,
# never against the whole message, so an unrelated mention elsewhere never triggers the floor.
_OTP_ASK = re.compile(
    r"password|passcode|\bpin\b|one[- ]time|otp|verification\s+code|security\s+code"
    r"|code\s+(?:we|you)|card\s+(?:number|details)|cvv", re.I,
)
_WALLET_ASK = re.compile(
    r"seed\s+phrase|recovery\s+phrase|wallet\s+(?:phrase|key)|private\s+key"
    r"|sign\s+(?:this|the)\s+(?:transaction|approval)|approve\s+(?:this|the)\s+(?:wallet|transaction)", re.I,
)
_EXTORTION_ASK = re.compile(
    r"\bransom\b|\bencrypted\s+your\s+files\b|\brelease\s+the\s+video\b|\bexpose\s+you\b|\bblackmail\b"
    r"|\bpay\s+(?:up|us)\s+or\b|\b(?:bitcoin|crypto|usdt)\b[^.?!\n]{0,60}\b(?:pay|send)\b", re.I,
)


@dataclass
class DimensionScore:
    key: str
    label: str
    points: int
    maximum: int
    why: str = ""
    # Added for DI Scoring Transparency — real data already gathered by Higgins Triage/TC Hawkeye,
    # never fabricated: which checks this dimension actually drew on, the real evidence text behind
    # its points, and which of those checks were unavailable/incomplete (never reported as if clean).
    checks: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    """Explainable attribution behind one Findings Rating (PRD §2.5.1 / §2.5.8)."""
    dimensions: list[DimensionScore] = field(default_factory=list)
    baseline: int = 0                    # the six-dimension sum, before any adjustment
    benign_baseline_applied: bool = False
    legitimacy_credit: int = 0
    legitimacy_reason: str = ""
    decisive_floor_applied: bool = False
    decisive_mechanism: str | None = None
    rating: int = 0
    finding: str = "unlikely_scam"
    # The specific, evidence-backed reason the benign floor fired (empty when it didn't) — never the
    # generic "nothing was positively verified" phrase alone (Developer Instructions: "Correct the
    # Benign Baseline Rule"). States exactly what remained unresolved, not merely that full
    # legitimacy wasn't confirmed.
    benign_baseline_trigger: str = ""
    # Added for DI Scoring Transparency (never recomputed client-side — this *is* the real sequence
    # score_plan() just ran, PRD §2.3.D order: baseline -> benign floor -> legitimacy credit ->
    # impersonation/corroboration floor -> decisive floor -> 0-100 clamp).
    calculation_trace: list[dict] = field(default_factory=list)
    narrative: str = ""
    content_gaps: list[str] = field(default_factory=list)   # material TC Hawkeye couldn't read at all (PRD §8.4/§5 completeness)

    def wire(self) -> dict:
        return {
            "rating": self.rating, "finding": self.finding,
            "dimensions": [{"key": d.key, "label": d.label, "points": d.points, "max": d.maximum, "why": d.why,
                           "checks": d.checks, "evidence": d.evidence, "missing": d.missing}
                           for d in self.dimensions],
            "baseline": self.baseline, "benignBaselineApplied": self.benign_baseline_applied,
            "benignBaselineTrigger": self.benign_baseline_trigger,
            "legitimacyCredit": self.legitimacy_credit, "legitimacyReason": self.legitimacy_reason,
            "decisiveFloorApplied": self.decisive_floor_applied, "decisiveMechanism": self.decisive_mechanism,
            "calculationTrace": self.calculation_trace, "narrative": self.narrative, "contentGaps": self.content_gaps,
        }


def classify_finding(score: int) -> str:
    """The four Findings, by exact inclusive score boundary (PRD §2.1 / §2.5.10).

    Boundary contract (must hold exactly): 24→not_scam, 25→unlikely_scam, 59→unlikely_scam,
    60→likely_scam, 84→likely_scam, 85→scam.
    """
    if not 0 <= score <= 100:
        raise ValueError("Findings rating must be between 0 and 100")
    if score >= 85:
        return "scam"
    elif score >= 60:
        return "likely_scam"
    elif score >= 25:
        return "unlikely_scam"
    else:
        return "not_scam"


# ── The six dimensions ───────────────────────────────────────────────────────

def _scam_mechanism(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "scam_mechanism", "Scam Mechanism"
    decisive = any(f.get("decisive") and f["signal"] == "concern"
                   for c in plan.checks for f in c.facts if f.get("class") == "live_evidence")
    pattern = plan.pattern
    if decisive:
        return DimensionScore(m, lbl, 25, 25, "An authoritative source has already listed this as a scam.")
    if ipdmc.identity_is_false and ipdmc.purpose_is_deceptive:
        return DimensionScore(m, lbl, 25, 25, "A false identity is established and is being used for a deceptive purpose.")
    if pattern and pattern.get("stage") == "full" and ipdmc.mechanism_evidence:
        return DimensionScore(m, lbl, 25, 25, f"Fully matches Apollo's known \u201c{pattern.get('name', '')}\u201d scam pattern, with independent supporting evidence.")
    if ipdmc.has_deception and ipdmc.consequential_requests:
        return DimensionScore(m, lbl, 20, 25, "An established deceptive activity is paired with a consequential request.")
    if pattern and pattern.get("stage") == "full":
        return DimensionScore(m, lbl, 22, 25, f"Fully matches Apollo's known \u201c{pattern.get('name', '')}\u201d scam pattern.")
    if pattern and pattern.get("stage") == "opening":
        return DimensionScore(m, lbl, 14, 25, f"Matches the opening of the {pattern.get('name', 'known')} scam pattern.")
    if ipdmc.identity_is_false:
        # A lookalike/deceptive domain is itself a recognised scam mechanism, even with nothing else
        # established yet (no separate deceptive purpose claim, no pattern match).
        return DimensionScore(m, lbl, 20, 25, "A lookalike or otherwise falsified identity/domain is established.")
    if ipdmc.has_impersonation:
        return DimensionScore(m, lbl, 10, 25, "An organisation is named beside a route that isn't its own.")
    return DimensionScore(m, lbl, 0, 25, "No recognised scam mechanism established.")


def _requested_action(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "requested_action", "Requested Action"
    if not ipdmc.consequential_requests:
        return DimensionScore(m, lbl, 0, 20, "Nothing consequential is being asked for.")
    unverified = bool(ipdmc.unverified_destinations) or ipdmc.destinations_verified != "passed"
    if unverified:
        return DimensionScore(m, lbl, 20, 20, "A consequential request (credentials, money, remote access or changed payment details) through a route nobody has verified.")
    return DimensionScore(m, lbl, 5, 20, "A consequential request, but through a verified official route.")


def _identity_destination(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "identity_destination", "Identity & Destination"
    if ipdmc.identity_is_false and (ipdmc.unverified_destinations or ipdmc.destinations_verified == "failed"):
        return DimensionScore(m, lbl, 20, 20, "A false identity and an unverified or concerning destination.")
    if ipdmc.identity_is_false or ipdmc.destinations_verified == "failed":
        return DimensionScore(m, lbl, 18, 20, "Either the claimed identity or a destination is established as false — a lookalike domain is itself a deceptive destination.")
    if ipdmc.identity_verified == "passed" and ipdmc.destinations_verified == "passed":
        return DimensionScore(m, lbl, 0, 20, "Identity and destinations are both positively verified.")
    return DimensionScore(m, lbl, 0, 20, "Identity and/or destinations aren't positively verified either way, but nothing concerning was found.")


def _manipulation_behaviour(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "manipulation_behaviour", "Manipulation & Behaviour"
    terms = len(getattr(plan.entities, "urgency", None) or [])
    bonus = 1 if ipdmc.consequential_requests else 0
    hits = terms + bonus
    if hits >= 3:
        return DimensionScore(m, lbl, 15, 15, "Multiple urgency/coercion cues, paired with a consequential request.")
    if terms >= 2:
        return DimensionScore(m, lbl, 10, 15, "Multiple urgency or coercion cues found.")
    if terms == 1:
        return DimensionScore(m, lbl, 6, 15, "An urgency or coercion cue found.")
    return DimensionScore(m, lbl, 0, 15, "No urgency, coercion or secrecy language found.")


def _knowledge_base(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "knowledge_base", "Knowledge Base Intelligence"
    pattern = plan.pattern
    if pattern and pattern.get("stage") == "full":
        return DimensionScore(m, lbl, 10, 10, f"Matches Apollo's knowledge base pattern \u201c{pattern.get('name', '')}\u201d.")
    if pattern and pattern.get("stage") == "opening":
        return DimensionScore(m, lbl, 6, 10, f"Matches the opening of Apollo's \u201c{pattern.get('name', '')}\u201d pattern.")
    if plan.advisories:
        return DimensionScore(m, lbl, 5, 10, "Apollo's knowledge base holds a related advisory.")
    return DimensionScore(m, lbl, 0, 10, "No knowledge base match.")


def _evidence_corroboration(plan: Plan, ipdmc: IPDMCChecks) -> DimensionScore:
    m, lbl = "evidence_corroboration", "Evidence Corroboration"
    groups = {(c.kind, f.get("topic")) for c in plan.checks for f in c.facts
             if f.get("class") == "live_evidence" and f["signal"] in ("concern", "anomaly")}
    n = len(groups)
    pattern = plan.pattern
    if pattern and pattern.get("stage") == "full":
        # A full KB pattern match is itself several converging textual cues (that's how it matched).
        n = max(n, 3)
    elif pattern and pattern.get("stage") == "opening":
        n = max(n, 1)
    if n >= 3:
        return DimensionScore(m, lbl, 10, 10, f"{n} independent warning signals corroborate each other.")
    if n == 2:
        return DimensionScore(m, lbl, 6, 10, "Two independent warning signals corroborate each other.")
    if n == 1:
        return DimensionScore(m, lbl, 3, 10, "One warning signal recorded, not yet independently corroborated.")
    return DimensionScore(m, lbl, 0, 10, "No corroborating evidence recorded.")


_DIMENSION_FUNCS = (_scam_mechanism, _requested_action, _identity_destination, _manipulation_behaviour,
                    _knowledge_base, _evidence_corroboration)

# ── DI Scoring Transparency: real-data enrichment, never fabricated ─────────
# Which check kinds each dimension actually draws its evidence from (triage.py's Check.kind values).
_DIMENSION_CHECK_KINDS: dict[str, tuple[str, ...]] = {
    "scam_mechanism": ("link", "phone", "email", "impersonation", "message_analysis"),
    "requested_action": ("link", "phone", "email"),
    "identity_destination": ("impersonation", "link", "phone", "email"),
    "manipulation_behaviour": (),          # text/entity analysis, not an external check
    "knowledge_base": (),                   # an internal KB lookup, not a Check
    "evidence_corroboration": ("link", "phone", "email", "impersonation"),
}


def _check_summaries(plan: Plan, kinds: tuple[str, ...]) -> list[dict]:
    """The checks that ran (or weren't needed). An unavailable check is listed once, under missing evidence —
    never under "checks performed" as well (owner, 2026-11-08)."""
    return [{"kind": c.kind, "subject": c.subject, "status": c.status} for c in plan.checks
            if c.kind in kinds and c.status != "unavailable"]


def _missing_checks(plan: Plan, kinds: tuple[str, ...]) -> list[str]:
    return [f"{c.kind} check on {c.subject}: unavailable" for c in plan.checks
           if c.kind in kinds and c.status == "unavailable"]


def _enrich_with_real_evidence(breakdown: ScoreBreakdown, plan: Plan, ipdmc: IPDMCChecks) -> None:
    """Attaches, to each already-scored dimension, exactly the checks/evidence/missing-checks data
    Higgins Triage and TC Hawkeye already gathered for it — nothing here changes a single point or
    a single `why` sentence; it only exposes the real trace behind them (PRD's DI Scoring
    Transparency requirements 3 and 5: missing evidence is listed as missing, never as "confirmed
    clean").

    Evidence Corroboration counts the warning signals the rows above already show, so it lists only
    what those rows didn't — the same line is never printed twice in one breakdown (owner, 2026-11-08)."""
    evidence_by_key = {
        "scam_mechanism": list(dict.fromkeys(ipdmc.mechanism_evidence)),
        "requested_action": list(dict.fromkeys(ipdmc.destination_evidence)),
        "identity_destination": list(dict.fromkeys(ipdmc.identity_evidence + ipdmc.destination_evidence)),
        "manipulation_behaviour": list(getattr(plan.entities, "urgency", None) or []),
        "knowledge_base": ([f"Matches Apollo's \u201c{plan.pattern.get('name', '')}\u201d pattern"] if plan.pattern
                           else [a.get("title", "") for a in (plan.advisories or [])]),
        "evidence_corroboration": list(dict.fromkeys(
            f["text"] for c in plan.checks for f in c.facts
            if f.get("class") == "live_evidence" and f.get("signal") in ("concern", "anomaly") and f.get("text")
        )),
    }
    shown_evidence: set[str] = set()
    shown_checks: set[tuple[str, str]] = set()
    shown_missing: set[str] = set()
    for d in breakdown.dimensions:
        kinds = _DIMENSION_CHECK_KINDS.get(d.key, ())
        checks = _check_summaries(plan, kinds)
        evidence = evidence_by_key.get(d.key, [])
        missing = _missing_checks(plan, kinds)
        if d.key == "evidence_corroboration":
            checks = [c for c in checks if (c["kind"], c["subject"]) not in shown_checks]
            evidence = [e for e in evidence if e not in shown_evidence]
            missing = [m for m in missing if m not in shown_missing]
        d.checks, d.evidence, d.missing = checks, evidence, missing
        shown_checks.update((c["kind"], c["subject"]) for c in checks)
        shown_evidence.update(evidence)
        shown_missing.update(missing)


def _build_calculation_trace(breakdown: ScoreBreakdown) -> list[dict]:
    """The exact arithmetic score_plan() just performed, as an ordered, human-readable trace — the UI
    renders this list verbatim, it never recomputes anything."""
    trace = [{"step": "Six-dimension baseline",
             "detail": " + ".join(f"{d.label} {d.points}" for d in breakdown.dimensions) + f" = {breakdown.baseline}",
             "value": breakdown.baseline}]
    running = breakdown.baseline
    if breakdown.benign_baseline_applied:
        trace.append({"step": "Benign baseline applied",
                     "detail": breakdown.benign_baseline_trigger or
                               f"No positive verification was established, so the ordinary unverified floor "
                               f"of {BENIGN_BASELINE} applies instead of the lower {running}.",
                     "value": BENIGN_BASELINE})
        running = BENIGN_BASELINE
    if breakdown.legitimacy_credit:
        running = max(0, running - breakdown.legitimacy_credit)
        trace.append({"step": "Legitimacy credit", "detail": f"-{breakdown.legitimacy_credit} ({breakdown.legitimacy_reason})", "value": running})
    if breakdown.rating > running and not breakdown.decisive_floor_applied:
        trace.append({"step": "Impersonation/corroboration floor", "detail": f"Raised to {breakdown.rating} (PRD \u00a72.3's \u201clikely a scam\u201d floor).", "value": breakdown.rating})
    if breakdown.decisive_floor_applied:
        trace.append({"step": "Decisive mechanism floor", "detail": f"{breakdown.decisive_mechanism} \u2014 never scored below {DECISIVE_FLOOR}.", "value": DECISIVE_FLOOR})
    trace.append({"step": "Final rating (0-100)", "detail": f"{breakdown.finding}", "value": breakdown.rating})
    return trace


def _build_narrative(breakdown: ScoreBreakdown) -> str:
    """Higgins' own plain-English account of why this rating and verdict were reached — composed
    only from the structured breakdown above, never from a separate explanation."""
    label = {"scam": "This is a Scam", "likely_scam": "This is Likely a Scam",
             "unlikely_scam": "This is Unlikely a Scam", "not_scam": "This is Not a Scam"}[breakdown.finding]
    contributing = [d for d in breakdown.dimensions if d.points > 0]
    parts = [f"Higgins rated this {breakdown.rating}/100 \u2014 {label}."]
    if contributing:
        parts.append("That came from: " + "; ".join(f"{d.label} ({d.points}/{d.maximum} \u2014 {d.why})" for d in contributing) + ".")
    else:
        parts.append("None of the six dimensions found anything concerning.")
    if breakdown.benign_baseline_applied:
        parts.append(breakdown.benign_baseline_trigger or
                     f"Because nothing was positively verified either way, the rating used the ordinary "
                     f"unverified baseline of {BENIGN_BASELINE} rather than reading as confirmed-safe.")
    if breakdown.legitimacy_credit:
        parts.append(f"{breakdown.legitimacy_credit} points were credited back: {breakdown.legitimacy_reason}")
    if breakdown.decisive_floor_applied:
        parts.append(f"A decisive scam mechanism was established ({breakdown.decisive_mechanism}), which is never scored below {DECISIVE_FLOOR}, regardless of the other dimensions.")
    missing_total = sum(len(d.missing) for d in breakdown.dimensions)
    if missing_total:
        parts.append(f"{missing_total} check(s) were unavailable and are recorded as unavailable, not as evidence either way.")
    return " ".join(parts)


# ── Contextual adjustments (PRD §2.3) ───────────────────────────────────────

def _positively_verified(plan: Plan, ipdmc: IPDMCChecks) -> bool:
    """Was *something* actually, positively verified — not merely "nothing concerning found"? Broader
    than ipdmc.genuine_explanation_supported (which needs both identity AND destination independently
    confirmed): a destination match against an organisation's own official domain, with nothing else
    concerning anywhere, is already a positive verification even when there was no separate identity
    claim to check (e.g. the link already *is* the organisation's own domain).

    Never true while a consequential request (money, credentials, remote access) still points at a
    destination nobody verified (ipdmc.unverified_destinations): an official link elsewhere in the same
    message never vouches for a different, unverified payment number or account — that's exactly the
    "verify the link, redirect the money" shape genuine delivery-toll and invoice scams rely on."""
    if ipdmc.unverified_destinations:
        return False
    if ipdmc.genuine_explanation_supported:
        return True
    decisive_clear = any(f.get("decisive") and f["signal"] == "clear"
                         for c in plan.checks for f in c.facts if f.get("class") == "live_evidence")
    if decisive_clear:
        return True
    has_weak_signal = any(f["signal"] == "weak" for c in plan.checks for f in c.facts if f.get("class") == "live_evidence")
    if (ipdmc.destinations_verified == "passed" or ipdmc.identity_verified == "passed") and not (
        ipdmc.identity_is_false or ipdmc.has_impersonation or ipdmc.has_deception or has_weak_signal
    ):
        return True
    return False


def _severe_or_mule_signal(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """The two newest, narrowest-scoped independent signals — severe-consequence manipulation and
    money-mule recruitment — used specifically to decide whether an L-rule's pattern-only
    "likely_scam" (no separate S4 corroboration) should be reported as a confirmed scam instead.
    Deliberately excludes the OTP/wallet/extortion/impersonation branches above: those already have
    their own established roles (feeding S-rules via identity_is_false, or the score fallback when no
    L-rule passes at all) and must not retroactively escalate every pattern match that happens to also
    contain a credential ask — e.g. the four call-only KB patterns are correctly capped at likely_scam
    even on a full match, by PRD design, and must stay there."""
    if not ipdmc.consequential_requests:
        return None
    if getattr(plan.entities, "severe_manipulation", False):
        return "Severe-consequence manipulation (a secrecy/isolation instruction, an acute-distress appeal, or a threat of arrest or prosecution) used to extract a consequential request"
    if getattr(plan.entities, "mule_signal", False):
        return "Money-mule recruitment: asked to receive money and forward it on for a commission"
    return None


def _independent_decisive_mechanism(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """The subset of _decisive_mechanism's reasons that don't depend on the KB pattern match being its
    own corroboration — PRD §2.3.A's named critical mechanisms (OTP/credential harvesting, wallet
    exploitation, extortion, verified deceptive destinations), plus severe-consequence manipulation
    (an explicit secrecy/isolation instruction, an acute personal-danger appeal, or a threat of arrest,
    prosecution or an irreversible consequence) and money-mule recruitment. Used by decide.py to decide
    whether a pattern that only reaches L2 (a full KB pattern match with no separate S4 corroboration)
    should still be reported as a confirmed scam rather than merely likely — deliberately excludes the
    "fully-corroborated pattern" reason below, which is satisfied by the pattern match itself and so
    can't independently confirm anything beyond what L2 already establishes."""
    quotes = " ".join(r.get("quote", "") for r in ipdmc.consequential_requests)
    if any(r["type"] == "credentials" for r in ipdmc.consequential_requests) and (
        _OTP_ASK.search(quotes) or ipdmc.identity_is_false
    ):
        return "OTP, password or account-credential harvesting through a falsified identity or domain"
    if _WALLET_ASK.search(quotes):
        return "Wallet or recovery-phrase exploitation"
    if _EXTORTION_ASK.search(quotes):
        return "Extortion or ransomware demand"
    if corroborated_impersonation(plan) and any(
        f["signal"] == "concern" and f.get("decisive") for c in plan.checks if c.kind == "link" for f in c.facts
    ):
        return "Credential phishing through a verified deceptive destination"
    return _severe_or_mule_signal(plan, ipdmc)


def _l2_escalation_signal(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """Used by decide.py to decide whether an L-rule's pattern-only "likely_scam" (no separate S4
    corroboration) should be reported as a confirmed scam instead. Call-channel patterns (bank/
    government/tech-support/delivery call) are deliberately restricted to the narrower severity/mule
    signals even here: by PRD design, a phone scam that only fully matches one of those four patterns
    stays "likely" without separate corroboration, even when it also contains a credential ask — that
    ask alone must not retroactively make every such call a confirmed scam."""
    if plan.channel == "call":
        return _severe_or_mule_signal(plan, ipdmc)
    return _independent_decisive_mechanism(plan, ipdmc)


def _decisive_mechanism(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """A handful of critical exploit mechanisms that, once established, are never scored as merely
    'likely' — the floor exists because waiting for more corroboration on these specific asks causes
    real harm (PRD §2.3.A)."""
    mechanism = _independent_decisive_mechanism(plan, ipdmc)
    if mechanism:
        return mechanism
    if plan.pattern and plan.pattern.get("stage") == "full" and ipdmc.mechanism_evidence and ipdmc.consequential_requests:
        # A complete, KB-confirmed scam pattern, independently corroborated, paired with a
        # consequential request (e.g. a CEO/gift-card fraud with a confirmed fake sender) — waiting
        # for more evidence at this point causes real harm, same reasoning as the named mechanisms above.
        return f"A fully-corroborated \u201c{plan.pattern.get('name', '')}\u201d pattern paired with a consequential request"
    return _established_by_rules(plan, ipdmc)


def _established_by_rules(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """A scam the S1–S4 rules established (finding_rules.established_scam_rules) — the same condition on
    which decide.py reports "This is a scam". That verdict is what the person sees, so the rating is
    floored like any other decisive mechanism: a result shown as a scam is never rated "likely" (owner,
    2026-11-08 — a myGov lookalike sender with a tax-debt demand read "This is a scam" over "83/100 —
    Likely a Scam"). The reason is the rule's own, so the breakdown says why."""
    passed = established_scam_rules(plan, ipdmc)
    if not passed:
        return None
    rule = passed[0]
    reason = rule.reason.rstrip(".")
    return f"{reason[0].lower()}{reason[1:]} (rule {rule.rule_id})"


def _unresolved(check) -> bool:
    """A check's own facts didn't already establish or clear what it would have covered — the same test
    decide.technical_issue() applies to a provider failure, reused here (ApolloSG Developer Instructions
    §2, Criterion 1: "An optional or redundant service failure that has no effect on investigative
    reliability must not automatically invoke Benign")."""
    return not any(f.get("decisive") for f in check.facts) and not any(f["signal"] in ("concern", "clear") for f in check.facts)


def _investigation_failure(plan: Plan) -> list[str]:
    """Criterion 1 — Investigation Failure (Developer Instructions §2): a technical, verification-service,
    evidence-processing, evidence-integrity or investigation-execution failure genuinely prevented a
    required investigative operation from completing or being processed reliably. A successfully
    completed check that simply found nothing (status "not_found") is never a failure — only a check
    that stayed "unavailable", a sub-service within an otherwise-resolved check that could not be
    reached (e.g. "Google Safe Browsing could not be checked for …" — services.higgins.tc_hawkeye.
    official.answer — a "missing" fact on a check that isn't itself "not_found"), a provider failure
    nothing else already resolved, or evidence TC Hawkeye submitted but couldn't extract/decode/parse/
    analyse (`plan.gaps`) qualify."""
    reasons = [(next((f["text"] for f in c.facts if f["signal"] == "missing"), None)
               or f"the {c.kind} check on {c.subject} could not be completed")
              for c in plan.checks if c.status == "unavailable" and _unresolved(c)]
    reasons += [f"IPQualityScore timed out or failed after retrying while checking {c.subject}, with nothing else "
               f"resolving it" for c in plan.checks if c.provider_failures and c.status != "unavailable" and _unresolved(c)]
    reasons += [f["text"] for c in plan.checks for f in c.facts
               if f["signal"] == "missing" and c.status not in ("unavailable", "not_found") and _unresolved(c)]
    reasons += [f"{g['item']} could not be reliably processed ({g['what']})" for g in (plan.gaps or [])]
    return reasons


def _conflicting_results(ipdmc: IPDMCChecks) -> list[str]:
    """Criterion 2 — Conflicting Investigative Results (Developer Instructions §2): materially
    contradictory investigative findings TC Hawkeye could not reliably reconcile — already gathered by
    finding_rules.gather_ipdmc (an unresolved "Conflict" open_issue, e.g. a register entry under a
    related-but-different name, or a scam-pattern match beside the organisation's own, genuine routes).
    Excludes a contradiction finding_rules.gather_ipdmc itself already reconciled with a genuine
    explanation (`genuine_explanation_supported` — identity and destinations both positively verified,
    with nothing else concerning) — that one was successfully reconciled, not left unresolved.
    Where the contradiction itself already establishes deception, an S-rule/decisive mechanism applies
    its own floor (never below 85) regardless of this one, so it is never diluted by the benign floor —
    the two floors only ever raise a score with `max()`, never lower it."""
    if not ipdmc.has_contradictions or ipdmc.genuine_explanation_supported:
        return []
    return list(ipdmc.contradiction_details)


def benign_trigger(plan: Plan, ipdmc: IPDMCChecks) -> tuple[str, list[str]] | None:
    """Whether the Benign Baseline may fire at all, restricted to exactly the two approved criteria
    (Developer Instructions §2/§6) — never merely because nothing was positively verified either way.
    Returns (category, reasons) or None. `category`: "investigation_failure" | "conflicting_results".
    The single source of truth for Benign eligibility: decide.py reads the same result (via this
    module's ScoreBreakdown.benign_baseline_applied) to mandate Magnum DI escalation, rather than
    re-deciding eligibility on its own."""
    failures = _investigation_failure(plan)
    if failures:
        return "investigation_failure", failures
    conflicts = _conflicting_results(ipdmc)
    if conflicts:
        return "conflicting_results", conflicts
    return None


def _benign_baseline_trigger_text(trigger: tuple[str, list[str]], baseline: int) -> str:
    """The specific, traceable reason the floor fired — states exactly what failed or conflicted
    (Developer Instructions §2: specific trigger, supporting evidence, traceability, rating
    justification), never a generic "nothing was positively verified" phrase — and states plainly that
    the investigation has been handed over to Magnum DI (Developer Instructions §3: mandatory
    escalation), not left as TC Hawkeye's own, final word."""
    category, reasons = trigger
    what = ("TC Hawkeye could not reliably complete or process part of this investigation" if category == "investigation_failure"
           else "TC Hawkeye found materially contradictory investigative results it could not reliably reconcile")
    joined = "; ".join(r.rstrip(". ") for r in reasons)
    return (f"The calculated six-dimension score ({baseline}/100) is not itself a reason for concern, but it "
            f"also isn't a confirmed-safe result: {what} — {joined}. Because of this, the "
            f"investigation has been handed over to Magnum DI to look into the whole case — this {BENIGN_BASELINE}-"
            f"point floor is provisional, not confirmation of a scam, and Magnum DI may remove it with evidence "
            f"that resolves it, or confirm a higher rating the evidence supports.")


def _legitimacy_credit(plan: Plan, ipdmc: IPDMCChecks) -> tuple[int, str]:
    """PRD §2.3.B — a reduction of 20-30 points when something is positively verified, with nothing
    else outstanding that's concerning."""
    if not _positively_verified(plan, ipdmc):
        return 0, ""
    decisive_clear = any(f.get("decisive") and f["signal"] == "clear"
                         for c in plan.checks for f in c.facts if f.get("class") == "live_evidence")
    if decisive_clear:
        return 30, "An authoritative source positively confirmed the identity and destination."
    return 25, "Identity and destinations are both positively verified, with no unresolved warning."


# ── Final rating ─────────────────────────────────────────────────────────────

def score_plan(plan: Plan, ipdmc: IPDMCChecks) -> ScoreBreakdown:
    """The Findings Rating (0-100) and its four-tier classification, per PRD §2.3.D's sequence:
    six-dimension baseline → benign floor → legitimacy credit → decisive mechanism floor → bound → classify.
    """
    dims = [fn(plan, ipdmc) for fn in _DIMENSION_FUNCS]
    baseline = sum(d.points for d in dims)
    breakdown = ScoreBreakdown(dimensions=dims, baseline=baseline)

    score = baseline
    trigger = benign_trigger(plan, ipdmc)
    if trigger and score < BENIGN_BASELINE:
        # Developer Instructions §2/§6 — the floor fires on exactly the two approved criteria
        # (benign_trigger: a genuine investigation failure, or an unresolved material contradiction),
        # never merely because nothing was positively verified either way. It only ever raises a lower
        # calculated score, never lowers a higher one, so established scam evidence is never diluted.
        score = BENIGN_BASELINE
        breakdown.benign_baseline_applied = True
        breakdown.benign_baseline_trigger = _benign_baseline_trigger_text(trigger, baseline)

    credit, reason = _legitimacy_credit(plan, ipdmc)
    if credit:
        score = max(0, score - credit)
        breakdown.legitimacy_credit = credit
        breakdown.legitimacy_reason = reason

    if ipdmc.identity_is_false or ipdmc.has_impersonation:
        score = max(score, IMPERSONATION_FLOOR)

    corroboration_pts = next(d.points for d in dims if d.key == "evidence_corroboration")
    action_pts = next(d.points for d in dims if d.key == "requested_action")
    if corroboration_pts >= 6 and action_pts >= 15:
        # PRD's old L3 equivalent: two or more independent warning signals, converging with a
        # consequential request through an unverified route, is already substantial evidence —
        # the same "likely a scam" floor as a confirmed false identity, even without one.
        score = max(score, IMPERSONATION_FLOOR)

    mechanism = _decisive_mechanism(plan, ipdmc)
    if mechanism:
        score = max(score, DECISIVE_FLOOR)
        breakdown.decisive_floor_applied = True
        breakdown.decisive_mechanism = mechanism

    breakdown.rating = max(0, min(100, score))
    breakdown.finding = classify_finding(breakdown.rating)

    # DI Scoring Transparency — attach the real trace behind the number above; changes nothing already decided.
    _enrich_with_real_evidence(breakdown, plan, ipdmc)
    breakdown.content_gaps = [f"{g.get('item', '')}: {g.get('what', '')}" for g in (plan.gaps or [])]
    breakdown.calculation_trace = _build_calculation_trace(breakdown)
    breakdown.narrative = _build_narrative(breakdown)
    return breakdown
