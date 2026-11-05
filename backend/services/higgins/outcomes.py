"""Apollo case outcomes — the four Findings, fed by both investigation layers.

TC FlyBy and Magnum DI both end a case with one of these four Findings.
Each Finding fixes the assessment it implies, so the two can never disagree.
A general question (nothing submitted to check) has no case outcome.

The four customer-facing Findings:
  scam              — "This is a scam"
  not_scam          — "This is not a scam"
  likely_scam       — "This is likely a scam"
  unable_to_determine — "We are unable to determine if this is a scam"

Historical compatibility:
  confirmed_threat  → scam
  no_scam_indicators → not_scam
  concerning        → likely_scam (historical records only)
"""
from __future__ import annotations

from typing import Optional

# ── The four Findings ────────────────────────────────────────────────────────

OUTCOMES = ("scam", "not_scam", "likely_scam", "unable_to_determine")

LABELS = {
    "scam": "This is a scam",
    "not_scam": "This is not a scam",
    "likely_scam": "This is likely a scam",
    "unable_to_determine": "We are unable to determine if this is a scam",
}

ASSESSMENT = {
    "scam": "concern_found",
    "not_scam": "no_concern_found_within_scope",
    "likely_scam": "concern_found",
    "unable_to_determine": "uncertain",
    # Legacy codes
    "confirmed_threat": "concern_found",
    "no_scam_indicators": "no_concern_found_within_scope",
    "concerning": "concern_found",
}

# Which way each outcome points.
DIRECTION = {outcome: "concern" if assessment == "concern_found" else "clear"
             for outcome, assessment in ASSESSMENT.items() if assessment != "uncertain"}


# ── Historical backward compatibility ────────────────────────────────────────
# Old outcome codes stored in MongoDB → new Finding codes.

LEGACY_MAP = {
    "confirmed_threat": "scam",
    "no_scam_indicators": "not_scam",
    "concerning": "likely_scam",
    # These are unchanged:
    "likely_scam": "likely_scam",
    "unable_to_determine": "unable_to_determine",
}

# All valid codes (new + legacy) for deserialization
ALL_VALID = set(OUTCOMES) | set(LEGACY_MAP.keys())

# Legacy labels (for display of historical records that haven't been migrated)
LEGACY_LABELS = {
    "confirmed_threat": "This is a scam",
    "no_scam_indicators": "This is not a scam",
    "concerning": "This is likely a scam",
}


def normalize(outcome: str | None) -> str | None:
    """Convert a legacy outcome code to the current Finding code. Returns None for None/unknown."""
    if outcome is None:
        return None
    if outcome in OUTCOMES:
        return outcome
    return LEGACY_MAP.get(outcome)


def label(outcome: str | None) -> str | None:
    """The customer-facing label for an outcome code (including legacy codes)."""
    if outcome is None:
        return None
    # Try current labels first, then legacy
    return LABELS.get(outcome) or LEGACY_LABELS.get(outcome) or LABELS.get(normalize(outcome))


def settled_by_flyby(answered_by: Optional[str]) -> bool:
    """TC FlyBy settled the result (answered_by "tc_flyby_*"). Anything else, including results recorded before routing
    existed, was Magnum DI's."""
    return str(answered_by or "").startswith("tc_flyby")


def investigator(answered_by: Optional[str]) -> str:
    """Who settled a result, by name: the one place this is decided."""
    return "TC FlyBy" if settled_by_flyby(answered_by) else "Magnum DI"


# ── Magnum DI outcome criteria (describes the four Findings for the AI model) ──

CRITERIA = (
    "Apollo's case Finding. "
    "scam (assessment concern_found): the investigation has established that this is a scam — a known scam "
    "listing, a fake identity used for deception, an established deceptive activity, or a complete scam pattern "
    "corroborated by independent evidence. Requires at least one S-rule (S1 known scam, S2 fake identity, "
    "S3 scam activity, S4 complete pattern) to pass. "
    "not_scam (assessment no_concern_found_within_scope): the investigation has verified the identity, "
    "destinations, purpose and resolved all scam warnings. All applicable N-rules (N1 genuine identity, "
    "N2 genuine destinations, N3 genuine purpose, N4 warnings resolved) must pass. Unknown is not passed. "
    "likely_scam (assessment concern_found): strong signs of impersonation, a strong scam pattern match, "
    "or several independent scam indicators — when no S-rule passes but the evidence strongly supports a scam "
    "and no genuine explanation resolves it. Requires at least one L-rule (L1 impersonation signs, L2 strong "
    "pattern, L3 independent indicators) to pass. "
    "unable_to_determine (assessment uncertain): the available evidence cannot establish more. Too little "
    "information, important checks unavailable, weak indicators only, conflicting results, or no scam indicators "
    "found but legitimacy cannot be established. "
    "Null only when nothing was submitted to check (a general question)."
)
