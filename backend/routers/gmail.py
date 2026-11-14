"""Gmail read-only connection & manual inbox scan. See services/gmail.py for the OAuth/API details.

Privacy contract: /gmail/scan returns message content to the caller for THIS request only — it is
never written to Mongo. Only the encrypted OAuth refresh token is persisted, and only until the
user disconnects (DELETE /gmail/connection)."""
from __future__ import annotations

import secrets
import hashlib
from datetime import timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from core.config import GOOGLE_GMAIL_REDIRECT_URI, PUBLIC_BASE, logger
from core.db import db, now_utc
from services import gmail as gmail_service
from services.mailbox_monitor import scan_gmail_through_shared_pipeline

router = APIRouter()

# Where the OAuth callback is allowed to bounce the browser back to — the app supplies this itself
# (Linking.createURL) so it always matches the current dev/Expo-Go/production redirect target; we
# just refuse anything that isn't one of Apollo's own schemes to prevent this becoming an open redirect.
def _valid_app_redirect(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.fragment:
        return False
    if parsed.scheme == "apollo":
        return bool(parsed.netloc or parsed.path)
    if parsed.scheme in {"exp", "exps"}:
        return bool(parsed.hostname)  # development-only Expo return; carries no Google token
    public_host = urlparse(PUBLIC_BASE).hostname
    if parsed.scheme == "https":
        return bool(public_host and parsed.hostname == public_host)
    if parsed.scheme == "http":
        return parsed.hostname in {"127.0.0.1", "localhost"}
    return False


def _bounce(base: str, **params) -> str:
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}"


class GmailConnectOut(BaseModel):
    authorization_url: str


@router.get("/gmail/connect", response_model=GmailConnectOut)
async def gmail_connect(device_id: str = Query(min_length=8, max_length=64), app_redirect: str = Query(min_length=4, max_length=500)):
    if not gmail_service.configured():
        raise HTTPException(503, "Gmail isn't configured on this build")
    if not _valid_app_redirect(app_redirect):
        raise HTTPException(400, "Invalid redirect target")
    state = secrets.token_urlsafe(24)
    state_digest = hashlib.sha256(state.encode()).hexdigest()
    await db.gmail_oauth_states.insert_one({"state_digest": state_digest, "device_id": device_id, "app_redirect": app_redirect,
                                            "retention_class": "oauth_csrf_temporary", "created_at": now_utc(),
                                            "expires_at": now_utc() + timedelta(minutes=10)})
    logger.info("gmail oauth start redirect_uri=%s", GOOGLE_GMAIL_REDIRECT_URI)
    return GmailConnectOut(authorization_url=gmail_service.build_authorization_url(state))


@router.get("/gmail/oauth/callback")
async def gmail_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    state_digest = hashlib.sha256(state.encode()).hexdigest() if state else None
    row = await db.gmail_oauth_states.find_one_and_delete({"state_digest": state_digest}) if state_digest else None
    if not row:
        # No trusted app_redirect to bounce to at all — the only safe response is a plain page.
        raise HTTPException(400, "This Gmail connection link is invalid or expired. Please try connecting again in the app.")
    app_redirect = row["app_redirect"]
    if row["expires_at"].replace(tzinfo=timezone.utc) < now_utc():
        return RedirectResponse(_bounce(app_redirect, gmail="error", reason="expired"), status_code=303)
    if error:
        return RedirectResponse(_bounce(app_redirect, gmail="denied"), status_code=303)
    if not code:
        return RedirectResponse(_bounce(app_redirect, gmail="error"), status_code=303)
    try:
        token_data = await gmail_service.exchange_code(code)
        refresh = token_data.get("refresh_token")
        email = await gmail_service.fetch_profile_email(token_data["access_token"])
        if not refresh:
            # Google omits it on a repeat consent; only fail if we don't already have one for THIS account.
            existing = await gmail_service.get_connection(row["device_id"], email)
            if not existing:
                return RedirectResponse(_bounce(app_redirect, gmail="error", reason="no_refresh_token"), status_code=303)
        else:
            await gmail_service.save_connection(row["device_id"], refresh, email)
    except HTTPException as exc:
        logger.info("gmail callback failed: %s", exc.detail)
        return RedirectResponse(_bounce(app_redirect, gmail="error"), status_code=303)
    return RedirectResponse(_bounce(app_redirect, gmail="connected"), status_code=303)


def _account_state(row: dict) -> dict:
    lease_active = bool(row.get("monitor_lease_until") and row["monitor_lease_until"].replace(tzinfo=timezone.utc) > now_utc())
    state = "off" if not row.get("monitoring_enabled") else "checking" if lease_active else "needs_attention" if row.get("monitor_last_error_at") and not row.get("monitor_last_success_at") else "ready"
    created = row.get("created_at")
    return {"email": row.get("email"), "connected_at": created.isoformat() if created else None, "monitoring_enabled": bool(row.get("monitoring_enabled")),
            "monitor_last_checked_at": row.get("monitor_last_checked_at"), "monitor_last_error_at": row.get("monitor_last_error_at"),
            "monitor_last_success_at": row.get("monitor_last_success_at"), "monitor_last_assessment_at": row.get("monitor_last_assessment_at"),
            "monitor_last_attempt_at": row.get("monitor_last_attempt_at"), "monitor_state": state,
            "cursor_pending": bool(row.get("monitor_next_page_token"))}


@router.get("/gmail/status")
async def gmail_status(device_id: str = Query(min_length=8, max_length=64)):
    rows = await gmail_service.get_connections(device_id)
    accounts = [_account_state(r) for r in rows]
    primary = rows[0] if rows else None
    lease_active = bool(primary and primary.get("monitor_lease_until") and primary["monitor_lease_until"].replace(tzinfo=timezone.utc) > now_utc())
    monitor_state = "disconnected" if not primary else "off" if not primary.get("monitoring_enabled") else "checking" if lease_active else "needs_attention" if primary.get("monitor_last_error_at") and not primary.get("monitor_last_success_at") else "ready"
    return {"connected": len(rows) > 0, "configured": gmail_service.configured(),
            "oauth_redirect_uri": GOOGLE_GMAIL_REDIRECT_URI if gmail_service.configured() else None,
            "accounts": accounts,
            # Back-compat single-account fields mirror the first account.
            "monitoring_enabled": bool(primary and primary.get("monitoring_enabled")),
            "monitor_last_checked_at": primary.get("monitor_last_checked_at") if primary else None,
            "monitor_last_error_at": primary.get("monitor_last_error_at") if primary else None,
            "monitor_last_success_at": primary.get("monitor_last_success_at") if primary else None,
            "monitor_last_assessment_at": primary.get("monitor_last_assessment_at") if primary else None,
            "monitor_last_attempt_at": primary.get("monitor_last_attempt_at") if primary else None,
            "monitor_state": monitor_state, "cursor_pending": bool(primary and primary.get("monitor_next_page_token"))}


class GmailMonitoringIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    enabled: bool


@router.post("/gmail/monitoring")
async def gmail_monitoring(body: GmailMonitoringIn):
    # Monitor all connected accounts together — the toggle applies device-wide.
    result = await db.gmail_connections.update_many({"device_id": body.device_id},
        {"$set": {"monitoring_enabled": body.enabled, "updated_at": now_utc()}})
    if not result.matched_count:
        raise HTTPException(404, "Connect Gmail before enabling monitoring")
    return {"monitoring_enabled": body.enabled}


@router.delete("/gmail/connection", status_code=204)
async def gmail_disconnect(device_id: str = Query(min_length=8, max_length=64), email: Optional[str] = Query(default=None, max_length=320)):
    # Omit `email` to disconnect every account on this device; pass one to remove a single account.
    await gmail_service.disconnect(device_id, email)


class GmailScanIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)


@router.post("/gmail/scan")
async def gmail_scan(body: GmailScanIn):
    return await scan_gmail_through_shared_pipeline(body.device_id, "manual")



class AttachmentInfo(BaseModel):
    filename: str
    mime_type: str = ""
    size: int = 0


class GmailMessagePreview(BaseModel):
    id: str
    account: str = ""
    sender: str = Field(alias="from", default="")
    subject: str = ""
    date: str = ""
    snippet: str = ""
    attachment_count: int = 0
    attachment_names: list[str] = []

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class GmailMessagesOut(BaseModel):
    messages: list[GmailMessagePreview]
    next_page_token: Optional[str] = None


@router.get("/gmail/messages", response_model=GmailMessagesOut)
async def gmail_messages(device_id: str = Query(min_length=8, max_length=64), limit: int = Query(default=20, ge=1, le=50), page_token: Optional[str] = Query(default=None), email: Optional[str] = Query(default=None, max_length=320)):
    """Return lightweight inbox previews — id, from, subject, date, snippet.
    Pass `email` to fetch from a single connected account; omit it to fetch from all.
    Does NOT return full body content (that happens on single-message fetch)."""
    import httpx
    connections = await gmail_service.get_connections(device_id)
    if not connections:
        raise HTTPException(404, "Gmail is not connected")
    # When a specific account is requested, filter connections to that one.
    if email:
        connections = [r for r in connections if r.get("email", "").lower() == email.lower()]
        if not connections:
            raise HTTPException(404, "That email account is not connected")
    previews: list[dict] = []
    next_token: Optional[str] = None
    for row in connections:
        account_email = row.get("email", "")
        try:
            access_token = await gmail_service._access_token_for(device_id, account_email)
        except HTTPException:
            continue
        auth = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=15) as http:
            params: dict = {"maxResults": limit, "q": "newer_than:30d"}
            if page_token:
                params["pageToken"] = page_token
            listed = await http.get(f"{gmail_service.GMAIL_API}/messages", params=params, headers=auth)
            if listed.status_code == 401:
                continue
            listed.raise_for_status()
            listing = listed.json()
            next_token = listing.get("nextPageToken")
            for item in listing.get("messages", []):
                got = await http.get(f"{gmail_service.GMAIL_API}/messages/{item['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}, headers=auth)
                if got.status_code != 200:
                    continue
                msg = got.json()
                headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
                # Extract attachment info from payload parts (metadata format includes part structure but not body data)
                att_names = gmail_service._extract_attachment_names(msg.get("payload", {}))
                previews.append({
                    "id": msg.get("id", ""),
                    "account": account_email,
                    "from": headers.get("from", ""),
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "attachment_count": len(att_names),
                    "attachment_names": att_names[:10],  # cap at 10 to keep response lean
                })
    return GmailMessagesOut(messages=previews, next_page_token=next_token)


class GmailMessageDetail(BaseModel):
    id: str
    account: str = ""
    sender: str = Field(alias="from", default="")
    subject: str = ""
    date: str = ""
    body: str = ""
    attachments: list[AttachmentInfo] = []
    raw_base64url: str | None = None
    original_unavailable_reason: str | None = None

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


@router.get("/gmail/message/{message_id}", response_model=GmailMessageDetail)
async def gmail_message_detail(message_id: str, response: Response, device_id: str = Query(min_length=8, max_length=64), email: Optional[str] = Query(default=None), include_original: bool = Query(default=False)):
    """Fetch a single message's full content for analysis."""
    import httpx
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization"
    access_token = await gmail_service._access_token_for(device_id, email)
    auth = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as http:
        got = await http.get(f"{gmail_service.GMAIL_API}/messages/{message_id}", params={"format": "full"}, headers=auth)
        if got.status_code == 401:
            raise HTTPException(401, "Gmail access was rejected; reconnect")
        got.raise_for_status()
        msg = got.json()
        if msg.get("id") != message_id:
            raise HTTPException(502, "Gmail returned a different message; nothing was checked")
        h = gmail_service._headers_of(msg)
        text, _ = gmail_service._extract_content(msg)
        # Extract full attachment metadata for the UI and investigation
        raw_attachments = gmail_service.get_attachment_ids(msg.get("payload", {}))
        attachments = [AttachmentInfo(filename=a["filename"], mime_type=a.get("mimeType", ""), size=a.get("size", 0)) for a in raw_attachments]
        raw, unavailable = (await gmail_service.selected_message_original(http, auth, message_id, int(msg.get("sizeEstimate") or 0))
                            if include_original else (None, None))
        return GmailMessageDetail(
            id=msg.get("id", ""),
            account=email or "",
            **{"from": h.get("from", "")},
            subject=h.get("subject", ""),
            date=h.get("date", ""),
            body=text,
            attachments=attachments,
            raw_base64url=raw,
            original_unavailable_reason=unavailable,
        )
