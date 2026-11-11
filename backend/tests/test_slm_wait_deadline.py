"""FR-03 deadline tests; no Mongo or native model needed."""
import ast
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


def load_wait():
    path = Path(__file__).resolve().parents[1] / "services/higgins/coordinator.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_wait_for_slm")
    advisory = SimpleNamespace(accepted_for_stage=AsyncMock(return_value=None))
    scope = {"slm_advisory": advisory}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    return scope["_wait_for_slm"], advisory


class WaitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.wait, self.advisory = load_wait()
        self.now = datetime.now(timezone.utc)
        self.case = {"expires_at": self.now + timedelta(minutes=5)}
        self.job = {"job_id": "job-A"}
        self.issued = {"expiresAt": (self.now + timedelta(minutes=1)).isoformat()}

    async def test_successful_cited_result(self):
        answer = {"caseFinding": {"reasons": ["E-1"]}}
        self.advisory.accepted_for_stage.return_value = answer
        self.assertEqual(await self.wait("owner", self.case, self.job, "case_finding",
                                         self.issued, "caseFinding"), answer)

    async def test_request_expiry(self):
        self.issued["expiresAt"] = (self.now - timedelta(seconds=1)).isoformat()
        self.assertIsNone(await self.wait("owner", self.case, self.job, "case_finding", self.issued))
        self.advisory.accepted_for_stage.assert_not_awaited()

    async def test_case_expiry(self):
        self.case["expires_at"] = self.now - timedelta(seconds=1)
        self.assertIsNone(await self.wait("owner", self.case, self.job, "tc_hawkeye", self.issued))
        self.advisory.accepted_for_stage.assert_not_awaited()

    async def test_job_expiry(self):
        self.job["expires_at"] = self.now - timedelta(seconds=1)
        self.assertIsNone(await self.wait("owner", self.case, self.job, "tc_hawkeye", self.issued))
        self.advisory.accepted_for_stage.assert_not_awaited()

    async def test_missing_expiry(self):
        self.assertIsNone(await self.wait("owner", self.case, self.job, "tc_hawkeye", {}))
        self.advisory.accepted_for_stage.assert_not_awaited()

    async def test_missing_required_result_times_out(self):
        self.advisory.accepted_for_stage.return_value = {"observations": []}
        issued = {"expiresAt": (self.now + timedelta(milliseconds=25)).isoformat()}
        self.assertIsNone(await self.wait("owner", self.case, self.job,
                                          "case_finding", issued, "caseFinding"))


if __name__ == "__main__":
    unittest.main()
