"""Admin "Reset Stats": permanently deletes ApolloSG's usage and cost records and sets every count back to zero, so a
test round starts from nothing. Device identities, family links and Family Help sessions, saved reports, Higgins
history, the knowledge base itself, blocklists and the admin audit log are kept."""
from __future__ import annotations

from core.db import db, now_utc

# AI calls and their cost (Usage & Costs, Magnum DI, Reconciliation, Investigations, Diagnostics), Triage screening
# decisions and cost, web-search usage, and the Intelligence Reuse counts.
USAGE_COLLECTIONS = ("gemini_usage", "triage_results", "trusted_search_usage", "intel_reuse_metrics")

# What the admin sees on the page before pressing the button, in the order it is done.
WHAT_IS_RESET = (
    "Every AI call and its cost (Usage & Costs, Magnum DI, Reconciliation, Investigations, Diagnostics)",
    "Triage screening decisions and their cost",
    "Web-search usage and the Intelligence Reuse counts",
    "Finished investigation records (open ones are left alone)",
    "Knowledge Base and Intelligence Reuse hit counts (the entries stay)",
    "Every device's counts: TC Hawkeye, Magnum DI, Ask Higgins, device checks, Learn read, scam alerts read",
)
WHAT_IS_KEPT = ("devices", "family links and Family Help sessions", "saved reports", "Higgins history",
                "the knowledge base", "blocklists", "the admin audit log")


async def reset_stats() -> dict[str, int]:
    """Returns how many records each step deleted or zeroed."""
    now = now_utc()
    done: dict[str, int] = {}
    for name in USAGE_COLLECTIONS:
        done[name] = (await db[name].delete_many({})).deleted_count
    # Past its 15-minute window an investigation is only a record of what ran (gates, who answered, cost routing).
    done["investigation_cases"] = (await db.investigation_cases.delete_many({"expires_at": {"$lte": now}})).deleted_count
    done["knowledge_hits"] = (await db.higgins_knowledge.update_many({"hits": {"$gt": 0}}, {"$set": {"hits": 0}})).modified_count
    done["reuse_hits"] = (await db.reusable_intelligence.update_many({"hits": {"$gt": 0}}, {"$set": {"hits": 0}})).modified_count
    done["device_counts"] = (await db.devices.update_many({"stats": {"$exists": True}}, {"$unset": {"stats": ""}})).modified_count
    return done
