"""TC FlyBy stage 1 — direct and authoritative sources.

Every lookup here is a direct check against the source that holds the answer: Apollo's blocklist and
Google Safe Browsing (cached in reputation_cache), the domain registry's RDAP record, Apollo's register of
official government and organisation domains, the official scam-advisory feeds Apollo already holds, the
ABR/ASIC check-digit algorithms, and any specialist results Higgins Triage already gathered for the case.
No AI is involved. A lookup that fails is recorded as unavailable — never as safe.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services import kb_sources
from services.higgins import brand_domains
from services.higgins.brand_domains import registrable
from services.higgins.tc_flyby.triage import FREE_MAIL, Check, Plan, abn_valid, acn_valid

LOOKUP_SECONDS = 8.0


def fact(text: str, signal: str, *, decisive: bool = False, kind: str = "live_evidence", source: dict | None = None,
         topic: str | None = None) -> dict:
    """One statement TC FlyBy established. `kind` keeps live evidence apart from Apollo knowledge (never a finding).
    `signal`: concern | anomaly (a warning sign) | weak (a weak signal: alone or together never Concerning, only the
    corroboration a warning sign or impersonation needs) | clear | neutral | missing (looked up, not established) |
    context (knowledge)."""
    return {"text": text, "signal": signal, "decisive": decisive, "class": kind, "source": source, "topic": topic}


def source_ref(publisher: str, *, url: str | None = None, authority: str = "official", basis: str = "", retrieval: str = "fetched",
            checked_at: str | None = None) -> dict:
    return {"publisher": publisher, "url": url, "authority": authority, "basis": basis, "retrieval": retrieval,
            "checkedAt": checked_at or datetime.now(timezone.utc).isoformat()}


# ── Network lookups (each one replaceable in bounded tests) ─────────────────
async def lookup_url(url: str) -> dict | None:
    """Apollo blocklist + Google Safe Browsing verdict for one URL."""
    from services import intel
    try:
        result = await asyncio.wait_for(intel.run_intel_check("url", url), timeout=LOOKUP_SECONDS)
    except Exception:  # noqa: BLE001 — an unchecked URL is unavailable, never clean
        return None
    return {"verdict": result.verdict, "threatTypes": list(result.threat_types), "coverage": result.coverage,
            "sources": [s.model_dump() for s in result.sources], "checkedAt": result.checked_at.isoformat()}


async def lookup_domain(domain: str) -> dict | None:
    """The domain registry's RDAP registration record."""
    from services import rdap
    try:
        info = await asyncio.wait_for(rdap.lookup_domain_cached(domain), timeout=LOOKUP_SECONDS)
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.available or info.error:
        return None
    return {"registeredAt": info.registered_at.isoformat() if info.registered_at else None, "ageDays": info.age_days,
            "registrar": info.registrar, "newlyRegistered": info.newly_registered}


async def advisories(hosts: list[str], sender_domain: str, text: str) -> list[dict]:
    """Official scam advisories Apollo already holds that name one of these domains (or describe this scam)."""
    from services.triage_engine import _match_scam_intel
    try:
        return await _match_scam_intel({"link_domains": hosts, "sender_domain": sender_domain, "text_preview": text[:2000]})
    except Exception:  # noqa: BLE001
        return []


# ── Reading what Higgins Triage already gathered for the case ────────────────
def pregathered(pe: dict | None) -> dict:
    pe = pe or {}
    return {"safe_browsing": (pe.get("safe_browsing") or {}).get("urls") or {},
            "rdap": (pe.get("rdap") or {}).get("domains") or {},
            "redirects": (pe.get("redirects") or {}).get("urls") or {},
            "ipqs_urls": (pe.get("ipqs") or {}).get("urls") or {},
            "ipqs_phones": (pe.get("ipqs") or {}).get("phones") or {},
            "downloads": (pe.get("download_links") or {}).get("items") or [],
            "advisories": (pe.get("scam_intel") or {}).get("matches") or []}


KNOWN_SECTIONS = {"safe_browsing", "rdap", "redirects", "ipqs", "download_links", "scam_intel", "_summary", "hibp"}


def unread_sections(pe: dict | None) -> dict:
    """Pre-gathered results TC FlyBy has no reader for. They are passed on verbatim so nothing is lost."""
    out = {}
    for key, value in (pe or {}).items():
        if key not in KNOWN_SECTIONS:
            out[key] = value
        elif key in ("safe_browsing", "rdap", "redirects") and isinstance(value, dict) and not any(k in value for k in ("urls", "domains")):
            out[key] = value
    return out


def official_domain(host: str) -> tuple[str, str] | None:
    """(publisher, basis) when the host belongs to an official government/organisation domain on Apollo's register."""
    source = kb_sources.source_for(f"https://{host}")
    if source and source.tier == kb_sources.TIER_1:
        return source.publisher, "ApolloSG's register of official government and regulator domains"
    name = brand_domains.owner(host)
    if name:
        return name, f"{name}'s published domain ({registrable(host)}) on ApolloSG's register of organisation domains"
    return None


_THREATS = {"SOCIAL_ENGINEERING": "a phishing (social engineering) site", "MALWARE": "a malware site",
            "UNWANTED_SOFTWARE": "a site serving unwanted software", "POTENTIALLY_HARMFUL_APPLICATION": "a site serving harmful apps",
            "CRIMINAL_NETWORK": "a site on a network run by criminals", "UNLICENSED_FINANCIAL_SERVICE": "an unlicensed financial operator",
            "IMPOSTER_FINANCIAL_SERVICE": "an imposter of a real financial firm", "ILLEGAL_GAMBLING": "a blocked illegal gambling website"}

# The free lists' own pages, for the source of a listing fact (services/threat_feeds.py).
_LIST_PAGES = {"phishtank": "https://phishtank.org/", "openphish": "https://openphish.com/", "spamhaus_drop": "https://www.spamhaus.org/drop/",
               "asic_investor_alerts": "https://moneysmart.gov.au/check-and-report-scams/investor-alert-list",
               "acma_blocked_gambling": "https://www.acma.gov.au/blocked-gambling-websites"}
_OFFICIAL_LISTS = {"asic_investor_alerts", "acma_blocked_gambling"}


def _listing_source(sources: list[dict], host: str, checked_at: str | None) -> dict:
    from services import intel
    names = [s.get("name") for s in sources if s.get("status") == "match"]
    first = next((n for n in names if n in _LIST_PAGES), None)
    url = _LIST_PAGES[first] if first else f"https://transparencyreport.google.com/safe-browsing/search?url={host}"
    return source_ref(intel.listed_by(sources), url=url, authority="official" if first in _OFFICIAL_LISTS else "independent",
                      basis="Direct threat-list lookup", checked_at=checked_at)


def _threat_words(types: list[str]) -> str:
    return " and ".join(dict.fromkeys(_THREATS.get(t, t.replace("_", " ").lower()) for t in types)) or "dangerous"


def _host_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].split("?")[0].split("#")[0].split("@")[-1].lower()


async def _link(check: Check, pg: dict, plan_: Plan) -> None:
    host = check.subject
    owner = official_domain(host)
    if owner:
        publisher, basis = owner
        check.facts.append(fact(f"{host} is {publisher}'s official domain.", "clear", decisive=True, topic="official_domain",
                                source=source_ref("ApolloSG official-domain register", authority="official", basis=basis)))
    urls = check.urls or [f"https://{host}/"]
    checked_any = False
    for url in urls[:2]:
        chain = (pg["redirects"].get(url) or {}).get("chain") or []
        targets = [url] + ([chain[-1]] if len(chain) > 1 and chain[-1] != url else [])
        if len(targets) > 1:
            # Moving within the same site (or between one organisation's own domains) is how sites work, not a warning sign.
            same = brand_domains.same_organisation(_host_of(url), _host_of(targets[-1]))
            check.facts.append(fact(f"The link {url} redirects to {targets[-1]}" + (", on the same site." if same else "."),
                                    "neutral" if same else "weak", topic="redirect",
                                    source=source_ref("Apollo redirect expansion", authority="independent", basis="HTTP redirect chain recorded by Apollo")))
        for target in targets:
            sb = pg["safe_browsing"].get(target)
            if sb and sb.get("status", "ok") == "ok" and sb.get("verdict"):
                result = {"verdict": sb["verdict"], "threatTypes": sb.get("threat_types") or [], "coverage": sb.get("coverage", "full"),
                          "sources": sb.get("sources") or [{"name": "google_safe_browsing", "status": "match" if sb["verdict"] == "malicious" else "clear"}],
                          "checkedAt": sb.get("queried_at")}
            else:
                result = await lookup_url(target)
            if not result or result["coverage"] == "none":
                continue
            checked_any = True
            target_host = _host_of(target)
            if result["verdict"] == "malicious":
                from services import intel
                check.facts.append(fact(f"{intel.listed_by(result['sources'])} lists {target_host} as {_threat_words(result['threatTypes'])}.", "concern",
                                        decisive=True, topic="listing", source=_listing_source(result["sources"], target_host, result.get("checkedAt"))))
            elif result["verdict"] == "clean":
                from services import intel
                check.facts.append(fact(f"{target_host} is not listed by {intel.answered(result['sources'])}.", "clear", topic="listing",
                                        source=source_ref("Google Safe Browsing and the free threat lists",
                                                          url=f"https://transparencyreport.google.com/safe-browsing/search?url={target_host}",
                                                          authority="independent", basis="Direct threat-list lookup", checked_at=result.get("checkedAt"))))
    domain = registrable(host)
    rd = pg["rdap"].get(domain) or pg["rdap"].get(host)
    record = None
    if rd and rd.get("status") == "ok" and rd.get("registration_date") not in (None, "unknown"):
        record = {"registeredAt": rd["registration_date"], "ageDays": None, "newlyRegistered": bool(rd.get("newly_registered"))}
    elif not owner:
        record = await lookup_domain(domain)
    if record and record.get("registeredAt"):
        age = record.get("ageDays")
        when = record["registeredAt"][:10]
        young = record.get("newlyRegistered") or (age is not None and age < 90)
        check.facts.append(fact(f"{domain} was registered on {when}" + (f" ({age} days before this check)." if age is not None and age < 365 else "."),
                                "weak" if young else "neutral", topic="registration",
                                source=source_ref("Domain registry (RDAP)", url=f"https://rdap.org/domain/{domain}", authority="official",
                                               basis="The registry's RDAP registration record")))
    for url, info in pg["ipqs_urls"].items():
        if host in url.lower() and info.get("status") == "ok":
            flags = [name for name in ("phishing", "malware", "suspicious") if info.get(name)]
            if flags:
                check.facts.append(fact(f"IPQualityScore flags {host} as {', '.join(flags)} (risk score {info.get('risk_score', '?')}/100).", "weak",
                                        source=source_ref("IPQualityScore", authority="independent", basis="Commercial URL reputation lookup")))
    for item in pg["downloads"]:
        if host in (item.get("url") or "").lower():
            check.facts.append(fact(f"The link downloads a file directly ({item.get('filename', 'a file')}).", "weak",
                                    source=source_ref("ApolloSG download-link detection", authority="independent", basis="Static link analysis")))
    for match in pg["advisories"] + plan_.advisories:
        if (match.get("matched_on") or "") == f"domain: {host}" or (match.get("matched_on") or "") == f"domain: {domain}":
            check.facts.append(fact(f"An official scam advisory names {host}: “{match.get('title', 'advisory')}”.", "concern", decisive=True,
                                    source=source_ref("Official scam advisory feed", authority="official", basis="Government advisory held by ApolloSG")))
    if any(f["decisive"] for f in check.facts):
        check.status, check.route = "resolved", "official_source"
    elif not checked_any and not owner:
        check.facts.append(fact(f"Google Safe Browsing could not be checked for {host}.", "missing", topic="listing"))


def _mismatch(name: str, official: str, place: str, kind: str, detail: str) -> tuple[str, str]:
    """(text, topic) for an address that isn't one of the organisation's own. Only a lookalike sign or a shared
    service is a warning sign by itself; an address that doesn't carry the name needs something independent."""
    if kind == "lookalike":
        return (f"{place} carries {name}'s name, but it is not {name}'s domain ({official}) — "
                f"{brand_domains.SIGN_WORDS[detail]}.", "lookalike")
    if kind == "shared_service":
        return (f"{place} puts {name}'s name in front of {detail}, a link or website service anyone can use, "
                f"not on {name}'s own domain ({official}).", "shared_service")
    return f"The material names {name}, but {place} is not {name}'s domain ({official}).", "impersonation"


def _impersonation(check: Check, plan_: Plan) -> None:
    name, official = check.subject, check.urls[0]
    places = [h for h in plan_.entities.hosts] + [e.split("@")[-1] for e in plan_.entities.emails]
    if not places:
        check.status, check.open_issue = "needs_reasoning", f"Whether the material genuinely comes from {name}."
        return
    kinds = {place: brand_domains.classify(name, place) for place in places}
    # A recognised email-sending service's tracking link that doesn't carry the name says only who delivered the email:
    # it is no mismatch (so it can't send the case to Magnum DI by itself) and never proof the email is genuine.
    from services.email_infrastructure import is_tracking
    delivery = [p for p in places if kinds[p][0] == "unrelated" and is_tracking(p)]
    places = [p for p in places if p not in delivery]
    if delivery and not places:
        check.facts.append(fact(f"The links go through {', '.join(sorted({registrable(p) for p in delivery})[:3])}, an email-sending service's "
                                "click tracking. That shows who delivered the email, not who sent it.", "neutral", topic="email_delivery"))
        check.status, check.route = "resolved", "official_source"
        return
    mismatched = [p for p in places if kinds[p][0] not in ("official", "country_site")]
    source = source_ref("ApolloSG official-domain register", basis=f"{name}'s published domains")
    if mismatched:
        for place in mismatched[:3]:
            text, topic = _mismatch(name, official, place, *kinds[place])
            check.facts.append(fact(text, "anomaly", topic=topic, source=source) | {"place": place})
        check.status, check.open_issue = "needs_reasoning", f"Impersonation: whether the material genuinely comes from {name}."
        return
    domains = sorted({kinds[p][1] for p in places})
    country = sorted({kinds[p][1] for p in places if kinds[p][0] == "country_site"})
    if domains == [registrable(official)]:
        text = f"Every link and address in the material uses {official}, {name}'s official domain."
    else:
        text = f"Every link and address in the material uses {name}'s own domains ({', '.join(domains)})."
        if country:
            text += (f" {', '.join(country)} {'is' if len(country) == 1 else 'are'} {name}'s name exactly on a country ending, "
                     f"as {name}'s own country sites are; not on ApolloSG's register.")
    check.facts.append(fact(text, "clear", topic="official_domains", source=source))
    check.status, check.route = "resolved", "official_source"


async def _regulator_listing(check: Check, scope: str, what: str) -> bool:
    """ASIC's investor alert list names this exact email address or phone number: a decisive concern from an official source."""
    from services import threat_feeds
    try:
        rows = await threat_feeds.listed(scope, check.subject)
    except Exception:  # noqa: BLE001 — an unchecked list is missing evidence, never a clear result
        return False
    if not rows:
        return False
    row = rows[0]
    check.facts.append(fact(f"ASIC's investor alert list names this {what} ({row.get('entity') or 'an entity'}, {row.get('category') or 'listed'}).",
                            "concern", decisive=True, topic="listing",
                            source=source_ref(row.get("publisher") or "ASIC", url=row.get("detail_url"), authority="official",
                                              basis="Listed by Australia's financial regulator on its investor alert list",
                                              checked_at=(row.get("last_verified_at") or datetime.now(timezone.utc)).isoformat())))
    check.status, check.route = "resolved", "official_source"
    return True


def _directory_source(url: str | None, basis: str) -> dict:
    from services import org_directory
    return source_ref(org_directory.PUBLISHER, url=url, authority="official", basis=basis)


def _contacts(items: list[dict]) -> str:
    return ", ".join(f"{c['value']}" + (f" ({c['label']})" if c.get("label") else "") for c in items)


async def _phone(check: Check, pg: dict, plan_: Plan | None = None) -> None:
    from services import org_directory
    await _regulator_listing(check, "phone", "phone number")
    claimed = plan_.entities.brands[0][0] if plan_ and plan_.entities.brands else None
    verdict = org_directory.number_verdict(check.subject, claimed)
    if verdict and verdict["status"] == "published":
        check.facts.append(fact(f"{check.subject} is {verdict['name']}'s published {verdict['label'] or 'contact number'}.", "clear",
                                topic="official_contact",
                                source=_directory_source(verdict.get("source_url"), f"Found on {verdict['name']}'s own contact page")))
        if check.status == "open":
            check.status, check.route = "resolved", "official_source"
    elif verdict:
        # The owner's rule: a number presented as a listed organisation's that isn't one of its published numbers is a
        # warning sign that needs corroboration (organisations have many numbers).
        check.facts.append(fact(f"The material names {verdict['name']}, but {check.subject} is not one of {verdict['name']}'s published numbers. "
                                f"{verdict['name']}'s published {'number is' if len(verdict['use_instead']) == 1 else 'numbers are'} "
                                f"{_contacts(verdict['use_instead'])}.", "anomaly", topic="unlisted_contact",
                                source=_directory_source((verdict["use_instead"][0] or {}).get("source_url"),
                                                         f"{verdict['name']}'s published numbers on its own pages")))
    info = next((v for k, v in pg["ipqs_phones"].items() if k and check.subject and k[-8:] in check.subject.replace(" ", "")), None)
    if info and info.get("status") == "ok":
        risky = (info.get("fraud_score") or 0) >= 85 or info.get("recent_abuse")
        check.facts.append(fact(f"IPQualityScore gives {check.subject} a fraud score of {info.get('fraud_score', '?')}/100"
                                + ("; recent abuse is reported" if info.get("recent_abuse") else "") + f" (carrier: {info.get('carrier', 'unknown')}).",
                                "weak" if risky else "neutral",
                                source=source_ref("IPQualityScore", authority="independent", basis="Commercial phone reputation lookup")))


async def _email(check: Check, plan_: Plan) -> None:
    from services import org_directory
    await _regulator_listing(check, "email", "email address")
    domain = check.subject.split("@")[-1].lower()
    owner = official_domain(domain)
    published = org_directory.email_verdict(check.subject)
    if published:
        check.facts.append(fact(f"{check.subject} is {published['name']}'s published {published['label'] or 'address'}.", "clear",
                                topic="official_contact",
                                source=_directory_source(published.get("source_url"), f"Found on {published['name']}'s own pages")))
    elif owner:
        check.facts.append(fact(f"{check.subject} uses {domain}, {owner[0]}'s official domain.", "clear",
                                source=source_ref("ApolloSG official-domain register", basis=owner[1])))
    elif domain in FREE_MAIL and plan_.entities.brands:
        check.facts.append(fact(f"{check.subject} is a free personal email account ({domain}), not an address of {plan_.entities.brands[0][0]}.", "anomaly",
                                topic="freemail", source=source_ref("ApolloSG official-domain register", basis="Free email providers are not organisation domains")))


def _registration_number(check: Check) -> None:
    label = "ABN" if check.kind == "abn" else "ACN"
    valid = abn_valid(check.subject) if check.kind == "abn" else acn_valid(check.subject)
    publisher = "Australian Business Register" if check.kind == "abn" else "ASIC"
    source = source_ref(f"{publisher} check-digit algorithm", authority="official", basis=f"{publisher}'s published {label} validation rule")
    if valid:
        check.facts.append(fact(f"{label} {check.subject} passes the {publisher}'s check-digit test.", "neutral", source=source))
    else:
        check.facts.append(fact(f"{label} {check.subject} fails the {publisher}'s check-digit test, so it is not a valid {label}.", "anomaly", source=source))
        check.status, check.route = "resolved", "official_source"


async def run(plan_: Plan, pre_gathered: dict | None, text: str) -> None:
    """Stage 1 for every planned check. Stops nothing itself — the engine decides from the facts."""
    pg = pregathered(pre_gathered)
    sender_domain = plan_.entities.emails[0].split("@")[-1].lower() if plan_.entities.emails else ""
    hosts = [registrable(h) for h in plan_.entities.hosts]
    plan_.advisories = [] if pg["advisories"] or not (hosts or sender_domain or text) else await advisories(hosts, sender_domain, text)
    for check in plan_.checks:
        if check.kind == "link":
            await _link(check, pg, plan_)
        elif check.kind == "impersonation":
            _impersonation(check, plan_)
        elif check.kind == "phone":
            await _phone(check, pg, plan_)
        elif check.kind == "email":
            await _email(check, plan_)
        elif check.kind in ("abn", "acn"):
            _registration_number(check)
        elif check.kind == "scam_alerts":
            for match in pg["advisories"] + plan_.advisories:
                on = match.get("matched_on") or ""
                if on.startswith("keyword"):
                    check.facts.append(fact(f"An official advisory describes a similar scam: “{match.get('title', 'advisory')}” (severity {match.get('severity', 'unknown')}).",
                                            "context", kind="apollo_knowledge",
                                            source=source_ref("Official scam advisory feed", basis="Government advisory held by ApolloSG — general knowledge")))
