"""What Higgins shows when TC FlyBy settles a check, and the slice Magnum DI receives when it can't.

Higgins explains what was found → what it means → what to do. Every finding is live evidence about this
case, citing the TC FlyBy evidence item and the source that established it. Apollo KB knowledge is never a
finding: it appears only as supporting context in the explanation. Anything TC FlyBy could not establish stays
an uncertainty — missing evidence is never turned into a fact.
"""
from __future__ import annotations

import json
import re

from services.higgins import outcomes
from services.higgins.tc_flyby.decide import WARNING, Decision, corroborated_impersonation, signals
from services.higgins.tc_flyby.triage import Check, Plan

ROUTE_LABEL = {"tc_flyby_official": "official source checks", "tc_flyby_kb": "ApolloSG's knowledge base", "tc_flyby_search": "a targeted web search"}


def _finding(f: dict, evidence_ids: list[str], confidence: str) -> dict:
    return {"text": f["text"], "basis": "observation", "confidence": confidence, "evidenceIds": evidence_ids,
            "sourceIds": f.get("sourceIds") or [], "supersedesFindingIds": []}


def _action(label: str, instruction: str) -> dict:
    return {"kind": "instruction", "label": label, "instruction": instruction, "capabilityId": None, "sourceIds": [],
            "desiredField": None, "desiredValue": None}


def _live(checks: list[Check]) -> list[tuple[Check, dict]]:
    return [(c, f) for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] != "missing"]


def _signs(checks: list[Check]) -> list[tuple[Check, dict]]:
    """Warning signs first, then the weak signals (recorded, never a concern on their own)."""
    live = _live(checks)
    return [(c, f) for c, f in live if f["signal"] in WARNING] + [(c, f) for c, f in live if f["signal"] == "weak"]


def _knowledge(checks: list[Check]) -> list[dict]:
    return [f for c in checks for f in c.facts if f.get("class") == "apollo_knowledge"]


def _not_found(checks: list[Check]) -> list[str]:
    """How Apollo checked, for the DI tab only: lookups that found nothing or didn't answer. They describe TC FlyBy's
    method, so they are never listed under what isn't certain."""
    out = [f["text"] for c in checks for f in c.facts if f["signal"] == "missing"]
    out += [f"{c.subject}: TC FlyBy's lookup was unavailable, so this wasn't established either way." for c in checks if c.status == "unavailable"]
    return [t if t.endswith((".", "!", "?")) else f"{t}." for t in out]


def _topic(text: str) -> str:
    """"Impersonation: whether it's from Linkt." reads as "impersonation (whether it's from Linkt)"."""
    t = f"{text[0].lower()}{text[1:]}".strip().rstrip(".")
    m = re.match(r"^([^:()]{1,40}): (.+)$", t)
    return f"{m.group(1)} ({m.group(2)})" if m else t


def _method(lead: str, checks: list[Check], *, not_taken: bool) -> str:
    """"How Apollo checked": what TC FlyBy did and, said once after the reason it gives, the open issues it didn't take
    further; then the lookups that found nothing or didn't answer."""
    topics = [_topic(c.open_issue) for c in checks if not_taken and c.open_issue and c.status in ("open", "needs_reasoning", "not_needed")]
    return " ".join([lead, *([f"So these weren't taken further: {'; '.join(topics)}."] if topics else []), *_not_found(checks)])


def _who(plan_: Plan) -> str:
    return f"Apollo can't confirm who actually {'called' if plan_.channel == 'call' else 'sent this'}."


_PAGE_UNOPENED = "ApolloSG didn't open the page, so what it shows or asks for wasn't checked."


def _knowledge_block(checks: list[Check]) -> str:
    notes = _knowledge(checks)
    if not notes:
        return ""
    lines = "\n".join(f"- {f['text']}" + (f" — {f['source']['url']}" if (f.get("source") or {}).get("url") else "") for f in notes[:4])
    return f"\n\n**What ApolloSG's knowledge base adds** (general knowledge, not evidence about what you sent)\n{lines}"


def _evidence_for(subject: str, material: dict[str, str], flyby_item: str) -> list[str]:
    """The TC FlyBy record, plus the submitted item(s) the checked value actually appears in."""
    needle = subject.lower()
    return [flyby_item, *[eid for eid, text in material.items() if needle and needle in text.lower()][:2]]


def _evidence(c: Check, material: dict[str, str], flyby_item: str) -> list[str]:
    return _evidence_for(c.subject, material, flyby_item)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}" if items else ""


def _routes(checks: list[Check]) -> str:
    used = {c.route for c in checks if c.route}
    searched = [c for c in checks if c.route == "web_search"]
    reused = [c for c in searched if any((f.get("source") or {}).get("reused") for f in c.facts)]
    search = ("a targeted web search" if not reused else "ApolloSG's recent targeted web search, reused while still current"
              if len(reused) == len(searched) else "a targeted web search, partly reused from ApolloSG's recent lookups")
    names = [label for route, label in (("triage_rules", "Higgins Triage's message rules"), ("official_source", "official source checks"),
                                        ("apollo_kb", "ApolloSG's knowledge base"), ("web_search", search)) if route in used]
    return _join(names) or "official source checks"


def _subject(plan_: Plan) -> str:
    return (", ".join(plan_.entities.hosts[:3]) or "the link") if plan_.link_only else "what you sent"


def _checked(plan_: Plan, how: str) -> str:
    """One sentence, used word for word by "How Apollo checked" and the scope, so the report says it once."""
    examined = ("the call details" if plan_.channel == "call" else
                "the submitted link" + ("s" if len(plan_.entities.hosts) > 1 else "") if plan_.link_only else "the submitted material")
    return f"TC FlyBy checked {examined} using {how}."


def _scope(plan_: Plan, how: str) -> str:
    if plan_.channel == "call":
        return f"{_checked(plan_, how)} No one was called back, nothing was opened and no account was accessed."
    return f"{_checked(plan_, how)} Nothing was opened or fetched from the destination, no one was contacted and no account was accessed."


def concern(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, route: str) -> dict:
    decisive = [(c, f) for c, f in _live(checks) if f["decisive"] and f["signal"] == "concern"]
    lead_check, lead = decisive[0]
    brand = plan_.entities.brands[0][0] if plan_.entities.brands else None
    findings = [_finding(f, _evidence(c, material, flyby_item), "high") for c, f in decisive]
    findings += [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _signs(checks) if not f["decisive"]]
    kinds = {c.kind for c, _ in decisive}
    actions: list[dict] = []
    if "link" in kinds:
        actions.append(_action("Don't open the link", f"Don't open {lead_check.subject if lead_check.kind == 'link' else 'the link'} and don't enter anything on it."))
    if "phone" in kinds:
        actions.append(_action("Don't call or reply", "Don't call the number back or reply to it."))
    if "email" in kinds:
        actions.append(_action("Don't reply", "Don't reply to the email or open its attachments."))
    if "company" in kinds:
        actions.append(_action("Don't send money", "Don't invest, pay or send personal details to this company."))
    actions.append(_action(f"Contact {brand} yourself" if brand else "Check independently",
                           f"If you're unsure, contact {brand} using the number on your card, statement or their official app — not anything in this material."
                           if brand else "If you're unsure, contact the organisation using contact details you already have — not anything in this material."))
    actions.append(_action("Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid or shared details, contact your bank now."))
    means = ("An official safety source has already identified this as dangerous, so there's nothing left to weigh up: "
             "acting on it would put your money, accounts or device at risk.")
    found = "\n".join(f"- {f['text']}" for _, f in decisive)
    settled = "the official result already settles what to do"
    explanation = (f"**What was found**\n{found}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How Apollo checked**\n"
                   + _method(f"{_checked(plan_, ROUTE_LABEL[route])} Magnum DI's deeper analysis wasn't needed, because {settled}.", checks, not_taken=True))
    return {
        "overview": f"{lead['text']} Don't act on it" + (f" — if you need to, contact {brand} yourself." if brand else "."),
        "explanationMarkdown": explanation, "assessment": "concern_found", "outcome": "confirmed_threat", "attention": "action_needed",
        "attentionReason": "An official source has already identified it as dangerous, so acting on it puts your money or accounts at risk.",
        "findings": findings[:8], "uncertainties": ["Anything outside the submitted material — earlier messages or the sender's history — wasn't examined."],
        "scope": _scope(plan_, ROUTE_LABEL[route]), "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [], "actions": actions, "recommendedActionIndex": 0, "question": None, "completion": "complete",
    }


# What each kind of check looked at in the material (singular, plural), for "Apollo checked … in it".
_LOOKED_AT = {"link": ("the link", "the links"), "impersonation": ("the organisation it names", "the organisations it names"),
              "phone": ("the phone number", "the phone numbers"), "email": ("the email address", "the email addresses"),
              "company": ("the business it names", "the businesses it names"), "abn": ("the ABN", "the ABNs"), "acn": ("the ACN", "the ACNs"),
              "licence": ("the licence number", "the licence numbers"), "person": ("the person it names", "the people it names"),
              "claim": ("the claim it makes", "the claims it makes"), "phrase": ("whether its wording appears elsewhere online",) * 2}


def _what_was_checked(checks: list[Check]) -> str:
    """Only the checks that actually ran, named by what they looked at — never a fixed list."""
    ran = [c for c in checks if c.status in ("resolved", "not_found")]
    counts = {kind: sum(c.kind == kind for c in ran) for kind in _LOOKED_AT}
    looked = [_LOOKED_AT[kind][counts[kind] > 1] for kind in _LOOKED_AT if counts[kind]]
    alerts = any(c.kind == "scam_alerts" for c in ran)
    if looked:
        return f"Apollo checked {_join(looked)} in it" + (", and compared it with the official scam alerts ApolloSG holds." if alerts else ".")
    return ("Apollo found no links, numbers, addresses or names in it to look up"
            + (", so it compared it with the official scam alerts ApolloSG holds." if alerts else "."))


def clear(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, route: str) -> dict:
    """No scam indicators in what TC FlyBy checked — never described as safe."""
    facts = _live(checks)
    findings = [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in facts]
    official_check, official = next(((c, f) for c, f in facts if f["decisive"] and f["signal"] == "clear"), (None, None))
    if plan_.link_only:
        # A verified official domain settles who the address belongs to — that check only, never the whole case.
        others = any(c is not official_check and c.status in ("resolved", "not_found") for c in checks)
        overview = (f"{official['text']} That settles who the address belongs to"
                    + (", and none of Apollo's other checks found a warning sign." if others else ".")
                    if official else
                    f"Nothing Apollo checked raises a concern about {_subject(plan_)}. That isn't proof the site is safe — only that these checks found nothing.")
        means = ("These checks look at who runs the address and whether any safety list or warning names it. They don't show what the page asks "
                 "you to do, so still never enter passwords or codes on a page you reached from a message.")
        uncertainties = [_PAGE_UNOPENED]
    else:
        overview = ("Apollo's checks found no scam indicators in what you sent. That isn't proof it's genuine — only that these checks found "
                    "nothing, and it doesn't ask you to send money, codes or details anywhere that hasn't been verified.")
        means = (f"{_what_was_checked(checks)} Checks like these can't confirm who sent it, so if anything about it feels off, contact the person "
                 "or organisation using details you already have.")
        uncertainties = [_who(plan_)]
    found = "\n".join(f"- {f['text']}" for _, f in facts) or "- No warning signs in anything Apollo checked."
    explanation = (f"**What was found**\n{found}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How Apollo checked**\n"
                   + _method(f"{_checked(plan_, ROUTE_LABEL[route])} Nothing in it needed Magnum DI's deeper analysis.", checks, not_taken=False))
    return {
        "overview": overview, "explanationMarkdown": explanation, "assessment": "no_concern_found_within_scope", "outcome": "no_scam_indicators",
        "attention": "none", "attentionReason": None, "findings": findings[:8],
        "uncertainties": uncertainties,
        "scope": _scope(plan_, ROUTE_LABEL[route]), "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [], "actions": [], "recommendedActionIndex": None, "question": None, "completion": "complete",
    }


_CHECK_FIRST = "If you need the organisation, go to it through its official app or a website address you type yourself."
_NOT_NEEDED = "Magnum DI's deeper analysis wasn't needed, because it couldn't change the outcome or what to do."


def _result(plan_: Plan, checks: list[Check], *, overview: str, found: list[dict], means: str, how: str, outcome: str, attention: str,
            reason: str | None, actions: list[dict], uncertainties: list[str], extra_sources: list[str] = ()) -> dict:
    lines = "\n".join(f"- {f['text']}" for f in found) or "- Nothing beyond what's listed under what isn't certain."
    return {
        "overview": overview[:900],
        "explanationMarkdown": f"**What was found**\n{lines}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How Apollo checked**\n{how}",
        "assessment": outcomes.ASSESSMENT[outcome], "outcome": outcome, "attention": attention, "attentionReason": reason,
        "findings": found[:8], "uncertainties": uncertainties[:4], "scope": _scope(plan_, _routes(checks)),
        "sourceIds": sorted({*extra_sources, *(s for f in found for s in f["sourceIds"])}), "remainingEvidenceIds": [],
        "actions": actions, "recommendedActionIndex": 0 if actions else None, "question": None, "completion": "complete",
    }


def pattern_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, outcome: str) -> dict:
    """The material matches an established scam pattern in Apollo's KB. The material's own words are the
    findings; the pattern is general knowledge that supports the assessment — never proof about the sender."""
    p = plan_.pattern
    items = list(material)[:2]
    quoted = [*p["found"], *([p["ask"]] if p["ask"] else [])]
    found = [{"text": f"It {label}: “{quote}”.", "basis": "observation", "confidence": "high", "evidenceIds": items, "sourceIds": [],
              "supersedesFindingIds": []} for label, quote in quoted]
    found += [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _signs(checks)]
    kb_sources = sorted({s for c in checks if c.kind == "scam_pattern" for f in c.facts for s in f.get("sourceIds", [])})
    advice = p["advice"]
    call = plan_.channel == "call"
    if outcome == "likely_scam":
        overview = f"This matches the {p['name']} that {p['publisher']} warns about. {advice[0][1]} {advice[1][1]}"
        means = (f"Together, these are the defining features of the {p['name']}: {p['summary']} A match like this supports Apollo's "
                 f"assessment, but it isn't proof that this particular {'caller' if call else 'sender'} is a scammer — which is why the safe "
                 "step is to check through a channel you already trust.")
        attention, reason = "action_needed", p["consequence"]
    else:
        overview = (f"This starts the way the {p['name']} does, as {p['publisher']} describes it, though it hasn't asked for anything yet. "
                    f"Before you reply: {advice[1][1][0].lower()}{advice[1][1][1:]}")
        means = (f"Scams like this often begin exactly this way: {p['summary']} Nothing has been asked for yet, so it could still be genuine — "
                 "but checking first costs nothing.")
        attention, reason = "review", "Replying or acting before you've checked is what messages like this rely on."
    return _result(plan_, checks, overview=overview, found=found, means=means, outcome=outcome, attention=attention, reason=reason,
                   # The scope's own first sentence, word for word, so "How Apollo checked" says it once.
                   how=_method(f"{_checked(plan_, _routes(checks))} It compared {'them' if call else 'it'} with the established scam patterns in "
                               f"ApolloSG's knowledge base. {_NOT_NEEDED}", checks, not_taken=True),
                   actions=[_action(label, instruction) for label, instruction in advice],
                   uncertainties=[(f"Apollo can't confirm who actually {'called' if call else 'sent this'} — a pattern match supports the assessment "
                                   f"but isn't proof about the {'caller' if call else 'sender'}.")],
                   extra_sources=kb_sources)


def impersonation_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, facts: list[dict]) -> dict:
    """The material borrows an organisation's name, its link goes elsewhere, and an independent fact about
    that link backs it up: Concerning, whatever the wording says."""
    brand = plan_.entities.brands[0][0]
    place = next(f["place"] for f in facts if f.get("place"))
    support = [f for f in facts if not f.get("place")]
    found = [_finding(f, _evidence_for(f.get("place") or place, material, flyby_item), "high" if f.get("place") else "medium") for f in facts]
    return _result(
        plan_, checks, found=found, outcome="concerning", attention="action_needed",
        overview=(f"This uses {brand}'s name, but its link goes to {place}, which isn't {brand}'s domain. {support[0]['text']} "
                  f"Don't use the link — go to {brand} directly through their official app or website."),
        means=(f"{place} isn't one of {brand}'s published domains, and a separate check on that address backs up the concern. "
               "That's enough to treat it as concerning without weighing up the wording."),
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=True),
        reason=f"Anything typed into that link goes to whoever runs {place}, which isn't one of {brand}'s published domains.",
        actions=[_action("Don't use the link", f"Don't open {place} and don't enter anything on it."),
                 _action(f"Contact {brand} yourself", f"Contact {brand} using their official app, a website address you type yourself, or the number on your card or statement."),
                 _action("Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already entered details, contact the organisation now.")],
        uncertainties=[_PAGE_UNOPENED])


_COUNT = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _signs_established(warnings: int, rest: int) -> str:
    """Only the established warning signs are called warning signs. Weak signals (and a name that still needs
    corroborating) are listed after them, and are never called warning signs."""
    if not rest:
        return f"Apollo's checks established the warning sign{'s' if warnings > 1 else ''} above."
    first = "the first finding above as a warning sign" if warnings == 1 else f"the first {_COUNT[warnings] if warnings < len(_COUNT) else warnings} findings above as warning signs"
    other = ("The other finding is recorded too, but doesn't count as a warning sign on its own." if rest == 1 else
             "The other findings are recorded too, but don't count as warning signs on their own.")
    return f"Apollo's checks established {first}. {other}"


def signals_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str) -> dict:
    """Warning signs the evidence established, with nothing that proves a scam: Concerning. Deeper analysis
    couldn't change what to do — be careful and check independently."""
    warning = signals(plan_)
    facts = warning + [(c, f) for c, f in _signs(checks) if (c, f) not in warning]
    subject = _subject(plan_)
    link = plan_.link_only or any(c.kind == "link" for c, _ in facts)
    actions = ([_action("Don't enter details", "Don't enter passwords, codes or card details on this page."), _action("Go there directly", _CHECK_FIRST)]
               if link else
               [_action("Don't act on it yet", "Don't send money, codes or personal details, and don't call or reply using anything in it."),
                _action("Check independently", "If it claims to be from someone you know or deal with, contact them using details you already have — "
                                               "not anything in it.")])
    return _result(
        plan_, checks, outcome="concerning", attention="review", actions=actions,
        found=[_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in facts],
        overview=(f"{subject[0].upper()}{subject[1:]} raises a concern: {facts[0][1]['text']} Nothing here proves it's a scam, but don't act on "
                  "it until you've checked it through a channel you trust."),
        means=f"{_signs_established(len(warning), len(facts) - len(warning))} That's reason to be careful, but not enough to call it a scam.",
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=True),
        reason="Acting on something with warning signs before checking it is how people lose money or access to their accounts.",
        uncertainties=[_PAGE_UNOPENED if link else _who(plan_)])


def _unchecked(plan_: Plan) -> bool:
    """Something that bears on the outcome couldn't be checked: part of the material couldn't be read, a lookup was
    unavailable, or a link has no listing or registration result. A young registration was checked (it's a weak
    signal), so it isn't a gap. Wording only: it decides nothing."""
    if plan_.gaps or any(c.status == "unavailable" for c in plan_.checks):
        return True
    for c in plan_.checks:
        if c.kind != "link" or any(f["decisive"] and f["signal"] == "clear" for f in c.facts):
            continue
        topics = {f.get("topic"): f["signal"] for f in c.facts}
        if topics.get("listing") != "clear" or topics.get("registration") not in ("neutral", "weak"):
            return True
    return False


def undetermined(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str) -> dict:
    """The available evidence can't establish more, and deeper investigation couldn't change that. It says why:
    something couldn't be checked, weak signals were found, or both — never a gap that isn't there."""
    subject = _subject(plan_)
    after = ("only use it if you reached it yourself from the organisation's official website or app." if plan_.link_only else
             "check it through a channel you trust before acting on it.")
    unchecked = _unchecked(plan_)
    weak = sum(f["signal"] == "weak" for _, f in _live(checks))
    found = ("It found no warning signs" + ("" if not weak else ", only a weak signal that isn't a concern on its own" if weak == 1 else
                                            ", only weak signals that aren't a concern on their own"))
    why = [*(["some of what would settle this couldn't be checked"] if unchecked else []),
           *(["a weak signal can't settle it either way" if weak == 1 else "weak signals can't settle it either way"] if weak else [])]
    why = why or ["the checks that ran couldn't settle it either way"]
    means = f"{why[0][0].upper()}{why[0][1:]}{' and ' + why[1] if len(why) > 1 else ''}, so the available evidence can't establish more."
    return _result(
        plan_, checks, outcome="unable_to_determine", attention="review", actions=[_action("Check before using it", _CHECK_FIRST)],
        found=[_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _live(checks)],
        overview=f"ApolloSG couldn't establish enough about {subject} to say either way. {found}, but that isn't the same as it being safe — {after}",
        means=means,
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=False),
        reason=("Something ApolloSG couldn't fully check may still be unsafe." if unchecked else
                "What ApolloSG found can't show whether it's safe or not."),
        uncertainties=[_PAGE_UNOPENED if plan_.link_only else _who(plan_)])


def _with_gaps(result: dict, plan_: Plan) -> dict:
    """Whatever Higgins Triage couldn't extract stays visible: listed as remaining and uncertain, never assumed."""
    if not plan_.gaps:
        return result
    notes = [f"{g['item'][0].upper()}{g['item'][1:]}: {g['what']}." for g in plan_.gaps]
    return {**result, "completion": "partial", "uncertainties": [*notes, *result["uncertainties"]][:6],
            "remainingEvidenceIds": sorted({*result["remainingEvidenceIds"], *(g["evidenceId"] for g in plan_.gaps)})}


def compose(decision: Decision, plan_: Plan, material: dict[str, str], flyby_item: str) -> dict:
    """Higgins' result for a case TC FlyBy resolved, by what settled it."""
    route, checks = decision.answered_by, plan_.checks
    if decision.basis == "threat":
        result = concern(plan_, checks, material, flyby_item, route)
    elif decision.basis == "pattern":
        result = pattern_result(plan_, checks, material, flyby_item, decision.outcome)
    elif decision.basis == "impersonation":
        result = impersonation_result(plan_, checks, material, flyby_item, corroborated_impersonation(plan_))
    elif decision.basis == "signals":
        result = signals_result(plan_, checks, material, flyby_item)
    elif decision.outcome == "no_scam_indicators":
        result = clear(plan_, checks, material, flyby_item, route)
    else:
        result = undetermined(plan_, checks, material, flyby_item)
    return _with_gaps(result, plan_)


def knowledge_answer(check: Check, route: str, presented: str, source_ids: list[str]) -> dict:
    """A general question answered from Apollo's KB or a targeted search — information, not a finding."""
    if route == "tc_flyby_kb":
        overview = "Here's what ApolloSG's library says on this, from the sources below."
        body = presented
    else:
        lead = next((f for f in check.facts if f.get("class") == "live_evidence"), None)
        overview = (lead["text"] if lead else "Here's what a targeted search found.")[:600]
        sources = "\n".join(f"- {s['title']} — {s['url']}" for f in check.facts for s in (f.get("source") or {}).get("all") or [])
        body = f"{overview}\n\nSources:\n{sources}" if sources else overview
    return {
        "overview": overview[:900],
        "explanationMarkdown": f"{body}\n\n**How ApolloSG answered**\nTC FlyBy answered this with {ROUTE_LABEL[route]}. It's general information, "
                               "not a finding about anything you've submitted.",
        "assessment": "no_concern_found_within_scope", "outcome": None, "attention": "none", "attentionReason": None, "findings": [],
        "uncertainties": ["This is general information. If something specific has happened to you, send it to Apollo to check."],
        "scope": "A general question — nothing was submitted to check.", "sourceIds": source_ids, "remainingEvidenceIds": [],
        "actions": [], "recommendedActionIndex": None, "question": None, "completion": "complete",
    }


def magnum_brief(checks: list[Check], issues: list[dict], unread_sections: dict, pattern: dict | None = None,
                 floor: dict | None = None, cross_source: list[dict] | None = None, history: list[dict] | None = None) -> str:
    """Only what Magnum DI needs: the issues the deciding test sent it, the facts that bear on them, and what is still missing.
    Resolved, uneventful checks are named in one line so Magnum DI doesn't redo them; Apollo KB text isn't sent
    (a scam-pattern check is named in one line, as general knowledge)."""
    signals = [f"- {f['text']}" + (f" (source: {f['source']['publisher']})" if f.get("source") else "")
               + (" (weak signal: never a concern on its own)" if f["signal"] == "weak" else "")
               for c, f in _signs(checks)]
    missing = [f"- {f['text']}" for c in checks for f in c.facts if f["signal"] == "missing"]
    missing += [f"- {c.subject}: lookup unavailable" for c in checks if c.status == "unavailable"]
    clean = sorted({f"{c.kind} {c.subject}" for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] == "clear"})
    neutral = [f"- {f['text']}" for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] == "neutral"]
    parts = ["TC FlyBy fly-by results for this case (live evidence, with sources)."]
    if signals:
        parts.append("Established signals:\n" + "\n".join(signals))
    if neutral:
        parts.append("Established facts:\n" + "\n".join(neutral[:8]))
    if clean:
        parts.append("Already checked with no concern: " + "; ".join(clean[:10]) + ".")
    if missing:
        parts.append("Looked up, not found or unavailable (missing evidence, not proof either way):\n" + "\n".join(missing))
    if pattern:
        how = {"full": "matches", "opening": "matches the opening of", "partial": "partly matches"}[pattern["stage"]]
        parts.append(f"ApolloSG KB pattern check (general knowledge, not evidence about this case): the material {how} the "
                     f"{pattern['name']} described by {pattern['publisher']}.")
    if floor and floor.get("outcome"):
        how = ("resting on established threat evidence, which Magnum DI can't contradict or lower" if floor["established"] else
               "provisional: Magnum DI may confirm it, raise it, or correct it downward only with evidence that resolves it. "
               "A finding that corrects it cites that evidence and lists the provisional finding's id in supersedesFindingIds")
        parts.append(f"TC FlyBy's outcome: {outcomes.LABELS[floor['outcome']]} — {how}:\n"
                     + "\n".join(f"- {f['id']}: {f['text']}" for f in floor["findings"] if not f["text"].startswith("It asks for a secret")))
    if floor and floor.get("minimum"):
        parts.append("Established threat evidence (Magnum DI can't contradict it; the outcome can't be below "
                     f"{outcomes.LABELS[floor['minimum']]}):\n" + "\n".join(f"- {f['id']}: {f['text']}" for f in floor["findings"] if f["text"].startswith("It asks for a secret")))
    if issues:
        parts.append("For Magnum DI to settle — only these; everything above is already established:\n"
                     + "\n".join(f"- ({i['capability']}) {i['text']}" for i in issues))
    if cross_source:
        from services.correlation import brief_lines
        parts.append("Cross-source record (each source's own answer, its reference and how current it is; context, not new findings):\n"
                     + brief_lines(cross_source))
    if history:
        from services.higgins.history import brief_lines as history_lines
        parts.append("Related history (context only, never evidence for this case: don't cite it as a finding, a warning sign or "
                     "corroboration, and don't let it change the outcome. Related cases are this device's own; ApolloSG uses history "
                     "that agrees only to raise the confidence of findings this case's own evidence already supports):\n"
                     + history_lines(history))
    if unread_sections:
        parts.append("Other specialist results, verbatim: " + json.dumps(unread_sections, ensure_ascii=False, default=str))
    return "\n\n".join(parts)
