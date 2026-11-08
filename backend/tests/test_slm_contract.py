"""Standalone tests of the Luddish/backend advisory contract. No DB or pytest fixture."""
import unittest
from pydantic import ValidationError
from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning,
)


def request():
    return SLMReasoningRequest.model_validate({
        "caseId": "case-A", "caseRevision": 7, "requestId": "req-A",
        "role": "tc_hawkeye", "operation": "evidence_reasoning",
        "question": "What warrants verification?",
        "evidence": [{"evidenceId": "E-1", "text": "Guaranteed monthly return"}],
    })


def result(**changes):
    data = {
        "caseId": "case-A", "caseRevision": 7, "requestId": "req-A",
        "execution": "on_device", "modelId": "qwen-test",
        "answer": {
            "observations": [{"text": "The message claims a guaranteed return", "evidenceIds": ["E-1"]}],
            "contradictions": [], "alternativeExplanations": [],
            "verificationSuggestions": [{"text": "Verify the claim independently", "evidenceIds": ["E-1"]}],
            "draftExplanation": None,
        },
    }
    data.update(changes)
    return SLMReasoningResult.model_validate(data)


class ContractTests(unittest.TestCase):
    def test_advisory_only(self):
        accepted = accept_advisory_reasoning(request(), result())
        self.assertEqual(accepted.observations[0].evidence_ids, ["E-1"])
        self.assertNotIn("verdict", accepted.wire())
        self.assertNotIn("score", accepted.wire())

    def test_rejects_case_mismatch(self):
        for field, val in (("caseId", "case-B"), ("caseRevision", 8), ("requestId", "req-B")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "slm_request_mismatch"):
                accept_advisory_reasoning(request(), result(**{field: val}))

    def test_rejects_unrecognised_citation(self):
        wrong = result(answer={
            "observations": [{"text": "Other case", "evidenceIds": ["other-case"]}],
            "contradictions": [], "alternativeExplanations": [],
            "verificationSuggestions": [], "draftExplanation": None,
        })
        with self.assertRaisesRegex(ValueError, "unrecognised_slm_evidence"):
            accept_advisory_reasoning(request(), wrong)

    def test_rejects_generated_verdict_or_score(self):
        with self.assertRaises(ValidationError):
            result(answer={
                "observations": [], "contradictions": [], "alternativeExplanations": [],
                "verificationSuggestions": [], "draftExplanation": None,
                "verdict": "This is a Scam", "score": 99,
            })

    def test_rejects_duplicate_evidence_and_input_overflow(self):
        with self.assertRaises(ValidationError):
            SLMReasoningRequest.model_validate({
                **request().wire(), "evidence": [
                    {"evidenceId": "E-1", "text": "a"},
                    {"evidenceId": "E-1", "text": "b"},
                ]
            })
        with self.assertRaises(ValidationError):
            SLMReasoningRequest.model_validate({
                **request().wire(), "evidence": [{"evidenceId": "E-1", "text": "x" * 120001}],
            })

    def test_unavailable_is_not_a_success(self):
        with self.assertRaises(ValidationError):
            result(execution="cloud")
        with self.assertRaises(ValidationError):
            result(simulated=True)


if __name__ == "__main__":
    unittest.main()
