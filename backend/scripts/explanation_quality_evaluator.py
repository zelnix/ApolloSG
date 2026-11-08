#!/usr/bin/env python3
"""Higgins explanation-quality evaluator - OFFLINE, DEV-ONLY (ApolloSG PRD v2.3, Higgins Luddish).

Not part of the production investigation pipeline, not imported by any API route, not part of the
pytest regression gate, never writes to a case, never touches a verdict or a Finding. Run manually by
a developer to get a qualitative, before/after read on explanation quality for the agreed edge-case
scenarios, using an LLM purely as a reviewer of already-locked, already-fidelity-checked text - it
never generates anything a user sees, and it can't override tests/test_higgins_explanation_narrative.py
or the deterministic Fidelity Check, which remain the only pass/fail gates.

"Before" vs "after" here means: before/after the explanation-quality pass added in this change set
(connecting the material findings into one line of reasoning, or explaining why the single most
material finding matters - see services/higgins/explain/facts.py connecting_knowledge and
services/higgins/explain/words.py SIGNIFICANCE/CONNECTIONS). The "before" text is reconstructed by
removing that one added sentence from the real, current render - everything else (every finding's own
wording, the verdict, the uncertainties, the actions) is identical in both, because nothing else in
this change set touches rendered text.

Usage:
    cd /app/backend && python scripts/explanation_quality_evaluator.py
Requires EMERGENT_LLM_KEY in backend/.env (already present). Writes
content/EXPLANATION_QUALITY_EVALUATION.md.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from services.higgins import explain  # noqa: E402
from services.higgins.explain import words as W  # noqa: E402
from tests.test_higgins_explanation_narrative import (  # noqa: E402
    ROUTING, _scenario_a, _scenario_b, _scenario_c, _scenario_d,
)

MODEL_PROVIDER, MODEL_NAME = "anthropic", "claude-sonnet-5-5"
REPORT_PATH = Path(__file__).resolve().parents[1] / "content" / "EXPLANATION_QUALITY_EVALUATION.md"

SCENARIOS = {
    "Scenario A - SMS impersonation and shortened URLs": _scenario_a,
    "Scenario B - Suspicious password-protected attachment": _scenario_b,
    "Scenario C - Business Email Compromise": _scenario_c,
    "Scenario D - Incomplete delivery notification": _scenario_d,
}

_ADDED_SENTENCES = set(W.SIGNIFICANCE.values()) | {s for _, s in W.CONNECTIONS}

RUBRIC = """You are reviewing ONE automatically-generated plain-English explanation of a fraud/scam
investigation, written for a non-technical person. You are NOT re-investigating the case - treat every
fact below as already established and locked; judge only the WRITING and REASONING of the explanation
text, never whether the verdict itself is correct.

Score each of these six criteria from 1 (poor) to 5 (excellent), with one short comment each:
1. natural_language - does it read like a knowledgeable person talking, not a template or a checklist?
2. connects_findings - does it show HOW the findings relate to each other and to the conclusion, not just list them?
3. explains_significance - does it say WHY the evidence matters, in terms a non-expert understands?
4. evidence_balance - does it fairly represent favourable evidence, concerns, contradictions and uncertainty, without exaggerating or downplaying any of them?
5. avoids_mechanical_repetition - does it avoid repeating the verdict or the same phrasing over and over, and avoid unexplained jargon?
6. accurate_representation - does it match the locked findings exactly, with nothing invented and nothing dropped?

Then give: strengths (a short list), weaknesses (a short list), suggested_wording (a short list of concrete
rewrite suggestions that would improve the explanation WITHOUT inventing any new fact).

Respond with ONLY a JSON object, no markdown fences, no prose outside the JSON, shaped exactly like:
{"scores": {"natural_language": 0, "connects_findings": 0, "explains_significance": 0,
"evidence_balance": 0, "avoids_mechanical_repetition": 0, "accurate_representation": 0},
"comments": {"natural_language": "", "connects_findings": "", "explains_significance": "",
"evidence_balance": "", "avoids_mechanical_repetition": "", "accurate_representation": ""},
"strengths": [], "weaknesses": [], "suggested_wording": []}
"""


def _render_text(plain) -> str:
    lines = [plain.result, "", "What was found:"]
    lines += [f"- {f.text}" for f in plain.established]
    if plain.means:
        lines += ["", "What it means:", *plain.means]
    if plain.uncertain:
        lines += ["", "Still unresolved:", *[f"- {u}" for u in plain.uncertain]]
    if plain.todo:
        lines += ["", "What to do:", *[f"- {t}" for t in plain.todo]]
    return "\n".join(lines)


def _before_after(build_response):
    response = build_response()
    plain = explain.explain(response, answered_by="tc_flyby_official", routing=ROUTING, sources=[])
    assert plain.fidelity.status == "PASS", f"fixture itself failed Fidelity: {plain.fidelity.failures}"
    after = _render_text(plain)
    before_means = [m for m in plain.means if m not in _ADDED_SENTENCES]
    before = _render_text(plain.model_copy(update={"means": before_means}))
    return before, after


async def _judge(chat_factory, label, text):
    from emergentintegrations.llm.chat import UserMessage
    chat = chat_factory()
    raw = await chat.send_message(UserMessage(text=f"{RUBRIC}\n\n--- Explanation to review ({label}) ---\n{text}\n--- end ---"))
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "could not parse model response as JSON", "raw": raw}


async def main():
    from emergentintegrations.llm.chat import LlmChat

    key = os.environ["EMERGENT_LLM_KEY"]

    def chat_factory():
        return LlmChat(api_key=key, session_id=f"explanation-quality-eval-{uuid.uuid4().hex[:8]}",
                       system_message="You are a precise, concise writing reviewer for fraud-investigation explanations."
                       ).with_model(MODEL_PROVIDER, MODEL_NAME)

    report = ["# Higgins Explanation Quality Evaluation (offline, dev-only)", "",
              "Model: `{}/{}` via the Emergent LLM key. Not part of the production pipeline; does not gate "
              "pytest; informs manual review only.".format(MODEL_PROVIDER, MODEL_NAME), ""]
    for label, build in SCENARIOS.items():
        before_text, after_text = _before_after(build)
        before_eval, after_eval = await asyncio.gather(
            _judge(chat_factory, label + " - BEFORE", before_text),
            _judge(chat_factory, label + " - AFTER", after_text))
        report += [
            "## " + label, "",
            "### Before", "```", before_text, "```",
            "**Scores (before):** " + json.dumps(before_eval.get("scores", before_eval)), "",
            "### After", "```", after_text, "```",
            "**Scores (after):** " + json.dumps(after_eval.get("scores", after_eval)), "",
            "**Strengths (after):** " + json.dumps(after_eval.get("strengths", [])),
            "**Weaknesses (after):** " + json.dumps(after_eval.get("weaknesses", [])),
            "**Suggested wording (after):** " + json.dumps(after_eval.get("suggested_wording", [])), "",
        ]
        print(label + ": before=" + json.dumps(before_eval.get("scores")) + " after=" + json.dumps(after_eval.get("scores")))

    REPORT_PATH.write_text("\n".join(report))
    print("\nWrote " + str(REPORT_PATH))


if __name__ == "__main__":
    asyncio.run(main())
