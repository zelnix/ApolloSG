"""Source-level regression guards for mandatory SLM consolidation.

These complement behavioural contract tests. They intentionally do not demand
removal of legacy functions; they protect the supported execution path while
refactoring candidates are evaluated.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
COORDINATOR = ROOT / "backend/services/higgins/coordinator.py"
LAYOUT = ROOT / "frontend/app/_layout.tsx"
GATE = ROOT / "frontend/src/domain/slm/RequiredSLMGate.tsx"
BOOTSTRAP = ROOT / "frontend/src/domain/slm/bootstrap.native.ts"
RUNTIME = ROOT / "frontend/src/domain/slm/sharedRuntime.ts"
WORKFLOW = ROOT / ".github/workflows/slm-contract.yml"


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def called_names(node):
    return {call.func.id for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}


class SLMRedundancyRegression(unittest.TestCase):
    def test_mandatory_investigation_never_commits_legacy_hawkeye_result(self):
        tree = ast.parse(COORDINATOR.read_text())
        run = function(tree, "run_turn")
        calls = called_names(run)
        self.assertIn("_await_escalation_assessment", calls)
        self.assertIn("_await_case_finding", calls)
        self.assertIn("_commit_slm_finding", calls)
        self.assertNotIn("_commit_flyby", calls)
        self.assertLess(
            next(n.lineno for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_await_escalation_assessment"),
            next(n.lineno for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_await_case_finding"),
        )

    def test_no_hawkeye_or_cloud_fallback_on_missing_slm_finding(self):
        run = function(ast.parse(COORDINATOR.read_text()), "run_turn")
        self.assertNotIn("_commit_flyby", called_names(run))
        self.assertIn("_commit_slm_finding", called_names(run))
        self.assertIn("device_unavailable", ast.get_source_segment(COORDINATOR.read_text(), run))

    def test_existing_global_compatibility_gate_remains_in_place(self):
        layout = LAYOUT.read_text()
        self.assertIn("<RequiredSLMGate>", layout)
        self.assertIn("</RequiredSLMGate>", layout)
        self.assertLess(layout.index("<RequiredSLMGate>"), layout.index("<SharedLuddishStartup"))
        gate = GATE.read_text()
        self.assertIn("checkRequiredSLMCompatibility(", gate)
        self.assertIn('status: "incompatible"', gate)

    def test_one_shared_runtime_registration_boundary(self):
        bootstrap = BOOTSTRAP.read_text()
        runtime = RUNTIME.read_text()
        self.assertIn("if (runtime) return Promise.resolve(true)", bootstrap)
        self.assertIn("if (startup) return startup", bootstrap)
        self.assertIn("setSharedSLM(created)", bootstrap)
        self.assertIn("let shared: SLMAdapter | null = null", runtime)
        self.assertIn("export function getSharedSLM()", runtime)

    def test_contract_ci_keeps_both_languages_and_coordinator(self):
        workflow = WORKFLOW.read_text()
        for expected in (
            "tests/slmRuntime.test.ts",
            "tests/slmAskHiggins.test.ts",
            "tests/test_slm_contract.py",
            "tests/test_slm_advisory_stage.py",
            "services/higgins/coordinator.py",
        ):
            self.assertIn(expected, workflow)


if __name__ == "__main__":
    unittest.main()
