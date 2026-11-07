"""Consumer snapshot for reviewed-source government alerts with explicit freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.db import db, now_utc
from services import learning_feeds, scam_analysis, scam_intel

STALE_AFTER = timedelta(hours=6)

# Display names for official sources whose stored name is an unexplained acronym. Apollo never shows a
# bare acronym to the person — the full authority name is spelled out (abbreviation kept in brackets).
SOURCE_DISPLAY_NAME = {
    "ncsc-uk": "UK National Cyber Security Centre",
    "ic3": "FBI Internet Crime Complaint Center (IC3)",
    "enisa": "European Union Agency for Cybersecurity (ENISA)",
    "moneysmart": "Moneysmart (ASIC)",
}


def _source_name(source_id: str, fallback: str | None) -> str:
    return SOURCE_DISPLAY_NAME.get(source_id, fallback or source_id)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def ensure_indexes() -> None:
    await db.learning_feed_items.create_index("fingerprint", unique=True)
    await db.learning_feed_items.create_index("expires_at", expireAfterSeconds=0)
    await db.learning_feed_state.create_index("feed_id", unique=True)
    # Cleanup indexes for accumulating temporary records (§5 freshness correction)
    await db.learning_candidates.create_index("fingerprint", unique=True)
    await db.learning_candidates.create_index("created_at")  # For periodic cleanup
    await db.learning_feed_runs.create_index("started_at")   # For periodic cleanup


async def refresh_all() -> None:
    await learning_feeds.refresh_due()
    try:
        from services import scam_analysis
        await scam_analysis.analyze_pending()
    except Exception:  # noqa: BLE001 — analysis is best-effort; ingestion must never fail because of it
        pass
    try:
        from services.higgins import knowledge
        await knowledge.refresh()
    except Exception:  # noqa: BLE001 — the knowledge base catches up on the next cycle
        pass
    try:
        from services.higgins import kb_queue
        await kb_queue.process_pending()
    except Exception:  # noqa: BLE001 — KB queue retries on the next cycle
        pass


async def cleanup_stale_records() -> dict:
    """Remove accumulating temporary records that are no longer needed.
    
    - learning_candidates older than 120 days: intermediate ingestion records
    - learning_feed_runs older than 30 days: historical refresh run logs
    
    Feed items themselves are cleaned by MongoDB's TTL index (expires_at).
    Published educational content is NOT affected.
    """
    cutoff_candidates = now_utc() - timedelta(days=120)
    cutoff_runs = now_utc() - timedelta(days=30)
    
    candidates_removed = (await db.learning_candidates.delete_many(
        {"created_at": {"$lt": cutoff_candidates}}
    )).deleted_count
    
    runs_removed = (await db.learning_feed_runs.delete_many(
        {"started_at": {"$lt": cutoff_runs}}
    )).deleted_count
    
    return {"candidates_removed": candidates_removed, "runs_removed": runs_removed}


# ── Freshness rules ───────────────────────────────────────────────────────────
# Default publication window: 60 days. Older warnings are kept ONLY when the analysis
# recorded verified ongoing activity evidence (verifiedOngoing=true) that describes the
# actual consumer threat. Rechecking an old article does not make its warning current.
# Undated items: require verified ongoing activity; otherwise excluded.
RECENCY_CUTOFF = timedelta(days=60)
# Extended window for warnings with verified ongoing campaign evidence
VERIFIED_ONGOING_CUTOFF = timedelta(days=365)


def _parse_reported(value: str | None) -> datetime | None:
    """Parse the AI's structured reportedDate ('YYYY-MM-DD' or 'YYYY-MM') into an aware datetime."""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _month_year(dt: datetime | None) -> str:
    return dt.strftime("%B %Y") if dt else "Date not stated"


# ── Single eligibility rule ───────────────────────────────────────────────────
# The same relevance, audience and freshness checks for the feed, badge and Apollo state.
def is_eligible(built: dict, now: datetime) -> bool:
    """Return True if an alert is eligible for the feed, badge and Apollo state.
    This is the ONE eligibility gate — used everywhere, not just in the feed."""
    tier = built.get("tier", "general_education")
    # Only specific_scam and emerging_pattern are alerts
    if tier not in ("specific_scam", "emerging_pattern"):
        return False
    # Audience: only consumer alerts
    if built.get("audience") != "consumer":
        return False
    # Relevance: must be relevant to Australia (confirmed or verified global applicable)
    relevance = built.get("australianRelevance", "unknown")
    if relevance == "overseas_only":
        return False
    if relevance == "unknown":
        return False
    # relevance is "confirmed" or "potential" (potential = verified global consumer threat)
    # Freshness
    effective = built.get("effectiveDate")
    verified_ongoing = built.get("verifiedOngoing", False)
    if effective:
        age = now - effective
        if age > RECENCY_CUTOFF:
            # Older than 60 days: only keep if verified ongoing AND within the extended window
            if not verified_ongoing or age > VERIFIED_ONGOING_CUTOFF:
                return False
    else:
        # Undated: require verified ongoing activity evidence
        if not verified_ongoing:
            return False
    return True


def _alert(row: dict, source: dict, analysis: dict, now: datetime) -> dict:
    """Build one consumer alert from a feed item + its cached analysis. Only facts the analysis
    extracted from the source are shown; nothing is invented here."""
    published = _aware(row.get("published_at"))
    reported = _parse_reported(analysis.get("reportedDate"))
    effective = published or reported  # when this specific scam was reported
    region = scam_intel.region_for(row["source_id"])
    sections = analysis.get("sections") or {}
    severity = analysis.get("severity", "LOW")
    relevance = analysis.get("australianRelevance", "unknown")
    relevance_reason = analysis.get("australianRelevanceReason") or ""
    source_name = _source_name(row["source_id"], source.get("name"))
    # Where it applies
    applies, named = scam_analysis.applies_in(row.get("title") or "", row.get("summary") or "", region)
    applies_label = scam_intel.REGION_LABEL.get(applies, applies)
    place = f"the {applies_label}" if applies_label.startswith(("United ", "European ")) else applies_label
    if applies == "unknown":
        applies_reason = "No evidence of Australian applicability or global consumer threat."
    elif applies == "global":
        applies_reason = "This is a global consumer threat that can affect people in Australia."
    elif named:
        applies_reason = f'It names "{named}", which is specific to {place}.'
    else:
        applies_reason = f"Published by an Australian authority." if applies == "AU" else "It doesn't name anything specific to one country."
    if applies not in ("AU", "global", "unknown") and applies != "everywhere":
        relevance, relevance_reason = "overseas_only", f"Only applies in {place}. {applies_reason}"
    # Verified ongoing activity (recorded separately from refresh time)
    verified_ongoing = analysis.get("verifiedOngoing", False)
    verified_ongoing_evidence = analysis.get("verifiedOngoingEvidence", "")
    verified_ongoing_at = analysis.get("verifiedOngoingAt")
    fresh = bool(effective and (now - effective) <= RECENCY_CUTOFF)
    # Growl rule: same eligibility as the feed. A specific High/Extreme campaign growls when it passes
    # the full eligibility check (relevance + freshness + audience).
    growling = False  # set after eligibility check below
    higgins = {
        "whatHappened": sections.get("whatHappened") or (row.get("summary") or row.get("title") or ""),
        "whyGrowling": analysis.get("severityReason") or "",
        "whereHappening": sections.get("whereHappening") or "",
        "whatItMeansForAustralia": sections.get("whatItMeansForYou") or "",
        "whatToWatch": sections.get("whatToWatch") or "",
        "whatToDo": sections.get("whatToDo") or "",
        "source": source_name,
        "publishedAt": (published or reported).isoformat() if (published or reported) else None,
        "dateLabel": _month_year(effective),
        "url": row.get("url"),
    }
    built = {
        "title": row["title"], "url": row["url"], "summary": row["summary"], "source": source_name,
        "sourceUrl": (source.get("canonical_base_urls") or [None])[0], "sourceType": row["content_type"], "sourceTrust": row["trust_status"],
        "publishedAt": published, "updatedAt": _aware(row.get("updated_at")), "lastCheckedAt": _aware(row["last_checked_at"]),
        "reportedDate": analysis.get("reportedDate") or "", "effectiveDate": effective, "dateLabel": _month_year(effective),
        "ageLabel": _month_year(effective),
        "region": region, "regionLabel": scam_intel.REGION_LABEL.get(region, region),
        "tier": analysis.get("tier", "general_education"), "audience": analysis.get("audience", "consumer"), "facts": analysis.get("facts") or {},
        "severity": severity, "severityReason": analysis.get("severityReason") or "", "severityConfidence": analysis.get("confidence") or "low",
        "sourceSeverity": row.get("source_severity"),
        "australianRelevance": relevance, "australianRelevanceReason": relevance_reason,
        "appliesIn": applies, "appliesInLabel": "Everywhere" if applies in ("everywhere", "global") else applies_label, "appliesInReason": applies_reason,
        "verifiedOngoing": verified_ongoing, "verifiedOngoingEvidence": verified_ongoing_evidence, "verifiedOngoingAt": verified_ongoing_at,
        "growling": False, "higgins": higgins,
    }
    # Apply the single eligibility rule for growling — same gate as the feed and badge
    if is_eligible(built, now) and severity in ("HIGH", "EXTREME") and analysis.get("tier") == "specific_scam":
        built["growling"] = True
    return built


async def alert_by_url(url: str) -> dict | None:
    """One analysed alert/advisory by its official URL, in the same consumer shape as the feed."""
    row = await db.learning_feed_items.find_one({"url": url, "scam_analysis.analysisVersion": scam_analysis.ANALYSIS_VERSION},
                                                {"_id": 0, "fingerprint": 0, "candidate_id": 0, "expires_at": 0})
    if not row:
        return None
    source = await db.learning_sources.find_one({"source_id": row["source_id"]}, {"_id": 0}) or {}
    return _alert(row, source, row["scam_analysis"], now_utc())


async def snapshot(limit: int = 50) -> dict:
    now = now_utc(); feeds = await db.learning_feeds.find({"enabled": True}, {"_id": 0}).to_list(100)
    source_ids = {row["source_id"] for row in feeds}; sources = {row["source_id"]: row for row in await db.learning_sources.find({"source_id": {"$in": list(source_ids)}}, {"_id": 0}).to_list(100)}
    states = {row["feed_id"]: row for row in await db.learning_feed_state.find({}, {"_id": 0}).to_list(100)}
    feed_states = {}
    for feed in feeds:
        row = states.get(feed["feed_id"]); success = _aware(row.get("last_success_at")) if row else None
        latest_failed = bool(row and row.get("status") == "unavailable")
        status = "unavailable" if not success else "stale" if latest_failed or now - success > STALE_AFTER else "fresh"
        source = sources.get(feed["source_id"], {})
        feed_states[feed["feed_id"]] = {"status": status, "source": _source_name(feed["source_id"], source.get("name")), "sourceUrl": (source.get("canonical_base_urls") or [None])[0],
            "sourceType": feed["content_type"], "lastSuccessAt": success, "lastCheckedAt": _aware(row.get("last_checked_at")) if row else None,
            "errorType": row.get("error") if latest_failed else None}
    rows = await db.learning_feed_items.find({}, {"_id": 0, "fingerprint": 0, "candidate_id": 0, "expires_at": 0}).sort("published_at", -1).limit(200).to_list(200)
    alerts: list[dict] = []; emerging: list[dict] = []; pending = 0; stale = 0
    shown_urls: set[str] = set()
    for row in rows:
        analysis = row.get("scam_analysis")
        if not analysis or analysis.get("analysisVersion") != scam_analysis.ANALYSIS_VERSION:
            pending += 1
            continue
        if row["url"] in shown_urls:
            continue
        shown_urls.add(row["url"])
        source = sources.get(row["source_id"], {})
        built = _alert(row, source, analysis, now)
        # Apply the single eligibility rule
        if not is_eligible(built, now):
            if built["effectiveDate"] and (now - built["effectiveDate"]) > RECENCY_CUTOFF:
                stale += 1
            continue
        if built["tier"] == "specific_scam":
            alerts.append(built)
        elif built["tier"] == "emerging_pattern":
            emerging.append(built)
    # Most recent first; undated items sort last.
    _key = lambda it: it["effectiveDate"] or datetime.min.replace(tzinfo=timezone.utc)
    alerts.sort(key=_key, reverse=True); emerging.sort(key=_key, reverse=True)
    alerts = alerts[:limit]; emerging = emerging[:limit]
    growling = next((it for it in alerts if it["growling"]), None)
    last_analysed = max((_aware(r.get("scam_analysis", {}).get("analyzedAt")) for r in rows if r.get("scam_analysis")), default=None)
    last_sourced = max((v.get("lastSuccessAt") for v in feed_states.values() if v.get("lastSuccessAt")), default=None)
    return {"coverage": "Specific scam campaigns reported by recognised government and official cyber-authority sources (Australia, USA, UK, EU), each read and explained from the source itself. General scam education lives in Learn with Higgins.",
            "generatedAt": now, "feeds": feed_states, "alerts": alerts, "emerging": emerging, "pendingCount": pending,
            "lastAnalysedAt": last_analysed, "lastSourcedAt": last_sourced, "growling": growling}
