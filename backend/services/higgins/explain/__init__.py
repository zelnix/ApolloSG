"""Higgins Plain-English Renderer and Fidelity Check.

A validated result (TC Hawkeye's or Magnum DI's) is explained in everyday words, in Apollo's wording only, and
checked against the result before anything is shown:
  1. facts.py   — the authoritative findings, in structured form (Subject → Check → Result for every finding), from
                  the validated result and the case's records;
  2. render.py  — the plain-English draft (no AI; fixed plain words, labels and explanations only);
  3. fidelity.py — the Fidelity Check: PASS only when nothing was lost, added or changed;
  4. briefing.py — the Higgins Case Briefing every surface projects, with its own Fidelity Check.
On FAIL the failing parts are put back in Apollo's own wording and checked again. If it still fails, the person sees
Apollo's own wording only (mode "literal"). The structured result is never changed: the explanation sits beside it,
and where the two could ever differ the structured result wins.
"""
from __future__ import annotations

import re
from typing import Optional

from services.higgins.contracts import CaseBriefing, FidelityResult, HigginsResponse, PlainEnglish, PlainItem
from services.higgins.explain import briefing as briefing_mod
from services.higgins.explain import facts as facts_mod
from services.higgins.explain import fidelity, render

# The draft, then one repair (failed parts in Apollo's own wording). Still failing → Apollo's wording only.
MAX_ATTEMPTS = 2
_PART = re.compile(r"(result|subject|finding:\d+|means:\d+|matters:\d+|todo:\d+|uncertain:\d+|how:\d+)")


def explain(response: HigginsResponse, *, answered_by: Optional[str], routing: dict, sources: list[dict],
            gates: tuple[str, ...] | list[str] = ()) -> Optional[PlainEnglish]:
    """Higgins' plain English for a validated result, checked. None for a general question (nothing to explain)."""
    return explain_case(response, answered_by=answered_by, routing=routing, sources=sources, gates=gates)[0]


def explain_case(response: HigginsResponse, *, answered_by: Optional[str], routing: dict, sources: list[dict],
                 gates: tuple[str, ...] | list[str] = ()) -> tuple[Optional[PlainEnglish], Optional[CaseBriefing]]:
    """The checked plain English and the Higgins Case Briefing built from the same facts and the same shown draft."""
    if response.outcome is None and not response.findings:
        return None, None
    facts = facts_mod.build(response, answered_by=answered_by, routing=routing, sources=sources, gates=gates)
    literal: frozenset[str] = frozenset()
    attempts: list[FidelityResult] = []
    for attempt in range(MAX_ATTEMPTS):
        draft = render.render(facts, literal)
        result = fidelity.check(facts, draft)
        attempts.append(result)
        if result.status == "PASS":
            return _plain(draft, "plain" if attempt == 0 else "repaired", result, attempts), briefing_mod.build(facts, draft, response, gates)
        refs = {failure.ref for failure in result.failures}
        literal = literal | (frozenset(refs) if all(_PART.fullmatch(r) for r in refs) else frozenset({"*"}))
    draft = render.render(facts, frozenset({"*"}))
    return _plain(draft, "literal", attempts[-1], attempts), briefing_mod.build(facts, draft, response, gates)


def _plain(draft: render.Draft, mode: str, result: FidelityResult, attempts: list[FidelityResult]) -> PlainEnglish:
    return PlainEnglish(
        mode=mode, result=draft.result.text, severity=draft.severity, subject=draft.subject.text if draft.subject else "",
        established=[PlainItem(text=i.text, detail=i.detail, explain=i.explain, finding_id=i.finding_id) for i in draft.established],
        means=[i.text for i in draft.means], matters=[i.text for i in draft.matters], todo=[i.text for i in draft.todo],
        uncertain=[i.text for i in draft.uncertain], how=[i.text for i in draft.how], fidelity=result,
        attempts=len(attempts), attempt_failures=[a.failures for a in attempts],
    )


def summary(plain: Optional[PlainEnglish], *, by: str, revision: int, briefing: Optional[CaseBriefing] = None) -> Optional[dict]:
    """What the admin portal shows for a case's latest result: PASS/FAIL, what was shown and why. No case content."""
    if plain is None:
        return None
    out = {"status": "FAIL" if plain.mode == "literal" else "PASS", "mode": plain.mode, "attempts": plain.attempts,
           "attemptFailures": [[{"code": f.code, "ref": f.ref, "detail": f.detail} for f in failures] for failures in plain.attempt_failures],
           "by": by, "revision": revision}
    if briefing is not None:
        out["briefing"] = {"status": briefing.fidelity.status, "userActionRequired": briefing.user_action_required,
                           "failures": [{"code": f.code, "ref": f.ref, "detail": f.detail} for f in briefing.fidelity.failures]}
    return out


def renderer_error(*, by: str, revision: int) -> dict:
    return {"status": "FAIL", "mode": "literal", "attempts": 0, "attemptFailures": [[{"code": "RENDERER_ERROR", "ref": "", "detail": ""}]],
            "by": by, "revision": revision}
