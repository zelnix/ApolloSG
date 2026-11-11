"""Standalone unit tests for coordinator's read-only Luddish advisory handoff.

No Mongo server, native model, Gemini call or global pytest fixtures required.
"""
import asyncio
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class Cursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    async def to_list(self, _length):
        return self.documents


class Collection:
    def __init__(self):
        self.documents = []
        self.queries = []

    def find(self, query, _projection):
        self.queries.append(query)
        documents = [
            item for item in self.documents
            if item.get("owner_id") == query.get("owner_id")
            and item.get("case_id") == query.get("case_id")
            and item.get("job_id") == query.get("job_id")
            and item.get("kind") == query.get("kind")
            and item.get("fulfilled") is True
            and item.get("submission", {}).get("state") == "advisory_received"
            and item.get("expires_at") > query["expires_at"]["$gt"]
        ]
        return Cursor(documents)


collection = Collection()
fake_db = types.ModuleType("core.db")
fake_db.db = types.SimpleNamespace(investigation_device_requests=collection)
fake_db.now_utc = lambda: datetime.now(timezone.utc)
sys.modules["core.db"] = fake_db
fake_repo = types.ModuleType("services.higgins.repository")
fake_repo.dec_json = lambda value: value
sys.modules["services.higgins.repository"] = fake_repo

from services.higgins import slm_advisory  # noqa: E402


CASE = {"case_id": "case-A", "revision": 7, "active_job_id": "job-A",
        "status": "investigating", "epoch": "epoch-A"}
JOB = {"job_id": "job-A", "status": "investigating", "epoch": "epoch-A"}


def candidate(role="tc_hawkeye", *, citation="E-1", revision=7, owner="owner-A"):
    return {
        "owner_id": owner, "case_id": "case-A", "job_id": "job-A",
        "kind": "slm_advisory", "fulfilled": True, "epoch": "epoch-A",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=2),
        "request_ciphertext": {
            "caseId": "case-A", "caseRevision": revision, "requestId": "request-A",
            "role": role,
            "operation": "investigation_readiness" if role == "higgins_triage" else
                         "explanation" if role == "luddish" else "evidence_reasoning",
            "question": "Which verifications are missing?",
            "evidence": [{"evidenceId": "E-1", "text": "message"}],
        },
        "submission": {"state": "advisory_received", "model_id": "local-only",
            "result_ciphertext": {
                "observations": [],
                "contradictions": [],
                "alternativeExplanations": [],
                "verificationSuggestions": [{"text": "Check licence", "evidenceIds": [citation]}],
                "draftExplanation": None,
            }},
    }


class TestAdvisoryRead(unittest.TestCase):
    def setUp(self):
        collection.documents = []
        collection.queries = []
        self.environ = patch.dict(os.environ, {"APOLLO_SLM_HANDOFF": "on"})
        self.environ.start()

    def tearDown(self):
        self.environ.stop()

    def read(self, case=None, job=None, role="tc_hawkeye", owner="owner-A"):
        return asyncio.run(slm_advisory.accepted_for_stage(owner, case or CASE, job or JOB, role))

    def test_valid_matching_case_and_evidence_are_advisory_only(self):
        collection.documents = [candidate()]
        value = self.read()
        self.assertEqual(value["classification"], "unverified_slm_advisory")
        self.assertEqual(value["verificationSuggestions"][0]["evidenceIds"], ["E-1"])
        self.assertNotIn("verdict", value)
        self.assertNotIn("score", value)

    def test_wrong_role_does_not_hide_older_valid_role(self):
        collection.documents = [candidate("magnum_di"), candidate("tc_hawkeye")]
        self.assertEqual(self.read()["role"], "tc_hawkeye")

    def test_rejects_other_owner_and_stale_revision(self):
        collection.documents = [candidate()]
        self.assertIsNone(self.read(owner="owner-B"))
        collection.documents = [candidate(revision=6)]
        self.assertIsNone(self.read())

    def test_rejects_citations_not_from_the_original_request(self):
        collection.documents = [candidate(citation="other-case")]
        self.assertIsNone(self.read())

    def test_rejects_cancelled_job_and_changed_epoch(self):
        collection.documents = [candidate()]
        self.assertIsNone(self.read(case={**CASE, "status": "cancelled"}))
        self.assertIsNone(self.read(job={**JOB, "epoch": "epoch-B"}))

    def test_expired_or_disabled_advice_is_unavailable(self):
        doc = candidate()
        doc["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        collection.documents = [doc]
        self.assertIsNone(self.read())
        collection.documents = [candidate()]
        with patch.dict(os.environ, {"APOLLO_SLM_HANDOFF": "off"}):
            self.assertIsNone(self.read())
        self.assertEqual(len(collection.queries), 1)

    def test_slm_questions_prioritise_only_existing_checks(self):
        from types import SimpleNamespace
        checks = [
            SimpleNamespace(subject="Phone number", question="Check caller number"),
            SimpleNamespace(subject="Business licence", question="Verify licence registration"),
            SimpleNamespace(subject="Website", question="Inspect website domain"),
        ]
        original_ids = {id(check) for check in checks}
        advice = {"verificationSuggestions": [
            {"text": "Verify business licence registration", "evidenceIds": ["E-1"]}
        ]}
        slm_advisory.prioritise_existing_checks(checks, None, advice)
        self.assertEqual(checks[0].subject, "Business licence")
        self.assertEqual({id(check) for check in checks}, original_ids)
        self.assertEqual(len(checks), 3)

    def test_no_slm_advice_preserves_deterministic_order(self):
        from types import SimpleNamespace
        checks = [
            SimpleNamespace(subject="Website", question="Check domain"),
            SimpleNamespace(subject="Business licence", question="Verify registration"),
        ]
        slm_advisory.prioritise_existing_checks(checks, None, {})
        self.assertEqual([check.subject for check in checks], ["Website", "Business licence"])

    def test_only_bounded_verification_suggestions_can_be_returned(self):
        self.assertEqual(slm_advisory.advisory_verification_questions({
            "verificationSuggestions": [{"text": "Check A"}] * 50,
        }), ["Check A"] * 8)


if __name__ == "__main__":
    unittest.main()
