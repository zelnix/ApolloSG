"""Related history for a case: what THIS device's own earlier cases, and ApolloSG's previous reports, say about the
same link, number, email address, message, file or organisation. Context, never evidence.

The owner's rules:
- Devices are mutually exclusive. ApolloSG runs only on this device and has no relationship to any other, even one the
  same person owns. A related case is always one of this device's own cases (owner_id == device_id); another device's
  case is never shown, named or counted here. Cross-device intelligence comes only through ApolloSG's previous reports
  (services/observed_intel.assertion), in its approved words: a statement and its confidence ("has been previously
  reported as malicious — High confidence") or "has mixed previous reports" — never which device, how many, when, or
  anyone's case or verdict.
- Related cases are an earlier case on this device with the same website or link, phone number or email address, the
  same message or file, the same organisation named, or one already linked to this case as connected events.
- History never becomes evidence for the current case: it is never a finding, a warning sign or a corroboration, and it
  never changes the outcome, attention, actions or what isn't certain. It only adds weight to what the case's own
  evidence already found: when the case's own outcome is a concern and the history agrees (an earlier concern on this
  device, or a previous report of malicious or concerning), each finding about that same subject that supports the
  outcome moves one confidence step up (low → medium → high), once, however many notes agree. Mixed previous reports
  never agree. Each note lists the findings it raised, so where the extra weight came from stays visible.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.config import URL_HMAC_SECRET
from core.db import db, now_utc
from services.higgins import outcomes
from services.higgins.brand_domains import registrable
from services.higgins.contracts import HigginsResponse, HistoryNote

log = logging.getLogger("apollo.history")

KEEP = timedelta(days=90)
MAX_NOTES = 8
CONCERN = ("likely_scam", "scam", "concerning", "confirmed_threat")
CONCERN_STATES = ("growling", "barking", "biting")
STEP = {"low": "medium", "medium": "high", "high": "high"}
DEVICE_SOURCE = "This device's own cases"
# What each kind of subject is called on screen, and the most specific relation first.
NOUN = {"website": "link", "number": "number", "email": "email address", "message": "message", "file": "file", "organisation": "organisation"}
ORDER = ("message", "file", "website", "number", "email", "organisation")
# observed_intel's kind for each subject it records.
OBSERVED_KIND = {"website": "domain", "number": "phone", "email": "email", "message": "message", "file": "file"}
_FILES = ("image", "document", "attachment", "audio")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")[-9:]


def _text_digest(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text or "").strip().lower().encode()).hexdigest()


def subjects(plan_, texts: dict[str, str], rows: list[dict]) -> list[dict]:
    """The case's subjects, once each: {match, value (normalised, never shown), label (as the material wrote it)}."""
    out: list[dict] = []
    for check in plan_.checks:
        if check.kind == "link":
            out.append({"match": "website", "value": registrable(check.subject.lower()), "label": check.subject})
        elif check.kind == "phone" and len(_digits(check.subject)) >= 8:
            out.append({"match": "number", "value": _digits(check.subject), "label": check.subject})
        elif check.kind == "email":
            out.append({"match": "email", "value": check.subject.strip().lower(), "label": check.subject})
        elif check.kind == "impersonation" and check.subject:
            out.append({"match": "organisation", "value": re.sub(r"[^a-z0-9]", "", check.subject.lower()), "label": check.subject})
    by_id = {r["evidence_id"]: r for r in rows}
    for eid, text in texts.items():
        row = by_id.get(eid) or {}
        if row.get("kind") == "text" and row.get("origin") == "user_submission" and not row.get("parent_id") and len(text.strip()) >= 20:
            out.append({"match": "message", "value": _text_digest(text), "label": None})
    for row in rows:
        if row.get("kind") in _FILES and row.get("origin") == "user_submission" and row.get("integrity_hash"):
            out.append({"match": "file", "value": row["integrity_hash"].lower(), "label": None})
    seen, unique = set(), []
    for s in out:
        if s["value"] and (s["match"], s["value"]) not in seen:
            seen.add((s["match"], s["value"]))
            unique.append(s)
    return unique


def device_key(owner: str, subject: dict) -> str:
    """A one-way code for a subject on THIS device: the same subject on two devices gives two unrelated codes."""
    return hmac.new(URL_HMAC_SECRET.encode(), f"case-history|{owner}|{subject['match']}|{subject['value']}".encode(), hashlib.sha256).hexdigest()[:32]


def observed_subjects(subs: list[dict]) -> list[dict]:
    """The message and file subjects ApolloSG may record in its previous reports (its websites, numbers and
    addresses come from the TC FlyBy checks themselves)."""
    return [{"kind": s["match"], "value": s["value"]} for s in subs if s["match"] in ("message", "file")]


def _iso(value) -> Optional[str]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return value or None


def _named(subject: dict) -> str:
    noun = NOUN[subject["match"]]
    return f"this {noun}, {subject['label']}," if subject.get("label") else f"this {noun}"


def _cap(text: str) -> str:
    return text[0].upper() + text[1:]


def _note(kind: str, match: str, text: str, source: str, agrees: bool, **extra) -> dict:
    return {"kind": kind, "match": match, "text": text, "source": source, "agrees": agrees, **{k: v for k, v in extra.items() if v}}


async def _previously_reported(owner: str, subs: list[dict]) -> list[dict]:
    """ApolloSG's previous reports on the case's subjects, in the approved words only (observed_intel.SAID): a statement
    and its confidence, or "mixed previous reports" — never which device, how many, when, or anyone's case. A note
    that agrees carries the subject's one-way code (`key`, server-side only) so the case's own finding is recorded as
    dependent on it (no artificial consensus)."""
    from services import observed_intel, threat_feeds
    notes = []
    for s in subs:
        kind = OBSERVED_KIND.get(s["match"])
        if not kind:
            continue
        value = s["label"] if kind in ("domain", "phone", "email") else s["value"]
        said = await observed_intel.assertion(kind, value, exclude=owner)
        if said:
            agrees = said["level"] in observed_intel.SUPPORTING
            notes.append(_note("previously_encountered", s["match"], f"{_cap(_named(s))} {observed_intel.SAID[said['level']]}.",
                               observed_intel.LABEL, agrees, subject=s.get("label"), key=said["key"] if agrees else None))
        if kind not in ("domain", "phone", "email") or (said and said["level"] == "mixed"):
            continue
        for other in await observed_intel.related(kind, value):
            listed = await threat_feeds.matches(other["name"]) if other["kind"] == "domain" and other.get("name") else []
            lists = list(dict.fromkeys(threat_feeds.LISTINGS[threat_feeds.BY_ID[m["source"]].listing][0] for m in listed))
            if lists:
                notes.append(_note("previously_encountered", s["match"],
                                   f"{_cap(_named(s))} has been previously reported together with {other['name']}, which "
                                   f"{' and '.join(lists)} lists — High confidence.", observed_intel.LABEL, True,
                                   subject=s.get("label"), key=(observed_intel.subject(kind, value) or (None,))[0]))
    return notes


def asserted(notes: list[dict]) -> list[str]:
    """The one-way codes of the subjects ApolloSG's previous reports asserted something about to this case."""
    return [n["key"] for n in notes if n.get("key")]


def _related_text(subject: dict, outcome: Optional[str]) -> str:
    result = f" Its result: {outcomes.LABELS[outcome]}." if outcome in outcomes.LABELS else ""
    if subject["match"] in ("message", "file"):
        return f"An earlier case on this device had the same {NOUN[subject['match']]}.{result}"
    if subject["match"] == "organisation":
        return f"An earlier case on this device named the same organisation, {subject['label']}.{result}"
    return f"An earlier case on this device involved the same {NOUN[subject['match']]}, {subject['label']}.{result}"


async def current_event(owner: str, case: dict) -> Optional[dict]:
    """This case's own Patrol event on this device, when it has one."""
    ors = [{"investigation_case_id": case["case_id"]}] + ([{"event_id": case["client_submission_id"]}] if case.get("client_submission_id") else [])
    return await db.patrol_events.find_one({"device_id": owner, "$or": ors}, {"_id": 0, "event_id": 1, "scent_id": 1})


async def _related_cases(owner: str, case: dict, subs: list[dict], current: Optional[dict]) -> list[dict]:
    keys = {device_key(owner, s): s for s in subs}
    notes, seen_events = [], {(current or {}).get("event_id")}
    if keys:
        docs = await db.device_case_history.find({"owner_id": owner, "keys": {"$in": list(keys)}, "case_id": {"$ne": case["case_id"]},
                                                  "expires_at": {"$gt": now_utc()}}, {"_id": 0}).sort("at", -1).to_list(20)
        for doc in docs:
            if doc.get("event_id") in seen_events:
                continue
            matched = sorted((keys[k] for k in doc["keys"] if k in keys), key=lambda s: ORDER.index(s["match"]))
            subject = matched[0]
            seen_events.add(doc.get("event_id"))
            notes.append(_note("related_case", subject["match"], _related_text(subject, doc.get("outcome")), DEVICE_SOURCE,
                               doc.get("outcome") in CONCERN, subject=subject.get("label"), eventId=doc.get("event_id"),
                               at=_iso(doc.get("at")), outcome=doc.get("outcome")))
    if current and current.get("scent_id"):
        async for e in db.patrol_events.find({"device_id": owner, "scent_id": current["scent_id"], "event_id": {"$ne": current["event_id"]}},
                                             {"_id": 0, "event_id": 1, "occurred_at": 1, "state": 1}).sort("occurred_at", -1).limit(10):
            if e["event_id"] in seen_events:
                continue
            seen_events.add(e["event_id"])
            notes.append(_note("related_case", "connected", "An earlier event on this device is connected to this one.", DEVICE_SOURCE,
                               e.get("state") in CONCERN_STATES, eventId=e["event_id"], at=_iso(e.get("occurred_at"))))
    return notes


async def gather(owner: str, case: dict, subs: list[dict]) -> list[dict]:
    """Every history note for the case, from this device's own cases and ApolloSG's previous reports. A lookup
    that fails leaves its notes out; history is context, so it never breaks an investigation."""
    notes: list[dict] = []
    try:
        current = await current_event(owner, case)
        notes += await _related_cases(owner, case, subs, current)
    except Exception:  # noqa: BLE001
        log.warning("history_related_failed case=%s", case["case_id"], exc_info=True)
    try:
        notes += await _previously_reported(owner, subs)
    except Exception:  # noqa: BLE001
        log.warning("history_observed_failed case=%s", case["case_id"], exc_info=True)
    return notes[:MAX_NOTES]


def brief_lines(notes: list[dict]) -> str:
    """The history in Magnum DI's brief, each note with where it came from."""
    return "\n".join(f"- [{n['source']}] {n['text']}" + (f" ({n['at'][:10]})" if n.get("at") else "") for n in notes)


# ── Adding weight (at commit, after the result validated) ─────────────────────
def _supports(text: str, outcome: str) -> bool:
    from services.higgins.explain import facts
    return facts.structure_finding({"text": text}, {}, outcome)["stance"] != "contrary"


def _about(text: str, note: dict) -> bool:
    """The finding is about the note's subject. A shared message, file or connected event is the whole case."""
    match, subject, low = note["match"], (note.get("subject") or "").lower(), text.lower()
    if match in ("message", "file", "connected"):
        return True
    if not subject:
        return False
    if match == "website":
        return subject in low or registrable(subject) in low
    if match == "number":
        return bool(_digits(subject)) and _digits(subject) in re.sub(r"\D", "", text)
    return subject in low   # an email address, or the organisation's name


def weigh(response: HigginsResponse, notes: list[dict]) -> HigginsResponse:
    """The result with its history beside it. Agreeing history raises the confidence of the concern findings about the
    same subject one step; nothing else in the result changes."""
    if not notes:
        return response
    concern = response.outcome in CONCERN
    raised: set[str] = set()
    shown = []
    for n in notes:
        ids = [f.id for f in response.findings if concern and n["agrees"] and _about(f.text, n) and _supports(f.text, response.outcome)]
        raised.update(ids)
        shown.append(HistoryNote(kind=n["kind"], match=n["match"], text=n["text"], source=n["source"], agrees=n["agrees"],
                                 subject=n.get("subject"), event_id=n.get("eventId"), at=n.get("at"), outcome=n.get("outcome"),
                                 finding_ids=ids))
    findings = [f.model_copy(update={"confidence": STEP[f.confidence]}) if f.id in raised else f for f in response.findings]
    return response.model_copy(update={"findings": findings, "history": shown})


async def record(owner: str, case: dict, outcome: Optional[str], keys: list[str]) -> None:
    """Keep this case in this device's own history: one-way codes of its subjects, its result and when — never content.
    Only this device ever reads it back; it goes when the device's data is deleted, and after KEEP."""
    if not outcome or not keys:
        return
    current = await current_event(owner, case)
    now = now_utc()
    await db.device_case_history.update_one({"owner_id": owner, "case_id": case["case_id"]}, {
        "$set": {"keys": keys, "outcome": outcome, "event_id": (current or {}).get("event_id") or case.get("client_submission_id"),
                 "updated_at": now, "expires_at": now + KEEP},
        "$setOnInsert": {"owner_id": owner, "case_id": case["case_id"], "at": case.get("created_at") or now}}, upsert=True)


async def ensure_indexes() -> None:
    await db.device_case_history.create_index([("owner_id", 1), ("case_id", 1)], unique=True)
    await db.device_case_history.create_index([("owner_id", 1), ("keys", 1)])
    await db.device_case_history.create_index("expires_at", expireAfterSeconds=0)
