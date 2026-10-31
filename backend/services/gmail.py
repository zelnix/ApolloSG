"""Gmail read-only connection: server-side OAuth (Web-application client), encrypted refresh-token
storage in Mongo, and a manual inbox scan. Scope is `gmail.readonly` only — Apollo never sends,
deletes, labels or modifies anything in the connected account.

Privacy contract: message content fetched by scan_inbox() is returned to the caller for THIS
request only and is NEVER written to Mongo. Only the encrypted OAuth refresh token is persisted —
and only for as long as the user keeps the connection (see disconnect()).
"""
from __future__ import annotations

import base64
import re
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from core.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_GMAIL_REDIRECT_URI, GMAIL_TOKEN_ENCRYPTION_KEY, logger
from core.db import db, now_utc

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
OAUTH_STATE_TTL = timedelta(minutes=10)

_fernet: Optional[Fernet] = Fernet(GMAIL_TOKEN_ENCRYPTION_KEY.encode()) if GMAIL_TOKEN_ENCRYPTION_KEY else None


def configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_GMAIL_REDIRECT_URI and _fernet)


async def cleanup_unreadable_connections() -> int:
    """Remove only grants encrypted under an unavailable/retired key; never contact Google."""
    if not _fernet:
        return 0
    removed = 0
    async for row in db.gmail_connections.find({"refresh_token_enc": {"$type": "string"}}, {"_id": 0, "device_id": 1, "refresh_token_enc": 1}):
        try:
            _fernet.decrypt(row["refresh_token_enc"].encode())
        except (InvalidToken, KeyError):
            result = await db.gmail_connections.delete_one({"device_id": row["device_id"], "refresh_token_enc": row["refresh_token_enc"]})
            removed += result.deleted_count
    return removed


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_GMAIL_REDIRECT_URI, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state,
    }
    return f"{AUTH_URI}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(TOKEN_URI, data={
            "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_GMAIL_REDIRECT_URI, "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        logger.info("gmail code exchange failed: %s", resp.status_code)
        raise HTTPException(400, "Google authorization failed")
    payload = resp.json()
    granted = set(str(payload.get("scope", "")).split())
    if granted != {SCOPE}:
        raise HTTPException(400, "Google did not grant the exact read-only Gmail permission")
    return payload


async def _refresh_access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(TOKEN_URI, data={
            "refresh_token": refresh_token, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
    if resp.status_code != 200:
        raise HTTPException(401, "Gmail grant expired or was revoked; reconnect")
    return resp.json()["access_token"]


async def fetch_profile_email(access_token: str) -> str:
    """Read the connected account's address (profile.emailAddress) so each account is labelled."""
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(f"{GMAIL_API}/profile", headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code != 200:
        raise HTTPException(400, "Could not read the Gmail account address")
    return str(resp.json().get("emailAddress", "")).lower()


async def save_connection(device_id: str, refresh_token: str, email: str) -> None:
    if not _fernet:
        raise HTTPException(503, "Gmail isn't configured on this build")
    enc = _fernet.encrypt(refresh_token.encode()).decode()
    # One row per (device, account) so a device can protect multiple Gmail accounts.
    await db.gmail_connections.update_one(
        {"device_id": device_id, "email": email},
        {"$set": {"refresh_token_enc": enc, "scopes": [SCOPE], "updated_at": now_utc()},
         "$setOnInsert": {"device_id": device_id, "email": email, "created_at": now_utc(), "monitoring_enabled": True}},
        upsert=True,
    )


async def get_connections(device_id: str) -> list[dict]:
    return [row async for row in db.gmail_connections.find({"device_id": device_id})]


async def get_connection(device_id: str, email: Optional[str] = None) -> Optional[dict]:
    query: dict[str, Any] = {"device_id": device_id}
    if email:
        query["email"] = email
    return await db.gmail_connections.find_one(query)


async def disconnect(device_id: str, email: Optional[str] = None) -> None:
    query: dict[str, Any] = {"device_id": device_id}
    if email:
        query["email"] = email
    async for row in db.gmail_connections.find(query):
        if _fernet and row.get("refresh_token_enc"):
            try:
                refresh = _fernet.decrypt(row["refresh_token_enc"].encode()).decode()
                async with httpx.AsyncClient(timeout=10) as http:
                    await http.post("https://oauth2.googleapis.com/revoke", data={"token": refresh})
            except Exception as exc:
                logger.info("gmail provider revocation did not complete: %s", type(exc).__name__)
    await db.gmail_connections.delete_many(query)


async def _access_token_for(device_id: str, email: Optional[str] = None) -> str:
    row = await get_connection(device_id, email)
    if not row or not _fernet:
        raise HTTPException(404, "Gmail is not connected")
    if not row.get("refresh_token_enc"):
        raise HTTPException(409, "Gmail connection is incomplete; reconnect before scanning")
    try:
        refresh = _fernet.decrypt(row["refresh_token_enc"].encode()).decode()
    except (InvalidToken, KeyError, UnicodeDecodeError):
        await db.gmail_connections.delete_one({"device_id": device_id, "email": row.get("email")})
        raise HTTPException(401, "Gmail grant could not be decrypted; reconnect")
    try:
        return await _refresh_access_token(refresh)
    except HTTPException:
        await disconnect(device_id, row.get("email"))
        raise


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _walk_parts(part: dict):
    if isinstance(part.get("parts"), list):
        for child in part["parts"]:
            yield from _walk_parts(child)
    elif part.get("body", {}).get("data"):
        mime = part.get("mimeType", "")
        if mime in ("text/plain", "text/html"):
            yield mime, _b64url_decode(part["body"]["data"])


def _extract_anchors(chunks: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    """Pulls (visible text, href) pairs from the text/html MIME part — this is what Email Guard's
    displayed-link-text vs real-destination mismatch check needs; plain text alone can't carry it."""
    from bs4 import BeautifulSoup

    anchors: list[dict[str, str]] = []
    for mime, raw in chunks:
        if mime != "text/html":
            continue
        try:
            soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
        except Exception:  # noqa: BLE001
            continue
        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            text = a.get_text(" ", strip=True)
            if not text or not href.lower().startswith(("http://", "https://")):
                continue
            anchors.append({"text": text, "href": href})
    return anchors


def _extract_content(message: dict) -> tuple[str, list[dict[str, str]]]:
    """Returns (plain_text, anchors). Text prefers text/plain (crude tag-strip fallback for
    text/html); anchors come from the text/html part specifically, when present. Capped — this is a
    signal source for the on-device rule engine, not a faithful rendering of the email."""
    payload = message.get("payload", {})
    chunks = list(_walk_parts(payload))
    if not chunks and payload.get("body", {}).get("data"):
        chunks = [(payload.get("mimeType", ""), _b64url_decode(payload["body"]["data"]))]
    plain = next((b for m, b in chunks if m == "text/plain"), None)
    raw = plain or (chunks[0][1] if chunks else b"")
    text = raw.decode("utf-8", errors="replace")
    if "<" in text and ">" in text:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, _extract_anchors(chunks)


def _headers_of(message: dict) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in message.get("payload", {}).get("headers", [])}


def _extract_auth_results(headers: dict[str, str]) -> dict[str, str]:
    """Parse SPF, DKIM, and DMARC results from Gmail's Authentication-Results header.
    These are set by Google's receiving mail server and are trustworthy when read from the API.
    Returns a dict with keys 'spf', 'dkim', 'dmarc' → 'pass'|'fail'|'softfail'|'neutral'|'none'|'unknown'."""
    auth_header = headers.get("authentication-results", "")
    results: dict[str, str] = {"spf": "unknown", "dkim": "unknown", "dmarc": "unknown"}
    if not auth_header:
        return results
    lower = auth_header.lower()
    for mechanism in ("spf", "dkim", "dmarc"):
        # Look for "mechanism=result" patterns in the authentication-results header
        match = re.search(rf"{mechanism}=(\w+)", lower)
        if match:
            result = match.group(1)
            if result in ("pass", "fail", "softfail", "neutral", "none", "temperror", "permerror"):
                results[mechanism] = result
    return results


def _extract_attachment_names(payload: dict) -> list[str]:
    """Extract attachment filenames from the message payload for risky-type flagging."""
    names: list[str] = []
    _collect_attachment_names(payload, names)
    return names


def _collect_attachment_names(part: dict, names: list[str]) -> None:
    """Recursively walk MIME parts to find attachment filenames."""
    if isinstance(part.get("parts"), list):
        for child in part["parts"]:
            _collect_attachment_names(child, names)
    filename = part.get("filename", "")
    if filename and part.get("body", {}).get("attachmentId"):
        names.append(filename)


async def scan_inbox_page(device_id: str, page_token: str | None = None, limit: int = 15, email: str | None = None,
                          after_ms: int | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one durable cursor page for a single account; content remains request-scoped. `after_ms`: only mail
    received after the account's checkpoint (incremental monitoring)."""
    limit = max(1, min(limit, 25))
    row = await get_connection(device_id, email)
    account = row.get("email") if row else email
    token = await _access_token_for(device_id, account)
    auth = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as http:
        params = {"maxResults": limit, "q": "newer_than:30d" + (f" after:{int(after_ms) // 1000}" if after_ms else "")}
        if page_token:
            params["pageToken"] = page_token
        listed = await http.get(f"{GMAIL_API}/messages", params=params, headers=auth)
        if listed.status_code == 401:
            await disconnect(device_id, account)
            raise HTTPException(401, "Gmail access was rejected; reconnect")
        listed.raise_for_status()
        listing = listed.json()
        ids = listing.get("messages", [])
        out: list[dict[str, Any]] = []
        for item in ids:
            got = await http.get(f"{GMAIL_API}/messages/{item['id']}", params={"format": "full"}, headers=auth)
            if got.status_code != 200:
                continue
            msg = got.json()
            h = _headers_of(msg)
            text, anchors = _extract_content(msg)
            # #3: Extract authentication evidence from Gmail-provided headers.
            # These are set by the receiving mail server (Google), not by the sender — they are
            # trustworthy when read from the API (unlike headers pasted in email body text).
            auth_results = _extract_auth_results(h)
            # Extract Reply-To for mismatch detection (Email Gate improvement)
            reply_to = h.get("reply-to", "")
            # Extract attachment filenames for risky-type flagging
            attachment_names = _extract_attachment_names(msg.get("payload", {}))
            out.append({"id": msg.get("id", ""), "account": account, "from": h.get("from", ""), "subject": h.get("subject", ""),
                        "date": h.get("date", ""), "internal_date": msg.get("internalDate"), "body": text, "links": anchors,
                        "reply_to": reply_to, "attachment_names": attachment_names,
                        "auth_results": auth_results})
    return out, listing.get("nextPageToken")


async def scan_inbox(device_id: str, limit: int = 15) -> list[dict[str, Any]]:
    """Scan the first page of EVERY connected account for this device (monitor all together).
    Each returned item is tagged with its `account` address."""
    connections = await get_connections(device_id)
    if not connections:
        raise HTTPException(404, "Gmail is not connected")
    aggregated: list[dict[str, Any]] = []
    for row in connections:
        try:
            items, _next = await scan_inbox_page(device_id, None, limit, row.get("email"))
            aggregated.extend(items)
        except HTTPException:
            continue  # a single revoked/expired account must not block the others
    return aggregated



async def download_attachment(device_id: str, message_id: str, attachment_id: str, email: str | None = None) -> bytes | None:
    """Download an individual attachment from a Gmail message.
    Returns raw attachment bytes, or None on failure."""
    access_token = await _access_token_for(device_id, email)
    auth = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{GMAIL_API}/messages/{message_id}/attachments/{attachment_id}",
                headers=auth,
            )
        if resp.status_code != 200:
            return None
        import base64
        data_b64 = resp.json().get("data", "")
        # Gmail API returns URL-safe base64
        return base64.urlsafe_b64decode(data_b64 + "==")
    except Exception:
        return None


def get_attachment_ids(payload: dict) -> list[dict]:
    """Extract attachment IDs and filenames from a Gmail message payload.
    Returns list of {filename, attachmentId, mimeType}."""
    attachments: list[dict] = []
    _collect_attachments(payload, attachments)
    return attachments


def _collect_attachments(part: dict, out: list[dict]) -> None:
    if isinstance(part.get("parts"), list):
        for child in part["parts"]:
            _collect_attachments(child, out)
    filename = part.get("filename", "")
    attachment_id = part.get("body", {}).get("attachmentId")
    if filename and attachment_id:
        out.append({"filename": filename, "attachmentId": attachment_id,
                     "mimeType": part.get("mimeType", ""),
                     "size": part.get("body", {}).get("size", 0)})
