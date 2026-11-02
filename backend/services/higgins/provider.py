"""The single AI gateway. Every AI call ApolloSG makes goes through generate() here.

ApolloSG investigation → this gateway → the selected provider's adapter (services/higgins/adapters) → the selected model.
Feature code never imports a provider SDK: it builds a neutral request (services/higgins/ai_request.py) and passes the
model ApolloSG Settings selected (services/higgins/ai_settings.py). The gateway works out the provider from the model.

Every check runs here, whatever the provider: the model is approved and can do what the call needs (fixed answer shape,
images, web search), images go only with an authorised purpose, credentials are stripped and the privacy boundary is
applied to every text part, usage is recorded, and the DI transaction record is written. No prompt/response logging,
no hidden-reasoning display, no implicit model or provider switch, no SDK retries. A Magnum DI investigation makes at
most one call through this gateway for the whole correlated case (see coordinator.py), and there is no retry.

SPENDING LIMITS (services/ai_budget.py): before a live call is sent its estimated cost is reserved against ApolloSG's
daily limits in one atomic update — the total limit, and for automatic checks their share of it. A call that would go
over is refused with `budget_limit` and nothing is sent. After the call the reservation is settled to the cost of the
usage the provider reported; when the billing outcome isn't known (a timeout, a dropped connection, no usage) the
estimate stays held. Each call's usage record carries its model, purpose, time, device, case, job, input / candidate /
thinking / cached tokens, web searches and estimated cost (services/gemini_usage.py).

NO-FALLBACK CONTRACT:
    In production every provider failure is reported exactly as-is — the error code, the HTTP status, the finish
    reason. There is no simulation fallback, no mock substitute, no other model and no other provider. Higgins
    surfaces the honest failure to the person.

PREVIEW vs PRODUCTION — decided by where this server runs:
    Preview  — the Emergent preview workspace (its process manager sets APP_URL to a
               *.preview.emergentagent.com address), or APOLLO_PREVIEW_SIMULATOR=on. server.py
               installs the simulator at startup. generate() routes through it. No provider calls.
    Production — anything else. The published app is never served from the preview domain, and the
               workspace's APP_URL is never copied into a deployment's settings. _preview_generate
               stays None and cannot be installed. generate() calls the live provider.
    The preview/ directory IS deployed with the rest of the project, so its presence
    proves nothing; a missing or unrecognised address always means the live provider, never fake
    answers. (APOLLO_ENV is deliberately NOT used: an old "preview" value of it still
    sits in the deployment's secrets.)
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
import logging as _logging
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from services import ai_budget
from services.gemini_usage import call_cost
from services.gemini_usage import record_usage as _record_usage
from services.higgins import adapters, ai_settings
from services.higgins.ai_request import AIResult, Message, Part, ProviderFailure, _sanitise_diagnostic  # noqa: F401
from services.higgins.capacity import CALL_SECONDS, OUTPUT
from services.higgins.llm_boundary import Purpose, enforce_boundary, strip_credentials

_gateway_log = _logging.getLogger("apollo.gateway")

_PREVIEW_HOST_SUFFIX = ".preview.emergentagent.com"


def preview_environment() -> bool:
    """True only on the preview server: the Emergent preview workspace, or APOLLO_PREVIEW_SIMULATOR=on.

    The workspace is recognised by APP_URL, which its own process manager sets to the preview address.
    The published app is never served from *.preview.emergentagent.com, so production stays live."""
    if os.getenv("APOLLO_PREVIEW_SIMULATOR", "").strip().lower() == "on":
        return True
    host = (urlparse(os.getenv("APP_URL", "").strip()).hostname or "").lower()
    return host.endswith(_PREVIEW_HOST_SUFFIX)


# ── Preview handler slot ────────────────────────────────────────────────────
# Filled by services.higgins.preview.dispatch.install_preview_provider() at
# startup, and only when preview_environment() is true. Everywhere else this
# stays None and generate() calls the live provider.
_preview_generate = None


def get_provider_mode() -> str:
    """Return 'preview' or 'live' based on whether a preview handler is installed."""
    return "preview" if _preview_generate is not None else "live"


def register_preview_handler(handler) -> None:
    """Install the preview generate handler. Called at startup from preview/dispatch.py.
    Refuses outside an explicit preview environment, so the simulator can never answer in production."""
    global _preview_generate
    if not preview_environment():
        raise RuntimeError("The preview simulator can only be installed on the preview server.")
    _preview_generate = handler
    _gateway_log.info("preview handler registered")


def require_capability(model: str, capability: str) -> str:
    """The model's provider, once the model is approved, can do `capability` and its provider is connected.
    Anything else is refused before a request is built — never answered by another model."""
    provider_id = ai_settings.provider_of(model)
    if provider_id is None:
        raise ProviderFailure("provider_configuration", original_message=f"{model} isn't an ApolloSG-approved model.")
    if capability not in ai_settings.capabilities(model):
        raise ProviderFailure("provider_configuration", original_message=f"{model} can't do what this call needs ({capability}).")
    if provider_id not in adapters.ADAPTERS:
        raise ProviderFailure("provider_configuration",
                              original_message=f"ApolloSG isn't connected to {ai_settings.label(provider_id)} yet.")
    return provider_id


# Purposes that are authorised for binary (image/audio) content transmission.
_BINARY_AUTHORISED_PURPOSES = frozenset({
    Purpose.VISION_PREFLIGHT,
    Purpose.INVESTIGATION,
    # The Vision Gate exists to have the model look at the person's privacy-screened image.
    Purpose.VISION_INVESTIGATION,
    # Device setting screenshots are read to confirm the user configured the setting correctly.
    Purpose.DEVICE_SETTING_VERIFICATION,
})


def _contains_binary(contents: Any) -> bool:
    """Check whether contents include binary (non-text) parts."""
    if isinstance(contents, (str, bytes)):
        return isinstance(contents, bytes)
    if isinstance(contents, Part):
        return contents.data is not None
    if isinstance(contents, Message):
        return any(_contains_binary(p) for p in contents.parts)
    if isinstance(contents, list):
        return any(_contains_binary(item) for item in contents)
    return False


def _audit_payload(system: str, contents: Any, web_search: bool) -> dict:
    """Non-blocking audit of what is being sent, for cost attribution. A lightweight breakdown of the payload
    composition without copying content. Token estimates use ~4 chars/token as a rough heuristic."""
    rounds: list[dict] = []
    total_text_chars = total_binary_parts = 0
    for item in contents if isinstance(contents, list) else [contents]:
        if isinstance(item, Message):
            text_chars = sum(len(p.text) for p in item.parts if p.text)
            binary = sum(1 for p in item.parts if p.data is not None)
            rounds.append({"role": item.role or "unknown", "text_chars": text_chars, "est_tokens": text_chars // 4, "binary_parts": binary})
        elif isinstance(item, str):
            text_chars, binary = len(item), 0
            rounds.append({"role": "user", "text_chars": text_chars, "est_tokens": text_chars // 4})
        elif isinstance(item, Part):
            text_chars, binary = len(item.text or ""), int(item.data is not None)
            rounds.append({"role": "part", "text_chars": text_chars, "est_tokens": text_chars // 4, "binary_parts": binary})
        else:
            continue
        total_text_chars += text_chars
        total_binary_parts += binary
    system_chars = len(system) if system else 0
    return {"system_chars": system_chars, "system_est_tokens": system_chars // 4, "web_search": web_search,
            "content_rounds": len(rounds), "total_text_chars": total_text_chars,
            "total_est_tokens": (system_chars + total_text_chars) // 4, "total_binary_parts": total_binary_parts,
            "rounds": rounds[:20]}  # Cap to avoid bloating the record


def _screen(purpose: Purpose, contents: Any) -> Any:
    """The privacy boundary on every text part. Builds a separate analysis copy; the caller's evidence is never mutated."""
    def part(p: Any) -> Any:
        if isinstance(p, str):
            return enforce_boundary(purpose, p)
        return replace(p, text=enforce_boundary(purpose, p.text)) if isinstance(p, Part) and p.text else p
    if isinstance(contents, str):
        return enforce_boundary(purpose, contents)
    if isinstance(contents, list):
        return [Message(item.role, [part(p) for p in item.parts]) if isinstance(item, Message) else part(item) for item in contents]
    return contents


_DI_OWNERS: dict[str, str] = {}


def register_di_owner(correlation_id: str, owner: str) -> None:
    """Magnum DI tells the gateway which device owns a correlation id, so the DI record can be
    returned only to that device. Bounded to the most recent cases."""
    if not correlation_id or not owner:
        return
    _DI_OWNERS[correlation_id] = owner
    if len(_DI_OWNERS) > 500:
        for key in list(_DI_OWNERS)[:100]:
            _DI_OWNERS.pop(key, None)


def _owner_for(correlation_id: str | None) -> str | None:
    return _DI_OWNERS.get(correlation_id or "")


# Refusals the provider doesn't bill: the request was turned away before any answer was produced.
_NOT_BILLED_HTTP = frozenset({400, 401, 403, 404, 413, 422, 429})
_NOT_BILLED_CODES = frozenset({"rate_limited", "provider_configuration", "privacy_violation"})


def _billed_unknown(exc: ProviderFailure) -> bool:
    return not (exc.code in _NOT_BILLED_CODES or (exc.http_status or 0) in _NOT_BILLED_HTTP)


async def generate(system: str, contents: Any, *, model: str,
                   capability: str = "text", json_output: bool = False,
                   web_search: bool = False, timeout: float = CALL_SECONDS,
                   response_schema: dict | None = None,
                   purpose: Purpose,
                   correlation_id: str | None = None,
                   trigger_source: str | None = None,
                   device_id: str | None = None,
                   job_id: str | None = None) -> AIResult:
    """Single authoritative AI gateway. Every AI inference request MUST use this function.

    `model` is the one ApolloSG Settings selected (pinned on the investigation's job); it is called exactly as given.
    NO-FALLBACK CONTRACT: in production every provider failure is reported exactly as-is.

    Preview: the preview dispatch handles generate() calls — installed at startup.
    Production: no preview handler can be installed. This function calls the live provider only.
    """
    # ── Live provider and preview alike: every production check runs first ──
    # The simulator replaces ONLY the provider call below. Model approval and capability, image authorisation,
    # credential stripping and the privacy boundary all run before it, so a request production would
    # refuse is refused in preview too — preview can no longer pass what production rejects.
    provider_id = require_capability(model, capability)
    has_binary = _contains_binary(contents)
    if web_search:
        require_capability(model, "search")
    if has_binary:
        require_capability(model, "vision")

    call_id = str(uuid.uuid4())
    call_type = "generate_json" if json_output else "generate_text"
    t0 = time.monotonic()

    # ── Payload composition audit ──────────────────────────────────────
    # Captures what is being sent so per-call costs can be attributed to system prompt, evidence, rounds, etc.
    payload_audit = _audit_payload(system, contents, web_search)
    purpose_name = purpose.value if hasattr(purpose, "value") else str(purpose)
    device_id = device_id or _owner_for(correlation_id)
    case_id = (correlation_id or "").removeprefix("case-") if (correlation_id or "").startswith("case-") else None
    reservation: ai_budget.Reservation | None = None

    async def _track(success: bool, usage: dict | None = None, failure_code: str | None = None, search_queries: int | None = None):
        extra_data: dict = {"payload_audit": payload_audit, "search_tool": web_search}
        if search_queries is not None:
            extra_data["search_queries"] = search_queries
        if trigger_source:
            extra_data["trigger_source"] = trigger_source
        try:
            await _record_usage(record_id=call_id, correlation_id=correlation_id, model=model, provider=provider_id,
                                purpose=purpose_name, call_type=call_type,
                                success=success, failure_code=failure_code, usage_metadata=usage,
                                duration_ms=int((time.monotonic() - t0) * 1000), extra=extra_data,
                                device_id=device_id, case_id=case_id, job_id=job_id,
                                reservation_id=reservation.reservation_id if reservation else None)
        except Exception:
            _gateway_log.warning("ai_usage: failed to persist usage record %s", call_id, exc_info=True)

    if has_binary and purpose not in _BINARY_AUTHORISED_PURPOSES:
        raise ProviderFailure("privacy_violation", retryable=False)
    if has_binary:
        _gateway_log.info("gateway_binary: purpose=%s provider=%s model=%s capability=%s", purpose.value, provider_id, model, capability)

    if system:
        system = strip_credentials(system)
    contents = _screen(purpose, contents)

    # ── Preview: the simulator answers instead of the provider call ──
    if _preview_generate is not None:
        return await _preview_generate(
            system, contents, model=model, provider=provider_id, capability=capability,
            json_output=json_output, web_search=web_search, timeout=timeout,
            response_schema=response_schema, purpose=purpose,
            correlation_id=correlation_id, trigger_source=trigger_source)

    # ── Live provider ─────────────────────────────────────────────────────
    if os.getenv("APOLLO_FORBID_PROVIDER_CALLS") == "1":
        raise AssertionError("Live provider calls are prohibited in bounded tests")

    # Reserve the call's estimated cost against today's limits, atomically, before anything is sent.
    try:
        reservation = await ai_budget.reserve(
            ai_budget.estimate_call_usd(model, provider_id, payload_audit, web_search=web_search, max_output_tokens=OUTPUT.value),
            automated=ai_budget.automated(trigger_source), purpose=purpose_name, model=model, provider=provider_id,
            correlation_id=correlation_id, device_id=device_id, case_id=case_id, job_id=job_id)
    except ai_budget.BudgetExceeded as exc:
        await _track(False, failure_code="budget_limit")
        raise ProviderFailure("budget_limit", retryable=False, operation="spending_limit", original_message=str(exc)) from None

    adapter = adapters.ADAPTERS[provider_id]
    try:
        result = await asyncio.wait_for(adapter.invoke(model=model, system=system, contents=contents, json_output=json_output,
                                                       response_schema=response_schema, web_search=web_search), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await ai_budget.unknown(reservation)
        await _track(False, failure_code="timeout")
        raise ProviderFailure("provider_unavailable", retryable=True, operation="response_generation",
                              original_message=f"{ai_settings.label(provider_id)} API call timed out after {timeout}s") from exc
    except ProviderFailure as exc:
        if _billed_unknown(exc):
            await ai_budget.unknown(reservation)
        else:
            await ai_budget.settle(reservation, 0.0)
        await _track(False, failure_code=f"http_{exc.http_status}" if exc.code == "provider_configuration" and exc.http_status else exc.code)
        raise
    except Exception as exc:  # an adapter bug is still reported as the provider failing, never hidden
        await ai_budget.unknown(reservation)
        await _track(False, failure_code="provider_unavailable")
        raise ProviderFailure("provider_unavailable", retryable=True, original_message=str(exc)[:300] or None,
                              exception_type=type(exc).__name__) from exc

    # Track successful usage, with the number of web searches the model ran (each one is billed), and settle the
    # reservation to what the provider reported. No usage reported: the billing isn't known, so the estimate stays held.
    searches = search_query_count(result.grounding) if web_search else None
    if result.usage:
        await ai_budget.settle(reservation, call_cost(model, provider_id, result.usage, searches or 0))
    else:
        await ai_budget.unknown(reservation)
    await _track(True, usage=result.usage, search_queries=searches)

    # DI transaction record for the real call (production as well as preview).
    try:
        from services.higgins import di_record as _di
        await _di.save_di_record(
            correlation_id=correlation_id, owner=_owner_for(correlation_id),
            investigation_id=(correlation_id or "").removeprefix("case-") or None,
            model=model, provider=provider_id, purpose=purpose.value if hasattr(purpose, "value") else str(purpose),
            simulated=False, environment="Production", status="success",
            request=_di.describe_request(system, contents, web_search),
            response_text=result.text, finish_reason=result.finish_reason, usage=result.usage,
            duration_ms=int((time.monotonic() - t0) * 1000), retries=0, calls=1)
    except Exception:
        _gateway_log.warning("di_record: could not record live DI transaction", exc_info=True)
    return result


def search_query_count(grounding: dict | None) -> int:
    """How many web searches the model ran for one answer (from its grounding record)."""
    grounding = grounding or {}
    return len(grounding.get("web_search_queries") or grounding.get("webSearchQueries") or [])


async def generate_json(system: str, prompt: Any, **kwargs: Any) -> tuple[dict, dict]:
    result = await generate(system, prompt, json_output=True, **kwargs)
    return result.object(), result.metadata


async def generate_text(system: str, prompt: Any, **kwargs: Any) -> AIResult:
    return await generate(system, prompt, json_output=False, **kwargs)


def configuration(provider_id: str) -> dict:
    """How this server reaches the given provider. Says only whether its key is set — never the key."""
    preview_active = _preview_generate is not None
    name = ai_settings.label(provider_id)
    adapter = adapters.ADAPTERS.get(provider_id)
    return {"provider": f"{name} (preview)" if preview_active else name, "providerId": provider_id,
            "preview_active": preview_active, "connected": adapter is not None,
            "sdk": getattr(adapter, "SDK", None), "keyConfigured": ai_settings.key_configured(provider_id),
            "accountAccess": "Preview provider (no external calls)" if preview_active else getattr(adapter, "ACCOUNT", "Not connected"),
            "providerRetention": "Preview: no data leaves this server." if preview_active else getattr(adapter, "RETENTION", ""),
            "dataFlow": "Device -> ApolloSG service -> Preview provider (local)." if preview_active else
                        f"Device -> ApolloSG service -> {name} API."}
