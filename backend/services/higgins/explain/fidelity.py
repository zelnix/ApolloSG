"""Fidelity Check: before Higgins' plain English is shown, it is compared with the authoritative facts.

PASS only when nothing was lost, added or changed:
  - the outcome is stated by its label, and no other outcome is named;
  - how serious it is matches the attention level, word for word (words.SEVERITY);
  - every finding is there, in order, with the same meaning, confidence and who established it;
  - every sentence of the result is said somewhere, with the same meaning; and every plain sentence says something the
    result says (nothing unsupported);
  - every link, address, number, date and amount is kept, and none is added; quoted words stay word for word;
  - a contradiction in the evidence stays a contradiction;
  - nothing sounds more certain, safer, milder or more alarming than Apollo's own wording, and the right
    investigator gets the credit;
  - every step of what to do is kept; explanations are only Apollo's fixed ones.
Deterministic: no AI. Failure details name only the kind of problem and where, never content from the case.
"""
from __future__ import annotations

import re
from collections import Counter

from services.higgins import outcomes
from services.higgins.contracts import FidelityFailure, FidelityResult
from services.higgins.explain import words as W
from services.higgins.explain.facts import (CONTRAST, STOP, Facts, _stem, classify, entities, entity_text, identity_value, normal,
                                            result_kinds, sentences, words)
from services.higgins.explain.render import QUOTE, Draft, literal_parts

CODES = {
    "OUTCOME_CHANGED": "The plain English doesn't open with Apollo's outcome as recorded.",
    "OUTCOME_CONFLICT": "The plain English names a different outcome from Apollo's.",
    "SEVERITY_CHANGED": "How serious it is doesn't match Apollo's attention level.",
    "FINDING_DROPPED": "A finding is missing from the plain English.",
    "FINDING_ADDED": "The plain English lists a finding Apollo didn't record.",
    "FINDING_ORDER": "The findings are in a different order from Apollo's.",
    "FINDING_ALTERED": "A finding's meaning changed in the plain English.",
    "CONFIDENCE_CHANGED": "How sure ApolloSG is about a finding changed.",
    "BASIS_CHANGED": "Who established a finding, or how, changed.",
    "EXPLANATION_NOT_APOLLO": "An explanation isn't one of Apollo's fixed explanations.",
    "STATEMENT_DROPPED": "Something Apollo's result says is missing from the plain English.",
    "STATEMENT_ALTERED": "Something Apollo's result says changed meaning in the plain English.",
    "UNSUPPORTED_STATEMENT": "The plain English says something Apollo's result doesn't.",
    "ACTION_DROPPED": "A step of what to do is missing.",
    "ACTION_ALTERED": "A step of what to do changed.",
    "ENTITY_DROPPED": "A link, address, number, date or amount from the result is missing.",
    "ENTITY_INVENTED": "A link, address, number, date or amount appears that the result doesn't have.",
    "QUOTE_ALTERED": "Words quoted from what was sent weren't kept word for word.",
    "CONTRADICTION_DROPPED": "A contradiction in the evidence was smoothed over.",
    "CERTAINTY_ADDED": "The plain English sounds more certain than Apollo's result.",
    "SAFETY_CLAIM_ADDED": "The plain English sounds safer than Apollo's result.",
    "SEVERITY_SOFTENED": "The plain English plays the risk down.",
    "SEVERITY_ESCALATED": "The plain English plays the risk up.",
    "ATTRIBUTION_CHANGED": "The plain English credits the wrong investigator.",
    "SUBJECT_DROPPED": "A finding lost what it is about: the address, website, number or company it names.",
    "RESULT_CHANGED": "What a check found about its subject isn't what Apollo recorded.",
    "RESULT_KIND_CHANGED": "Unavailable, failed, no match and not applicable were mixed up.",
    "DECISION_REASON_DROPPED": "The reason for Apollo's status is missing or changed.",
    "UNRESOLVED_DROPPED": "Something Apollo left unresolved is missing or changed.",
    "ACTION_REASON_DROPPED": "The case asks the person to act without the reason Apollo recorded, or drops that reason.",
    "STANCE_CHANGED": "A finding that supports or goes against Apollo's conclusion is on the wrong side.",
    "CAUSAL_DROPPED": "A \"because\" or \"so\" link between two facts was lost.",
    "RENDERER_ERROR": "The renderer stopped with an error, so Apollo's own wording was shown.",
}

NEGATIONS = {"not", "no", "never", "nothing", "none", "nobody", "nowhere", "neither", "nor", "without"}
CAUSAL = re.compile(r"\b(because|so|therefore|as a result|which means|that's why|that is why|hence|thus|since)\b", re.I)


def canon(text: str) -> list[str]:
    """The meaning-bearing words of `text`, with formal and plain forms (and contractions) made the same."""
    out: list[str] = []
    for w in words(W.swap(text)):
        if w in ("can't", "cannot"):
            out += ["can", "not"]
        elif w == "won't":
            out += ["will", "not"]
        elif w.endswith("n't"):
            out += [w[:-3], "not"]
        else:
            w = re.sub(r"'(s|re|ve|ll|d|m)$", "", w).strip("'")
            if w and w not in STOP:
                out.append(_stem(w))
    return [w for w in out if w and w not in STOP]


def faithful(original: str, rendered: str) -> bool:
    """`rendered` makes the same point as `original`: nearly all its meaning-bearing words, little that's new, the
    same yes-or-no, the same numbers and every quote word for word."""
    a, b = canon(original), canon(rendered)
    if not a:
        return not b or normal(original) == normal(rendered)
    sa, sb = set(a), set(b)
    if len(sa & sb) / len(sa) < 0.85 or (sb and len(sb - sa) / len(sb) > 0.25):
        return False
    if sum(w in NEGATIONS for w in a) != sum(w in NEGATIONS for w in b):
        return False
    if Counter(w for w in a if any(c.isdigit() for c in w)) != Counter(w for w in b if any(c.isdigit() for c in w)):
        return False
    return all(q in rendered for q in QUOTE.findall(original))


def _count(text: str, phrase: str) -> int:
    return len(re.findall(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", text.lower().replace("’", "'")))


def _fail(code: str, ref: str = "", detail: str = "") -> FidelityFailure:
    return FidelityFailure(code=code, ref=ref, detail=detail)


def _units(draft: Draft) -> list[tuple[str, str]]:
    """Every plain sentence, with the part it renders."""
    return [(item.ref, s) for item in draft.items() for s in sentences(item.text)]


def check(f: Facts, draft: Draft) -> FidelityResult:
    failures: list[FidelityFailure] = []
    parts = literal_parts(f)
    own_label = f"{outcomes.label(f.outcome)}." if f.outcome else ""
    core = W.swap(f.core)  # Apollo's own wording, with the same plain swaps, so a contraction isn't counted as new

    # ── The outcome and how serious it is ──
    if own_label and not draft.result.text.startswith(own_label):
        failures.append(_fail("OUTCOME_CHANGED", "result"))
    if draft.severity != W.SEVERITY[f.attention]:
        failures.append(_fail("SEVERITY_CHANGED", "severity"))

    # ── Findings: every one, in order, same meaning, same confidence, same investigator ──
    ids = [x["id"] for x in f.findings]
    shown = [item.finding_id for item in draft.established]
    for i, fid in enumerate(ids):
        if fid not in shown:
            failures.append(_fail("FINDING_DROPPED", f"finding:{i}"))
    for item in draft.established:
        if item.finding_id not in ids:
            failures.append(_fail("FINDING_ADDED", item.ref))
    if [x for x in shown if x in ids] != [x for x in ids if x in shown]:
        failures.append(_fail("FINDING_ORDER", "finding"))
    for item in draft.established:
        if item.finding_id not in ids:
            continue
        i = ids.index(item.finding_id)
        finding = f.findings[i]
        if not faithful(finding["statement"], item.text):
            failures.append(_fail("FINDING_ALTERED", f"finding:{i}"))
        if W.CONFIDENCE[finding["confidence"]] not in item.detail:
            failures.append(_fail("CONFIDENCE_CHANGED", f"finding:{i}"))
        if W.BASIS[finding["basis"]].format(by=f.by) not in item.detail:
            failures.append(_fail("BASIS_CHANGED", f"finding:{i}"))
        if item.explain and item.explain not in W.GLOSSARY_TEXTS:
            failures.append(_fail("EXPLANATION_NOT_APOLLO", f"finding:{i}"))
        # Subject → Finding → Result: the finding still names what it is about, and still says what the check found.
        if finding["subject"] and not has_subject(item.text, finding["subjectType"], finding["subject"]):
            failures.append(_fail("SUBJECT_DROPPED", f"finding:{i}", finding["subjectType"]))
        if finding["check"] != "stated" and classify(item.text) != (finding["check"], finding["result"]):
            failures.append(_fail("RESULT_CHANGED", f"finding:{i}", finding["check"]))
        if result_kinds(item.text) != result_kinds(finding["statement"]):
            failures.append(_fail("RESULT_KIND_CHANGED", f"finding:{i}"))
        if item.stance != finding["stance"]:
            failures.append(_fail("STANCE_CHANGED", f"finding:{i}"))

    # ── Why this status, and what remains unresolved: each one whole, in its own place ──
    def kept(ref: str, shown: list) -> bool:
        item = next((x for x in shown if x.ref == ref), None)
        return item is not None and all(any(faithful(s, p) for p in sentences(item.text)) for s in sentences(parts[ref]))
    if f.attention_reason and not kept("matters:0", draft.matters):
        failures.append(_fail("DECISION_REASON_DROPPED", "matters:0"))
    for i in range(len(f.uncertainties)):
        if not kept(f"uncertain:{i}", draft.uncertain):
            failures.append(_fail("UNRESOLVED_DROPPED", f"uncertain:{i}"))

    # ── What to do: every step, one for one ──
    todo = {item.ref: item for item in draft.todo}
    for i in range(len(f.actions)):
        item = todo.get(f"todo:{i}")
        if item is None:
            failures.append(_fail("ACTION_DROPPED", f"todo:{i}"))
        elif not faithful(parts[f"todo:{i}"], item.text):
            failures.append(_fail("ACTION_ALTERED", f"todo:{i}"))

    # ── Every sentence of the result is said; every plain sentence is supported ──
    units = _units(draft)
    plain_units = [(ref, s) for ref, s in units if not (ref == "result" and s == own_label) and ref != "subject"]
    for ref, text in parts.items():
        if ref.startswith(("finding:", "todo:")):
            continue  # checked one for one above
        for s in sentences(text):
            if ref == "result" and s == own_label:
                continue
            if not any(faithful(s, p) for _, p in plain_units):
                near = max((len(set(canon(s)) & set(canon(p))) / max(len(set(canon(s))), 1) for _, p in plain_units), default=0)
                failures.append(_fail("STATEMENT_ALTERED" if near >= 0.5 else "STATEMENT_DROPPED", ref))
    authoritative = [s for ref, text in parts.items() for s in sentences(text)]
    for ref, p in plain_units:
        if ref.startswith(("finding:", "todo:")):
            continue
        if not any(faithful(s, p) for s in authoritative):
            failures.append(_fail("UNSUPPORTED_STATEMENT", ref))

    # ── A contradiction stays a contradiction; a cause stays a cause; "couldn't check" never becomes "not found" ──
    for c in f.contradictions:
        matches = [p for _, p in units if faithful(c, p)]
        if matches and not any(CONTRAST.search(p) for p in matches):
            failures.append(_fail("CONTRADICTION_DROPPED", _where(parts, c)))
    for ref, text in parts.items():
        if ref.startswith("finding:"):
            continue  # checked against the finding itself above
        for s in sentences(text):
            matches = [p for _, p in plain_units if faithful(s, p)]
            if CAUSAL.search(s) and matches and not any(CAUSAL.search(p) for p in matches):
                failures.append(_fail("CAUSAL_DROPPED", ref))
            if matches and all(result_kinds(p) != result_kinds(s) for p in matches):
                failures.append(_fail("RESULT_KIND_CHANGED", ref))
    if draft.subject is not None and (not f.subject or not has_subject(draft.subject.text, f.subject["type"], f.subject["value"])):
        failures.append(_fail("SUBJECT_DROPPED", "subject"))

    # ── Identifiers and quotes: kept word for word, none added ──
    shown_text = "\n".join(item.text for item in draft.items())
    found = entities(shown_text)
    lowered = entity_text(shown_text)
    digits_shown = re.sub(r"\D", "", shown_text)
    for kind, values in f.entities.items():
        for value in values:
            present = value in found.get(kind, set()) or value in lowered or (
                kind in ("phone", "registration") and re.sub(r"\D", "", value) in digits_shown)
            if not present:
                failures.append(_fail("ENTITY_DROPPED", _where(parts, value), kind))
    allowed_text = entity_text(f.corpus)
    for kind, values in found.items():
        for value in values:
            if value not in f.allowed.get(kind, set()) and value not in allowed_text:
                failures.append(_fail("ENTITY_INVENTED", _where_item(draft, value), kind))
    for ref, text in parts.items():
        for quote in QUOTE.findall(text):
            if quote not in shown_text:
                failures.append(_fail("QUOTE_ALTERED", ref))

    # ── Tone: no more certain, safe, mild or alarming than Apollo's own wording; the right investigator ──
    for code, phrases in (("CERTAINTY_ADDED", W.CERTAINTY), ("SAFETY_CLAIM_ADDED", W.SAFETY),
                          ("SEVERITY_SOFTENED", W.SOFTENERS), ("SEVERITY_ESCALATED", W.ESCALATORS)):
        for phrase in phrases:
            if _count(shown_text, phrase) > _count(core, phrase):
                failures.append(_fail(code, _where_item(draft, phrase, count=True), phrase))
    for name in outcomes.LABELS.values():
        if f"{name}." != own_label and _count(shown_text, name.lower()) > _count(core, name.lower()):
            failures.append(_fail("OUTCOME_CONFLICT", _where_item(draft, name.lower(), count=True)))
    other = "Magnum DI" if f.by == "TC Hawkeye" else "TC Hawkeye"
    if _count(shown_text, other.lower()) > _count(core, other.lower()):
        failures.append(_fail("ATTRIBUTION_CHANGED", _where_item(draft, other.lower(), count=True)))

    unique: list[FidelityFailure] = []
    for failure in failures:
        if all((failure.code, failure.ref) != (u.code, u.ref) for u in unique):
            unique.append(failure)
    return FidelityResult(status="FAIL" if unique else "PASS", failures=unique)


def has_subject(text: str, kind: str, value: str) -> bool:
    """The identifier is in `text`, compared the way identifiers are (case, "www.", spacing in numbers)."""
    low = entity_text(text)
    if kind in ("phone", "registration"):
        return re.sub(r"\D", "", value) in re.sub(r"\D", "", text)
    return identity_value(kind, value) in re.sub(r"(https?://)?www\.", r"\1", low)


def check_briefing(f: Facts, draft: Draft, briefing) -> FidelityResult:
    """The Case Briefing against the facts: every material finding with its subject, check, result and side; the
    status and its reason; what remains unresolved; and "needs you" only with the reason Apollo recorded."""
    failures: list[FidelityFailure] = []
    shown = {b.id: b for b in briefing.findings}
    for i, sf in enumerate(f.findings):
        b = shown.get(sf["id"])
        if b is None:
            failures.append(_fail("FINDING_DROPPED", f"finding:{i}"))
            continue
        if sf["subject"] and (b.subject != sf["subject"] or not has_subject(b.finding, sf["subjectType"], sf["subject"])):
            failures.append(_fail("SUBJECT_DROPPED", f"finding:{i}", sf["subjectType"]))
        if (b.check, b.result) != (sf["check"], sf["result"]):
            failures.append(_fail("RESULT_CHANGED", f"finding:{i}", sf["check"]))
        if b.stance != sf["stance"] or (sf["id"] in briefing.supporting) != (sf["stance"] == "supporting") \
                or (sf["id"] in briefing.contrary) != (sf["stance"] == "contrary"):
            failures.append(_fail("STANCE_CHANGED", f"finding:{i}"))
    if briefing.status_code != f.outcome:
        failures.append(_fail("OUTCOME_CHANGED", "briefing"))
    if f.attention_reason and not faithful(W.swap(f.attention_reason), briefing.status_reason):
        failures.append(_fail("DECISION_REASON_DROPPED", "briefing"))
    asks = f.attention in ("action_needed", "urgent") and bool(f.attention_reason)
    if briefing.user_action_required and not (briefing.action_reason or "").strip():
        failures.append(_fail("ACTION_REASON_DROPPED", "briefing"))
    if asks and not briefing.user_action_required:
        failures.append(_fail("ACTION_REASON_DROPPED", "briefing"))
    if len(briefing.unresolved) != len(f.uncertainties) or not all(
            any(faithful(s, p) for p in sentences(shown_u)) for u, shown_u in zip(f.uncertainties, briefing.unresolved) for s in sentences(u)):
        failures.append(_fail("UNRESOLVED_DROPPED", "briefing"))
    # The short summary: each sentence is one finding said in fewer words — same subject, check and result — or the
    # first unresolved reason in Apollo's fixed line. Nothing else.
    material = [sf for sf in f.findings if sf["materiality"] == "material"]
    unresolved_line = W.UNRESOLVED_LINE.format(reason=briefing.unresolved[0]) if briefing.unresolved else None
    for s in sentences(briefing.summary.replace(unresolved_line, "") if unresolved_line else briefing.summary):
        if not any((classify(s) == (sf["check"], sf["result"]) or faithful(sf["statement"], s))
                   and (not sf["subject"] or has_subject(s, sf["subjectType"], sf["subject"])) for sf in f.findings):
            failures.append(_fail("UNSUPPORTED_STATEMENT", "summary"))
    if material and any(sf["subject"] for sf in material) and not any(
            sf["subject"] and has_subject(briefing.summary, sf["subjectType"], sf["subject"]) for sf in material):
        failures.append(_fail("SUBJECT_DROPPED", "summary"))
    unique = [x for i, x in enumerate(failures) if all((x.code, x.ref) != (u.code, u.ref) for u in failures[:i])]
    return FidelityResult(status="FAIL" if unique else "PASS", failures=unique)


def _where(parts: dict[str, str], needle: str) -> str:
    """The first authoritative part that holds `needle`."""
    low = entity_text(needle)
    return next((ref for ref, text in parts.items() if low in entity_text(text) or needle in text), "")


def _where_item(draft: Draft, needle: str, *, count: bool = False) -> str:
    """The first plain part that holds `needle` (for a counted word: more often than Apollo's own wording does)."""
    for item in draft.items():
        if (count and _count(item.text, needle)) or (not count and needle in entity_text(item.text)):
            return item.ref
    return ""


def describe(code: str) -> str:
    return CODES.get(code, code)
