"""Versioned transport/scheduling policy, not a claim about model capabilities."""
from dataclasses import asdict, dataclass
import asyncio
from functools import wraps
import inspect
import os

from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()


@dataclass(frozen=True)
class Bound:
    value: int
    unit: str
    purpose: str
    overflow: str


POLICY_VERSION = "2026-11-01.1"
TEXT = Bound(int(os.getenv("HIGGINS_MAX_TEXT_CHARACTERS", "262144")), "characters",
             "Bound transport allocation before provider token admission", "reject explicitly; never slice")
ITEMS = Bound(int(os.getenv("HIGGINS_MAX_ITEMS", "256")), "items",
              "Bound one request's inventory; additional batches require continuation", "reject explicitly; never slice")
OUTPUT = Bound(int(os.getenv("HIGGINS_OUTPUT_TOKENS", "16384")), "tokens",
               "Reserve response and reasoning within the provider's output limit", "non-STOP output is incomplete")
SCHEMA_RESERVE = Bound(1024, "tokens", "Conservative role/tool-wrapper overhead not exposed by Developer API token counting", "reject; do not trim context")

# ── Case Lifetime ───────────────────────────────────────────────────
# The server-side case record lives for 24 hours after creation. Within that window
# the investigation runs, the device picks up the result, and evidence is cleaned up.
# Processing timeout (WORK_SECONDS) is separate: a timeout stops work but preserves
# available findings. The case is never hard-cleared from the client while it holds
# committed findings.
CASE_LIFETIME_SECONDS = int(os.getenv("CASE_LIFETIME_SECONDS", str(24 * 3600)))  # 24 hours
LIFETIME_SECONDS = CASE_LIFETIME_SECONDS  # backward-compatible alias
TEMPORARY_RETENTION = "apollo_temporary"
WORK_SECONDS = 300
CALL_SECONDS = 90

# ── Retention Policy ───────────────────────────────────────────────────
# Submitted content (pictures, files, text): deleted from the server within 24 hours of its investigation finishing.
# A check that is still running is never cut off; the clock starts when it finishes.
EVIDENCE_RETENTION_SECONDS = int(os.getenv("EVIDENCE_RETENTION_SECONDS", str(24 * 3600)))  # 24 hours
# Device-local investigations: the server does NOT retain completed investigations.
# The server is a temporary processing workspace only; the device owns the durable record.
# Saved reports on device: retained for 90 days or until the storage cap requires oldest-first removal.
DEVICE_REPORT_RETENTION_DAYS = 90


def policy() -> dict:
    return {"version": POLICY_VERSION, "bounds": {k: asdict(v) for k, v in
            {"text": TEXT, "items": ITEMS, "output": OUTPUT, "schemaReserve": SCHEMA_RESERVE}.items()},
            "caseLifetimeSeconds": CASE_LIFETIME_SECONDS, "workSeconds": WORK_SECONDS,
            "evidenceRetentionSeconds": EVIDENCE_RETENTION_SECONDS}


def bounded_analysis(function):
    """Bound the complete compatibility request, including queued reputation/page work.

This is not durable job recovery. A timeout cancels descendants and reports non-completion,
never a verdict. Evaluate the original annotations to preserve FastAPI's body/form contract.
"""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await asyncio.wait_for(function(*args, **kwargs), timeout=WORK_SECONDS)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, 'The investigation work budget was reached. Not all evidence was processed; no complete conclusion is available.') from exc
    wrapped.__signature__ = inspect.signature(function, eval_str=True)
    return wrapped