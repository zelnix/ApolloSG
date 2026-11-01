"""Family sharing: pairing with a code, shared events, acks, incidents and text notes."""
from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.config import logger
from core.db import db, now_utc
from core.models import ApolloState, PatrolEvent
from routers.push import PUSH_FAMILY, PUSH_THREAT, send_push

router = APIRouter()


async def notify_guardians(event: PatrolEvent) -> None:
    """A Barking or Biting alert reaches the family devices paired with a code (in-app and push). There is no email."""
    try:
        links = await db.family_links.find({"protected_device_id": event.device_id, "deleted_at": None}).to_list(10)
        # fan out to paired guardian devices (in-app + push)
        for ln in links:
            await db.shared_events.update_one({"event_id": event.event_id, "guardian_device_id": ln["guardian_device_id"]}, {"$set": {
                "event_id": event.event_id, "guardian_device_id": ln["guardian_device_id"], "protected_device_id": event.device_id, "from_label": ln.get("owner_name") or "Family member",
                "state": event.state, "headline": event.headline, "what_to_do": event.what_to_do, "indicator_host": event.indicator_host, "occurred_at": event.occurred_at, "created_at": now_utc()}}, upsert=True)
        if links:
            who = links[0].get("owner_name") or "A family member"
            verb = "needs to be careful" if event.state == "barking" else "was protected"
            try:
                await send_push(
                    recipients=[ln["guardian_device_id"] for ln in links][:100],
                    data={"title": f"ApolloSG: {who} {verb}", "message": event.headline, "subtext": "Tap to see the alert and call them.", "action_url": f"/family/alert/{event.event_id}", **PUSH_THREAT},
                    idempotency_key=f"guardian-{event.event_id}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("guardian push failed (non-blocking): %s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        logger.warning("guardian notify failed: %s", type(exc).__name__)


class PairRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    owner_name: str = Field(default="", max_length=60)


class LinkRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")
    guardian_name: str = Field(default="", max_length=40)  # how the protected person will see this watcher


# A pairing code is 6 random digits, works once, and expires after 15 minutes. Only a device's newest code works.
PAIR_CODE_MINUTES = 15
# Wrong codes a device may try in that window before linking pauses, so the codes can't be guessed.
PAIR_LINK_MAX_MISSES = 5


_PHONE_OK = set("+0123456789 ()-")


def _clean_phone(p: str) -> str:
    p = p.strip()
    if p and (any(ch not in _PHONE_OK for ch in p) or sum(ch.isdigit() for ch in p) < 6):
        raise HTTPException(status_code=400, detail="Enter a valid phone number")
    return p


@router.post("/family/pair")
async def create_pair_code(body: PairRequest):
    now = now_utc()
    # A new code replaces this device's earlier ones.
    await db.pair_codes.update_many({"protected_device_id": body.device_id, "used": False}, {"$set": {"used": True, "replaced_at": now}})
    while True:  # never the same digits as another code that still works
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not await db.pair_codes.find_one({"code": code, "used": False, "expires_at": {"$gt": now}}, {"_id": 1}):
            break
    expires = now + timedelta(minutes=PAIR_CODE_MINUTES)
    await db.pair_codes.insert_one({"code": code, "protected_device_id": body.device_id, "owner_name": body.owner_name, "created_at": now, "expires_at": expires, "used": False})
    return {"code": code, "expires_at": expires, "expires_in_minutes": PAIR_CODE_MINUTES}


@router.post("/family/link")
async def link_device(body: LinkRequest):
    now = now_utc()
    window = now - timedelta(minutes=PAIR_CODE_MINUTES)
    if await db.pair_link_misses.count_documents({"device_id": body.device_id, "at": {"$gt": window}}) >= PAIR_LINK_MAX_MISSES:
        raise HTTPException(status_code=429, detail="Too many wrong codes. Wait 15 minutes, then ask for a new code.")
    pc = await db.pair_codes.find_one({"code": body.code, "used": False})
    if not pc or pc["expires_at"].replace(tzinfo=timezone.utc) < now:
        await db.pair_link_misses.delete_many({"device_id": body.device_id, "at": {"$lte": window}})
        await db.pair_link_misses.insert_one({"device_id": body.device_id, "at": now})
        raise HTTPException(status_code=404, detail="That code didn't work. It may have expired — ask for a new one.")
    if pc["protected_device_id"] == body.device_id:
        raise HTTPException(status_code=400, detail="You can't link a device to itself")
    await db.pair_codes.update_one({"_id": pc["_id"]}, {"$set": {"used": True}})
    await db.family_links.update_one({"protected_device_id": pc["protected_device_id"], "guardian_device_id": body.device_id},
                                     {"$set": {"protected_device_id": pc["protected_device_id"], "guardian_device_id": body.device_id, "owner_name": pc.get("owner_name", ""), "created_at": now_utc(), "deleted_at": None,
                                               "lifecycle_generation": uuid.uuid4().hex,
                                               **({"guardian_label": body.guardian_name.strip()} if body.guardian_name.strip() else {})}}, upsert=True)
    return {"linked": True, "owner_name": pc.get("owner_name", "")}


class WatcherNameIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=40)


@router.put("/family/links/{link_id}/name")
async def rename_watcher(link_id: str, body: WatcherNameIn):
    """A guardian sets/changes how they appear on the protected person's phone ("Sarah", "Dad")."""
    try:
        oid = ObjectId(link_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Unknown pairing.")
    r = await db.family_links.update_one({"_id": oid, "guardian_device_id": body.device_id, "deleted_at": None}, {"$set": {"guardian_label": body.name.strip()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Unknown pairing.")
    return {"name": body.name.strip()}


class PhoneIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)  # caller (guardian)
    protected_device_id: str = Field(min_length=8, max_length=64)
    phone: str = Field(default="", max_length=24)


@router.post("/family/links/phone")
async def set_link_phone(body: PhoneIn):
    """Watcher edits/adds the number they call for a person they watch (overrides the owner-supplied one)."""
    phone = _clean_phone(body.phone)
    r = await db.family_links.update_one({"protected_device_id": body.protected_device_id, "guardian_device_id": body.device_id, "deleted_at": None}, {"$set": {"guardian_phone": phone}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"phone": phone}


def _link_phone(ln: dict[str, Any]) -> str:
    return ln.get("guardian_phone") or ln.get("owner_phone") or ""


@router.get("/family/links")
async def list_links(device_id: str = Query(min_length=8, max_length=64)):
    protecting = await db.family_links.find({"guardian_device_id": device_id, "deleted_at": None}).to_list(20)
    watched_by = await db.family_links.find({"protected_device_id": device_id, "deleted_at": None}).to_list(20)
    # `watching_me` stays a count for compatibility; `watchers` lists each paired device (label + since, never its id) so the
    # protected person can remove one. `link_id` is the handle for DELETE /family/links/{link_id}.
    return {
        "i_watch": [{"link_id": str(l["_id"]), "owner_name": l.get("owner_name", ""), "protected_device_id": l["protected_device_id"], "phone": _link_phone(l), "since": l["created_at"], "my_label": l.get("guardian_label") or ""} for l in protecting],
        "watching_me": len(watched_by),
        "watchers": [{"link_id": str(l["_id"]), "guardian_label": l.get("guardian_label") or "A family member", "since": l["created_at"], "last_checkin_at": l.get("last_checkin_at")} for l in watched_by],
    }


@router.delete("/family/links/{link_id}", status_code=204)
async def unlink_device(link_id: str, device_id: str = Query(min_length=8, max_length=64)):
    """Either side may end a pairing: the protected person removes a watcher, or a guardian stops watching.
    Soft delete — the other device simply stops receiving fan-outs, pushes and weekly rollups (all filter deleted_at=None)."""
    try:
        oid = ObjectId(link_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Unknown pairing.")
    r = await db.family_links.update_one(
        {"_id": oid, "deleted_at": None, "$or": [{"protected_device_id": device_id}, {"guardian_device_id": device_id}]},
        {"$set": {"deleted_at": now_utc(), "unlinked_by": device_id}},
    )
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Unknown pairing.")
    link = await db.family_links.find_one({"_id": oid}, {"protected_device_id": 1, "guardian_device_id": 1})
    if link:  # the relationship ended
        from services.family_assist.sessions import revoke_for_relationship
        await revoke_for_relationship(link_id)
        await db.incident_notes.update_many({"protected_device_id": link["protected_device_id"], "guardian_device_id": link["guardian_device_id"]},
                                            {"$set": {"lifecycle_revoked_at": now_utc()}})
    return Response(status_code=204)


@router.get("/family/shared-events")
async def shared_events(device_id: str = Query(min_length=8, max_length=64)):
    docs = await db.shared_events.find({"guardian_device_id": device_id}).sort("occurred_at", -1).to_list(100)
    links = {l["protected_device_id"]: l for l in await db.family_links.find({"guardian_device_id": device_id, "deleted_at": None}).to_list(20)}
    return [{**{k: v for k, v in d.items() if k != "_id"}, "phone": _link_phone(links.get(d.get("protected_device_id", ""), {}))} for d in docs]


class AckIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)  # guardian device
    reply: Literal["called", "messaged", "visiting", "noted"] = "called"


ACK_LABEL = {"called": "I called them", "messaged": "I messaged them", "visiting": "I'm visiting them", "noted": "Noted, no action needed"}


@router.post("/family/shared-events/{event_id}/ack")
async def ack_shared_event(event_id: str, body: AckIn):
    """Guardian Reply: the family member marks how they responded; both sides see it."""
    se = await db.shared_events.find_one({"event_id": event_id, "guardian_device_id": body.device_id})
    if not se:
        raise HTTPException(status_code=404, detail="Alert not found")
    ts = now_utc()
    await db.shared_events.update_one({"_id": se["_id"]}, {"$set": {"acknowledged_at": ts, "ack_label": ACK_LABEL[body.reply]}})
    ev = await db.patrol_events.find_one({"event_id": event_id})
    # A threat the person sent themselves may never have reached the server's event list: the shared copy names them.
    owner = (ev or {}).get("device_id") or se.get("protected_device_id")
    if owner:
        guardian_label = await _label_of(body.device_id, owner)
        headline = (ev or se)["headline"]
        await db.family_acks.update_one({"event_id": event_id, "guardian_device_id": body.device_id}, {"$set": {
            "event_id": event_id, "protected_device_id": owner, "guardian_device_id": body.device_id,
            "guardian_label": guardian_label, "ack_label": ACK_LABEL[body.reply], "headline": headline, "acknowledged_at": ts}}, upsert=True)
        try:
            await send_push(
                recipients=[owner],
                data={"title": f"{guardian_label} replied: {ACK_LABEL[body.reply]}", "message": headline, "action_url": "/family", **PUSH_FAMILY},
                idempotency_key=f"ack-{event_id}-{body.device_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ack push failed (non-blocking): %s", type(exc).__name__)
    return {"acknowledged": True, "ack_label": ACK_LABEL[body.reply]}


async def _label_of(member_id: str, viewer_id: str) -> str:
    """How `member_id` appears to `viewer_id` across their family link, in either direction."""
    ln = await db.family_links.find_one({"protected_device_id": viewer_id, "guardian_device_id": member_id, "deleted_at": None})
    if ln:
        return ln.get("guardian_label") or "A family member"
    ln = await db.family_links.find_one({"protected_device_id": member_id, "guardian_device_id": viewer_id, "deleted_at": None})
    return (ln or {}).get("owner_name") or "A family member"


# Family Reply Notes — on a threat someone shared, their family member sends a quick note straight back to that
# person's phone. Two calm presets or their own words (short; the composer reminds them never to send codes).
THREAT_NOTE_TEXT = {"calling": "I'm calling you now.", "wait": "Don't do anything yet. Don't reply, pay or tap anything until we've talked."}


class ThreatNoteIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)  # the family member's device
    kind: Literal["calling", "wait", "custom"]
    text: str = Field(default="", max_length=140)


@router.post("/family/shared-events/{event_id}/notes", status_code=201)
async def add_threat_note(event_id: str, body: ThreatNoteIn):
    se = await db.shared_events.find_one({"event_id": event_id, "guardian_device_id": body.device_id})
    if not se:
        raise HTTPException(status_code=404, detail="Alert not found")
    text = " ".join(body.text.split()) if body.kind == "custom" else THREAT_NOTE_TEXT[body.kind]
    if not text:
        raise HTTPException(status_code=422, detail="Write a short note first.")
    if await db.threat_notes.count_documents({"event_id": event_id, "guardian_device_id": body.device_id}) >= 20:
        raise HTTPException(status_code=429, detail="That's a lot of notes on one alert. A call may help more.")
    owner = se["protected_device_id"]
    label = await _label_of(body.device_id, owner)
    ts = now_utc()
    note = {"note_id": uuid.uuid4().hex, "event_id": event_id, "protected_device_id": owner, "guardian_device_id": body.device_id,
            "guardian_label": label, "kind": body.kind, "text": text, "created_at": ts}
    await db.threat_notes.insert_one(dict(note))
    # Also the latest answer in the person's "Family responses to your alerts" list.
    await db.family_acks.update_one({"event_id": event_id, "guardian_device_id": body.device_id}, {"$set": {
        "event_id": event_id, "protected_device_id": owner, "guardian_device_id": body.device_id, "guardian_label": label,
        "ack_label": text, "headline": se.get("headline", ""), "acknowledged_at": ts}}, upsert=True)
    try:
        await send_push(recipients=[owner],
                        data={"title": f"{label}: {text}", "message": se.get("headline", ""), "action_url": f"/patrol/{event_id}", **PUSH_FAMILY},
                        idempotency_key=f"threat-note-{note['note_id']}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("threat note push failed (non-blocking): %s", type(exc).__name__)
    return note


@router.get("/family/shared-events/{event_id}/notes")
async def list_threat_notes(event_id: str, device_id: str = Query(min_length=8, max_length=64)):
    """The person sees every family member's notes on their threat; a family member sees only the notes they sent."""
    docs = await db.threat_notes.find({"event_id": event_id, "$or": [{"protected_device_id": device_id}, {"guardian_device_id": device_id}]}).sort("created_at", 1).to_list(50)
    return [{k: v for k, v in d.items() if k != "_id"} for d in docs]


# ---------------------------------------------------------------------------
# Family Incident Sharing — the protected person explicitly shares ONE incident (Threat Scent timeline + the
# combined Stay With Me plan and tick progress) with paired guardians. Minimal fields only; no message text.
# ---------------------------------------------------------------------------

class SharedIncidentEvent(BaseModel):
    event_id: str = Field(max_length=64)
    category: str = Field(max_length=20)
    state: ApolloState
    headline: str = Field(max_length=200)
    occurred_at: str = Field(max_length=40)
    status: str = Field(default="active", max_length=20)


class SharedIncidentStep(BaseModel):
    id: str = Field(max_length=40)
    text: str = Field(max_length=400)


class ShareIncidentIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    scent_id: str = Field(min_length=4, max_length=64)
    headline: str = Field(max_length=200)
    state: ApolloState
    events: list[SharedIncidentEvent] = Field(max_length=30)
    steps: list[SharedIncidentStep] = Field(max_length=30)
    done: list[str] = Field(default_factory=list, max_length=30)
    note: str = Field(default="", max_length=300)


class IncidentProgressIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    done: list[str] = Field(default_factory=list, max_length=30)
    resolved: bool = False


def _incident_out(d: dict[str, Any], links: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {**{k: v for k, v in d.items() if k != "_id"}, "phone": _link_phone(links.get(d.get("protected_device_id", ""), {}))}


@router.post("/family/incidents/share")
async def share_incident(body: ShareIncidentIn):
    links = await db.family_links.find({"protected_device_id": body.device_id, "deleted_at": None}).to_list(10)
    ts = now_utc()
    for ln in links:
        await db.shared_incidents.update_one({"scent_id": body.scent_id, "guardian_device_id": ln["guardian_device_id"]}, {"$set": {
            "scent_id": body.scent_id, "guardian_device_id": ln["guardian_device_id"], "protected_device_id": body.device_id,
            "from_label": ln.get("owner_name") or "Family member", "headline": body.headline, "state": body.state,
            "events": [e.model_dump() for e in body.events], "steps": [s.model_dump() for s in body.steps], "done": body.done, "note": body.note,
            "resolved": False, "shared_at": ts, "updated_at": ts}}, upsert=True)
    if links:
        who = links[0].get("owner_name") or "A family member"
        try:
            await send_push(recipients=[ln["guardian_device_id"] for ln in links][:100],
                            data={"title": f"Higgins: {who} is asking for your help", "message": body.headline, "subtext": "Do have a look at what happened and the steps they're working through.", "action_url": f"/family/incident/{body.scent_id}", **PUSH_THREAT},
                            idempotency_key=f"incident-{body.scent_id}-{ts.isoformat()[:16]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("incident push failed (non-blocking): %s", type(exc).__name__)
    return {"shared_with": len(links)}


@router.patch("/family/incidents/{scent_id}/progress")
async def incident_progress(scent_id: str, body: IncidentProgressIn):
    r = await db.shared_incidents.update_many({"scent_id": scent_id, "protected_device_id": body.device_id}, {"$set": {"done": body.done, "resolved": body.resolved, "updated_at": now_utc()}})
    return {"updated": r.matched_count}


@router.get("/family/incidents")
async def list_shared_incidents(device_id: str = Query(min_length=8, max_length=64)):
    docs = await db.shared_incidents.find({"guardian_device_id": device_id}).sort("updated_at", -1).to_list(50)
    links = {l["protected_device_id"]: l for l in await db.family_links.find({"guardian_device_id": device_id, "deleted_at": None}).to_list(20)}
    return [_incident_out(d, links) for d in docs]


@router.get("/family/incidents/{scent_id}")
async def get_shared_incident(scent_id: str, device_id: str = Query(min_length=8, max_length=64)):
    d = await db.shared_incidents.find_one({"scent_id": scent_id, "guardian_device_id": device_id})
    if not d:
        raise HTTPException(status_code=404, detail="Incident not found")
    links = {l["protected_device_id"]: l for l in await db.family_links.find({"guardian_device_id": device_id, "deleted_at": None}).to_list(20)}
    return _incident_out(d, links)


# Family Reassurance Note — a guardian sends a short "I'm here" note back onto a shared incident. Preset kinds
# keep it calm and quick; a custom line is capped short. Never carries passwords/codes (protected user is told so).
NOTE_TEXT = {"here": "I'm here — call me when you're ready.", "calling": "I'm calling you now.", "on_way": "I'm on my way over.", "together": "Don't worry, we'll sort this out together."}


class IncidentNoteIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)  # guardian device
    kind: Literal["here", "calling", "on_way", "together", "custom"] = "here"
    text: str = Field(default="", max_length=140)
    from_name: str = Field(default="", max_length=40)
    phone: str = Field(default="", max_length=32)  # guardian's call-back number, optional


@router.post("/family/incidents/{scent_id}/notes", status_code=201)
async def add_incident_note(scent_id: str, body: IncidentNoteIn):
    inc = await db.shared_incidents.find_one({"scent_id": scent_id, "guardian_device_id": body.device_id})
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    text = body.text.strip() if body.kind == "custom" else NOTE_TEXT[body.kind]
    if not text:
        raise HTTPException(status_code=422, detail="Write a short note first.")
    link_q = {"guardian_device_id": body.device_id, "protected_device_id": inc["protected_device_id"], "deleted_at": None}
    link = await db.family_links.find_one(link_q)
    from_name, phone = body.from_name.strip(), re.sub(r"[^+\d ]", "", body.phone).strip()
    remember = {k: v for k, v in (("guardian_label", from_name), ("guardian_phone", phone)) if v}
    if remember and link:
        await db.family_links.update_one({"_id": link["_id"]}, {"$set": remember})
    guardian_label = from_name or (link or {}).get("guardian_label") or "A family member"
    phone = phone or (link or {}).get("guardian_phone", "")
    note = {"note_id": uuid.uuid4().hex, "scent_id": scent_id, "protected_device_id": inc["protected_device_id"], "guardian_device_id": body.device_id,
            "guardian_label": guardian_label, "kind": body.kind, "text": text, "phone": phone, "created_at": now_utc()}
    await db.incident_notes.insert_one(dict(note))
    try:
        await send_push(recipients=[inc["protected_device_id"]],
                        data={"title": f"{guardian_label}: {text}", "message": inc["headline"], "action_url": f"/patrol/scent/{scent_id}", **PUSH_FAMILY},
                        idempotency_key=f"note-{note['note_id']}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("note push failed (non-blocking): %s", type(exc).__name__)
    return note


@router.get("/family/incidents/{scent_id}/notes")
async def list_incident_notes(scent_id: str, device_id: str = Query(min_length=8, max_length=64)):
    """Protected user sees every guardian's notes; a guardian sees only the notes they sent."""
    docs = await db.incident_notes.find({"scent_id": scent_id, "$or": [{"protected_device_id": device_id}, {"guardian_device_id": device_id}]}).sort("created_at", 1).to_list(50)
    return [{k: v for k, v in d.items() if k not in ("_id", "audio_path")} for d in docs]


# Family Weekly Check-In — a calm, count-only summary of a watched person's week. Uses the event summaries the

@router.get("/family/acks")
async def list_acks(device_id: str = Query(min_length=8, max_length=64)):
    docs = await db.family_acks.find({"protected_device_id": device_id}).sort("acknowledged_at", -1).to_list(50)
    return [{k: v for k, v in d.items() if k != "_id"} for d in docs]


# --------------------------------------------------------------------------- Scam alert sharing (family, in-app)
class ShareScamAlertIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    url: str = Field(min_length=8, max_length=2000)


async def _family_recipients(device_id: str) -> list[tuple[str, str]]:
    """Every linked family device in either direction, with how the sender appears to that recipient."""
    out: dict[str, str] = {}
    for ln in await db.family_links.find({"protected_device_id": device_id, "deleted_at": None}).to_list(50):
        out.setdefault(ln["guardian_device_id"], ln.get("owner_name") or "A family member")
    for ln in await db.family_links.find({"guardian_device_id": device_id, "deleted_at": None}).to_list(50):
        out.setdefault(ln["protected_device_id"], ln.get("guardian_label") or "A family member")
    return list(out.items())


@router.post("/family/scam-alerts/share")
async def share_scam_alert(body: ShareScamAlertIn):
    """Send an official-source scam alert to linked family. Alert facts are taken from Apollo's own
    official-source snapshot — never from the client — so nothing unverified can be forwarded."""
    from services import government_alerts
    snap = await government_alerts.snapshot(100)
    alert = next((a for a in [*(snap.get("alerts") or []), *(snap.get("emerging") or [])] if a.get("url") == body.url), None)
    if not alert:
        raise HTTPException(status_code=404, detail="This alert is no longer listed by ApolloSG's official sources.")
    recipients = await _family_recipients(body.device_id)
    ts = now_utc()
    for rid, label in recipients:
        await db.shared_scam_alerts.update_one({"url": body.url, "recipient_device_id": rid, "sender_device_id": body.device_id}, {"$set": {
            "url": body.url, "recipient_device_id": rid, "sender_device_id": body.device_id, "from_label": label,
            "title": alert.get("title", ""), "severity": alert.get("severity", "LOW"), "region_label": alert.get("regionLabel", ""),
            "source": alert.get("source", ""), "date_label": alert.get("dateLabel", ""), "shared_at": ts}}, upsert=True)
    if recipients:
        from urllib.parse import quote
        try:
            await send_push(recipients=[rid for rid, _ in recipients][:100],
                            data={"title": "Higgins: scam alert from your family", "message": alert.get("title", ""), "subtext": "Tap to see what to look for and how to stay safe.",
                                  "action_url": f"/higgins/scam/{quote(body.url, safe='')}", **PUSH_FAMILY},
                            idempotency_key=f"scam-share-{body.device_id}-{secrets.token_hex(4)}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("scam alert share push failed (non-blocking): %s", type(exc).__name__)
    return {"shared_with": len(recipients)}


@router.get("/family/scam-alerts")
async def list_shared_scam_alerts(device_id: str = Query(min_length=8, max_length=64)):
    linked = {rid for rid, _ in await _family_recipients(device_id)}
    docs = await db.shared_scam_alerts.find({"recipient_device_id": device_id}, {"_id": 0}).sort("shared_at", -1).to_list(50)
    return [{k: v for k, v in d.items() if k != "sender_device_id"} for d in docs if d.get("sender_device_id") in linked]



# --------------------------------------------------------------------------- Send a threat to family (in-app)
class ShareThreatIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    event_id: str = Field(min_length=8, max_length=64)
    state: ApolloState
    # The same room a Patrol record has (core/models.PatrolEventIn): the summary is sent whole, never cut short.
    result: str = Field(min_length=1, max_length=200)
    headline: str = Field(min_length=1, max_length=1000)
    what_happened: str = Field(default="", max_length=6000)
    what_to_do: str = Field(default="", max_length=2000)
    involved_label: Optional[Literal["Website", "Number"]] = None
    involved: Optional[str] = Field(default=None, max_length=253)
    case_ref: str = Field(default="", max_length=40)
    occurred_at: datetime


@router.post("/family/threats/share")
async def share_threat(body: ShareThreatIn):
    """The person sends one threat's short summary to their linked family: the result, what happened, what to do and
    the website or number involved. The original message, its links and pictures never leave the phone."""
    if bool(body.involved_label) != bool(body.involved):
        raise HTTPException(status_code=422, detail="Say what was involved together with whether it's a website or a number.")
    recipients = await _family_recipients(body.device_id)
    ts = now_utc()
    for rid, label in recipients:
        await db.shared_events.update_one({"event_id": body.event_id, "guardian_device_id": rid}, {
            "$set": {"event_id": body.event_id, "guardian_device_id": rid, "protected_device_id": body.device_id, "from_label": label,
                     "state": body.state, "result": body.result, "headline": body.headline, "what_happened": body.what_happened,
                     "what_to_do": body.what_to_do, "involved_label": body.involved_label, "involved": body.involved,
                     "indicator_host": body.involved if body.involved_label == "Website" else None,
                     "case_ref": body.case_ref, "occurred_at": body.occurred_at, "shared_by_owner": True, "shared_at": ts},
            # Sent again, it's a fresh ask: the family member can answer it again.
            "$unset": {"acknowledged_at": "", "ack_label": ""},
            "$setOnInsert": {"created_at": ts}}, upsert=True)
        try:
            await send_push(recipients=[rid],
                            data={"title": f"{label} sent you a threat to look at", "message": body.headline,
                                  "subtext": "Tap to see what happened and what to do.", "action_url": f"/family/alert/{body.event_id}", **PUSH_FAMILY},
                            idempotency_key=f"threat-share-{body.event_id}-{rid}-{ts.isoformat()[:16]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("threat share push failed (non-blocking): %s", type(exc).__name__)
    return {"shared_with": len(recipients)}
