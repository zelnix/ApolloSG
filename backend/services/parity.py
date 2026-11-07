"""Environment parity fingerprint: what this server runs and serves, with no secret values.

Preview and production are separate servers with separate databases and settings. Comparing this
fingerprint from both (scripts/parity_check.py) shows exactly where production would behave differently
from what was tested in preview: different code, a different Learn library, a feed one server can't read,
a different model or flag, a missing key, or broken file storage.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from core.db import db
from services import emergent_storage, feed_health
from services.higgins import ai_settings

ROOT = Path(__file__).resolve().parents[1]
_CODE_DIRS = ("core", "routers", "services", "content")
# Settings whose VALUES are safe to compare (no credentials).
SETTINGS = ("APOLLO_PREVIEW_SIMULATOR", "FAMILY_ASSIST_ENABLED",
            "FAMILY_ASSIST_TURN_PROVIDER")
# Credentials: only whether each one is set is reported — never the value.
CREDENTIALS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "EMERGENT_LLM_KEY", "SAFE_BROWSING_API_KEY", "VIRUSTOTAL_API_KEY", "IPQS_API_KEY",
               "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GMAIL_TOKEN_ENCRYPTION_KEY", "EMERGENT_EMAIL_KEY",
               "EMERGENT_PUSH_KEY", "URL_HMAC_SECRET", "RULE_SIGNING_PRIVATE_KEY", "INVESTIGATION_KEY_FILE",
               "CLOUDFLARE_TURN_KEY_ID", "OUTBOUND_PROXIES")


@lru_cache(maxsize=1)
def code_fingerprint() -> str:
    """One hash over the backend's code and content files, so two servers can tell whether they run the same build."""
    digest = hashlib.sha256()
    files = [ROOT / "server.py", *(p for d in _CODE_DIRS for p in (ROOT / d).rglob("*") if p.suffix in (".py", ".json"))]
    for path in sorted(f for f in files if f.is_file() and "__pycache__" not in f.parts):
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


async def _storage_ok() -> bool:
    try:
        await asyncio.wait_for(asyncio.to_thread(emergent_storage.init_storage), timeout=15)
        return True
    except Exception:  # noqa: BLE001 — any failure means article images can't load on this server
        return False


async def snapshot() -> dict:
    published = await db.learning_articles.find({"status": "published", "deleted_at": None},
                                                {"_id": 0, "slug": 1, "source_type": 1, "language": 1, "thumbnail_path": 1}).to_list(5000)
    curated = sorted(row["slug"] for row in published if row.get("source_type") == "owner_curated")
    by_source: dict[str, int] = {}
    for row in published:
        by_source[row.get("source_type") or "unknown"] = by_source.get(row.get("source_type") or "unknown", 0) + 1
    feeds = await feed_health.snapshot()
    return {
        "code": code_fingerprint(),
        "learn": {
            "published": len(published),
            "shownOnLearnScreen": sum(row.get("language") == "en-AU" for row in published),  # the screen asks for en-AU
            "bySourceType": dict(sorted(by_source.items())),
            "curatedCount": len(curated),
            "curatedLibrary": hashlib.sha256("\n".join(curated).encode()).hexdigest()[:16],
            "withoutThumbnail": sum(not row.get("thumbnail_path") for row in published if row.get("language") == "en-AU"),
        },
        "feeds": {row["feedId"]: {"status": row["status"], "via": row["relay"] or "direct"} for row in feeds["feeds"]},
        "settings": {name: os.environ.get(name) or None for name in SETTINGS},
        # The AI investigation provider and model, as selected in ApolloSG Settings (stored per server, in its own
        # database). Magnum DI and TC Hawkeye both use it.
        "aiModel": {key: (await ai_settings.selection())[key] for key in ("provider", "model")},
        "credentialsSet": {name: bool(os.environ.get(name)) for name in CREDENTIALS},
        "fileStorage": "ok" if await _storage_ok() else "failing",
    }
