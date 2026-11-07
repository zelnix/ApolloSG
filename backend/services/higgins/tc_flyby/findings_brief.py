"""TC Hawkeye — Higgins Findings Brief (Apollo PRD v2.2 Phase 5).

Re-presents what report.compose() already established, under the six approved headers, so the
evidence behind a Finding is never buried in prose:

    Finding               one of the four approved Findings labels, exactly.
    Findings Rating       the evidence-backed 0-100 score.
    What ApolloSG Found   the actual investigative discoveries (names, domains, phone numbers,
                          claims, suspicious behaviour) that were found.
    Why This Matters      Higgins' explanation of the scam mechanism, in everyday language.
    What Was Verified     what TC Hawkeye actually checked, the results, authoritative sources
                          and any relevant verification limitations.
    Recommended Action    one clear primary action, with additional steps only when necessary.

Nothing here is invented — every field is read from the already-composed result dict and the
Findings Rating breakdown; this module only arranges them under the required presentation. Higgins
Luddish remains the single explanatory voice: the text itself is unchanged, only re-grouped.
"""
from __future__ import annotations

import re

from services.higgins import outcomes
from services.higgins.tc_flyby.scoring import ScoreBreakdown


def _section(markdown: str, heading: str) -> str:
    """One **Heading** block's body out of the explanationMarkdown, or "" when absent."""
    pattern = re.compile(r"\*\*" + re.escape(heading) + r"\*\*\n(.*?)(?=\n\*\*|\Z)", re.I | re.S)
    found = pattern.search(markdown or "")
    return found.group(1).strip() if found else ""


def build(result: dict, breakdown: ScoreBreakdown, taxonomy: dict | None) -> dict:
    """The six-header Findings Brief for one TC Hawkeye Finding."""
    outcome = result.get("outcome")
    found_items = [f["text"] for f in (result.get("findings") or [])] or \
        ["Nothing specific was established beyond what's listed under what isn't certain."]
    why_matters = (_section(result.get("explanationMarkdown"), "What it means")
                   or result.get("attentionReason") or result.get("overview") or "")
    actions = result.get("actions") or []
    idx = result.get("recommendedActionIndex")
    primary = actions[idx] if isinstance(idx, int) and 0 <= idx < len(actions) else (actions[0] if actions else None)
    additional = [a for i, a in enumerate(actions) if a is not primary]
    return {
        "finding": outcomes.label(outcome) or "Unable to determine",
        "findingsRating": breakdown.rating,
        "whatApolloFound": found_items,
        "whyThisMatters": why_matters,
        "whatWasVerified": {"summary": result.get("scope") or "", "limitations": result.get("uncertainties") or []},
        "recommendedAction": {"primary": primary, "additional": additional[:2]},
        "taxonomy": taxonomy,
    }
