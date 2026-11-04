"""Four-Stage Evidence Evaluation Pipeline — the Robust Threat Decision Engine.

Sits between TC FlyBy's raw check results and the final decision in ``decide.py``.
It does NOT replace the existing decision logic; it provides a structured evaluation
that ``decide.provisional()`` uses to avoid false-positive escalation while preserving
detection of genuine threats.

Architecture:
    Plan (with checks & facts)
        → Stage 1: Relevance Gate    — attribute each fact, exclude irrelevant ones
        → Stage 2: Deduplication     — group correlated findings, prevent inflation
        → Stage 3: Dual-Hypothesis   — evaluate legitimate vs malicious for each signal
        → Stage 4: Calibrated Review — final risk/confidence that informs decide.py

Design constraints (from the PRD):
    - No arbitrary weights or invented confidence thresholds.
    - AI-generated claims never become trusted evidence without validation.
    - Verified malicious indicators are never overridden by otherwise-legitimate context.
    - Preserve the established workflow: Apollo → Higgins → TC FlyBy → Magnum DI → Explain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from services.higgins.brand_domains import registrable
from services.higgins.tc_flyby.triage import Check, Plan


# ── Data structures ──────────────────────────────────────────────────────────

Relevance = Literal["primary", "supporting", "excluded"]
HypothesisBalance = Literal["legitimate", "malicious", "ambiguous", "verified_threat"]


@dataclass
class EvidenceRecord:
    """One piece of evidence with its four-stage evaluation metadata.

    ``fact`` is the original TC FlyBy check fact (a dict with text, signal, decisive,
    class, source, topic).  Everything else is evaluation metadata this module adds.
    """
    fact: dict
    check: Check
    # Stage 1 — Relevance
    subject_attribution: str = ""               # who/what this evidence is about
    relevance: Relevance = "primary"
    exclusion_reason: Optional[str] = None
    # Stage 2 — Deduplication
    correlation_group: Optional[str] = None     # group key for correlated findings
    is_representative: bool = True              # the lead finding in its group
    # Stage 3 — Dual-Hypothesis
    legitimate_hypothesis: Optional[str] = None
    malicious_hypothesis: Optional[str] = None
    hypothesis_balance: HypothesisBalance = "ambiguous"
    # Provenance
    source_type: str = ""                       # "authoritative" | "third_party" | "deterministic" | "device"


@dataclass
class EvaluationResult:
    """The output of the full four-stage evaluation pipeline."""
    records: list[EvidenceRecord] = field(default_factory=list)
    # Stage 1 summary
    relevant_count: int = 0
    excluded_count: int = 0
    excluded_audit: list[dict] = field(default_factory=list)  # {fact_text, reason}
    # Stage 2 summary
    groups: dict[str, list[EvidenceRecord]] = field(default_factory=dict)
    deduplicated_count: int = 0
    # Stage 3 summary
    has_verified_threat: bool = False
    all_legitimate_favoured: bool = False
    # Stage 4 summary
    threat_level: str = "no_threat"    # no_threat | needs_verification | suspicious | high_risk
    confidence: str = "low"            # low | medium | high
    should_downgrade: bool = False     # True when the evaluation advises downgrading a provisional concern
    downgrade_reason: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

_THIRD_PARTY_TOPICS = frozenset({"ipqs", "reputation", "risk_score", "redirect"})
_AUTHORITATIVE_TOPICS = frozenset({"listing", "safe_browsing", "official_domains", "advisory", "scam_advisory"})

_NEWLY_REGISTERED = re.compile(r"registered (?:on|in|less than)|newly registered", re.I)
_IPQS = re.compile(r"ipqualityscore|ipqs|fraud score", re.I)
_REDIRECT = re.compile(r"redirect", re.I)
_LISTING = re.compile(r"safe browsing|blocklist|phishtank|openphish|spamhaus|scam (?:warning|advisory)", re.I)


def _source_type(f: dict) -> str:
    """Classify where this fact came from."""
    if f.get("decisive"):
        return "authoritative"
    topic = f.get("topic") or ""
    if topic in _AUTHORITATIVE_TOPICS or _LISTING.search(f.get("text", "")):
        return "authoritative"
    if topic in _THIRD_PARTY_TOPICS or _IPQS.search(f.get("text", "")) or _NEWLY_REGISTERED.search(f.get("text", "")):
        return "third_party"
    return "deterministic"


def _correlation_key(f: dict, check: Check) -> str:
    """Group key: findings about the same subject and check type are correlated."""
    place = registrable(f.get("place", "")) or registrable(check.subject)
    return f"{check.kind}:{place}"


# ── Stage 1: Relevance Gate ─────────────────────────────────────────────────

def _relevance_gate(plan: Plan) -> list[EvidenceRecord]:
    """Attribute every fact to its subject and classify relevance.

    Exclusion criteria:
    - Impersonation facts for 'merely mentioned' brands (already handled in decide.py,
      but recorded here for the audit trail).
    - Search results that don't name the actual subject of the investigation.
    - Facts from checks that couldn't run (status 'unavailable') — these are gaps, not evidence.
    """
    # Identify the verified sender (if any impersonation check resolved clear).
    verified_sender = {c.subject for c in plan.checks
                       if c.kind == "impersonation" and c.status == "resolved"
                       and any(f["signal"] == "clear" for f in c.facts)}

    records: list[EvidenceRecord] = []
    for check in plan.checks:
        for f in check.facts:
            if f["class"] != "live_evidence":
                continue
            rec = EvidenceRecord(fact=f, check=check)
            rec.subject_attribution = f.get("place") or check.subject
            rec.source_type = _source_type(f)

            # Exclusion: impersonation fact for a merely-mentioned brand
            if (check.kind == "impersonation" and f.get("topic") == "impersonation"
                    and verified_sender and check.subject not in verified_sender):
                rec.relevance = "excluded"
                rec.exclusion_reason = (f"Brand '{check.subject}' is merely mentioned; "
                                        f"the sender is verified as {', '.join(verified_sender)}.")

            # Exclusion: check was unavailable (gap, not evidence)
            elif check.status == "unavailable":
                rec.relevance = "excluded"
                rec.exclusion_reason = f"Check '{check.kind}' for '{check.subject}' was unavailable."

            # Supporting: third-party reputation data (not primary evidence)
            elif rec.source_type == "third_party" and f["signal"] != "concern":
                rec.relevance = "supporting"

            records.append(rec)
    return records


# ── Stage 2: Deduplication ──────────────────────────────────────────────────

def _deduplicate(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Group findings that share the same underlying cause.

    The first (strongest-signal) finding in each group is the representative.
    Others are marked ``is_representative = False``.  All findings are preserved;
    the flag tells Stage 4 which ones to count toward risk.
    """
    groups: dict[str, list[EvidenceRecord]] = {}
    signal_rank = {"concern": 0, "anomaly": 1, "weak": 2, "clear": 3, "neutral": 4, "missing": 5, "context": 6}

    for rec in records:
        if rec.relevance == "excluded":
            continue
        key = _correlation_key(rec.fact, rec.check)
        rec.correlation_group = key
        groups.setdefault(key, []).append(rec)

    for key, group in groups.items():
        # Sort by signal strength: concern > anomaly > weak > ...
        group.sort(key=lambda r: signal_rank.get(r.fact["signal"], 99))
        for i, rec in enumerate(group):
            rec.is_representative = (i == 0)

    return records


# ── Stage 3: Dual-Hypothesis Evaluation ─────────────────────────────────────

# Deterministic legitimate explanations: when a signal has a well-known benign cause,
# record it.  These are NOT arbitrary weights — they are documented, testable rules
# about what each signal actually means in context.

_LEGIT_NEWLY_REGISTERED = ("A newly registered domain may belong to a new legitimate business, "
                           "a recently launched product, or a rebranded website.")
_LEGIT_IPQS_HIGH = ("IPQualityScore rates likelihood, not confirmed harm. "
                     "Many legitimate new or niche websites score high.")
_LEGIT_REDIRECT = ("Redirects are commonly used for URL shortening, email tracking, "
                    "marketing analytics and CDN delivery.")
_LEGIT_UNRELATED_DOMAIN = ("An unrelated domain for a mentioned brand means the email is from "
                            "a different sender, not that it impersonates the mentioned brand.")
_LEGIT_FREEMAIL = ("A free email address is common for individuals and small businesses.")


def _evaluate_hypotheses(records: list[EvidenceRecord], plan: Plan) -> list[EvidenceRecord]:
    """For each relevant, representative finding, evaluate the legitimate and malicious
    interpretations independently.

    Rules:
    - A decisive concern from an authoritative source → ``verified_threat``.
    - A signal with a well-known benign explanation AND no corroborating authoritative
      evidence → ``legitimate`` favoured.
    - A signal from an authoritative scam listing or official advisory → ``malicious``.
    - Everything else → ``ambiguous``.

    Authenticated sender identity is evidence against spoofing, but NOT proof of overall safety.
    Verified malicious indicators are preserved regardless of legitimate context.
    """
    for rec in records:
        if rec.relevance == "excluded" or not rec.is_representative:
            continue

        text = rec.fact.get("text", "")
        signal = rec.fact["signal"]
        topic = rec.fact.get("topic", "")

        # ── Verified threat: decisive authoritative finding ──
        if rec.fact.get("decisive") and signal == "concern":
            rec.malicious_hypothesis = f"Authoritative source confirms threat: {text}"
            rec.legitimate_hypothesis = None
            rec.hypothesis_balance = "verified_threat"
            continue

        # ── Authoritative listing (Safe Browsing, scam advisory, blocklist) ──
        if rec.source_type == "authoritative" and signal == "concern":
            rec.malicious_hypothesis = f"Listed by an authoritative source: {text}"
            rec.legitimate_hypothesis = "Authoritative listings can have false positives, but are generally reliable."
            rec.hypothesis_balance = "malicious"
            continue

        # ── Third-party signals: consider legitimate explanation ──
        if _NEWLY_REGISTERED.search(text):
            rec.legitimate_hypothesis = _LEGIT_NEWLY_REGISTERED
            rec.malicious_hypothesis = "Scam sites are often newly registered to avoid detection."
            rec.hypothesis_balance = "ambiguous"  # could be either
            continue

        if _IPQS.search(text):
            rec.legitimate_hypothesis = _LEGIT_IPQS_HIGH
            rec.malicious_hypothesis = "High fraud scores correlate with known scam patterns."
            rec.hypothesis_balance = "ambiguous"
            continue

        if _REDIRECT.search(text) and signal == "weak":
            rec.legitimate_hypothesis = _LEGIT_REDIRECT
            rec.malicious_hypothesis = "Redirects can hide the final malicious destination."
            rec.hypothesis_balance = "legitimate"  # redirects alone are more often legitimate
            continue

        # ── Impersonation: unrelated domain for a mentioned brand ──
        if topic == "impersonation":
            rec.legitimate_hypothesis = _LEGIT_UNRELATED_DOMAIN
            rec.malicious_hypothesis = ("The sender may be impersonating the named brand by using a "
                                         "domain that doesn't belong to it.")
            # If there's a verified sender, heavily favour legitimate
            verified_sender = {c.subject for c in plan.checks
                               if c.kind == "impersonation" and c.status == "resolved"
                               and any(f["signal"] == "clear" for f in c.facts)}
            rec.hypothesis_balance = "legitimate" if verified_sender else "ambiguous"
            continue

        if topic == "freemail":
            rec.legitimate_hypothesis = _LEGIT_FREEMAIL
            rec.malicious_hypothesis = "Scammers commonly use free email services for anonymity."
            rec.hypothesis_balance = "ambiguous"
            continue

        # ── Warning sign from a deterministic check (anomaly or concern) ──
        if signal in ("concern", "anomaly") and rec.source_type == "deterministic":
            rec.malicious_hypothesis = f"Deterministic check found a warning sign: {text}"
            rec.legitimate_hypothesis = None  # no obvious benign explanation for a deterministic concern
            rec.hypothesis_balance = "malicious"
            continue

        # ── Default: ambiguous ──
        if signal in ("concern", "anomaly"):
            rec.malicious_hypothesis = text
            rec.legitimate_hypothesis = "No specific legitimate explanation identified."
            rec.hypothesis_balance = "ambiguous"
        elif signal in ("clear", "neutral"):
            rec.legitimate_hypothesis = text
            rec.hypothesis_balance = "legitimate"

    return records


# ── Stage 4: Calibrated Decision ────────────────────────────────────────────

def _calibrate(records: list[EvidenceRecord]) -> EvaluationResult:
    """Determine the overall threat level and confidence from the evaluated evidence.

    This does NOT replace ``decide.provisional()`` — it provides advisory information
    that ``decide.py`` uses to avoid false positives.

    Decision rules (deterministic, no arbitrary weights):
    - Any ``verified_threat`` record → high_risk, high confidence.
    - Any ``malicious`` record (authoritative) → suspicious, medium+ confidence.
    - All representative records favour ``legitimate`` → no_threat or needs_verification.
    - Mixed records (some ambiguous) → needs_verification.
    """
    result = EvaluationResult(records=records)
    relevant = [r for r in records if r.relevance != "excluded"]
    representatives = [r for r in relevant if r.is_representative]
    result.relevant_count = len(relevant)
    result.excluded_count = len(records) - len(relevant)
    result.excluded_audit = [{"fact_text": r.fact.get("text", ""), "reason": r.exclusion_reason}
                             for r in records if r.relevance == "excluded"]

    # Build correlation groups
    for r in records:
        if r.correlation_group:
            result.groups.setdefault(r.correlation_group, []).append(r)
    result.deduplicated_count = len(representatives)

    # Stage 3 summary
    warning_reps = [r for r in representatives if r.fact["signal"] in ("concern", "anomaly")]
    result.has_verified_threat = any(r.hypothesis_balance == "verified_threat" for r in warning_reps)

    if warning_reps:
        result.all_legitimate_favoured = all(r.hypothesis_balance == "legitimate" for r in warning_reps)
    else:
        result.all_legitimate_favoured = True

    # Stage 4: calibrated threat level
    if result.has_verified_threat:
        result.threat_level = "high_risk"
        result.confidence = "high"
    elif any(r.hypothesis_balance == "malicious" for r in warning_reps):
        result.threat_level = "suspicious"
        result.confidence = "medium"
    elif result.all_legitimate_favoured and warning_reps:
        result.threat_level = "needs_verification"
        result.confidence = "low"
        result.should_downgrade = True
        result.downgrade_reason = ("All warning signs have plausible legitimate explanations "
                                   "and no authoritative source confirms a threat.")
    elif any(r.hypothesis_balance == "ambiguous" for r in warning_reps):
        result.threat_level = "needs_verification"
        result.confidence = "low"
    else:
        result.threat_level = "no_threat"
        result.confidence = "high" if not records else "medium"

    return result


# ── Public API ───────────────────────────────────────────────────────────────

def evaluate(plan: Plan) -> EvaluationResult:
    """Run the full four-stage evidence evaluation pipeline on a TC FlyBy plan.

    Returns an ``EvaluationResult`` that ``decide.py`` uses to calibrate its decision.
    The evaluation never overrides established threat evidence; it only advises when
    a concern outcome may be a false positive.
    """
    # Stage 1: Relevance Gate
    records = _relevance_gate(plan)
    # Stage 2: Deduplication
    records = _deduplicate(records)
    # Stage 3: Dual-Hypothesis
    records = _evaluate_hypotheses(records, plan)
    # Stage 4: Calibrated Decision
    return _calibrate(records)


def should_downgrade_provisional(plan: Plan, provisional_outcome: str | None) -> tuple[bool, str | None]:
    """Quick check: should ``decide.provisional()``'s outcome be downgraded?

    Returns ``(True, reason)`` when the evidence evaluation advises a downgrade.
    Returns ``(False, None)`` when the provisional outcome should stand.

    Only concern outcomes can be downgraded.  Confirmed threats are never downgraded.
    """
    if not provisional_outcome or provisional_outcome in ("confirmed_threat", "no_scam_indicators"):
        return False, None
    result = evaluate(plan)
    if result.should_downgrade:
        return True, result.downgrade_reason
    return False, None
