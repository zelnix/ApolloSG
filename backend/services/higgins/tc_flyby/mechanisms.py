"""TC Hawkeye — the 14 named Detection Mechanisms (PRD v2.3 §4, D01-D14).

Phase 3 engineering task, per the Phase 1 Capability Review (`content/prd_v23_capability_review.md`):
"a *named*, independently-testable function per mechanism, each feeding a specific evidence item"
didn't exist before this module — the underlying signal was scattered across `finding_rules.py`,
`scoring.py` and `official.py` under other names. This module does not duplicate or recompute
anything: each function reads the *same* `Plan`/`IPDMCChecks` data the scoring engine already
produced, and simply names and packages it the way §4 and §4.5 (structured per-investigation
output) require. It never changes a Findings Rating — `scoring.py` remains the single, authoritative
scoring calculation (PRD §6 implementation constraints).

Each mechanism reports:
  fired       — whether this mechanism's trigger conditions are met, from real investigation data.
  confidence  — "established" (direct evidence), "indicated" (circumstantial), or "not_evaluated"
                (nothing in this message could ever test this mechanism — never a silent false "no").
  why         — a one-line, evidence-backed explanation.
  evidence    — PRD §4.2's own "Evidence Output Requirements" for that mechanism, each field either a
                real value taken from the investigation or `None` (never fabricated, never guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import CONSEQUENTIAL, Plan

# Message types whose own purpose is inconsistent with being asked for credentials or remote access —
# PRD D01's own example: "a supposed delivery notification asking for login credentials".
_D01_MISMATCHED_PURPOSE = {
    "delivery_toll": ("credentials", "remote_access"),
    "prize": ("credentials", "remote_access", "gift_cards_crypto"),
    "invoice": ("remote_access",),
}
_ROMANCE_PATTERN_KEYS = ("romance_grooming",)
_INVESTMENT_PATTERN_KEYS = ("investment_returns", "investment_fake_endorsement")
_EMOTIONAL_PATTERN_KEYS = ("family_new_number", "romance_grooming")
_CREDENTIAL_PATTERN_KEYS = ("otp_bypass", "bank_code_call", "organisation_phishing")
_REMOTE_ACCESS_PATTERN_KEYS = ("remote_access", "tech_support_call")


@dataclass
class MechanismFinding:
    code: str                      # "D01".."D14"
    name: str
    fired: bool
    confidence: str                # established | indicated | not_evaluated
    why: str
    evidence: dict = field(default_factory=dict)

    def wire(self) -> dict:
        return {"code": self.code, "name": self.name, "fired": self.fired, "confidence": self.confidence,
                "why": self.why, "evidence": self.evidence}


def _pattern_key(plan: Plan) -> str | None:
    return (plan.pattern or {}).get("key") if plan.pattern else None


def _consequential(plan: Plan) -> list[dict]:
    return [r for r in plan.entities.requests if r["type"] in CONSEQUENTIAL]


def _live_facts(plan: Plan) -> list[dict]:
    return [f for c in plan.checks for f in c.facts if f.get("class") == "live_evidence"]


def _not_evaluated(code: str, name: str, why: str) -> MechanismFinding:
    return MechanismFinding(code, name, fired=False, confidence="not_evaluated", why=why, evidence={})


def detect_d01_structural_asymmetry(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Claimed identity, structure, channel and action inconsistencies."""
    code, name = "D01", "Structural Asymmetry"
    mismatched = [r for r in _consequential(plan) if r["type"] in _D01_MISMATCHED_PURPOSE.get(plan.message_type, ())]
    if ipdmc.identity_is_false:
        return MechanismFinding(code, name, True, "established",
                                "The claimed identity does not match the independently verified technical details (domain/sender).",
                                {"claimedIdentity": ipdmc.claimed_identity, "observedChannel": plan.channel or "message",
                                 "comparisonOfClaimedVsObserved": ipdmc.identity_evidence or None, "requestedAction": None})
    if mismatched:
        r = mismatched[0]
        return MechanismFinding(code, name, True, "indicated",
                                f"The requested action ({r['type']}) is inconsistent with the purported purpose "
                                f"of this communication ({plan.message_type}).",
                                {"claimedIdentity": None, "messageStructure": plan.message_type,
                                 "observedChannel": plan.channel or "message", "requestedAction": r["quote"],
                                 "comparisonOfClaimedVsObserved": None})
    return MechanismFinding(code, name, False, "indicated", "No identity/channel/action inconsistency established.", {})


def detect_d02_channel_redirection(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Moves to private chat, telephone or payment channel."""
    code, name = "D02", "Channel Redirection"
    redirect = next((r for r in plan.entities.requests if r["type"] in ("call_back", "reply")), None)
    if redirect:
        return MechanismFinding(code, name, True, "established",
                                f"This message asks the recipient to move off it, to a {('phone call' if redirect['type'] == 'call_back' else 'reply/SMS')} channel.",
                                {"originalChannel": plan.channel or "message", "proposedChannel": "phone" if redirect["type"] == "call_back" else "reply",
                                 "requestContent": redirect["quote"], "reasonGiven": None, "targets": redirect.get("targets") or None})
    return MechanismFinding(code, name, False, "indicated", "No request to move to a different channel found.", {})


def detect_d03_domain_deception(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Lookalikes, subdomain abuse, shorteners and redirects."""
    code, name = "D03", "Domain Deception"
    facts = _live_facts(plan)
    deceptive = [f for f in facts if f.get("topic") in ("lookalike", "redirect", "shortener", "registration") and f["signal"] in ("concern", "anomaly")]
    if ipdmc.identity_is_false or deceptive:
        urls = [u for c in plan.checks for u in c.urls]
        return MechanismFinding(code, name, True, "established",
                                "A deceptive domain (lookalike, redirect chain or shortener) was established by live evidence.",
                                {"urls": urls or None, "domainAnalysis": [f["text"] for f in deceptive] or ipdmc.identity_evidence or None})
    return MechanismFinding(code, name, False, "indicated", "No deceptive domain technique established.", {})


def detect_d04_payment_rail_manipulation(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Unusual destinations, crypto, gift cards and substitutions."""
    code, name = "D04", "Payment Rail Manipulation"
    hit = next((r for r in _consequential(plan) if r["type"] in ("gift_cards_crypto", "payment_details_change")), None)
    if hit or ipdmc.has_payment_diversion:
        return MechanismFinding(code, name, True, "established",
                                "A non-standard or substituted payment method/destination is being requested.",
                                {"paymentMethod": hit["type"] if hit else "payment_diversion", "requestedRecipient": hit.get("targets") if hit else None,
                                 "justificationGiven": None})
    return MechanismFinding(code, name, False, "indicated", "No unusual payment rail requested.", {})


def detect_d05_urgency_time_pressure(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Artificial deadlines and immediate-action pressure."""
    code, name = "D05", "Urgency and Time Pressure"
    terms = plan.entities.urgency or []
    if terms:
        return MechanismFinding(code, name, True, "established", f"{len(terms)} urgency/time-pressure phrase(s) found.",
                                {"urgencyPhrases": terms, "statedDeadline": None, "statedConsequences": None})
    return MechanismFinding(code, name, False, "indicated", "No urgency or time-pressure language found.", {})


def detect_d06_authority_impersonation(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Unsupported bank, government or employer authority."""
    code, name = "D06", "Authority Impersonation"
    if ipdmc.has_impersonation or (ipdmc.identity_is_false and plan.message_type in ("bank", "government")):
        return MechanismFinding(code, name, True, "established",
                                "An organisation (bank/government/employer) is claimed beside a route that independent checks show isn't its own.",
                                {"authorityClaimed": plan.entities.brands[0][0] if plan.entities.brands else plan.message_type,
                                 "verificationChecks": ipdmc.identity_evidence or None})
    return MechanismFinding(code, name, False, "indicated", "No unsupported authority claim established.", {})


def detect_d07_emotional_manipulation(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Fear, affection, guilt, sympathy and secrecy."""
    code, name = "D07", "Emotional Manipulation"
    key = _pattern_key(plan)
    if key in _EMOTIONAL_PATTERN_KEYS or plan.message_type in ("romance", "family_impersonation"):
        found = [f for f, _ in (plan.pattern or {}).get("found", [])] if plan.pattern else []
        return MechanismFinding(code, name, True, "established" if key in _EMOTIONAL_PATTERN_KEYS else "indicated",
                                "Emotionally manipulative language (affection, guilt, sympathy or secrecy) was matched against Apollo's knowledge base.",
                                {"emotionalLanguage": found or None, "narrativeElements": (plan.pattern or {}).get("summary") if plan.pattern else None})
    return MechanismFinding(code, name, False, "indicated", "No emotional-manipulation tactic established.", {})


def detect_d08_credential_extraction(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Passwords, OTPs, recovery codes and seed phrases."""
    code, name = "D08", "Credential Extraction"
    hit = next((r for r in _consequential(plan) if r["type"] == "credentials"), None)
    key = _pattern_key(plan)
    if hit or key in _CREDENTIAL_PATTERN_KEYS:
        return MechanismFinding(code, name, True, "established", "A direct or indirect request for credentials/OTP/codes was found.",
                                {"credentialType": hit["type"] if hit else key, "exactWording": hit["quote"] if hit else None,
                                 "loginPageUrls": [u for c in plan.checks if c.kind == "link" for u in c.urls] or None})
    return MechanismFinding(code, name, False, "indicated", "No credential-extraction request found.", {})


def detect_d09_remote_access_manipulation(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Remote software, screen sharing and device control."""
    code, name = "D09", "Remote Access Manipulation"
    hit = next((r for r in _consequential(plan) if r["type"] == "remote_access"), None)
    key = _pattern_key(plan)
    if hit or key in _REMOTE_ACCESS_PATTERN_KEYS:
        return MechanismFinding(code, name, True, "established", "A request for remote access, screen sharing or device control was found.",
                                {"accessMethod": hit["quote"] if hit else key, "statedReason": None})
    return MechanismFinding(code, name, False, "indicated", "No remote-access request found.", {})


def detect_d10_transaction_inconsistency(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Claims inconsistent with authenticated transaction context."""
    code, name = "D10", "Transaction Inconsistency"
    contradicted = (plan.pattern or {}).get("contradicted") if plan.pattern else None
    if contradicted:
        return MechanismFinding(code, name, True, "established", "The communication's claim conflicts with evidence Apollo independently established.",
                                {"claim": "; ".join(contradicted), "authenticatedContext": None})
    # ApolloSG has no authenticated bank/transaction record to compare against today (no live account
    # integration) — honestly reported as not evaluated, never guessed either way.
    return _not_evaluated(code, name, "No authenticated transaction record is available to compare this claim against.")


def detect_d11_investment_deception(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Unrealistic returns, fake endorsements and withdrawal barriers."""
    code, name = "D11", "Investment Deception"
    key = _pattern_key(plan)
    if key in _INVESTMENT_PATTERN_KEYS or (plan.message_type == "investment" and plan.entities.claims):
        return MechanismFinding(code, name, True, "established" if key in _INVESTMENT_PATTERN_KEYS else "indicated",
                                "Unrealistic-return or fraudulent-investment language was matched.",
                                {"promisedReturns": plan.entities.claims or None, "endorsements": None,
                                 "withdrawalBarriers": [f for f, _ in (plan.pattern or {}).get("found", []) if "withdraw" in f.lower()] or None})
    return MechanismFinding(code, name, False, "indicated", "No investment-deception tactic established.", {})


def detect_d12_relationship_grooming(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Trust-building and progression toward exploitation."""
    code, name = "D12", "Relationship Grooming"
    key = _pattern_key(plan)
    if key in _ROMANCE_PATTERN_KEYS or plan.message_type == "romance":
        found = [f for f, _ in (plan.pattern or {}).get("found", [])] if plan.pattern else []
        return MechanismFinding(code, name, True, "established" if key in _ROMANCE_PATTERN_KEYS else "indicated",
                                "Relationship-building language, consistent with Apollo's known romance/grooming pattern, was matched.",
                                {"relationshipNarrative": found or None, "requestProgression": (plan.pattern or {}).get("ask") if plan.pattern else None})
    return MechanismFinding(code, name, False, "indicated", "No relationship-grooming pattern established.", {})


def detect_d13_identity_mismatch(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Claimed versus independently verified identity."""
    code, name = "D13", "Identity Mismatch"
    if ipdmc.identity_is_false:
        return MechanismFinding(code, name, True, "established", "The claimed identity does not match what independent checks verified.",
                                {"claimedIdentity": ipdmc.claimed_identity, "verifiedIdentity": None,
                                 "mismatchDetails": ipdmc.identity_evidence or None})
    return MechanismFinding(code, name, False, "indicated", "No identity mismatch established.", {})


def detect_d14_verification_contradiction(plan: Plan, ipdmc: IPDMCChecks) -> MechanismFinding:
    """Material conflicts with authoritative evidence."""
    code, name = "D14", "Verification Contradiction"
    contradicted = (plan.pattern or {}).get("contradicted") if plan.pattern else None
    decisive_concern = [f for f in _live_facts(plan) if f.get("decisive") and f["signal"] == "concern"]
    if contradicted or decisive_concern or ipdmc.has_contradictions:
        details = contradicted or [f["text"] for f in decisive_concern] or ipdmc.contradiction_details
        return MechanismFinding(code, name, True, "established", "A material claim is directly contradicted by authoritative evidence.",
                                {"claimMade": "; ".join(details) if details else None, "authoritativeEvidence": None,
                                 "contradictionStatement": "; ".join(details) if details else None})
    return MechanismFinding(code, name, False, "indicated", "No contradiction with authoritative evidence established.", {})


_ALL = (detect_d01_structural_asymmetry, detect_d02_channel_redirection, detect_d03_domain_deception,
       detect_d04_payment_rail_manipulation, detect_d05_urgency_time_pressure, detect_d06_authority_impersonation,
       detect_d07_emotional_manipulation, detect_d08_credential_extraction, detect_d09_remote_access_manipulation,
       detect_d10_transaction_inconsistency, detect_d11_investment_deception, detect_d12_relationship_grooming,
       detect_d13_identity_mismatch, detect_d14_verification_contradiction)


def run_all(plan: Plan, ipdmc: IPDMCChecks) -> list[MechanismFinding]:
    """Every D01-D14 mechanism, run against this investigation's own Plan/IPDMCChecks — §4.5's
    "structured per-investigation output" requirement (which mechanisms fired, and why)."""
    return [fn(plan, ipdmc) for fn in _ALL]
