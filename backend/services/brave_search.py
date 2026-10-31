"""Brave Search — the one web search TC FlyBy may run for a case (services/higgins/tc_flyby/search.py).

One request, `GET https://api.search.brave.com/res/v1/web/search`, authenticated with BRAVE_API_KEY in the
X-Subscription-Token header. The key lives only on the server. No AI is involved: the results are returned exactly as
Brave sent them (url, title, description, extra snippets) and TC FlyBy reads them deterministically.

Spending: every request reserves its price against ApolloSG's daily limits first (services/ai_budget.py) and is
recorded in the usage log with purpose "tc_flyby_search". A refused or rejected request is not billed and releases its
reservation; a request whose billing outcome isn't known (timeout, dropped connection) keeps it.

Not configured, or on the preview server (which makes no paid calls): SearchUnavailable, before anything is sent.
Brave is never retried here: a failure is reported as it happened.
"""
from __future__ import annotations

import os
import uuid

import httpx

from services import ai_budget

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MODEL = "brave-web-search"
PURPOSE = "tc_flyby_search"
QUERY_USD = 0.005          # Brave Search API: $5 per 1,000 requests
MAX_QUERY_CHARS = 400      # Brave accepts up to 400 characters and 50 words
MAX_QUERY_WORDS = 50
RESULTS = 10


class SearchUnavailable(Exception):
    """The search couldn't run or didn't answer. `reason` is a stable code, never the key or Brave's body."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _key() -> str:
    return (os.environ.get("BRAVE_API_KEY") or "").strip()


def configured() -> bool:
    return bool(_key())


def _preview() -> bool:
    from services.higgins import provider
    return provider.get_provider_mode() == "preview"


def _query(text: str) -> str:
    words = " ".join((text or "").split()).split(" ")[:MAX_QUERY_WORDS]
    return " ".join(words)[:MAX_QUERY_CHARS].strip()


def _results(payload: dict) -> list[dict]:
    out = []
    for item in ((payload.get("web") or {}).get("results") or []):
        url, title = str(item.get("url") or ""), str(item.get("title") or "")
        if not url or not title:
            continue
        out.append({"url": url, "title": title[:300], "description": str(item.get("description") or "")[:600],
                    "extraSnippets": [str(s)[:600] for s in (item.get("extra_snippets") or [])[:5]]})
    return out


async def _record(status: str, cost: float, *, correlation_id: str | None, trigger_source: str | None, device_id: str | None,
                  case_id: str | None, reservation_id: str) -> None:
    from services import gemini_usage
    await gemini_usage.record_search(record_id=reservation_id, provider="brave", model=MODEL, purpose=PURPOSE, success=status == "ok",
                                     failure_code=None if status == "ok" else status, cost_usd=cost, correlation_id=correlation_id,
                                     device_id=device_id, case_id=case_id, trigger_source=trigger_source)


async def search(query: str, *, correlation_id: str | None, trigger_source: str | None = None, device_id: str | None = None,
                 case_id: str | None = None) -> list[dict]:
    """The results of one Brave request: [{url, title, description, extraSnippets}]. Raises SearchUnavailable."""
    q = _query(query)
    if not q:
        raise SearchUnavailable("empty_query")
    if not configured():
        raise SearchUnavailable("not_configured")
    if _preview():
        raise SearchUnavailable("preview_no_paid_search")
    if os.getenv("APOLLO_FORBID_PROVIDER_CALLS") == "1":
        raise AssertionError("Live search calls are prohibited in bounded tests")
    try:
        reservation = await ai_budget.reserve(QUERY_USD, automated=ai_budget.automated(trigger_source), purpose=PURPOSE, model=MODEL,
                                              provider="brave", correlation_id=correlation_id, device_id=device_id, case_id=case_id)
    except ai_budget.BudgetExceeded as exc:
        raise SearchUnavailable(exc.code) from None
    meta = {"correlation_id": correlation_id, "trigger_source": trigger_source, "device_id": device_id, "case_id": case_id,
            "reservation_id": reservation.reservation_id or str(uuid.uuid4())}
    params = {"q": q, "count": RESULTS, "safesearch": "moderate", "extra_snippets": "true", "result_filter": "web"}
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": _key()}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(SEARCH_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        # Sent, but no answer: Brave may have billed it, so the reservation stays (ai_budget unknown-billing allowance).
        await ai_budget.unknown(reservation)
        await _record("search_" + ("timeout" if isinstance(exc, httpx.TimeoutException) else "transport_error"), QUERY_USD, **meta)
        raise SearchUnavailable("search_timeout" if isinstance(exc, httpx.TimeoutException) else "search_transport_error") from None
    if response.status_code != 200:
        code = {400: "search_bad_request", 401: "search_unauthorized", 403: "search_forbidden", 422: "search_bad_request",
                429: "search_rate_limited"}.get(response.status_code, "search_upstream_error")
        if response.status_code >= 500:
            await ai_budget.unknown(reservation)
            await _record(code, QUERY_USD, **meta)
        else:
            await ai_budget.settle(reservation, 0.0)   # refused before any result: not billed
            await _record(code, 0.0, **meta)
        raise SearchUnavailable(code)
    try:
        payload = response.json()
    except ValueError:
        await ai_budget.settle(reservation, QUERY_USD)
        await _record("search_invalid_json", QUERY_USD, **meta)
        raise SearchUnavailable("search_invalid_json") from None
    await ai_budget.settle(reservation, QUERY_USD)
    await _record("ok", QUERY_USD, **meta)
    return _results(payload)
