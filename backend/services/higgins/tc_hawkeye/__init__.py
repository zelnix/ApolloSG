"""TC Hawkeye — Apollo's evidence-backed investigation.

    Input → Higgins Triage → only the relevant checks → for each check:
        1. direct / authoritative source (official.py)
        2. Apollo Knowledge Base — including the established scam patterns (patterns.py)
        3. one targeted web search per case — Brave Search, read deterministically; no AI model (search.py)
    → an Apollo case outcome (outcomes.py) when further investigation couldn't change the finding or what
      Higgins tells the person, or hand Magnum DI only what TC Hawkeye could not settle.

TC Hawkeye makes no AI call at all, never pays to confirm what a reliable source has already established, and Magnum DI never
rediscovers what TC Hawkeye found: it receives a short brief of the unresolved issues and the facts that bear on
them, with web search left off unless a specific external fact is still missing.

Evidence integrity: live evidence (facts about this case, each with its source), Apollo knowledge (general
context, never a finding) and AI reasoning (Magnum DI's inferences) are kept apart throughout. Anything a
lookup did not find stays missing.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.db import db, now_utc
from services import admin_alerts, kb_sources
from services.higgins import evidence as ev
from services.higgins import knowledge
from services.higgins import repository as repo
from services.higgins.contracts import Coverage, SourceReference
from services.higgins.tc_hawkeye import decide as deciding
from services.higgins.tc_hawkeye import official, patterns, report, search
from services.higgins.tc_hawkeye.official import fact, source_ref
from services.higgins.tc_hawkeye.triage import CALL_GATE, RED_FLAG_CLAIM, Check, Plan, digits
from services.higgins.tc_hawkeye.triage import plan as triage_plan

log = logging.getLogger("apollo.tc_hawkeye")

PREGATHERED_ITEM_ID = "apollo-triage-intelligence"   # what Higgins Triage gathered before the case started
CHECKS_ITEM_ID = "tc-flyby-di-checks"                   # TC Hawkeye's full check record, with provenance
BRIEF_ITEM_ID = "tc-flyby-di-brief"                     # the slice Magnum DI receives
_CORPORATE = re.compile(r"\b(pty|ltd|limited|inc|llc|plc|the|group|holdings)\b\.?", re.I)
# A warning only an official source naming this exact value makes decisive; any other warning is a third-party
# warning, and text found copied elsewhere is supporting evidence only: both are weak signals.
_SEARCH_SIGNAL = {"WARNING": "weak", "OFFICIAL": "clear", "FOUND_ELSEWHERE": "weak"}


@dataclass
class HawkeyeOutcome:
    resolved: bool
    answered_by: str
    response: dict | None = None
    rows: list[dict] = field(default_factory=list)       # what Magnum DI receives when it is needed
    magnum_search: bool = False
    #: What Magnum DI's result can't go below (decide.floor): TC Hawkeye's concern, established or provisional.
    floor: dict | None = None
    usage: dict = field(default_factory=dict)
    simulated: bool = False
    model: str | None = None


FlyByOutcome = HawkeyeOutcome  # Legacy import compatibility


# ── Higgins Triage's extraction: every input made investigation-ready ─────────
def _page_number(row: dict) -> int | None:
    match = re.search(r"\.page(\d+)$", row.get("client_item_id") or "")
    return int(match.group(1)) if match else None


def _gap(row: dict, item: str, what: str, *, magnum: bool) -> dict:
    """Something Triage couldn't extract. `magnum`: Magnum DI can read it directly (an image), so reading it is
    something deeper investigation could add."""
    return {"evidenceId": row["evidence_id"], "item": item, "what": what, "magnum": magnum}


async def _material(owner: str, case: dict, rows: list[dict]) -> tuple[dict[str, str], list[dict], list[dict]]:
    """Before TC Hawkeye sees anything: submitted text and links, the text the phone read from screenshots and
    images, and the text layer of documents — and a record of whatever couldn't be extracted.
    Returns (texts, gaps, rows read)."""
    texts: dict[str, str] = {}
    gaps: list[dict] = []
    read: list[dict] = []
    by_id = {r["evidence_id"]: r for r in rows}
    extracted = {r["parent_id"] for r in rows if r["kind"] == "text" and r.get("parent_id") and r["origin"] != "apollo_inference"}
    scanned: dict[str, set[int]] = {}
    for row in rows:
        parent = by_id.get(row.get("parent_id") or "")
        if row["kind"] == "text" and parent and parent["kind"] == "document":
            pages = (await repo.evidence_meta(row)).get("pages") or []
            scanned[parent["evidence_id"]] = {p["page"] for p in pages if not p.get("readable", True)}
    for row in rows:
        if row["origin"] in ("apollo_inference", "device_observation", "external_source"):
            continue
        kind, eid = row["kind"], row["evidence_id"]
        label = row.get("label") or kind
        parent = by_id.get(row.get("parent_id") or "")
        if row["availability"] != "available":
            if kind in ("image", "document", "audio", "attachment") and eid not in extracted:
                gaps.append(_gap(row, label, "it wasn't available to examine", magnum=False))
            continue
        if kind in ("text", "url"):
            text = (await repo.read_bytes(owner, case["case_id"], eid)).decode("utf-8", errors="replace")
            if text.strip() and not ev.is_workflow_metadata(text):
                texts[eid] = text
                read.append(row)
        elif kind == "image" and parent and parent["kind"] == "document":
            doc, page = parent.get("label") or "the document", _page_number(row)
            if page is None:
                gaps.append(_gap(row, f"an image inside {doc}", "what the image shows couldn't be extracted", magnum=True))
            elif page in scanned.get(parent["evidence_id"], set()) or parent["evidence_id"] not in extracted:
                gaps.append(_gap(row, f"page {page} of {doc}", "a scanned page with no text layer, so its text couldn't be extracted", magnum=True))
            else:
                gaps.append(_gap(row, f"the pictures on page {page} of {doc}", "the page's text was extracted, but not what its pictures show", magnum=True))
        elif kind == "image" and eid not in extracted:
            gaps.append(_gap(row, label, "no text could be read from this image on the phone, so its content wasn't extracted", magnum=True))
        elif kind == "document" and eid not in extracted:
            gaps.append(_gap(row, label, "the document's text couldn't be extracted", magnum=False))
        elif kind == "document":
            reasons = {o.get("reason") or "" for o in (row.get("coverage") or {}).get("omittedRanges") or []}
            gaps += [_gap(row, f"part of {label}", reason, magnum=False) for reason in sorted(reasons)
                     if reason and not reason.startswith("rendered page withheld")]
        elif kind in ("audio", "attachment"):
            gaps.append(_gap(row, label, "ApolloSG can't extract content from this kind of file", magnum=False))
    return texts, gaps, read


# ── Higgins Triage's rules: what flagged the case is a warning sign TC Hawkeye builds on ──
def _lookalike_chars(org: str, text: str) -> list[str]:
    from services import triage_engine as te
    return list(dict.fromkeys(ch for word in te.disguised_words(text) if word in org for ch in word
                              if te._DISGUISE.match(ch) or te._OTHER_SCRIPT.match(ch)))


def _rule_fact(rule_id: str, title: str, text: str) -> str:
    """What the rule saw, quoting the message's own words where the rule reads them (the phone's wording)."""
    from services import triage_engine as te
    if rule_id == "MSG-23":
        org = te.organisation_named(text)
        chars = _lookalike_chars(org, text)
        how = " and ".join(f"“{c}”" for c in chars) if chars else "look-alike characters"
        return f"It writes “{org}” with {how} in place of ordinary letters. A real business has no reason to do that."
    if rule_id == "MSG-24":
        rebate = te._REBATE.search(text) or te._STC.search(text)
        reply = te._REPLY.search(text)
        ask = f"asks you to reply (“{reply.group(0)}”)" if reply else "asks you to call a number it supplies"
        return (f"It claims a government rebate (“{rebate.group(0)}”), puts a deadline on it to hurry you "
                f"(“{te._PRESSURE.search(text).group(0)}”) and {ask}.")
    return f"{title}."


def _triage_stage(plan_: Plan, text: str, provider_evidence: dict | None) -> None:
    """Higgins Triage's message rules — the catalogue the phone runs — over the material. Each threat-producing rule
    met is a warning sign about this case: TC Hawkeye's own checks can add to it, never dismiss it."""
    if not plan_.has_message or plan_.channel == CALL_GATE:
        return
    from services.triage import evaluate
    from services.triage_engine import _extract_evidence_from_text, _rule_evidence
    evidence = _extract_evidence_from_text("", text)
    met = evaluate(_rule_evidence(evidence, [], provider_evidence or {})).met_rules
    if not met:
        return
    facts = [{**fact(_rule_fact(r.rule_id, r.title, text), "concern", topic="triage_rule"), "ruleId": r.rule_id} for r in met]
    plan_.checks.append(Check(id=f"c{len(plan_.checks) + 1}", kind="triage_rules", subject="Higgins Triage's message rules",
                              status="resolved", route="triage_rules", facts=facts))


#: Higgins Triage's message rules that rest on who the material says it is and where it sends you — its links,
#: numbers and addresses. A request for a secret, a listed link or a disguised name rests on the words themselves.
_ROUTE_RULES = frozenset({"MSG-08", "MSG-14", "MSG-18", "MSG-20", "MSG-21", "MSG-22"})


def _reconsider_triage(plan_: Plan) -> None:
    """Before the Evidence Lock, an initial detection can be disproved. A route-based Higgins Triage rule stops counting
    as a warning sign when TC Hawkeye's official sources verified every link, number and address in the material as the
    organisation's own: what it rested on turned out to be genuine. The rule's fact is kept, marked disproved, and the
    verification is recorded as TC Hawkeye's own fact."""
    routes = [c.subject for c in plan_.checks if c.kind in ("link", "email", "phone")]
    if not routes or not all(deciding.verified(r, plan_) for r in routes):
        return
    disproved = [f for c in plan_.checks if c.kind == "triage_rules" for f in c.facts
                 if f.get("ruleId") in _ROUTE_RULES and f["signal"] == "concern"]
    if not disproved:
        return
    shown = ", ".join(f"“{r}”" for r in routes[:3]) + (f" and {len(routes) - 3} more" if len(routes) > 3 else "")
    for f in disproved:
        f.update(signal="neutral", disproved=True)
    names = "; ".join(f["text"].rstrip(".") for f in disproved)
    plan_.checks.append(Check(id=f"c{len(plan_.checks) + 1}", kind="triage_review", subject="Higgins Triage's first reading",
                              status="resolved", route="official_source",
                              facts=[{**fact(f"Higgins Triage first flagged this ({names}), but official sources verified {shown} as the "
                                             "organisation's own, so that no longer counts as a warning sign.", "clear", topic="triage_disproved"),
                                      "ruleIds": [f["ruleId"] for f in disproved]}]))


# ── Stage 2: Apollo Knowledge Base ──────────────────────────────────────────
def _current(entries: list[dict]) -> list[dict]:
    """Sourced, current KB entries only: saved AI answers and historical pages are not used."""
    return [e for e in entries if e.get("kind") != "gemini_answer" and e.get("status") != "historical"]


def _kb_fact(entry: dict, text: str) -> dict:
    level = "official" if entry.get("authority_tier") == kb_sources.TIER_1 else "independent"
    return fact(text, "context", kind="apollo_knowledge", source={
        "publisher": entry.get("publisher"), "url": entry.get("url"), "title": entry.get("title"), "authority": level,
        "basis": "ApolloSG Knowledge Base — general knowledge, not evidence about this case", "retrieval": "fetched", "kbId": entry.get("kb_id")})


def _offsite(plan_: Plan) -> bool | None:
    """Evidence-based pattern indicator: does a link in the material go somewhere that isn't an official domain?
    None when there is no link."""
    links = [c for c in plan_.checks if c.kind == "link"]
    if not links:
        return None
    return any(not any(f["decisive"] and f["signal"] == "clear" for f in c.facts) for c in links)


async def _pattern_stage(plan_: Plan, text: str) -> None:
    """Compare the material with the established scam patterns in Apollo's KB (deterministic, no cost)."""
    if not plan_.has_message:
        return
    found = await patterns.best(text, has_link=bool(plan_.entities.hosts), has_brand=bool(plan_.entities.brands), offsite=_offsite(plan_),
                                channel=plan_.channel)
    if not found:
        return
    plan_.pattern = found.wire()
    entry = found.entry
    check = Check(id=f"c{len(plan_.checks) + 1}", kind="scam_pattern", subject=entry.get("title") or found.wire()["name"], route="apollo_kb",
                  facts=[_kb_fact(entry, f"{entry.get('publisher')}: “{entry.get('title')}”")])
    check.status = "resolved"   # a partial match establishes nothing by itself; the deciding test weighs it
    plan_.checks.append(check)


async def _kb_stage(plan_: Plan, text: str) -> None:
    await _pattern_stage(plan_, text)
    for check in plan_.checks:
        try:
            if check.kind == "general_question":
                hits = _current(await knowledge.search(check.subject))
                if hits:
                    check.facts += [_kb_fact(e, f"{e.get('publisher')}: “{e.get('title')}”") for e in hits]
                    check.status, check.route = "resolved", "apollo_kb"
                elif not check.question:
                    check.status, check.open_issue = "needs_reasoning", "A general question that needs reasoning rather than a lookup."
            elif check.kind == "claim":
                if RED_FLAG_CLAIM.search(check.subject):
                    check.facts.append(fact(f"The material promises “{check.subject}”. Scamwatch lists “over-the-top promises of big returns” "
                                            "as a warning sign of investment scams.", "anomaly", topic="claim",
                                            source=source_ref("Scamwatch (ACCC)", url="https://www.scamwatch.gov.au/types-of-scams/investment-scams",
                                                              basis="Scamwatch's published warning signs of investment scams")))
                else:
                    check.facts.append(fact(f"The material makes a financial claim: “{check.subject}”.", "neutral", topic="claim"))
                for entry in _current(await knowledge.related(check.subject))[:2]:
                    check.facts.append(_kb_fact(entry, f"{entry.get('publisher')} on claims like this: “{entry.get('title')}”"))
                check.status, check.route = "resolved", "apollo_kb"
            elif check.kind == "scam_alerts":
                for entry in _current(await knowledge.related(text[:1500]))[:2]:
                    check.facts.append(_kb_fact(entry, f"{entry.get('publisher')}: “{entry.get('title')}”"))
                check.status, check.route = "resolved", "apollo_kb"
            elif check.kind == "company":
                for entry in _current(await knowledge.related(check.subject)):
                    if entry.get("kind") == "scam_alert" and check.subject.lower() in f"{entry.get('title', '')} {entry.get('body', '')}".lower():
                        check.facts.append(_kb_fact(entry, f"ApolloSG's library holds an official alert that mentions “{check.subject}” (“{entry.get('title')}”). "
                                                           "That is context, not proof about this case."))
        except Exception:  # noqa: BLE001 — the KB can never break an investigation
            log.warning("tc_hawkeye_kb_stage_failed kind=%s", check.kind, exc_info=True)


# ── Stage 3: applying targeted search answers ───────────────────────────────
def _names(check: Check, text: str) -> bool:
    """The warning is about this exact value, not a similar one."""
    if check.kind == "phone":
        return digits(check.subject)[-8:] in digits(text)
    return check.subject.lower() in (text or "").lower()


def _core(name: str) -> str:
    return " ".join(_CORPORATE.sub(" ", name.lower()).split())


_GENERIC_NAME_WORDS = {"australia", "australian", "services", "service", "capital", "investments", "investment", "financial", "finance",
                       "markets", "trading", "wealth", "partners", "securities", "management", "asset", "funds", "fund", "global",
                       "international", "company", "corporation", "solutions", "enterprises"}


def _shares_name(name: str, entry: str) -> bool:
    """The register entry shares a distinctive word with the name in the material (a possible trading name,
    parent or related entity) without matching it."""
    words = {w for w in re.findall(r"[a-z0-9]+", _core(name)) if len(w) >= 4 and w not in _GENERIC_NAME_WORDS}
    return any(re.search(rf"\b{re.escape(w)}\b", entry) for w in words)


def _apply(check: Check, answer: dict, plan_: Plan) -> None:
    status = answer.get("status")
    if status == "UNAVAILABLE":
        # Not searched (one search per case, not set up, a failure): missing evidence, never a pass.
        check.status = "unavailable"
        # Retain source-provided fields; Higgins SLM interprets their meaning.
        check.open_issue = ""
        check.facts.append(fact(json.dumps(answer, ensure_ascii=False, default=str),
                                "missing", topic="web_search"))
        return
    check.route = "web_search"
    sources = answer.get("sources") or []
    lead = sources[0] if sources else None
    src = ({"publisher": lead["domain"] or lead["title"], "url": lead["url"], "title": lead["title"], "authority": lead["authority"],
            "basis": lead["basis"], "retrieval": "search_result", "all": sources} if lead else None)
    if src and answer.get("reused"):
        # An earlier lookup reused while still current: its pages keep the time Apollo last checked them.
        src.update(reused=True, checkedAt=answer.get("lastVerifiedAt"))
    if status in ("UNANSWERED", "UNSOURCED"):
        check.status = "not_found"
        check.facts.append(fact(f"TC Hawkeye's search returned no sourced answer about {check.subject}.", "missing"))
        return
    if status in search.NOT_FOUND:
        check.status = "not_found"
        check.facts.append(fact(answer.get("fact") or f"TC Hawkeye's search found no record for {check.subject}.", "missing", source=src))
        return
    decisive = (status == "WARNING" and check.kind in ("link", "phone", "email", "company")
                and any(s.get("authority") == "official" for s in sources) and _names(check, answer.get("fact", "")))
    check.facts.append(fact(answer.get("fact", ""), "concern" if decisive else _SEARCH_SIGNAL.get(status, "neutral"), decisive=decisive, source=src))
    check.status = "resolved"
    if check.kind in ("abn", "acn", "licence") and plan_.entities.companies:
        named = plan_.entities.companies
        entry = answer.get("fact", "").lower()
        if any(_core(c) and _core(c) in entry for c in named):
            check.facts.append(fact(f"The register entry for {check.subject} matches {named[0]}, the name in the material.", "clear", topic="name_match"))
        elif any(_shares_name(c, entry) for c in named):
            # Related but different: a trading name or related entity would explain it, a lookalike wouldn't.
            check.facts.append(fact(f"The register entry for {check.subject} is under a related but different name to {', '.join(named)}, the name in "
                                    "the material.", "anomaly", topic="name_relation"))
            check.status, check.open_issue = "needs_reasoning", (f"Conflict: {check.subject} is registered to a related but different name than "
                                                                 f"{named[0]} — whether that is a trading name or related entity, or a mismatch.")
        else:
            check.facts.append(fact(f"The register entry for {check.subject} does not match {', '.join(named)}, the name in the material.", "anomaly",
                                    topic="name_match"))


# ── After the deciding test (decide.py) ─────────────────────────────────────
def _settle(plan_: Plan, issues: list[deciding.Issue]) -> None:
    """Record per check whether Magnum DI takes it on: only what the deciding test sent it. Every other open
    check was not needed, because it couldn't change Apollo's finding or Higgins' action."""
    sent = {i.check_id for i in issues if i.check_id}
    for check in plan_.checks:
        if check.id in sent:
            check.status = "needs_reasoning"
        elif check.status in ("open", "needs_reasoning"):
            check.status = "not_needed"


# ── Persistence and provenance ──────────────────────────────────────────────
def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _register_sources(owner: str, case_id: str, checks: list[Check]) -> None:
    refs: list[SourceReference] = []
    for check in checks:
        for f in check.facts:
            src = f.get("source") or {}
            pages = [(s["url"], s.get("title"), s.get("authority"), s.get("basis"), "search_result") for s in src.get("all") or []]
            if not pages and (src.get("url") or "").startswith("https://"):
                pages = [(src["url"], src.get("title") or src.get("publisher"), src.get("authority"), src.get("basis"), src.get("retrieval"))]
            ids = []
            reused = bool(src.get("reused"))
            checked = _parse_time(src.get("checkedAt")) if reused else None
            for url, title, authority, basis, retrieval in pages:
                ref = SourceReference(id=str(uuid.uuid4()), url=url, title=(title or url)[:200], retrieved_at=checked or now_utc(),
                                      retrieval=retrieval if retrieval in ("fetched", "search_result") else "fetched",
                                      authority=authority if authority in ("official", "independent", "self_claimed") else "unknown",
                                      authority_basis=(basis or "")[:300], reused=reused)
                refs.append(ref)
                ids.append(ref.id)
            f["sourceIds"] = ids
    if not refs:
        return
    mapping = await repo.add_sources(owner, case_id, refs)
    for check in checks:
        for f in check.facts:
            f["sourceIds"] = list(dict.fromkeys(mapping.get(i, i) for i in f.get("sourceIds", [])))


async def _item(owner: str, case: dict, client_item_id: str, text: str, label: str) -> str:
    existing = next((r for r in await repo.list_evidence(owner, case["case_id"]) if r.get("client_item_id") == client_item_id), None)
    if existing:
        return existing["evidence_id"]
    item = await ev.ingest_text(owner, case, client_item_id, text, kind="observation", origin="apollo_inference", label=label,
                                meta={"source": "tc_hawkeye_di"}, coverage=Coverage(status="examined", unit="items", total=1, examined=1))
    return item.id


async def _mark_read(owner: str, case_id: str, read: list[dict], texts: dict[str, str]) -> None:
    """TC Hawkeye read these items in full to triage them, so they are examined."""
    for row in read:
        coverage = row.get("coverage") or {}
        total = coverage.get("total") or (1 if coverage.get("unit") == "items" else len(texts[row["evidence_id"]]))
        await ev.mark_examined(owner, case_id, row["evidence_id"], 0, total, total)


async def _magnum_rows(owner: str, case: dict, brief_id: str, needed: set[str] | None, settled: set[str]) -> list[dict]:
    """What Magnum DI receives: TC Hawkeye's brief, the evidence each unresolved issue needs, and anything TC Hawkeye didn't
    examine. Material TC Hawkeye already settled — and the raw lookups behind it — isn't resent. `needed` None: the
    whole case (TC Hawkeye's own result couldn't be used)."""
    pe_values = {json.dumps(v, sort_keys=True, default=str) for v in (case.get("triage_provider_evidence") or {}).values()}
    skip = set() if needed is None else settled - needed
    rows = []
    for row in await repo.list_evidence(owner, case["case_id"]):
        cid = row.get("client_item_id") or ""
        if cid in (PREGATHERED_ITEM_ID, CHECKS_ITEM_ID):
            continue
        if row["evidence_id"] in skip or (row["origin"] == "apollo_inference" and row.get("parent_id") in skip):
            continue
        if cid.startswith("intel-") and pe_values:
            text = (await repo.read_bytes(owner, case["case_id"], row["evidence_id"])).decode("utf-8", errors="replace")
            try:
                if json.dumps(json.loads(text), sort_keys=True, default=str) in pe_values:
                    continue
            except ValueError:
                pass
        rows.append(row)
    return sorted(rows, key=lambda r: r["evidence_id"] != brief_id)


def _summary(plan_: Plan, decision: deciding.Decision | None, issues: list[deciding.Issue], magnum_search: bool, searched: dict) -> dict:
    return {"ranAt": now_utc(), "answeredBy": decision.answered_by if decision else "magnum_di", "resolved": bool(decision),
            "outcome": decision.outcome if decision else None, "basis": decision.basis if decision else None, "messageType": plan_.message_type,
            "pattern": {"key": plan_.pattern["key"], "stage": plan_.pattern["stage"]} if plan_.pattern else None,
            "checks": [{"kind": c.kind, "status": c.status, "route": c.route} for c in plan_.checks],
            "searchCalls": searched["calls"], "searchQueries": searched["queries"], "cacheHits": searched["cacheHits"],
            "searchProvider": searched.get("provider"), "searchTarget": searched.get("target"), "aiCalls": 0,
            "flybyTokens": searched["tokens"], "simulated": searched["simulated"], "searchModel": searched["model"],
            "magnumNeeded": not decision, "magnumSearch": magnum_search, "reusedOnRetry": 0,
            "gaps": [{"item": g["item"], "what": g["what"]} for g in plan_.gaps],
            "issues": [{"capability": i.capability, "text": i.text} for i in issues]}


# ── Entry point ─────────────────────────────────────────────────────────────
async def investigate(owner: str, case: dict, job: dict, question: str, rows: list[dict], progress, *, triage_advice: dict | None = None, hawkeye_advice: dict | None = None) -> HawkeyeOutcome:
    """Run TC Hawkeye checks and retain their evidence-backed investigation record.

    Accepted Higgins Triage and Hawkeye SLM suggestions may reorder existing
    checks, but cannot create evidence or authorise a final Finding. The
    coordinator separately requires Higgins SLM escalation assessment and a
    validated on-device SLM Finding before committing the case.
    """
    case_id = case["case_id"]
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "tc_hawkeye_ciphertext": 1})
    if stored and stored.get("tc_hawkeye_ciphertext"):
        record = repo.dec_json(stored["tc_hawkeye_ciphertext"])
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$inc": {"routing.tc_hawkeye.reusedOnRetry": 1}})
    else:
        record = await _run(owner, case, job, question, rows, progress, triage_advice=triage_advice, hawkeye_advice=hawkeye_advice)
    usage = record["search"]["tokens"]
    common = {"usage": {"input_tokens": usage.get("input") or None, "output_tokens": usage.get("output") or None},
              "simulated": record["search"]["simulated"], "model": record["search"]["model"]}
    if record.get("response"):
        return HawkeyeOutcome(True, record["decision"]["answeredBy"], response=record["response"], **common)
    issues = record.get("issues")
    needed = None if issues is None else {e for i in issues for e in i["evidenceIds"]}
    rows_ = await _magnum_rows(owner, case, record["items"]["brief"], needed, set(record.get("settled") or []))
    return HawkeyeOutcome(False, "magnum_di", rows=rows_, magnum_search=record["magnumSearch"], floor=record.get("floor"), **common)


async def _run(owner: str, case: dict, job: dict, question: str, rows: list[dict], progress, *, triage_advice: dict | None = None, hawkeye_advice: dict | None = None) -> dict:
    case_id = case["case_id"]
    await progress("observe", "Higgins Triage is preparing what was sent and working out what needs checking.")
    texts, gaps, read = await _material(owner, case, rows)
    plan_ = triage_plan(question, list(texts.values()), gaps=gaps, gate=next(iter(case.get("gates") or []), None))
    from services.higgins.slm_advisory import prioritise_existing_checks
    prioritise_existing_checks(plan_.checks, triage_advice, hawkeye_advice)
    combined = "\n".join(texts.values())
    _triage_stage(plan_, combined, case.get("triage_provider_evidence"))

    await progress("observe", "TC Hawkeye is checking official sources first.")
    await official.run(plan_, case.get("triage_provider_evidence"), combined)
    _reconsider_triage(plan_)
    # Cross-source matching: every source's own answer per website, number and address, with its freshness. Context for
    # Magnum DI's brief only: it adds nothing to the checks.
    from services import correlation
    try:
        cross = await correlation.cross_source(plan_, case.get("triage_provider_evidence"), owner)
    except Exception:  # noqa: BLE001 — extra context; never breaks an investigation
        log.warning("cross_source_failed case=%s", case_id, exc_info=True)
        cross = []
    # Related history: this device's own earlier cases and ApolloSG's previous reports. Context, never evidence:
    # nothing here reaches the checks, so it can't make or change the outcome (services/higgins/history.py).
    from services.higgins import history
    subjects = history.subjects(plan_, texts, rows)
    notes = await history.gather(owner, case, subjects)
    decision, issues = deciding.evaluate(plan_, texts, final=False)
    searched = {"calls": 0, "queries": 0, "cacheHits": 0, "tokens": {"input": 0, "output": 0}, "simulated": False, "model": None, "status": "skipped"}
    # A decisive concern ends TC Hawkeye's stages, whether it settles the case or hands Magnum DI what it couldn't read.
    if not decision and not deciding.decisive(plan_):
        await progress("observe", "TC Hawkeye is checking ApolloSG's knowledge base.")
        await _kb_stage(plan_, combined)
        decision, issues = deciding.evaluate(plan_, texts, final=False)
    if not decision and not deciding.decisive(plan_):
        # Only what no verified source already answered: a check settled by a direct source or the KB isn't open.
        open_checks = [c for c in plan_.checks if c.question and c.status == "open"]
        if open_checks:
            await progress("research", "TC Hawkeye is running one targeted web search.")
            focus = {t for r in deciding.unverified_requests(plan_) for t in r["targets"]}
            searched = await search.run(open_checks, correlation_id=f"case-{case_id}", trigger_source=job.get("source"), owner=owner,
                                        focus=focus, brands=[b[0] for b in plan_.entities.brands])
            for check in open_checks:
                if check.id in searched["answers"]:
                    _apply(check, searched["answers"][check.id], plan_)
        decision, issues = deciding.evaluate(plan_, texts, final=True)
    _settle(plan_, issues)
    magnum_search = False if decision else deciding.magnum_needs_search(plan_, issues)
    floor = None if decision else deciding.floor(plan_, deciding.provisional(plan_))
    # A reputation-check provider (IPQualityScore) genuinely failed or timed out after retrying, with
    # nothing else resolving what it would have covered — a Criterion 1 Investigation Failure (Developer
    # Instructions §2) that now mandatorily escalates to Magnum DI (decide.evaluate()) rather than TC
    # Hawkeye resolving it alone; still logged to the admin Alerts console for visibility either way.
    failed_checks = deciding.technical_issue(plan_)
    if failed_checks:
        await admin_alerts.log_technical_failure(
            owner=owner, case_id=case_id, checks=sorted({c.kind for c in failed_checks}),
            subjects=sorted({c.subject for c in failed_checks if c.subject}),
            reason="IPQualityScore did not answer after retrying.")

    await _register_sources(owner, case_id, plan_.checks)
    unread_sections = official.unread_sections(case.get("triage_provider_evidence"))
    checks_id = await _item(owner, case, CHECKS_ITEM_ID, json.dumps({
        "messageType": plan_.message_type, "entities": plan_.entities.wire(), "checks": [c.wire() for c in plan_.checks],
        "pattern": plan_.pattern, "gaps": plan_.gaps, "issues": [i.wire() for i in issues], "crossSource": cross,
        "search": {k: v for k, v in searched.items() if k != "answers"}}, ensure_ascii=False, default=str), "TC Hawkeye investigation checks")
    await _mark_read(owner, case_id, read, texts)

    response = None
    if decision and decision.basis == "knowledge":
        check = plan_.checks[0]
        entries = [e for e in [await db.higgins_knowledge.find_one({"kb_id": (f.get("source") or {}).get("kbId")}, {"_id": 0})
                               for f in check.facts if (f.get("source") or {}).get("kbId")] if e]
        presented = knowledge.present(entries, check.subject)[0] if entries else ""
        response = report.knowledge_answer(check, decision.answered_by, presented, sorted({s for f in check.facts for s in f.get("sourceIds", [])}))
    elif decision:
        response = report.compose(decision, plan_, texts, checks_id)
    brief_id = None
    if not decision:
        brief_id = await _item(owner, case, BRIEF_ITEM_ID, report.magnum_brief(plan_.checks, [i.wire() for i in issues], unread_sections, plan_.pattern, floor, cross, notes),
                               "TC Hawkeye brief for Magnum DI")

    # Material TC Hawkeye read in full, and the images whose content it read through the text extracted from them.
    by_id = {r["evidence_id"]: r for r in rows}
    settled = {r["evidence_id"] for r in read} | {r["parent_id"] for r in read if (by_id.get(r.get("parent_id") or "") or {}).get("kind") == "image"}
    record = {"version": 3, "ranAt": now_utc().isoformat(), "plan": {"messageType": plan_.message_type, "linkOnly": plan_.link_only,
              "general": plan_.general, "gaps": plan_.gaps}, "checks": [c.wire() for c in plan_.checks], "pattern": plan_.pattern,
              "decision": {"answeredBy": decision.answered_by, "outcome": decision.outcome, "basis": decision.basis} if decision else None,
              "issues": [i.wire() for i in issues], "settled": sorted(settled),
              "response": response, "magnumSearch": magnum_search, "floor": floor, "search": {k: v for k, v in searched.items() if k != "answers"},
              "crossSource": cross, "items": {"checks": checks_id, "brief": brief_id},
              # One-way codes and history notes only — never content. kbAsserted: what ApolloSG's previous reports asserted
              # to this case, so its own finding never counts as independent confirmation of them (observed_intel).
              "history": notes, "historyKeys": [history.device_key(owner, s) for s in subjects],
              "observedExtra": history.observed_subjects(subjects),
              "kbAsserted": sorted(set(correlation.asserted(cross)) | set(history.asserted(notes)))}
    summary = _summary(plan_, decision, issues, magnum_search, searched)
    summary["floor"] = floor
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {
        "tc_hawkeye_ciphertext": repo.enc_json(record), "routing.tc_hawkeye": summary, "routing.answeredBy": summary["answeredBy"]}})
    return record


_ESTABLISHED = ("concern", "anomaly", "clear", "weak")


async def established(owner: str, case_id: str, limit: int = 4) -> list[str]:
    """What TC Hawkeye established about this case, word for word from its check record: live facts only (never ApolloSG
    knowledge, never what a lookup didn't find), warning signs first. Kept and shown when Magnum DI couldn't finish."""
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "tc_hawkeye_ciphertext": 1})
    if not stored or not stored.get("tc_hawkeye_ciphertext"):
        return []
    facts = [f for c in repo.dec_json(stored["tc_hawkeye_ciphertext"]).get("checks") or [] for f in c.get("facts") or []
             if f.get("class") == "live_evidence" and f.get("signal") in _ESTABLISHED and str(f.get("text") or "").strip()]
    facts.sort(key=lambda f: _ESTABLISHED.index(f["signal"]))
    return list(dict.fromkeys(str(f["text"]).strip() for f in facts))[:limit]


async def discard_response(owner: str, case: dict) -> None:
    """TC Hawkeye's composed result failed Apollo's validation: Magnum DI takes the case instead, with TC Hawkeye's
    brief and with web search on, since TC Hawkeye's conclusion can't be relied on."""
    case_id = case["case_id"]
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "tc_hawkeye_ciphertext": 1})
    if not stored or not stored.get("tc_hawkeye_ciphertext"):
        return
    record = repo.dec_json(stored["tc_hawkeye_ciphertext"])
    checks = [Check.from_wire(c) for c in record["checks"]]
    whole = [{"capability": "reasoning", "evidenceIds": [], "checkId": None,
              "text": "TC Hawkeye's own result didn't pass Apollo's validation, so investigate the whole case."}]
    brief = report.magnum_brief(checks, whole, official.unread_sections(case.get("triage_provider_evidence")), record.get("pattern"), record.get("floor"),
                                record.get("crossSource"), record.get("history"))
    record["items"]["brief"] = await _item(owner, case, BRIEF_ITEM_ID, brief, "TC Hawkeye brief for Magnum DI")
    record.update(response=None, decision=None, magnumSearch=True, issues=None)
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {
        "tc_hawkeye_ciphertext": repo.enc_json(record), "routing.answeredBy": "magnum_di", "routing.tc_hawkeye.resolved": False,
        "routing.tc_hawkeye.magnumNeeded": True, "routing.tc_hawkeye.magnumSearch": True, "routing.tc_hawkeye.answeredBy": "magnum_di"}})
