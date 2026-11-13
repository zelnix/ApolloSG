"""Evidence sufficiency for automatic text investigation admission.

This is not a scam verdict. It uses only submitted content, without network calls,
and never converts an unavailable intelligence result into a clean finding.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.higgins.tc_flyby.triage import extract


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason: str
    explanation: str = ""


def background_text_ready(text: str, *, sender: str = "", content_complete: bool = True) -> Readiness:
    """Admit material with a concrete investigable subject or consequential request.

    A truncated message can still contain sufficient evidence; truncation is
    separately retained on the case and must never be hidden.
    """
    if not text or not text.strip():
        return Readiness(False, "no_message_content", "I can’t begin an investigation because there’s no message content to examine. Please share the message or another piece of evidence.")
    entities = extract(text)
    if entities.urls or entities.hosts or entities.emails or entities.payment_details:
        return Readiness(True, "investigable_identifier")
    if entities.abns or entities.acns or entities.licences or entities.companies:
        return Readiness(True, "investigable_registration_or_company")
    if any(request.get("type") in (
        "payment", "credentials", "personal_details", "remote_access",
        "gift_cards_crypto", "payment_details_change", "call_back",
        "open_link", "reply",
    ) for request in entities.requests):
        return Readiness(True, "consequential_or_actionable_request")
    if entities.mule_signal or entities.severe_manipulation:
        return Readiness(True, "investigable_message_conduct")
    # A sender label alone, a generic time/number, or an intelligence-provider
    # failure is not sufficient evidence to investigate a particular claim.
    return Readiness(False, "no_investigable_subject", "I can’t begin an investigation from this information alone. Please share the message, link, request, or other details you want me to check.")
