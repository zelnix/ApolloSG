"""Apollo case outcomes — the four Findings, fed by both investigation layers.

TC Hawkeye and Magnum DI both end a case with one of these four Findings, each carrying a 0-100 Findings
Rating (services.higgins.tc_flyby.scoring). Each Finding fixes the assessment it implies, so the two can
never disagree. A general question (nothing submitted to check) has no case outcome.

The four customer-facing Findings (Apollo PRD v2.2 §2.1 — exact, inclusive rating boundaries):
  scam              85-100  "This is a Scam"
  likely_scam        60-84  "This is Likely a Scam"
  unlikely_scam      25-59  "This is Unlikely a Scam"
  not_scam            0-24  "This is Not a Scam"

Historical compatibility:
  confirmed_threat    → scam
  no_scam_indicators  → not_scam
  concerning          → likely_scam (historical records only)
  unable_to_determine → unlikely_scam — the two were the same idea in practice: neither a scam nor
                         positively verified, the normal "nothing meaningful found" outcome (PRD's
                         "Unlikely a Scam"). A genuinely incomplete investigation (a check that never
                         got an answer, even after retrying) is now its own non-Finding case status
                         ("technical_issue" — tc_flyby/triage.py, decide.py), not a Finding at all.
"""
from __future__ import annotations

from typing import Optional

# ── The four Findings ────────────────────────────────────────────────────────

OUTCOMES = ("scam", "not_scam", "likely_scam", "unlikely_scam")

LABELS = {
    "scam": "This is a scam",
    "not_scam": "This is not a scam",
    "likely_scam": "This is likely a scam",
    "unlikely_scam": "This is unlikely a scam",
}

ASSESSMENT = {
    "scam": "concern_found",
    "not_scam": "no_concern_found_within_scope",
    "likely_scam": "concern_found",
    "unlikely_scam": "no_concern_found_within_scope",
    # Legacy codes
    "confirmed_threat": "concern_found",
    "no_scam_indicators": "no_concern_found_within_scope",
    "concerning": "concern_found",
    # unable_to_determine kept at its original "uncertain" assessment for backward compatibility with
    # records already stored that way — normalize()/label() still read it as unlikely_scam for display,
    # but a stored record's own assessment field is never rewritten.
    "unable_to_determine": "uncertain",
}

# Which way each outcome points. "uncertain" (legacy unable_to_determine only) points neither way.
DIRECTION = {outcome: "concern" if assessment == "concern_found" else "clear"
             for outcome, assessment in ASSESSMENT.items() if assessment != "uncertain"}


# ── Historical backward compatibility ────────────────────────────────────────
# Old outcome codes stored in MongoDB → new Finding codes.

LEGACY_MAP = {
    "confirmed_threat": "scam",
    "no_scam_indicators": "not_scam",
    "concerning": "likely_scam",
    "unable_to_determine": "unlikely_scam",
    # This is unchanged:
    "likely_scam": "likely_scam",
}

# All valid codes (new + legacy) for deserialization
ALL_VALID = set(OUTCOMES) | set(LEGACY_MAP.keys())

# Legacy labels (for display of historical records that haven't been migrated)
LEGACY_LABELS = {
    "confirmed_threat": "This is a scam",
    "no_scam_indicators": "This is not a scam",
    "concerning": "This is likely a scam",
    "unable_to_determine": "This is unlikely a scam",
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
    """TC Hawkeye settled the result (answered_by "tc_flyby_*"). Anything else, including results recorded before routing
    existed, was Magnum DI's."""
    return str(answered_by or "").startswith("tc_flyby")


def investigator(answered_by: Optional[str]) -> str:
    """Who settled a result, by name: the one place this is decided."""
    return "TC Hawkeye" if settled_by_flyby(answered_by) else "Magnum DI"


# ── Magnum DI outcome criteria (describes the four Findings for the AI model) ──

CRITERIA = (
    "Apollo's case Finding and its 0-100 Findings Rating. "
    "scam (85-100, concern_found): decisive evidence of a fraudulent mechanism or activity — a known scam "
    "listing, a fake identity used for deception, an established deceptive activity, or a complete scam pattern "
    "corroborated by independent evidence. "
    "likely_scam (60-84, concern_found): substantial evidence of fraud, manipulation or impersonation — strong "
    "signs of impersonation, a strong scam pattern match, or several independent scam indicators, when nothing "
    "genuine resolves it. "
    "unlikely_scam (25-59, no_concern_found_within_scope): a benign or routine communication without "
    "meaningful scam indicators and without enough positive verification to call it genuine — the normal "
    "finding for ordinary, unverified communications. "
    "not_scam (0-24, no_concern_found_within_scope): positive verification (identity, destination, channel or "
    "transaction) establishes the communication's legitimacy. "
    "Null only when nothing was submitted to check (a general question)."
)
