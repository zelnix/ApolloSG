"""Apollo V1 backend — application entry point (`uvicorn server:app`).

Privacy posture:
- Explicit checks may use user-submitted text, links, chosen screenshots or mailbox items for one
  disclosed, purpose-limited assessment. Request-scoped raw copies are not persisted by Apollo.
- Credentials and secret URL parameters are removed before processing; outbound page fetches are bounded and SSRF-safe.
- Patrol receives only sanitised summaries/evidence, and reputation caches store HMAC digests rather than raw indicators.

Layout (Hardening Gate step 4 — split of the former monolith, zero behaviour change):
- core/      config (env), db (Motor + document base), models (shared schemas), auth (device bearer + admin key)
- services/  intel (blocklist, Safe Browsing, cache, redirects), email (guardian invitations)
- routers/   one APIRouter per domain; all mounted under /api behind `enforce_device_auth`, except
             routers/admin (mounted under /api/admin behind `require_admin_key`).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from core.auth import enforce_device_auth, require_admin_key
from core.config import ADMIN_HEADER, logger
from core.db import client, db, now_utc
from core.models import BlocklistEntry
from core.privacy_boundary import PrivacyBoundary
from services.patrol_policy import ensure_evidence_receipt_indexes
from services import patrol_records
from services.mailbox_monitor import ensure_indexes as ensure_mailbox_monitor_indexes, supervise_mailbox_monitor
from services.maintenance import ensure_indexes as ensure_maintenance_indexes, supervise_maintenance
from services.higgins.retention import migrate_and_index
from services.higgins import repository as investigation_repository
from services.higgins import report_store
from services import system_health_jobs
from services.higgins import context as higgins_context
from services import capability_registry, government_alerts, learning
from services import gemini_usage
from services import triage_engine
from services import gmail as gmail_service
from services import family_assist
from services.threat_revalidation import ensure_indexes as ensure_threat_indexes, migrate_blocklist_entries
from routers import admin, admin_portal, analysis, ask, call, devices, family, family_assist as family_assist_router, family_weekly, gmail, health, intel, investigations, learning as learning_router, learning_admin, patrol, phone_identity as phone_identity_router, posture, product, protections, push, triage_telemetry, usage
from routers.family_weekly import weekly_checkin_loop
from services.seed_learning_images import router as seed_images_router

# ── Blocklist disabled (product decision: Apollo does not maintain an independent threat catalogue) ──
# SEED_BLOCKLIST population stopped. Historical data preserved in db.blocklist.
# External intelligence providers (Safe Browsing etc.) remain the authoritative verdict sources.


@asynccontextmanager
async def lifespan(_: FastAPI):
    # ── Preview provider ──────────────────────────────────────────────────
    # The simulator is installed ONLY on the preview server (see provider.preview_environment). The preview/
    # directory is deployed with everything else, so its presence decides nothing; production stays live Gemini.
    from services.higgins.provider import get_provider_mode, preview_environment
    if preview_environment():
        from services.higgins.preview.dispatch import install_preview_provider
        install_preview_provider()
    logger.info("provider_mode=%s", get_provider_mode())

    await migrate_and_index()
    await investigation_repository.ensure_indexes()
    from services import device_pickup
    await device_pickup.ensure_indexes()
    await report_store.ensure_indexes()
    await system_health_jobs.ensure_indexes()
    await higgins_context.ensure_indexes()
    await government_alerts.ensure_indexes()
    from services.higgins import knowledge as higgins_knowledge
    await higgins_knowledge.ensure_indexes()
    try:
        # Reusable intelligence (not KB knowledge): its indexes, and the KB's old saved Gemini answers moved into it.
        from services import reusable_intel
        await reusable_intel.ensure_indexes()
        await reusable_intel.migrate_gemini_answers()
    except Exception:  # noqa: BLE001 — the cache must never block startup
        logger.warning("reusable intelligence setup failed", exc_info=True)
    await learning.ensure_indexes()
    try:
        # Sources first (article citations are checked against them), then the same Learn library in every
        # environment — content comes from the code, never from a one-off script run against one database.
        await learning.seed_catalogue_sources_feeds()
        await learning.seed_learning_articles()
        await learning.seed_catalogue_articles()
        from services import learning_feeds as _feeds
        await _feeds.purge_listing_page_links()
        await _feeds.repair_feed_links()
    except Exception:  # noqa: BLE001 — seeding must never block startup
        logger.warning("learning catalogue seed failed", exc_info=True)
    try:
        from services import apollo_kb
        await apollo_kb.ensure_indexes()
    except Exception:  # noqa: BLE001 — the knowledge base must never block startup
        logger.warning("apollo kb setup failed", exc_info=True)
    await capability_registry.ensure_indexes()
    await investigation_repository.backfill_work_epochs()
    try:
        # Records saved under TC Hawkeye's old internal name ("teddy") move to its current names; nothing to do once moved.
        from services.higgins.tc_flyby import legacy_names
        await legacy_names.migrate()
    except Exception:  # noqa: BLE001 — renaming old records must never block startup
        logger.warning("TC Hawkeye legacy name migration failed", exc_info=True)
    try:
        # Past cases judged again under the current rules, once per rule catalogue version (services/triage/rejudge.py).
        from services.triage import rejudge
        await rejudge.migrate()
    except Exception:  # noqa: BLE001 — re-judging old records must never block startup
        logger.warning("triage re-judge migration failed", exc_info=True)
    # Legacy retention migration removed — server no longer retains completed investigations
    await ensure_maintenance_indexes()
    await gemini_usage.ensure_indexes()
    # Daily AI spending limits (reserve → settle ledger) and one-piece-of-work-per-evidence claims.
    from services import ai_budget, work_dedupe
    await ai_budget.ensure_indexes()
    await work_dedupe.ensure_indexes()
    await triage_engine.ensure_indexes()
    from services.triage.store import ensure_indexes as ensure_triage_history_indexes
    await ensure_triage_history_indexes()
    from services.triage.telemetry import ensure_indexes as ensure_triage_telemetry_indexes
    await ensure_triage_telemetry_indexes()
    try:
        await db.admin_sessions.create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        # Production Atlas may already have this index — tolerate conflicts on startup.
        pass
    await ensure_mailbox_monitor_indexes()
    await push.ensure_indexes()
    await family_assist.ensure_indexes()
    await ensure_threat_indexes()
    from services import threat_feeds
    await threat_feeds.ensure_indexes()
    try:
        # Official Organisation Directory (shipped list; admin-edited entries are never overwritten) and the
        # privacy-safe observed patterns' indexes.
        from services import observed_intel, org_directory
        await org_directory.seed()
        await org_directory.load()
        await observed_intel.ensure_indexes()
        # This device's own case history (one-way codes only; services/higgins/history.py).
        from services.higgins import history as case_history
        await case_history.ensure_indexes()
    except Exception:  # noqa: BLE001 — the directory must never block startup
        logger.warning("official organisation directory setup failed", exc_info=True)
    # Caller reputation freshness index
    await db.caller_id_numbers.create_index("evidence_expires_at")
    # Legacy blocklist migration disabled (product decision: no independent Apollo threat catalogue).
    # Historical blocklist data and ThreatIndicator records preserved for audit.
    await db.devices.create_index("device_id", unique=True)
    await db.devices.create_index("token_hash", unique=True, partialFilterExpression={"token_hash": {"$type": "string"}})
    await db.reputation_cache.create_index("indicator_digest", unique=True)
    await db.reputation_cache.create_index("expires_at")  # plain index; expiry is checked at read time, never auto-deleted
    await db.domain_info_cache.create_index("domain", unique=True)
    await db.domain_info_cache.create_index("expires_at")  # plain index; expiry is checked at read time, never auto-deleted
    # Multi-account: one row per (device, Gmail account). Drop the legacy device_id-unique index
    # (it capped a device to a single account) and migrate to a compound unique index.
    try:
        existing = await db.gmail_connections.index_information()
        if "device_id_1" in existing and not existing["device_id_1"].get("key") == [("device_id", 1), ("email", 1)]:
            await db.gmail_connections.drop_index("device_id_1")
    except Exception as exc:  # noqa: BLE001
        logger.info("gmail index migration skipped: %s", type(exc).__name__)
    # Backfill: legacy rows without an email get a placeholder so the compound index accepts them.
    await db.gmail_connections.update_many({"email": {"$exists": False}}, {"$set": {"email": ""}})
    await db.gmail_connections.create_index([("device_id", 1), ("email", 1)], unique=True)
    # Legacy: cleanup_unreadable_connections was removed from automatic startup
    # to avoid destroying user data in production. If cleanup is needed, run it
    # as an explicit admin operation.
    # OAuth state index migration — tolerant of first-deploy (empty collection) and Atlas environments.
    try:
        oauth_indexes = await db.gmail_oauth_states.index_information()
        for index_name, definition in oauth_indexes.items():
            if definition.get("key") == [("state", 1)]:
                await db.gmail_oauth_states.drop_index(index_name)
                continue
            if definition.get("key") == [("expires_at", 1)] and definition.get("partialFilterExpression") != {"retention_class": "oauth_csrf_temporary"}:
                await db.gmail_oauth_states.drop_index(index_name)
        # Legacy records without state_digest are left in place; they'll expire via TTL index.
        # Destructive delete_many removed: production deploys must not delete existing OAuth state records.
        pass
    except Exception:  # noqa: BLE001
        logger.warning("OAuth state index migration skipped (first deploy or index already migrated)")
    await db.gmail_oauth_states.create_index("state_digest", unique=True)
    # Plain index on expires_at; expiry is checked at read time, never auto-deleted.
    # A TTL index (expireAfterSeconds=0) would hard-delete OAuth CSRF state records
    # automatically, which is destructive on deployment restarts.
    # Migration: the old TTL index "oauth_csrf_expiry_ttl" must be dropped first
    # because MongoDB rejects a new index on the same key+filter with different options.
    try:
        await db.gmail_oauth_states.drop_index("oauth_csrf_expiry_ttl")
        logger.info("Dropped legacy TTL index oauth_csrf_expiry_ttl")
    except Exception:  # noqa: BLE001
        pass  # Index doesn't exist (first deploy or already migrated)
    await db.gmail_oauth_states.create_index("expires_at",
                                              name="oauth_csrf_expiry_plain",
                                              partialFilterExpression={"retention_class": "oauth_csrf_temporary"})
    # Generic IMAP credentials are no longer accepted or written. Legacy rows are retained for an explicit,
    # audited migration rather than destructively dropping user data on every process start.
    await db.mailbox_assessment_receipts.create_index([("provider", 1), ("device_id", 1), ("message_digest", 1)], unique=True)
    await db.phone_risk_cache.create_index("phone_e164", unique=True)
    await db.patrol_events.create_index([("device_id", 1), ("event_id", 1)], unique=True)
    await ensure_evidence_receipt_indexes()
    await patrol_records.ensure_indexes()
    await db.trust_entries.create_index("trust_id", unique=True)
    await db.ask_messages.create_index([("device_id", 1), ("created_at", 1)])
    await db.ask_handoffs.create_index([("device_id", 1), ("handoff_id", 1)], unique=True)
    await db.blocklist.create_index("host", unique=True)  # Preserved for historical data; no longer seeded
    await db.admin_audit.create_index([("at", -1)])
    await db.incident_notes.create_index("note_id")
    await db.family_audio_cleanup.create_index("cleanup_id", unique=True)
    await db.incident_notes.create_index([("guardian_device_id", 1), ("protected_device_id", 1), ("submission_id", 1)], unique=True,
                                         partialFilterExpression={"submission_id": {"$type": "string"}})
    # ── Background loops — Stage 12 audit ────────────────────────────────────
    # Each loop has a single clear purpose. No two loops perform the same job.
    #
    # 1. weekly_checkin_loop       — Device-check-in reminder (weekly cadence).
    # 2. supervise_mailbox_monitor — Connected email account monitoring (per-account schedule).
    # 3. government_alert_loop     — Scam Alerts ingestion + shared learning-feed refresh (15 min).
    #    Calls government_alerts.refresh_all() which also invokes learning_feeds.refresh_due().
    #    Each learning feed has its own refresh_interval_minutes — Learn weekly publishing is
    #    NOT run every 15 minutes; it only checks whether each feed's individual interval has elapsed.
    # 4. family_assist_loop        — Family Help session/media maintenance (15 s heartbeat).
    # 5. push_receipt_loop         — Expo push receipt reconciliation (5 min).
    # 6. supervise_maintenance     — Evidence/case cleanup, worker heartbeat (own schedule).
    loop_task = asyncio.create_task(weekly_checkin_loop())
    mailbox_task = asyncio.create_task(supervise_mailbox_monitor(), name="apollo-mailbox-supervisor")
    async def government_alert_loop():
        while True:
            try:
                await government_alerts.refresh_all()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("government alert refresh failed")
            await asyncio.sleep(900)  # 15 min between refresh cycles
    government_alert_task = asyncio.create_task(government_alert_loop(), name="apollo-government-alerts")
    async def family_assist_loop():
        while True:
            try:
                await family_assist.maintenance_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # no session/media payload logging
                logger.warning("family assist maintenance failed")
            await asyncio.sleep(15)
    family_assist_task = asyncio.create_task(family_assist_loop(), name="apollo-family-assist")

    # Gentle alerts raised during quiet hours are held, not dropped: this releases each one, separately,
    # once the person's quiet window has ended.
    async def quiet_hold_loop():
        while True:
            try:
                await push.release_held_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("held alert release failed")
            await asyncio.sleep(60)

    quiet_hold_task = asyncio.create_task(quiet_hold_loop(), name="apollo-quiet-hold")
    maintenance_task = asyncio.create_task(supervise_maintenance(), name="apollo-maintenance-supervisor")

    # 7. learn_weekly_publish_loop — Auto-publish pending learning candidates (weekly cadence).
    #    Runs weekly_publish() from learning_feeds once every 7 days.  On each tick it also
    #    calls refresh_due() so that feed ingestion + publishing happen in the same cycle.
    async def learn_weekly_publish_loop():
        while True:
            try:
                from services import learning_feeds
                await learning_feeds.refresh_due()
                result = await learning_feeds.weekly_publish()
                if result["promoted"] or result["published"]:
                    logger.info("learn weekly publish: promoted=%d published=%d skipped=%d failed=%d",
                                result["promoted"], result["published"], result["skipped"], result["failed"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("learn weekly publish loop failed")
            await asyncio.sleep(604_800)  # 7 days in seconds

    learn_publish_task = asyncio.create_task(learn_weekly_publish_loop(), name="apollo-learn-weekly-publish")

    # 8. apollo_kb_loop — Tavily maintains the Apollo Knowledge Base once a week (admin console has a
    #    refresh button). Hourly it only asks whether a weekly run is due; the schedule lives in the DB.
    async def apollo_kb_loop():
        from services import apollo_kb
        await asyncio.sleep(120)  # let startup settle first
        while True:
            try:
                if await apollo_kb.due():
                    await apollo_kb.run("scheduled")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("apollo kb loop failed")
            await asyncio.sleep(3600)

    apollo_kb_task = asyncio.create_task(apollo_kb_loop(), name="apollo-kb")

    # 9. threat_feeds_loop — the free threat-intelligence feeds (services/threat_feeds.py): each refreshes once a day,
    #    failures are retried every 2 hours. Hourly it only refreshes the feeds that are due; admins can refresh now.
    async def threat_feeds_loop():
        from services import observed_intel, org_directory, threat_feeds
        await asyncio.sleep(90)  # let startup settle first
        while True:
            try:
                await threat_feeds.run(trigger="scheduled", only_due=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("threat feeds loop failed")
            try:
                # Re-read each organisation's own pages once a week (a day after an unreadable attempt); drop
                # observations nobody made in the last 30 days.
                await org_directory.run(trigger="scheduled", only_due=True)
                await observed_intel.purge()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("official organisation directory loop failed")
            try:
                # Descriptive phone names (Google Play's supported devices list), once a week.
                from services import device_models
                await device_models.run_if_due()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("device model names loop failed")
            await asyncio.sleep(3600)

    threat_feeds_task = asyncio.create_task(threat_feeds_loop(), name="apollo-threat-feeds")

    # Admin → Screens: in the preview, picks up captures requested from the live admin panel (services/screen_capture.py).
    from services import screen_capture
    screens_task = asyncio.create_task(screen_capture.queue_loop(), name="apollo-screens-queue")

    yield
    screens_task.cancel()
    threat_feeds_task.cancel()
    apollo_kb_task.cancel()
    learn_publish_task.cancel()
    maintenance_task.cancel()
    quiet_hold_task.cancel()
    loop_task.cancel()
    mailbox_task.cancel()
    government_alert_task.cancel()
    family_assist_task.cancel()
    await asyncio.gather(screens_task, threat_feeds_task, apollo_kb_task, learn_publish_task, maintenance_task, quiet_hold_task, loop_task, mailbox_task, government_alert_task, family_assist_task, return_exceptions=True)
    client.close()


app = FastAPI(title="ApolloSG V1 API", lifespan=lifespan)
app.add_middleware(PrivacyBoundary)


@app.exception_handler(HTTPException)
async def typed_failure_handler(request: Request, exc: HTTPException):
    """Investigation routes raise the spec's `{"error": Failure}` body; legacy routes keep FastAPI's `{"detail": ...}`."""
    body = exc.detail if isinstance(exc.detail, dict) and "error" in exc.detail else {"detail": exc.detail}
    headers = dict(exc.headers or {})
    if request.url.path.startswith("/api/health/"):
        headers["Cache-Control"] = "no-store"
    return JSONResponse(body, status_code=exc.status_code, headers=headers)


@app.get("/health", include_in_schema=False)
async def deployment_health():
    """Root liveness probe for the deployment platform (unauthenticated, no DB). Device-facing health stays at /api/health."""
    return {"status": "ok"}


# Every device-facing router is mounted under /api behind the device bearer gate (public paths are listed in core.auth).
for r in (health, devices, intel, patrol, investigations, ask, learning_router, product, family, family_assist_router, family_weekly, push, analysis, gmail, call, posture, protections, triage_telemetry, phone_identity_router):
    app.include_router(r.router, prefix="/api", dependencies=[Depends(enforce_device_auth)])
app.include_router(family_assist_router.ws_router, prefix="/api")
app.include_router(admin_portal.router, prefix="/api", tags=["admin-portal"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])
app.include_router(learning_admin.router, prefix="/api/admin", tags=["learning-admin"], dependencies=[Depends(require_admin_key)])
app.include_router(seed_images_router, prefix="/api", tags=["learning-seed"])
# Learning images are public (no auth needed for serving cached images)
app.include_router(learning_router.public_router, prefix="/api", tags=["learning-public"])
app.include_router(usage.router, prefix="/api", tags=["usage"])
# The Apollo SG banner that emails load (public: a mail app has no device credential).
from routers import brand as brand_router
app.include_router(brand_router.router, prefix="/api", tags=["brand"])
# The privacy policy web page (public: the App Store listing and a browser have no device credential).
from routers import legal as legal_router
app.include_router(legal_router.router, prefix="/api", tags=["legal"])

# GuardDog production trust endpoints (unauthenticated — public trust artifacts and controlled verification).
from routers import guarddog as guarddog_router
app.include_router(guarddog_router.router)

# GuardDog live reputation (device-authenticated — Site Gate DNS checks).
from routers import guarddog_live
app.include_router(guarddog_live.router, dependencies=[Depends(enforce_device_auth)])

# Temporary diagnostic log capture (no auth — frontend posts traces here during investigation debugging).
from routers import debug_log as debug_log_router
app.include_router(debug_log_router.router, prefix="/api", tags=["debug"])


# CORS is not authentication (bearer tokens do that). The web preview is same-origin (/api on the same host), and native
# apps don't use CORS, so only explicitly configured browser origins are allowed (add the admin console's origin here).
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=_cors_origins, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key", ADMIN_HEADER, "X-Admin-Actor"])
