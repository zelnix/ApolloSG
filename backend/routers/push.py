"""Alert notification boundary (spec §10A push protocol).

Delivery goes through Apollo's managed push relay: the app registers the device's native FCM/APNs token, the relay
resolves tokens from the installation id at send time, and no device token is ever stored here. Permission,
registration and delivery remain separate states. Every send is one durable delivery per (owner, event, channel,
recipient) with a payload digest and attempt history. A queued request, an accepted relay response and a visible
notification are separate outcomes; nothing is reported "sent" without a registered recipient and an accepted
response, and a timeout after send is `outcome_unknown` until retried — never a definite non-delivery.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core.config import logger
from core.db import db, now_utc
from core.models import PatrolEvent
from routers.devices import device_quiet_until
from services.notification_text import owner_alert_summary, present_push

router = APIRouter()

# Sound routing — Android channel id MUST match a channel the app actually creates
# (src/push/notifications.ts). Android silently drops a notification addressed to a channel that
# does not exist or has been deleted, so the consolidated "apollo_alerts" channel is the only
# destination for Apollo's own alerts; Family Help keeps its separate channel. `sound` is the iOS
# filename for the same intent (the channel owns the sound on Android 8+).
APOLLO_ALERTS_CHANNEL = "apollo_alerts"
PUSH_THREAT = {"channel_id": APOLLO_ALERTS_CHANNEL, "sound": "apollo_bark.wav"}   # Apollo barks: threat alerts (owner + family)
PUSH_FAMILY = {"channel_id": "family", "sound": "apollo_chime.wav"}               # softer chime: family replies
PUSH_GROWL = {"channel_id": APOLLO_ALERTS_CHANNEL, "sound": None}

PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "")
# The build pipeline replaces the placeholder with the real key when the app is published, so before
# that the channel is honestly "not configured" rather than silently failing on every send.
PUSH_KEY_PLACEHOLDER = PUSH_KEY.strip().lower() in ("", "placeholder")
# Billing/consent states on the owner's Emergent account. Not transient: retrying is pointless until
# the owner acts, so they are recorded as the failure reason instead of being retried in a loop.
BILLING_CODES = ("insufficient_credits", "integration_disabled", "daily_limit_reached")

DeliveryState = Literal["queued", "submitted", "provider_accepted", "device_observed", "failed", "outcome_unknown"]

_client = httpx.AsyncClient(base_url=PUSH_BASE_URL, headers={"X-Push-Key": PUSH_KEY}, timeout=15.0)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """Mongo returns naive UTC datetimes; without the offset the app would read them as local time."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def push_configured() -> bool:
    return not PUSH_KEY_PLACEHOLDER


def push_setup_detail() -> str:
    return ("Alerts that arrive while ApolloSG is closed are switched on when the app is published and built — the managed "
            "alert key is filled in by the build pipeline (EMERGENT_PUSH_KEY). Until then no notification is sent.")



async def ensure_indexes() -> None:
    await db.push_registrations.create_index([("device_id", 1)], unique=True)
    await db.push_deliveries.create_index([("owner_id", 1), ("event_key", 1), ("channel", 1), ("recipient_id", 1)], unique=True)
    await db.push_deliveries.create_index([("delivery_id", 1)], unique=True)
    await db.push_deliveries.create_index([("state", 1), ("updated_at", 1)])
    await db.push_deliveries.create_index([("recipient_id", 1), ("created_at", -1)])
    await db.held_alerts.create_index([("device_id", 1), ("send_after", 1)])


# ------------------------------------------------------------------ registration
class RegisterPushBody(BaseModel):
    platform: Literal["android", "ios"]
    # The device's native FCM/APNs token. The relay resolves it from the installation id at send
    # time, so it is forwarded once and never stored here.
    device_token: str = Field(min_length=8, max_length=4096)

    model_config = {"populate_by_name": True}


@router.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody, request: Request):
    """Registers the calling installation for alerts. Ownership is the authenticated device; a body user_id cannot choose it."""
    if not push_configured():
        raise HTTPException(503, push_setup_detail())
    owner = request.state.device["device_id"]
    try:
        resp = await _client.post("/api/v1/push/users/register", json={"user_id": owner, "platform": body.platform, "device_token": body.device_token})
    except httpx.HTTPError:
        raise HTTPException(502, "ApolloSG's alert service could not be reached, so this device is not registered for alerts yet.")
    if resp.status_code == 401:
        raise HTTPException(503, "ApolloSG's managed alert key is missing or invalid, so this device cannot be registered for alerts.")
    if resp.status_code >= 500:
        raise HTTPException(502, "ApolloSG's alert service is unavailable, so this device is not registered for alerts yet.")
    if resp.status_code >= 400:
        raise HTTPException(422, "ApolloSG's alert service rejected this device token.")
    existing = await db.push_registrations.find_one({"device_id": owner}, {"_id": 0, "registration_id": 1})
    registration_id = existing["registration_id"] if existing else str(uuid.uuid4())
    registered_at = now_utc()
    await db.push_registrations.update_one(
        {"device_id": owner},
        {"$set": {"registration_id": registration_id, "platform": body.platform, "provider": "emergent", "registered_at": registered_at},
         "$unset": {"token": "", "project_id": ""}},  # tokens live in the relay, never in Apollo's database
        upsert=True)
    return {"registered": True, "provider": "emergent", "registrationId": registration_id, "registeredAt": registered_at.isoformat()}


async def _registrations(recipients: list[str]) -> dict[str, dict]:
    return {r["device_id"]: r async for r in db.push_registrations.find({"device_id": {"$in": recipients}}, {"_id": 0})}


# ------------------------------------------------------------------ deliveries
def _status(row: dict) -> dict:
    return {"deliveryId": row["delivery_id"], "channel": "push", "state": row["state"], "retryable": row.get("retryable", False),
            "failureCode": row.get("failure_code"), "updatedAt": _iso(row["updated_at"])}


def _relay_data(data: dict, event_key: Optional[str] = None) -> dict:
    """The relay's data contract. Fields it types as strings must be omitted rather than sent as null —
    a null value makes the provider reject the request outright (this is what failed every weekly
    family alert with HTTP 400 while Apollo sent `subtitle: null`)."""
    out = {"title": data["title"], "message": data["message"], "channel_id": data.get("channel_id") or APOLLO_ALERTS_CHANNEL}
    for key in ("subtext", "action_url", "sound", "image_url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value
    # The alert key rides along in the deep link so a tap on the phone can be recorded against this
    # exact alert — the only honest proof that it arrived.
    if event_key and isinstance(out.get("action_url"), str):
        out["action_url"] = f"{out['action_url']}{'&' if '?' in out['action_url'] else '?'}a={event_key}"
    return out


async def _set(delivery_id: str, state: DeliveryState, *, failure_code: Optional[str] = None, retryable: bool = False, extra: Optional[dict] = None) -> None:
    attempt = {"at": now_utc(), "state": state, "failureCode": failure_code, **(extra or {})}
    await db.push_deliveries.update_one({"delivery_id": delivery_id}, {"$set": {"state": state, "failure_code": failure_code, "retryable": retryable, "updated_at": now_utc(), **(extra or {})},
                                                                     "$push": {"attempts": attempt}})


async def _trigger(recipients: list[str], data: dict, idempotency_key: str, attempt: int = 0) -> httpx.Response:
    """One relay trigger, retrying only the 'same key still in flight' answer (which is not a failure)."""
    payload = {"recipients": recipients, "data": _relay_data(data, idempotency_key), "$idempotency_key": idempotency_key}
    resp = await _client.post("/api/v1/push/trigger", json=payload)
    if resp.status_code == 409 and attempt < 3 and _code(resp) == "idempotency_key_in_progress":
        await asyncio.sleep(3)
        return await _trigger(recipients, data, idempotency_key, attempt + 1)
    return resp


def _code(resp: httpx.Response) -> str:
    if not resp.headers.get("content-type", "").startswith("application/json"):
        return ""
    try:
        return (resp.json() or {}).get("code", "") or ""
    except ValueError:
        return ""


async def send_push(recipients: list[str], data: dict, idempotency_key: Optional[str] = None, owner_id: Optional[str] = None) -> list[dict]:
    """Queues and submits one durable delivery per recipient. Returns DeliveryStatus rows (possibly empty when nobody is registered).
    Raises 503 when the channel is not configured. Never claims success from an empty or error response."""
    if not recipients:
        return []
    if len(recipients) > 100:
        raise ValueError("max 100 recipients per send; chunk before sending")
    if "title" not in data or "message" not in data:
        raise ValueError("data must include title and message")
    # The one presentation boundary for every push: entities decoded once, text fitted to the OS.
    data = present_push(data)
    if not push_configured():
        raise HTTPException(503, push_setup_detail())
    event_key = idempotency_key or f"adhoc-{uuid.uuid4()}"
    owner = owner_id or recipients[0]
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    registrations = await _registrations(recipients)
    rows: list[dict] = []
    for recipient in recipients:
        if recipient not in registrations:
            continue  # unregistered destinations produce no delivery; callers that need one recipient check `recipient_unregistered`
        row = {"delivery_id": str(uuid.uuid4()), "owner_id": owner, "event_key": event_key, "channel": "push", "recipient_id": recipient,
               "payload_digest": digest, "state": "queued", "retryable": True, "failure_code": None, "attempts": [], "ticket_id": None, "receipt": None,
               # Kept so the person can later see WHAT Apollo sent, not just that something was sent.
               "title": data["title"], "action_url": data.get("action_url"), "opened_at": None,
               "created_at": now_utc(), "updated_at": now_utc()}
        try:
            await db.push_deliveries.insert_one(row)
        except DuplicateKeyError:
            existing = await db.push_deliveries.find_one({"owner_id": owner, "event_key": event_key, "channel": "push", "recipient_id": recipient}, {"_id": 0})
            if existing and existing["payload_digest"] != digest:
                logger.warning("push delivery %s reused with a different payload; original retained", existing["delivery_id"])
            if existing and existing["state"] in ("failed", "outcome_unknown") and existing.get("retryable"):
                row = existing  # bounded retry of the same logical delivery
            else:
                rows.append(existing or row)
                continue
        rows.append(row)
    to_send = [r for r in rows if r["state"] in ("queued", "failed", "outcome_unknown") and r.get("retryable", True) and len(r.get("attempts", [])) < 5]
    if not to_send:
        return [_status(r) for r in rows]
    for r in to_send:
        await _set(r["delivery_id"], "submitted")

    async def finish() -> list[dict]:
        return [_status(await db.push_deliveries.find_one({"delivery_id": r["delivery_id"]}, {"_id": 0})) for r in rows]

    try:
        resp = await _trigger([r["recipient_id"] for r in to_send], data, event_key)
    except httpx.TimeoutException:
        for r in to_send:  # the request may have reached the relay: unknown until retried, not a definite failure
            await _set(r["delivery_id"], "outcome_unknown", failure_code="provider_timeout", retryable=True)
        return await finish()
    except httpx.HTTPError:
        for r in to_send:
            await _set(r["delivery_id"], "failed", failure_code="provider_unreachable", retryable=True)
        return await finish()

    code = _code(resp)
    if code in BILLING_CODES:
        # The owner's account, not the device: say so plainly in the ledger and stop — a retry loop
        # would only repeat the refusal. Sends resume on their own once the owner acts.
        logger.warning("push paused: %s (%s)", code, resp.status_code)
        for r in to_send:
            await _set(r["delivery_id"], "failed", failure_code=code, retryable=False)
        return await finish()
    if resp.status_code == 401:
        for r in to_send:
            await _set(r["delivery_id"], "failed", failure_code="push_key_invalid", retryable=False)
        return await finish()
    if resp.status_code >= 400:
        for r in to_send:
            await _set(r["delivery_id"], "failed", failure_code=code or f"provider_http_{resp.status_code}", retryable=resp.status_code >= 500)
        return await finish()
    # Accepted by the relay. That is a hand-off, not a sighting: the delivery stays "provider_accepted"
    # and is never reported as seen on the device.
    for r in to_send:
        await _set(r["delivery_id"], "provider_accepted")
    return await finish()


@router.get("/push/deliveries/{delivery_id}")
async def get_delivery(delivery_id: str, request: Request):
    owner = request.state.device["device_id"]
    row = await db.push_deliveries.find_one({"delivery_id": delivery_id, "$or": [{"owner_id": owner}, {"recipient_id": owner}]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Unknown delivery.")
    return _status(row)


@router.get("/push/registration")
async def get_registration(request: Request):
    """Registration state for the calling installation (separate from the OS notification permission)."""
    owner = request.state.device["device_id"]
    row = await db.push_registrations.find_one({"device_id": owner}, {"_id": 0, "registration_id": 1, "registered_at": 1, "platform": 1, "provider": 1})
    return {"configured": push_configured(), "registered": bool(row), "registrationId": row["registration_id"] if row else None,
            "registeredAt": _iso(row["registered_at"]) if row else None, "provider": row.get("provider") if row else None,
            "setupDetail": None if push_configured() else push_setup_detail()}


class PushTestIn(BaseModel):
    device_id: Optional[str] = Field(default=None, min_length=8, max_length=64)  # ignored: the authenticated installation is the recipient


@router.post("/push/test", status_code=202)
async def push_test(request: Request, body: Optional[PushTestIn] = None):
    """Sample bark so people can hear and see exactly what a threat alert looks like. 202 DeliveryStatus when queued;
    409 recipient_unregistered when this installation has no registration; 503 when the channel is not configured."""
    owner = request.state.device["device_id"]
    if not push_configured():
        raise HTTPException(503, push_setup_detail())
    if not await db.push_registrations.find_one({"device_id": owner}, {"_id": 1}):
        return JSONResponse({"detail": "This installation has no push registration yet. Allow notifications and let ApolloSG register, then try again.",
                             "error": {"code": "recipient_unregistered", "message": "This installation has no push registration yet. Allow notifications and let ApolloSG register, then try again."}}, status_code=409)
    statuses = await send_push(recipients=[owner], owner_id=owner,
                               data={"title": "Apollo is barking (test)", "message": "Higgins: This is what a threat alert looks like. A real alert names the concern and the evidence.",
                                     "subtext": "Higgins: No action needed — this is a test.", "action_url": "/settings", **PUSH_THREAT},
                               idempotency_key=f"test-{owner}-{int(now_utc().timestamp())}")
    if not statuses:
        return JSONResponse({"detail": "No registered destination for this installation.",
                             "error": {"code": "recipient_unregistered", "message": "No registered destination for this installation."}}, status_code=409)
    return JSONResponse(statuses[0], status_code=202)


async def push_owner_alert(event: PatrolEvent, *, briefing=None, source: dict | None = None) -> None:
    """Tell the protected person the moment Apollo barks/bites while the app is closed.
    Growling is a non-urgent nudge → held until the quiet window ends rather than dropped.
    Respects per-category notification preferences: barking/biting always send;
    sniffing/growling can be disabled by the user. `briefing` / `source`: the case's Higgins Case Briefing and its
    recorded source identifiers, so the push names the same finding and subject the app shows."""
    try:
        # Map event state to notification category
        if event.state in ("barking", "biting"):
            category = event.state
        else:
            category = "sniffing_growling"

        # Check user's notification preference for this category
        if not await should_send_category(event.device_id, category):
            logger.info("push suppressed by preference: device=%s category=%s", event.device_id[:8], category)
            return

        # A purpose-built short summary — the full Higgins explanation stays in the Threat Case.
        message = owner_alert_summary(event, briefing=briefing, source=source)
        if event.state in ("growling", "sniffing", "ears_up"):
            verb = "Apollo is sniffing" if event.state == "sniffing" else "Apollo is growling"
            data = {"title": verb, "message": message, "action_url": f"/patrol/{event.event_id}", **PUSH_GROWL}
            quiet_until = await device_quiet_until(event.device_id)
            if quiet_until:
                await hold_until_morning(event.device_id, data, quiet_until, f"owner-{event.event_id}")
                return
        else:
            verb = "Apollo is barking" if event.state == "barking" else "Apollo is biting"
            data = {"title": verb, "message": message, "action_url": f"/patrol/{event.event_id}", **PUSH_THREAT}
        await send_push(recipients=[event.device_id], data=data, idempotency_key=f"owner-{event.event_id}", owner_id=event.device_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("owner push failed (non-blocking): %s", type(exc).__name__)


# ------------------------------------------------------------------ quiet hours: held, not dropped
async def hold_until_morning(device_id: str, data: dict, send_after: datetime, event_key: str) -> None:
    """A gentle alert raised during quiet hours waits for the window to end instead of being dropped.
    Each held alert is sent separately when the window ends, in the order it was raised."""
    await db.held_alerts.update_one(
        {"device_id": device_id, "event_key": event_key},
        {"$setOnInsert": {"hold_id": str(uuid.uuid4()), "device_id": device_id, "event_key": event_key, "data": data,
                          "send_after": send_after, "created_at": now_utc(), "sent_at": None}},
        upsert=True)
    logger.info("growling alert held until the quiet window ends")


async def release_held_alerts(at: Optional[datetime] = None, limit: int = 100) -> int:
    """Send the alerts whose quiet window has now ended — one notification each, oldest first."""
    at = at or now_utc()
    due = [r async for r in db.held_alerts.find({"sent_at": None, "send_after": {"$lte": at}}, {"_id": 0}).sort("created_at", 1).limit(limit)]
    sent = 0
    for row in due:
        try:
            await send_push(recipients=[row["device_id"]], data=row["data"], idempotency_key=row["event_key"], owner_id=row["device_id"])
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("held alert release failed (non-blocking): %s", type(exc).__name__)
        # Marked either way: a held alert is released once, and a failure is recorded in the delivery
        # ledger rather than being retried here forever.
        await db.held_alerts.update_one({"hold_id": row["hold_id"]}, {"$set": {"sent_at": now_utc()}})
    return sent


# ------------------------------------------------------------------ what Apollo sent, and what became of it
@router.get("/push/alerts")
async def list_alerts(request: Request, limit: int = Query(default=30, ge=1, le=100)):
    """Every alert Apollo sent to this installation and what became of it. States are the real ones:
    queued/submitted (on its way), provider_accepted (handed to the delivery service), failed (with the
    reason), outcome_unknown (never confirmed either way), plus alerts still held for the morning.
    Being accepted is not proof it was seen — only `openedAt` says it was tapped on this phone."""
    owner = request.state.device["device_id"]
    rows = [r async for r in db.push_deliveries.find({"recipient_id": owner}, {"_id": 0}).sort("created_at", -1).limit(limit)]
    alerts = [{"alertKey": r["event_key"], "title": r.get("title") or "Apollo alert", "state": r["state"],
               "failureCode": r.get("failure_code"), "sentAt": _iso(r["created_at"]),
               "updatedAt": _iso(r["updated_at"]), "openedAt": _iso(r.get("opened_at"))}
              for r in rows]
    held = [h async for h in db.held_alerts.find({"device_id": owner, "sent_at": None}, {"_id": 0}).sort("created_at", -1).limit(limit)]
    alerts.extend({"alertKey": h["event_key"], "title": (h.get("data") or {}).get("title") or "Apollo alert", "state": "held",
                   "failureCode": None, "sentAt": _iso(h["created_at"]), "updatedAt": _iso(h["created_at"]),
                   "heldUntil": _iso(h["send_after"]), "openedAt": None} for h in held)
    alerts.sort(key=lambda a: a["sentAt"], reverse=True)
    return alerts[:limit]


@router.post("/push/alerts/{alert_key}/opened")
async def mark_alert_opened(alert_key: str, request: Request):
    """The person tapped this alert on this phone — the only honest proof it actually arrived."""
    owner = request.state.device["device_id"]
    result = await db.push_deliveries.update_one({"event_key": alert_key, "recipient_id": owner, "opened_at": None},
                                                 {"$set": {"opened_at": now_utc(), "updated_at": now_utc()}})
    return {"recorded": result.modified_count > 0}



# ------------------------------------------------------------------ notification categories & preferences
# Five categories. Barking and Biting are always on (cannot be disabled).
# Sniffing & Growling, New Scam Alerts, and New Learn with Higgins are user-configurable.
NOTIFICATION_CATEGORIES = [
    {"id": "barking", "label": "Barking", "description": "Active threats that need your immediate attention", "always_on": True},
    {"id": "biting", "label": "Biting", "description": "Confirmed protective blocks Apollo has enforced", "always_on": True},
    {"id": "sniffing_growling", "label": "Sniffing & Growling", "description": "Cases needing your attention, with a link straight to the case", "always_on": False},
    {"id": "scam_alerts", "label": "New Scam Alerts", "description": "New scam advisories from official sources", "always_on": False},
    {"id": "learn_with_higgins", "label": "Learn with Higgins", "description": "New learning content from Higgins", "always_on": False},
]

DEFAULT_PREFS = {"sniffing_growling": True, "scam_alerts": True, "learn_with_higgins": True}


async def _get_notification_prefs(device_id: str) -> dict:
    """Read this device's notification preferences. Missing = all enabled."""
    doc = await db.devices.find_one({"device_id": device_id}, {"settings.notification_preferences": 1})
    return {**DEFAULT_PREFS, **((doc or {}).get("settings", {}).get("notification_preferences") or {})}


async def should_send_category(device_id: str, category: str) -> bool:
    """Whether this device wants to receive notifications for the given category.
    Barking and Biting always return True."""
    if category in ("barking", "biting"):
        return True
    prefs = await _get_notification_prefs(device_id)
    return bool(prefs.get(category, True))


class NotificationPrefsIn(BaseModel):
    sniffing_growling: Optional[bool] = None
    scam_alerts: Optional[bool] = None
    learn_with_higgins: Optional[bool] = None


@router.get("/push/preferences")
async def get_notification_preferences(request: Request):
    """Current notification category preferences for this device."""
    owner = request.state.device["device_id"]
    prefs = await _get_notification_prefs(owner)
    return {"categories": NOTIFICATION_CATEGORIES, "preferences": prefs}


@router.put("/push/preferences")
async def set_notification_preferences(body: NotificationPrefsIn, request: Request):
    """Update notification category preferences. Only the three configurable categories can be changed.
    Barking and Biting are always on — the endpoint silently ignores any attempt to disable them."""
    owner = request.state.device["device_id"]
    current = await _get_notification_prefs(owner)
    update = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in DEFAULT_PREFS}
    merged = {**current, **update}
    await db.devices.update_one(
        {"device_id": owner},
        {"$set": {"settings.notification_preferences": merged, "last_seen_at": now_utc()}},
        upsert=True,
    )
    return {"categories": NOTIFICATION_CATEGORIES, "preferences": merged}
