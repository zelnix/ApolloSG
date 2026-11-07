"""What ApolloSG sends through its AI gateway, in no provider's terms.

Feature code (Magnum DI, TC Hawkeye) builds its request from these types and hands it to the gateway
(services/higgins/provider.generate). Only a provider adapter (services/higgins/adapters/) turns them into
a provider SDK's own types, so no feature code depends on Gemini, Claude or OpenAI.

- A request is a list of Messages; each Message holds Parts (text, or bytes with their media type).
- The required response shape is a JSON-schema dict (services/higgins/response_schema.py).
- Web search is a yes/no on the request; the adapter attaches its provider's own search tool.
- Every result's web-search record (`grounding`) uses one shape whatever the provider:
  {"grounding_chunks": [{"web": {"uri", "title", "domain"}}],
   "grounding_supports": [{"segment": {"start_index", "end_index", "text"}, "grounding_chunk_indices": [..]}],
   "web_search_queries": [..]}  (segment offsets are UTF-8 byte offsets into the answer text).
- Token usage uses these names: prompt_token_count, candidates_token_count, total_token_count,
  cached_content_token_count.
- A complete answer has finish_reason "STOP"; anything else is reported as incomplete.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Part:
    text: str | None = None
    data: bytes | None = None
    mime_type: str | None = None

    @classmethod
    def from_bytes(cls, *, data: bytes, mime_type: str) -> "Part":
        return cls(data=data, mime_type=mime_type)


@dataclass(frozen=True)
class Message:
    role: str
    parts: list[Part] = field(default_factory=list)


def _sanitise_diagnostic(text: str) -> str:
    """Redact API keys, tokens and sensitive data from diagnostic text."""
    text = re.sub(r'(key|token|secret|password|auth)[=:]\s*\S+', r'\1=<REDACTED>', text, flags=re.IGNORECASE)
    text = re.sub(r'AIza[A-Za-z0-9_-]{30,}', '<REDACTED_KEY>', text)
    text = re.sub(r'AQ\.[A-Za-z0-9_-]{20,}', '<REDACTED_KEY>', text)
    text = re.sub(r'sk-[A-Za-z0-9_-]{20,}', '<REDACTED_KEY>', text)
    text = re.sub(r'Bearer\s+\S+', 'Bearer <REDACTED>', text, flags=re.IGNORECASE)
    return text[:500] if len(text) > 500 else text


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, finish_reason: str | None = None,
                 http_status: int | None = None, original_message: str | None = None,
                 exception_type: str | None = None, operation: str | None = None):
        self.code, self.retryable, self.finish_reason = code, retryable, finish_reason
        self.http_status = http_status
        self.original_message = _sanitise_diagnostic(original_message) if original_message else None
        self.exception_type = exception_type
        self.operation = operation or "response_generation"
        super().__init__(code)


@dataclass
class AIResult:
    """One answer from the selected provider/model (or the preview simulator standing in for it)."""
    text: str
    finish_reason: str
    usage: dict[str, Any]
    grounding: dict[str, Any] | None
    model: str
    provider: str = "gemini"
    # True when the preview simulator produced this result instead of the provider. Carried through to
    # what is stored, so a simulated answer can never be recorded as a real one.
    simulated: bool = False

    @property
    def metadata(self) -> dict:
        return {"provider": "Preview simulator" if self.simulated else self.provider, "model": self.model,
                "finish_reason": self.finish_reason, "provider_complete": self.finish_reason == "STOP",
                "usage": self.usage, "grounding": self.grounding, "simulated": self.simulated}

    def object(self) -> dict:
        try:
            value = json.loads(self.text)
        except (ValueError, TypeError) as exc:
            raise ProviderFailure("response_invalid") from exc
        if not isinstance(value, dict):
            raise ProviderFailure("response_invalid")
        return value
