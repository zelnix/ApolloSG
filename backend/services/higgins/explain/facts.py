"""Higgins Plain-English Renderer, step 1: the authoritative findings, in structured form.

Built only from the validated result (TC FlyBy's or Magnum DI's) and the case's own records: Apollo's routing
(what Higgins Triage and TC FlyBy did, what Magnum DI was sent) and the registered sources. Nothing is
recomputed, re-scored or reinterpreted here. The renderer explains these facts; the Fidelity Check compares its
wording against them; where the two ever differ, these facts win.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from services.higgins import outcomes
from services.higgins.contracts import HigginsResponse
from services.higgins.tc_flyby.report import ROUTE_LABEL

# ── Words and sentences ──────────────────────────────────────────────────────
STOP = set(("a an the this that these those it its it's is are was were be been being so to of on in at or and but with for by as "
            "from your you there there's here what which who how would will can could has have had do does did if then than also just "
            "into about").split())
_WORD = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("’", "'").replace("‘", "'"))


def normal(text: str) -> str:
    return " ".join(words(text))


def _stem(w: str) -> str:
    w = re.sub(r"'s$", "", w)
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def meaning(text: str) -> set[str]:
    return {_stem(w) for w in words(text) if w not in STOP}


def negated(m: set[str]) -> bool:
    return any(w in ("not", "no", "never") or w.endswith("n't") for w in m)


def same_meaning(a: str, b: str) -> bool:
    """The same point in other words: three quarters of `a`'s meaningful words are in `b`, with the same yes-or-no."""
    ma, mb = meaning(a), meaning(b)
    return len(ma) >= 4 and len(ma & mb) / len(ma) >= 0.75 and negated(ma) == negated(mb)


def sentences(text: str) -> list[str]:
    """Split only where . ! ? is followed by a space, so example.com.au and $3.20 stay whole."""
    out, start = [], 0
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1].isspace()):
            out.append(text[start:i + 1].strip())
            start = i + 1
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return [s for s in out if s]


def strip_markdown(text: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\((https?:[^)]+)\)", r"\1 (\2)", text)
    return re.sub(r"^[-*•]\s+", "", text).strip()


# ── Identifiers that must survive word for word ──────────────────────────────
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
ENTITY_PATTERNS: dict[str, re.Pattern] = {
    "url": re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.I),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "domain": re.compile(r"(?<![@\w/.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b(?![@\w-])", re.I),
    "registration": re.compile(r"\b(?:ABN|ACN|ARBN|AFSL|ACL|licen[cs]e(?: number| no\.?)?|registration(?: number| no\.?)?)\s*:?\s*\d[\d ]{4,14}\d\b", re.I),
    "phone": re.compile(r"(?<![\w$.])\+?\d[\d ()-]{6,16}\d(?![\w.%])"),
    "money": re.compile(r"(?:A?\$|AUD ?|USD ?|€|£)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|million|billion)\b)?", re.I),
    "percent": re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|per ?cent\b)", re.I),
    "date": re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}} {_MONTH} \d{{4}}\b|\b{_MONTH} \d{{1,2}},? \d{{4}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b", re.I),
    "duration": re.compile(r"\b\d+(?:\.\d+)? (?:days?|weeks?|months?|years?|hours?|minutes?)\b", re.I),
}


def _norm_entity(kind: str, value: str) -> str:
    value = value.strip().rstrip(".,;:!?").lower()
    if kind == "url":
        value = value.rstrip("/")
    if kind in ("phone", "registration"):
        value = re.sub(r"[\s()-]", "", value)
    return value


def entities(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for kind, pattern in ENTITY_PATTERNS.items():
        for m in pattern.finditer(text):
            value = _norm_entity(kind, m.group(0))
            if kind == "phone" and not 8 <= len(re.sub(r"\D", "", value)) <= 15:
                continue
            if kind == "domain" and re.fullmatch(r"[\d.]+", value):
                continue
            if value:
                found.setdefault(kind, set()).add(value)
    # A URL's own host is part of the URL, not a separate identifier to restate.
    return found


def entity_text(text: str) -> str:
    """Text normalised the way entities are, so a preserved identifier can be found inside it."""
    return text.lower().replace("’", "'")


# ── Subject → check → result: one finding, structured ────────────────────────
# A deterministic reading of a finding's own words. No AI and nothing looked up: which identity the finding is about
# (its subject), which check it reports and what that check found. What the words don't say stays unknown.
SUBJECT_KINDS = ("email", "url", "domain", "phone", "registration")
NOUN = {"email": "email address", "url": "link", "domain": "website", "phone": "phone number", "registration": "registration number"}


def identity_value(kind: str, value: str) -> str:
    """The form two identifiers are compared in: lower case, no trailing punctuation, no "www."."""
    v = _norm_entity(kind, value)
    return re.sub(r"^(https?://)?www\.", r"\1", v) if kind in ("url", "domain") else v


def identifiers(text: str) -> list[tuple[str, str]]:
    """(kind, value as written) for each subject identifier in `text`, in the order they appear, each once."""
    found = []
    for kind in SUBJECT_KINDS:
        for m in ENTITY_PATTERNS[kind].finditer(text):
            value = m.group(0).strip().rstrip(".,;:!?")
            if kind == "phone" and not 8 <= len(re.sub(r"\D", "", value)) <= 15:
                continue
            if kind == "domain" and re.fullmatch(r"[\d.]+", value):
                continue
            found.append((m.start(), -len(value), kind, value))
    out: list[tuple[str, str]] = []
    taken: list[tuple[int, int]] = []
    seen: set[str] = set()
    for start, neg_len, kind, value in sorted(found):
        end = start - neg_len
        if any(s <= start < e for s, e in taken):  # a number inside an ABN, a host inside a link
            continue
        taken.append((start, end))
        key = f"{kind}:{identity_value(kind, value)}"
        if key not in seen:
            seen.add(key)
            out.append((kind, value))
    return out


def _host(kind: str, value: str) -> str:
    v = identity_value(kind, value)
    return (v.split("//")[-1].split("/")[0] if kind == "url" else v.split("@")[-1] if kind == "email" else v)


# Which check a finding reports, first match wins. Read on the plain-swapped words, so "is not" and "isn't" read alike.
CHECK_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("official_contact", re.compile(r"\b(?:published|official|listed)\b[^.]{0,80}?\b(?:contact|customer[- ]service|customer[- ]care|support|enquiries|help ?desk)\b"
                                    r"|\b(?:contact|customer[- ]service|support) (?:address|email|number|page)\b", re.I)),
    ("impersonation", re.compile(r"\b(?:isn't|not)\b[^.]{0,60}['’]s (?:own )?domain|\bcarries [^.]{1,60}['’]s name\b|\bputs [^.]{1,60}['’]s name\b", re.I)),
    ("official_domain", re.compile(r"\bofficial domains?\b|\bown domains?\b|\bpublished domains?\b", re.I)),
    ("risk_score", re.compile(r"\bfraud score\b|\brisk score\b", re.I)),
    ("reputation", re.compile(r"\bsafe browsing\b|\bblocklist\w*\b|\bscam (?:warning|advisory|advisories|alert)s?\b|\bwarnings?\b|\badvisor(?:y|ies)\b"
                              r"|\breputation\b|\bflag(?:s|ged)?\b|\b(?:lists|listed)\b", re.I)),
    ("registration", re.compile(r"\bregistered (?:on|in|less than|\d)|\bregistration record\b|\bRDAP\b", re.I)),
    ("redirect", re.compile(r"\bredirect(?:s|ed|ing)?\b", re.I)),
    ("registration_number", re.compile(r"\bcheck-digit\b", re.I)),
    ("free_email", re.compile(r"\bfree (?:personal )?email\b", re.I)),
)
_NEG = re.compile(r"\b(?:not|no|never|none|nothing|without)\b|n't\b", re.I)
# The four "nothing established" results, which must never be mixed up.
RESULT_KINDS: tuple[tuple[str, re.Pattern], ...] = (
    ("unavailable", re.compile(r"\bunavailable\b|\b(?:couldn't|can't|wasn't|weren't|isn't|aren't|not)\s+(?:be\s+|been\s+)?(?:checked|reached|looked up|read|completed?)\b"
                               r"|\bunable to (?:check|reach|look|read|complete)\b|\btimed out\b|\bdidn't answer\b", re.I)),
    ("not_applicable", re.compile(r"\bnot applicable\b|\b(?:doesn't|didn't|don't) apply\b|\bcan't (?:run|apply) (?:on|to|here)\b", re.I)),
    ("failed", re.compile(r"\bfail(?:s|ed)?\b", re.I)),
    ("no_match", re.compile(r"\bno (?:record|match|result|listing|entry|scam warning|warning|advisory|advisories|trace|mention)s?\b"
                            r"|\b(?:isn't|wasn't|aren't|weren't|not) (?:found|listed|named|flagged|mentioned)\b|\bfound no(?:thing)?\b"
                            r"|\bnothing (?:was )?found\b|\bhas nothing on\b|\bnever (?:been )?(?:listed|flagged|named)\b", re.I)),
)
REASSURING = {"OFFICIAL", "NOT_LISTED", "VALID"}
CONCERNING = {"NOT_OFFICIAL", "LISTED", "FAILED"}

_ORG_NAME = r"([A-Z][\w&.-]*(?: (?:[A-Z][\w&.-]*|of|and|&)){0,4})"
_ORG = (re.compile(rf"\bpublished {_ORG_NAME} (?:customer|contact|support|enquir|help|email|address)"),
        re.compile(rf"(?<![\w.@]){_ORG_NAME}['’]s (?:official|own|published|customer|support|contact|domain)"),
        re.compile(rf"\bnot {_ORG_NAME}['’]s\b"))
_NOT_ORG = {"Apollo", "ApolloSG", "TC FlyBy", "Magnum DI", "Higgins", "Google", "Google Safe Browsing", "Safe Browsing", "IPQualityScore",
            "It", "This", "The", "That", "Every", "No", "Its", "Their", "A", "An"}
# A finding that names its subject only generically, by type.
_GENERIC = {
    "domain": re.compile(r"\b(?:the|this|that|its) (?:website|web ?site|site|web address|domain)\b", re.I),
    "email": re.compile(r"\b(?:the|this|that) (?:email address|sender's address|sender address)\b", re.I),
    "phone": re.compile(r"\b(?:the|this|that) (?:phone number|number|caller)\b", re.I),
}


def result_kinds(text: str) -> frozenset[str]:
    """Which of unavailable / not applicable / failed / no match the words say."""
    from services.higgins.explain import words as W
    t = W.swap(text)
    return frozenset(kind for kind, rx in RESULT_KINDS if rx.search(t))


def classify(text: str) -> tuple[str, str]:
    """(check, result) the words report. ("stated", ...) when they name no check Apollo has."""
    from services.higgins.explain import words as W
    t = W.swap(text)
    check = next((name for name, rx in CHECK_RULES if rx.search(t)), "stated")
    kinds = result_kinds(t)
    if "unavailable" in kinds:
        return check, "UNAVAILABLE"
    if "not_applicable" in kinds:
        return check, "NOT_APPLICABLE"
    neg = bool(_NEG.search(t))
    if check in ("official_contact", "official_domain"):
        return check, "NOT_OFFICIAL" if neg else "OFFICIAL"
    if check in ("impersonation", "free_email"):
        return check, "NOT_OFFICIAL"
    if check == "reputation":
        return check, "NOT_LISTED" if neg or "no_match" in kinds else "LISTED"
    if check == "registration":
        return check, "NO_MATCH" if "no_match" in kinds else "REGISTERED"
    if check == "redirect":
        return check, "REDIRECTS"
    if check == "risk_score":
        return check, "SCORED"
    if check == "registration_number":
        return check, "FAILED" if "failed" in kinds else "VALID"
    return check, "FAILED" if "failed" in kinds else "NO_MATCH" if "no_match" in kinds else "STATED"


def identity(text: str) -> tuple[frozenset[str], str, str]:
    """A finding's identity: the identifiers it is about, the check and the result. Two findings are the same only
    when this is the same — never because their sentences look alike."""
    return (frozenset(f"{k}:{identity_value(k, v)}" for k, v in identifiers(text)), *classify(text))


def organisation(text: str) -> Optional[str]:
    for rx in _ORG:
        for m in rx.finditer(text):
            name = m.group(1).rstrip(".")
            if name and name not in _NOT_ORG:
                return name
    return None


def case_candidates(core: str) -> dict[str, list[str]]:
    """The identifiers of each type the result names, once each — what a generic "the website" can only mean when
    there is exactly one."""
    ids = identifiers(core)
    sites = list(dict.fromkeys(_host(k, v) for k, v in ids if k in ("url", "domain")))
    emails = list(dict.fromkeys(v for k, v in ids if k == "email"))
    return {"domain": sites or list(dict.fromkeys(_host("email", e) for e in emails)), "email": emails,
            "phone": list(dict.fromkeys(v for k, v in ids if k == "phone"))}


def bind_subject(text: str, candidates: dict[str, list[str]]) -> tuple[str, bool]:
    """The finding with its subject named. Only a finding that names no identifier of its own is bound, and only to
    the one identifier of that type the result names; anything ambiguous is left as written."""
    if identifiers(text):
        return text, False
    for kind, rx in _GENERIC.items():
        if len(candidates.get(kind, [])) == 1 and rx.search(text):
            return rx.sub(f'"{candidates[kind][0]}"', text, count=1), True
    check, result = classify(text)
    if check == "reputation" and result in ("LISTED", "NOT_LISTED") and len(candidates.get("domain", [])) == 1:
        return f'{text.rstrip().rstrip(".")} for "{candidates["domain"][0]}".', True
    return text, False


def structure_finding(finding: dict, candidates: dict[str, list[str]], outcome: Optional[str]) -> dict:
    """subject, subject type, organisation, check, result, the finding, its evidence, materiality and stance."""
    statement, bound = bind_subject(finding["text"], candidates)
    ids = identifiers(statement)
    check, result = classify(statement)
    polarity = "clear" if check != "stated" and result in REASSURING else "concern" if check != "stated" and result in CONCERNING else "neutral"
    direction = outcomes.DIRECTION.get(outcome or "")
    subject = ids[0] if ids else None
    org = organisation(statement)
    # "st0ko-login.co is not Stoko's domain": Stoko is the organisation the subject is NOT — never its owner.
    claimed = bool(org) and (check == "impersonation" or bool(re.search(rf"\bnot {re.escape(org)}['’]s\b", statement)))
    return {**finding, "statement": statement,
            "subject": subject[1] if subject else None, "subjectType": subject[0] if subject else None,
            "subjectSource": ("case" if bound else "finding") if subject else None,
            "organisation": org, "organisationClaimed": claimed, "check": check, "result": result, "polarity": polarity,
            "materiality": "material" if subject or check != "stated" else "context",
            "stance": "context" if polarity == "neutral" or not direction else "supporting" if polarity == direction else "contrary"}


# The subject a case is about, by what was checked: an email check is about the address, a link check the link.
_PREFERRED = {"email": ("email", "domain", "url"), "account": ("email",), "link": ("url", "domain"), "site": ("url", "domain"),
              "network": ("domain", "url"), "call": ("phone",), "text": ("url", "domain", "email", "phone")}


def case_subject(findings: list[dict], gates: tuple[str, ...] | list[str]) -> Optional[dict]:
    with_subject = [f for f in findings if f.get("subject")]
    if not with_subject:
        return None
    order = next((_PREFERRED[g] for g in gates if g in _PREFERRED), ()) + SUBJECT_KINDS
    lead = next(f for kind in order for f in with_subject if f["subjectType"] == kind)
    host = _host(lead["subjectType"], lead["subject"])
    named = lead if lead["organisation"] else next((f for f in with_subject if f["organisation"]
                                                    and _host(f["subjectType"], f["subject"]) == host), None)
    # organisation_claimed: the organisation is only named (the subject isn't its), so it is never called its owner.
    return {"value": lead["subject"], "type": lead["subjectType"], "organisation": named["organisation"] if named else None,
            "organisation_claimed": bool(named and named["organisationClaimed"])}


# ── The authoritative findings ───────────────────────────────────────────────
CONTRAST = re.compile(r"\b(but|however|although|though|whereas|contradict\w*|inconsistent|doesn't match|does not match|don't match|differ\w*|unlike)\b", re.I)
_FOUND = re.compile(r"^what (was|apollo|tc flyby|magnum di) found", re.I)
_HOW = re.compile(r"^how apollo (checked|answered)", re.I)
_MEANS = re.compile(r"^what it means", re.I)
AUTHORITY = {"official": "official source", "independent": "independent source",
             "self_claimed": "the destination's own page, not independent", "unknown": "search result, publisher not independently verified"}


def _blocks(markdown: str) -> list[tuple[Optional[str], list[str]]]:
    """The explanation's own sections: a "## Title" or "**Title**" line starts one."""
    out: list[tuple[Optional[str], list[str]]] = [(None, [])]
    for raw in markdown.split("\n"):
        m = re.match(r"^\s*(?:#{1,6}\s+(.+?)|\*\*(.+?)\*\*\s*(.*))\s*$", raw)
        if m and (m.group(1) or (m.group(2) and not re.search(r"[.!?]$", m.group(2)))):
            out.append((strip_markdown(m.group(1) or m.group(2)), [strip_markdown(m.group(3))] if m.group(3) else []))
        elif raw.strip():
            out[-1][1].append(strip_markdown(raw))
    return [(t, [line for line in lines if line]) for t, lines in out if t or lines]


@dataclass
class Facts:
    by: str
    revision: int
    outcome: Optional[str]
    assessment: str
    attention: str
    completion: str
    verdict: list[str]
    findings: list[dict]
    meaning: list[tuple[Optional[str], str]]
    method: list[str]
    attention_reason: Optional[str]
    uncertainties: list[str]
    scope: str
    remaining: int
    recommended: Optional[dict]
    other_actions: list[dict]
    actions: list[dict]
    sources: list[dict]
    triaged: bool
    flyby_routes: list[str]
    magnum: Optional[dict]
    # Every authoritative sentence of "How Apollo checked" and the scope, once.
    how: list[str] = field(default_factory=list)
    # The result's own words (no sources), and the same with the sources it relied on.
    core: str = ""
    corpus: str = ""
    # Identifiers the plain English must keep (from the result's own words), and those it may show (also the sources).
    entities: dict[str, set[str]] = field(default_factory=dict)
    allowed: dict[str, set[str]] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    # What the case is about: {"value", "type", "organisation"}, from its findings. None when no finding names one.
    subject: Optional[dict] = None

    def structure(self) -> dict[str, Any]:
        """The authoritative findings in Apollo's conceptual schema (finding / triage / flyby / investigation / ...).
        Every finding keeps its subject, subject type, organisation, check, result, the finding itself, its evidence,
        materiality and confidence, so Subject → Finding → Result can't come apart."""
        return {
            "finding": {"verdict": self.verdict, "classification": self.outcome, "assessment": self.assessment, "severity": self.attention,
                        "confidence": [f["confidence"] for f in self.findings]},
            "subject": self.subject,
            "findings": [{"id": f["id"], "subject": f["subject"], "subject_type": f["subjectType"], "organisation": f["organisation"],
                          "organisation_claimed": f["organisationClaimed"], "check": f["check"], "result": f["result"], "finding": f["statement"],
                          "evidence": {"evidence_ids": f["evidenceIds"], "source_ids": f["sourceIds"]},
                          "materiality": f["materiality"], "stance": f["stance"], "confidence": f["confidence"], "basis": f["basis"]}
                         for f in self.findings],
            "triage": {"ran": self.triaged}, "flyby": {"routes": self.flyby_routes},
            "investigation": {"by": self.by, "findings": self.findings, "meaning": [p for _, p in self.meaning], "method": self.method,
                              "contradictions": self.contradictions, "magnum": self.magnum},
            "entities": {k: sorted(v) for k, v in self.entities.items()},
            "evidence": {"authoritative_sources": self.sources},
            "uncertainty": {"unknowns": self.uncertainties, "scope": self.scope, "completion": self.completion, "unexamined": self.remaining},
            "guidance": {"recommended_action": self.recommended, "other_actions": self.other_actions, "urgency": self.attention},
            "renderer_constraints": {"must_preserve": sorted(v for vals in self.entities.values() for v in vals),
                                     "must_not_infer": ["classification", "severity", "confidence", "recommended action", "urgency", "attribution"]},
        }


def build(response: HigginsResponse, *, answered_by: Optional[str], routing: dict, sources: list[dict],
          gates: tuple[str, ...] | list[str] = ()) -> Facts:
    by = outcomes.investigator(answered_by)
    findings = [{"id": f.id, "text": strip_markdown(f.text), "basis": f.basis, "confidence": f.confidence, "sourceIds": list(f.source_ids),
                 "evidenceIds": list(f.evidence_ids)} for f in response.findings]
    meaning_paras: list[tuple[Optional[str], str]] = []
    method: list[str] = []
    finding_norms = [normal(f["text"]) for f in findings]
    for title, lines in _blocks(response.explanation_markdown or ""):
        if title and _HOW.search(title):
            method += [s for line in lines for s in sentences(line)]
        elif title and _FOUND.search(title):
            # A "what was found" line that isn't one of the structured findings is still a fact: kept as meaning.
            meaning_paras += [(None, line) for line in lines if not any(normal(line) in fn or fn in normal(line) for fn in finding_norms)]
        else:
            if title and lines and re.fullmatch(r"\(.+\)", lines[0]):
                # "**What Apollo's knowledge base adds** (general knowledge, not evidence …)": the caveat belongs to the title.
                title, lines = f"{title} {lines[0]}", lines[1:]
            meaning_paras += [(None if not title or _MEANS.search(title) else title, line) for line in lines]
    actions = [{"id": a.id, "label": strip_markdown(a.label), "instruction": strip_markdown(a.instruction)} for a in response.actions]
    recommended = next((a for a in actions if a["id"] == response.recommended_action_id), actions[0] if actions else None)
    used = set(response.source_ids)
    relied = [{"id": s.get("id"), "title": s.get("title") or s.get("url"), "url": s.get("url"), "authority": s.get("authority", "unknown"),
               "retrieval": s.get("retrieval")} for s in sources if s.get("id") in used]
    flyby = routing.get("tc_flyby") or {}
    routes = []
    for check in flyby.get("checks") or []:
        label = ROUTE_LABEL.get(check.get("route") or "")
        if label and label not in routes:
            routes.append(label)
    facts = Facts(
        by=by, revision=response.revision, outcome=response.outcome, assessment=response.assessment, attention=response.attention,
        completion=response.completion, verdict=[s for p in (response.overview or "").split("\n") for s in sentences(strip_markdown(p))],
        findings=findings, meaning=meaning_paras, method=method,
        attention_reason=strip_markdown(response.attention_reason) if response.attention_reason else None,
        uncertainties=[strip_markdown(u) for u in response.uncertainties if u.strip()], scope=strip_markdown(response.scope or ""),
        remaining=len(response.remaining_evidence_ids), recommended=recommended,
        other_actions=[a for a in actions if a is not recommended], actions=actions, sources=relied,
        triaged=bool(flyby) and response.revision == 1, flyby_routes=routes if response.revision == 1 else [],
        magnum=routing.get("magnum") if by == "Magnum DI" and response.revision == 1 else None,
    )
    for s in method + sentences(facts.scope):
        if normal(s) not in {normal(h) for h in facts.how}:
            facts.how.append(s)
    authoritative = (facts.verdict + [f["text"] for f in findings] + [p for _, p in meaning_paras] + [t for t, _ in meaning_paras if t]
                     + method + facts.uncertainties + [facts.scope, facts.attention_reason or ""]
                     + [f"{a['label']} {a['instruction']}" for a in actions] + routes + [outcomes.LABELS.get(facts.outcome or "", "")])
    facts.core = "\n".join(t for t in authoritative if t)
    facts.corpus = "\n".join([facts.core, *(f"{s['title']} {s['url']}" for s in relied)])
    facts.entities = entities(facts.core)
    facts.allowed = entities(facts.corpus)
    facts.contradictions = [s for text in (facts.verdict + [f["text"] for f in findings] + [p for _, p in meaning_paras] + facts.uncertainties)
                            for s in sentences(text) if CONTRAST.search(s)]
    candidates = case_candidates(facts.core)
    facts.findings = [structure_finding(f, candidates, facts.outcome) for f in findings]
    facts.subject = case_subject(facts.findings, gates)
    return facts
