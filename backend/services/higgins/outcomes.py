"""Apollo case outcomes — one outcome system fed by both investigation layers.

TC FlyBy and Magnum DI both end a case with one of these. Each outcome fixes the assessment it implies, so
the two can never disagree. A general question (nothing submitted to check) has no case outcome.
"""
from __future__ import annotations

from typing import Optional

OUTCOMES = ("no_scam_indicators", "concerning", "likely_scam", "confirmed_threat", "unable_to_determine")

LABELS = {
    "no_scam_indicators": "No scam indicators found",
    "concerning": "Concerning",
    "likely_scam": "Likely scam",
    "confirmed_threat": "Confirmed scam or threat",
    "unable_to_determine": "Unable to determine",
}

ASSESSMENT = {
    "no_scam_indicators": "no_concern_found_within_scope",
    "concerning": "concern_found",
    "likely_scam": "concern_found",
    "confirmed_threat": "concern_found",
    "unable_to_determine": "uncertain",
}

# Which way each outcome points, read from its assessment: a finding pointing the same way supports it. An outcome
# that is uncertain points neither way.
DIRECTION = {outcome: "concern" if assessment == "concern_found" else "clear"
             for outcome, assessment in ASSESSMENT.items() if assessment != "uncertain"}


def settled_by_flyby(answered_by: Optional[str]) -> bool:
    """TC FlyBy settled the result (answered_by "tc_flyby_*"). Anything else, including results recorded before routing
    existed, was Magnum DI's."""
    return str(answered_by or "").startswith("tc_flyby")


def investigator(answered_by: Optional[str]) -> str:
    """Who settled a result, by name: the one place this is decided."""
    return "TC FlyBy" if settled_by_flyby(answered_by) else "Magnum DI"

# What each outcome means — stated once, here, and given to Magnum DI as the schema's description.
CRITERIA = (
    "Apollo's case outcome. "
    "no_scam_indicators (assessment no_concern_found_within_scope): the checks performed found no scam indicators — "
    "this does not mean ApolloSG has proven the item safe, so never describe it as safe. "
    "concerning (assessment concern_found): established warning signs backed by at least one medium- or high-confidence "
    "finding. Third-party search results, reputation scores or weak signals alone never establish 'concerning'. "
    "likely_scam (assessment concern_found): the evidence, together with an established scam pattern, points to a scam — "
    "without proof about this particular sender. Requires at least one medium- or high-confidence finding. "
    "confirmed_threat (assessment concern_found): an authoritative source names this exact link, number, address or "
    "company as a scam or threat. "
    "unable_to_determine (assessment uncertain): the available evidence can't establish more. "
    "When the investigation is partial (completion 'partial'), the outcome cannot exceed 'concerning'. "
    "Null only when nothing was submitted to check (a general question)."
)
