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

Final rating = bounded(0, 100, dimension_sum - legitimacy_credit), then an impersonation/
corroboration floor of 65 and a decisive-mechanism floor of 85 are applied last — established
critical scam evidence always outranks a legitimacy credit (PRD §2.3.D: "Decisive scam evidence
takes precedence over general sender-authentication credits"). The rating is **never** adjusted
upward merely because verification is missing — see the Correction note below.

Classification bands (exact, inclusive score boundaries — PRD §2.1):
    85-100  scam            "This is a Scam"
    60-84   likely_scam     "This is Likely a Scam"
    25-59   unlikely_scam   "This is Unlikely a Scam"
    0-24    not_scam        "This is Not a Scam" — but only when verification was actually
                             established; otherwise "unlikely_scam" (see Correction below).

Note on calibration: the dimensions below are driven entirely by what Higgins Triage and TC Hawkeye's own
checks already established (IPDMCChecks, the Plan's pattern match, entities and live evidence) — never
by new keyword scoring on raw text.

Correction (Developer Instructions — "Clarification of Scoring and Findings Requirements"): a
message with no substantive scam indicators scores 0-24 on real, evidence-based dimension points
alone — nothing is ever added to the number just because verification wasn't performed, available
or necessary (an absence of positive verification is not evidence of malicious activity). What used
to be a score-inflating "benign baseline" is now a *separate* axis entirely: `verification_established`
(§_positively_verified) plus a `verification_note` that explains, honestly, why this message's
authenticity has or hasn't been independently established. `classify_finding()` reads *both* axes: a
score of 0-24 reads "Not a Scam" only when verification was actually established; otherwise it reads
"Unlikely a Scam" ("no scam indicators were identified, but authenticity hasn't been independently
established") — the same real number, never an invented one, under a Finding that no longer silently
equals "confirmed safe". All four Findings, and every score-boundary rule at 25+, are unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.higgins.tc_flyby.checks import corroborated_impersonation
from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import Plan

# ── Constants ────────────────────────────────────────────────────────────────

DECISIVE_FLOOR = 85    # PRD §2.3.A — an established critical scam mechanism is never scored below this.
IMPERSONATION_FLOOR = 65  # a confirmed false identity (lookalike domain / corroborated impersonation)
                           # is, on its own, already "substantial evidence of fraud" (PRD §2.1's "likely
                           # a scam" bar) — matches the old L1 rule's guarantee that strong impersonation
                           # alone settles at "likely", never softened down by verification status.

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
    legitimacy_credit: int = 0
    legitimacy_reason: str = ""
    decisive_floor_applied: bool = False
    decisive_mechanism: str | None = None
    rating: int = 0
    finding: str = "unlikely_scam"
    # Verification completeness — a separate axis from scam risk (Developer Instructions:
    # "Clarification of Scoring and Findings Requirements"). `verification_established` gates the
    # not_scam/unlikely_scam boundary in `classify_finding()`; it never changes `rating`.
    verification_established: bool = False
    verification_note: str = ""
    # Added for DI Scoring Transparency (never recomputed client-side — this *is* the real sequence
    # score_plan() just ran, PRD §2.3.D order: baseline -> legitimacy credit -> impersonation/
    # corroboration floor -> decisive floor -> 0-100 clamp -> verification-gated classification).
    calculation_trace: list[dict] = field(default_factory=list)
    narrative: str = ""
    content_gaps: list[str] = field(default_factory=list)   # material TC Hawkeye couldn't read at all (PRD §8.4/§5 completeness)

    def wire(self) -> dict:
        return {
            "rating": self.rating, "finding": self.finding,
            "dimensions": [{"key": d.key, "label": d.label, "points": d.points, "max": d.maximum, "why": d.why,
                           "checks": d.checks, "evidence": d.evidence, "missing": d.missing}
                           for d in self.dimensions],
            "baseline": self.baseline,
            "verificationEstablished": self.verification_established, "verificationNote": self.verification_note,
            "legitimacyCredit": self.legitimacy_credit, "legitimacyReason": self.legitimacy_reason,
            "decisiveFloorApplied": self.decisive_floor_applied, "decisiveMechanism": self.decisive_mechanism,
            "calculationTrace": self.calculation_trace, "narrative": self.narrative, "contentGaps": self.content_gaps,
        }


def classify_finding(score: int, verification_established: bool = True) -> str:
    """The four Findings, by exact inclusive score boundary (PRD §2.1 / §2.5.10), gated by whether
    verification was actually established (Developer Instructions correction).

    Boundary contract (must hold exactly) when verification_established is True (unchanged):
    24→not_scam, 25→unlikely_scam, 59→unlikely_scam, 60→likely_scam, 84→likely_scam, 85→scam.

    When verification_established is False, the 0-24 band reads "unlikely_scam" instead of
    "not_scam" — a real, unmodified score under an honest Finding, never an invented point. Every
    boundary at 25 and above is identical either way: missing verification never raises the score,
    it only prevents a low, genuinely clean score from being read as "confirmed safe".
    """
    if not 0 <= score <= 100:
        raise ValueError("Findings rating must be between 0 and 100")
    if score >= 85:
        return "scam"
    elif score >= 60:
        return "likely_scam"
    elif score >= 25:
        return "unlikely_scam"
    elif verification_established:
        return "not_scam"
    else:
        return "unlikely_scam"


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
    return [{"kind": c.kind, "subject": c.subject, "status": c.status} for c in plan.checks if c.kind in kinds]


def _missing_checks(plan: Plan, kinds: tuple[str, ...]) -> list[str]:
    return [f"{c.kind} check on {c.subject}: unavailable" for c in plan.checks
           if c.kind in kinds and c.status == "unavailable"]


def _enrich_with_real_evidence(breakdown: ScoreBreakdown, plan: Plan, ipdmc: IPDMCChecks) -> None:
    """Attaches, to each already-scored dimension, exactly the checks/evidence/missing-checks data
    Higgins Triage and TC Hawkeye already gathered for it — nothing here changes a single point or
    a single `why` sentence; it only exposes the real trace behind them (PRD's DI Scoring
    Transparency requirements 3 and 5: missing evidence is listed as missing, never as "confirmed
    clean")."""
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
    for d in breakdown.dimensions:
        kinds = _DIMENSION_CHECK_KINDS.get(d.key, ())
        d.checks = _check_summaries(plan, kinds)
        d.evidence = evidence_by_key.get(d.key, [])
        d.missing = _missing_checks(plan, kinds)


def _build_calculation_trace(breakdown: ScoreBreakdown) -> list[dict]:
    """The exact arithmetic score_plan() just performed, as an ordered, human-readable trace — the UI
    renders this list verbatim, it never recomputes anything."""
    trace = [{"step": "Six-dimension baseline",
             "detail": " + ".join(f"{d.label} {d.points}" for d in breakdown.dimensions) + f" = {breakdown.baseline}",
             "value": breakdown.baseline}]
    running = breakdown.baseline
    if breakdown.legitimacy_credit:
        running = max(0, running - breakdown.legitimacy_credit)
        trace.append({"step": "Legitimacy credit", "detail": f"-{breakdown.legitimacy_credit} ({breakdown.legitimacy_reason})", "value": running})
    if breakdown.rating > running and not breakdown.decisive_floor_applied:
        trace.append({"step": "Impersonation/corroboration floor", "detail": f"Raised to {breakdown.rating} (PRD \u00a72.3's \u201clikely a scam\u201d floor).", "value": breakdown.rating})
    if breakdown.decisive_floor_applied:
        trace.append({"step": "Decisive mechanism floor", "detail": f"{breakdown.decisive_mechanism} \u2014 never scored below {DECISIVE_FLOOR}.", "value": DECISIVE_FLOOR})
    # Verification completeness never changes the number above — shown as its own step so it can
    # never be mistaken for a score adjustment (Developer Instructions).
    trace.append({"step": "Verification check (context only \u2014 does not change the score)",
                 "detail": breakdown.verification_note, "value": breakdown.rating})
    trace.append({"step": "Final rating (0-100)", "detail": breakdown.finding, "value": breakdown.rating})
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
        parts.append("No scam indicators were identified.")
    parts.append(breakdown.verification_note)
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


def _decisive_mechanism(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """A handful of critical exploit mechanisms that, once established, are never scored as merely
    'likely' — the floor exists because waiting for more corroboration on these specific asks causes
    real harm (PRD §2.3.A)."""
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
    if plan.pattern and plan.pattern.get("stage") == "full" and ipdmc.mechanism_evidence and ipdmc.consequential_requests:
        # A complete, KB-confirmed scam pattern, independently corroborated, paired with a
        # consequential request (e.g. a CEO/gift-card fraud with a confirmed fake sender) — waiting
        # for more evidence at this point causes real harm, same reasoning as the named mechanisms above.
        return f"A fully-corroborated \u201c{plan.pattern.get('name', '')}\u201d pattern paired with a consequential request"
    return None


def _checked_and_clean(plan: Plan, ipdmc: IPDMCChecks) -> bool:
    """Retained as a pure diagnostic predicate (used by `_verification_note` for wording only): true
    when nothing about this message remains unresolved, and whatever TC Hawkeye actually checked
    came back clean. No longer gates a score adjustment — verification completeness never changes
    `rating` (Developer Instructions: "Clarification of Scoring and Findings Requirements")."""
    if ipdmc.consequential_requests and (ipdmc.unverified_destinations or ipdmc.destinations_verified != "passed"):
        return False
    all_facts = [f for c in plan.checks for f in c.facts if f.get("class") == "live_evidence"]
    if not all_facts:
        return False
    if any(f["signal"] in ("concern", "anomaly", "weak", "missing") for f in all_facts):
        return False
    return any(f["signal"] in ("clear", "neutral") for f in all_facts)


def _verification_note(plan: Plan, ipdmc: IPDMCChecks, verified: bool, score: int) -> str:
    """Honest, evidence-backed context on verification completeness — a separate axis from scam
    risk (Developer Instructions). Never implies risk by itself; always populated, so the DI tab can
    show it beside the (unmodified) score without a contradictory-looking gap between the two."""
    if verified:
        return "This message's identity and/or destination were positively verified, with nothing concerning found."
    if score > 0:
        # Real scam indicators already contributed to the score above — don't also claim "none found".
        return "This message's authenticity has not been independently established, separately from the scam indicators already reflected in the score above."
    base = "No scam indicators were identified, but the message's authenticity has not been independently established."
    if not plan.checks:
        return base
    unavailable_kinds = sorted({c.kind for c in plan.checks if c.status == "unavailable"})
    if unavailable_kinds:
        return base + f" The {', '.join(unavailable_kinds)} check(s) on it could not be completed."
    return base


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
    six-dimension baseline → legitimacy credit → impersonation/corroboration floor → decisive
    mechanism floor → bound → verification-gated classification (Developer Instructions
    correction — verification completeness never changes the number itself).
    """
    dims = [fn(plan, ipdmc) for fn in _DIMENSION_FUNCS]
    baseline = sum(d.points for d in dims)
    breakdown = ScoreBreakdown(dimensions=dims, baseline=baseline)

    score = baseline
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

    # Verification completeness — a separate axis from the score above (Developer Instructions):
    # missing/unavailable/unnecessary verification is never a reason to raise `rating`. It only
    # gates whether a genuinely low, evidence-based score of 0-24 reads as "Not a Scam" (verification
    # actually established) or "Unlikely a Scam" (no scam indicators found, but authenticity also
    # not independently established).
    breakdown.verification_established = _positively_verified(plan, ipdmc)
    breakdown.verification_note = _verification_note(plan, ipdmc, breakdown.verification_established, breakdown.rating)
    breakdown.finding = classify_finding(breakdown.rating, breakdown.verification_established)

    # DI Scoring Transparency — attach the real trace behind the number above; changes nothing already decided.
    _enrich_with_real_evidence(breakdown, plan, ipdmc)
    breakdown.content_gaps = [f"{g.get('item', '')}: {g.get('what', '')}" for g in (plan.gaps or [])]
    breakdown.calculation_trace = _build_calculation_trace(breakdown)
    breakdown.narrative = _build_narrative(breakdown)
    return breakdown
