"""Regression guard: an investigation verdict requires a cited On-device AI Finding.

These source-level checks run without MongoDB, model downloads or external services.
They protect the execution boundary; device-level acceptance is still required.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestOnDeviceVerdictAuthority(unittest.TestCase):
    def test_coordinator_has_no_legacy_verdict_fallback(self):
        source = (ROOT / "services/higgins/coordinator.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        run_turn = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_turn")
        body = ast.get_source_segment(source, run_turn)
        self.assertIn("_await_case_finding(", body)
        self.assertIn("_commit_slm_finding(", body)
        self.assertIn('Outcome("device_unavailable"', body)
        self.assertNotIn("_commit_flyby(", body)
        self.assertNotIn("provider.generate(", body)
        self.assertNotIn("claim_magnum_call(", body)
        self.assertNotIn("ai_settings.investigation_model(", body)
        self.assertNotIn('"provider_model": job_model', body)

    def test_handoff_is_a_core_capability_without_an_environment_switch(self):
        for name in ("services/higgins/slm_advisory.py", "services/higgins/coordinator.py", "routers/slm_handoff.py"):
            with self.subTest(name=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("APOLLO_SLM_HANDOFF", source)


if __name__ == "__main__":
    unittest.main()
