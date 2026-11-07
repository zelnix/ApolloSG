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
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.higgins.tc_flyby.checks import corroborated_impersonation
from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import Plan

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

    def wire(self) -> dict:
        return {
            "rating": self.rating, "finding": self.finding,
            "dimensions": [{"key": d.key, "label": d.label, "points": d.points, "max": d.maximum, "why": d.why}
                           for d in self.dimensions],
            "baseline": self.baseline, "benignBaselineApplied": self.benign_baseline_applied,
            "legitimacyCredit": self.legitimacy_credit, "legitimacyReason": self.legitimacy_reason,
            "decisiveFloorApplied": self.decisive_floor_applied, "decisiveMechanism": self.decisive_mechanism,
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
    if not _positively_verified(plan, ipdmc) and score < BENIGN_BASELINE:
        # PRD §2.3.C — ordinary, unverified communications never read as "not a scam" just because a
        # handful of ambiguous points happened to add up low: nothing concerning was found, but nothing
        # was positively verified either, so the floor is "unlikely a scam", not "not a scam".
        score = BENIGN_BASELINE
        breakdown.benign_baseline_applied = True

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
    return breakdown
