"""Behavioural regression coverage for mandatory on-device escalation and Finding contracts.

Standalone: no MongoDB, Gemini, native model, or global test fixtures.
"""
import unittest
from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning,
)

BASE = {
    "caseId": "case-1", "caseRevision": 3, "requestId": "req-1",
    "question": "Assess supplied evidence",
    "evidence": [{"evidenceId": "own-1", "text": "Unverified payment request"}],
}
EMPTY = {
    "observations": [], "contradictions": [], "alternativeExplanations": [],
    "verificationSuggestions": [], "draftExplanation": None,
}


def accepted(role, operation, answer, *, request_changes=None, result_changes=None):
    request = SLMReasoningRequest.model_validate({
        **BASE, "role": role, "operation": operation, **(request_changes or {}),
    })
    result = SLMReasoningResult.model_validate({
        "caseId": BASE["caseId"], "caseRevision": BASE["caseRevision"],
        "requestId": BASE["requestId"], "execution": "on_device",
        "modelId": "local-test", "answer": {**EMPTY, **answer},
        **(result_changes or {}),
    })
    return accept_advisory_reasoning(request, result)


class MandatorySLMBehaviour(unittest.TestCase):
    def assessment(self, decision, evidence_ids=None, gaps=None):
        return {"escalationAssessment": {
            "decision": decision, "rationale": "Requires evidence-based assessment",
            "evidenceIds": evidence_ids if evidence_ids is not None else ["own-1"],
            "materialGaps": gaps if gaps is not None else [],
        }}

    def test_all_supported_escalation_decisions(self):
        for decision, gaps in (
            ("proceed_local", []),
            ("escalate", ["Independent corroboration missing"]),
            ("additional_evidence_required", ["Original source missing"]),
        ):
            with self.subTest(decision=decision):
                answer = accepted("higgins_escalation_assessment", "escalation_assessment",
                                  self.assessment(decision, gaps=gaps))
                self.assertEqual(answer.escalation_assessment.decision, decision)

    def test_missing_escalation_never_counts_as_success(self):
        with self.assertRaisesRegex(ValueError, "invalid_escalation_assessment"):
            accepted("higgins_escalation_assessment", "escalation_assessment", {})

    def test_proceed_local_rejects_unresolved_material_gaps(self):
        with self.assertRaisesRegex(ValueError, "unresolved_material_gaps"):
            accepted("higgins_escalation_assessment", "escalation_assessment",
                     self.assessment("proceed_local", gaps=["Missing verification"]))

    def test_escalation_cannot_cite_another_device_evidence(self):
        with self.assertRaisesRegex(ValueError, "invalid_escalation_assessment"):
            accepted("higgins_escalation_assessment", "escalation_assessment",
                     self.assessment("escalate", evidence_ids=["other-device-evidence"],
                                     gaps=["Unverified"]))

    def test_finding_requires_grounded_reasons(self):
        finding = {"caseFinding": {
            "outcome": "unlikely_scam", "explanation": "Evidence is limited",
            "reasons": [{"text": "Claim present", "evidenceIds": ["own-1"]}],
            "uncertainty": "Sender unverified", "advice": "Verify independently",
        }}
        answer = accepted("case_finding", "case_finding", finding)
        self.assertEqual(answer.case_finding.reasons[0].evidence_ids, ["own-1"])
        finding["caseFinding"]["reasons"][0]["evidenceIds"] = ["other-device-evidence"]
        with self.assertRaisesRegex(ValueError, "unrecognised_slm_evidence"):
            accepted("case_finding", "case_finding", finding)

    def test_request_identity_must_match(self):
        for field, value in (("caseId", "other-case"), ("caseRevision", 4), ("requestId", "other-request")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "slm_request_mismatch"):
                accepted("higgins_escalation_assessment", "escalation_assessment",
                         self.assessment("escalate", gaps=["Unknown"]),
                         result_changes={field: value})


if __name__ == "__main__":
    unittest.main()
