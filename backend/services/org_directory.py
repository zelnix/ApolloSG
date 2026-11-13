"""ApolloSG Official Organisation Directory: the published domains, phone numbers and email addresses of the organisations
scammers most often pretend to be, each traced to the organisation's own page.

Where it lives: the ApolloSG KB (`higgins_knowledge`, kind `official_organisation`), one entry per organisation, never a
separate store. It is structured reference data, so the KB's question search never quotes it (knowledge._NOT_GENERAL).

What counts as official:
- A domain counts when it shipped with ApolloSG (curated) or one of the organisation's source pages is on it or names it.
- A phone number or email address counts only when ApolloSG found it on one of the organisation's own source pages within
  the last CONFIRM_WINDOW. A successful re-read that no longer shows it stops it counting at once. A page that can't be read
  keeps the last confirmation until the window runs out; it never confirms anything new.
- Source pages must be on the organisation's own domains or an official (Tier 1) authority. A page the source blocks from
  cloud servers is read from an Internet Archive copy no older than ARCHIVE_MAX_AGE.

How checks use it (services/higgins/tc_flyby/official.py): a number or address on the list is the organisation's published
contact (it settles that check only). A number the material presents as a listed organisation's, but that isn't one of its
published numbers, is a warning sign that needs corroboration (the owner's rule): organisations have many numbers.

Shipped entries come from content/official_organisations.json; admins add and edit entries in the admin portal (every
change audit-logged, each entry needs at least one official source page). An admin-edited entry is never overwritten.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from core.db import db, now_utc
from services import kb_sources
from services.higgins import brand_domains
from services.higgins.indicators import BRANDS

log = logging.getLogger("apollo.org_directory")

KIND = "official_organisation"
SEED = Path(__file__).resolve().parents[1] / "content" / "official_organisations.json"
SECTORS = {"bank": "Banks", "government": "Government", "delivery_toll": "Delivery and tolls", "telco": "Phone and internet",
           "shopping_payments": "Shopping and payments"}
VERIFY_EVERY = timedelta(days=7)
RETRY_AFTER = timedelta(days=1)
CONFIRM_WINDOW = timedelta(days=30)
ARCHIVE_MAX_AGE = timedelta(days=30)
PAGE_LIMIT = 6_000_000
PUBLISHER = "ApolloSG Official Organisation Directory"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_NUMBERISH = re.compile(r"\+?\(?\d[\d\s().\-]{4,18}\d")
_TEL = re.compile(r"""href\s*=\s*["']tel:([^"']+)["']""", re.I)
_MAILTO = re.compile(r"""href\s*=\s*["']mailto:([^"'?]+)""", re.I)
_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


# ── Normalising ────────────────────────────────────────────────────────────────

def national(value: str) -> str:
    """An Australian number in one form for comparison: 13 22 21 → 132221, +61 2 9999 3283 → 0299993283,
    +61 1300 169 468 → 1300169468. Other countries' numbers keep their country code (+44…)."""
    raw = html.unescape(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    international = raw.startswith("+") or digits.startswith("00")
    digits = digits[2:] if digits.startswith("00") else digits
    if international:
        if not digits.startswith("61"):
            return f"+{digits}"
        digits = digits[2:]
    if digits.startswith("1"):
        return digits                      # 13, 1300, 1800 numbers
    if len(digits) == 9:
        return "0" + digits
    return digits


def key_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().removeprefix("the ")).strip("-")


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def _fresh(item: dict, now: datetime) -> bool:
    confirmed = _aware(item.get("confirmed_at"))
    return item.get("status") == "confirmed" and bool(confirmed) and now - confirmed <= CONFIRM_WINDOW


def _source_allowed(url: str, domains: list[str]) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    source = kb_sources.source_for(url)
    return bool(source and source.tier == kb_sources.TIER_1) or any(host == d or host.endswith("." + d) for d in domains)


# ── The in-memory view the checks read (rebuilt after every change) ────────────

_VIEW: dict = {"orgs": {}, "phones": {}, "emails": {}}
_ADDED_NEEDLES: set[str] = set()


def _apply(orgs: list[dict]) -> None:
    now = now_utc()
    view = {"orgs": {}, "phones": {}, "emails": {}}
    domains: dict[str, tuple[str, ...]] = {}
    for needle in _ADDED_NEEDLES:
        BRANDS.pop(needle, None)
    _ADDED_NEEDLES.clear()
    for org in orgs:
        name = org["name"]
        counted = [d["domain"] for d in org.get("domains") or [] if d.get("status") == "curated" or _fresh(d, now)]
        main = next((dom for brand, dom in BRANDS.values() if brand == name), counted[0] if counted else None)
        if not main:
            continue
        for alias in {*(org.get("aliases") or []), name.lower().removeprefix("the ")}:
            if alias and alias not in BRANDS:
                BRANDS[alias] = (name, main)
                _ADDED_NEEDLES.add(alias)
        domains[name] = tuple(counted)
        phones = [p for p in org.get("phones") or [] if _fresh(p, now)]
        emails = [e for e in org.get("emails") or [] if _fresh(e, now)]
        view["orgs"][name] = {"key": org["key"], "name": name, "sector": org.get("sector"), "domains": counted, "phones": phones, "emails": emails}
        for p in phones:
            view["phones"].setdefault(p["national"], {"name": name, **p})
        for e in emails:
            view["emails"].setdefault(e["address"].lower(), {"name": name, **e})
    brand_domains.DIRECTORY.clear()
    brand_domains.DIRECTORY.update(domains)
    _VIEW.clear()
    _VIEW.update(view)
    _SOURCES.clear()
    _SOURCES.update({org["name"]: org.get("sources") or [] for org in orgs})


async def load() -> int:
    orgs = await db.higgins_knowledge.find({"kind": KIND, "status": {"$ne": "archived"}}, {"_id": 0}).to_list(500)
    _apply(orgs)
    return len(orgs)


def phone_owner(number: str) -> dict | None:
    """{name, number, label, source_url, confirmed_at} when this is a published number of an organisation on the directory."""
    return _VIEW["phones"].get(national(number)) if number else None


def email_owner(address: str) -> dict | None:
    return _VIEW["emails"].get((address or "").strip().lower())


def org(name: str) -> dict | None:
    return _VIEW["orgs"].get(name)


def find(claimed: str | None) -> dict | None:
    """The directory entry for an organisation as material or a caller names it ("Commonwealth Bank", "the ATO")."""
    text = " ".join((claimed or "").lower().split()).removeprefix("the ")
    if not text:
        return None
    by_name = {name.lower().removeprefix("the "): entry for name, entry in _VIEW["orgs"].items()}
    if text in by_name:
        return by_name[text]
    hit = BRANDS.get(text)
    return _VIEW["orgs"].get(hit[0]) if hit else None


def _contact(item: dict, key: str) -> dict:
    return {"value": item[key], "label": item.get("label") or "", "source_url": item.get("source_url")}


def _call(entry: dict) -> dict | None:
    """The organisation's main published number: what every warning's "Call the real number" button dials."""
    return _contact(entry["phones"][0], "number") if entry.get("phones") else None


def number_verdict(number: str, claimed: str | None = None) -> dict | None:
    """What the directory says about a number: an organisation's published contact, or (when the material or caller
    names a listed organisation) not one of that organisation's published numbers, with the ones to use instead."""
    hit = phone_owner(number)
    if hit:
        return {"status": "published", "name": hit["name"], "label": hit.get("label") or "", "source_url": hit.get("source_url")}
    entry = find(claimed)
    if entry and entry["phones"]:
        return {"status": "not_published", "name": entry["name"], "use_instead": [_contact(p, "number") for p in entry["phones"][:3]],
                "call": _call(entry)}
    return None


def email_verdict(address: str, claimed: str | None = None) -> dict | None:
    hit = email_owner(address)
    if hit:
        return {"status": "published", "name": hit["name"], "label": hit.get("label") or "", "source_url": hit.get("source_url")}
    entry = find(claimed)
    domain = (address or "").lower().split("@")[-1]
    if entry and brand_domains.registrable(domain) not in brand_domains.official_domains(entry["name"]):
        return {"status": "not_published", "name": entry["name"], "use_instead": [_contact(e, "address") for e in entry["emails"][:2]],
                "domains": list(brand_domains.official_domains(entry["name"]))[:3], "call": _call(entry)}
    return None


def host_of(value: str) -> str:
    """The host of a link, a bare domain ("commbank.com.au/login") or an email address."""
    value = (value or "").strip()
    if "@" in value and "//" not in value:
        return value.rsplit("@", 1)[-1].lower()
    return (urlparse(value if "//" in value else f"https://{value}").hostname or "").lower()


def site_verdict(host: str, claimed: str | None = None) -> dict | None:
    """A website against the directory: an organisation's own domain, one carrying a listed organisation's name that
    isn't its domain (a lookalike or a shared service), or, when the material names a listed organisation, a website that
    isn't one of its own — each with the organisation's own website to use instead."""
    host = (host or "").lower().strip(".").removeprefix("www.")
    if "." not in host:
        return None
    source = lambda entry: next((s["url"] for s in _source_rows(entry["name"])), None)  # noqa: E731
    owner = brand_domains.owner(host)
    if owner and owner in _VIEW["orgs"]:
        return {"status": "official", "name": owner, "domain": brand_domains.registrable(host), "source_url": source(_VIEW["orgs"][owner])}
    for name, entry in _VIEW["orgs"].items():
        kind, detail = brand_domains.classify(name, host)
        if kind in ("lookalike", "shared_service"):
            official = brand_domains.official_domains(name)
            return {"status": kind, "name": name, "domain": brand_domains.registrable(host), "official_domain": official[0] if official else None,
                    "detail": brand_domains.SIGN_WORDS.get(detail) if kind == "lookalike" else f"{detail} is a link or website service anyone can use",
                    "source_url": source(entry), "call": _call(entry)}
    from services.higgins.tc_hawkeye.official import official_domain
    entry = find(claimed)
    # Another organisation's or a government website, or the organisation's own country site, is never "not official".
    if entry and not official_domain(host) and brand_domains.classify(entry["name"], host)[0] != "country_site":
        official = brand_domains.official_domains(entry["name"])
        return {"status": "not_official", "name": entry["name"], "domain": brand_domains.registrable(host),
                "official_domain": official[0] if official else None, "source_url": source(entry), "call": _call(entry)}
    return None


def names() -> list[dict]:
    """Each organisation on the directory with the names people use for it, so the phone can tell which one material names."""
    return [{"name": name, "aliases": sorted(n for n, (brand, _) in BRANDS.items() if brand == name)} for name in sorted(_VIEW["orgs"])]


MAX_CONTACTS = 10


def verdicts(claimed: str | None, sites: list[str], phones: list[str], emails: list[str]) -> list[dict]:
    """The directory's verdict on each website, number and address in material being checked (only those it has one for).
    An in-memory lookup: nothing is fetched and nothing is kept."""
    judges = (("site", sites, lambda v: site_verdict(host_of(v), claimed)), ("phone", phones, lambda v: number_verdict(v, claimed)),
              ("email", emails, lambda v: email_verdict(v, claimed)))
    out = []
    for kind, values, judge in judges:
        for value in list(dict.fromkeys(v.strip() for v in values if v and v.strip()))[:MAX_CONTACTS]:
            found = judge(value)
            if found:
                out.append({"kind": kind, "value": value, **found})
    return out


_SOURCES: dict[str, list[dict]] = {}


def _source_rows(name: str) -> list[dict]:
    return _SOURCES.get(name) or []


# ── Shipped entries ────────────────────────────────────────────────────────────

def _entry(raw: dict, origin: str, previous: dict | None = None) -> dict:
    """A directory entry from a shipped or admin-entered record, keeping what ApolloSG already confirmed."""
    before = {"phones": {p["national"]: p for p in (previous or {}).get("phones") or []},
              "emails": {e["address"].lower(): e for e in (previous or {}).get("emails") or []},
              "domains": {d["domain"]: d for d in (previous or {}).get("domains") or []},
              "sources": {s["url"]: s for s in (previous or {}).get("sources") or []}}
    keep = lambda old, **new: {**{k: old.get(k) for k in ("status", "confirmed_at", "source_url") if old}, **new}  # noqa: E731
    phones = [keep(before["phones"].get(national(p["number"]), {}), number=p["number"], national=national(p["number"]), label=p.get("label") or "")
              for p in raw.get("phones") or []]
    emails = [keep(before["emails"].get(e["address"].lower(), {}), address=e["address"].strip(), label=e.get("label") or "")
              for e in raw.get("emails") or []]
    domains = []
    for d in raw.get("domains") or []:
        old = before["domains"].get(d, {})
        status = "curated" if origin == "shipped" or old.get("status") == "curated" else old.get("status") or "unconfirmed"
        domains.append({"domain": d, "status": status, "confirmed_at": old.get("confirmed_at")})
    for item in phones + emails:
        item.setdefault("status", "unchecked")
        item["status"] = item["status"] or "unchecked"
    sources = [before["sources"].get(u) or {"url": u, "status": "unchecked"} for u in raw.get("sources") or []]
    return {"kind": KIND, "key": raw.get("id") or key_for(raw["name"]), "name": raw["name"], "sector": raw.get("sector"),
            "aliases": sorted({a.strip().lower() for a in raw.get("aliases") or [] if a.strip()}), "domains": domains, "phones": phones,
            "emails": emails, "sources": sources, "origin": origin, "status": "current",
            "title": f"{raw['name']}: official domains and contacts", "publisher": PUBLISHER, "authority_tier": "official_organisation",
            "jurisdiction": "AU", "knowledge_class": "reference_data", "body": ""}


async def seed() -> int:
    """Bring in the shipped list. An entry an admin changed is left as the admin made it."""
    data = json.loads(SEED.read_text(encoding="utf-8"))
    added = 0
    for raw in data["organisations"]:
        key = raw["id"]
        previous = await db.higgins_knowledge.find_one({"kind": KIND, "key": key}, {"_id": 0})
        if previous and previous.get("origin") != "shipped":
            continue
        doc = _entry(raw, "shipped", previous)
        now = now_utc()
        result = await db.higgins_knowledge.update_one({"kind": KIND, "key": key}, {
            "$set": {**doc, "updated_at": now, "provenance": {"publisher": PUBLISHER, "authority_tier": "official_organisation",
                                                              "jurisdiction": "AU", "retrieved_via": "official_organisations.json",
                                                              "source_url": doc["sources"][0]["url"] if doc["sources"] else None}},
            "$setOnInsert": {"kb_id": f"org-{key}", "created_at": now, "hits": 0}}, upsert=True)
        added += bool(result.upserted_id)
    return added


# ── Reading the organisation's own pages ───────────────────────────────────────

class PageMissing(Exception):
    pass


async def _read(url: str, domains: list[str]) -> dict:
    """The page's text, numbers and addresses. Direct first; an Internet Archive copy when the source refuses us."""
    from services.archive_relay import capture_of
    from services.outbound import public_get
    via, copy_at, body = "direct", None, None
    try:
        response = await public_get(url, max_hops=4, limit=PAGE_LIMIT, deadline=25, gzip_ok=True)
        final = str(response.request.url)
        if response.status_code in (404, 410):
            raise PageMissing("page_not_found")
        if response.status_code == 200 and _source_allowed(final, domains):
            body = response.content
    except PageMissing:
        raise
    except Exception:  # noqa: BLE001 — the source refused or failed us: try a recent archived copy
        body = None
    if body is None:
        stamp = now_utc().strftime("%Y%m%d%H%M%S")
        response = await public_get(f"https://web.archive.org/web/{stamp}id_/{url}", max_hops=3, limit=PAGE_LIMIT, deadline=30, gzip_ok=True)
        copy_at = capture_of(str(response.request.url), url)
        if response.status_code != 200 or not copy_at:
            raise ValueError("archive_unavailable")
        if now_utc() - copy_at > ARCHIVE_MAX_AGE:
            raise ValueError("archive_copy_too_old")
        via, body = "internet_archive", response.content
    page = body.decode("utf-8", "replace")
    stripped = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", stripped))
    phones = {national(t) for t in _TEL.findall(page)} | {national(t) for t in _NUMBERISH.findall(text)}
    emails = {e.lower() for e in _EMAIL.findall(text)} | {html.unescape(m).strip().lower() for m in _MAILTO.findall(page)}
    return {"url": url, "via": via, "copy_at": copy_at, "text": text.lower(), "phones": phones, "emails": emails,
            "host": (urlparse(url).hostname or "").lower()}


async def verify(key: str, trigger: str = "scheduled") -> dict:
    """Re-read one organisation's source pages and confirm (or stop counting) each contact and domain."""
    doc = await db.higgins_knowledge.find_one({"kind": KIND, "key": key}, {"_id": 0})
    if not doc:
        return {"key": key, "status": "missing"}
    now = now_utc()
    domains = [d["domain"] for d in doc.get("domains") or []]
    pages, sources = [], []
    for source in doc.get("sources") or []:
        entry = {"url": source["url"], "checked_at": now}
        try:
            page = await _read(source["url"], domains)
            pages.append(page)
            entry.update(status="read", via=page["via"], copy_at=page["copy_at"], error=None)
        except PageMissing:
            entry.update(status="missing", via=None, copy_at=None, error="page_not_found")
        except Exception as exc:  # noqa: BLE001 — unreadable: recorded, never a confirmation
            entry.update(status="unreadable", via=None, copy_at=None, error=str(exc)[:80] if isinstance(exc, ValueError) else type(exc).__name__)
        sources.append(entry)

    def settle(item: dict, found_on: str | None) -> dict:
        if found_on:
            return {**item, "status": "confirmed", "confirmed_at": now, "source_url": found_on}
        if pages:
            return {**item, "status": "not_found"}
        return item   # nothing could be read: the last confirmation stands until its window runs out

    phones = [settle(p, next((pg["url"] for pg in pages if p["national"] in pg["phones"]), None)) for p in doc.get("phones") or []]
    emails = [settle(e, next((pg["url"] for pg in pages if e["address"].lower() in pg["emails"]), None)) for e in doc.get("emails") or []]
    out_domains = []
    for d in doc.get("domains") or []:
        on = next((pg["url"] for pg in pages if brand_domains.registrable(pg["host"]) == d["domain"] or d["domain"] in pg["text"]), None)
        out_domains.append({**d, "confirmed_at": now} if on and d["status"] == "curated" else
                           {**d, "status": "confirmed", "confirmed_at": now} if on else
                           {**d, "status": "unconfirmed"} if pages and d["status"] != "curated" else d)
    status = "verified" if pages else "unreadable"
    await db.higgins_knowledge.update_one({"kind": KIND, "key": key}, {"$set": {
        "phones": phones, "emails": emails, "domains": out_domains, "sources": sources, "last_verified_at": now, "verify_status": status,
        "verify_trigger": trigger, "provenance.last_checked_at": now}})
    return {"key": key, "status": status, "pages_read": len(pages), "confirmed": sum(i["status"] == "confirmed" for i in phones + emails)}


def due(doc: dict, now: datetime) -> bool:
    last = _aware(doc.get("last_verified_at"))
    if not last:
        return True
    return now - last >= (RETRY_AFTER if doc.get("verify_status") == "unreadable" else VERIFY_EVERY)


async def run(key: str | None = None, *, trigger: str = "scheduled", only_due: bool = False) -> list[dict]:
    now, results = now_utc(), []
    query = {"kind": KIND, "status": {"$ne": "archived"}, **({"key": key} if key else {})}
    async for doc in db.higgins_knowledge.find(query, {"_id": 0, "key": 1, "last_verified_at": 1, "verify_status": 1}):
        if only_due and not due(doc, now):
            continue
        try:
            results.append(await verify(doc["key"], trigger))
        except Exception:  # noqa: BLE001 — one organisation never stops the rest
            log.warning("org_directory_verify_failed key=%s", doc["key"], exc_info=True)
    if results:
        await load()
    return results


# ── Admin changes ──────────────────────────────────────────────────────────────

def parse_form(form: dict) -> tuple[dict, list[str]]:
    """An admin's entry, checked. Returns (record, problems in plain words)."""
    problems = []
    name = " ".join((form.get("name") or "").split())
    if not 2 <= len(name) <= 80:
        problems.append("Give the organisation's name.")
    sector = form.get("sector") or ""
    if sector not in SECTORS:
        problems.append("Pick a sector.")
    domains = list(dict.fromkeys(d.lower().removeprefix("www.") for d in re.split(r"[\s,]+", form.get("domains") or "") if d))
    if not domains:
        problems.append("Add at least one of the organisation's own domains.")
    problems += [f"{d} isn't a domain." for d in domains if not _DOMAIN.match(d)]
    phones = []
    for line in [line.strip() for line in (form.get("phones") or "").splitlines() if line.strip()]:
        number, _, label = line.partition("|")
        if not 6 <= len(re.sub(r"\D", "", number)) <= 15:
            problems.append(f"{number.strip()} isn't a phone number.")
        phones.append({"number": number.strip(), "label": label.strip()})
    emails = []
    for line in [line.strip() for line in (form.get("emails") or "").splitlines() if line.strip()]:
        address, _, label = line.partition("|")
        if not _EMAIL.fullmatch(address.strip()):
            problems.append(f"{address.strip()} isn't an email address.")
        emails.append({"address": address.strip(), "label": label.strip()})
    sources = list(dict.fromkeys(u.strip() for u in (form.get("sources") or "").split() if u.strip()))
    if not sources:
        problems.append("Add at least one official source page.")
    problems += [f"{u} isn't on the organisation's own domains or an official authority's website (https only)." for u in sources
                 if not _source_allowed(u, domains)]
    aliases = [a.strip().lower() for a in (form.get("aliases") or "").split(",") if len(a.strip()) >= 3]
    return {"id": form.get("key") or key_for(name), "name": name, "sector": sector, "aliases": aliases, "domains": domains,
            "phones": phones, "emails": emails, "sources": sources}, problems


async def save(record: dict, actor: str) -> str:
    previous = await db.higgins_knowledge.find_one({"kind": KIND, "key": record["id"]}, {"_id": 0})
    doc = _entry(record, "admin", previous)
    now = now_utc()
    await db.higgins_knowledge.update_one({"kind": KIND, "key": doc["key"]}, {
        "$set": {**doc, "updated_at": now, "updated_by": actor,
                 "provenance": {"publisher": PUBLISHER, "authority_tier": "official_organisation", "jurisdiction": "AU",
                                "retrieved_via": "admin", "source_url": doc["sources"][0]["url"]}},
        "$setOnInsert": {"kb_id": f"org-{doc['key']}", "created_at": now, "hits": 0}}, upsert=True)
    await load()
    return doc["key"]


async def archive(key: str, actor: str) -> bool:
    result = await db.higgins_knowledge.update_one({"kind": KIND, "key": key}, {"$set": {
        "status": "archived", "origin": "admin", "updated_by": actor, "updated_at": now_utc()}})
    await load()
    return bool(result.modified_count)


async def entries() -> list[dict]:
    return await db.higgins_knowledge.find({"kind": KIND, "status": {"$ne": "archived"}}, {"_id": 0}).sort([("sector", 1), ("name", 1)]).to_list(500)


def counts(doc: dict, now: datetime | None = None) -> dict:
    now = now or now_utc()
    return {"phones": sum(_fresh(p, now) for p in doc.get("phones") or []), "phones_total": len(doc.get("phones") or []),
            "emails": sum(_fresh(e, now) for e in doc.get("emails") or []), "emails_total": len(doc.get("emails") or [])}
