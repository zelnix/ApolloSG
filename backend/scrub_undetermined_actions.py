#!/usr/bin/env python3
"""One-time migration: strip hallucinated brand contact instructions from historical
investigation_cases and investigation_turn_commits where outcome is unable_to_determine
(or the legacy equivalent no_scam_indicators).

The same guard is now applied at generation time in validation.py, so only records
committed before that fix need scrubbing.

Usage
-----
Dry run (default — prints what it would change, touches nothing):
    cd /app/backend && python scrub_undetermined_actions.py

Apply changes:
    cd /app/backend && python scrub_undetermined_actions.py --apply
"""
from __future__ import annotations

import asyncio
import re
import sys
import os

# Put /app/backend on the path before importing any project modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# core.config is imported implicitly via core.db; it calls load_dotenv() for us.
from core.db import db  # noqa: E402
from services.higgins.repository import enc_json, dec_json  # noqa: E402

# ── Same regex used in validation.py UNDETERMINED GUARD ──────────────────────
_CONTACT_RE = re.compile(
    r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'    # email address  (e.g. phish@nab.com.au)
    r'|\+?\d[\d ()-]{6,16}\d(?![\w.%])',  # phone number
    re.I,
)

# Both the current code and its legacy predecessor
UNDETERMINED_OUTCOMES = {"unable_to_determine", "no_scam_indicators"}

# Fernet raises InvalidToken when a record was encrypted with a rotated key — expected
# for old records.  Skip them silently rather than counting as an error.
try:
    from cryptography.fernet import InvalidToken as _InvalidToken
except ImportError:  # safety net if the import path ever changes
    _InvalidToken = Exception


# ── Scrub helpers ─────────────────────────────────────────────────────────────

def _scrub_response(response: dict) -> tuple[dict, int]:
    """Remove actions whose instruction contains contact info.

    Returns (possibly-updated response dict, number of actions dropped).
    If nothing changed, returns the original dict unchanged (not a copy).
    """
    outcome = response.get("outcome")
    if outcome not in UNDETERMINED_OUTCOMES:
        return response, 0

    actions = response.get("actions") or []
    if not actions:
        return response, 0

    clean = [a for a in actions if not _CONTACT_RE.search(a.get("instruction") or "")]
    dropped = len(actions) - len(clean)
    if dropped == 0:
        return response, 0

    # Recalculate recommendedActionId: keep it if it survived; otherwise fall
    # back to the first remaining action, or None when nothing is left.
    recommended_id = response.get("recommendedActionId")
    clean_ids = {a["id"] for a in clean}
    if recommended_id not in clean_ids:
        recommended_id = clean[0]["id"] if clean else None

    updated = {**response, "actions": clean, "recommendedActionId": recommended_id}
    return updated, dropped


# ── Collection scrapers ───────────────────────────────────────────────────────

async def scrub_cases(dry_run: bool) -> dict:
    """Scan investigation_cases.response_ciphertext and remove contact actions."""
    total = scrubbed = errors = skipped = 0

    cursor = db.investigation_cases.find(
        {"response_ciphertext": {"$exists": True, "$ne": None}, "deleted": False},
        {"_id": 1, "case_id": 1, "response_ciphertext": 1},
    )
    async for doc in cursor:
        total += 1
        try:
            response = dec_json(doc["response_ciphertext"])
            updated, dropped = _scrub_response(response)
            if dropped > 0:
                if not dry_run:
                    await db.investigation_cases.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"response_ciphertext": enc_json(updated)}},
                    )
                scrubbed += 1
                prefix = "[DRY RUN] Would scrub" if dry_run else "Scrubbed"
                print(f"  {prefix}: case {doc.get('case_id')} — dropped {dropped} contact action(s)")
        except _InvalidToken:
            # Encrypted with a rotated key — cannot read, will expire naturally.
            skipped += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ERROR: case {doc.get('case_id')}: {type(exc).__name__}: {exc}", file=sys.stderr)

    return {"total": total, "scrubbed": scrubbed, "skipped": skipped, "errors": errors}


async def scrub_turn_commits(dry_run: bool) -> dict:
    """Scan investigation_turn_commits.commit_ciphertext and remove contact actions."""
    total = scrubbed = errors = 0

    cursor = db.investigation_turn_commits.find(
        {"commit_ciphertext": {"$exists": True, "$ne": None}},
        {"_id": 1, "case_id": 1, "turn_id": 1, "commit_ciphertext": 1},
    )
    async for doc in cursor:
        total += 1
        try:
            commit = dec_json(doc["commit_ciphertext"])
            response = commit.get("response") or {}
            updated_resp, dropped = _scrub_response(response)
            if dropped > 0:
                commit_updated = {**commit, "response": updated_resp}
                if not dry_run:
                    await db.investigation_turn_commits.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"commit_ciphertext": enc_json(commit_updated)}},
                    )
                scrubbed += 1
                prefix = "[DRY RUN] Would scrub" if dry_run else "Scrubbed"
                print(f"  {prefix}: turn_commit {doc.get('turn_id')} (case {doc.get('case_id')}) — dropped {dropped} contact action(s)")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ERROR: turn_commit {doc.get('turn_id')}: {exc}", file=sys.stderr)

    return {"total": total, "scrubbed": scrubbed, "errors": errors}


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> int:
    dry_run = "--apply" not in sys.argv
    mode_label = "DRY RUN (pass --apply to commit changes)" if dry_run else "APPLYING CHANGES"
    print(f"\n=== Scrub hallucinated contact info from undetermined cases ({mode_label}) ===\n")

    print("→ Scanning investigation_cases …")
    cases = await scrub_cases(dry_run)
    print(f"  Cases scanned: {cases['total']}, to scrub: {cases['scrubbed']}, key-rotated (skipped): {cases['skipped']}, errors: {cases['errors']}\n")

    print("→ Scanning investigation_turn_commits …")
    commits = await scrub_turn_commits(dry_run)
    print(f"  Commits scanned: {commits['total']}, to scrub: {commits['scrubbed']}, errors: {commits['errors']}\n")

    total = cases["scrubbed"] + commits["scrubbed"]
    if dry_run:
        if total > 0:
            print(f"DRY RUN complete: {total} document(s) would be updated.")
            print("Re-run with --apply to commit the changes.")
        else:
            print("DRY RUN complete: no documents found with hallucinated contact info. Nothing to do.")
    else:
        print(f"Done: {total} document(s) updated.")

    return cases["errors"] + commits["errors"]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
