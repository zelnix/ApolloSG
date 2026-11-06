"""The deciding test — is the case resolved at TC FlyBy, or could Magnum DI change the result?

    Could deeper Magnum DI investigation or reasoning change Apollo's finding or Higgins' action?
        NO  → TC FlyBy resolves the case. "Unable to determine" is a valid finished outcome.
        YES → only the unresolved element, with the minimum context it needs, goes to Magnum DI.

No input format, case category or uncertainty sends a case to Magnum DI by itself. A screenshot or document
is investigated through the content Higgins Triage extracted from it, like any text. Magnum DI's additional
capabilities, and the only situations in which they can change the result:

    reading   — content Triage couldn't extract (Magnum DI reads images and pages directly), when nothing
                already established settles what to do;
    reasoning — the wording and tactics of a message that asks for something consequential (money,
                credentials, personal details, remote access, changed payment details, gift cards or crypto,
                a call-back on an organisation's behalf) through a route no official source verified, when
                nothing established settles it;
    relating  — a contradiction whose explanation could reverse the finding: a register entry under a
                related-but-different name; an organisation named beside a link or address that isn't its own
                with nothing else to go on; a scam pattern's wording beside the organisation's genuine links
                when the request still goes somewhere unverified.

Within the concern outcomes (Concerning, Likely scam, Confirmed scam or threat) Higgins' action is the same
protective one, so Magnum DI is never called to move a case between them. The triggers are still checked when a
concern outcome was reached: unread content could hold a request that calls for a different or additional step
(or show a provisional concern was a false positive), and a contradiction about the very facts a provisional concern
rests on could reverse it. Established threat evidence is never overridden.

Weak signals (a redirect to another site, a newly registered domain, a direct download, a third-party reputation
warning, text found copied elsewhere) never make a case Concerning, alone or together. They count only as the
independent corroboration an impersonation or another warning sign needs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.higgins.brand_domains import registrable
from services.higgins.tc_flyby import evidence_evaluation
from services.higgins.tc_flyby.triage import CONSEQUENTIAL, Check, Plan, digits

#: Signals that are warning signs (with "concern"). "weak" signals are never a warning sign by themselves.
WARNING = ("concern", "anomaly")
#: What may corroborate an impersonation: a warning sign or a weak signal about the same link.
CORROBORATES = ("concern", "anomaly", "weak")
_SECRET_ASK = re.compile(r"password|passcode|\bpin\b|one[- ]time|otp|verification\s+code|security\s+code|code\s+(?:we|you)|card\s+(?:number|details)|cvv", re.I)


@dataclass
class Decision:
    answered_by: str
    outcome: str | None        # Apollo's case outcome (outcomes.py); None for a general question
    basis: str                 # threat | pattern | impersonation | signals | clear | unknown | knowledge


@dataclass
class Issue:
    """One element only Magnum DI could settle, and the evidence items it needs to see for it."""
    capability: str            # reading | reasoning | relating
    text: str
    evidence_ids: list[str] = field(default_factory=list)
    check_id: str | None = None   # the planned check this settles, when there is one

    def wire(self) -> dict:
        return {"capability": self.capability, "text": self.text, "evidenceIds": self.evidence_ids, "checkId": self.check_id}


def _live(plan_: Plan) -> list[tuple[Check, dict]]:
    return [(c, f) for c in plan_.checks for f in c.facts if f["class"] == "live_evidence"]


def _ambiguous(f: dict) -> bool:
    """An organisation's name merely mentioned beside a link or address that isn't its own: on its own it could be
    a news link or someone's personal email, so it needs corroboration before it establishes anything. (An address
    that carries the organisation's name itself — a lookalike — is a warning sign without it.)"""
    return f.get("topic") in ("impersonation", "freemail")


def corroborated_impersonation(plan_: Plan) -> list[dict]:
    """The material names an organisation, a link in it isn't that organisation's own (not one of its published
    domains or country sites), and an independent fact about that same link backs it up (newly registered,
    flagged, redirected to another site, a direct download).

    An organisation merely *mentioned* in a legitimate sender's material is not impersonation. Two guards:

    1. **Verified sender**: when another brand's impersonation check resolved clear (the material's links
       genuinely belong to that brand), an 'unrelated' domain mismatch for a different brand is expected and
       is excluded — the sender is identified, the other brand is just mentioned.

    2. **Corroboration strength**: a domain that doesn't carry the brand's name at all (topic 'impersonation',
       i.e. the classify() result was 'unrelated') needs concern-level corroboration — an official warning or
       a decisive listing. Weak signals (newly registered, IPQS flag, redirect) don't establish impersonation
       when the domain makes no attempt to look like the brand. Lookalike and shared-service domains, which
       actively mimic the brand, are corroborated by any signal (the existing behaviour)."""
    # Brands whose impersonation check resolved clear: the material's links belong to that brand.
    verified_sender = {c.subject for c in plan_.checks
                       if c.kind == "impersonation" and c.status == "resolved"
                       and any(f["signal"] == "clear" for f in c.facts)}

    mismatched: list[dict] = []
    for c in plan_.checks:
        if c.kind != "impersonation":
            continue
        for f in c.facts:
            if f.get("topic") not in ("impersonation", "lookalike", "shared_service"):
                continue
            # Guard 1: if the sender is verified as another brand, an 'unrelated' mismatch for this brand
            # means it is merely mentioned — not impersonation.
            if f.get("topic") == "impersonation" and verified_sender and c.subject not in verified_sender:
                continue
            mismatched.append(f)

    if not mismatched:
        return []

    places = {registrable(f["place"]) for f in mismatched if f.get("place")}

    # Guard 2: per-place corroboration strength.
    # Lookalike / shared-service domains: any signal corroborates (concern, anomaly, weak).
    # Unrelated domains (topic "impersonation"): only concern-level signals corroborate.
    strong_places = {registrable(f["place"]) for f in mismatched
                     if f.get("place") and f.get("topic") in ("lookalike", "shared_service")}
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

    # ── Lookalike / shared-service self-corroboration ─────────────────────────
    # A domain that carries the brand's name (e.g. "commbank-secure.net") establishes
    # deceptive intent by its name alone.  A clean Safe Browsing result means the site
    # has not yet been reported — it does NOT mean the site is safe.
    # Unrelated-domain mismatches (the brand is merely mentioned alongside another
    # sender's address) still require a concern-level link-check signal before
    # impersonation is established.
    lookalike_mismatched = [f for f in mismatched
                            if f.get("topic") in ("lookalike", "shared_service")]
    if lookalike_mismatched:
        # Include any link-check corroboration that was found (may be empty — that is fine).
        return lookalike_mismatched + support

    # Unrelated-domain path: needs concern-level corroboration from the link check.
    return mismatched + support if support else []


def official_routes(plan_: Plan) -> bool:
    """Every link and address in the material belongs to the organisation it names."""
    impersonation = [c for c in plan_.checks if c.kind == "impersonation"]
    return bool(impersonation) and all(c.status == "resolved" and not any(f["signal"] == "anomaly" for f in c.facts) for c in impersonation)


def signals(plan_: Plan) -> list[tuple[Check, dict]]:
    """Warning signs the evidence establishes, whatever the input was. Weak signals never count, alone or together.
    A name merely mentioned beside another organisation's address counts once something independent backs it up. A
    register entry under a related but different name is a conflict for Magnum DI, not a warning sign."""
    corroborated = bool(corroborated_impersonation(plan_))
    return [(c, f) for c, f in _live(plan_) if f["signal"] in WARNING and f.get("topic") != "name_relation"
            and (corroborated or not _ambiguous(f))]


def _route(checks: list[Check]) -> str:
    routes = {c.route for c in checks if c.route}
    if "web_search" in routes:
        return "tc_flyby_search"
    return "tc_flyby_kb" if routes == {"apollo_kb"} else "tc_flyby_official"


def _contradicted(plan_: Plan) -> bool:
    p = plan_.pattern
    return bool(p and p["impersonatesOrganisation"] and plan_.entities.brands and official_routes(plan_))


def provisional(plan_: Plan) -> Decision | None:
    """The Finding the established evidence already supports, evaluated through
    the S1–S4, N1–N4, L1–L3 rules.

    Replaces the old automatic assumptions:
    - A complete scam pattern is no longer automatically "likely_scam" — S4 requires
      separate corroborating evidence; otherwise it's L2.
    - An exact scam listing is no longer the only route to a definite scam Finding.
    - An established warning sign no longer automatically becomes "concerning".
    - No scam warnings does not mean the communication is genuine (requires N1–N4).

    The four-stage evidence evaluation pipeline still reviews for false-positive avoidance.
    """
    from services.higgins.tc_flyby.finding_rules import evaluate as rules_evaluate

    rules_result = rules_evaluate(plan_)
    finding = rules_result.finding

    if finding == "scam":
        # Determine the route from the deciding rule
        deciding = rules_result.deciding_rules
        if "S1" in deciding:
            # Known scam — check which route found it
            for c, f in _live(plan_):
                if f["signal"] == "concern" and f["decisive"]:
                    route = "tc_flyby_search" if c.route == "web_search" else "tc_flyby_official"
                    return Decision(route, "scam", "threat")
        if "S2" in deciding:
            return Decision("tc_flyby_official", "scam", "impersonation")
        if "S3" in deciding:
            return Decision(_route(plan_.checks), "scam", "signals")
        if "S4" in deciding:
            return Decision("tc_flyby_kb", "scam", "pattern")
        return Decision(_route(plan_.checks), "scam", "threat")

    if finding == "likely_scam":
        deciding = rules_result.deciding_rules
        # Evidence evaluation: should this be downgraded?
        downgrade, reason = evidence_evaluation.should_downgrade_provisional(plan_, "likely_scam")
        if downgrade:
            return None  # let Magnum DI investigate further
        if "L2" in deciding:
            return Decision("tc_flyby_kb", "likely_scam", "pattern")
        if "L1" in deciding:
            # L1 passed — check if corroborated_impersonation has data for the impersonation report
            corroborated = corroborated_impersonation(plan_)
            if corroborated:
                return Decision("tc_flyby_official", "likely_scam", "impersonation")
            # L1 passed via lookalike nature (no separate corroboration) — use signals path
            found = signals(plan_)
            if found:
                return Decision(_route([c for c, _ in found]), "likely_scam", "signals")
            return Decision(_route(plan_.checks), "likely_scam", "signals")
        if "L3" in deciding:
            found = signals(plan_)
            return Decision(_route([c for c, _ in found]) if found else _route(plan_.checks),
                            "likely_scam", "signals")
        return Decision(_route(plan_.checks), "likely_scam", "signals")

    # "not_scam" and "unable_to_determine" are only determined at the final evaluate() step,
    # not as provisional decisions — they need all checks to complete first.
    return None


def verified(target: str, plan_: Plan) -> bool:
    """An official source established that this route belongs to the organisation: an official domain, an
    official email domain, or a number a search confirmed as an official contact."""
    low = target.lower()
    for c in plan_.checks:
        if c.kind == "link" and c.subject in low:
            return any(f["decisive"] and f["signal"] == "clear" for f in c.facts)
        if c.kind == "email" and c.subject.lower() == low:
            return any(f["signal"] == "clear" for f in c.facts)
        if c.kind == "phone" and digits(c.subject)[-8:] and digits(c.subject)[-8:] == digits(target)[-8:]:
            return any(f["signal"] == "clear" for f in c.facts)
    return False   # payment details and anything unchecked can't be verified


def unverified_requests(plan_: Plan) -> list[dict]:
    """Consequential requests whose routes aren't all verified as official."""
    out = []
    for r in plan_.entities.requests:
        consequential = r["type"] in CONSEQUENTIAL or (r["type"] == "call_back" and bool(plan_.entities.brands))
        if consequential and not (r["targets"] and all(verified(t, plan_) for t in r["targets"])):
            out.append(r)
    return out


def _ids_with(texts: dict[str, str], needles: list[str]) -> list[str]:
    low = [n.lower() for n in needles if n]
    return [eid for eid, text in texts.items() if any(n in text.lower() for n in low)] or list(texts)[:2]


def resting_on(plan_: Plan, found: Decision) -> list[tuple[str | None, str]]:
    """(check id, finding) for each finding TC FlyBy's concern outcome rests on."""
    if found.basis == "threat":
        return [(c.id, f["text"]) for c, f in _live(plan_) if f["signal"] == "concern" and f["decisive"]]
    if found.basis == "pattern":
        p = plan_.pattern
        check = next((c.id for c in plan_.checks if c.kind == "scam_pattern"), None)
        return [(check, f"It {label}: “{quote}”.") for label, quote in [*p["found"], *([p["ask"]] if p["ask"] else [])]]
    if found.basis == "impersonation":
        ids = {id(f): c.id for c in plan_.checks for f in c.facts}
        return [(ids.get(id(f)), f["text"]) for f in corroborated_impersonation(plan_)]
    return [(c.id, f["text"]) for c, f in signals(plan_)]


def floor(plan_: Plan, found: Decision | None) -> dict | None:
    """What Magnum DI's result can't go below. A concern resting on established threat evidence (a decisive concern)
    is never lowered; a provisional one is lowered only by a finding that cites the evidence resolving it and names the
    provisional finding (its id) in supersedesFindingIds. A request for a password, PIN, one-time code or card details
    is established threat evidence in itself: the outcome can't be below Concerning."""
    asks = [r["quote"] for r in plan_.entities.requests if r["type"] == "credentials" and _SECRET_ASK.search(r["quote"])]
    if not found and not asks:
        return None
    established = bool(found and found.basis == "threat")
    prefix = "E" if established else "P"
    findings = [{"id": f"{prefix}{n}", "text": text} for n, (_, text) in enumerate(resting_on(plan_, found), start=1)] if found else []
    findings += [{"id": f"E{len(findings) + n}", "text": f"It asks for a secret: “{quote}”."} for n, quote in enumerate(asks[:2], start=1)]
    return {"outcome": found.outcome if found else None, "established": established,
            "minimum": "likely_scam" if asks else None, "findings": findings}


def magnum_issues(plan_: Plan, texts: dict[str, str], found: Decision | None = None) -> list[Issue]:
    """What Magnum DI's extra capabilities could still change. With a concern outcome reached, only what could
    change it or the protective action counts: content TC FlyBy couldn't read, and (for a provisional concern) a
    contradiction about the very facts the concern rests on. The concern's request is already known, so reasoning
    about it can't change what to do."""
    issues = _all_issues(plan_, texts)
    if not found:
        return issues
    if found.basis == "threat":
        return [i for i in issues if i.capability == "reading"]
    rests = {check for check, _ in resting_on(plan_, found) if check}
    return [i for i in issues if i.capability == "reading" or (i.capability == "relating" and i.check_id in rests)]


def _all_issues(plan_: Plan, texts: dict[str, str]) -> list[Issue]:
    issues = [Issue("reading", f"Read {g['item']} directly — {g['what']}.", [g["evidenceId"]]) for g in plan_.gaps if g.get("magnum")]
    requests = unverified_requests(plan_)
    if plan_.has_message and requests:
        asks = "; ".join(f"{r['type'].replace('_', ' ')} (“{r['quote']}”" + (f" → {', '.join(r['targets'][:3])}" if r["targets"] else "") + ")"
                         for r in requests[:4])
        partly = (f" ApolloSG KB: the material partly matches the {plan_.pattern['name']} ({plan_.pattern['publisher']}), general knowledge only."
                  if plan_.pattern and plan_.pattern["stage"] == "partial" else "")
        analysis = next((c.id for c in plan_.checks if c.kind == "message_analysis"), None)
        issues.append(Issue("reasoning", f"Message and deception analysis. The material asks the person to act — {asks} — through a route "
                                         f"no official source verified, and nothing TC FlyBy established settles what to do.{partly}", list(texts), analysis))
    for c in plan_.checks:
        if c.open_issue.startswith("Conflict"):
            issues.append(Issue("relating", c.open_issue, _ids_with(texts, plan_.entities.companies + [c.subject]), c.id))
    corroborated = bool(corroborated_impersonation(plan_))
    for c, f in _live(plan_):
        if _ambiguous(f) and f["signal"] == "anomaly" and not corroborated:
            issues.append(Issue("relating", f"Whether the material genuinely comes from the organisation it names: {f['text']}",
                                _ids_with(texts, [f.get("place") or c.subject]), c.id))
    p = plan_.pattern
    if p and p["stage"] in ("full", "opening") and _contradicted(plan_) and requests:
        pattern_check = next((c.id for c in plan_.checks if c.kind == "scam_pattern"), None)
        issues.append(Issue("relating", f"The wording matches the {p['name']} ({p['publisher']}), yet the links and addresses are the "
                                        "organisation's own: whether the conflicting indicators change the finding.", list(texts), pattern_check))
    return issues


def _complete(plan_: Plan) -> bool:
    """Every planned check that bears on the outcome actually ran over everything submitted: nothing left
    unextracted, no lookup unavailable, and each link either an official domain or both listed-clean and of
    established registration.

    Email-delivery infrastructure signals (topic 'email_delivery', 'email_delivery_redirect') are excluded from
    the weak-signal blocking check because they show only who delivered the email, never a concern about its content."""
    if plan_.gaps or any(c.status == "unavailable" for c in plan_.checks):
        return False
    _DELIVERY_TOPICS = frozenset({"email_delivery", "email_delivery_redirect"})
    if any(f["signal"] == "weak" and f.get("topic") not in _DELIVERY_TOPICS for _, f in _live(plan_)):
        return False   # a weak signal is something found: "No scam indicators found" needs nothing found
    for c in plan_.checks:
        if c.kind != "link" or any(f["decisive"] and f["signal"] == "clear" for f in c.facts):
            continue
        topics = {f.get("topic"): f["signal"] for f in c.facts}
        if not (topics.get("listing") == "clear" and topics.get("registration") == "neutral"):
            return False
    return True


def evaluate(plan_: Plan, texts: dict[str, str], *, final: bool) -> tuple[Decision | None, list[Issue]]:
    """(TC FlyBy's decision, []) when the case is resolved; (None, issues) when Magnum DI could change it.
    Before the last stage only a decisive official result (or an answered general question) stops TC FlyBy —
    every other outcome waits until the checks Higgins Triage planned have run.

    Uses the S1–S4, N1–N4, L1–L3 rules to determine the Finding."""
    found = provisional(plan_)
    if found and found.outcome == "scam":
        # TC FlyBy's stages end here; the deciding test still applies to what it couldn't read.
        issues = magnum_issues(plan_, texts, found)
        return (None, issues) if issues else (found, [])
    if plan_.general:
        check = plan_.checks[0]
        if check.status == "resolved":
            return Decision("tc_flyby_kb" if check.route == "apollo_kb" else "tc_flyby_search", None, "knowledge"), []
        return None, ([Issue("reasoning", f"Answer the general question: {check.subject}", list(texts), check.id)] if final else [])
    if plan_.channel == "call" and not plan_.has_message and not plan_.link_only:
        # A call described only in the question: TC FlyBy has nothing to compare, so Magnum DI assesses the call itself.
        return None, ([Issue("reasoning", "Assess the phone call the person describes in their question: who the caller claimed to be, "
                                          "what they asked for, and what the person should do.", list(texts))] if final else [])
    if not final:
        return None, []

    # Check the rules engine FIRST for not_scam before generating magnum issues
    # If the rules engine says not_scam (all N rules pass), TC FlyBy settles it here.
    from services.higgins.tc_flyby.finding_rules import evaluate as rules_evaluate
    rules_result = rules_evaluate(plan_)

    if not found and rules_result.finding == "not_scam":
        route = _route(plan_.checks)
        return Decision(route, "not_scam", "clear"), []

    issues = magnum_issues(plan_, texts, found)
    if issues:
        return None, issues
    if found:
        return found, []           # a concern outcome nothing unresolved could change: the protective action stands

    # No provisional concern reached and no magnum issues — use the rules engine result
    route = _route(plan_.checks)

    if rules_result.finding == "unable_to_determine":
        return Decision(route, "unable_to_determine", "unknown"), []

    # Shouldn't reach here if provisional() handled scam/likely_scam correctly
    return Decision(route, "unable_to_determine", "unknown"), []


def decisive(plan_: Plan) -> bool:
    """A decisive concern was found: TC FlyBy's stages end (the deciding test still applies)."""
    found = provisional(plan_)
    return bool(found and found.outcome == "scam")


def magnum_needs_search(plan_: Plan, issues: list[Issue]) -> bool:
    """Web search stays OFF for Magnum DI unless a specific external fact may still be missing: content it
    will read for the first time, a lookup that was unavailable, or a general question TC FlyBy couldn't answer."""
    return bool(any(i.capability == "reading" for i in issues) or any(c.status == "unavailable" for c in plan_.checks) or plan_.general)
