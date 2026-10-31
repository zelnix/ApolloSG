"""ApolloSG Free Knowledge Base: free, public threat-intelligence feeds, normalised into the stores ApolloSG already has.

Every source here is free and public. Nothing is paid for, and no new server, platform or database is added: each feed is
downloaded through the bounded public transport (services/outbound.public_get) and written into the collection that
already holds that kind of intelligence.

- Listings → `threat_indicators`, ApolloSG's indicator store with its dual-timestamp lifecycle (first seen, last verified,
  evidence expiry). Scope `url` (an exact page, or a whole site when the source lists the site), `netblock`, `email` or
  `phone`. Only scope `hostname` ever becomes a native Site Gate rule (routers/guarddog.py), so none of these do.
  PhishTank and OpenPhish (phishing pages), Spamhaus DROP (criminal networks), ASIC's investor alert list (websites,
  email addresses and phone numbers of unlicensed and imposter financial operators) and ACMA's blocked illegal gambling
  websites. Link checks read them through services/intel.run_intel_check, as one list each.
- Knowledge → `higgins_knowledge` (the ApolloSG KB), as general knowledge, never case evidence: CISA's Known Exploited
  Vulnerabilities catalogue (kind `exploited_vulnerability`, with NVD's severity added) and MITRE ATT&CK techniques for
  Mobile and Enterprise (kind `attack_technique`).

Provenance on every record: the feed (`source`), the source's own reference (phish id, SBL id, ASIC entry, CVE, ATT&CK id),
the publisher, the licence or terms, when ApolloSG first saw it, when the source last confirmed it, and when it stops
counting (`evidence_expiry_deadline`).

Freshness: every feed refreshes once a day (REFRESH_EVERY), retried every RETRY_AFTER after a failure, and an admin can
refresh now. An entry missing from a successful refresh is delisted (expired, `source_delisted`); a knowledge entry its
source no longer lists becomes Historical. A download that is far smaller than the last one is refused rather than used to
delist everything. A list whose last success is older than its window is reported as not checked, never as clear.

Privacy: these are published lists about public infrastructure and scam operators. Email addresses and phone numbers are
kept only as one-way fingerprints (services/reusable_intel.subject_key), the same way ApolloSG keys them everywhere else.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable
from urllib.parse import urlparse

from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc
from core.models import IntelSource
from services.kb_sources import TIER_1, TIER_2
from services.outbound import gunzip, public_get

log = logging.getLogger("apollo.threat_feeds")

REFRESH_EVERY = timedelta(hours=24)
RETRY_AFTER = timedelta(hours=2)
LOCK_FOR = timedelta(minutes=30)
MIN_SHARE = 0.5          # a download with under half of last time's entries is refused
UNPACKED_LIMIT = 120_000_000
BATCH = 1000
LOCK_ID = "threat_feeds_lock"

LISTING_CONTENT = "threat_listing"
KNOWLEDGE_CONTENT = "threat_knowledge"


# ── Normalising what the lists hold ────────────────────────────────────────────

def norm_host(value: str) -> str:
    return (value or "").strip().lower().rstrip(".").removeprefix("www.")


def url_parts(raw: str) -> tuple[str, str] | None:
    """(site key, page key) for a link: the host without www., and host + path. Scheme, query and fragment are ignored."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = urlparse(text if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I) else f"https://{text}")
        host = norm_host(parsed.hostname or "")
    except ValueError:
        return None
    if not host or "." not in host or not re.fullmatch(r"[\w.-]+", host):
        return None
    return host, host + parsed.path.rstrip("/")


def parent_domains(host: str) -> list[str]:
    """The host's parent domains, up to and including its registrable domain."""
    from services.higgins.brand_domains import registrable
    host, top = norm_host(host), registrable(norm_host(host))
    parts, out = host.split("."), []
    for i in range(1, len(parts)):
        parent = ".".join(parts[i:])
        if len(parent) < len(top):
            break
        out.append(parent)
    return out


# Platforms where a listed address names one account or page, never the whole platform.
_PLATFORMS = frozenset({
    "facebook.com", "fb.com", "instagram.com", "t.me", "telegram.me", "telegram.org", "wa.me", "whatsapp.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "youtu.be", "tiktok.com", "google.com", "sites.google.com", "docs.google.com",
    "play.google.com", "apps.apple.com", "apple.com", "medium.com", "wix.com", "reddit.com", "discord.gg", "discord.com",
    "bit.ly", "tinyurl.com", "linktr.ee", "github.com", "dropbox.com", "drive.google.com", "forms.gle", "outlook.com",
})


@lru_cache(maxsize=65536)
def restricted(host: str) -> bool:
    """A shared platform itself, a free mail provider or an organisation's own (or official) domain: a listing here can
    only name one page, never the website. A user's own site on a shared service (name.weebly.com) isn't restricted."""
    from services import kb_sources
    from services.higgins import brand_domains
    from services.higgins.tc_flyby.triage import FREE_MAIL
    reg = brand_domains.registrable(host)
    if host in _PLATFORMS or reg in _PLATFORMS or (host == reg and (reg in brand_domains.SHARED_SERVICES or reg in FREE_MAIL)):
        return True
    return bool(brand_domains.owner(host) or kb_sources.source_for(f"https://{host}"))


def whole_site_allowed(host: str) -> bool:
    """A regulator's list may name a whole website, except a shared platform, a free mail provider or an organisation's
    own published domain: there it can only name the exact page."""
    from services.higgins import brand_domains
    from services.higgins.tc_flyby.triage import FREE_MAIL
    reg = brand_domains.registrable(host)
    return not (restricted(host) or reg in brand_domains.SHARED_SERVICES or reg in FREE_MAIL)


def names_a_page(raw: str, parts: tuple[str, str]) -> bool:
    """On a restricted host a listing counts only when it names a specific page: never the home page, and never a
    one-step address whose real target is in its query (google.com/url?q=…), because matching ignores the query."""
    host, page = parts
    if not restricted(host):
        return True
    if page == host:
        return False
    return not ("?" in raw and len([s for s in page[len(host):].split("/") if s]) < 2)


def _hex(ip: ipaddress._BaseAddress) -> str:
    return f"{int(ip):032x}"


def _subject(scope: str, value: str) -> str:
    from services.reusable_intel import subject_key
    return subject_key(scope, value)


# ── The feeds ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Feed:
    feed_id: str
    name: str                       # what it holds, for Feed Health and the admin page
    publisher: str
    url: str
    hosts: tuple[str, ...]          # where the download may come from, after redirects
    parse: Callable[[list[bytes]], list[dict]]
    store: str                      # indicators | knowledge | enrich
    listing: str = ""               # the list name link checks report (services/intel.py), for indicator feeds
    valid_for: timedelta = timedelta(days=3)
    limit: int = 8_000_000
    deadline: float = 60
    gzip_file: bool = False
    accept: str | None = None
    paged: bool = False
    licence: str = ""
    attribution: str = ""
    terms: str = ""
    tier: str = TIER_2
    jurisdiction: str = "INTL"
    kinds: tuple[str, ...] = field(default_factory=tuple)  # knowledge kinds this feed writes


def _indicator(scope: str, key: str, hostname: str, reference: str | None, evidence: str, threat_type: str, *,
               whole_site: bool = False, detail_url: str | None = None, source_first_seen: str | None = None, **extra) -> dict:
    return {"scope": scope, "key": key, "hostname": hostname, "source_reference": reference, "original_evidence": evidence[:500],
            "threat_type": threat_type, "whole_site": whole_site, "detail_url": detail_url, "source_first_seen": source_first_seen, **extra}


def parse_phishtank(pages: list[bytes]) -> list[dict]:
    rows = []
    for item in json.loads(pages[0]):
        raw = item.get("url") or ""
        parts = url_parts(raw)
        if not parts or item.get("verified") != "yes" or item.get("online") != "yes" or not names_a_page(raw, parts):
            continue
        target = item.get("target") or "Other"
        rows.append(_indicator("url", parts[1], parts[0], str(item.get("phish_id") or "") or None,
                               f"Verified phishing page{'' if target == 'Other' else f' targeting {target}'} (PhishTank phish {item.get('phish_id')})",
                               "SOCIAL_ENGINEERING", detail_url=item.get("phish_detail_url"), source_first_seen=item.get("submission_time")))
    return rows


def parse_openphish(pages: list[bytes]) -> list[dict]:
    rows = []
    for line in pages[0].decode("utf-8", "replace").splitlines():
        parts = url_parts(line)
        if parts and names_a_page(line, parts):
            rows.append(_indicator("url", parts[1], parts[0], None, "Phishing page detected by OpenPhish", "SOCIAL_ENGINEERING",
                                   detail_url="https://openphish.com/"))
    return rows


def parse_spamhaus_drop(pages: list[bytes]) -> list[dict]:
    rows = []
    for line in pages[0].decode("utf-8", "replace").splitlines():
        try:
            item = json.loads(line)
            net = ipaddress.ip_network(item["cidr"], strict=False)
        except (ValueError, KeyError, TypeError):
            continue  # the metadata line, or a malformed one
        rows.append(_indicator("netblock", str(net), str(net), item.get("sblid"),
                               f"Network {net} is on Spamhaus DROP ({item.get('sblid', 'no SBL id')}): hijacked or run by criminals",
                               "CRIMINAL_NETWORK", ip_version=net.version, net_start=_hex(net.network_address), net_end=_hex(net.broadcast_address)))
    return rows


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ASIC_TYPES = {"Imposter": "IMPOSTER_FINANCIAL_SERVICE"}
ASIC_LIST_PAGE = "https://moneysmart.gov.au/check-and-report-scams/investor-alert-list"


def parse_asic(pages: list[bytes]) -> list[dict]:
    rows = []
    for item in json.loads(pages[0]):
        name, category = (item.get("nameMandatory") or "an unnamed entity").strip(), item.get("investorAlertCategoryMandatory") or "Unlicensed"
        ref = str(item.get("uniqueIdentifier") or "") or None
        threat = _ASIC_TYPES.get(category, "UNLICENSED_FINANCIAL_SERVICE")
        evidence = f"On ASIC's investor alert list: {name} ({category}" + (f", updated {item['dateUpdated']})" if item.get("dateUpdated") else ")")
        common = {"detail_url": ASIC_LIST_PAGE, "source_first_seen": item.get("dateAdded"), "entity": name[:160], "category": category}
        for website in item.get("websites") or []:
            # ASIC writes notes beside some addresses ("bcfex.com (no longer works)") and stray spaces ("example .com").
            cleaned = re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", website or ""))
            parts = url_parts(cleaned)
            if not parts or not names_a_page(cleaned, parts):
                continue  # a bare platform or mail-provider address names nobody in particular
            host, page = parts
            whole = whole_site_allowed(host)
            rows.append(_indicator("url", host if whole else page, host, ref, evidence, threat, whole_site=whole, **common))
        for raw in item.get("emails") or []:
            for address in _EMAIL.findall(raw or ""):
                rows.append(_indicator("email", _subject("email", address), "", ref, evidence, threat, **common))
        for raw in item.get("phones") or []:
            digits = re.sub(r"\D", "", raw or "")
            if (raw or "").strip().lower().startswith("fax") or not 8 <= len(digits) <= 15:
                continue
            rows.append(_indicator("phone", _subject("phone", raw), "", ref, evidence, threat, **common))
    return rows


def parse_acma(pages: list[bytes]) -> list[dict]:
    rows = []
    for domain in json.loads(pages[0]):
        host = norm_host(str(domain))
        if "." in host and whole_site_allowed(host):
            rows.append(_indicator("url", host, host, None, f"{host} is on ACMA's list of blocked illegal gambling websites",
                                   "ILLEGAL_GAMBLING", whole_site=True, detail_url="https://www.acma.gov.au/blocked-gambling-websites"))
    return rows


KEV_PAGE = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"


def parse_kev(pages: list[bytes]) -> list[dict]:
    rows = []
    for item in json.loads(pages[0]).get("vulnerabilities") or []:
        cve = (item.get("cveID") or "").upper()
        if not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve):
            continue
        ransomware = " It is known to be used in ransomware campaigns." if item.get("knownRansomwareCampaignUse") == "Known" else ""
        body = "\n\n".join(part for part in [
            item.get("shortDescription") or "",
            f"Affected: {item.get('vendorProject', '')} {item.get('product', '')}.".replace("  ", " "),
            f"Actively exploited: CISA added it to its Known Exploited Vulnerabilities catalogue on {item.get('dateAdded')}.{ransomware}",
            f"What to do: {item['requiredAction']}" if item.get("requiredAction") else ""] if part)
        rows.append({"kind": "exploited_vulnerability", "key": cve, "title": f"{cve}: {item.get('vulnerabilityName') or 'Known exploited vulnerability'}",
                     "body": body, "url": f"{KEV_PAGE}?search_api_fulltext={cve}", "published_at": _day(item.get("dateAdded")),
                     "extra": {"source_reference": cve, "kev_body": body, "vendor": item.get("vendorProject"), "product": item.get("product"),
                               "date_added": item.get("dateAdded"), "due_date": item.get("dueDate"),
                               "ransomware": item.get("knownRansomwareCampaignUse"), "cwes": item.get("cwes") or []}})
    return rows


def parse_nvd(pages: list[bytes]) -> list[dict]:
    rows = []
    for page in pages:
        for wrapper in json.loads(page).get("vulnerabilities") or []:
            cve = wrapper.get("cve") or {}
            metrics = cve.get("metrics") or {}
            metric = next((m[0] for name in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30") if (m := metrics.get(name))), None)
            data = (metric or {}).get("cvssData") or {}
            description = next((d["value"] for d in cve.get("descriptions") or [] if d.get("lang") == "en"), "")
            rows.append({"key": cve.get("id", "").upper(), "nvd": {
                "score": data.get("baseScore"), "severity": data.get("baseSeverity") or (metric or {}).get("baseSeverity"),
                "cvss": data.get("version"), "vector": data.get("vectorString"), "description": description[:1500],
                "published": cve.get("published"), "last_modified": cve.get("lastModified")}})
    return [row for row in rows if row["key"]]


def nvd_line(nvd: dict | None) -> str:
    if not nvd or not nvd.get("score"):
        return ""
    return f"Severity (NVD): {nvd.get('severity') or 'unrated'}, {nvd['score']}/10 on CVSS {nvd.get('cvss') or ''}.".replace(" .", ".")


_CITATION = re.compile(r"\s*\(Citation:[^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _attack(domain: str) -> Callable[[list[bytes]], list[dict]]:
    def parse(pages: list[bytes]) -> list[dict]:
        rows = []
        for obj in json.loads(pages[0]).get("objects") or []:
            ref = next((r for r in obj.get("external_references") or [] if r.get("source_name") == "mitre-attack"), None)
            if obj.get("type") != "attack-pattern" or not ref or not ref.get("external_id"):
                continue
            tactics = [p["phase_name"].replace("-", " ").title() for p in obj.get("kill_chain_phases") or [] if p.get("phase_name")]
            text = _MD_LINK.sub(r"\1", _CITATION.sub("", obj.get("description") or "")).strip()
            body = "\n\n".join(part for part in [text, f"Tactics: {', '.join(tactics)}." if tactics else "",
                                                 f"Platforms: {', '.join(obj.get('x_mitre_platforms') or [])}." if obj.get("x_mitre_platforms") else ""] if part)
            rows.append({"kind": "attack_technique", "key": f"{domain}:{ref['external_id']}",
                         "title": f"{ref['external_id']}: {obj.get('name', '')} (MITRE ATT&CK {domain.title()})", "body": body,
                         "url": ref.get("url"), "published_at": _day(obj.get("created")),
                         "historical": bool(obj.get("revoked") or obj.get("x_mitre_deprecated")),
                         "extra": {"source_reference": ref["external_id"], "attack_id": ref["external_id"], "matrix": domain,
                                   "tactics": tactics, "platforms": obj.get("x_mitre_platforms") or [],
                                   "subtechnique": bool(obj.get("x_mitre_is_subtechnique")), "modified": obj.get("modified")}})
        return rows
    return parse


def _day(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_TAXII = "https://attack-taxii.mitre.org/api/v21/collections/{}/objects/?match%5Btype%5D=attack-pattern"
_ATTACK_TERMS = "https://attack.mitre.org/resources/legal-and-branding/terms-of-use/"
_ATTACK_ATTRIBUTION = "© The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation."
_US_GOV = "US Government work (public domain)"

FEEDS: tuple[Feed, ...] = (
    Feed("phishtank", "Verified phishing pages that are online now", "PhishTank (Cisco Talos)",
         "https://data.phishtank.com/data/online-valid.json.gz", ("data.phishtank.com", "cdn.phishtank.com"), parse_phishtank, "indicators",
         listing="phishtank", limit=12_000_000, deadline=120, gzip_file=True, licence="Free PhishTank data, with attribution to PhishTank",
         terms="https://phishtank.org/developer_info.php"),
    Feed("openphish", "Phishing pages (community feed)", "OpenPhish", "https://openphish.com/feed.txt",
         ("openphish.com", "raw.githubusercontent.com"), parse_openphish, "indicators", listing="openphish", limit=4_000_000,
         licence="OpenPhish Community Feed (free)", terms="https://openphish.com/phishing_feeds.html"),
    Feed("spamhaus-drop-v4", "Criminal networks (IPv4)", "The Spamhaus Project", "https://www.spamhaus.org/drop/drop_v4.json",
         ("www.spamhaus.org",), parse_spamhaus_drop, "indicators", listing="spamhaus_drop", valid_for=timedelta(days=7), limit=4_000_000,
         licence="Spamhaus DROP (free to use under its terms)", terms="https://www.spamhaus.org/drop/terms/"),
    Feed("spamhaus-drop-v6", "Criminal networks (IPv6)", "The Spamhaus Project", "https://www.spamhaus.org/drop/drop_v6.json",
         ("www.spamhaus.org",), parse_spamhaus_drop, "indicators", listing="spamhaus_drop", valid_for=timedelta(days=7), limit=2_000_000,
         licence="Spamhaus DROP (free to use under its terms)", terms="https://www.spamhaus.org/drop/terms/"),
    Feed("asic-investor-alerts", "Unlicensed and imposter financial operators: websites, email addresses and phone numbers",
         "Australian Securities and Investments Commission (ASIC)", "https://static.moneysmart.gov.au/_data/investor-alert-list.json",
         ("static.moneysmart.gov.au",), parse_asic, "indicators", listing="asic_investor_alerts", valid_for=timedelta(days=7),
         limit=12_000_000, licence="Published by ASIC on Moneysmart", terms="https://moneysmart.gov.au/copyright", tier=TIER_1, jurisdiction="AU"),
    Feed("acma-blocked-gambling", "Blocked illegal gambling websites", "Australian Communications and Media Authority (ACMA)",
         "https://backend.acma.gov.au/gmbl/api/Domain", ("backend.acma.gov.au",), parse_acma, "indicators", listing="acma_blocked_gambling",
         valid_for=timedelta(days=7), limit=4_000_000, licence="Published by ACMA", terms="https://www.acma.gov.au/copyright-notice",
         tier=TIER_1, jurisdiction="AU"),
    Feed("cisa-kev", "Known Exploited Vulnerabilities catalogue", "US Cybersecurity and Infrastructure Security Agency (CISA)",
         "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", ("www.cisa.gov",), parse_kev, "knowledge",
         limit=12_000_000, licence=_US_GOV, attribution="US Cybersecurity and Infrastructure Security Agency.", terms=KEV_PAGE, tier=TIER_1,
         kinds=("exploited_vulnerability",)),
    Feed("nvd-kev", "Severity of each known exploited vulnerability", "US National Vulnerability Database (NIST NVD)",
         "https://services.nvd.nist.gov/rest/json/cves/2.0?hasKev&resultsPerPage=2000", ("services.nvd.nist.gov",), parse_nvd, "enrich",
         limit=60_000_000, deadline=180, paged=True, licence=_US_GOV + "; this product uses the NVD API but is not endorsed or certified by the NVD",
         terms="https://nvd.nist.gov/developers/terms-of-use", tier=TIER_1),
    Feed("mitre-attack-mobile", "MITRE ATT&CK techniques for Mobile", "The MITRE Corporation (ATT&CK)",
         _TAXII.format("x-mitre-collection--dac0d2d7-8653-445c-9bff-82f934c1e858"), ("attack-taxii.mitre.org",), _attack("mobile"), "knowledge",
         limit=20_000_000, deadline=120, accept="application/taxii+json;version=2.1", licence="MITRE ATT&CK terms of use (royalty-free, with attribution)",
         attribution=_ATTACK_ATTRIBUTION, terms=_ATTACK_TERMS, kinds=("attack_technique",)),
    Feed("mitre-attack-enterprise", "MITRE ATT&CK techniques for Enterprise", "The MITRE Corporation (ATT&CK)",
         _TAXII.format("x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019"), ("attack-taxii.mitre.org",), _attack("enterprise"), "knowledge",
         limit=40_000_000, deadline=180, accept="application/taxii+json;version=2.1", licence="MITRE ATT&CK terms of use (royalty-free, with attribution)",
         attribution=_ATTACK_ATTRIBUTION, terms=_ATTACK_TERMS, kinds=("attack_technique",)),
)
BY_ID = {feed.feed_id: feed for feed in FEEDS}

# The lists a link check reports, one each: name → (how it's called, its feeds).
LISTINGS: dict[str, tuple[str, tuple[str, ...]]] = {}
for _feed in FEEDS:
    if _feed.listing:
        label = {"phishtank": "PhishTank", "openphish": "OpenPhish", "spamhaus_drop": "Spamhaus DROP",
                 "asic_investor_alerts": "ASIC's investor alert list", "acma_blocked_gambling": "ACMA's blocked gambling websites list"}[_feed.listing]
        LISTINGS[_feed.listing] = (label, LISTINGS.get(_feed.listing, (label, ()))[1] + (_feed.feed_id,))


# ── Downloading and storing ────────────────────────────────────────────────────

async def _download(feed: Feed) -> list[bytes]:
    async def one(url: str) -> bytes:
        response = await public_get(url, max_hops=3, limit=feed.limit, deadline=feed.deadline, accept=feed.accept)
        if response.status_code != 200 or urlparse(str(response.request.url)).hostname not in feed.hosts:
            raise ValueError("feed response rejected")
        return gunzip(response.content, UNPACKED_LIMIT) if feed.gzip_file else response.content
    pages = [await one(feed.url)]
    if feed.paged:  # NVD: page through totalResults, at NVD's public rate (5 requests in 30 seconds)
        first = json.loads(pages[0])
        start, total, size = first.get("resultsPerPage") or 0, first.get("totalResults") or 0, first.get("resultsPerPage") or 0
        while size and start < total and len(pages) < 10:
            await asyncio.sleep(6)
            pages.append(await one(f"{feed.url}&startIndex={start}"))
            start += size
    return pages


def _indicator_id(feed: Feed, row: dict) -> str:
    return "tf-" + hashlib.sha256(f"{feed.feed_id}|{row['scope']}|{row['key']}".encode()).hexdigest()[:24]


async def _store_indicators(feed: Feed, rows: list[dict], started: datetime) -> tuple[int, int]:
    unique = {(row["scope"], row["key"]): row for row in rows}
    added, ops = 0, []
    for row in unique.values():
        doc = {**row, "indicator_id": _indicator_id(feed, row), "source": feed.feed_id, "publisher": feed.publisher, "listing": feed.listing,
               "original_scope": row["scope"], "status": "active", "review_status": "auto_verified", "last_verified_at": started,
               "last_revalidation_at": started, "last_revalidation_outcome": "confirmed", "consecutive_check_failures": 0,
               "next_scheduled_check": started + REFRESH_EVERY, "evidence_expiry_deadline": started + feed.valid_for,
               "withdrawn_at": None, "withdrawal_reason": None, "updated_at": started, "added_by": f"feed:{feed.feed_id}"}
        ops.append(UpdateOne({"indicator_id": doc["indicator_id"]}, {"$set": doc, "$setOnInsert": {"first_seen_at": started, "added_at": started},
                                                                     "$inc": {"verification_count": 1}}, upsert=True))
        if len(ops) >= BATCH:
            added += (await db.threat_indicators.bulk_write(ops, ordered=False)).upserted_count
            ops = []
    if ops:
        added += (await db.threat_indicators.bulk_write(ops, ordered=False)).upserted_count
    removed = await db.threat_indicators.update_many(
        {"source": feed.feed_id, "status": {"$in": ["active", "check_overdue"]}, "last_verified_at": {"$lt": started}},
        {"$set": {"status": "expired", "withdrawal_reason": "source_delisted", "withdrawn_at": started, "updated_at": started,
                  "last_revalidation_outcome": "source_delisted", "last_revalidation_at": started}})
    return added, removed.modified_count


async def _store_knowledge(feed: Feed, rows: list[dict], started: datetime) -> tuple[int, int]:
    from services.higgins import knowledge
    scope = {"kind": {"$in": list(feed.kinds)}, "provenance.retrieved_via": feed.feed_id}
    before = await db.higgins_knowledge.count_documents(scope)
    nvd = {doc["key"]: doc.get("nvd") async for doc in db.higgins_knowledge.find({**scope, "nvd": {"$exists": True}}, {"_id": 0, "key": 1, "nvd": 1})}
    for row in rows:
        body = "\n\n".join(part for part in [row["body"], nvd_line(nvd.get(row["key"]))] if part)
        kb_id = await knowledge.upsert(row["kind"], row["key"], title=row["title"], body=body, publisher=feed.publisher, authority_tier=feed.tier,
                                       jurisdiction=feed.jurisdiction, url=row.get("url"), licence=feed.licence, attribution=feed.attribution,
                                       published_at=row.get("published_at"), retrieved_via=feed.feed_id, extra=row["extra"])
        if row.get("historical"):
            await db.higgins_knowledge.update_one({"kb_id": kb_id}, {"$set": {"status": "historical", "historical_reason": "deprecated_by_source"}})
    removed = await db.higgins_knowledge.update_many(
        {**scope, "provenance.last_checked_at": {"$lt": started}, "status": {"$ne": "historical"}},
        {"$set": {"status": "historical", "historical_at": started, "historical_reason": "no_longer_listed_by_source"}})
    knowledge.forget_weights()
    return await db.higgins_knowledge.count_documents(scope) - before, removed.modified_count


async def _enrich(rows: list[dict], started: datetime) -> tuple[int, int]:
    """NVD's severity, added to the CISA KEV entries ApolloSG already holds. Never adds or removes an entry."""
    enriched = 0
    async for doc in db.higgins_knowledge.find({"kind": "exploited_vulnerability", "key": {"$in": [row["key"] for row in rows]}},
                                               {"_id": 0, "kb_id": 1, "key": 1, "kev_body": 1}):
        nvd = next(row["nvd"] for row in rows if row["key"] == doc["key"])
        body = "\n\n".join(part for part in [doc.get("kev_body") or "", nvd_line(nvd)] if part)
        await db.higgins_knowledge.update_one({"kb_id": doc["kb_id"]}, {"$set": {"nvd": {**nvd, "retrieved_at": started}, "body": body}})
        enriched += 1
    return enriched, 0


async def _state(feed_id: str) -> dict:
    return await db.learning_feed_state.find_one({"feed_id": feed_id}, {"_id": 0}) or {}


async def refresh(feed: Feed, trigger: str = "scheduled") -> dict:
    """Download, check and store one feed. Its state goes on Feed Health (learning_feed_state) like the government feeds."""
    started = now_utc()
    run = {"run_id": secrets.token_hex(12), "feed_id": feed.feed_id, "pipeline": "threat_feeds", "trigger": trigger, "started_at": started,
           "status": "running", "fetched": 0, "accepted": 0, "added": 0, "removed": 0, "rejected": 0, "error": None}
    await db.learning_feed_runs.insert_one(dict(run))
    try:
        rows = feed.parse(await _download(feed))
        previous = (await _state(feed.feed_id)).get("item_count") or 0
        if not rows:
            raise ValueError("feed response rejected")
        if previous > 100 and len(rows) < previous * MIN_SHARE:
            raise ValueError("feed shrank unexpectedly")
        run["fetched"] = run["accepted"] = len(rows)
        store = {"indicators": _store_indicators, "knowledge": _store_knowledge}.get(feed.store)
        run["added"], run["removed"] = await (store(feed, rows, started) if store else _enrich(rows, started))
        run["status"] = "success"
        await db.learning_feed_state.update_one({"feed_id": feed.feed_id}, {"$set": {
            "feed_id": feed.feed_id, "pipeline": "threat_feeds", "last_checked_at": started, "last_success_at": started, "status": "fresh",
            "item_count": len(rows), "error": None, "error_detail": None}}, upsert=True)
    except Exception as exc:  # noqa: BLE001 — recorded for Feed Health; the next cycle tries again
        run["status"], run["error"] = "failed", type(exc).__name__
        detail = str(exc)[:120] if isinstance(exc, ValueError) else None
        log.warning("threat_feed_failed feed=%s error=%s detail=%s", feed.feed_id, type(exc).__name__, detail)
        await db.learning_feed_state.update_one({"feed_id": feed.feed_id}, {"$set": {
            "feed_id": feed.feed_id, "pipeline": "threat_feeds", "last_checked_at": started, "status": "unavailable",
            "error": type(exc).__name__, "error_detail": detail}}, upsert=True)
    run["finished_at"] = now_utc()
    await db.learning_feed_runs.update_one({"run_id": run["run_id"]}, {"$set": run})
    _fresh_cache.clear()
    return {k: run[k] for k in ("feed_id", "status", "fetched", "added", "removed", "error")}


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def due(state: dict, now: datetime) -> bool:
    checked, success = _aware(state.get("last_checked_at")), _aware(state.get("last_success_at"))
    if not checked:
        return True
    return (not success or now - success >= REFRESH_EVERY) and now - checked >= (RETRY_AFTER if state.get("status") == "unavailable" else REFRESH_EVERY)


async def _acquire() -> bool:
    now = now_utc()
    try:
        await db.apollo_kb_state.find_one_and_update({"_id": LOCK_ID, "$or": [{"held_until": None}, {"held_until": {"$lte": now}}]},
                                                     {"$set": {"held_until": now + LOCK_FOR}}, upsert=True)
        return True
    except DuplicateKeyError:
        return False


async def _release() -> None:
    await db.apollo_kb_state.update_one({"_id": LOCK_ID}, {"$set": {"held_until": None}})


async def run(feed_id: str | None = None, *, trigger: str = "scheduled", only_due: bool = False) -> dict:
    """Refresh every feed (or one, or only those due). Feeds run one at a time, in order: KEV before NVD's severity."""
    if not await _acquire():
        return {"status": "already_running", "feeds": []}
    results = []
    try:
        now = now_utc()
        for feed in FEEDS:
            if (feed_id and feed.feed_id != feed_id) or (only_due and not due(await _state(feed.feed_id), now)):
                continue
            results.append(await refresh(feed, trigger))
        await _expire_overdue()
    finally:
        await _release()
    return {"status": "done", "feeds": results}


async def _expire_overdue() -> int:
    """Listings whose feed stopped confirming them stop counting at their expiry deadline."""
    now = now_utc()
    result = await db.threat_indicators.update_many(
        {"source": {"$in": list(BY_ID)}, "status": {"$in": ["active", "check_overdue"]}, "evidence_expiry_deadline": {"$lte": now}},
        {"$set": {"status": "expired", "withdrawal_reason": "expired_unverified", "withdrawn_at": now, "updated_at": now}})
    return result.modified_count


async def ensure_indexes() -> None:
    await db.threat_indicators.create_index([("scope", 1), ("key", 1)])
    await db.threat_indicators.create_index([("source", 1), ("status", 1), ("last_verified_at", 1)])
    await db.threat_indicators.create_index([("scope", 1), ("ip_version", 1), ("net_start", 1)])
    await db.higgins_knowledge.create_index([("kind", 1), ("provenance.retrieved_via", 1)])
    await db.higgins_knowledge.create_index([("kind", 1), ("source_reference", 1)])


# ── Lookups ────────────────────────────────────────────────────────────────────

_fresh_cache: dict[str, tuple[datetime, set[str]]] = {}


async def fresh_feeds() -> set[str]:
    """Feeds whose last success is within their window (kept a minute)."""
    cached = _fresh_cache.get("fresh")
    now = now_utc()
    if cached and now - cached[0] < timedelta(minutes=1):
        return cached[1]
    fresh = set()
    async for state in db.learning_feed_state.find({"feed_id": {"$in": list(BY_ID)}}, {"_id": 0, "feed_id": 1, "last_success_at": 1}):
        success = _aware(state.get("last_success_at"))
        if success and now - success <= BY_ID[state["feed_id"]].valid_for:
            fresh.add(state["feed_id"])
    _fresh_cache["fresh"] = (now, fresh)
    return fresh


def _active(now: datetime) -> dict:
    return {"status": "active", "evidence_expiry_deadline": {"$gt": now}}


async def _addresses(host: str) -> list[ipaddress._BaseAddress] | None:
    """The host's IP addresses (an IP literal is its own); None when they couldn't be found."""
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443), timeout=2.5)
    except (OSError, asyncio.TimeoutError):
        return None
    return list({ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos})


def _when(value) -> str:
    value = _aware(value)
    return value.strftime("on %-d %b %Y") if isinstance(value, datetime) else "recently"


_MATCH_FIELDS = {"_id": 0, "source": 1, "original_evidence": 1, "threat_type": 1, "last_verified_at": 1, "first_seen_at": 1,
                 "source_reference": 1, "detail_url": 1, "evidence_expiry_deadline": 1, "publisher": 1}

# Each list's own page, for a person to see the list (and, where the list has one, the entry itself).
LIST_PAGES = {"phishtank": "https://phishtank.org/", "openphish": "https://openphish.com/", "spamhaus_drop": "https://www.spamhaus.org/drop/",
              "asic_investor_alerts": ASIC_LIST_PAGE, "acma_blocked_gambling": "https://www.acma.gov.au/blocked-gambling-websites"}


async def matches(host: str, url: str | None = None, *, ips: list | None = None) -> list[dict]:
    """The current free-list entries for a link or website, with their provenance. `ips`: the website's addresses, for
    Spamhaus DROP (none given: networks aren't compared)."""
    now = now_utc()
    host = norm_host(host)
    parts = url_parts(url) if url else None
    keys = list(dict.fromkeys([host, *([parts[1]] if parts else [])]))
    rows = await db.threat_indicators.find(
        {"scope": "url", **_active(now), "$or": [{"key": {"$in": keys}}, {"key": {"$in": parent_domains(host)}, "whole_site": True}]},
        _MATCH_FIELDS).to_list(20)
    for ip in ips or []:
        rows += await db.threat_indicators.find(
            {"scope": "netblock", "ip_version": ip.version, "net_start": {"$lte": _hex(ip)}, "net_end": {"$gte": _hex(ip)}, **_active(now)},
            _MATCH_FIELDS).to_list(5)
    return [row for row in rows if row["source"] in BY_ID]


async def listing_sources(host: str, url: str | None = None) -> list[IntelSource]:
    """One IntelSource per free list for a link (url) or a website (host): match, clear, or unavailable when the list
    isn't current — never clear by default. `url` is the list's own page (the entry's page when the list has one)."""
    fresh = await fresh_feeds()
    ips = await _addresses(norm_host(host))
    found = await matches(host, url, ips=ips)
    out = []
    for name, (label, feed_ids) in LISTINGS.items():
        hits = [m for m in found if m["source"] in feed_ids]
        if hits:
            evidence = hits[0]["original_evidence"]
            by = "" if label in evidence else f" by {label}"
            out.append(IntelSource(name=name, status="match", threat_types=sorted({h["threat_type"] for h in hits}),
                                   detail=f"{evidence} — confirmed{by} {_when(hits[0]['last_verified_at'])}.",
                                   url=hits[0].get("detail_url") or LIST_PAGES[name]))
        elif not any(f in fresh for f in feed_ids):
            out.append(IntelSource(name=name, status="unavailable", failure="list_out_of_date", url=LIST_PAGES[name],
                                   detail=f"{label} hasn't been refreshed recently, so it wasn't checked."))
        elif name == "spamhaus_drop" and ips is None:
            out.append(IntelSource(name=name, status="unavailable", failure="dns_failed", url=LIST_PAGES[name],
                                   detail=f"ApolloSG couldn't find this website's IP address to compare with {label}."))
        else:
            out.append(IntelSource(name=name, status="clear", detail=f"Not on {label}.", url=LIST_PAGES[name]))
    return out


async def listed(scope: str, value: str) -> list[dict]:
    """The current listings of an email address or phone number (ASIC's investor alert list)."""
    now = now_utc()
    rows = await db.threat_indicators.find({"scope": scope, "key": _subject(scope, value), **_active(now)},
                                           {"_id": 0, "source": 1, "publisher": 1, "entity": 1, "category": 1, "detail_url": 1,
                                            "original_evidence": 1, "last_verified_at": 1}).to_list(5)
    return rows


# ── Admin ──────────────────────────────────────────────────────────────────────

async def status() -> list[dict]:
    """Each feed with its health (Feed Health's 24-hour rule), entries current, and its last run."""
    from services import feed_health
    now, rows = now_utc(), []
    for feed in FEEDS:
        state = await _state(feed.feed_id)
        last = await db.learning_feed_runs.find_one({"feed_id": feed.feed_id, "pipeline": "threat_feeds"}, {"_id": 0}, sort=[("started_at", -1)])
        if feed.store == "indicators":
            current = await db.threat_indicators.count_documents({"source": feed.feed_id, **_active(now)})
        elif feed.store == "knowledge":
            current = await db.higgins_knowledge.count_documents({"provenance.retrieved_via": feed.feed_id, "status": {"$ne": "historical"}})
        else:
            current = await db.higgins_knowledge.count_documents({"kind": "exploited_vulnerability", "nvd": {"$exists": True}})
        rows.append({"feed": feed, "state": state, "health": feed_health.classify(state or None, now), "current": current, "last_run": last,
                     "error": feed_health.error_message(state.get("error"), state.get("error_detail")) if state.get("status") == "unavailable" else None})
    return rows
