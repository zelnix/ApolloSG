"""ApolloSG Settings → AI Provider & Model: the one provider and model every AI investigation call uses.

Magnum DI and TC Hawkeye both use this one selection; TC Hawkeye has no selection of its own. Ask Higgins makes no AI call.
The selection is stored in the database, so it applies from the next investigation on every server process and survives
restarts and redeploys. Who changed it and when is stored with it, and each change is written to the admin audit log.
An investigation keeps the model it started with (repository.create_job), so a change never alters existing results.

A model can be selected only when it is approved here AND can do everything an investigation needs (REQUIRED): the
fixed answer shape, reading images sent as evidence, and web search with sources. Its provider also needs a connected
adapter (services/higgins/adapters) and an API key on the server. Keys stay in server configuration: this module only
says whether one is set, never its value.

Nothing here ever switches model. If the selected model can't be used, the investigation fails and says why.
"""
from __future__ import annotations

import os
from typing import Optional

from core.db import db, now_utc
from services.higgins import adapters

COLLECTION = "apollo_settings"
SETTING = "ai_investigation_model"
LEGACY_COLLECTION = "gemini_model_choices"  # the old per-feature Gemini Map choice; read once for continuity

# What an investigation asks of the model, and how a missing one is shown to the admin.
REQUIRED = {"json": "can't return ApolloSG's fixed answer shape",
            "vision": "can't read images sent as evidence",
            "search": "can't search the web with sources"}

_FULL = frozenset({"text", "vision", "audio_input", "functions", "search", "json"})
_LITE = frozenset({"text", "json"})  # text + fixed answer shape only: no web search, no images
# Claude and OpenAI: text and image input, function calling, web search with sources and structured output, per each
# model's published page. No audio input.
_TEXT_IMAGE = frozenset({"text", "vision", "functions", "search", "json"})

# The approved models for each provider, with what each can do. A provider with no approved models yet is
# listed so the admin can see it, but nothing can be selected for it.
PROVIDERS: dict[str, dict] = {
    "gemini": {"label": "Google Gemini", "key_env": ("GEMINI_API_KEY", "GEMINI_DEV_API_KEY"), "models": {
        # Per the model card: text/image/video/audio/PDF in, function calling, Search grounding and structured
        # outputs are all supported on 3.1 Flash-Lite.
        "gemini-3.1-flash-lite": _FULL,
        "gemini-3.5-flash": _FULL,
        "gemini-3.8-flash": _FULL,
        "gemini-3-flash-preview": _FULL,
        "gemini-2.5-flash": _FULL,
        "gemini-2.5-pro": _FULL,
        "gemini-3.1-pro-preview": _FULL,
        "gemini-2.5-flash-lite": _LITE,
        "gemini-3.5-flash-lite": _LITE,
    }},
    "anthropic": {"label": "Anthropic Claude", "key_env": ("ANTHROPIC_API_KEY",), "models": {
        "claude-haiku-5-5": _TEXT_IMAGE,
        "claude-sonnet-5-5": _TEXT_IMAGE,
        "claude-opus-5-5": _TEXT_IMAGE,
    }},
    "openai": {"label": "OpenAI", "key_env": ("OPENAI_API_KEY",), "models": {
        "gpt-5.6-luna": _TEXT_IMAGE,
        "gpt-5.4-mini": _TEXT_IMAGE,
        "gpt-5.6-terra": _TEXT_IMAGE,
        "gpt-5.4": _TEXT_IMAGE,
        "gpt-5.6-sol": _TEXT_IMAGE,
        "gpt-5.5": _TEXT_IMAGE,
    }},
}
DEFAULT = {"provider": "gemini", "model": "gemini-3.1-flash-lite"}

# The last selection this process read or saved, for the admin portal's page banner (which can't wait on the database).
_last_known: dict = dict(DEFAULT)


def provider_of(model: str) -> Optional[str]:
    return next((pid for pid, p in PROVIDERS.items() if model in p["models"]), None)


def label(provider: str) -> str:
    return PROVIDERS.get(provider, {}).get("label", provider)


def capabilities(model: str) -> frozenset:
    provider = provider_of(model)
    return PROVIDERS[provider]["models"][model] if provider else frozenset()


def key_configured(provider: str) -> bool:
    return any(os.environ.get(name, "").strip() for name in PROVIDERS.get(provider, {}).get("key_env", ()))


def unavailable(provider: str, model: str) -> list[str]:
    """Why this model can't be selected for investigations; empty when it can."""
    if provider not in PROVIDERS or model not in PROVIDERS[provider]["models"]:
        return ["isn't an ApolloSG-approved model"]
    caps = PROVIDERS[provider]["models"][model]
    reasons = [why for need, why in REQUIRED.items() if need not in caps]
    if provider not in adapters.ADAPTERS:
        reasons.append(f"ApolloSG isn't connected to {label(provider)} yet")
    if not key_configured(provider):
        reasons.append(f"no {label(provider)} API key is set on the server")
    return reasons


def options() -> list[dict]:
    """Every provider with its approved models, cheapest first, each marked available or not (and why)."""
    from services.gemini_usage import MODEL_PRICING
    out = []
    for pid, p in PROVIDERS.items():
        models = sorted(p["models"], key=lambda m: (m not in MODEL_PRICING, MODEL_PRICING.get(m, {}).get("input", 0), m))
        out.append({"id": pid, "label": p["label"], "connected": pid in adapters.ADAPTERS, "keyConfigured": key_configured(pid),
                    "models": [{"id": m, "price": MODEL_PRICING.get(m), "reasons": unavailable(pid, m)} for m in models]})
    return out


async def selection() -> dict:
    """The selected provider and model, who changed it and when. `default` is True while nobody has changed it."""
    global _last_known
    doc = await db[COLLECTION].find_one({"setting": SETTING}, {"_id": 0})
    if doc:
        value = {"provider": doc["provider"], "model": doc["model"], "changed_by": doc.get("changed_by"),
                 "changed_at": doc.get("changed_at"), "default": False}
    else:
        # Before this setting existed, an admin picked Magnum DI's Gemini model on the Gemini Map: that stays in force.
        legacy = await db[LEGACY_COLLECTION].find_one({"feature": "magnum_di"}, {"_id": 0})
        if legacy and provider_of(legacy.get("model", "")):
            value = {"provider": provider_of(legacy["model"]), "model": legacy["model"], "changed_by": legacy.get("changed_by"),
                     "changed_at": legacy.get("changed_at"), "default": False}
        else:
            value = {**DEFAULT, "changed_by": None, "changed_at": None, "default": True}
    _last_known = value
    return value


async def investigation_model() -> str:
    """The model the next Magnum DI or TC Hawkeye call uses — exactly as selected, never substituted."""
    return (await selection())["model"]


def last_known() -> dict:
    return _last_known


async def choose(provider: str, model: str, email: str) -> dict:
    """Save an admin's selection and return the one it replaces. A model that can't be used is refused (ValueError)."""
    global _last_known
    reasons = unavailable(provider, model)
    if reasons:
        raise ValueError(f"{model or 'that model'} {'; '.join(reasons)}")
    before = await selection()
    now = now_utc()
    await db[COLLECTION].update_one({"setting": SETTING}, {"$set": {"provider": provider, "model": model, "changed_by": email,
                                                                   "changed_at": now}}, upsert=True)
    _last_known = {"provider": provider, "model": model, "changed_by": email, "changed_at": now, "default": False}
    return before
