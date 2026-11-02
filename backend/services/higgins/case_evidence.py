"""The case's Evidence record: each material fact the investigation established — once — with the stage that found
it first and the later stages that established it too (Higgins Triage → TC FlyBy → Magnum DI).

Built at commit from the case's own records only: TC FlyBy's check record (Higgins Triage's message rules are one of
its checks) and the validated result's findings. Nothing is looked up, re-scored or reworded:
- A lookup that found nothing, or didn't answer, is no evidence either way: it stays in "How ApolloSG checked".
- ApolloSG's knowledge base is general knowledge, never evidence about this case.
- A finding that only states the conclusion ("This is a scam") is the result, not evidence for it.
- Two statements are one fact when they report the same thing (explain.facts: the same identity, the same meaning, or
  the same quoted words). The first stage keeps the fact, in its own words. A later stage that reached it in its own
  words confirms it. A later stage repeating the very same words is only passing the fact on, so it confirms nothing.
stance is relative to the outcome: supporting, contrary ("points the other way") or neutral (the outcome points
neither way, or the fact doesn't bear on it). The result's own briefing decides a finding's side wherever it takes one,
so the Evidence tab and the Findings Brief can never disagree.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from services.higgins import outcomes
from services.higgins.contracts import EvidenceFact, HigginsResponse
from services.higgins.explain import facts as F

_POLARITY = {"concern": "concern", "anomaly": "concern", "weak": "concern", "clear": "clear"}
_RANK = {"low": 0, "medium": 1, "high": 2}
_QUOTE = re.compile(r"[“\"]([^”\"]{4,240})[”\"]")
_CONCLUSION = re.compile(
    r"^(?:overall,?\s+)?(?:this|that|it|the)(?:\s+(?:message|email|text|sms|link|website|site|page|call|caller|sender|number|offer))?\s+"
    r"(?:is|looks like|appears to be|seems to be)\s+(?:very |most |almost certainly |probably |likely )?(?:an?\s+)?"
    r"(?:likely |probable |possible |clear |typical )?(?:scam|phishing|fraud|fraudulent|legitimate|genuine|safe|malicious|threat)\b",
    re.I)


def _stance(polarity: str, outcome: Optional[str]) -> str:
    direction = outcomes.DIRECTION.get(outcome or "")
    if polarity not in ("concern", "clear") or not direction:
        return "neutral"
    return "supporting" if polarity == direction else "contrary"


def _quotes(text: str) -> set[str]:
    return {F.normal(q) for q in _QUOTE.findall(text) if len(F.normal(q)) >= 4}


def _same(a: str, b: str) -> bool:
    if F.same_meaning(a, b) or F.same_meaning(b, a):
        return True
    (ids_a, check_a, result_a), (ids_b, check_b, result_b) = F.identity(a), F.identity(b)
    # "x isn't Brand's domain" and "x isn't one of Brand's published domains" report the one check.
    family = lambda check: "official_domain" if check == "impersonation" else check  # noqa: E731
    if ids_a and ids_a == ids_b and check_a != "stated" and family(check_a) == family(check_b) and result_a == result_b:
        return True
    qa, qb = _quotes(a), _quotes(b)
    return bool(qa and qb and (qa <= qb or qb <= qa))


def _time(value) -> Optional[datetime]:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _from_checks(record: dict, outcome: Optional[str]) -> tuple[list[dict], set[str]]:
    """What Higgins Triage's rules and TC FlyBy's checks established, in the order they ran — and the names of the
    message rules that were met. A rule's name ("Multiple moderate scam indicators form a coherent scam pattern") is
    its conclusion, not evidence: only a rule that quotes what it saw in the material is a fact."""
    out, rule_names = [], set()
    checks_item = (record.get("items") or {}).get("checks")
    at = _time(record.get("ranAt"))
    for check in record.get("checks") or []:
        triage = check.get("kind") == "triage_rules"
        for n, f in enumerate(check.get("facts") or []):
            signal = f.get("signal")
            if f.get("class", "live_evidence") != "live_evidence" or signal in ("missing", "context") or not (f.get("text") or "").strip():
                continue
            if triage and not _quotes(f["text"]):
                rule_names.add(F.normal(f["text"]))
                continue
            out.append({"id": f"{check.get('id')}.{n + 1}", "text": f["text"].strip(), "stage": "higgins_triage" if triage else "tc_flyby",
                        "stance": _stance(_POLARITY.get(signal, "neutral"), outcome), "weak": signal == "weak",
                        "confidence": "high" if f.get("decisive") else "medium", "basis": "observation",
                        # A message rule read the material itself; TC FlyBy's facts are in its check record.
                        "evidence_ids": list(record.get("settled") or []) if triage else [checks_item] if checks_item else [],
                        "source_ids": list(f.get("sourceIds") or []),
                        "finding_ids": [], "rule_id": f.get("ruleId"), "at": at})
    return out, rule_names


def _from_findings(response: HigginsResponse, stage: str, at: datetime, rule_names: set[str]) -> list[dict]:
    """The validated result's findings. A finding's side is the briefing's wherever it takes one; a finding the
    briefing leaves without a side is one of the reasons the result gives for its outcome."""
    briefing = response.briefing if response.briefing and response.briefing.fidelity.status == "PASS" else None
    sides = {b.id: b.stance for b in briefing.findings} if briefing else {}
    reason = "supporting" if outcomes.DIRECTION.get(response.outcome or "") else "neutral"
    out = []
    for f in response.findings:
        text = F.strip_markdown(f.text)
        if not text or F.normal(text) in rule_names or _CONCLUSION.search(text) or F.classify(text)[1] in ("UNAVAILABLE", "NOT_APPLICABLE"):
            continue
        side = sides.get(f.id) or F.structure_finding({"text": text}, {}, response.outcome)["stance"]
        out.append({"id": f.id, "text": text, "stage": stage, "stance": side if side in ("supporting", "contrary") else None, "reason": reason,
                    "weak": False, "confidence": f.confidence, "basis": f.basis, "evidence_ids": list(f.evidence_ids),
                    "source_ids": list(f.source_ids), "finding_ids": [f.id], "rule_id": None, "at": at})
    return out


def _merge(into: dict, other: dict) -> None:
    if other["stage"] != into["stage"] and other["stage"] not in into["corroborated_by"] and F.normal(other["text"]) != F.normal(into["text"]):
        into["corroborated_by"].append(other["stage"])
    if _RANK.get(other["confidence"], -1) > _RANK.get(into["confidence"], -1):
        into["confidence"] = other["confidence"]
    if other["stance"]:
        into["stance"] = other["stance"]
    for key in ("evidence_ids", "source_ids", "finding_ids"):
        into[key] = list(dict.fromkeys([*into[key], *other[key]]))


def build(response: HigginsResponse, record: dict, *, answered_by: Optional[str], simulated: bool,
          at: Optional[datetime] = None) -> list[EvidenceFact]:
    """The case's material facts, each once, in the order they were first established."""
    at = at or datetime.now(timezone.utc)
    stage = "tc_flyby" if outcomes.settled_by_flyby(answered_by) else "magnum_di"
    facts: list[dict] = []
    checked, rule_names = _from_checks(record, response.outcome)
    for candidate in [*checked, *_from_findings(response, stage, at, rule_names)]:
        match = next((f for f in facts if F.normal(f["text"]) == F.normal(candidate["text"])), None) \
            or next((f for f in facts if _same(f["text"], candidate["text"])), None)
        if match:
            _merge(match, candidate)
        else:
            facts.append({**candidate, "stance": candidate["stance"] or candidate.get("reason") or "neutral", "corroborated_by": []})
    return [EvidenceFact(id=f["id"], text=f["text"], stance=f["stance"], discovered_by=f["stage"], corroborated_by=f["corroborated_by"],
                         weak=f["weak"], basis=f["basis"], confidence=f["confidence"], evidence_ids=[e for e in f["evidence_ids"] if e],
                         source_ids=f["source_ids"], finding_ids=f["finding_ids"], rule_id=f["rule_id"], established_at=f["at"] or at,
                         simulated=simulated)
            for f in facts]
