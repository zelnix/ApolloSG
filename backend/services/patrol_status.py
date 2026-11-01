"""Whether a Patrol record is closed, and whether the person closed it. Mirror: frontend src/domain/patrolStatus.ts.

closed:  resolved, trusted or carrying a resolved time. A migration or re-judge never reopens a closed record.
handled: the person's own decision — trusted, or resolved while Apollo still had a concern (a record Apollo resolved
         itself is resting). An investigation's answer never reopens a handled record either; only the person can.
Pure: no I/O.
"""
from __future__ import annotations


def closed(doc: dict) -> bool:
    return doc.get("status") in ("resolved", "trusted") or bool(doc.get("resolved_at"))


def handled(doc: dict) -> bool:
    return doc.get("status") == "trusted" or (doc.get("status") == "resolved" and doc.get("state") != "resting")
