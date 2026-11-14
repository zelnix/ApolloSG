"""Shared check-evaluation helpers (Finding D).

Functions extracted from decide.py that are also needed by finding_rules.py.
Keeping them here breaks the deferred-import cycle between those two modules
without touching any public API: decide.py re-exports everything from here for
backward compatibility.

Dependencies: only triage.py and brand_domains — no imports from decide.py or
finding_rules.py, so this module sits at the bottom of the tc_flyby import graph.
"""
from __future__ import annotations

from services.higgins.brand_domains import registrable
from services.higgins.tc_hawkeye.triage import CONSEQUENTIAL, Check, Plan, digits

#: What may corroborate an impersonation: a warning sign or a weak signal about the same link.
CORROBORATES = ("concern", "anomaly", "weak")


def _live(plan_: Plan) -> list[tuple[Check, dict]]:
    return [(c, f) for c in plan_.checks for f in c.facts if f["class"] == "live_evidence"]


def corroborated_impersonation(plan_: Plan) -> list[dict]:
    """The material names an organisation, a link in it isn't that organisation's own (not one of its
    published domains or country sites), and an independent fact about that same link backs it up.

    An organisation merely *mentioned* in a legitimate sender's material is not impersonation.
    Two guards:

    1. **Verified sender**: when another brand's impersonation check resolved clear (the material's
       links genuinely belong to that brand), an 'unrelated' domain mismatch for a different brand
       is expected and is excluded — the sender is identified, the other brand is just mentioned.

    2. **Corroboration strength**: a domain that doesn't carry the brand's name at all (topic
       'impersonation', i.e. the classify() result was 'unrelated') needs concern-level
       corroboration.  Shared-service URLs also need concern-level corroboration: legitimate organisations use them.
       A lookalike registrable domain retains its existing protection.
    """
    verified_sender = {
        c.subject for c in plan_.checks
        if c.kind == "impersonation" and c.status == "resolved"
        and any(f["signal"] == "clear" for f in c.facts)
    }

    mismatched: list[dict] = []
    for c in plan_.checks:
        if c.kind != "impersonation":
            continue
        for f in c.facts:
            if f.get("topic") not in ("impersonation", "lookalike", "shared_service"):
                continue
            if f.get("topic") == "impersonation" and verified_sender and c.subject not in verified_sender:
                continue
            mismatched.append(f)

    if not mismatched:
        return []

    places = {registrable(f["place"]) for f in mismatched if f.get("place")}

    strong_places = {
        registrable(f["place"]) for f in mismatched
        if f.get("place") and f.get("topic") == "lookalike"
    }
    unrelated_places = places - strong_places

    support: list[dict] = []
    for c in plan_.checks:
        if c.kind != "link" or registrable(c.subject) not in places:
            continue
        for f in c.facts:
            if f["class"] != "live_evidence":
                continue
            reg = registrable(c.subject)
            if reg in strong_places and f["signal"] in CORROBORATES:
                support.append(f)
            elif reg in unrelated_places and f["signal"] == "concern":
                support.append(f)

    lookalike_mismatched = [f for f in mismatched if f.get("topic") == "lookalike"]
    if lookalike_mismatched:
        return lookalike_mismatched + support

    return mismatched + support if support else []


def official_routes(plan_: Plan) -> bool:
    """Every link and address in the material belongs to the organisation it names."""
    impersonation = [c for c in plan_.checks if c.kind == "impersonation"]
    return bool(impersonation) and all(
        c.status == "resolved" and not any(f["signal"] == "anomaly" for f in c.facts)
        for c in impersonation
    )


def verified(target: str, plan_: Plan) -> bool:
    """An official source established that this route belongs to the organisation."""
    low = target.lower()
    for c in plan_.checks:
        if c.kind == "link" and c.subject in low:
            return any(f["decisive"] and f["signal"] == "clear" for f in c.facts)
        if c.kind == "email" and c.subject.lower() == low:
            return any(f["signal"] == "clear" for f in c.facts)
        if c.kind == "phone" and digits(c.subject)[-8:] and digits(c.subject)[-8:] == digits(target)[-8:]:
            return any(f["signal"] == "clear" for f in c.facts)
    return False


def unverified_requests(plan_: Plan) -> list[dict]:
    """Consequential requests whose routes aren't all verified as official."""
    out = []
    for r in plan_.entities.requests:
        consequential = r["type"] in CONSEQUENTIAL or (
            r["type"] == "call_back" and bool(plan_.entities.brands or plan_.entities.self_identified_sender)
        )
        if consequential and not (r["targets"] and all(verified(t, plan_) for t in r["targets"])):
            out.append(r)
    return out
