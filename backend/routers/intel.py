"""Reputation checks, batch checks and feedback."""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.db import db, now_utc
from core.models import ApolloState, IntelCheckRequest, IntelCheckResponse
from services.intel import assess_indicator, run_intel_check

router = APIRouter()


@router.get("/intel/status")
async def intel_status():
    from services.google_web_risk import configured, enabled, period
    if configured():
        # Status must not issue a billable lookup, including synthetic test URLs.
        try:
            quota = await db.web_risk_quota.find_one({"_id": period(now_utc())}, {"reserved": 1, "testing_reserved": 1, "production_reserved": 1})
            used = int(quota.get("reserved", 0)) if quota else 0
            sb = {"status": "configured" if enabled() else "disabled",
                  "provider": "google_web_risk", "reserved_this_month": used,
                  "operational_cutoff": 95000,
                  "testing_reserved": int(quota.get("testing_reserved", 0)) if quota else 0,
                  "testing_budget": 10000,
                  "production_reserved": int(quota.get("production_reserved", 0)) if quota else 0,
                  "production_budget": 85000,
                  "detail": "Status is passive; it does not verify live Google API access."}
        except Exception:
            sb = {"status": "unavailable", "provider": "google_web_risk",
                  "detail": "Request accounting unavailable. External lookups must not proceed."}
    else:
        sb = {"status": "not_configured" if enabled() else "disabled", "provider": "google_web_risk",
              "detail": "Status is passive; Google Web Risk needs an enabled integration and server API key."}
    count = await db.blocklist.count_documents({"deleted_at": None})
    return {"safe_browsing": sb, "blocklist": {"status": "ok", "entries": count}, "checked_at": now_utc()}


@router.post("/intel/check", response_model=IntelCheckResponse)
async def intel_check(body: IntelCheckRequest):
    from services import org_directory
    result = await assess_indicator(body.indicator_type, body.value, body.expand)
    official = org_directory.site_verdict(org_directory.host_of(body.value))
    return result.model_copy(update={"official": official}) if official else result


Contact = Annotated[str, Field(min_length=1, max_length=320)]


class OfficialContactsIn(BaseModel):
    """The websites, numbers and addresses in material being checked, and the organisation it names (if any)."""
    claimed_org: Optional[str] = Field(default=None, max_length=60)
    sites: list[Contact] = Field(default_factory=list, max_length=20)
    phones: list[Contact] = Field(default_factory=list, max_length=20)
    emails: list[Contact] = Field(default_factory=list, max_length=20)


@router.post("/official/contacts")
async def official_contacts(body: OfficialContactsIn):
    """The Official Organisation Directory's verdict on each contact: an organisation's own, or not the official contact
    of the organisation the material names, with the one to use instead. Nothing is fetched or stored."""
    from services import org_directory
    return {"verdicts": org_directory.verdicts(body.claimed_org, body.sites, body.phones, body.emails)}


@router.get("/official/names")
async def official_names():
    """The organisations on the Official Organisation Directory and the names people use for them (reference data)."""
    from services import org_directory
    return {"organisations": org_directory.names()}


class FeedbackIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=64)
    event_id: str = Field(min_length=8, max_length=64)
    kind: Literal["false_positive", "missed_threat", "override"]
    state: ApolloState
    host: Optional[str] = Field(default=None, max_length=253)
    sources: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=300)


@router.post("/feedback", status_code=201)
async def submit_feedback(body: FeedbackIn):
    """Report Mistake / user override. Reviewed by humans — never auto-whitelists a site globally."""
    await db.feedback.insert_one({**body.model_dump(), "created_at": now_utc()})
    return {"received": True}


class IntelBatchRequest(BaseModel):
    indicator_type: Literal["url", "domain"] = "url"
    values: list[str] = Field(min_length=1, max_length=200)


class IntelBatchItem(BaseModel):
    value: str
    result: Optional[IntelCheckResponse] = None
    error: Optional[str] = None


@router.post("/intel/check-batch", response_model=list[IntelBatchItem])
async def intel_check_batch(body: IntelBatchRequest):
    """Benchmark support: check many indicators in one round-trip. Same privacy rules as /intel/check."""
    out: list[IntelBatchItem] = []
    for value in body.values:
        try:
            out.append(IntelBatchItem(value=value, result=await run_intel_check(body.indicator_type, value)))
        except HTTPException as exc:
            out.append(IntelBatchItem(value=value, error=str(exc.detail)))
    return out
