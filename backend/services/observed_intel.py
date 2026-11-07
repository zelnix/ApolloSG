"""ApolloSG's cross-device intelligence (part of the KB, server-side only): what independent ApolloSG findings say about a
website, phone number, email address, message or file, kept as one-way codes and per-device marks, never content.

The owner's rules:
- Cases never cross device boundaries. Another device's case is never sent to, shown on, named on or reconstructable on
  this one. A device receives only an approved, privacy-safe derived assertion (`assertion`): known malicious (High
  confidence), suspected malicious (Medium confidence) or mixed previous reports — never a count of devices, never that
  another device or person encountered it, never a case, a time or a verdict of anyone else's.
- Server-side consensus: each device's latest qualifying finding about a subject is one mark — supporting (a concern
  outcome), contradicting (a complete check that found no scam indicators), inconclusive (unable to determine) or
  insufficient evidence (part of the evidence couldn't be checked) — with whether it was independent and when.
  Unanimous means no contradicting mark exists; one contradicting mark removes unanimity at once (every assertion is
  worked out from the marks when it is read). Inconclusive and insufficient marks never break unanimity and are kept
  apart. A disputed subject asserts only "mixed previous reports", and only once THRESHOLD independent reports exist.
- No artificial consensus: a finding made while ApolloSG already asserted something about that subject to the case
  (`kbAsserted` in the TC Hawkeye record: the cross-source record in Magnum DI's brief, or the history notes beside the
  result) is recorded as dependent and never counts as independent confirmation of the same assertion; a device's
  dependent finding never replaces its own earlier independent one. So Case A → assertion → Case B can never grow it.
- A device's own marks are never part of the assertion it receives (`exclude`): its own cases are its related cases.

Stored in ApolloSG's own indicator store (`threat_indicators`, source `apollosg-observed`):
- scope `observed`: one subject, as a one-way code (a website as `domain:<code>`). A website's name is stored readably
  only once THRESHOLD independent devices support it, because by then it is a pattern rather than one person's material.
- scope `observed_relation`: two websites, numbers or addresses that appeared together in supporting material.
- Each device is a mark made from the subject and the device together, so a device can't be followed from one subject to
  another. Marks older than WINDOW are dropped.

What is recorded: the subjects of a finished, non-simulated case, except an organisation's own or official address, a
shared platform, a free mail provider's domain, or a number on the Official Organisation Directory.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
from datetime import datetime, timedelta, timezone

from core.db import db, now_utc

log = logging.getLogger("apollo.observed")

SOURCE = "apollosg-observed"
THRESHOLD = 3          # independent supporting devices, unanimous: a High-confidence assertion
MEDIUM = 2             # independent supporting devices, unanimous: a Medium-confidence assertion
WINDOW = timedelta(days=30)
CONCERN_OUTCOMES = ("likely_scam", "scam", "concerning", "confirmed_threat")
STANCES = ("supporting", "contradicting", "inconclusive", "insufficient")
MAX_SUBJECTS = 6
# The only words a device is ever given about ApolloSG's previous reports (never "KB", never "cases", never a count).
LABEL = "ApolloSG's previous reports"
SAID = {"known_malicious": "has been previously reported as malicious — High confidence",
        "suspected_malicious": "has been previously reported as concerning — Medium confidence",
        "mixed": "has mixed previous reports"}
SUPPORTING = ("known_malicious", "suspected_malicious")


def subject(kind: str, value: str) -> tuple[str, str | None] | None:
    """(one-way key, readable name or None) for a website, phone number, email address, message or file that may be recorded."""
    from services import org_directory, threat_feeds
    from services.higgins.brand_domains import owner, registrable
    from services.higgins.tc_flyby.triage import FREE_MAIL
    from services.reusable_intel import fingerprint, subject_key
    value = (value or "").strip()
    if not value:
        return None
    if kind in ("message", "file"):
        # A content digest (SHA-256) made on this server from the message text or the file's bytes: coded again here.
        digest = value.lower()
        return (f"{kind}:{fingerprint(f'observed-{kind}|' + digest)}", None) if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) else None
    if kind == "domain":
        host = threat_feeds.norm_host(value.split("//")[-1].split("/")[0].split("@")[-1].split(":")[0])
        domain = registrable(host)
        if "." not in domain or threat_feeds.restricted(domain) or owner(domain) or domain in FREE_MAIL:
            return None
        return f"domain:{fingerprint('observed-domain|' + domain)}", domain
    if kind == "phone":
        return (None if org_directory.phone_owner(value) else (subject_key("phone", value), None))
    if kind == "email":
        domain = value.lower().split("@")[-1]
        # A free mail address is one person's account (a scammer's Gmail): it may be recorded. Organisations' own are never.
        if org_directory.email_owner(value) or (domain not in FREE_MAIL and (owner(domain) or threat_feeds.restricted(domain))):
            return None
        return subject_key("email", value), None
    return None


def _mark(key: str, device: str) -> str:
    return hashlib.sha256(f"observed|{key}|{device}".encode()).hexdigest()[:24]


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def tally(marks: list[dict], *, now: datetime, own: str | None = None) -> dict:
    """The consensus in the window, leaving out `own` (a mark): independent supporting marks, dependent ones, the other
    stances, unanimity and the latest supporting time. Server-side only — never sent to a device."""
    out = {**{s: 0 for s in STANCES}, "dependent": 0, "lastSupporting": None}
    for m in marks:
        if now - _aware(m["at"]) > WINDOW or (own and m["m"] == own):
            continue
        stance = m.get("s", "supporting")
        if stance == "supporting" and not m.get("i", True):
            out["dependent"] += 1
            continue
        out[stance] += 1
        if stance == "supporting" and (out["lastSupporting"] is None or _aware(m["at"]) > out["lastSupporting"]):
            out["lastSupporting"] = _aware(m["at"])
    out["unanimous"] = out["contradicting"] == 0
    return out


async def _add(scope: str, key: str, device: str, now: datetime, fields: dict, *, stance: str = "supporting", independent: bool = True) -> int:
    """Set this device's mark on one subject (or relation); returns the independent supporting devices in the window."""
    doc = await db.threat_indicators.find_one({"scope": scope, "key": key, "source": SOURCE}, {"_id": 0, "marks": 1})
    mark = _mark(key, device)
    kept = [m for m in (doc or {}).get("marks") or [] if now - _aware(m["at"]) <= WINDOW]
    mine = next((m for m in kept if m["m"] == mark), None)
    if stance == "supporting" and not independent and mine and mine.get("s", "supporting") == "supporting" and mine.get("i", True):
        new = mine   # this device already confirmed it independently; a dependent repeat never replaces that
    else:
        new = {"m": mark, "at": now, "s": stance, "i": independent}
    marks = [m for m in kept if m["m"] != mark] + [new]
    t = tally(marks, now=now)
    supporting = t["supporting"]
    revealed = {"hostname": fields.get("readable") or ""} if supporting >= THRESHOLD else {"hostname": ""}
    await db.threat_indicators.update_one({"scope": scope, "key": key, "source": SOURCE}, {
        "$set": {"marks": marks, "devices_30d": supporting, "consensus": {s: t[s] for s in (*STANCES, "dependent")}, "unanimous": t["unanimous"],
                 "last_verified_at": now, "evidence_expiry_deadline": now + WINDOW, "status": "active", "updated_at": now,
                 "review_status": "auto_verified", "threat_type": "OBSERVED_CONCERN",
                 "original_evidence": f"Independent ApolloSG findings in the window: {supporting} supporting, {t['contradicting']} contradicting",
                 **{k: v for k, v in fields.items() if k != "readable"}, **revealed},
        "$setOnInsert": {"indicator_id": "obs-" + hashlib.sha256(f"{scope}|{key}".encode()).hexdigest()[:24], "source": SOURCE,
                         "first_seen_at": now, "added_at": now, "added_by": "observed", "original_scope": scope}}, upsert=True)
    return supporting


def _subjects_of(record: dict) -> list[tuple[str, str, str | None]]:
    """(kind, key, readable) for each website, number, address, message and file in a TC Hawkeye record."""
    entities = {}
    for check in record.get("checks") or []:
        entities.setdefault({"link": "domain", "phone": "phone", "email": "email"}.get(check["kind"], ""), []).append(check["subject"])
    out, seen = [], set()
    for kind in ("domain", "phone", "email"):
        for value in entities.get(kind, []):
            found = subject(kind, value)
            if found and found[0] not in seen:
                seen.add(found[0])
                out.append((kind, found[0], found[1]))
    for extra in record.get("observedExtra") or []:
        found = subject(extra["kind"], extra["value"])
        if found and found[0] not in seen:
            seen.add(found[0])
            out.append((extra["kind"], found[0], None))
    return out[:MAX_SUBJECTS]


def stance_of(outcome: str | None, completion: str | None) -> str | None:
    if outcome in CONCERN_OUTCOMES:
        return "supporting"
    if outcome in ("not_scam", "no_scam_indicators"):
        return "contradicting" if completion == "complete" else "insufficient"
    if outcome == "unable_to_determine":
        return "inconclusive" if completion == "complete" else "insufficient"
    return None


async def record_case(owner: str, case_id: str, outcome: str | None, *, simulated: bool = False, completion: str | None = "complete") -> int:
    """Set this device's mark on each of a finished case's subjects (and, when supporting, how they appeared together).
    Returns the subjects recorded. Intelligence never reaches TC Hawkeye's checks, so a case's own evidence (or Magnum DI's
    reasoning) made its outcome; only the subjects ApolloSG asserted something about to this case are dependent."""
    stance = stance_of(outcome, completion)
    if not stance or simulated:
        return 0
    from services.higgins import repository as repo
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "tc_flyby_ciphertext": 1, "observed_at": 1})
    if not stored or not stored.get("tc_flyby_ciphertext") or stored.get("observed_at"):
        return 0
    record = repo.dec_json(stored["tc_flyby_ciphertext"])
    # Asserted by the KB while this case ran → not independent confirmation of that same assertion.
    asserted = set(record.get("kbAsserted") or [])
    now = now_utc()
    subjects = _subjects_of(record)
    for kind, key, readable in subjects:
        await _add("observed", key, owner, now, {"subject_kind": kind, "readable": readable}, stance=stance, independent=key not in asserted)
    if stance == "supporting":
        # Seen together (a possible campaign): websites, numbers and addresses only.
        linked = [s for s in subjects if s[0] in ("domain", "phone", "email")]
        for (ka, a, ra), (kb, b, rb) in itertools.combinations(sorted(linked, key=lambda s: s[1]), 2):
            await _add("observed_relation", f"rel:{hashlib.sha256(f'{a}|{b}'.encode()).hexdigest()[:32]}", owner, now,
                       {"a_key": a, "b_key": b, "a_kind": ka, "b_kind": kb, "a_name": ra, "b_name": rb},
                       independent=not (a in asserted or b in asserted))
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id}, {"$set": {"observed_at": now}})
    return len(subjects)


async def _doc(kind: str, value: str) -> dict | None:
    found = subject(kind, value)
    if not found:
        return None
    return await db.threat_indicators.find_one({"scope": "observed", "key": found[0], "source": SOURCE, "status": "active",
                                                "evidence_expiry_deadline": {"$gt": now_utc()}}, {"_id": 0})


async def assertion(kind: str, value: str, *, exclude: str | None = None) -> dict | None:
    """The only thing a device may receive about a subject in its own case: {level, confidence, key (a one-way code,
    server-side only)} — "known_malicious"/high (THRESHOLD or more independent supporting findings, unanimous),
    "suspected_malicious"/medium (MEDIUM or more, unanimous), or "mixed"/None (supporting and contradicting findings, at
    least THRESHOLD independent ones together). Thin consensus asserts nothing. `exclude` is the asking device: its own
    cases are its related cases, never part of this assertion. Never a count, a time or another device's verdict."""
    doc = await _doc(kind, value)
    if not doc:
        return None
    t = tally(doc.get("marks") or [], now=now_utc(), own=_mark(doc["key"], exclude) if exclude else None)
    if t["unanimous"]:
        if t["supporting"] >= THRESHOLD:
            return {"level": "known_malicious", "confidence": "high", "key": doc["key"]}
        if t["supporting"] >= MEDIUM:
            return {"level": "suspected_malicious", "confidence": "medium", "key": doc["key"]}
        return None
    if t["supporting"] and t["supporting"] + t["contradicting"] >= THRESHOLD:
        return {"level": "mixed", "confidence": None, "key": doc["key"]}
    return None


async def related(kind: str, value: str) -> list[dict]:
    """Subjects that appeared together with this one in supporting material on THRESHOLD or more independent devices:
    {key, kind, name}. Never how many."""
    found = subject(kind, value)
    if not found:
        return []
    rows = await db.threat_indicators.find({"scope": "observed_relation", "source": SOURCE, "status": "active", "devices_30d": {"$gte": THRESHOLD},
                                            "evidence_expiry_deadline": {"$gt": now_utc()}, "$or": [{"a_key": found[0]}, {"b_key": found[0]}]},
                                           {"_id": 0, "a_key": 1, "b_key": 1, "a_kind": 1, "b_kind": 1, "a_name": 1, "b_name": 1, "devices_30d": 1}).to_list(10)
    out = []
    for row in rows:
        side = "b" if row["a_key"] == found[0] else "a"
        out.append({"key": row[f"{side}_key"], "kind": row[f"{side}_kind"], "name": row.get(f"{side}_name")})
    return out


async def purge() -> int:
    result = await db.threat_indicators.update_many(
        {"source": SOURCE, "status": "active", "evidence_expiry_deadline": {"$lte": now_utc()}},
        {"$set": {"status": "expired", "withdrawal_reason": "expired_unverified", "marks": [], "hostname": ""}})
    removed = await db.threat_indicators.delete_many({"source": SOURCE, "status": "expired", "updated_at": {"$lt": now_utc() - timedelta(days=90)}})
    return result.modified_count + removed.deleted_count


async def summary() -> dict:
    """Counts and the patterns at or above the threshold, for the admin portal. No content."""
    now = now_utc()
    base = {"source": SOURCE, "status": "active", "evidence_expiry_deadline": {"$gt": now}}
    subjects = await db.threat_indicators.find({**base, "scope": "observed", "devices_30d": {"$gte": THRESHOLD}},
                                               {"_id": 0, "subject_kind": 1, "hostname": 1, "key": 1, "devices_30d": 1, "first_seen_at": 1,
                                                "last_verified_at": 1, "consensus": 1, "unanimous": 1}).sort("devices_30d", -1).to_list(50)
    campaigns = await db.threat_indicators.find({**base, "scope": "observed_relation", "devices_30d": {"$gte": THRESHOLD}},
                                                {"_id": 0, "a_kind": 1, "b_kind": 1, "a_name": 1, "b_name": 1, "a_key": 1, "b_key": 1,
                                                 "devices_30d": 1, "last_verified_at": 1}).sort("devices_30d", -1).to_list(50)
    return {"tracked": await db.threat_indicators.count_documents({**base, "scope": "observed"}),
            "atThreshold": await db.threat_indicators.count_documents({**base, "scope": "observed", "devices_30d": {"$gte": THRESHOLD}}),
            "campaigns": campaigns, "subjects": subjects, "threshold": THRESHOLD, "windowDays": WINDOW.days}


async def ensure_indexes() -> None:
    await db.threat_indicators.create_index([("scope", 1), ("key", 1), ("source", 1)])
    await db.threat_indicators.create_index([("scope", 1), ("a_key", 1)])
    await db.threat_indicators.create_index([("scope", 1), ("b_key", 1)])
