"""Wright v1 schema acceptance/rejection; no inference or verdict production."""
import pytest
from services.higgins.wright_semantic_contract import validate_wright_semantic

def valid():
    return {
        "version": "wright.semantic.v1",
        "classification": "ambiguous",
        "scamTypes": [],
        "intent": "Requests a response; intent not independently verified",
        "coercion": "uncertain",
        "exposure": {"payment": "UNKNOWN", "credentials": "UNKNOWN",
                     "identity": "UNKNOWN", "remoteAccess": "UNKNOWN"},
        "narrative": "The source requests a reply but does not establish fraud.",
        "uncertainty": "Sender identity not independently verified",
        "supportingEvidenceIds": [],
    }

def test_accepts_uncertain_case_without_invented_evidence():
    assert validate_wright_semantic(valid(), {"source-1"}).classification == "ambiguous"

@pytest.mark.parametrize("change", [
    {"version": "wright.semantic.v2"},
    {"classification": "definitely_scam"},
    {"scamTypes": ["x"] * 7},
    {"supportingEvidenceIds": ["other-device-case"]},
    {"coercion": "present"},
    {"exposure": {"payment": "CONFIRMED", "credentials": "UNKNOWN",
                  "identity": "UNKNOWN", "remoteAccess": "UNKNOWN"}},
    {"verdict": "NO_THREAT_IDENTIFIED"},
])
def test_rejects_unsupported_or_unsafe_semantics(change):
    case = valid()
    case.update(change)
    with pytest.raises((ValueError, TypeError)):
        validate_wright_semantic(case, {"source-1"})

def test_cited_semantics():
    case = valid()
    case.update(classification="legitimate_context", supportingEvidenceIds=["source-1"])
    assert validate_wright_semantic(case, {"source-1"}).supporting_evidence_ids == ["source-1"]
