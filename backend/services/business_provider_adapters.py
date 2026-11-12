"""Server-side provider adapters for curated Call Gate business registry enrichment.

Never call from a mobile client. Responses are research inputs, not verified caller IDs.
All calls fail closed and expose no credentials in errors. Paid Twilio fields are opt-in.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

import httpx


class ProviderUnavailable(Exception):
    pass


def _domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", domain) or "." not in domain or ".." in domain:
        raise ValueError("Invalid business domain")
    return domain


def _abn(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11:
        raise ValueError("ABN must contain 11 digits")
    return digits


def _phone(value: str) -> str:
    if not re.fullmatch(r"\+?[0-9 ()-]{5,28}", value):
        raise ValueError("Invalid phone number")
    return value.strip()


async def fetch_brandfetch(domain: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    key = os.getenv("BRANDFETCH_API_KEY")
    if not key:
        raise ProviderUnavailable("Brandfetch not configured")
    domain = _domain(domain)
    async def call(http: httpx.AsyncClient):
        try:
            response = await http.get(
                f"https://api.brandfetch.io/v2/brands/domain/{quote(domain, safe='')}",
                headers={"Authorization": f"Bearer {key}"}, timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid provider response")
            # Never accept provider-returned brand domains as official without separate review.
            logos = payload.get("logos") or []
            candidates = []
            for logo in logos if isinstance(logos, list) else []:
                if not isinstance(logo, dict) or logo.get("type") not in ("icon", "logo", "symbol"):
                    continue
                for fmt in logo.get("formats", []):
                    if isinstance(fmt, dict) and fmt.get("format") in ("png", "svg") and isinstance(fmt.get("src"), str) and fmt["src"].startswith("https://"):
                        candidates.append(fmt["src"])
            return {"domain_queried": domain, "brand_name": payload.get("name"), "logo_candidates": candidates[:10], "provider": "brandfetch"}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderUnavailable("Brandfetch request failed") from exc
    if client is not None:
        return await call(client)
    async with httpx.AsyncClient() as http:
        return await call(http)


async def fetch_abn_lookup(abn: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    guid = os.getenv("ABN_LOOKUP_GUID")
    if not guid:
        raise ProviderUnavailable("ABN Lookup not configured")
    abn = _abn(abn)
    async def call(http: httpx.AsyncClient):
        try:
            # Official ABR limited JSON endpoint returns JSONP, not plain JSON.
            response = await http.get("https://abr.business.gov.au/json/AbnDetails.aspx",
                params={"abn": abn, "guid": guid, "callback": "apolloCallback"}, timeout=8)
            response.raise_for_status()
            body = response.text.strip().removesuffix(";").strip()
            prefix = "apolloCallback("
            if not body.startswith(prefix) or not body.endswith(")"):
                raise ValueError("Unexpected ABR JSONP response")
            import json
            payload = json.loads(body[len(prefix):-1])
            if not isinstance(payload, dict):
                raise ValueError("Invalid ABR response")
            return {
                "provider": "abn_lookup", "abn": abn,
                "entity_name": payload.get("EntityName"),
                "abn_status": payload.get("AbnStatus"),
                "business_names": payload.get("BusinessName") or [],
                "registration_confirmed": str(payload.get("AbnStatus", "")).strip().lower() == "active"
                    and re.sub(r"\D", "", str(payload.get("Abn", ""))) == abn,
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderUnavailable("ABN Lookup request failed") from exc
    if client is not None:
        return await call(client)
    async with httpx.AsyncClient() as http:
        return await call(http)


async def fetch_twilio_lookup(number: str, *, country: str = "AU", client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    sid = os.getenv("TWILIO_API_KEY")
    secret = os.getenv("TWILIO_API_SECRET")
    if not sid or not secret:
        raise ProviderUnavailable("Twilio Lookup not configured")
    number = _phone(number)
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Invalid country code")
    # Paid packages are disabled unless explicitly approved by backend operator.
    fields = os.getenv("TWILIO_LOOKUP_FIELDS", "").strip()
    allowed = {"line_type_intelligence"}
    if fields and set(fields.split(",")) - allowed:
        raise ValueError("Unsupported or unapproved paid Twilio fields")
    params = {"CountryCode": country} if not number.startswith("+") else {}
    if fields:
        params["Fields"] = fields
    async def call(http: httpx.AsyncClient):
        try:
            response = await http.get(
                f"https://lookups.twilio.com/v2/PhoneNumbers/{quote(number, safe='')}",
                params=params, auth=(sid, secret), timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid Twilio response")
            line = payload.get("line_type_intelligence") or {}
            return {
                "provider": "twilio_lookup_v2", "valid": payload.get("valid"),
                "phone_number": payload.get("phone_number"),
                "country_code": payload.get("country_code"),
                "line_type": line.get("type") if isinstance(line, dict) else None,
                "carrier_name": line.get("carrier_name") if isinstance(line, dict) else None,
                "paid_fields_requested": fields.split(",") if fields else [],
                "caller_authenticated": False,
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderUnavailable("Twilio Lookup request failed") from exc
    if client is not None:
        return await call(client)
    async with httpx.AsyncClient() as http:
        return await call(http)
