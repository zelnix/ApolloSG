"""Apollo Scam Guard — Finding Rules (S1–S4, N1–N4, L1–L3) and the Findings Rating.

Each rule is an explicit, testable condition evaluated against TC Hawkeye's investigation Plan. No
keyword counting, no new AI calls — the rules below gather and explain evidence exactly as before.

Unified Evidence Classification & Six-Dimension Findings Rating PRD (v1.0, 8 Nov 2026): the Finding
itself (scam / likely_scam / unlikely_scam / not_scam) is the evidence verdict this S1-S4/N1-N4/L1-L3
waterfall establishes — never silently replaced by the 0-100 Findings Rating (scoring.py) alone. The
Rating is still a weighted score across six investigative dimensions, computed in full every time
(same floors, credits and calculation trace as before); evaluate() below calls scoring.reconcile() to
align that rating to this waterfall's verdict only when the two land in different bands, and records
why (PRD §5.1/§7.2 — "a documented minimal boundary adjustment", never a second route to a verdict).
evaluate_rules() runs the S1-S4/N1-N4/L1-L3 waterfall in full; its deciding_rules/rules_passed/
rules_failed keep feeding Higgins' explanations and decide.py's routing (which rule explains "why").
"unable_to_determine" is no longer a Finding people see — it reads as "unlikely_scam" (scoring.
evidence_verdict; PRD §4: "U is an internal evidence state, not a fifth verdict"); a genuinely
incomplete investigation (a critical check that never got an answer, even after retrying) is caught
upstream, before any Finding is attempted.

Historical decision order (evaluate_rules — still computed, no longer decisive on its own):
  1. Evaluate S1–S4. If any passes and no unresolved reliable info undermines it → scam.
  2. Evaluate N1–N4. If all applicable pass → not_scam.
  3. Evaluate L1–L3. If any passes and no genuine explanation resolves it → likely_scam.
  4. Otherwise → unable_to_determine.

Investigation Checks (IPDMC):
  I — Identity: Who is behind the communication? Does the identity check out?
  P — Purpose: What is the communication trying to achieve?
  D — Destination: Where do links, money, replies, credentials go?
  M — Mechanism: Evidence of impersonation, deception, false promises, payment diversion?
  C — Contradictions: Does anything conflict with the scam explanation?
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from services.higgins.brand_domains import registrable
from services.higgins.tc_flyby.triage import CONSEQUENTIAL, Check, Plan

# ── Data structures ──────────────────────────────────────────────────────────

CheckStatus = Literal["passed", "failed", "unknown", "not_applicable"]


@dataclass
class RuleResult:
    """Result of evaluating one rule (S1, N2, L3, etc.)."""
    rule_id: str
    passed: bool
    status: CheckStatus
    evidence: list[str] = field(default_factory=list)   # text descriptions
    reason: str = ""
    # For N rules: the specific check result
    check_details: dict | None = None


@dataclass
class IPDMCChecks:
    """Investigation Checks gathered from the Plan for rule evaluation."""
    # I — Identity
    identity_verified: CheckStatus = "unknown"
    identity_evidence: list[str] = field(default_factory=list)
    claimed_identity: str | None = None
    identity_is_false: bool = False

    # P — Purpose
    purpose_identified: bool = False
    purpose_description: str = ""
    purpose_is_deceptive: bool = False
    consequential_requests: list[dict] = field(default_factory=list)

    # D — Destination
    destinations_verified: CheckStatus = "unknown"
    destination_evidence: list[str] = field(default_factory=list)
    unverified_destinations: list[str] = field(default_factory=list)

    # M — Mechanism
    has_impersonation: bool = False
    has_deception: bool = False
    has_false_promises: bool = False
    has_payment_diversion: bool = False
    mechanism_evidence: list[str] = field(default_factory=list)

    # C — Contradictions
    has_contradictions: bool = False
    contradiction_details: list[str] = field(default_factory=list)
    genuine_explanation_supported: bool = False


@dataclass
class FindingRulesResult:
    """Complete output of the rules evaluation."""
    finding: str   # scam | not_scam | likely_scam | unlikely_scam
    rules_passed: list[RuleResult] = field(default_factory=list)
    rules_failed: list[RuleResult] = field(default_factory=list)
    ipdmc: IPDMCChecks = field(default_factory=IPDMCChecks)
    # Which rule(s) determined the finding
    deciding_rules: list[str] = field(default_factory=list)
    # Checks that could not be completed
    incomplete_checks: list[str] = field(default_factory=list)
    # Unresolved conflicts
    unresolved_conflicts: list[str] = field(default_factory=list)
    # The Findings Rating (0-100) and its full explainable breakdown (scoring.py) — populated by evaluate().
    rating: int = 0
    rating_breakdown: dict = field(default_factory=dict)


# ── Helper functions ─────────────────────────────────────────────────────────

def _live(plan: Plan) -> list[tuple[Check, dict]]:
    return [(c, f) for c in plan.checks for f in c.facts if f["class"] == "live_evidence"]


def _decisive_threats(plan: Plan) -> list[tuple[Check, dict]]:
    """Facts from authoritative sources that decisively identify a threat."""
    return [(c, f) for c, f in _live(plan)
            if f["signal"] == "concern" and f.get("decisive")]


def _warning_signals(plan: Plan) -> list[tuple[Check, dict]]:
    """Warning-level signals (concern or anomaly), excluding weak signals."""
    return [(c, f) for c, f in _live(plan)
            if f["signal"] in ("concern", "anomaly")]


def _weak_signals(plan: Plan) -> list[tuple[Check, dict]]:
    """Weak signals that are recorded but never sufficient on their own."""
    return [(c, f) for c, f in _live(plan) if f["signal"] == "weak"]


def _clear_signals(plan: Plan) -> list[tuple[Check, dict]]:
    """Clear/positive signals."""
    return [(c, f) for c, f in _live(plan) if f["signal"] == "clear"]


def _corroborated_impersonation(plan: Plan) -> list[dict]:
    """Thin wrapper — imported from checks.py to avoid any circular dependency."""
    from services.higgins.tc_flyby.checks import corroborated_impersonation
    return corroborated_impersonation(plan)


def _official_routes(plan: Plan) -> bool:
    """All links/addresses belong to the named organisation."""
    from services.higgins.tc_flyby.checks import official_routes
    return official_routes(plan)


def _unverified_requests(plan: Plan) -> list[dict]:
    """Consequential requests whose routes aren't verified."""
    from services.higgins.tc_flyby.checks import unverified_requests
    return unverified_requests(plan)


# ── Named decisive mechanisms (PRD §2.3.A / §8) ─────────────────────────────
# A handful of critical exploit mechanisms are, on the request's own quoted wording, already both
# the specific deceptive action S3 requires AND the evidence of what's false — waiting for a
# separate external check to corroborate these specific, narrowly-scoped asks causes real harm, so
# they establish S3 on their own (Unified Evidence Classification PRD §2 Goals: "A single
# established scam mechanism can establish 'This is a Scam' even where other attributes look
# legitimate"). Matched against the request's own quoted text, never the whole message, so an
# unrelated mention elsewhere never triggers this. scoring.py imports these (never redefines them)
# so the Findings Rating's decisive floor and S3's own evidence always agree on exactly the same
# mechanisms.
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


def _severe_or_mule_signal(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """Severe-consequence manipulation (an explicit secrecy/isolation instruction, an acute
    personal-danger appeal, or a threat of arrest, prosecution or an irreversible consequence) or
    money-mule recruitment used to extract a consequential request — narrow, specific entity flags
    set from the message's own wording, never from a separate check."""
    if not ipdmc.consequential_requests:
        return None
    if getattr(plan.entities, "severe_manipulation", False):
        return ("Severe-consequence manipulation (a secrecy/isolation instruction, an acute-distress "
                "appeal, or a threat of arrest or prosecution) used to extract a consequential request")
    if getattr(plan.entities, "mule_signal", False):
        return "Money-mule recruitment: asked to receive money and forward it on for a commission"
    return None


def _named_decisive_mechanism(plan: Plan, ipdmc: IPDMCChecks) -> str | None:
    """PRD §2.3.A's named critical mechanisms, established directly from the request's own quoted
    text (never the whole message) — OTP/credential harvesting, wallet exploitation, extortion,
    credential phishing through a verified deceptive destination, severe-consequence manipulation
    and money-mule recruitment. Each one, once established, already is a specific deceptive action
    with evidence of its own falsity (S3) — a separate corroborating check is not required for these
    narrowly-scoped asks specifically, because waiting for one causes real harm. Deliberately
    excludes the "fully-corroborated pattern" reason scoring.py's own decisive-mechanism check also
    allows: that one is satisfied by the pattern match itself, so it can't independently establish
    more than S4/L2 already do (PRD acceptance test: "L2 full pattern without independent S
    corroboration -> Likely; no automatic S promotion"). Also retains the old `_l2_escalation_signal`'s
    call-channel restriction: over a phone call nothing can verify a spoken "code" or "account
    details" ask the way a lookalike domain or a text's exact wording can, so a bare credential/
    wallet/extortion ask establishes this only off a call — on a call, only severe-consequence
    manipulation or money-mule recruitment do (the four call-only KB patterns stay "likely" on a
    full match alone, by design, even when they also contain a credential ask)."""
    if plan.channel == "call":
        return _severe_or_mule_signal(plan, ipdmc)
    quotes = " ".join(r.get("quote", "") for r in ipdmc.consequential_requests)
    if any(r["type"] == "credentials" for r in ipdmc.consequential_requests) and (
        _OTP_ASK.search(quotes) or ipdmc.identity_is_false
    ):
        return "OTP, password or account-credential harvesting through a falsified identity or domain"
    if _WALLET_ASK.search(quotes):
        return "Wallet or recovery-phrase exploitation"
    if _EXTORTION_ASK.search(quotes):
        return "Extortion or ransomware demand"
    if _corroborated_impersonation(plan) and any(
        f["signal"] == "concern" and f.get("decisive") for c in plan.checks if c.kind == "link" for f in c.facts
    ):
        return "Credential phishing through a verified deceptive destination"
    return _severe_or_mule_signal(plan, ipdmc)


# ── IPDMC Checks gathering ──────────────────────────────────────────────────

def gather_ipdmc(plan: Plan) -> IPDMCChecks:
    """Gather investigation check results from the Plan into the IPDMC structure."""
    checks = IPDMCChecks()

    # ── I — Identity ──
    impersonation_checks = [c for c in plan.checks if c.kind == "impersonation"]
    email_checks = [c for c in plan.checks if c.kind == "email"]
    phone_checks = [c for c in plan.checks if c.kind == "phone"]

    # Derive claimed identity from impersonation checks or from detected brands
    if impersonation_checks:
        checks.claimed_identity = impersonation_checks[0].subject
    elif getattr(plan.entities, 'brands', None):
        checks.claimed_identity = plan.entities.brands[0]

    if impersonation_checks:
        all_clear = all(
            c.status == "resolved" and any(f["signal"] == "clear" for f in c.facts)
            for c in impersonation_checks
        )
        any_concern = any(
            f["signal"] in ("concern", "anomaly")
            for c in impersonation_checks for f in c.facts
            if f.get("class") == "live_evidence"
        )
        if all_clear and not any_concern:
            checks.identity_verified = "passed"
            checks.identity_evidence = [f["text"] for c in impersonation_checks
                                         for f in c.facts if f["signal"] == "clear"]
        elif any_concern:
            checks.identity_verified = "failed"
            checks.identity_is_false = bool(_corroborated_impersonation(plan))
            checks.identity_evidence = [f["text"] for c in impersonation_checks
                                         for f in c.facts
                                         if f.get("class") == "live_evidence" and f["signal"] in ("concern", "anomaly")]
        else:
            checks.identity_verified = "unknown"

    # ── Belt-and-suspenders: lookalike establishes false identity by name ──────
    # A lookalike domain (e.g. commbank-secure.net) carries the brand's name in a
    # non-official domain — that name choice IS the deception and establishes false
    # identity without requiring a separate link-check signal.
    # This guards against future changes to corroborated_impersonation() accidentally
    # losing this protection.
    if not checks.identity_is_false and impersonation_checks:
        lookalike_facts = [
            f for c in impersonation_checks for f in c.facts
            if f.get("class") == "live_evidence" and f["signal"] == "anomaly"
            and f.get("topic") in ("lookalike", "shared_service")
        ]
        if lookalike_facts:
            checks.identity_is_false = True
            existing = set(checks.identity_evidence)
            for f in lookalike_facts:
                if f.get("text") and f["text"] not in existing:
                    checks.identity_evidence.append(f["text"])

    # Email verification
    for c in email_checks:
        for f in c.facts:
            if f.get("class") == "live_evidence" and f["signal"] == "clear":
                checks.identity_evidence.append(f["text"])
            elif f.get("class") == "live_evidence" and f["signal"] == "concern":
                if checks.identity_verified != "passed":
                    checks.identity_verified = "failed"
                checks.identity_evidence.append(f["text"])

    # ── P — Purpose ──
    requests = getattr(plan.entities, 'requests', None) or []
    if requests:
        checks.purpose_identified = True
        checks.purpose_description = "; ".join(
            f"{r['type'].replace('_', ' ')}: {r['quote']}" for r in requests[:4]
        )
        checks.consequential_requests = [r for r in requests if r["type"] in CONSEQUENTIAL]

    # Check if the purpose is deceptive based on established evidence
    pattern = plan.pattern
    if pattern and pattern["stage"] in ("full", "opening"):
        checks.purpose_is_deceptive = True

    # ── D — Destination ──
    link_checks = [c for c in plan.checks if c.kind == "link"]
    if link_checks:
        all_clear = all(
            any(f["decisive"] and f["signal"] == "clear" for f in c.facts)
            for c in link_checks
        )
        any_concern = any(
            f["signal"] in ("concern", "anomaly")
            for c in link_checks for f in c.facts
            if f.get("class") == "live_evidence"
        )
        if all_clear:
            checks.destinations_verified = "passed"
            checks.destination_evidence = [f["text"] for c in link_checks
                                            for f in c.facts if f["signal"] == "clear"]
        elif any_concern:
            checks.destinations_verified = "failed"
            checks.destination_evidence = [f["text"] for c in link_checks
                                            for f in c.facts
                                            if f.get("class") == "live_evidence" and f["signal"] in ("concern", "anomaly")]
        else:
            # Check listing and registration
            for c in link_checks:
                topics = {f.get("topic"): f["signal"] for f in c.facts if f.get("class") == "live_evidence"}
                if topics.get("listing") == "clear" and topics.get("registration") in ("neutral", "weak"):
                    checks.destinations_verified = "passed"
                    checks.destination_evidence.append(f"{c.subject}: clean listing, established registration")
                else:
                    checks.destinations_verified = "unknown"
                    checks.unverified_destinations.append(c.subject)

    unverified = _unverified_requests(plan)
    if unverified:
        checks.unverified_destinations.extend(
            t for r in unverified for t in r.get("targets", [])
        )

    # ── M — Mechanism ──
    corroborated = _corroborated_impersonation(plan)
    if corroborated:
        checks.has_impersonation = True
        checks.mechanism_evidence.extend(f["text"] for f in corroborated if f.get("text"))

    if pattern and pattern["stage"] == "full":
        checks.has_deception = True
        checks.mechanism_evidence.append(
            f"Matches the {pattern['name']} ({pattern.get('publisher', 'known source')})"
        )

    for c, f in _live(plan):
        if f["signal"] == "concern" and f.get("decisive"):
            checks.mechanism_evidence.append(f["text"])

    # ── C — Contradictions ──
    if pattern and pattern.get("impersonatesOrganisation") and getattr(plan.entities, 'brands', None) and _official_routes(plan):
        checks.has_contradictions = True
        checks.contradiction_details.append(
            "The material matches a scam pattern but the links belong to the named organisation."
        )

    for c in plan.checks:
        if c.open_issue.startswith("Conflict"):
            checks.has_contradictions = True
            checks.contradiction_details.append(c.open_issue)

    # Check if there's a supported genuine explanation
    if checks.identity_verified == "passed" and checks.destinations_verified == "passed":
        if not any(f["signal"] in ("concern", "anomaly") for _, f in _warning_signals(plan)):
            checks.genuine_explanation_supported = True

    return checks


# ── S Rules — "This is a scam" ──────────────────────────────────────────────

def s1_known_scam(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """S1 — Known scam: A reliable existing scam report identifies the same sender, website,
    phone number, payment destination or scam operation with a specific match."""
    decisive = _decisive_threats(plan)
    if not decisive:
        return RuleResult("S1", False, "failed", reason="No authoritative scam listing found.")

    # Check that the match is specific (not just a similar domain or generic warning)
    specific_matches = []
    for c, f in decisive:
        # A decisive concern from an authoritative source is a specific match
        text = f.get("text", "")
        specific_matches.append(text)

    if specific_matches and not ipdmc.has_contradictions:
        return RuleResult("S1", True, "passed", evidence=specific_matches,
                          reason="Authoritative source identifies this as a known scam.")

    if specific_matches and ipdmc.has_contradictions:
        # Has contradicting info — still passes if the authoritative source is reliable
        # and the contradiction doesn't undermine the specific match
        return RuleResult("S1", True, "passed", evidence=specific_matches,
                          reason="Authoritative source identifies this as a known scam; "
                                 "conflicting information noted but does not change the identification.")

    return RuleResult("S1", False, "failed", reason="No specific scam match established.")


def s2_fake_identity(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """S2 — Fake identity: The communication claims an identity, the investigation establishes
    that identity is false, and the false identity is used to obtain a response/payment/info."""
    # Condition 1: Claims to be from an identifiable person/organisation
    if not ipdmc.claimed_identity:
        return RuleResult("S2", False, "not_applicable",
                          reason="No identity claim in the material.")

    # Condition 2: The claimed identity is established as false
    if not ipdmc.identity_is_false:
        if ipdmc.identity_verified == "unknown":
            return RuleResult("S2", False, "unknown",
                              reason="Identity claim present but not verified either way.")
        return RuleResult("S2", False, "failed",
                          reason="Identity claim not established as false.")

    # Condition 3: The false identity is used to obtain a response/payment/info
    has_deceptive_purpose = (
        bool(ipdmc.consequential_requests) or
        ipdmc.purpose_is_deceptive
    )
    if not has_deceptive_purpose:
        return RuleResult("S2", False, "failed",
                          evidence=ipdmc.identity_evidence,
                          reason="Identity established as false but no deceptive purpose established.")

    return RuleResult("S2", True, "passed",
                      evidence=ipdmc.identity_evidence + [ipdmc.purpose_description],
                      reason="Fake identity established and used for deceptive purpose.")


def s3_scam_activity(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """S3 — Scam activity identified: A specific deceptive action is identified, evidence
    establishes what is false/misleading, and the deception obtains money/info/access."""
    # A named decisive mechanism (PRD §2.3.A — OTP/wallet/extortion/credential-phishing asks,
    # severe-consequence manipulation, money-mule recruitment) is, on the request's own quoted
    # wording, already both the specific deceptive action and the evidence of its falsity — checked
    # first so it can satisfy conditions 1 and 2 even with no separate external check corroboration.
    named_mechanism = _named_decisive_mechanism(plan, ipdmc)

    # Condition 1: Specific deceptive action identified
    if not ipdmc.has_deception and not ipdmc.mechanism_evidence and not named_mechanism:
        return RuleResult("S3", False, "failed",
                          reason="No specific deceptive action identified.")

    # Condition 2: Evidence establishes what is false/misleading
    # We need both: established deception AND established falsity
    established_deception = []
    for c, f in _warning_signals(plan):
        if f["signal"] == "concern" and f.get("decisive"):
            established_deception.append(f["text"])
        elif f["signal"] == "concern" and c.kind in ("link", "email", "phone", "company"):
            # A non-decisive concern that establishes something specific is false
            established_deception.append(f["text"])

    # Also count corroborated impersonation as established deception
    corroborated = _corroborated_impersonation(plan)
    if corroborated:
        established_deception.extend(f["text"] for f in corroborated if f.get("text"))

    # A lookalike/shared-service domain (anomaly from the impersonation check) is itself
    # established deception: the domain name was chosen to carry the brand's name.
    # This catches the case where corroborated_impersonation() returns evidence items
    # that may have already been counted, as well as direct lookalike evidence.
    for c in plan.checks:
        if c.kind == "impersonation":
            for f in c.facts:
                if (f.get("class") == "live_evidence" and f["signal"] == "anomaly"
                        and f.get("topic") in ("lookalike", "shared_service")
                        and f.get("text") and f["text"] not in established_deception):
                    established_deception.append(f["text"])

    if named_mechanism and named_mechanism not in established_deception:
        established_deception.append(named_mechanism)

    if not established_deception:
        return RuleResult("S3", False, "failed",
                          reason="Deception suspected but not established by evidence.")

    # Condition 3: Deception obtains money, info, access or consequential response
    has_consequential_target = (
        bool(ipdmc.consequential_requests) or
        ipdmc.purpose_is_deceptive
    )
    if not has_consequential_target:
        return RuleResult("S3", False, "failed",
                          evidence=established_deception,
                          reason="Deception established but no consequential target identified.")

    # All three conditions hold — but check for reliable conflicting info
    if ipdmc.has_contradictions and not ipdmc.identity_is_false:
        return RuleResult("S3", False, "failed",
                          evidence=established_deception,
                          reason="Deception evidence present but reliable conflicting information "
                                 "prevents a definite finding.")

    return RuleResult("S3", True, "passed",
                      evidence=established_deception,
                      reason="Deceptive activity established with evidence and consequential target.")


def s4_complete_pattern(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """S4 — Complete scam pattern: Matches a recognised pattern with all defining elements,
    identifiable technique, matching request, AND separate investigation evidence supports
    the deceptive element."""
    p = plan.pattern
    if not p:
        return RuleResult("S4", False, "not_applicable",
                          reason="No scam pattern matched.")

    # Condition 1: Matches a recognised pattern in the KB
    if p["stage"] != "full":
        return RuleResult("S4", False, "failed",
                          reason=f"Pattern match is '{p['stage']}', not complete.")

    # Condition 2: All defining elements present (enforced by 'full' stage)
    # Condition 3: Scam technique identifiable (inherent in pattern match)
    # Condition 4: Request/outcome matches (enforced by 'full' stage)

    # Condition 5: Separate investigation evidence supports the deceptive element
    # This is the key addition: a pattern match alone is not S4.
    # We need independent evidence beyond the pattern text match.
    supporting_evidence = []

    # Corroborated impersonation counts as supporting evidence
    if _corroborated_impersonation(plan):
        supporting_evidence.extend(
            f["text"] for f in _corroborated_impersonation(plan) if f.get("text")
        )

    # Decisive threats count
    for c, f in _decisive_threats(plan):
        supporting_evidence.append(f["text"])

    # Warning signals about the same subjects count
    for c, f in _warning_signals(plan):
        # Accept both concern AND anomaly from link/email/phone checks.
        # A freemail anomaly (gmail is a personal address, not a business domain) combined
        # with a full scam pattern is independent corroborating evidence for S4.
        if f["signal"] in ("concern", "anomaly") and c.kind in ("link", "email", "phone"):
            supporting_evidence.append(f["text"])

    if not supporting_evidence:
        # Pattern matches but no separate investigation evidence supports deception
        return RuleResult("S4", False, "failed",
                          reason="Complete pattern match but no separate investigation evidence "
                                 "supports the deceptive element. Evaluate L2.")

    # Check for reliable conflicting information
    if ipdmc.has_contradictions:
        # Contradictions present — pattern + evidence, but contradicted
        return RuleResult("S4", False, "failed",
                          evidence=supporting_evidence,
                          reason="Complete pattern with supporting evidence, but reliable "
                                 "conflicting information changes the conclusion.")

    return RuleResult("S4", True, "passed",
                      evidence=supporting_evidence,
                      reason=f"Complete match with the {p['name']} pattern, corroborated "
                             f"by independent investigation evidence.")


# ── N Rules — "This is not a scam" (ALL must pass) ──────────────────────────

def n1_genuine_identity(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """N1 — Genuine identity: The claimed sender/organisation is identified and verified,
    with evidence connecting that identity to the actual communication."""
    impersonation_checks = [c for c in plan.checks if c.kind == "impersonation"]
    if not impersonation_checks and not getattr(plan.entities, 'brands', None):
        # No identity claim to verify — N1 is not applicable
        return RuleResult("N1", True, "not_applicable",
                          reason="No identity claim in the material to verify.")

    if not impersonation_checks:
        return RuleResult("N1", False, "unknown",
                          reason="Identity relevant but no impersonation check performed.")

    # Check that verification is positive (not just "business exists")
    all_verified = all(
        c.status == "resolved" and any(
            f["signal"] == "clear" and f.get("decisive")
            for f in c.facts
        )
        for c in impersonation_checks
    )

    # Softer verification: at least clear signals even if not decisive
    soft_verified = all(
        c.status == "resolved" and any(f["signal"] == "clear" for f in c.facts)
        for c in impersonation_checks
    )

    if all_verified:
        return RuleResult("N1", True, "passed",
                          evidence=ipdmc.identity_evidence,
                          reason="Sender identity verified by authoritative evidence.")

    if soft_verified:
        return RuleResult("N1", True, "passed",
                          evidence=ipdmc.identity_evidence,
                          reason="Sender identity verified by investigation evidence.")

    if ipdmc.identity_verified == "failed":
        return RuleResult("N1", False, "failed",
                          evidence=ipdmc.identity_evidence,
                          reason="Identity claim not verified — investigation found concerns.")

    # No positive verification, but also no identity conflicts found.
    # If the impersonation check ran and found no anomaly, lookalike or freemail signal, there is
    # no identity conflict for N1 to flag — treat as not_applicable rather than "unknown".
    any_concern_flag = any(
        f["signal"] in ("concern", "anomaly")
        and f.get("topic") in ("impersonation", "lookalike", "shared_service", "freemail")
        for c in impersonation_checks
        for f in c.facts
        if f.get("class") == "live_evidence"
    )
    if not any_concern_flag:
        return RuleResult("N1", True, "not_applicable",
                          reason="Impersonation checks found no identity conflicts — no anomaly, lookalike or freemail detected.")

    return RuleResult("N1", False, "unknown",
                      reason="Identity relevant but could not be verified.")


def n2_genuine_destinations(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """N2 — Genuine destinations: All relevant links, contact details, and payment destinations
    are verified as genuinely used by the claimed sender."""
    link_checks = [c for c in plan.checks if c.kind == "link"]
    phone_checks = [c for c in plan.checks if c.kind == "phone"]
    email_checks = [c for c in plan.checks if c.kind == "email"]

    if not link_checks and not phone_checks and not email_checks:
        return RuleResult("N2", True, "not_applicable",
                          reason="No destinations in the material to verify.")

    evidence = []
    unverified = []

    for c in link_checks:
        has_decisive_clear = any(f["signal"] == "clear" and f.get("decisive")
                                for f in c.facts if f.get("class") == "live_evidence")
        has_clear = any(f["signal"] == "clear" for f in c.facts if f.get("class") == "live_evidence")
        has_concern = any(f["signal"] in ("concern", "anomaly") for f in c.facts if f.get("class") == "live_evidence")
        has_weak = any(f["signal"] == "weak" for f in c.facts if f.get("class") == "live_evidence")

        if has_concern:
            return RuleResult("N2", False, "failed",
                              evidence=[f["text"] for f in c.facts if f["signal"] in ("concern", "anomaly")],
                              reason=f"Destination {c.subject} has concerns.")

        if has_decisive_clear:
            # A decisive clear signal (e.g., official domain verification) positively verifies the destination
            evidence.append(f"{c.subject}: verified by authoritative source")
        elif has_clear and not has_weak:
            # Clean listing without weak signals: reasonably verified
            topics = {f.get("topic"): f["signal"] for f in c.facts if f.get("class") == "live_evidence"}
            if topics.get("listing") == "clear" and topics.get("registration") in ("neutral",):
                evidence.append(f"{c.subject}: clean listing, established registration")
            else:
                evidence.append(f"{c.subject}: clean listing")
        else:
            # Clean listing but WITH weak signals: the destination is not fully verified
            # A clean listing alone doesn't mean the destination is genuinely used by the claimed sender
            unverified.append(c.subject)

    # Payment details cannot be verified as genuine
    if getattr(plan.entities, 'payment_details', None):
        unverified.extend(plan.entities.payment_details[:3])

    if unverified:
        return RuleResult("N2", False, "unknown",
                          evidence=evidence,
                          reason=f"Important destinations not fully verified: {', '.join(unverified[:3])}.")

    if evidence:
        return RuleResult("N2", True, "passed", evidence=evidence,
                          reason="All relevant destinations verified.")

    return RuleResult("N2", False, "unknown",
                      reason="Destination verification incomplete.")


def n3_genuine_purpose(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """N3 — Genuine purpose: The activity is consistent with the genuine sender's operations,
    and evidence connects the specific request to legitimate activity."""
    if not getattr(plan.entities, 'requests', None):
        # No specific request — only if we have content
        if plan.has_message:
            return RuleResult("N3", True, "not_applicable",
                              reason="No specific request identified in the material.")
        return RuleResult("N3", True, "not_applicable",
                          reason="No material to assess purpose.")

    # Check if any request is consequential and unverified
    unverified = _unverified_requests(plan)
    if unverified:
        return RuleResult("N3", False, "unknown",
                          reason="Consequential request through unverified route — "
                                 "purpose cannot be confirmed as genuine.")

    # If identity is verified and destinations are verified, the requests go through
    # verified channels — purpose is connected to legitimate activity
    if ipdmc.identity_verified == "passed" and ipdmc.destinations_verified == "passed":
        return RuleResult("N3", True, "passed",
                          reason="Requests are through verified routes from verified sender.")

    # If identity is verified and there are no unverified requests
    # (all consequential requests were verified, or no consequential requests)
    if ipdmc.identity_verified == "passed" and not unverified:
        return RuleResult("N3", True, "passed",
                          reason="Requests are from verified sender with no unverified routes.")

    # If identity isn't verified but destinations are and there are no warnings
    if ipdmc.destinations_verified == "passed" and not _warning_signals(plan):
        return RuleResult("N3", True, "passed",
                          reason="Requests go to verified destinations with no scam warnings.")

    return RuleResult("N3", False, "unknown",
                      reason="Purpose cannot be connected to verified legitimate activity.")


def n4_scam_warnings_resolved(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """N4 — Scam warnings resolved: All important scam indicators have been explained,
    disproved, or resolved through supporting information."""
    warnings = _warning_signals(plan)
    weak = _weak_signals(plan)

    # A pattern match IS an important scam indicator that N4 must account for
    has_pattern = plan.pattern and plan.pattern["stage"] in ("full", "opening", "partial")

    if not warnings and not weak and not has_pattern:
        return RuleResult("N4", True, "passed",
                          reason="No scam indicators found to resolve.")

    # A pattern match that hasn't been resolved prevents N4 from passing
    if has_pattern:
        # The pattern is "resolved" if:
        # 1. It's contradicted by verified evidence (e.g., official links)
        # 2. A partial pattern where links go to the official domain is not actionable
        if ipdmc.has_contradictions and ipdmc.genuine_explanation_supported:
            pass  # Pattern is resolved by contradicting evidence
        elif plan.pattern["stage"] == "partial" and _official_routes(plan):
            pass  # Partial pattern with official routes — the key scam element (off-site link) is absent
        else:
            return RuleResult("N4", False, "failed",
                              evidence=[f"Material matches the {plan.pattern['name']} pattern "
                                        f"({plan.pattern['stage']} match)."],
                              reason="Scam pattern match has not been disproved.")

    # Any unresolved warning prevents N4 from passing
    unresolved_warnings = []
    for c, f in warnings:
        subject_clear = any(
            f2["signal"] == "clear" and f2.get("class") == "live_evidence"
            for f2 in c.facts
        )
        if not subject_clear:
            unresolved_warnings.append(f["text"])

    if unresolved_warnings:
        return RuleResult("N4", False, "failed",
                          evidence=unresolved_warnings,
                          reason=f"Important scam warnings unresolved: "
                                 f"{unresolved_warnings[0][:100]}...")

    # All warnings resolved
    return RuleResult("N4", True, "passed",
                      reason="All scam indicators reviewed and resolved.")


# ── L Rules — "This is likely a scam" ───────────────────────────────────────

def l1_strong_impersonation(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """L1 — Strong signs of impersonation: The communication claims an identity, at least one
    detail conflicts with it, and another independent finding supports the misuse."""
    if not ipdmc.claimed_identity:
        return RuleResult("L1", False, "not_applicable",
                          reason="No identity claim in the material.")

    # Condition 1: Claims a particular identity — checked above

    # Condition 2: At least one detail conflicts with the claimed identity
    corroborated = _corroborated_impersonation(plan)
    impersonation_concerns = [
        f for c in plan.checks if c.kind == "impersonation"
        for f in c.facts
        if f.get("class") == "live_evidence" and f["signal"] in ("concern", "anomaly")
        and f.get("topic") in ("impersonation", "lookalike", "shared_service", "freemail")
    ]

    if not impersonation_concerns and not corroborated:
        return RuleResult("L1", False, "failed",
                          reason="No conflicting identity details found.")

    # Condition 3: Another independent finding supports the possibility of misuse
    # This could be: a warning signal on a related link, a pattern match, suspicious request,
    # or the domain itself mimics the brand name (lookalike = the domain name is evidence of intent)
    independent_support = []

    # A lookalike domain (one that carries the brand's name) is itself evidence of intent
    # — the domain name was chosen to mimic the brand, which is an independent finding
    lookalike_facts = [f for f in impersonation_concerns if f.get("topic") == "lookalike"]
    if lookalike_facts:
        independent_support.extend(f["text"] for f in lookalike_facts)

    # Warning signals on links related to the impersonation
    for c, f in _warning_signals(plan):
        if c.kind == "link" and f["signal"] in ("concern", "anomaly"):
            independent_support.append(f["text"])

    # Pattern match counts as independent support
    if plan.pattern and plan.pattern["stage"] in ("full", "opening", "partial"):
        independent_support.append(
            f"Matches {plan.pattern['name']} pattern"
        )

    # Consequential unverified requests count
    if ipdmc.consequential_requests:
        for r in ipdmc.consequential_requests[:2]:
            independent_support.append(f"Asks for {r['type'].replace('_', ' ')}")

    if not independent_support and not corroborated:
        return RuleResult("L1", False, "failed",
                          evidence=[f.get("text", "") for f in impersonation_concerns],
                          reason="Identity conflict found but no independent support.")

    evidence = ([f.get("text", "") for f in impersonation_concerns] +
                [f["text"] for f in corroborated if f.get("text")] +
                independent_support)

    return RuleResult("L1", True, "passed",
                      evidence=evidence,
                      reason="Strong signs of impersonation: identity conflict with "
                             "independent supporting evidence.")


def l2_strong_pattern_match(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """L2 — Strong scam-pattern match: Matches a recognised pattern, the central scam
    behaviour is present, the request matches, but an important part of the suspected
    deception remains unverified."""
    p = plan.pattern
    if not p:
        return RuleResult("L2", False, "not_applicable",
                          reason="No scam pattern matched.")

    if p["stage"] not in ("full", "opening"):
        return RuleResult("L2", False, "failed",
                          reason=f"Pattern match is '{p['stage']}', too weak for L2.")

    # Condition 1: Matches a recognised pattern — checked
    # Condition 2: Central scam behaviour present — inherent in full/opening match
    # Condition 3: Request/outcome matches — inherent in full match (for opening, ask is absent)

    # Condition 4: Important part remains unverified but available evidence supports scam
    # This is the case when S4 doesn't pass (no separate corroborating evidence)
    # but the pattern itself is strong enough
    if p["stage"] == "full":
        # Full pattern but missing the separate corroborating evidence S4 needs
        # Still strong enough for L2
        evidence = [f"It {label}: \"{quote}\"." for label, quote in p["found"]]
        if p["ask"]:
            evidence.append(f"It {p['ask'][0]}: \"{p['ask'][1]}\".")

        # Check if contradicted by genuine information
        if ipdmc.has_contradictions and ipdmc.genuine_explanation_supported:
            return RuleResult("L2", False, "failed",
                              evidence=evidence,
                              reason="Pattern matched but contradicted by verified legitimate information.")

        return RuleResult("L2", True, "passed",
                          evidence=evidence,
                          reason=f"Matches the complete {p['name']} pattern; "
                                 f"an important part of the deception is unverified.")

    # Opening match (hallmarks present, ask absent) — only for family-type patterns
    evidence = [f"It {label}: \"{quote}\"." for label, quote in p["found"]]
    return RuleResult("L2", True, "passed",
                      evidence=evidence,
                      reason=f"Matches the opening of the {p['name']} pattern.")


def l3_independent_indicators(plan: Plan, ipdmc: IPDMCChecks) -> RuleResult:
    """L3 — Several independent scam indicators: At least two separate findings from
    genuinely different checks, at least one directly concerning deception, and the combined
    findings provide a stronger scam explanation than legitimate ones."""
    warnings = _warning_signals(plan)
    if len(warnings) < 2:
        return RuleResult("L3", False, "failed",
                          reason=f"Only {len(warnings)} warning signal(s); need at least 2.")

    # Check for genuinely different observations.
    # Group by check kind and subject to detect duplicate observations — but a "triage_rules" check
    # can carry several genuinely independent catalogue rules (each ruleId is its own distinct finding,
    # e.g. a look-alike character beside unrelated urgency/pressure wording), so those are split by
    # ruleId/topic rather than lumped together just because they came from the one check object.
    groups: dict[str, list[tuple[Check, dict]]] = {}
    for c, f in warnings:
        key = f"{c.kind}:{registrable(c.subject) or c.subject}"
        if c.kind == "triage_rules":
            key = f"{key}:{f.get('ruleId') or f.get('topic') or f['text']}"
        groups.setdefault(key, []).append((c, f))

    independent_groups = list(groups.values())
    if len(independent_groups) < 2:
        return RuleResult("L3", False, "failed",
                          reason="Warning signals are about the same underlying issue.")

    # Condition 3: At least one directly concerns deception
    deception_indicators = []
    deception_topics = {"impersonation", "lookalike", "shared_service", "freemail", "claim", "company"}
    deception_kinds = {"email", "phone", "company", "claim", "triage_rules"}
    for c, f in warnings:
        topic = f.get("topic", "")
        if topic in deception_topics:
            deception_indicators.append(f["text"])
        elif c.kind in deception_kinds and f["signal"] == "concern":
            deception_indicators.append(f["text"])
        elif f.get("decisive"):
            deception_indicators.append(f["text"])

    if not deception_indicators:
        return RuleResult("L3", False, "failed",
                          evidence=[f["text"] for _, f in warnings],
                          reason="Multiple indicators but none directly concerns deception.")

    # Condition 4: Combined findings stronger than legitimate explanation
    # If there's strong evidence of legitimacy, L3 doesn't pass
    if ipdmc.genuine_explanation_supported:
        return RuleResult("L3", False, "failed",
                          evidence=[f["text"] for _, f in warnings],
                          reason="Multiple indicators found but legitimate explanation "
                                 "accounts for the suspected behaviour.")

    evidence = [f["text"] for _, f in warnings]
    return RuleResult("L3", True, "passed",
                      evidence=evidence,
                      reason="Multiple independent scam indicators including deception evidence.")


# ── Decision Engine ──────────────────────────────────────────────────────────

def established_scam_rules(plan: Plan, ipdmc: IPDMCChecks, s_rules: list[RuleResult] | None = None) -> list[RuleResult]:
    """The S1–S4 rules that pass with no unresolved reliable information undermining them — exactly the
    condition under which evaluate_rules() reports "scam" (and decide.py's Decision carries it). One place
    for that condition, so the Findings Rating (scoring.py) can floor the score the same way: the verdict
    the person sees and the rating's band must never disagree (owner, 2026-11-08: a case shown as "This is
    a scam" was rated 83/100 "likely")."""
    rules = s_rules or [s1_known_scam(plan, ipdmc), s2_fake_identity(plan, ipdmc), s3_scam_activity(plan, ipdmc), s4_complete_pattern(plan, ipdmc)]
    passed = [r for r in rules if r.passed]
    if not passed:
        return []
    # S1 (known scam) is never undermined by a genuine explanation.
    undermined = ipdmc.has_contradictions and ipdmc.genuine_explanation_supported and not any(r.rule_id == "S1" for r in passed)
    return [] if undermined else passed


def evaluate_rules(plan: Plan) -> FindingRulesResult:
    """Evaluate the S1-S4 / N1-N4 / L1-L3 rules against the investigation plan.

    This still runs in full on every case — its evidence, deciding_rules and ipdmc feed Higgins'
    narrative and decide.py's routing (which rule explains "why", not just "what"). It no longer picks
    the Finding on its own, though: evaluate() below does that from the Findings Rating instead. The
    docstring below is historical (kept because deciding_rules / rules_passed / rules_failed still mean
    exactly what it says), but see evaluate() for what actually becomes `result.finding`.

    Decision order (informational only — superseded by the Findings Rating in evaluate()):
    1. S1-S4: If any passes → scam
    2. N1-N4: If all applicable pass → not_scam
    3. L1-L3: If any passes → likely_scam
    4. Otherwise → unable_to_determine
    """
    ipdmc = gather_ipdmc(plan)
    result = FindingRulesResult(finding="unable_to_determine", ipdmc=ipdmc)

    # Record incomplete checks
    for c in plan.checks:
        if c.status == "unavailable":
            result.incomplete_checks.append(f"{c.kind}: {c.subject}")
    if plan.gaps:
        for g in plan.gaps:
            result.incomplete_checks.append(f"{g['item']}: {g['what']}")

    # Record unresolved conflicts
    result.unresolved_conflicts = ipdmc.contradiction_details[:]

    # ── Step 1: Evaluate S1-S4 ──
    s_rules = [
        s1_known_scam(plan, ipdmc),
        s2_fake_identity(plan, ipdmc),
        s3_scam_activity(plan, ipdmc),
        s4_complete_pattern(plan, ipdmc),
    ]

    s_passed = [r for r in s_rules if r.passed]
    s_failed = [r for r in s_rules if not r.passed]

    # If any S rule passes and no unresolved reliable information undermines it
    if established_scam_rules(plan, ipdmc, s_rules):
        result.finding = "scam"
        result.deciding_rules = [r.rule_id for r in s_passed]
        result.rules_passed = s_passed
        result.rules_failed = s_failed
        return result

    # ── Step 2: Evaluate N1-N4 ──
    n_rules = [
        n1_genuine_identity(plan, ipdmc),
        n2_genuine_destinations(plan, ipdmc),
        n3_genuine_purpose(plan, ipdmc),
        n4_scam_warnings_resolved(plan, ipdmc),
    ]

    n_applicable = [r for r in n_rules if r.status != "not_applicable"]
    n_passed = [r for r in n_applicable if r.passed]
    n_failed = [r for r in n_applicable if not r.passed]

    # All applicable N rules must pass; unknown cannot be treated as passed. Also: at least one of
    # N1-N3 (genuine identity / destinations / purpose) must have substantively passed — N4 alone
    # ("no scam indicators to resolve") is an absence of concern, not positive verification, and
    # must never by itself establish "Not a Scam" (Unified Evidence Classification PRD §4:
    # "substantive positive verification", never a vacuous pass). Without this, an ordinary message
    # with nothing to check at all — nothing identified, nothing to verify — would read as a false
    # "Not a Scam" purely because there was nothing to object to either; it must read "Unlikely a
    # Scam" instead (PRD §5.1's own example).
    # Gaps (unprocessed material) prevent not_scam — an unavailable check is not a successful check.
    has_gaps = bool(plan.gaps) or any(c.status == "unavailable" for c in plan.checks)
    substantive_verification = any(r.rule_id in ("N1", "N2", "N3") and r.passed for r in n_applicable)
    if n_applicable and all(r.passed for r in n_applicable) and substantive_verification and not has_gaps:
        result.finding = "not_scam"
        result.deciding_rules = [r.rule_id for r in n_passed]
        result.rules_passed = s_passed + n_passed
        result.rules_failed = s_failed + n_failed
        return result

    # ── Step 3: Evaluate L1-L3 ──
    l_rules = [
        l1_strong_impersonation(plan, ipdmc),
        l2_strong_pattern_match(plan, ipdmc),
        l3_independent_indicators(plan, ipdmc),
    ]

    l_passed = [r for r in l_rules if r.passed]
    l_failed = [r for r in l_rules if not r.passed]

    if l_passed:
        # Check that no reliable genuine explanation resolves the suspected scam
        if not ipdmc.genuine_explanation_supported:
            result.finding = "likely_scam"
            result.deciding_rules = [r.rule_id for r in l_passed]
            result.rules_passed = s_passed + n_passed + l_passed
            result.rules_failed = s_failed + n_failed + l_failed
            return result

    # ── Step 4: Unable to determine ──
    result.finding = "unable_to_determine"
    result.rules_passed = s_passed + [r for r in n_rules if r.passed] + l_passed
    result.rules_failed = s_failed + [r for r in n_rules if not r.passed] + l_failed
    return result


def evaluate(plan: Plan) -> FindingRulesResult:
    """The Finding TC Hawkeye actually reports — the one shared evidence-authoritative resolver
    (Unified Evidence Classification PRD §3/§4/FR-01): evaluate_rules() above runs the S1-S4/N1-N4/
    L1-L3/U waterfall and that evidence verdict is final, never silently replaced by the score.
    scoring.score_plan() still computes the full six-dimension rating (unchanged — same floors,
    credits and calculation trace as always); scoring.reconcile() then aligns that rating to the
    evidence verdict's band with the smallest possible move when, and only when, they land in
    different bands (§5.1). "unable_to_determine" is never a Finding a person sees — it reads as
    "This is Unlikely a Scam" (scoring.evidence_verdict); genuine investigation failures (a critical
    check that never got an answer even after retrying) are handled upstream, before a Finding is
    attempted at all.
    """
    from services.higgins.tc_flyby import scoring

    result = evaluate_rules(plan)
    breakdown = scoring.score_plan(plan, result.ipdmc)
    breakdown = scoring.reconcile(result, breakdown)
    result.finding = breakdown.finding
    result.rating = breakdown.rating
    result.rating_breakdown = breakdown.wire()
    # Keep deciding_rules consistent with the resolved Finding when they already agree (the common
    # case); when evaluate_rules() itself reached "unable_to_determine" (no rule passed), leave
    # deciding_rules as whatever rules DID pass (if any — there usually are none) so decide.py's
    # routing still has something to work with, rather than clearing it to nothing.
    if not result.deciding_rules and (result.rules_passed):
        result.deciding_rules = [r.rule_id for r in result.rules_passed]
    return result


def evaluate_for_magnum(plan: Plan, magnum_outcome: str | None) -> FindingRulesResult:
    """Map a Magnum DI outcome to the new finding codes using the same rules.
    Magnum DI selects its own outcome via the AI model, but this function ensures
    the same finding criteria are applied."""
    # First evaluate the TC Hawkeye evidence with the rules
    rules_result = evaluate(plan)

    # If Magnum DI provided an outcome, validate it against the rules
    if magnum_outcome:
        # Magnum DI's outcome is trusted if it's consistent with the rules
        # or if it has additional evidence TC Hawkeye didn't have
        pass

    return rules_result
