"""FR-04 replay matching tests, without a database or network."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


def load_matcher():
    path = Path(__file__).resolve().parents[1] / "routers/slm_handoff.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_same_slm_submission")
    scope = {"repo": SimpleNamespace(dec_json=lambda value: value)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    return scope["_same_slm_submission"]


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.match = load_matcher()
        self.answer = {"observations": [], "verificationSuggestions": [{"text": "Check licence", "evidenceIds": ["E-1"]}]}
        self.stored = {"submission": {"state": "advisory_received", "model_id": "local",
                                      "result_ciphertext": self.answer}}

    def test_identical_replay_is_acknowledged(self):
        self.assertTrue(self.match(self.stored, "local", self.answer))

    def test_conflicting_payload_is_rejected(self):
        self.assertFalse(self.match(self.stored, "local", {"observations": ["new"]}))

    def test_other_model_is_rejected(self):
        self.assertFalse(self.match(self.stored, "different", self.answer))

    def test_unaccepted_submission_is_rejected(self):
        self.assertFalse(self.match({"submission": {"state": "pending", "model_id": "local",
                                                   "result_ciphertext": self.answer}}, "local", self.answer))

    def test_atomic_claim_requires_unanswered_and_unexpired_request(self):
        """Guard against replacing CAS with a read-then-write race."""
        path = Path(__file__).resolve().parents[1] / "routers/slm_handoff.py"
        tree = ast.parse(path.read_text())
        handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "receive_advisory")
        atomic_calls = [node for node in ast.walk(handler)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "find_one_and_update"]
        self.assertEqual(len(atomic_calls), 1)
        query = atomic_calls[0].args[0]
        self.assertIsInstance(query, ast.Dict)
        keys = [node.value for node in query.keys if isinstance(node, ast.Constant)]
        for required in ("owner_id", "case_id", "request_id", "kind", "submission", "expires_at"):
            self.assertIn(required, keys)
        values = dict(zip(keys, query.values))
        self.assertIsInstance(values["submission"], ast.Constant)
        self.assertIsNone(values["submission"].value)

    def test_missing_or_malformed_submission_is_rejected(self):
        self.assertFalse(self.match(None, "local", self.answer))
        self.assertFalse(self.match({"submission": {"state": "advisory_received",
                                                   "model_id": "local"}}, "local", self.answer))


if __name__ == "__main__":
    unittest.main()
