"""Phone Number Identity — who this number belongs to.

POST /number/identify  — resolve a phone number's identity from Apollo's own sources.
No paid reverse-lookup APIs. Uses: Official Organisation Directory, Apollo KB, web search (Brave).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger("apollo.phone_identity")


class IdentifyRequest(BaseModel):
    number: str = Field(min_length=3, max_length=40, description="Phone number to identify")
    country: Optional[str] = Field(default=None, min_length=2, max_length=2, description="2-letter country code hint for local numbers")


@router.post("/number/identify")
async def identify_number(body: IdentifyRequest):
    """Resolve who a phone number belongs to.

    Pipeline: normalize → check cache → Official Org Directory → Apollo KB → web search → assess → cache.
    No paid reverse-lookup APIs. Uses ApolloSG's existing research capability only.
    """
    try:
        from services.phone_identity import identify
        result = await identify(body.number, body.country)
        return result.model_dump()
    except Exception:
        logger.exception("phone_identity endpoint failed for number=%s", body.number[:4] + "…")
        raise
