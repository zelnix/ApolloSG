"""Apollo Privacy Simplification — outcome regression tests.

«Protect the person. Preserve the evidence. Share only what is necessary.»
These tests protect outcomes, not implementation ceremony."""
import asyncio
import copy
import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.higgins.adapters import gemini as gemini_adapter  # noqa: E402
from services.higgins.ai_request import Part  # noqa: E402

from services.higgins import provider  # noqa: E402
from services.higgins.provider import generate as _real_generate  # noqa: E402  (captured before the autouse live-call blocker)
from services.higgins.llm_boundary import Purpose, enforce_boundary, validate_outbound_payload  # noqa: E402

SCAM = ("URGENT from AusPost: your parcel is held. Pay at https://auspost-redelivery.example/pay "
        "or call +61 2 9000 1234. Your password is Hunter2!x and code 482913. "
        "Contact jane.victim@gmail.com")


def test_credentials_removed_before_external_transmission():
    for purpose in Purpose:
        out = enforce_boundary(purpose, SCAM)
        assert "Hunter2!x" not in out, purpose
        assert not any("password" in v.lower() for v in validate_outbound_payload(purpose, out)), purpose


def test_threat_indicators_survive_investigation_processing():
    out = enforce_boundary(Purpose.INVESTIGATION, SCAM)
    for indicator in ("https://auspost-redelivery.example/pay", "AusPost", "+61 2 9000 1234", "jane.victim@gmail.com"):
        assert indicator in out, indicator


def test_research_minimises_personal_identifiers_but_keeps_indicators():
    out = enforce_boundary(Purpose.RESEARCH, SCAM)
    assert "auspost-redelivery.example" in out and "AusPost" in out
    assert "jane.victim@gmail.com" not in out


def test_research_minimisation_is_not_applied_to_investigation():
    assert "jane.victim@gmail.com" in enforce_boundary(Purpose.INVESTIGATION, SCAM)


def test_privacy_processing_does_not_modify_original_evidence():
    original = {"sender": "+61 400 111 222", "password": "hunter22", "name": "Jane"}
    snapshot = copy.deepcopy(original)
    enforce_boundary(Purpose.TRIAGE, original)
    assert original == snapshot


def test_gemini_boundary_screens_a_copy_and_leaves_caller_parts_untouched(monkeypatch):
    """Every Gemini request goes through provider.generate(); the caller's Parts are never rewritten."""
    sent = {}

    class _Models:
        async def get(self, *, model):
            return type("Info", (), {"input_token_limit": 1_000_000, "output_token_limit": 8192})()

        async def count_tokens(self, *, model, contents):
            return type("Count", (), {"total_tokens": 100})()

        async def generate_content(self, *, model, contents, config):
            sent["contents"] = contents
            raise RuntimeError("stop after capture")

    class _Client:
        class aio:  # noqa: N801
            models = _Models()

    monkeypatch.setattr(gemini_adapter, "client", lambda: _Client())
    monkeypatch.setattr(gemini_adapter, "_model_limits", {})
    monkeypatch.setattr(provider, "_preview_generate", None)  # the live path is what this test captures

    async def _no_usage(*_a, **_k):  # keep the shared DB client off this test's private event loop
        return None
    monkeypatch.setattr(provider, "_record_usage", _no_usage)
    # The daily spending limit's reservation uses the shared DB client too; this test is about what is sent.
    monkeypatch.setattr(provider.ai_budget, "reserve", _no_usage)
    monkeypatch.setattr(provider.ai_budget, "settle", _no_usage)
    monkeypatch.setattr(provider.ai_budget, "unknown", _no_usage)
    monkeypatch.delenv("APOLLO_FORBID_PROVIDER_CALLS", raising=False)
    part = Part(text=SCAM)
    try:
        # Private loop: asyncio.run() would clear the shared event loop that other test modules rely on.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_real_generate("sys", [part], model="gemini-3.1-flash-lite", purpose=Purpose.INVESTIGATION, correlation_id="t"))
        finally:
            loop.close()
    except Exception as exc:  # noqa: BLE001
        sent.setdefault("error", repr(exc))
    assert part.text == SCAM, "caller's original evidence Part must not be modified"
    assert "contents" in sent, f"generate() must reach the Gemini transport in this test: {sent}"
    assert "Hunter2!x" not in str(sent["contents"])


def test_submitted_image_needs_no_approval_ceremony():
    """Submitting an image authorises its analysis: the screenshot endpoints take no status/digest fields."""
    import inspect
    from routers import analysis
    for fn in (analysis.vision_investigate,):
        params = inspect.signature(fn).parameters
        assert "sanitization_status" not in params and "sanitization_digest" not in params
