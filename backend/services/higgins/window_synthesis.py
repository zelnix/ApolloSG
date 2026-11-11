"""Evidence-cited cross-window reconciliation; interpretations never become verified facts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence

@dataclass(frozen=True)
class Synthesis:
    status: str
    classifications: tuple[str, ...]
    contradictory: bool
    evidence_ids: tuple[str, ...]
    uncertainties: tuple[str, ...]


def synthesise_window_interpretations(
    interpretations: Sequence[Mapping],
    expected_window_ids: set[str],
    allowed_evidence_ids: set[str],
) -> Synthesis:
    """Conservative synthesis: preserve disagreement, never vote into a verdict.

    Inputs must be individually schema-validated Wright outputs. This function
    additionally checks window coverage and evidence IDs, not semantic truth.
    """
    seen: set[str] = set()
    labels: set[str] = set()
    citations: set[str] = set()
    uncertainty: set[str] = set()
    allowed_labels = {"scam_indicators", "legitimate_context", "ambiguous", "insufficient_evidence"}
    for item in interpretations:
        wid = item.get("windowId")
        result = item.get("result")
        if not isinstance(wid, str) or wid not in expected_window_ids or wid in seen or not isinstance(result, dict):
            return Synthesis("limited", (), False, (), ("invalid_or_duplicate_window",))
        seen.add(wid)
        label = result.get("classification")
        refs = result.get("supportingEvidenceIds")
        if label not in allowed_labels or not isinstance(refs, list) or any(
            not isinstance(ref, str) or ref not in allowed_evidence_ids for ref in refs
        ):
            return Synthesis("limited", (), False, (), ("invalid_interpretation_or_citation",))
        labels.add(label)
        citations.update(refs)
        if result.get("uncertainty"):
            uncertainty.add(str(result["uncertainty"])[:600])
    if seen != expected_window_ids or not seen:
        return Synthesis("limited", tuple(sorted(labels)), False, tuple(sorted(citations)),
                         ("unexamined_evidence_windows",))
    contradiction = "scam_indicators" in labels and "legitimate_context" in labels
    if contradiction:
        uncertainty.add("Contradictory interpretations across source windows; further investigation required.")
    return Synthesis("conflicting" if contradiction else "complete",
                     tuple(sorted(labels)), contradiction, tuple(sorted(citations)), tuple(sorted(uncertainty)))
