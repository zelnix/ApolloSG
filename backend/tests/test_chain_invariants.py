"""Chain invariants, proved as tests (they never run in the app):

  Higgins Triage → TC Hawkeye → Magnum DI (when warranted) → Evidence Lock → Higgins Luddish → Findings Brief.

1. Higgins can't create or alter threats. Higgins' explanation (services/higgins/explain) sits beside the validated
   result and changes nothing in it: the same outcome, attention, findings, evidence and sources, for every outcome and
   every attention level. The Higgins modules never write to anything that holds a threat, and Ask Higgins' only way
   to a case is the shared pipeline, which opens a case for Higgins Triage — never an outcome, attention or threat.
2. Presentation can't silently change the verdict, severity, confidence or status: a briefing that says anything else
   fails its Fidelity Check (the phone then shows Apollo's own wording — tests/chainInvariants.test.ts).

Run: cd /app/backend && python -m pytest tests/test_chain_invariants.py -q
"""
from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path

import pytest

from services.higgins import coordinator, explain, outcomes
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse
from services.higgins.explain import facts as facts_mod
from services.higgins.explain import fidelity, render

BACKEND = Path(__file__).resolve().parents[1]
OUTCOMES = list(outcomes.LABELS)
ATTENTION = ["urgent", "action_needed", "review", "none"]
BY = ["tc_flyby", "magnum_di"]


def result(outcome: str, attention: str) -> HigginsResponse:
    clear = outcome == "no_scam_indicators"
    return HigginsResponse(
        revision=1,
        overview="The message uses CommBank's name, but the link goes to commbank-cancel.co, which isn't CommBank's domain.",
        explanation_markdown="**What was found**\n- commbank-cancel.co isn't one of CommBank's published domains.",
        assessment="no_concern_found_within_scope" if clear else "uncertain" if outcome == "unable_to_determine" else "concern_found",
        outcome=outcome, attention=attention,
        attention_reason="The link isn't CommBank's domain." if attention in ("urgent", "action_needed") else None,
        findings=[Finding(id="f1", text="commbank-cancel.co isn't one of CommBank's published domains.", basis="observation",
                          confidence="high", evidence_ids=["e1"], source_ids=["s1"]),
                  Finding(id="f2", text="The message asks for your NetBank password.", basis="observation", confidence="medium",
                          evidence_ids=["e1"])],
        uncertainties=["Apollo can't confirm who actually sent this."], scope="TC Hawkeye examined the submitted message.",
        source_ids=["s1"], remaining_evidence_ids=[],
        actions=[] if clear else [ActionProposal(id="a1", kind="instruction", label="Don't open the link",
                                                 instruction="Do not open commbank-cancel.co.")],
        recommended_action_id=None if clear else "a1", completion="complete")


SOURCES = [{"id": "s1", "url": "https://www.commbank.com.au/support/security.html", "title": "CommBank security",
            "authority": "official", "retrieval": "fetched"}]
MATRIX = [(o, a, by) for o in OUTCOMES for a in ATTENTION for by in BY]


# ── 1. Higgins can't create or alter threats ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("outcome,attention,by", MATRIX)
def test_explaining_a_result_changes_nothing_in_it(outcome, attention, by):
    response = result(outcome, attention)
    before = copy.deepcopy(response.model_dump())
    plain, briefing = explain.explain_case(response, answered_by=by, routing={}, sources=SOURCES, gates=["text"])
    assert response.model_dump() == before, "Higgins' explanation changed the validated result"
    assert plain is not None and briefing is not None
    # The briefing every screen projects says exactly what the result recorded.
    assert briefing.status_code == outcome
    assert briefing.status == outcomes.LABELS[outcome]
    assert briefing.attention == attention
    # No finding added or dropped; each keeps its evidence, sources, basis and confidence.
    assert [f.id for f in briefing.findings] == [f.id for f in response.findings]
    for shown, recorded in zip(briefing.findings, response.findings):
        assert shown.evidence_ids == recorded.evidence_ids
        assert shown.source_ids == recorded.source_ids
        assert shown.basis == recorded.basis
        assert shown.confidence == recorded.confidence
    # Nothing of concern is never turned into a decision the person owes, and an action-level result always is.
    assert briefing.user_action_required == (attention in ("urgent", "action_needed"))


@pytest.mark.parametrize("outcome,attention", [(o, a) for o in OUTCOMES for a in ATTENTION])
def test_the_committed_result_differs_only_by_the_explanation_beside_it(monkeypatch, outcome, attention):
    """coordinator._plain_english, the one place the explanation joins a result before it is committed."""
    class _Cases:
        async def find_one(self, *_args, **_kwargs):
            return {"routing": {}, "gates": ["text"]}

    class _Db:
        investigation_cases = _Cases()

    async def sources(_owner, _case_id):
        return SOURCES

    monkeypatch.setattr(coordinator, "db", _Db())
    monkeypatch.setattr(coordinator.repo, "sources", sources)
    response = result(outcome, attention)
    committed, summary = asyncio.run(coordinator._plain_english("owner", {"case_id": "case-1"}, response, "tc_flyby"))
    explained = {"plain_english", "briefing"}
    assert committed.model_dump(exclude=explained) == response.model_dump(exclude=explained)
    assert committed.briefing is not None and committed.briefing.status_code == response.outcome
    assert summary["status"] in ("PASS", "FAIL")


def test_a_renderer_error_leaves_the_result_exactly_as_validated(monkeypatch):
    class _Cases:
        async def find_one(self, *_args, **_kwargs):
            return {}

    class _Db:
        investigation_cases = _Cases()

    async def sources(_owner, _case_id):
        return []

    def broken(*_args, **_kwargs):
        raise RuntimeError("renderer")

    monkeypatch.setattr(coordinator, "db", _Db())
    monkeypatch.setattr(coordinator.repo, "sources", sources)
    monkeypatch.setattr(coordinator.explain, "explain_case", broken)
    response = result("likely_scam", "action_needed")
    committed, summary = asyncio.run(coordinator._plain_english("owner", {"case_id": "case-1"}, response, "magnum_di"))
    assert committed is response
    assert summary["status"] == "FAIL" and summary["mode"] == "literal"


# Collections that hold a threat, its Patrol record or its Triage result.
THREAT_COLLECTIONS = {"patrol_events", "patrol_records", "threat_indicators", "triage_investigations", "triage_results",
                      "shared_events", "threat_notes", "threat_revalidation_log"}
WRITES = {"insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
          "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write"}
# Everything that makes up Higgins: the explanation, the Case Briefing, Ask Higgins and what it reads.
HIGGINS = sorted((BACKEND / "services/higgins/explain").glob("*.py")) + [
    BACKEND / f"services/higgins/{name}.py" for name in
    ("presenter", "chat", "context_tools", "context", "knowledge", "app_knowledge", "pipeline_submit")]


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value)
    return out


@pytest.mark.parametrize("path", HIGGINS, ids=lambda p: p.name)
def test_higgins_never_writes_to_anything_that_holds_a_threat(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WRITES:
            touched = _names(node.func.value) & THREAT_COLLECTIONS
            assert not touched, f"{path.name}:{node.lineno} writes to {sorted(touched)}"


@pytest.mark.parametrize("path", sorted((BACKEND / "services/higgins/explain").glob("*.py")) + [BACKEND / "services/higgins/presenter.py"],
                         ids=lambda p: p.name)
def test_the_explanation_layer_has_no_database_at_all(path):
    tree = ast.parse(path.read_text())
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "core.db" not in modules and "db" not in imported, f"{path.name} reaches the database"


def test_ask_higgins_reaches_a_case_only_through_the_shared_pipeline_and_never_sets_a_result():
    tree = ast.parse((BACKEND / "services/higgins/pipeline_submit.py").read_text())
    # What it writes on the case it opened: where the item came from and the evidence gathered for Higgins Triage.
    stored: dict[str, set[str]] = {}  # name → keys assigned into it (update_fields["source_metadata"] = …)
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name) \
                and isinstance(node.slice, ast.Constant):
            stored.setdefault(node.value.id, set()).add(node.slice.value)
    set_fields: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "$set":
                    if isinstance(v, ast.Dict):
                        set_fields |= {x.value for x in v.keys if isinstance(x, ast.Constant)}
                    elif isinstance(v, ast.Name):
                        set_fields |= stored.get(v.id, set())
    assert set_fields == {"source_metadata", "triage_provider_evidence"}, sorted(set_fields)
    # The case is opened the same way User Checks open one, marked as Ask Higgins' request.
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_case"]
    assert calls and all(any(k.arg == "initiator" and getattr(k.value, "value", None) == "higgins_user_request" for k in c.keywords) for c in calls)
    # Ask Higgins' reply carries no verdict, severity or status of its own.
    from services.higgins.chat import ChatReply
    assert not {"outcome", "attention", "state", "severity", "status", "verdict", "confidence"} & set(ChatReply.model_fields)


# ── 2. Presentation can't silently change the verdict, severity, confidence or status ───────────────────────────────

def _checked(response: HigginsResponse):
    f = facts_mod.build(response, answered_by="tc_flyby", routing={}, sources=SOURCES, gates=["text"])
    draft = render.render(f, frozenset())
    _, briefing = explain.explain_case(response, answered_by="tc_flyby", routing={}, sources=SOURCES, gates=["text"])
    return f, draft, briefing


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_a_briefing_that_changes_the_verdict_fails_its_fidelity_check(outcome):
    f, draft, briefing = _checked(result(outcome, "review"))
    assert fidelity.check_briefing(f, draft, briefing).status == "PASS"
    other = next(o for o in OUTCOMES if o != outcome)
    changed = briefing.model_copy(update={"status_code": other, "status": outcomes.LABELS[other]})
    failed = fidelity.check_briefing(f, draft, changed)
    assert failed.status == "FAIL" and "OUTCOME_CHANGED" in {x.code for x in failed.failures}


def test_a_briefing_that_drops_a_finding_or_flips_its_side_fails_its_fidelity_check():
    f, draft, briefing = _checked(result("likely_scam", "action_needed"))
    dropped = briefing.model_copy(update={"findings": briefing.findings[:1]})
    assert "FINDING_DROPPED" in {x.code for x in fidelity.check_briefing(f, draft, dropped).failures}
    flipped = briefing.model_copy(update={"findings": [briefing.findings[0].model_copy(update={"stance": "contrary"}), *briefing.findings[1:]]})
    assert "STANCE_CHANGED" in {x.code for x in fidelity.check_briefing(f, draft, flipped).failures}


def test_a_briefing_that_hides_the_decision_the_person_owes_fails_its_fidelity_check():
    f, draft, briefing = _checked(result("likely_scam", "urgent"))
    assert briefing.user_action_required
    hidden = briefing.model_copy(update={"user_action_required": False, "action_reason": None})
    assert "ACTION_REASON_DROPPED" in {x.code for x in fidelity.check_briefing(f, draft, hidden).failures}
