"""Apollo Admin Portal — Google-authenticated operations dashboard.

Privacy: monitors Apollo, not Apollo's users. No customer PII.
Protection: never manufactures THREAT_BLOCKED / verified_block / Apollo is biting.
Truthfulness: every status from a real source; 'Unknown' when unverifiable.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import markdown
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from core.db import db, now_utc
from core import local_time
from core.brand import BANNER_ALT, BANNER_PATH
from services.gemini_usage import MODEL_PRICING
from services.higgins import ai_settings, model_test, provider
from services.admin_health import (
    OK, DEGRADED, DOWN, UNKNOWN, CONNECTED, NOT_CONFIGURED, UNABLE,
    get_dashboard_health, check_integrations, get_usage_and_costs,
    check_database, check_backend, check_ai_provider, check_magnum_di,
)

load_dotenv()

router = APIRouter(tags=["admin"])

ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL", "")).strip().casefold()
SESSION_TTL_HOURS = 8
EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
REPORT_DIR = Path(__file__).resolve().parent.parent

_SESSIONS = "admin_sessions"

# ── Nav items ────────────────────────────────────────────────────────────────

NAV = [
    ("Dashboard",       "/api/admin/portal",          "&#9632;"),
    ("Protection",      "/api/admin/protection",       "&#128737;"),
    ("Magnum DI",       "/api/admin/magnum-di",        "&#128270;"),
    ("Integrations",    "/api/admin/integrations",     "&#128279;"),
    ("Usage & Costs",   "/api/admin/usage",            "&#128176;"),
    ("Investigations",  "/api/admin/investigations-cost", "&#128200;"),
    ("Triage",          "/api/admin/triage",           "&#9878;"),
    ("Knowledge Base",  "/api/admin/knowledge",        "&#128218;"),
    ("Official Organisations", "/api/admin/org-directory", "&#127970;"),
    ("Intelligence Reuse", "/api/admin/intel-reuse",   "&#9851;"),
    ("Rule Book",       "/api/admin/rule-book",        "&#128214;"),
    ("Play Store",      "/api/admin/play-console",     "&#9654;"),
    ("Family Help Test", "/api/admin/family-help-test", "&#128241;"),
    ("Devices",         "/api/admin/device-list",      "&#128242;"),
    ("AI Map",          "/api/admin/gemini-map",       "&#129517;"),
    ("Reconciliation",  "/api/admin/reconciliation",   "&#128209;"),
    ("Incident Report", "/api/admin/investigations-cost?period=oct17", "&#128293;"),
    ("System",          "/api/admin/system",           "&#9881;"),
    ("Releases",        "/api/admin/releases",         "&#128230;"),
    ("Screens",         "/api/admin/screens",          "&#128444;"),
    ("Diagnostics",     "/api/admin/diagnostics",      "&#128295;"),
    ("Audit",           "/api/admin/audit-log",        "&#128220;"),
    ("ApolloSG Settings", "/api/admin/apollosg-settings", "&#9881;"),
    ("Admin",           "/api/admin/settings",         "&#128100;"),
]

REPORTS = {
    "gemini-usage-investigation": ("GEMINI_USAGE_INVESTIGATION.md", "Gemini Usage Investigation — Root Cause Analysis"),
    "gemini-usage-tracking": ("GEMINI_USAGE_TRACKING_REPORT.md", "Gemini Usage Tracking Report"),
    "play-console": ("content/play_console_declarations.md", "Google Play Console declarations"),
    "family-help-test": ("content/family_help_two_phone_test.md", "Family Help two-phone test"),
}


# ── Session helpers ──────────────────────────────────────────────────────────

def _cookie_kw() -> dict:
    return dict(key="apollo_admin", httponly=True, samesite="lax", path="/",
                max_age=SESSION_TTL_HOURS * 3600,
                secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")


async def _admin(request: Request) -> Optional[dict]:
    tok = request.cookies.get("apollo_admin")
    if not tok:
        return None
    row = await db[_SESSIONS].find_one({"token": tok})
    if not row:
        return None
    if row.get("expires_at") and row["expires_at"].replace(tzinfo=timezone.utc) < now_utc():
        await db[_SESSIONS].delete_one({"_id": row["_id"]})
        return None
    return row


def _login_redirect():
    return RedirectResponse("/api/admin/login", status_code=303)


def _origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    return f"{proto}://{host}"


async def _audit_log(email: str, action: str, detail: str = ""):
    try:
        await db.admin_audit.insert_one({
            "email": email, "action": action, "detail": detail,
            "timestamp": now_utc(),
        })
    except Exception:
        pass


# ── Auth routes ──────────────────────────────────────────────────────────────

@router.get("/admin/login")
async def admin_login(request: Request):
    return RedirectResponse(
        "https://auth.emergentagent.com/?" + urlencode({"redirect": _origin(request) + "/api/admin/auth/callback"}),
        status_code=303)


@router.get("/admin/auth/callback", response_class=HTMLResponse)
async def admin_auth_callback():
    return _shell("Signing in…", "", """
    <div style="display:flex;align-items:center;justify-content:center;height:80vh;">
      <div style="text-align:center;">
        <div class="spinner"></div>
        <p style="margin-top:16px;color:var(--muted);">Authenticating with Google…</p>
        <p id="err" style="color:var(--red);display:none;margin-top:12px;"></p>
      </div>
    </div>
    <script>
    (async()=>{const p=new URLSearchParams(location.hash.slice(1)),sid=p.get('session_id'),err=document.getElementById('err');
    if(!sid){err.textContent='Missing session. Please try again.';err.style.display='block';return;}
    try{const r=await fetch('/api/admin/auth/exchange',{method:'POST',headers:{'content-type':'application/json'},
    credentials:'same-origin',body:JSON.stringify({session_id:sid})});
    if(r.ok){location.replace('/api/admin/portal');return;}
    err.textContent=r.status===403?'Access denied. This account is not authorised.':'Sign-in failed.';
    err.style.display='block';}catch(e){err.textContent='Network error.';err.style.display='block';}})();
    </script>""", show_nav=False)


@router.post("/admin/auth/exchange")
async def admin_auth_exchange(request: Request):
    body = await request.json()
    sid = body.get("session_id", "")
    if not sid or len(sid) > 4096:
        return HTMLResponse("Invalid session", status_code=400)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": sid})
    if r.status_code != 200:
        return HTMLResponse("Invalid or expired sign-in", status_code=401)
    identity = r.json()
    email = (identity.get("email") or "").strip().casefold()
    if not ADMIN_EMAIL or not secrets.compare_digest(email, ADMIN_EMAIL):
        return HTMLResponse("Not authorised", status_code=403)
    token = secrets.token_urlsafe(32)
    now = now_utc()
    await db[_SESSIONS].insert_one({
        "token": token, "email": email, "name": identity.get("name", ""),
        "picture": identity.get("picture", ""), "created_at": now,
        "expires_at": now + timedelta(hours=SESSION_TTL_HOURS),
    })
    await _audit_log(email, "login")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(value=token, **_cookie_kw())
    return resp


@router.post("/admin/logout")
async def admin_logout(request: Request):
    tok = request.cookies.get("apollo_admin")
    if tok:
        sess = await db[_SESSIONS].find_one({"token": tok})
        if sess:
            await _audit_log(sess.get("email", ""), "logout")
        await db[_SESSIONS].delete_one({"token": tok})
    resp = RedirectResponse("/api/admin/login", status_code=303)
    resp.delete_cookie("apollo_admin", path="/")
    return resp


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/admin/portal", response_class=HTMLResponse)
async def dashboard(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    h = await get_dashboard_health()
    overall = h["overall"]
    overall_color = _status_color(overall)
    attention = h.get("attention", [])
    subs = h.get("subsystems", {})
    platforms = h.get("platforms", {})
    gates = h.get("gates", {})

    # Status cards
    sub_cards = ""
    sub_order = [
        ("ai_provider", "AI Provider"),
        ("magnum_di", "Magnum DI"),
        ("higgins", "Higgins Chat"),
        ("protection", "Protection"),
        ("privacy_redaction", "Privacy / Redaction"),
        ("database", "Database"),
        ("backend", "Backend / API"),
    ]
    for key, label in sub_order:
        s = subs.get(key, {"status": UNKNOWN, "detail": "Not checked"})
        sub_cards += _status_card(label, s["status"], s.get("detail", ""))

    # Gate health
    gate_cards = ""
    if isinstance(gates, dict) and "error" not in gates:
        for g, info in sorted(gates.items()):
            if g == "unknown" and info.get("count_24h", 0) > 0:
                gate_cards += _mini_status("&#9888; Unattributed", DEGRADED, f"{info.get('count_24h', 0)} checks need review")
            else:
                gate_cards += _mini_status(g.title(), info.get("status", UNKNOWN), f"{info.get('count_24h', 0)} checks/24h")

    # Platform health
    plat_cards = ""
    if isinstance(platforms, dict) and "error" not in platforms:
        for p, info in sorted(platforms.items()):
            plat_cards += _mini_status(p.title(), info.get("status", UNKNOWN),
                                       f"{info.get('registered_devices', 0):,} devices")

    # Attention
    attn_html = ""
    if attention:
        items = "".join(f"<li>{html_mod.escape(a)}</li>" for a in attention)
        attn_html = f'<div class="alert alert-warning"><strong>Attention required</strong><ul>{items}</ul></div>'
    else:
        attn_html = '<div class="alert alert-ok">No issues requiring attention</div>'

    # Recent admin activity
    recent = await db.admin_audit.find({}, {"_id": 0}).sort("timestamp", -1).limit(10).to_list(10)
    activity_rows = ""
    for r in recent:
        ts = r.get("timestamp", "")
        activity_rows += f"<tr><td>{_t(ts)}</td><td>{html_mod.escape(r.get('action',''))}</td><td>{html_mod.escape(str(r.get('detail',''))[:80])}</td></tr>"

    # Reports
    report_links = ""
    for slug, (_, title) in REPORTS.items():
        report_links += f'''<div class="report-row">
            <a href="/api/admin/reports/{slug}">{html_mod.escape(title)}</a>
            <a href="/api/admin/reports/{slug}/pdf" class="btn btn-sm" title="Download PDF">PDF</a>
        </div>'''

    body = f"""
    <div class="overall-banner" style="border-left:4px solid {overall_color};">
        <span class="dot" style="background:{overall_color};"></span>
        <span><strong>ApolloSG Status:</strong> {overall.upper()}</span>
        <span style="color:var(--muted);font-size:0.85em;margin-left:auto;">{_t(h.get('timestamp'))}</span>
    </div>
    {attn_html}

    <h2>Subsystem Health</h2>
    <div class="status-grid">{sub_cards}</div>

    <h2>Gate Health</h2>
    <div class="mini-grid">{gate_cards or '<span style="color:var(--muted);">No gate data available</span>'}</div>

    <h2>Platform Health</h2>
    <div class="mini-grid">{plat_cards or '<span style="color:var(--muted);">No platform data</span>'}</div>

    <h2>Reports</h2>
    <div class="report-list">{report_links}</div>

    <h2>Recent Admin Activity</h2>
    <table><thead><tr><th>Time</th><th>Action</th><th>Detail</th></tr></thead>
    <tbody>{activity_rows or '<tr><td colspan="3" style="color:var(--muted);">No recent activity</td></tr>'}</tbody></table>
    """
    return _shell("Dashboard", "/api/admin/portal", body, admin=adm)


# ── Protection ───────────────────────────────────────────────────────────────

@router.get("/admin/protection", response_class=HTMLResponse)
async def protection(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    h = await get_dashboard_health()
    gates = h.get("gates", {})
    prot = h.get("subsystems", {}).get("protection", {"status": UNKNOWN, "detail": ""})

    gate_rows = ""
    if isinstance(gates, dict) and "error" not in gates:
        for g, info in sorted(gates.items()):
            count = info.get("count_24h", 0)
            status = info.get("status", UNKNOWN)
            detail = info.get("detail", "")
            c = _status_color(status)
            if g == "unknown" and count > 0:
                # Unattributed checks — show as warning, not healthy
                gate_rows += (f"<tr style='background:rgba(210,153,34,0.08);'>"
                              f"<td><span class='dot' style='background:var(--yellow);'></span> "
                              f"&#9888; Unknown / Unattributed</td>"
                              f"<td style='text-align:right'>{count}</td>"
                              f"<td style='color:var(--yellow);'>{count} unattributed checks &mdash; attribution requires review</td></tr>")
            else:
                gate_rows += f"<tr><td><span class='dot' style='background:{c};'></span> {g.title()}</td><td style='text-align:right'>{count}</td><td>{status}{(' &mdash; ' + html_mod.escape(detail)) if detail else ''}</td></tr>"

    # Aggregate investigation outcomes (not individual user data)
    try:
        since = now_utc() - timedelta(hours=24)
        pipeline = [
            {"$match": {"created_at": {"$gte": since}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        outcomes = {r["_id"]: r["count"] for r in await db.investigation_reports.aggregate(pipeline).to_list(20)}
    except Exception:
        outcomes = {}

    outcome_rows = ""
    for st, ct in sorted(outcomes.items(), key=lambda x: -x[1]):
        outcome_rows += f"<tr><td>{st or 'unknown'}</td><td style='text-align:right'>{ct:,}</td></tr>"

    # Count unattributed for backfill button
    unattributed_count = sum(info.get("count_24h", 0) for g, info in gates.items() if g == "unknown") if isinstance(gates, dict) and "error" not in gates else 0
    backfill_btn = ""
    if unattributed_count > 0:
        backfill_btn = f"""
        <div class="alert alert-warning" style="margin-top:12px;">
            <strong>&#9888; {unattributed_count} unattributed checks found.</strong>
            Gate attribution was not recorded for these investigations.
            You can attempt to reclassify them using existing evidence metadata.
            <form method="post" action="/api/admin/backfill-gates" style="margin-top:8px;">
                <button type="submit" class="btn btn-sm">Run Gate Backfill</button>
            </form>
        </div>"""

    body = f"""
    <div class="overall-banner" style="border-left:4px solid {_status_color(prot['status'])};">
        <span class="dot" style="background:{_status_color(prot['status'])};"></span>
        <span><strong>Protection:</strong> {prot.get('detail','')}</span>
    </div>

    <h2>Gate Activity (24h)</h2>
    <table><thead><tr><th>Gate</th><th style="text-align:right">Checks</th><th>Status</th></tr></thead>
    <tbody>{gate_rows or '<tr><td colspan="3" style="color:var(--muted);">No gate data</td></tr>'}</tbody></table>
    {backfill_btn}

    <h2>Investigation Outcomes (24h, aggregate)</h2>
    <table><thead><tr><th>Outcome</th><th style="text-align:right">Count</th></tr></thead>
    <tbody>{outcome_rows or '<tr><td colspan="2" style="color:var(--muted);">No investigations</td></tr>'}</tbody></table>

    <p style="color:var(--muted);font-size:0.82em;margin-top:16px;">
        Protection truth rule: This portal observes ApolloSG. Verified enforcement comes only from genuine native enforcement evidence.
        This portal never creates THREAT_BLOCKED, verified_block, or "Apollo is biting" status.
    </p>
    """
    return _shell("Protection", "/api/admin/protection", body, admin=adm)


# ── Magnum DI ────────────────────────────────────────────────────────────────

@router.get("/admin/magnum-di", response_class=HTMLResponse)
async def magnum_di(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    md_health = await check_magnum_di()
    ai_health = await check_ai_provider()

    # Aggregate investigation stats (no user data)
    try:
        since = now_utc() - timedelta(hours=24)
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}, "success": True, "purpose": "investigation"}},
            {"$group": {"_id": None,
                        "calls": {"$sum": 1},
                        "avg_input": {"$avg": "$tokens.input"},
                        "max_input": {"$max": "$tokens.input"},
                        "avg_duration": {"$avg": "$duration_ms"},
                        "total_input": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
                        "total_output": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
                        "total_cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}}}}
        ]
        inv_stats = (await db.gemini_usage.aggregate(pipeline).to_list(1)) or [{}]
        inv = inv_stats[0] if inv_stats else {}
    except Exception:
        inv = {}

    body = f"""
    <div class="overall-banner" style="border-left:4px solid {_status_color(md_health['status'])};">
        <span class="dot" style="background:{_status_color(md_health['status'])};"></span>
        <span><strong>Magnum DI:</strong> {md_health.get('detail','')}</span>
    </div>

    <h2>AI Provider</h2>
    {_status_card("Gemini API", ai_health['status'], ai_health.get('detail',''))}

    <h2>Investigation Engine (24h)</h2>
    <div class="stats-grid">
        {_stat_card(f"{inv.get('calls', 0):,}", "Gemini Calls")}
        {_stat_card(f"{inv.get('avg_input', 0):,.0f}", "Avg Input Tokens")}
        {_stat_card(f"{inv.get('max_input', 0):,}", "Max Input Tokens")}
        {_stat_card(f"{inv.get('avg_duration', 0):,.0f} ms", "Avg Duration")}
        {_stat_card(f"{inv.get('total_input', 0):,}", "Total Input Tokens")}
        {_stat_card(f"${inv.get('total_cost', 0):.4f}", "Estimated Cost")}
    </div>

    <h2>Reports</h2>
    <div class="report-list">
        <div class="report-row"><a href="/api/admin/reports/gemini-usage-investigation">Gemini Usage Investigation — Root Cause Analysis</a>
            <a href="/api/admin/reports/gemini-usage-investigation/pdf" class="btn btn-sm">PDF</a></div>
        <div class="report-row"><a href="/api/admin/reports/gemini-usage-tracking">Gemini Usage Tracking Report</a>
            <a href="/api/admin/reports/gemini-usage-tracking/pdf" class="btn btn-sm">PDF</a></div>
    </div>
    """
    return _shell("Magnum DI", "/api/admin/magnum-di", body, admin=adm)


# ── Integrations ─────────────────────────────────────────────────────────────

@router.get("/admin/integrations", response_class=HTMLResponse)
async def integrations(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    intg = await check_integrations()
    rows = ""
    for key, info in intg.items():
        st = info.get("status", UNKNOWN)
        c = _integration_color(st)
        extras = ""
        for k, v in info.items():
            if k not in ("name", "status", "detail"):
                shown = _t(v) if _is_time(v) else html_mod.escape(str(v))
                extras += f"<span style='color:var(--muted);font-size:0.82em;'>{k}: {shown}</span> "
        rows += f"""<tr>
            <td><span class="dot" style="background:{c};"></span> {html_mod.escape(info.get('name', key))}</td>
            <td><span class="badge" style="background:{c}22;color:{c};">{_integration_label(st)}</span></td>
            <td>{html_mod.escape(info.get('detail', ''))}</td>
            <td style="font-size:0.82em;color:var(--muted);">{extras}</td>
        </tr>"""

    body = f"""
    <h2>Configured Integrations</h2>
    <table><thead><tr><th>Integration</th><th>Status</th><th>Detail</th><th>Info</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <p style="color:var(--muted);font-size:0.82em;margin-top:12px;">
        States: <span class="badge" style="background:#3fb95022;color:#3fb950;">Connected</span>
        <span class="badge" style="background:#d2992222;color:#d29922;">Degraded</span>
        <span class="badge" style="background:#8b949e22;color:#8b949e;">Not Configured</span>
        <span class="badge" style="background:#f8514922;color:#f85149;">Unable to Verify</span>
    </p>
    """
    return _shell("Integrations", "/api/admin/integrations", body, admin=adm)


# ── Usage & Costs ────────────────────────────────────────────────────────────

@router.get("/admin/usage", response_class=HTMLResponse)
async def usage_costs(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    data = await get_usage_and_costs()
    summary = data["summary"]
    alerts = data.get("alerts", [])

    alert_html = ""
    for a in alerts:
        cls = "alert-critical" if a["level"] == "critical" else "alert-warning"
        alert_html += f'<div class="alert {cls}">{html_mod.escape(a["message"])}</div>'

    svc_rows = ""
    for s in data["services"]:
        indent_cls = " style='padding-left:32px;color:var(--muted);'" if s.get("indent") else ""
        svc_rows += f"""<tr>
            <td{indent_cls}>{html_mod.escape(s.get('service',''))}</td>
            <td>{html_mod.escape(str(s.get('usage_today','')))}</td>
            <td>{html_mod.escape(str(s.get('usage_month','')))}</td>
            <td>{html_mod.escape(str(s.get('cost_today','')))}</td>
            <td>{html_mod.escape(str(s.get('cost_month','')))}</td>
            <td>{html_mod.escape(str(s.get('projected_month','')))}</td>
            <td>{html_mod.escape(str(s.get('status','')))}</td>
        </tr>"""

    body = f"""
    {alert_html}
    <h2>Cost Summary</h2>
    <div class="stats-grid">
        {_stat_card(summary.get('cost_today','N/A'), "Cost Today")}
        {_stat_card(summary.get('cost_month','N/A'), "Month-to-Date")}
        {_stat_card(summary.get('projected_month','N/A'), "Projected Month-End")}
        {_stat_card(summary.get('budget','Not set'), "Monthly Budget")}
        {_stat_card(summary.get('budget_used_pct','N/A'), "Budget Used")}
    </div>

    <h2>Service Breakdown</h2>
    <table style="font-size:0.88em;">
        <thead><tr><th>Service</th><th>Usage Today</th><th>Usage This Month</th><th>Cost Today</th><th>Cost MTD</th><th>Projected</th><th>Status</th></tr></thead>
        <tbody>{svc_rows}</tbody>
    </table>

    <p style="color:var(--muted);font-size:0.82em;margin-top:16px;">
        Costs are estimated from tracked token usage at published model rates.
        Where billing data is unavailable, "Cost unavailable" is shown.
        Backend hosting, data transfer, and storage costs are not tracked here.
    </p>
    """
    return _shell("Usage & Costs", "/api/admin/usage", body, admin=adm)



# ── Reconciliation ───────────────────────────────────────────────────────────

@router.get("/admin/reconciliation", response_class=HTMLResponse)
async def reconciliation(request: Request):
    """Full usage reconciliation: traces every gemini_usage record, cross-references
    with investigation_reports, and surfaces timestamp-boundary discrepancies."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    now = now_utc()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rolling_24h = now - timedelta(hours=24)

    # ── 1. Timestamp boundary analysis ──
    total_all_time = await db.gemini_usage.count_documents({})
    total_today = await db.gemini_usage.count_documents({"timestamp": {"$gte": today_start}})
    total_today_ok = await db.gemini_usage.count_documents({"timestamp": {"$gte": today_start}, "success": True})
    total_today_fail = await db.gemini_usage.count_documents({"timestamp": {"$gte": today_start}, "success": False})
    total_rolling = await db.gemini_usage.count_documents({"timestamp": {"$gte": rolling_24h}})

    inv_reports_24h = await db.investigation_reports.count_documents({"created_at": {"$gte": rolling_24h}})
    inv_reports_today = await db.investigation_reports.count_documents({"created_at": {"$gte": today_start}})
    inv_reports_all = await db.investigation_reports.count_documents({})

    earliest_rec = await db.gemini_usage.find_one({}, {"timestamp": 1}, sort=[("timestamp", 1)])
    latest_rec = await db.gemini_usage.find_one({}, {"timestamp": 1}, sort=[("timestamp", -1)])
    earliest_ts = _t(earliest_rec["timestamp"]) if earliest_rec else "N/A"
    latest_ts = _t(latest_rec["timestamp"]) if latest_rec else "N/A"

    boundary_html = f"""
    <h2>1. Timestamp Boundary Analysis</h2>
    <div class="alert alert-warning">
        <strong>Key insight:</strong> "Cost Today" uses <code>gemini_usage.timestamp &ge; midnight UTC</code>
        (calendar-day, success=True only). "Investigations in last 24h" uses
        <code>investigation_reports.created_at &ge; now &minus; 24h</code> (rolling window, different collection).
        These query <strong>different data</strong>: individual API calls vs completed investigation reports.
    </div>
    <table>
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody>
            <tr><td>Report generated at</td><td><code>{_t(now)}</code></td></tr>
            <tr><td>"Today" boundary (midnight UTC)</td><td><code>{_t(today_start)}</code></td></tr>
            <tr><td>Rolling 24h cutoff</td><td><code>{_t(rolling_24h)}</code></td></tr>
            <tr><td>Earliest gemini_usage record</td><td><code>{earliest_ts}</code></td></tr>
            <tr><td>Latest gemini_usage record</td><td><code>{latest_ts}</code></td></tr>
        </tbody>
    </table>
    <div class="stats-grid">
        {_stat_card(f'{total_all_time:,}', 'All-time API calls')}
        {_stat_card(f'{total_today:,}', 'Calls since midnight')}
        {_stat_card(f'{total_today_ok:,}', 'Successful (today)')}
        {_stat_card(f'{total_today_fail:,}', 'Failed (today)')}
        {_stat_card(f'{total_rolling:,}', 'Rolling 24h calls')}
    </div>
    <div class="stats-grid">
        {_stat_card(f'{inv_reports_all:,}', 'Investigation reports (all)')}
        {_stat_card(f'{inv_reports_today:,}', 'Reports since midnight')}
        {_stat_card(f'{inv_reports_24h:,}', 'Reports in rolling 24h')}
    </div>
    """

    # ── 2. Calls by purpose (today) ──
    purpose_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}}},
        {"$group": {
            "_id": {"purpose": "$purpose", "success": "$success"},
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "first": {"$min": "$timestamp"},
            "last": {"$max": "$timestamp"},
        }},
        {"$sort": {"_id.purpose": 1, "_id.success": -1}}
    ]
    purpose_rows = await db.gemini_usage.aggregate(purpose_pipeline).to_list(100)

    purpose_tbody = ""
    for r in purpose_rows:
        s_label = "Yes" if r["_id"]["success"] else "No"
        s_cls = "color:var(--green);" if r["_id"]["success"] else "color:var(--red);"
        purpose_tbody += f"""<tr>
            <td>{html_mod.escape(str(r['_id']['purpose'] or 'N/A'))}</td>
            <td style="{s_cls}">{s_label}</td>
            <td style="text-align:right;">{r['calls']:,}</td>
            <td style="text-align:right;">{r['input_tokens']:,}</td>
            <td style="text-align:right;">{r['output_tokens']:,}</td>
            <td style="text-align:right;">{r['thinking_tokens']:,}</td>
            <td style="text-align:right;">{r['cached_tokens']:,}</td>
            <td style="text-align:right;">${r['cost']:.4f}</td>
            <td>{_t(r['first'])}</td>
            <td>{_t(r['last'])}</td>
        </tr>"""

    purpose_html = f"""
    <h2>2. Calls by Purpose (Today, since midnight UTC)</h2>
    <table>
        <thead><tr><th>Purpose</th><th>Success</th><th>Calls</th><th>Input Tokens</th>
        <th>Output</th><th>Thinking</th><th>Cached</th><th>Est Cost</th>
        <th>First Call</th><th>Last Call</th></tr></thead>
        <tbody>{purpose_tbody or '<tr><td colspan="10" style="color:var(--muted);">No records found for today</td></tr>'}</tbody>
    </table>
    """

    # ── 3. Investigation calls grouped by correlation_id ──
    inv_corr_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}, "purpose": "investigation"}},
        {"$group": {
            "_id": "$correlation_id",
            "calls": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$success", 1, 0]}},
            "fail": {"$sum": {"$cond": ["$success", 0, 1]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "first_call": {"$min": "$timestamp"},
            "last_call": {"$max": "$timestamp"},
            "models": {"$addToSet": "$model"},
            "call_types": {"$addToSet": "$call_type"},
        }},
        {"$sort": {"cost": -1}}
    ]
    inv_groups = await db.gemini_usage.aggregate(inv_corr_pipeline).to_list(500)

    unique_corr = len(inv_groups)
    total_inv_calls = sum(g["calls"] for g in inv_groups)
    total_inv_input = sum(g["input_tokens"] for g in inv_groups)
    total_inv_cost = sum(g["cost"] for g in inv_groups)
    avg_input_per_call = total_inv_input / total_inv_calls if total_inv_calls > 0 else 0

    # Cross-reference with investigation_reports
    corr_ids = [g["_id"] for g in inv_groups if g["_id"]]
    report_map: dict[str, dict] = {}
    if corr_ids:
        for field in ["case_id", "correlation_id", "_id"]:
            try:
                found = await db.investigation_reports.find(
                    {field: {"$in": corr_ids}},
                    {"_id": 1, "case_id": 1, "correlation_id": 1, "status": 1,
                     "created_at": 1, "category": 1, "subject": 1}
                ).to_list(500)
                for f in found:
                    key = str(f.get(field, f.get("_id")))
                    if key not in report_map:
                        report_map[key] = f
            except Exception:
                pass

    # Also check any cases-like collections
    all_colls = await db.list_collection_names()
    case_colls = [c for c in all_colls if any(k in c.lower() for k in ["case", "invest", "magnum"])]

    extra_matches: dict[str, dict] = {}
    for coll_name in case_colls:
        if coll_name in ("gemini_usage", "investigation_reports"):
            continue
        for field in ["case_id", "correlation_id"]:
            try:
                found = await db[coll_name].find(
                    {field: {"$in": corr_ids[:100]}},
                    {"_id": 1, "case_id": 1, "correlation_id": 1, "status": 1,
                     "created_at": 1, "type": 1, "source": 1}
                ).to_list(200)
                for f in found:
                    key = str(f.get(field, f.get("_id")))
                    extra_matches[key] = {"collection": coll_name, **{k: v for k, v in f.items() if k != "_id"}}
            except Exception:
                pass

    # ── Source/trigger classification by correlation_id pattern ──
    def _classify_corr(cid: str) -> str:
        """Determine what code path created this correlation_id."""
        if not cid or cid == "NULL":
            return "unknown (no correlation_id)"
        if cid.startswith("case-"):
            return "coordinator (Magnum DI job)"
        if cid.startswith("msg-check-"):
            return "message check (investigation.py)"
        if cid.startswith("phone-check-"):
            return "phone check (investigation.py)"
        if cid == "health-check":
            return "health check probe"
        if cid == "research":
            return "research/grounding"
        if cid.startswith("chat-"):
            return "chat"
        if cid == "scam-analysis":
            return "scam analysis"
        return f"other ({cid[:20]})"

    source_buckets: dict[str, dict] = {}
    for g in inv_groups:
        cid = str(g["_id"] or "NULL")
        cat = _classify_corr(cid)
        b = source_buckets.setdefault(cat, {"calls": 0, "input": 0, "output": 0, "thinking": 0, "cost": 0.0, "unique_ids": 0})
        b["calls"] += g["calls"]
        b["input"] += g["input_tokens"]
        b["output"] += g["output_tokens"]
        b["thinking"] += g["thinking_tokens"]
        b["cost"] += g["cost"]
        b["unique_ids"] += 1

    source_tbody = ""
    for cat in sorted(source_buckets.keys(), key=lambda k: source_buckets[k]["cost"], reverse=True):
        b = source_buckets[cat]
        avg = b["input"] / b["calls"] if b["calls"] > 0 else 0
        source_tbody += f"""<tr>
            <td>{html_mod.escape(cat)}</td>
            <td style="text-align:right;">{b['unique_ids']:,}</td>
            <td style="text-align:right;">{b['calls']:,}</td>
            <td style="text-align:right;">{b['input']:,}</td>
            <td style="text-align:right;">{b['output']:,}</td>
            <td style="text-align:right;">{b['thinking']:,}</td>
            <td style="text-align:right;">${b['cost']:.4f}</td>
            <td style="text-align:right;">{avg:,.0f}</td>
        </tr>"""

    source_html = f"""
    <h2>2b. Investigation Calls by Source/Trigger</h2>
    <div class="alert alert-warning">
        <strong>Key question:</strong> How many of the investigation-labelled calls were user-initiated vs automated?<br/>
        Correlation IDs starting with <code>case-*</code> come from the Magnum DI coordinator (could be user OR mailbox-monitor triggered).<br/>
        <code>msg-check-*</code> = message analysis API, <code>phone-check-*</code> = phone analysis API,
        <code>health-check</code> = system health probe.<br/>
        <strong>The mailbox monitor creates <code>case-*</code> jobs automatically every 15 minutes for each monitored email.</strong>
    </div>
    <table>
        <thead><tr><th>Source Category</th><th>Unique IDs</th><th>Calls</th><th>Input Tokens</th>
        <th>Output</th><th>Thinking</th><th>Est Cost</th><th>Avg Input/Call</th></tr></thead>
        <tbody>{source_tbody or '<tr><td colspan="8" style="color:var(--muted);">No data</td></tr>'}</tbody>
    </table>
    """

    # ── Check mailbox-related investigation jobs ──
    mailbox_receipts = await db.mailbox_assessment_receipts.count_documents({"state": {"$in": ["submitted", "complete"]}, "updated_at": {"$gte": today_start}})
    mailbox_jobs_today = 0
    try:
        mailbox_jobs_today = await db.investigation_jobs.count_documents({
            "created_at": {"$gte": today_start},
            "idempotency_key": {"$regex": "^mailbox:"}
        })
    except Exception:
        pass

    mailbox_html = f"""
    <h2>2c. Mailbox Monitor Activity (Today)</h2>
    <div class="stats-grid">
        {_stat_card(str(mailbox_receipts), 'Assessment receipts (today)')}
        {_stat_card(str(mailbox_jobs_today), 'Jobs with mailbox: key (today)')}
    </div>
    <p style="font-size:0.88em;color:var(--muted);">
        The mailbox monitor scans Gmail every 15 min and creates investigation jobs for each email.
        Each job generates up to 12 Gemini calls (10 tool rounds + forced conclusion + validation repair).
        If {mailbox_receipts} emails were assessed today, they could account for up to {mailbox_receipts * 12:,} investigation calls.
    </p>
    """

    # Build reconciliation table rows
    recon_tbody = ""
    running_calls = 0
    running_input = 0
    running_output = 0
    running_thinking = 0
    running_cached = 0
    running_cost = 0.0

    for idx, g in enumerate(inv_groups):
        corr_id = str(g["_id"] or "NULL")
        short_corr = corr_id[:32] + "..." if len(corr_id) > 35 else corr_id
        models = ", ".join(g["models"][:2])
        types = ", ".join(g["call_types"][:3])

        # Determine source/trigger
        cat = _classify_corr(corr_id)
        source = cat
        rpt = report_map.get(corr_id)
        ext = extra_matches.get(corr_id)
        if rpt:
            source = f"{cat} → report ({rpt.get('status', '?')})"
        elif ext:
            source = f"{cat} → {ext.get('collection', '?')} ({ext.get('status', ext.get('type', '?'))})"

        running_calls += g["calls"]
        running_input += g["input_tokens"]
        running_output += g["output_tokens"]
        running_thinking += g["thinking_tokens"]
        running_cached += g["cached_tokens"]
        running_cost += g["cost"]

        recon_tbody += f"""<tr>
            <td>{idx + 1}</td>
            <td title="{html_mod.escape(corr_id)}" style="font-size:0.78em;word-break:break-all;max-width:180px;"><code>{html_mod.escape(short_corr)}</code></td>
            <td style="text-align:right;">{g['calls']:,}</td>
            <td style="text-align:right;">{g['ok']:,}</td>
            <td style="text-align:right;">{g['fail']:,}</td>
            <td style="text-align:right;">{g['input_tokens']:,}</td>
            <td style="text-align:right;">{g['output_tokens']:,}</td>
            <td style="text-align:right;">{g['thinking_tokens']:,}</td>
            <td style="text-align:right;">{g['cached_tokens']:,}</td>
            <td style="text-align:right;">${g['cost']:.4f}</td>
            <td style="font-size:0.82em;">{_t(g['first_call'])}</td>
            <td style="font-size:0.82em;">{_t(g['last_call'])}</td>
            <td style="font-size:0.82em;">{html_mod.escape(models)}</td>
            <td style="font-size:0.82em;">{html_mod.escape(source)}</td>
        </tr>"""

    # Totals row
    recon_tbody += f"""<tr style="font-weight:700;background:var(--card);">
        <td colspan="2" style="text-align:right;">TOTALS ({unique_corr} unique IDs)</td>
        <td style="text-align:right;">{running_calls:,}</td>
        <td></td><td></td>
        <td style="text-align:right;">{running_input:,}</td>
        <td style="text-align:right;">{running_output:,}</td>
        <td style="text-align:right;">{running_thinking:,}</td>
        <td style="text-align:right;">{running_cached:,}</td>
        <td style="text-align:right;">${running_cost:.4f}</td>
        <td colspan="4"></td>
    </tr>"""

    recon_html = f"""
    <h2>3. Investigation Calls — Reconciliation Table</h2>
    <div class="stats-grid">
        {_stat_card(f'{unique_corr:,}', 'Unique correlation IDs')}
        {_stat_card(f'{total_inv_calls:,}', 'Total investigation calls')}
        {_stat_card(f'{total_inv_input:,}', 'Total input tokens')}
        {_stat_card(f'${total_inv_cost:.4f}', 'Total est cost')}
        {_stat_card(f'{avg_input_per_call:,.0f}', 'Avg input tokens/call')}
        {_stat_card(f'{len(report_map):,}', 'Matched in inv_reports')}
    </div>
    <div style="overflow-x:auto;">
    <table style="font-size:0.82em;">
        <thead><tr><th>#</th><th>Correlation ID</th><th>Calls</th><th>OK</th><th>Fail</th>
        <th>Input</th><th>Output</th><th>Thinking</th><th>Cached</th><th>Est Cost</th>
        <th>First Call</th><th>Last Call</th><th>Model(s)</th><th>Source / Trigger</th></tr></thead>
        <tbody>{recon_tbody}</tbody>
    </table>
    </div>
    """

    # ── 4. Top consumers ──
    top_html = ""
    if inv_groups:
        top_html = "<h2>4. Top 10 Highest-Consuming Correlation IDs</h2>"
        for idx, g in enumerate(inv_groups[:10]):
            corr_id = str(g["_id"] or "NULL")
            avg = g["input_tokens"] / g["calls"] if g["calls"] > 0 else 0
            pct = (g["input_tokens"] / total_inv_input * 100) if total_inv_input > 0 else 0
            top_html += f"""<div class="s-card" style="margin-bottom:8px;">
                <div class="s-card-head"><strong>#{idx+1}</strong> &nbsp; <code style="font-size:0.82em;word-break:break-all;">{html_mod.escape(corr_id)}</code></div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;margin-top:8px;">
                    <div><span style="color:var(--muted);font-size:0.78em;">Calls</span><br/><strong>{g['calls']:,}</strong></div>
                    <div><span style="color:var(--muted);font-size:0.78em;">Input tokens</span><br/><strong>{g['input_tokens']:,}</strong></div>
                    <div><span style="color:var(--muted);font-size:0.78em;">Avg input/call</span><br/><strong>{avg:,.0f}</strong></div>
                    <div><span style="color:var(--muted);font-size:0.78em;">Est cost</span><br/><strong>${g['cost']:.4f}</strong></div>
                    <div><span style="color:var(--muted);font-size:0.78em;">% of total input</span><br/><strong>{pct:.1f}%</strong></div>
                    <div><span style="color:var(--muted);font-size:0.78em;">Model(s)</span><br/><strong style="font-size:0.88em;">{html_mod.escape(', '.join(g['models']))}</strong></div>
                </div>
                <div style="font-size:0.8em;color:var(--muted);margin-top:6px;">
                    First: {_t(g['first_call'])} &mdash; Last: {_t(g['last_call'])}
                </div>
            </div>"""

    # ── 5. Failure analysis ──
    fail_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}, "success": False}},
        {"$group": {
            "_id": {"purpose": "$purpose", "failure_code": "$failure_code"},
            "count": {"$sum": 1},
            "first": {"$min": "$timestamp"},
            "last": {"$max": "$timestamp"},
        }},
        {"$sort": {"count": -1}}
    ]
    failures = await db.gemini_usage.aggregate(fail_pipeline).to_list(50)

    fail_tbody = ""
    for f in failures:
        fail_tbody += f"""<tr>
            <td>{html_mod.escape(str(f['_id']['purpose'] or 'N/A'))}</td>
            <td><code>{html_mod.escape(str(f['_id']['failure_code'] or 'N/A'))}</code></td>
            <td style="text-align:right;">{f['count']:,}</td>
            <td>{_t(f['first'])}</td>
            <td>{_t(f['last'])}</td>
        </tr>"""

    fail_html = f"""
    <h2>5. Failure Analysis (Today)</h2>
    <table>
        <thead><tr><th>Purpose</th><th>Failure Code</th><th>Count</th><th>First</th><th>Last</th></tr></thead>
        <tbody>{fail_tbody or '<tr><td colspan="5" style="color:var(--muted);">No failures recorded today</td></tr>'}</tbody>
    </table>
    """

    # ── 6. Compaction status ──
    compaction_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}, "purpose": "investigation"}},
        {"$group": {
            "_id": None,
            "with_flag": {"$sum": {"$cond": [{"$gt": ["$extra.compaction_active", None]}, 1, 0]}},
            "flag_true": {"$sum": {"$cond": [{"$eq": ["$extra.compaction_active", True]}, 1, 0]}},
            "flag_false": {"$sum": {"$cond": [{"$eq": ["$extra.compaction_active", False]}, 1, 0]}},
            "with_audit": {"$sum": {"$cond": [{"$gt": ["$extra.payload_audit", None]}, 1, 0]}},
        }}
    ]
    comp_data = (await db.gemini_usage.aggregate(compaction_pipeline).to_list(1)) or [{}]
    cd = comp_data[0] if comp_data else {}

    compaction_html = f"""
    <h2>6. Compaction & Payload Audit Status</h2>
    <div class="stats-grid">
        {_stat_card(str(cd.get('with_flag', 0)), 'With compaction flag')}
        {_stat_card(str(cd.get('flag_true', 0)), 'compaction_active=true')}
        {_stat_card(str(cd.get('flag_false', 0)), 'compaction_active=false')}
        {_stat_card(str(total_inv_calls - cd.get('with_flag', 0)), 'No compaction flag (legacy)')}
        {_stat_card(str(cd.get('with_audit', 0)), 'With payload audit data')}
    </div>
    """

    # ── 6b. Cost gap analysis ──
    # Count research calls for grounding cost estimation
    research_count_today = await db.gemini_usage.count_documents({
        "timestamp": {"$gte": today_start}, "purpose": "research", "success": True
    })
    grounding_est = research_count_today * 0.035  # $35/1k queries = $0.035/query
    total_estimated = total_inv_cost + sum(r["cost"] for r in purpose_rows if r["_id"]["success"])

    # Aggregate output+thinking tokens across ALL today's successful calls
    output_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}, "success": True}},
        {"$group": {
            "_id": None,
            "total_output": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "total_thinking": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "total_cached": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
        }}
    ]
    output_data = (await db.gemini_usage.aggregate(output_pipeline).to_list(1)) or [{}]
    od = output_data[0] if output_data else {}

    cost_gap_html = f"""
    <h2>6b. Cost Gap Analysis (Estimated vs Actual)</h2>
    <div class="alert alert-warning">
        <strong>Why ApolloSG's estimate may be lower than actual Google billing:</strong>
    </div>
    <table>
        <thead><tr><th>Component</th><th>Value</th><th>Estimated Impact</th></tr></thead>
        <tbody>
            <tr>
                <td>ApolloSG estimated cost (all purposes, success-only)</td>
                <td colspan="2" style="text-align:right;font-weight:700;">${total_estimated:.4f}</td>
            </tr>
            <tr>
                <td>Google Search grounding ({research_count_today} research calls &times; ~$0.035/query)</td>
                <td style="text-align:right;">{research_count_today} calls</td>
                <td style="text-align:right;color:var(--red);">+${grounding_est:.2f}</td>
            </tr>
            <tr>
                <td>Output tokens today</td>
                <td style="text-align:right;">{od.get('total_output', 0):,}</td>
                <td style="color:var(--muted);">Included in estimate</td>
            </tr>
            <tr>
                <td>Thinking tokens today</td>
                <td style="text-align:right;">{od.get('total_thinking', 0):,}</td>
                <td style="color:var(--muted);">Included in estimate</td>
            </tr>
            <tr>
                <td>Cached input tokens today</td>
                <td style="text-align:right;">{od.get('total_cached', 0):,}</td>
                <td style="color:var(--muted);">Discounted in estimate</td>
            </tr>
            <tr>
                <td>Pricing table drift (hardcoded rates may not match current Google pricing)</td>
                <td></td>
                <td style="text-align:right;color:var(--red);">+$1&ndash;3 (variable)</td>
            </tr>
            <tr style="font-weight:700;background:var(--card);">
                <td>Adjusted estimate</td>
                <td></td>
                <td style="text-align:right;">${total_estimated + grounding_est:.2f} + pricing drift</td>
            </tr>
        </tbody>
    </table>
    <p style="font-size:0.85em;color:var(--muted);margin-top:8px;">
        <strong>count_tokens() API calls:</strong> ApolloSG calls <code>count_tokens()</code> before every
        <code>generate_content()</code> for admission control. These calls are <strong>free</strong>
        (not billed by Google) but do add to API call volume.<br/>
        <strong>Failed calls (402):</strong> HTTP 402 billing failures do not consume tokens or incur charges.
    </p>
    """


    # ── 7. Historical comparison ──
    week_ago = now - timedelta(days=7)
    daily_pipeline = [
        {"$match": {"timestamp": {"$gte": week_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "calls": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$success", 1, 0]}},
            "fail": {"$sum": {"$cond": ["$success", 0, 1]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
        }},
        {"$sort": {"_id": 1}}
    ]
    daily = await db.gemini_usage.aggregate(daily_pipeline).to_list(10)

    daily_tbody = ""
    for d in daily:
        daily_tbody += f"""<tr>
            <td>{d['_id']}</td>
            <td style="text-align:right;">{d['calls']:,}</td>
            <td style="text-align:right;">{d['ok']:,}</td>
            <td style="text-align:right;">{d['fail']:,}</td>
            <td style="text-align:right;">{d['input_tokens']:,}</td>
            <td style="text-align:right;">${d['cost']:.4f}</td>
        </tr>"""

    history_html = f"""
    <h2>7. Historical Comparison (Last 7 Days)</h2>
    <table>
        <thead><tr><th>Date</th><th>Total Calls</th><th>Successful</th><th>Failed</th><th>Input Tokens</th><th>Est Cost</th></tr></thead>
        <tbody>{daily_tbody or '<tr><td colspan="6" style="color:var(--muted);">No historical data</td></tr>'}</tbody>
    </table>
    """

    # ── 8. investigation_reports inspection ──
    latest_reports = await db.investigation_reports.find(
        {}, {"_id": 1, "case_id": 1, "correlation_id": 1, "status": 1, "created_at": 1}
    ).sort("created_at", -1).limit(20).to_list(20)

    reports_tbody = ""
    for r in latest_reports:
        reports_tbody += f"""<tr>
            <td style="font-size:0.82em;"><code>{html_mod.escape(str(r.get('_id', '')))}</code></td>
            <td style="font-size:0.82em;"><code>{html_mod.escape(str(r.get('case_id', r.get('correlation_id', ''))))}</code></td>
            <td>{html_mod.escape(str(r.get('status', '')))}</td>
            <td>{_t(r.get('created_at'))}</td>
        </tr>"""

    schema_sample = await db.investigation_reports.find_one({})
    schema_keys = list(schema_sample.keys()) if schema_sample else []

    reports_html = f"""
    <h2>8. investigation_reports Collection Inspection</h2>
    <p style="color:var(--muted);font-size:0.88em;">Schema fields: <code>{html_mod.escape(', '.join(schema_keys) if schema_keys else 'empty collection')}</code></p>
    <table>
        <thead><tr><th>_id</th><th>Case / Correlation ID</th><th>Status</th><th>Created At</th></tr></thead>
        <tbody>{reports_tbody or '<tr><td colspan="4" style="color:var(--muted);">No investigation reports found</td></tr>'}</tbody>
    </table>
    """

    # ── 9. Dashboard reconciliation check ──
    success_by_purpose = [
        {"$match": {"timestamp": {"$gte": today_start}, "success": True}},
        {"$group": {"_id": "$purpose",
                    "calls": {"$sum": 1},
                    "input": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}}}},
        {"$sort": {"cost": -1}}
    ]
    by_purp = await db.gemini_usage.aggregate(success_by_purpose).to_list(20)
    total_ok_calls = sum(r["calls"] for r in by_purp)
    total_ok_input = sum(r["input"] for r in by_purp)
    total_ok_cost = sum(r["cost"] for r in by_purp)

    recon_check_tbody = ""
    for r in by_purp:
        recon_check_tbody += f"""<tr>
            <td>{html_mod.escape(str(r['_id'] or 'other'))}</td>
            <td style="text-align:right;">{r['calls']:,}</td>
            <td style="text-align:right;">{r['input']:,}</td>
            <td style="text-align:right;">${r['cost']:.4f}</td>
        </tr>"""
    recon_check_tbody += f"""<tr style="font-weight:700;background:var(--card);">
        <td>TOTAL (success-only, matches dashboard query)</td>
        <td style="text-align:right;">{total_ok_calls:,}</td>
        <td style="text-align:right;">{total_ok_input:,}</td>
        <td style="text-align:right;">${total_ok_cost:.4f}</td>
    </tr>"""

    recon_check_html = f"""
    <h2>9. Dashboard Reconciliation Check</h2>
    <p style="color:var(--muted);font-size:0.88em;">
        Dashboard "Cost Today" filter: <code>gemini_usage.timestamp &ge; {_t(today_start)}</code> (midnight UTC),
        <code>success = true</code>
    </p>
    <table>
        <thead><tr><th>Purpose</th><th>Calls</th><th>Input Tokens</th><th>Est Cost</th></tr></thead>
        <tbody>{recon_check_tbody}</tbody>
    </table>
    <p style="margin-top:12px;font-size:0.88em;">
        Compare these DB-queried totals against the dashboard snapshot values.
        Minor differences are expected if new calls were recorded between the snapshot and this report.
    </p>
    """

    # ── Related collections inventory ──
    related_html = f"""
    <h2>10. Related Collections</h2>
    <p style="color:var(--muted);font-size:0.88em;">Collections matching case/investigation/magnum patterns:</p>
    <ul style="font-size:0.88em;padding-left:20px;">
    """
    for cn in sorted(case_colls):
        try:
            cnt = await db[cn].count_documents({})
            related_html += f"<li><code>{html_mod.escape(cn)}</code> &mdash; {cnt:,} documents</li>"
        except Exception:
            related_html += f"<li><code>{html_mod.escape(cn)}</code> &mdash; error</li>"
    if not case_colls:
        related_html += "<li style='color:var(--muted);'>No case/investigation-related collections found</li>"
    related_html += "</ul>"

    body = f"""
    <div class="topbar-row">
        <span style="font-size:0.88em;color:var(--muted);">Generated {_t(now)}</span>
        <a href="/api/admin/reconciliation/pdf" class="btn btn-sm">Download PDF</a>
    </div>
    {boundary_html}
    {purpose_html}
    {source_html}
    {mailbox_html}
    {recon_html}
    {top_html}
    {fail_html}
    {compaction_html}
    {cost_gap_html}
    {history_html}
    {reports_html}
    {recon_check_html}
    {related_html}
    """
    extra_css = "table { table-layout: auto; } td, th { white-space: nowrap; } td code { word-break: break-all; white-space: normal; }"
    await _audit_log(adm.get("email", ""), "view_reconciliation", f"investigation calls={total_inv_calls}")
    return _shell("Reconciliation", "/api/admin/reconciliation", body, admin=adm, extra_css=extra_css)


@router.get("/admin/reconciliation/pdf")
async def reconciliation_pdf(request: Request):
    """Download the reconciliation report as PDF."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    now = now_utc()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tz = _tz_param(request)

    # Gather same data as the HTML page
    total_today_ok = await db.gemini_usage.count_documents({"timestamp": {"$gte": today_start}, "success": True})
    total_today_fail = await db.gemini_usage.count_documents({"timestamp": {"$gte": today_start}, "success": False})
    inv_reports_24h = await db.investigation_reports.count_documents({"created_at": {"$gte": now - timedelta(hours=24)}})

    # Purpose breakdown
    purpose_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}}},
        {"$group": {
            "_id": {"purpose": "$purpose", "success": "$success"},
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
        }},
        {"$sort": {"_id.purpose": 1}}
    ]
    purpose_rows = await db.gemini_usage.aggregate(purpose_pipeline).to_list(100)

    purpose_tbody = ""
    for r in purpose_rows:
        s = "Yes" if r["_id"]["success"] else "No"
        purpose_tbody += f"<tr><td>{r['_id']['purpose'] or 'N/A'}</td><td>{s}</td><td>{r['calls']:,}</td><td>{r['input_tokens']:,}</td><td>${r['cost']:.4f}</td></tr>"

    # Investigation correlation groups
    inv_corr_pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}, "purpose": "investigation"}},
        {"$group": {
            "_id": "$correlation_id",
            "calls": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$success", 1, 0]}},
            "fail": {"$sum": {"$cond": ["$success", 0, 1]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "first_call": {"$min": "$timestamp"},
            "last_call": {"$max": "$timestamp"},
            "models": {"$addToSet": "$model"},
        }},
        {"$sort": {"cost": -1}}
    ]
    inv_groups = await db.gemini_usage.aggregate(inv_corr_pipeline).to_list(500)

    recon_tbody = ""
    r_calls = r_input = r_output = r_thinking = r_cached = 0
    r_cost = 0.0
    for idx, g in enumerate(inv_groups):
        corr_id = str(g["_id"] or "NULL")[:30]
        models = ", ".join(g["models"][:2])
        r_calls += g["calls"]
        r_input += g["input_tokens"]
        r_output += g["output_tokens"]
        r_thinking += g["thinking_tokens"]
        r_cached += g["cached_tokens"]
        r_cost += g["cost"]
        recon_tbody += (f"<tr><td>{idx+1}</td><td style='font-size:8px;'>{corr_id}</td>"
                        f"<td>{g['calls']}</td><td>{g['ok']}</td><td>{g['fail']}</td>"
                        f"<td>{g['input_tokens']:,}</td><td>{g['output_tokens']:,}</td>"
                        f"<td>{g['thinking_tokens']:,}</td><td>{g['cached_tokens']:,}</td>"
                        f"<td>${g['cost']:.4f}</td>"
                        f"<td style='font-size:8px;'>{local_time.label(g['first_call'], tz)}</td>"
                        f"<td style='font-size:8px;'>{local_time.label(g['last_call'], tz)}</td>"
                        f"<td style='font-size:8px;'>{models}</td></tr>")

    recon_tbody += (f"<tr style='font-weight:bold;'><td colspan='2'>TOTALS ({len(inv_groups)} IDs)</td>"
                    f"<td>{r_calls:,}</td><td></td><td></td>"
                    f"<td>{r_input:,}</td><td>{r_output:,}</td>"
                    f"<td>{r_thinking:,}</td><td>{r_cached:,}</td>"
                    f"<td>${r_cost:.4f}</td><td colspan='3'></td></tr>")

    pdf_body = f"""
    <h2>Timestamp Boundaries</h2>
    <p>Report: {local_time.label(now, tz)}<br/>
    "Today" boundary: {local_time.label(today_start, tz)} (midnight UTC)<br/>
    gemini_usage today: {total_today_ok + total_today_fail:,} ({total_today_ok:,} ok, {total_today_fail:,} fail)<br/>
    investigation_reports (24h): {inv_reports_24h:,}</p>

    <h2>Calls by Purpose (Today)</h2>
    <table><thead><tr><th>Purpose</th><th>Success</th><th>Calls</th><th>Input Tokens</th><th>Est Cost</th></tr></thead>
    <tbody>{purpose_tbody or '<tr><td colspan="5">No data</td></tr>'}</tbody></table>

    <h2>Investigation Reconciliation Table</h2>
    <table style="font-size:8px;"><thead><tr>
    <th>#</th><th>Correlation ID</th><th>Calls</th><th>OK</th><th>Fail</th>
    <th>Input</th><th>Output</th><th>Thinking</th><th>Cached</th><th>Cost</th>
    <th>First</th><th>Last</th><th>Model</th></tr></thead>
    <tbody>{recon_tbody}</tbody></table>
    """

    full_html = _pdf_html("Usage Reconciliation Report", pdf_body, tz)

    from xhtml2pdf import pisa
    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(full_html), dest=pdf_buffer)
    pdf_buffer.seek(0)

    await _audit_log(adm.get("email", ""), "download_reconciliation_pdf", "")
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="apollo_reconciliation_{now.astimezone(timezone(timedelta(minutes=tz))).strftime("%Y%m%d_%I%M%p")}.pdf"'},
    )



@router.post("/admin/backfill-gates", response_class=HTMLResponse)
async def backfill_gates(request: Request):
    """One-time safe backfill: reclassify investigation_cases with empty gates[]
    using authoritative structured metadata from evidence items.
    
    Only reclassifies when the gate can be RELIABLY determined from:
    - mailbox_assessment_receipts (→ email)
    - evidence items with origin/label indicators
    - evidence URLs vs text content
    Does NOT use Gemini or guess from investigation text.
    """
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    import re as _re

    # Find all cases with empty gates
    empty_gate_cases = await db.investigation_cases.find(
        {"$or": [{"gates": {"$exists": False}}, {"gates": []}, {"gates": None}]},
        {"_id": 0, "case_id": 1, "owner_id": 1, "created_at": 1}
    ).to_list(1000)

    results = {"total": len(empty_gate_cases), "email": 0, "link": 0, "text": 0,
               "call": 0, "vision": 0, "unchanged": 0, "errors": 0}
    details = []

    for case in empty_gate_cases:
        cid = case["case_id"]
        oid = case["owner_id"]
        inferred_gate = None
        reason = ""

        try:
            # Check 1: Was this created by the mailbox monitor?
            receipt = await db.mailbox_assessment_receipts.find_one(
                {"case_id": cid}, {"_id": 0, "state": 1})
            if receipt:
                inferred_gate = "email"
                reason = "mailbox_assessment_receipt found"
            else:
                # Check 2: Look at evidence items for this case
                evidence = await db.investigation_evidence.find(
                    {"owner_id": oid, "case_id": cid},
                    {"_id": 0, "kind": 1, "origin": 1, "label": 1, "content_ciphertext": 1}
                ).to_list(20)

                has_url = any(e.get("kind") == "url" for e in evidence)
                has_email_label = any("email" in (e.get("label") or "").lower() or
                                      "mailbox" in (e.get("label") or "").lower() or
                                      "email" in (e.get("origin") or "").lower()
                                      for e in evidence)
                has_vision = any("vision" in (e.get("origin") or "").lower() or
                                 "screenshot" in (e.get("label") or "").lower() or
                                 "image" in (e.get("label") or "").lower()
                                 for e in evidence)

                if has_email_label:
                    inferred_gate = "email"
                    reason = "evidence label/origin contains email/mailbox"
                elif has_vision:
                    inferred_gate = "vision"
                    reason = "evidence origin/label indicates vision"
                elif has_url:
                    inferred_gate = "link"
                    reason = "evidence contains URL items"
                elif evidence:
                    inferred_gate = "text"
                    reason = "text-only evidence (default)"

            if inferred_gate:
                await db.investigation_cases.update_one(
                    {"case_id": cid, "owner_id": oid},
                    {"$set": {"gates": [inferred_gate]}}
                )
                results[inferred_gate] = results.get(inferred_gate, 0) + 1
                details.append(f"  {cid[:12]}… → {inferred_gate} ({reason})")
            else:
                results["unchanged"] += 1
                details.append(f"  {cid[:12]}… → unchanged (no reliable metadata)")

        except Exception as e:
            results["errors"] += 1
            details.append(f"  {cid[:12]}… → error: {type(e).__name__}")

    detail_html = "<br/>".join(html_mod.escape(d) for d in details[:50])
    if len(details) > 50:
        detail_html += f"<br/>... and {len(details) - 50} more"

    body = f"""
    <h2>Gate Backfill Results</h2>
    <div class="stats-grid">
        {_stat_card(str(results['total']), 'Total unattributed cases')}
        {_stat_card(str(results['email']), 'Reclassified → Email')}
        {_stat_card(str(results['link']), 'Reclassified → Link')}
        {_stat_card(str(results['text']), 'Reclassified → Text')}
        {_stat_card(str(results['call']), 'Reclassified → Call')}
        {_stat_card(str(results['vision']), 'Reclassified → Vision')}
        {_stat_card(str(results['unchanged']), 'Genuinely unattributed')}
        {_stat_card(str(results['errors']), 'Errors')}
    </div>
    <h3>Details</h3>
    <pre style="font-size:0.82em;color:var(--fg);background:var(--card);padding:16px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;">{detail_html}</pre>
    <a href="/api/admin/protection" class="btn" style="margin-top:12px;">&larr; Back to Protection</a>
    """
    await _audit_log(adm.get("email", ""), "backfill_gates", f"total={results['total']} reclassified={results['total'] - results['unchanged'] - results['errors']}")
    return _shell("Gate Backfill", "/api/admin/protection", body, admin=adm)





# ── Gemini Investigation Cost Report ─────────────────────────────────────────

from services.capability_registry import GATES as _GATES


def _to_local(dt: datetime | None) -> str:
    return _t(dt)


def _to_local_short(dt: datetime | None) -> str:
    return _t(dt, "short")


def _gate_display(gate_ids: list | None) -> str:
    """Map gate IDs to friendly admin display names."""
    if not gate_ids:
        return "None / System"
    names = []
    for gid in gate_ids:
        entry = _GATES.get(gid)
        if entry:
            names.append(entry[0])  # tuple: (title, owner, mode)
        else:
            names.append(gid)
    return ", ".join(names) if names else "None / System"


def _initiator_label(source: str | None) -> str:
    """Convert trigger source to user-friendly initiator label."""
    mapping = {
        "user_initiated": "User — Check",
        "mailbox_monitor": "ApolloSG — Mailbox Monitor",
        "recovery_resume": "ApolloSG — Recovery/Resume",
        "validation_test": "System — Test/Validation",
        "health_check": "System — Health Check",
        "chat": "User — Chat",
        "research": "ApolloSG — Research",
        "msg_check": "User — Message Check",
        "phone_check": "User — Phone Check",
        "scam_analysis": "ApolloSG — Automatic",
        "triage": "ApolloSG — Triage",
        "background_text": "ApolloSG — Background Text",
    }
    return mapping.get(source or "", source or "Unknown")


def _initiator_category(source: str | None) -> str:
    """Broad initiator category for summary grouping.
    
    Categories aligned with the 17 Oct Incident Analysis reporting format:
    - User — Check
    - Apollo — Mailbox Monitor
    - Apollo — Automatic
    - System — Test/Validation
    - Recovery/Resume
    - Unknown/Unattributed
    """
    if source in ("user_initiated", "chat", "msg_check", "phone_check"):
        return "User — Check"
    if source in ("mailbox_monitor",):
        return "ApolloSG — Mailbox Monitor"
    if source in ("recovery_resume",):
        return "Recovery/Resume"
    if source in ("scam_analysis", "research"):
        return "ApolloSG — Automatic"
    if source in ("validation_test", "health_check"):
        return "System — Test/Validation"
    if source is None or source == "" or source == "None":
        return "Unknown/Unattributed"
    return "Unknown/Unattributed"


def _device_name(profile: dict | None) -> str:
    """Extract a friendly device name from device profile, or 'No device'."""
    if not profile:
        return "No device"
    model = profile.get("model") or profile.get("deviceModel") or ""
    brand = profile.get("brand") or profile.get("manufacturer") or ""
    name = profile.get("deviceName") or profile.get("device_name") or ""
    if name:
        return name
    if brand and model:
        return f"{brand} {model}"
    if model:
        return model
    os_name = profile.get("os") or profile.get("platform") or ""
    if os_name:
        return os_name
    return "No device"


def _env_label(model_str: str | None) -> str:
    """Determine environment from model string."""
    if not model_str:
        return "Unknown"
    if model_str.startswith("mock:"):
        return "Mock"
    return "Production"


# How each investigation was answered (cost routing): TC FlyBy's route, or Magnum DI's Gemini call.
ANSWERED_BY_LABELS = {"tc_flyby_official": "Official check", "tc_flyby_kb": "ApolloSG KB", "tc_flyby_search": "Web search", "magnum_di": "Gemini"}
_ROUTE_LABELS = {"triage_rules": "Higgins Triage rules", "official_source": "Official source", "apollo_kb": "ApolloSG KB",
                 "google_search": "Web search (TC FlyBy)"}


def _answered_by(case: dict, magnum_calls: int) -> str:
    key = (case.get("routing") or {}).get("answeredBy")
    return key or ("magnum_di" if magnum_calls else "")


def _answered_by_badge(key: str) -> str:
    if not key:
        return '<span style="color:var(--muted);">&mdash;</span>'
    colour = "var(--yellow)" if key == "magnum_di" else "var(--green)"
    who = "Magnum DI" if key == "magnum_di" else "TC FlyBy"
    return (f'<span class="badge" data-testid="answered-by-{html_mod.escape(key)}" style="background:rgba(127,127,127,0.12);color:{colour};">'
            f'{html_mod.escape(ANSWERED_BY_LABELS.get(key, key))}</span> <span style="font-size:0.78em;color:var(--muted);">{who}</span>')


_OUTCOME_COLOURS = {"confirmed_threat": "var(--red)", "likely_scam": "var(--red)", "concerning": "var(--yellow)",
                    "unable_to_determine": "var(--muted)", "no_scam_indicators": "var(--green)"}


def _outcome_badge(key: str | None) -> str:
    """Apollo's case outcome — the same five outcomes whichever layer answered."""
    from services.higgins import outcomes
    if not key:
        return '<span style="color:var(--muted);">&mdash;</span>'
    return (f'<span class="badge" data-testid="outcome-{html_mod.escape(key)}" style="background:rgba(127,127,127,0.12);'
            f'color:{_OUTCOME_COLOURS.get(key, "var(--muted)")};">{html_mod.escape(outcomes.LABELS.get(key, key))}</span>')


def _routing_html(rows: list[dict], avg_cost: float) -> str:
    """Cost & performance measurement for Triage → TC FlyBy → Magnum DI over the period."""
    routed = [r for r in rows if (r["routing"] or {}).get("tc_flyby")]
    n = len(routed)
    resolved = sum(1 for r in routed if r["routing"]["tc_flyby"].get("resolved"))
    pct = lambda part, whole: f"{(100 * part / whole):.0f}%" if whole else "—"  # noqa: E731
    total = lambda key: sum(r.get(key, 0) for r in rows)  # noqa: E731
    cache_hits = sum(r["routing"]["tc_flyby"].get("cacheHits", 0) for r in routed)
    reused = sum(r["routing"]["tc_flyby"].get("reusedOnRetry", 0) for r in routed)
    magnum_search_off = sum(1 for r in routed if (r["routing"].get("magnum") or {}) and not r["routing"]["magnum"].get("search"))
    from services.higgins import outcomes as case_outcomes
    outcomes: dict[str, dict] = {}
    for r in rows:
        key = r["answered_by"] or "unknown"
        bucket = outcomes.setdefault(key, {"cases": 0, "cost": 0.0, "partial": 0, **{o: 0 for o in case_outcomes.OUTCOMES}})
        bucket["cases"] += 1
        bucket["cost"] += r["cost"]
        outcome = (r["routing"] or {}).get("outcome")
        if outcome in bucket:
            bucket[outcome] += 1
        if (r["routing"] or {}).get("completion") == "partial":
            bucket["partial"] += 1
    outcome_rows = "".join(
        f"<tr><td>{_answered_by_badge(key) if key != 'unknown' else 'Not recorded'}</td><td style='text-align:right;'>{b['cases']:,}</td>"
        + "".join(f"<td style='text-align:right;'>{b[o]:,}</td>" for o in case_outcomes.OUTCOMES)
        + f"<td style='text-align:right;'>{b['partial']:,}</td>"
        f"<td style='text-align:right;'>${(b['cost'] / b['cases'] if b['cases'] else 0):.4f}</td></tr>"
        for key, b in sorted(outcomes.items()))
    outcome_heads = "".join(f"<th>{html_mod.escape(case_outcomes.LABELS[o])}</th>" for o in case_outcomes.OUTCOMES)
    return f"""
    <h2 data-testid="cost-routing-heading">Cost Routing — Triage &rarr; TC FlyBy &rarr; Magnum DI</h2>
    <div class="stats-grid">
        {_stat_card(f'{n:,}', 'TC FlyBy Investigations')}
        {_stat_card(f'{resolved:,} ({pct(resolved, n)})', 'Resolved Without Magnum DI')}
        {_stat_card(pct(n - resolved, n), 'Magnum DI Invocation Rate')}
        {_stat_card(f"{total('flyby_queries'):,} / {total('magnum_queries'):,}", 'Search Queries (TC FlyBy / Magnum DI)')}
        {_stat_card(f"{total('flyby_in'):,} / {total('flyby_out'):,}", 'TC FlyBy AI Tokens (in / out)')}
        {_stat_card(f"{total('magnum_in'):,} / {total('magnum_out'):,}", 'Magnum Gemini Tokens (in / out)')}
        {_stat_card(f"{total('magnum_search_calls'):,} / {total('magnum_calls') - total('magnum_search_calls'):,}", 'Magnum Calls with Search On / Off')}
        {_stat_card(f'{cache_hits + reused + magnum_search_off:,}', 'Repeated Searches Avoided')}
        {_stat_card(f'${avg_cost:.4f}', 'Avg Cost per Investigation')}
    </div>
    <p style="font-size:0.82em;color:var(--muted);margin:4px 0 8px;">
        Repeated searches avoided = {cache_hits:,} TC FlyBy lookups served from its 7-day cache &middot; {reused:,} Magnum retries that reused
        TC FlyBy's record &middot; {magnum_search_off:,} Magnum calls sent with Google Search off because TC FlyBy had the facts.
        Search cost is estimated at the list price per query.
    </p>
    <table>
        <thead><tr><th>Answered By</th><th>Investigations</th>{outcome_heads}<th>Partial</th><th>Avg Cost</th></tr></thead>
        <tbody>{outcome_rows or '<tr><td colspan="9" style="color:var(--muted);">No investigations for this period</td></tr>'}</tbody>
    </table>
    """


def _settled_reason_html(routing: dict | None, *, short: bool = False) -> str:
    """Why this case was settled where it was: the settling rule from the rule book, linked to it."""
    from services import rulebook
    reason = rulebook.settled_reason(routing)
    if not reason:
        return '<span style="color:var(--muted);">Not recorded</span>'
    link = (f'<a href="/api/admin/rule-book#settling-rules" data-testid="settled-rule-{html_mod.escape(reason["ruleId"])}">'
            f'{html_mod.escape(reason["rule"])}</a>')
    if short:
        return link
    return (f'<span data-testid="settled-reason">{html_mod.escape(reason["sentence"])}</span>'
            f'<br><span style="font-size:0.82em;color:var(--muted);">Rule {html_mod.escape(reason["ruleId"])} &middot; {link} in the rule book</span>')


def _routing_drilldown_html(case: dict | None) -> str:
    routing = (case or {}).get("routing") or {}
    flyby = routing.get("tc_flyby")
    if not flyby:
        return ""
    magnum = routing.get("magnum") or {}
    checks = "".join(
        f"<tr><td>{html_mod.escape(c.get('kind', ''))}</td><td>{html_mod.escape(c.get('status', ''))}</td>"
        f"<td>{html_mod.escape(_ROUTE_LABELS.get(c.get('route') or '', {'needs_reasoning': 'Magnum DI', 'not_needed': 'Not needed'}.get(c.get('status'), '—')))}</td></tr>"
        for c in flyby.get("checks", []))
    issues = "<br>".join(f"{html_mod.escape(i.get('capability', ''))}: {html_mod.escape(i.get('text', '')[:200])}" for i in flyby.get("issues") or [])
    magnum_line = (f"Called &middot; Google Search {'on' if magnum.get('search') else 'off'} &middot; {magnum.get('itemsSent', 0)} evidence items sent "
                   f"&middot; {magnum.get('searchQueries', 0)} search queries" if magnum else "Not called")
    pattern = flyby.get("pattern") or {}
    pattern_line = (f"{html_mod.escape(pattern.get('key', ''))} &middot; {html_mod.escape(pattern.get('stage', ''))} match" if pattern else "No match")
    return f"""
    <h2>Cost Routing</h2>
    <table>
        <tbody>
            <tr><td style="color:var(--muted);width:180px;">Answered By</td><td>{_answered_by_badge(routing.get('answeredBy') or '')}</td></tr>
            <tr><td style="color:var(--muted);">Outcome</td><td>{_outcome_badge(routing.get('outcome'))}</td></tr>
            <tr><td style="color:var(--muted);">Why</td><td>{_settled_reason_html(routing)}</td></tr>
            <tr><td style="color:var(--muted);">Message Type</td><td>{html_mod.escape(flyby.get('messageType') or 'unknown')}</td></tr>
            <tr><td style="color:var(--muted);">ApolloSG KB Scam Pattern</td><td>{pattern_line}</td></tr>
            <tr><td style="color:var(--muted);">TC FlyBy Search</td><td>{flyby.get('searchCalls', 0)} call(s) &middot; {flyby.get('searchQueries', 0)} queries &middot; {flyby.get('cacheHits', 0)} from cache</td></tr>
            <tr><td style="color:var(--muted);">Magnum DI</td><td>{magnum_line}</td></tr>
            <tr><td style="color:var(--muted);">Sent To Magnum DI</td><td data-testid="magnum-issues">{issues or 'Nothing — TC FlyBy settled it'}</td></tr>
        </tbody>
    </table>
    <table style="margin-top:8px;">
        <thead><tr><th>Check</th><th>Status</th><th>Settled By</th></tr></thead>
        <tbody>{checks or '<tr><td colspan="3" style="color:var(--muted);">No checks were planned</td></tr>'}</tbody>
    </table>
    """


# ── Higgins Plain English: the Fidelity Check of each result (services/higgins/explain) ──
_FIDELITY_MODES = {"plain": "Plain English shown", "repaired": "Plain English shown, failed parts in ApolloSG's wording",
                   "literal": "Apollo's wording shown"}


def _fidelity_badge(fidelity: dict | None) -> str:
    if not fidelity:
        return '<span style="color:var(--muted);">&mdash;</span>'
    status = fidelity.get("status") or "FAIL"
    colour = "var(--green)" if status == "PASS" else "var(--red)"
    repaired = ' <span style="font-size:0.78em;color:var(--muted);">repaired</span>' if fidelity.get("mode") == "repaired" else ""
    return (f'<span class="badge" data-testid="fidelity-{status.lower()}" style="background:rgba(127,127,127,0.12);color:{colour};">'
            f'{html_mod.escape(status)}</span>{repaired}')


def _fidelity_summary_html(rows: list[dict]) -> str:
    """How often Higgins' plain English passed its Fidelity Check over the period."""
    from services.higgins.explain import fidelity as fidelity_check
    checked = [r["routing"]["fidelity"] for r in rows if (r["routing"] or {}).get("fidelity")]
    count = lambda mode: sum(1 for f in checked if f.get("mode") == mode)  # noqa: E731
    codes: dict[str, int] = {}
    for f in checked:
        for attempt in f.get("attemptFailures") or []:
            for failure in attempt:
                codes[failure.get("code", "")] = codes.get(failure.get("code", ""), 0) + 1
    code_rows = "".join(f"<tr><td><code>{html_mod.escape(code)}</code></td><td>{html_mod.escape(fidelity_check.describe(code))}</td>"
                        f"<td style='text-align:right;'>{n:,}</td></tr>" for code, n in sorted(codes.items(), key=lambda kv: -kv[1]))
    return f"""
    <h2 data-testid="fidelity-heading">Higgins Plain English &mdash; Fidelity Check</h2>
    <p style="font-size:0.82em;color:var(--muted);margin:4px 0 8px;">
        Before a result's plain-English explanation is shown, it is checked against the result: nothing lost, added or changed.
        A part that fails is put back in Apollo's own wording and checked again; if it still fails, the person sees Apollo's own wording only.
    </p>
    <div class="stats-grid">
        {_stat_card(f'{len(checked):,}', 'Results Checked')}
        {_stat_card(f'{count("plain"):,}', 'PASS First Time')}
        {_stat_card(f'{count("repaired"):,}', 'PASS After Repair')}
        {_stat_card(f'{count("literal"):,}', "FAIL: Apollo's Wording Shown")}
    </div>
    <table>
        <thead><tr><th>Failure</th><th>What it means</th><th>Times</th></tr></thead>
        <tbody>{code_rows or '<tr><td colspan="3" style="color:var(--muted);">No failures this period</td></tr>'}</tbody>
    </table>
    """


def _fidelity_attempts_html(fidelity: dict) -> str:
    from services.higgins.explain import fidelity as fidelity_check
    rows = ""
    for n, failures in enumerate(fidelity.get("attemptFailures") or [], start=1):
        lines = []
        for f in failures:
            where = " &middot; ".join(html_mod.escape(x) for x in (f.get("ref"), f.get("detail")) if x)
            lines.append(f"<code>{html_mod.escape(f.get('code', ''))}</code> {html_mod.escape(fidelity_check.describe(f.get('code', '')))}"
                         + (f" <span style='color:var(--muted);'>({where})</span>" if where else ""))
        result = "<br>".join(lines) or '<span style="color:var(--green);">PASS</span>'
        rows += f"<tr><td style='color:var(--muted);'>Attempt {n}</td><td data-testid='fidelity-attempt-{n}'>{result}</td></tr>"
    return rows


def _fidelity_texts_html(case: dict) -> str:
    """Apollo's wording beside Higgins' plain English, read from the case while the server still holds it."""
    from core.redaction import redact_investigation_secrets as clean
    from services.higgins.repository import dec_json
    response = None
    if case.get("response_ciphertext"):
        try:
            response = dec_json(case["response_ciphertext"])
        except Exception:  # noqa: BLE001 — unreadable record: say so rather than guess
            response = None
    if not response:
        return ('<p style="color:var(--muted);" data-testid="fidelity-texts-gone">The case content has left the server (ApolloSG keeps it no '
                'longer than 24 hours after the investigation finishes), so the two texts are no longer available. The check result stays.</p>')
    esc = lambda t: html_mod.escape(clean(t or ""))  # noqa: E731
    bullets = lambda items: "".join(f"<li>{esc(i)}</li>" for i in items if i)  # noqa: E731
    steps = [f"{a.get('label')}: {a.get('instruction')}" for a in response.get("actions") or []]
    apollo = (f"<p>{esc(response.get('overview'))}</p><h4>Findings</h4><ul>"
              + "".join(f"<li>{esc(f.get('text'))} <span style='color:var(--muted);'>({esc(f.get('basis'))} &middot; {esc(f.get('confidence'))})</span></li>"
                        for f in response.get("findings") or [])
              + f"</ul><h4>Explanation</h4><div style='white-space:pre-wrap;'>{esc(response.get('explanationMarkdown'))}</div>"
              + f"<h4>Reason</h4><p>{esc(response.get('attentionReason'))}</p>"
              + f"<h4>What to do</h4><ul>{bullets(steps)}</ul>"
              + f"<h4>Not certain</h4><ul>{bullets(response.get('uncertainties') or [])}</ul><h4>Scope</h4><p>{esc(response.get('scope'))}</p>")
    plain = response.get("plainEnglish")
    if plain and plain.get("mode") != "literal":
        higgins = (f"<p><strong>{esc(plain.get('result'))}</strong></p><p>{esc(plain.get('severity'))}</p><h4>What was found</h4><ul>"
                   + "".join(f"<li>{esc(i.get('text'))} <span style='color:var(--muted);'>({esc(i.get('detail'))})</span>"
                             + (f"<br><em style='color:var(--muted);'>{esc(i.get('explain'))}</em>" if i.get("explain") else "") + "</li>"
                             for i in plain.get("established") or [])
                   + f"</ul><h4>What it means</h4><ul>{bullets([*(plain.get('means') or []), *(plain.get('matters') or [])])}</ul>"
                   + f"<h4>What to do</h4><ul>{bullets(plain.get('todo') or [])}</ul>"
                   + f"<h4>Not certain</h4><ul>{bullets(plain.get('uncertain') or [])}</ul>"
                   + f"<h4>How Apollo checked</h4><ul>{bullets(plain.get('how') or [])}</ul>")
    else:
        higgins = "<p style='color:var(--muted);'>Not shown. The plain English failed its check, so the person saw Apollo's own wording.</p>"
    return (f"<table style='margin-top:8px;'><thead><tr><th style='width:50%;'>Apollo's wording (authoritative)</th>"
            f"<th>Higgins' plain English (what the person saw)</th></tr></thead><tbody><tr>"
            f"<td style='vertical-align:top;white-space:normal;' data-testid='fidelity-apollo-text'>{apollo}</td>"
            f"<td style='vertical-align:top;white-space:normal;' data-testid='fidelity-plain-text'>{higgins}</td></tr></tbody></table>")


def _fidelity_drilldown_html(case: dict | None) -> str:
    """The Fidelity Check of this case's latest result, and both texts while the server still holds the case."""
    fidelity = ((case or {}).get("routing") or {}).get("fidelity")
    if not fidelity:
        return ""
    mode = fidelity.get("mode") or ""
    return f"""
    <h2 data-testid="fidelity-drilldown">Higgins Plain English &mdash; Fidelity Check</h2>
    <table>
        <tbody>
            <tr><td style="color:var(--muted);width:180px;">Result</td><td>{_fidelity_badge(fidelity)}</td></tr>
            <tr><td style="color:var(--muted);">Shown To The Person</td><td data-testid="fidelity-mode">{html_mod.escape(_FIDELITY_MODES.get(mode, mode))}</td></tr>
            <tr><td style="color:var(--muted);">Result Explained</td><td>Revision {fidelity.get('revision', '—')} &middot; settled by {html_mod.escape(fidelity.get('by') or '—')}</td></tr>
            <tr><td style="color:var(--muted);">Checked</td><td>{_to_local(fidelity.get('at'))}</td></tr>
            {_fidelity_attempts_html(fidelity)}
        </tbody>
    </table>
    {_fidelity_texts_html(case or {})}
    """


def _triage_rules_html(triage: dict | None) -> str:
    """Higgins Triage's rule-catalogue record for this case: the codes the app's DI tab no longer shows."""
    if not triage:
        return ""
    rows = "".join(
        f"<tr><td><code>{html_mod.escape(str(r.get('ruleId', '')))}</code></td><td>{html_mod.escape(str(r.get('title', '')))}</td>"
        f"<td>{html_mod.escape(str(r.get('result', '')))}{(' &middot; ' + html_mod.escape(str(r['coverageGap']))) if r.get('coverageGap') else ''}</td>"
        f"<td style='white-space:normal;font-size:0.82em;'>{html_mod.escape('; '.join(str(e) for e in r.get('evidence') or [])[:300])}</td></tr>"
        for r in triage.get("rules") or [] if r.get("applicable"))
    gaps = "<br>".join(f"<code>{html_mod.escape(str(g.get('code', '')))}</code> &middot; rules {html_mod.escape(', '.join(g.get('ruleIds') or []))}"
                       for g in triage.get("coverageGaps") or [])
    return f"""
    <h2 data-testid="triage-rules-drilldown">Higgins Triage &mdash; Rule Catalogue</h2>
    <table>
        <tbody>
            <tr><td style="color:var(--muted);width:180px;">Outcome</td><td><code>{html_mod.escape(str(triage.get('outcome', '')))}</code></td></tr>
            <tr><td style="color:var(--muted);">Catalogue</td><td>v{html_mod.escape(str(triage.get('catalogueVersion', '—')))} &middot; source {html_mod.escape(str(triage.get('sourceType', '—')))}</td></tr>
            <tr><td style="color:var(--muted);">Rules</td><td>{len(triage.get('rulesChecked') or [])} of {len(triage.get('rulesApplicable') or [])} applicable checked &middot; met: {html_mod.escape(', '.join(triage.get('rulesMet') or []) or 'none')}</td></tr>
            <tr><td style="color:var(--muted);">Coverage Gaps</td><td>{gaps or 'None'}</td></tr>
            <tr><td style="color:var(--muted);">Evaluated</td><td>{_to_local(triage.get('evaluatedAt'))}</td></tr>
        </tbody>
    </table>
    <table style="margin-top:8px;">
        <thead><tr><th>Rule</th><th>Title</th><th>Result</th><th>Evidence</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="4" style="color:var(--muted);">No applicable rules recorded</td></tr>'}</tbody>
    </table>
    """


def _di_transactions_html(records: list[dict]) -> str:
    """Every AI transaction recorded for this case in full (Magnum DI's, and TC FlyBy's search call): status, tokens,
    cost, timing, the prompts sent and the complete reply. The app's DI tab shows only whether Magnum DI ran and what
    it was handed."""
    if not records:
        return '<h2>AI Transactions</h2><p style="color:var(--muted);">No AI call was recorded for this case: Magnum DI was not engaged.</p>'
    blocks = ""
    for i, r in enumerate(records):
        p = r.get("processing") or {}
        req = r.get("request") or {}
        cost = p.get("cost") or {}
        amount = cost.get("amountUsd")
        cost_line = "not recorded" if amount is None else f"US${amount:.6f} ({html_mod.escape(str(cost.get('basis', '')))})"
        tokens_basis = "simulated" if p.get("tokensAreSimulated") else "estimated" if p.get("tokensAreEstimates") else "measured"
        num = lambda v: "—" if v is None else f"{v:,}"  # noqa: E731
        response = r.get("response") or {}
        blocks += f"""
        <div class="s-card" style="margin-bottom:12px;" data-testid="di-transaction-{i}">
            <div class="s-card-head"><strong>Transaction {i + 1}</strong> &nbsp; {'TC FlyBy search' if r.get('purpose') == 'tc_flyby_search' else 'Magnum DI'} &middot; {_to_local(r.get('created_at'))}
                &middot; {html_mod.escape(str(r.get('status') or 'not recorded'))}{(' (' + html_mod.escape(str(r['failure_code'])) + ')') if r.get('failure_code') else ''}
                &middot; {'Simulated' if r.get('simulated') else 'Live'} &middot; {html_mod.escape(str(r.get('environment', '')))}</div>
            <table style="margin-top:8px;"><tbody>
                <tr><td style="color:var(--muted);width:180px;">Model</td><td>{html_mod.escape(str(r.get('model_requested') or '—'))} &middot; {html_mod.escape(str(r.get('provider') or '—'))}</td></tr>
                <tr><td style="color:var(--muted);">Tokens ({tokens_basis})</td><td data-testid="di-tokens-{i}">prompt {num(p.get('promptTokens'))} &middot; output {num(p.get('outputTokens'))} &middot; total {num(p.get('totalTokens'))} &middot; cached {num(p.get('cachedTokens'))}</td></tr>
                <tr><td style="color:var(--muted);">Cost</td><td data-testid="di-cost-{i}">{cost_line}</td></tr>
                <tr><td style="color:var(--muted);">Duration</td><td>{num(p.get('durationMs'))} ms &middot; {num(p.get('geminiCalls'))} call(s) &middot; {num(p.get('retries'))} retr(ies)</td></tr>
                <tr><td style="color:var(--muted);">Request</td><td>{num(req.get('requestBytes'))} bytes &middot; {req.get('attachmentCount', 0)} attachment(s) &middot; tools: {html_mod.escape(', '.join(req.get('tools') or []) or 'none')}</td></tr>
                <tr><td style="color:var(--muted);">Finish Reason</td><td>{html_mod.escape(str(response.get('finishReason') or '—'))}</td></tr>
            </tbody></table>
            <details style="margin-top:8px;"><summary>System prompt</summary><pre style="white-space:pre-wrap;font-size:0.8em;">{html_mod.escape(req.get('systemPrompt') or '(none)')}</pre></details>
            <details style="margin-top:4px;"><summary>Question and evidence sent</summary><pre style="white-space:pre-wrap;font-size:0.8em;" data-testid="di-prompt-{i}">{html_mod.escape(req.get('investigationPrompt') or 'not recorded')}</pre></details>
            <details style="margin-top:4px;"><summary>Complete reply</summary><pre style="white-space:pre-wrap;font-size:0.8em;" data-testid="di-reply-{i}">{html_mod.escape(response.get('text') or 'not recorded')}</pre></details>
        </div>"""
    return f'<h2 data-testid="di-transactions">AI Transactions ({len(records)})</h2>{blocks}'


def _investigation_desc(case: dict, gate_str: str) -> str:
    """Build a non-sensitive investigation description."""
    status = case.get("status", "unknown")
    case_id_short = case.get("case_id", "")[:8]
    if gate_str and gate_str != "None / System":
        return f"{gate_str} investigation — Case #{case_id_short}"
    return f"Investigation — Case #{case_id_short}"


def _parse_filter_dates(request: Request) -> tuple[datetime, datetime, str]:
    """Parse date filter query params. Returns (start_utc, end_utc, preset_label)."""
    preset = request.query_params.get("period", "today")
    now = now_utc()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if preset == "24h":
        return (now - timedelta(hours=24), now, "Last 24 Hours")
    if preset == "7d":
        return (now - timedelta(days=7), now, "Last 7 Days")
    if preset == "30d":
        return (now - timedelta(days=30), now, "Last 30 Days")
    if preset == "all":
        return (datetime(2020, 1, 1, tzinfo=timezone.utc), now, "All Time")
    if preset == "oct17":
        # 17 October 2026 incident analysis preset
        oct17_start = datetime(2026, 10, 17, 0, 0, 0, tzinfo=timezone.utc)
        oct17_end = datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc)
        return (oct17_start, oct17_end, "17 Oct Incident")
    if preset == "custom":
        try:
            start_str = request.query_params.get("start", "")
            end_str = request.query_params.get("end", "")
            start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc) if start_str else today_midnight
            end = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc) if end_str else now
            return (start, end, "Custom")
        except Exception:
            pass
    # Default: today
    return (today_midnight, now, "Today")


@router.get("/admin/investigations-cost", response_class=HTMLResponse)
async def investigations_cost_report(request: Request):
    """Gemini Investigation Cost Report — per-investigation cost attribution."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    from services.higgins.repository import dec_json

    start_utc, end_utc, period_label = _parse_filter_dates(request)
    filter_device = request.query_params.get("device", "")
    filter_gate = request.query_params.get("gate", "")
    filter_initiator = request.query_params.get("initiator", "")
    filter_case = request.query_params.get("case_id", "")
    filter_env = request.query_params.get("env", "")
    now = now_utc()

    # ── 1. Aggregate gemini_usage by correlation_id for the period ──
    usage_pipeline = [
        {"$match": {"timestamp": {"$gte": start_utc, "$lte": end_utc}}},
        {"$group": {
            "_id": "$correlation_id",
            "calls": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$success", 1, 0]}},
            "fail": {"$sum": {"$cond": ["$success", 0, 1]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "first_call": {"$min": "$timestamp"},
            "last_call": {"$max": "$timestamp"},
            "purposes": {"$addToSet": "$purpose"},
            "models": {"$addToSet": "$model"},
            "sources": {"$addToSet": "$extra.trigger_source"},
            # Cost routing: Magnum DI's call(s) and TC FlyBy's search call(s) are counted apart.
            "magnum_calls": {"$sum": {"$cond": [{"$eq": ["$purpose", "investigation"]}, 1, 0]}},
            "flyby_calls": {"$sum": {"$cond": [{"$eq": ["$purpose", "tc_flyby_search"]}, 1, 0]}},
            "magnum_in": {"$sum": {"$cond": [{"$eq": ["$purpose", "investigation"]}, {"$ifNull": ["$tokens.input", 0]}, 0]}},
            "magnum_out": {"$sum": {"$cond": [{"$eq": ["$purpose", "investigation"]}, {"$ifNull": ["$tokens.output", 0]}, 0]}},
            "flyby_in": {"$sum": {"$cond": [{"$eq": ["$purpose", "tc_flyby_search"]}, {"$ifNull": ["$tokens.input", 0]}, 0]}},
            "flyby_out": {"$sum": {"$cond": [{"$eq": ["$purpose", "tc_flyby_search"]}, {"$ifNull": ["$tokens.output", 0]}, 0]}},
            "magnum_queries": {"$sum": {"$cond": [{"$eq": ["$purpose", "investigation"]}, {"$ifNull": ["$search_queries", 0]}, 0]}},
            "flyby_queries": {"$sum": {"$cond": [{"$eq": ["$purpose", "tc_flyby_search"]}, {"$ifNull": ["$search_queries", 0]}, 0]}},
            "magnum_search_calls": {"$sum": {"$cond": [{"$and": [{"$eq": ["$purpose", "investigation"]},
                                                                 {"$eq": ["$extra.search_tool", True]}]}, 1, 0]}},
        }},
        {"$sort": {"cost": -1}},
    ]
    usage_groups = await db.gemini_usage.aggregate(usage_pipeline).to_list(2000)

    # ── 2. Separate investigation-attributed vs unattributed ──
    investigation_groups = []
    unattributed_groups = []
    for g in usage_groups:
        cid = g["_id"] or ""
        if cid.startswith("case-"):
            investigation_groups.append(g)
        else:
            unattributed_groups.append(g)

    # Cases TC FlyBy settled without any Gemini call have no usage record, but they are investigations too.
    gemini_case_ids = [g["_id"][5:] for g in investigation_groups]
    async for routed in db.investigation_cases.find({"routing.tc_flyby.ranAt": {"$gte": start_utc, "$lte": end_utc},
                                                     "case_id": {"$nin": gemini_case_ids}}, {"_id": 0, "case_id": 1, "routing": 1}):
        ran_at = routed["routing"]["tc_flyby"]["ranAt"]
        investigation_groups.append({"_id": f"case-{routed['case_id']}", "calls": 0, "ok": 0, "fail": 0, "input_tokens": 0, "output_tokens": 0,
                                     "thinking_tokens": 0, "cached_tokens": 0, "cost": 0.0, "first_call": ran_at, "last_call": ran_at,
                                     "purposes": [], "models": ["tc-flyby"], "sources": []})

    # ── 3. Lookup investigation_cases and jobs for each case_id ──
    case_ids = [g["_id"][5:] for g in investigation_groups]  # strip "case-" prefix
    cases_map: dict[str, dict] = {}
    jobs_map: dict[str, dict] = {}

    if case_ids:
        async for c in db.investigation_cases.find({"case_id": {"$in": case_ids}}, {"_id": 0}):
            cases_map[c["case_id"]] = c
        # Get the first/primary job for each case
        async for j in db.investigation_jobs.find(
            {"case_id": {"$in": case_ids}},
            {"_id": 0, "case_id": 1, "source": 1, "created_at": 1, "status": 1, "auto_resume_count": 1}
        ).sort("created_at", 1):
            if j["case_id"] not in jobs_map:
                jobs_map[j["case_id"]] = j

    # ── 4. Build report rows ──
    report_rows = []
    for g in investigation_groups:
        case_id = g["_id"][5:]
        case = cases_map.get(case_id, {})
        job = jobs_map.get(case_id, {})

        # Device
        dev_profile = None
        if case.get("device_profile_ciphertext"):
            try:
                dev_profile = dec_json(case["device_profile_ciphertext"])
            except Exception:
                pass
        device = _device_name(dev_profile)

        # Gate
        gate_str = _gate_display(case.get("gates"))

        # Initiated by - prefer job source, fallback to usage trigger_source
        source = job.get("source") or (g["sources"][0] if g["sources"] else None)
        initiator = _initiator_label(source)
        initiator_cat = _initiator_category(source)

        # Recovery
        resumed = (job.get("auto_resume_count") or 0) > 0

        # Environment
        env = _env_label(g["models"][0] if g["models"] else None)

        # Description
        desc = _investigation_desc(case, gate_str)

        # Total tokens
        total_tokens = g["input_tokens"] + g["output_tokens"] + g["thinking_tokens"]

        row = {
            "case_id": case_id,
            "corr_id": g["_id"],
            "device": device,
            "desc": desc,
            "gate": gate_str,
            "initiator": initiator,
            "initiator_cat": initiator_cat,
            "source_raw": source,
            "started": g["first_call"],
            "ended": g["last_call"],
            "calls": g["calls"],
            "ok": g["ok"],
            "fail": g["fail"],
            "input_tokens": g["input_tokens"],
            "output_tokens": g["output_tokens"],
            "thinking_tokens": g["thinking_tokens"],
            "cached_tokens": g["cached_tokens"],
            "total_tokens": total_tokens,
            "cost": g["cost"],
            "status": case.get("status", "unknown"),
            "env": env,
            "resumed": resumed,
            "models": g["models"],
            "answered_by": _answered_by(case, g.get("magnum_calls", 0)),
            "routing": case.get("routing") or {},
            **{k: g.get(k, 0) for k in ("magnum_calls", "flyby_calls", "magnum_in", "magnum_out", "flyby_in", "flyby_out",
                                        "magnum_queries", "flyby_queries", "magnum_search_calls")},
        }

        # Apply filters
        if filter_device and filter_device.lower() not in device.lower():
            continue
        if filter_gate and filter_gate.lower() not in gate_str.lower():
            continue
        if filter_initiator and filter_initiator.lower() not in initiator.lower() and filter_initiator.lower() not in initiator_cat.lower():
            continue
        if filter_case and filter_case.lower() not in case_id.lower():
            continue
        if filter_env and filter_env.lower() != env.lower():
            continue

        report_rows.append(row)

    # ── 5. Summary totals ──
    total_investigations = len(report_rows)
    total_calls = sum(r["calls"] for r in report_rows)
    total_tokens_sum = sum(r["total_tokens"] for r in report_rows)
    total_cost = sum(r["cost"] for r in report_rows)

    # By initiator category
    by_initiator: dict[str, dict] = {}
    for r in report_rows:
        cat = r["initiator_cat"]
        b = by_initiator.setdefault(cat, {"investigations": 0, "calls": 0, "tokens": 0, "cost": 0.0})
        b["investigations"] += 1
        b["calls"] += r["calls"]
        b["tokens"] += r["total_tokens"]
        b["cost"] += r["cost"]

    # Unattributed totals
    unattr_calls = sum(g["calls"] for g in unattributed_groups)
    unattr_tokens = sum(g["input_tokens"] + g["output_tokens"] + g["thinking_tokens"] for g in unattributed_groups)
    unattr_cost = sum(g["cost"] for g in unattributed_groups)

    # Grand totals from raw DB for reconciliation
    grand_pipeline = [
        {"$match": {"timestamp": {"$gte": start_utc, "$lte": end_utc}}},
        {"$group": {"_id": None,
                    "calls": {"$sum": 1},
                    "input": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
                    "output": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
                    "thinking": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}}}},
    ]
    grand = (await db.gemini_usage.aggregate(grand_pipeline).to_list(1)) or [{}]
    gd = grand[0] if grand else {}
    grand_calls = gd.get("calls", 0)
    grand_tokens = gd.get("input", 0) + gd.get("output", 0) + gd.get("thinking", 0)
    grand_cost = gd.get("cost", 0.0)

    # ── Get distinct values for filter dropdowns ──
    all_devices = sorted(set(r["device"] for r in report_rows))
    all_gates = sorted(set(r["gate"] for r in report_rows))
    all_initiators = sorted(set(r["initiator_cat"] for r in report_rows))
    all_envs = sorted(set(r["env"] for r in report_rows))

    # ── 6. Build HTML ──

    # Filter bar
    period_param = request.query_params.get("period", "today")
    def _period_btn(val: str, label: str) -> str:
        active = ' style="border-color:var(--accent);color:#fff;"' if period_param == val else ""
        return f'<a href="?period={val}" class="btn btn-sm"{active}>{label}</a>'

    filter_html = f"""
    <div class="topbar-row" style="flex-wrap:wrap;gap:8px;">
        <div style="display:flex;gap:6px;align-items:center;">
            <span style="font-size:0.82em;color:var(--muted);">Period:</span>
            {_period_btn("today", "Today")}
            {_period_btn("24h", "Last 24h")}
            {_period_btn("7d", "Last 7 Days")}
            {_period_btn("30d", "Last 30 Days")}
            {_period_btn("all", "All Time")}
            {_period_btn("oct17", "17 Oct Incident")}
        </div>
        <div style="font-size:0.82em;color:var(--muted);">
            {_to_local(start_utc)} &mdash; {_to_local(end_utc)} ({_TZ_NAME})
        </div>
    </div>
    <form method="get" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;font-size:0.82em;">
        <input type="hidden" name="period" value="{html_mod.escape(period_param)}"/>
        <input name="device" placeholder="Filter device…" value="{html_mod.escape(filter_device)}" style="background:var(--card);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:6px;width:120px;"/>
        <input name="gate" placeholder="Filter gate…" value="{html_mod.escape(filter_gate)}" style="background:var(--card);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:6px;width:120px;"/>
        <select name="initiator" style="background:var(--card);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:6px;">
            <option value="">All initiators</option>
            {''.join(f'<option value="{html_mod.escape(i)}"{"selected" if filter_initiator == i else ""}>{html_mod.escape(i)}</option>' for i in all_initiators)}
        </select>
        <input name="case_id" placeholder="Case ID…" value="{html_mod.escape(filter_case)}" style="background:var(--card);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:6px;width:120px;"/>
        <select name="env" style="background:var(--card);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:6px;">
            <option value="">All environments</option>
            {''.join(f'<option value="{html_mod.escape(e)}"{"selected" if filter_env == e else ""}>{html_mod.escape(e)}</option>' for e in all_envs)}
        </select>
        <button type="submit" class="btn btn-sm">Filter</button>
        <a href="?period={html_mod.escape(period_param)}" class="btn btn-sm" style="color:var(--muted);">Clear</a>
    </form>
    """

    # Environment indicator
    from services.higgins.provider import get_provider_mode
    pmode = get_provider_mode()
    env_indicator = f"""<div class="alert {'alert-warning' if pmode == 'preview' else 'alert-ok'}" style="margin-bottom:16px;">
        <strong>Environment:</strong> {'Preview (simulated — no paid Gemini calls)' if pmode == 'preview'
            else 'Production'} &nbsp;|&nbsp;
        <strong>Times:</strong> {_TZ_NAME} ("Today" starts at midnight UTC) &nbsp;|&nbsp;
        <strong>Period:</strong> {period_label}
    </div>"""

    # Summary cards
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    # One Magnum DI investigation = at most one Gemini call, never retried.
    # TC FlyBy's search request is counted separately below, under cost routing.
    over_limit = sum(1 for r in report_rows if r["magnum_calls"] > 1)
    magnum_cases = sum(1 for r in report_rows if r["magnum_calls"])
    avg_calls = total_calls / total_investigations if total_investigations else 0.0
    avg_cost = total_cost / total_investigations if total_investigations else 0.0
    summary_html = f"""
    <div class="stats-grid">
        {_stat_card(f'{total_investigations:,}', 'Investigation Cases')}
        {_stat_card(f'{total_calls:,}', 'Gemini API Calls')}
        {_stat_card(f'{avg_calls:.2f}', 'Calls per Investigation')}
        {_stat_card(f'${avg_cost:.4f}', 'Est. Cost per Investigation')}
        {_stat_card(_fmt_tokens(total_tokens_sum), 'Total Tokens')}
        {_stat_card(f'${total_cost:.4f}', 'Estimated Cost')}
    </div>
    <div class="alert {'alert-critical' if over_limit else 'alert-ok'}">
        <strong>One Magnum DI investigation = one Gemini call.</strong>
        {magnum_cases - over_limit:,} answered with their one call &middot; {over_limit:,} over the limit{' — investigate these cases' if over_limit else ''}.
        Gemini calls outside investigations this period: {unattr_calls:,} (${unattr_cost:.4f}).
    </div>
    {_routing_html(report_rows, avg_cost)}
    {_fidelity_summary_html(report_rows)}
    """

    # Initiator breakdown
    init_tbody = ""
    for cat in sorted(by_initiator.keys()):
        b = by_initiator[cat]
        init_tbody += f"""<tr>
            <td>{html_mod.escape(cat)}</td>
            <td style="text-align:right;">{b['investigations']:,}</td>
            <td style="text-align:right;">{b['calls']:,}</td>
            <td style="text-align:right;">{_fmt_tokens(b['tokens'])}</td>
            <td style="text-align:right;">${b['cost']:.4f}</td>
        </tr>"""
    if unattr_calls > 0:
        init_tbody += f"""<tr style="color:var(--yellow);">
            <td>Unattributed</td>
            <td style="text-align:right;">—</td>
            <td style="text-align:right;">{unattr_calls:,}</td>
            <td style="text-align:right;">{_fmt_tokens(unattr_tokens)}</td>
            <td style="text-align:right;">${unattr_cost:.4f}</td>
        </tr>"""

    init_html = f"""
    <h2>Breakdown by Initiator</h2>
    <table>
        <thead><tr><th>Initiated By</th><th>Investigations</th><th>Gemini Calls</th><th>Total Tokens</th><th>Estimated Cost</th></tr></thead>
        <tbody>{init_tbody or '<tr><td colspan="5" style="color:var(--muted);">No data for this period</td></tr>'}</tbody>
    </table>
    """

    # Main report table — full attribution columns
    main_tbody = ""
    for r in report_rows:
        resumed_badge = ' <span class="badge" style="background:rgba(210,153,34,0.15);color:var(--yellow);">Resumed</span>' if r["resumed"] else ""
        src_display = html_mod.escape(r.get("source_raw") or "—")
        env_cls = "color:var(--green);" if r["env"] == "Mock" else ("color:var(--yellow);" if r["env"] == "Production" else "")
        main_tbody += f"""<tr>
            <td>{html_mod.escape(r['device'])}</td>
            <td><a href="/api/admin/investigations-cost/{r['case_id']}?period={html_mod.escape(period_param)}">{html_mod.escape(r['desc'])}</a>{resumed_badge}</td>
            <td>{_answered_by_badge(r['answered_by'])}</td>
            <td>{_outcome_badge(r['routing'].get('outcome'))}</td>
            <td>{_settled_reason_html(r['routing'], short=True)}</td>
            <td>{_fidelity_badge(r['routing'].get('fidelity'))}</td>
            <td>{html_mod.escape(r['gate'])}</td>
            <td>{html_mod.escape(r['initiator'])}</td>
            <td><code style="font-size:0.82em;">{src_display}</code></td>
            <td style="{env_cls}">{html_mod.escape(r['env'])}</td>
            <td style="text-align:right;">{r['calls']:,}</td>
            <td style="text-align:right;">{_fmt_tokens(r['total_tokens'])}</td>
            <td style="text-align:right;">${r['cost']:.4f}</td>
        </tr>"""

    main_html = f"""
    <h2>Investigation Cases ({total_investigations:,})</h2>
    <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
        Each row = one investigation case. Click to see individual Gemini API calls.
        <strong>Investigation cases &ne; Gemini API calls.</strong>
    </p>
    <div style="overflow-x:auto;">
    <table>
        <thead><tr>
            <th>Device</th><th>Investigation</th><th>Answered By</th><th>Outcome</th><th>Why</th><th>Plain English</th><th>Gate</th><th>Initiated By</th>
            <th>Source</th><th>Env</th><th>Calls</th><th>Total Tokens</th><th>Est. Cost</th>
        </tr></thead>
        <tbody>{main_tbody or '<tr><td colspan="13" style="color:var(--muted);">No investigations found for this period and filters</td></tr>'}</tbody>
    </table>
    </div>
    """

    # Unattributed calls section
    unattr_html = ""
    if unattributed_groups:
        unattr_tbody = ""
        for g in unattributed_groups[:30]:
            cid = g["_id"] or "NULL"
            total = g["input_tokens"] + g["output_tokens"] + g["thinking_tokens"]
            purposes = ", ".join(g["purposes"][:3])
            srcs = ", ".join(str(s) for s in g["sources"][:3] if s)
            unattr_tbody += f"""<tr>
                <td style="font-size:0.82em;"><code>{html_mod.escape(str(cid)[:32])}</code></td>
                <td>{html_mod.escape(purposes)}</td>
                <td>{html_mod.escape(srcs or 'unknown')}</td>
                <td style="text-align:right;">{g['calls']:,}</td>
                <td style="text-align:right;">{_fmt_tokens(total)}</td>
                <td style="text-align:right;">${g['cost']:.4f}</td>
            </tr>"""
        unattr_html = f"""
        <h2>Unattributed Gemini Calls ({unattr_calls:,})</h2>
        <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
            These Gemini calls could not be attributed to a specific investigation case.
            They include chat, research, health checks, message checks, and other non-case calls.
        </p>
        <table>
            <thead><tr><th>Correlation ID</th><th>Purpose</th><th>Source</th><th>Calls</th><th>Tokens</th><th>Cost</th></tr></thead>
            <tbody>{unattr_tbody}</tbody>
        </table>
        """

    # Reconciliation
    attributed_calls = total_calls + unattr_calls
    attributed_cost = total_cost + unattr_cost
    calls_diff = grand_calls - attributed_calls
    cost_diff = grand_cost - attributed_cost
    reconciled = abs(calls_diff) == 0 and abs(cost_diff) < 0.01

    recon_html = f"""
    <h2>Reconciliation</h2>
    <table>
        <thead><tr><th>Category</th><th>Gemini Calls</th><th>Total Tokens</th><th>Estimated Cost</th></tr></thead>
        <tbody>
            <tr><td>Investigation-attributed</td><td style="text-align:right;">{total_calls:,}</td><td style="text-align:right;">{_fmt_tokens(total_tokens_sum)}</td><td style="text-align:right;">${total_cost:.4f}</td></tr>
            <tr><td>Unattributed (non-investigation)</td><td style="text-align:right;">{unattr_calls:,}</td><td style="text-align:right;">{_fmt_tokens(unattr_tokens)}</td><td style="text-align:right;">${unattr_cost:.4f}</td></tr>
            <tr style="font-weight:700;background:var(--card);"><td>Sum (attributed + unattributed)</td><td style="text-align:right;">{attributed_calls:,}</td><td style="text-align:right;">{_fmt_tokens(total_tokens_sum + unattr_tokens)}</td><td style="text-align:right;">${attributed_cost:.4f}</td></tr>
            <tr style="font-weight:700;"><td>Overall recorded gemini_usage</td><td style="text-align:right;">{grand_calls:,}</td><td style="text-align:right;">{_fmt_tokens(grand_tokens)}</td><td style="text-align:right;">${grand_cost:.4f}</td></tr>
            <tr><td>Discrepancy</td><td style="text-align:right;color:{'var(--green)' if calls_diff == 0 else 'var(--red)'};">{calls_diff:+,}</td><td></td><td style="text-align:right;color:{'var(--green)' if abs(cost_diff) < 0.01 else 'var(--red)'};">${cost_diff:+.4f}</td></tr>
        </tbody>
    </table>
    <div class="alert {'alert-ok' if reconciled else 'alert-warning'}">
        {'Reconciled — attributed + unattributed equals overall recorded usage.' if reconciled
         else 'Discrepancy detected — some calls may have different correlation_id formats or missing attribution.'}
    </div>
    <p style="font-size:0.82em;color:var(--muted);margin-top:4px;">
        <strong>Estimated Cost</strong> is calculated from recorded token counts using ApolloSG&rsquo;s pricing table.
        It may differ from your actual Google bill due to: Google Search grounding charges on research calls,
        pricing table drift, or cached-token treatment differences. It does not represent a direct Google invoice amount.
    </p>
    """

    # ── Temporal Burst Analysis ──
    # Groups calls into 1-minute windows to identify automated bursts
    burst_pipeline = [
        {"$match": {"timestamp": {"$gte": start_utc, "$lte": end_utc}}},
        {"$group": {
            "_id": {
                "minute": {"$dateToString": {"format": "%Y-%m-%dT%H:%M", "date": "$timestamp"}},
                "purpose": "$purpose",
            },
            "calls": {"$sum": 1},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "sources": {"$addToSet": "$extra.trigger_source"},
            "corr_ids": {"$addToSet": "$correlation_id"},
        }},
        {"$sort": {"_id.minute": 1}},
    ]
    burst_raw = await db.gemini_usage.aggregate(burst_pipeline).to_list(5000)

    # Aggregate by minute (across purposes)
    from collections import defaultdict as _ddict
    minute_data: dict[str, dict] = {}
    for b in burst_raw:
        minute_key = b["_id"]["minute"]
        md = minute_data.setdefault(minute_key, {"calls": 0, "cost": 0.0, "input_tokens": 0, "purposes": set(), "sources": set(), "corr_ids": set()})
        md["calls"] += b["calls"]
        md["cost"] += b["cost"]
        md["input_tokens"] += b["input_tokens"]
        md["purposes"].add(b["_id"]["purpose"])
        md["sources"].update(s for s in b["sources"] if s)
        md["corr_ids"].update(c for c in b["corr_ids"] if c)

    # Find burst minutes (> 5 calls/minute or > $0.05/minute)
    burst_minutes = [(m, d) for m, d in sorted(minute_data.items()) if d["calls"] >= 5 or d["cost"] >= 0.05]

    burst_html = ""
    if burst_minutes:
        burst_tbody = ""
        for minute_str, d in burst_minutes:
            # Highlight especially hot minutes
            is_hot = d["calls"] >= 20 or d["cost"] >= 0.20
            row_style = 'style="background:rgba(220,60,60,0.12);"' if is_hot else ""
            srcs = ", ".join(sorted(d["sources"])) or "—"
            purposes = ", ".join(sorted(d["purposes"]))
            # The minute bucket (grouped in UTC) as a time on the admin's own clock.
            burst_tbody += f"""<tr {row_style}>
                <td>{_t(minute_str, "short")}</td>
                <td style="text-align:right;font-weight:{'700' if is_hot else 'normal'};">{d['calls']:,}</td>
                <td style="text-align:right;">{_fmt_tokens(d['input_tokens'])}</td>
                <td style="text-align:right;">${d['cost']:.4f}</td>
                <td>{html_mod.escape(purposes)}</td>
                <td><code style="font-size:0.78em;">{html_mod.escape(srcs)}</code></td>
                <td style="text-align:right;">{len(d['corr_ids'])}</td>
            </tr>"""

        total_burst_calls = sum(d["calls"] for _, d in burst_minutes)
        total_burst_cost = sum(d["cost"] for _, d in burst_minutes)
        hot_count = sum(1 for _, d in burst_minutes if d["calls"] >= 20 or d["cost"] >= 0.20)

        burst_html = f"""
        <h2>Temporal Burst Analysis</h2>
        <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
            Minutes with &ge;5 calls or &ge;$0.05 cost. <span style="background:rgba(220,60,60,0.12);padding:2px 6px;border-radius:3px;">Red rows</span> = &ge;20 calls or &ge;$0.20/min (automated burst indicator).
            Total: <strong>{total_burst_calls:,}</strong> calls across <strong>{len(burst_minutes)}</strong> active minutes
            ({hot_count} hot). Burst cost: <strong>${total_burst_cost:.4f}</strong>
        </p>
        <div style="overflow-x:auto;max-height:400px;overflow-y:auto;">
        <table>
            <thead><tr>
                <th>Minute</th><th>Calls</th><th>Input Tokens</th><th>Est. Cost</th>
                <th>Purpose(s)</th><th>Source(s)</th><th>Distinct CorrIDs</th>
            </tr></thead>
            <tbody>{burst_tbody}</tbody>
        </table>
        </div>
        """

    body = f"""
    {env_indicator}
    {filter_html}
    {summary_html}
    {init_html}
    {burst_html}
    {main_html}
    {unattr_html}
    {recon_html}
    """

    extra_css = "td, th { white-space: nowrap; } td a { white-space: normal; }"
    await _audit_log(adm.get("email", ""), "view_investigations_cost", f"period={period_label} investigations={total_investigations}")
    return _shell("Gemini Investigation Cost Report", "/api/admin/investigations-cost", body, admin=adm, extra_css=extra_css)


@router.get("/admin/investigations-cost/{case_id}", response_class=HTMLResponse)
async def investigation_drilldown(request: Request, case_id: str):
    """Investigation drill-down — every Gemini call for one investigation."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    from services.higgins.repository import dec_json
    from services.higgins.provider import get_provider_mode

    correlation_id = f"case-{case_id}"

    # Get the case
    case = await db.investigation_cases.find_one({"case_id": case_id}, {"_id": 0})

    # Get primary job
    job = await db.investigation_jobs.find_one({"case_id": case_id}, {"_id": 0, "case_id": 1, "source": 1, "created_at": 1, "started_at": 1, "status": 1, "auto_resume_count": 1, "retry_history": 1, "provider_model": 1})

    # Get all Gemini calls for this investigation
    calls = await db.gemini_usage.find(
        {"correlation_id": correlation_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(500)

    if not calls and not case:
        body = f"""<div class="alert alert-warning">No data found for Case ID: <code>{html_mod.escape(case_id)}</code></div>
        <a href="/api/admin/investigations-cost" class="btn">&larr; Back to report</a>"""
        return _shell("Investigation Not Found", "/api/admin/investigations-cost", body, admin=adm)

    # Device info
    dev_profile = None
    device_id = ""
    if case:
        device_id = case.get("owner_id", "")
        if case.get("device_profile_ciphertext"):
            try:
                dev_profile = dec_json(case["device_profile_ciphertext"])
            except Exception:
                pass
    device = _device_name(dev_profile)
    gate_str = _gate_display(case.get("gates") if case else None)
    source = job.get("source") if job else None
    if not source and calls:
        # Fallback: get from first call's trigger_source
        source = (calls[0].get("extra") or {}).get("trigger_source")
    initiator = _initiator_label(source)
    resumed = (job.get("auto_resume_count", 0) if job else 0) > 0

    # Aggregate totals
    total_calls = len(calls)
    total_input = sum(c.get("tokens", {}).get("input", 0) or 0 for c in calls)
    total_output = sum(c.get("tokens", {}).get("output", 0) or 0 for c in calls)
    total_thinking = sum(c.get("tokens", {}).get("thinking", 0) or 0 for c in calls)
    total_cached = sum(c.get("tokens", {}).get("cached_input", 0) or 0 for c in calls)
    total_tokens = total_input + total_output + total_thinking
    total_cost = sum(c.get("estimated_cost_usd", 0) or 0 for c in calls)
    ok_calls = sum(1 for c in calls if c.get("success"))
    fail_calls = total_calls - ok_calls

    # Timestamps
    created_at = case.get("created_at") if case else None
    started_at = job.get("started_at") if job else (calls[0].get("timestamp") if calls else None)
    completed_at = calls[-1].get("timestamp") if calls else None
    duration = ""
    if started_at and completed_at:
        if isinstance(started_at, datetime) and isinstance(completed_at, datetime):
            delta = completed_at - started_at
            mins = int(delta.total_seconds() // 60)
            secs = int(delta.total_seconds() % 60)
            duration = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    env = _env_label(calls[0].get("model") if calls else None)

    # ── Provenance section ──
    provenance_html = f"""
    <h2>Investigation Provenance</h2>
    <a href="/api/admin/investigations-cost" class="btn btn-sm" style="margin-bottom:12px;">&larr; Back to report</a>
    <table>
        <tbody>
            <tr><td style="color:var(--muted);width:180px;">Case ID</td><td><code>{html_mod.escape(case_id)}</code></td></tr>
            <tr><td style="color:var(--muted);">Correlation ID</td><td><code>{html_mod.escape(correlation_id)}</code></td></tr>
            <tr><td style="color:var(--muted);">Device</td><td>{html_mod.escape(device)}</td></tr>
            <tr><td style="color:var(--muted);">Device ID</td><td><code style="font-size:0.82em;">{html_mod.escape(device_id[:16] + '…' if len(device_id) > 16 else device_id)}</code></td></tr>
            <tr><td style="color:var(--muted);">Gate</td><td>{html_mod.escape(gate_str)}</td></tr>
            <tr><td style="color:var(--muted);">Initiated By</td><td>{html_mod.escape(initiator)}</td></tr>
            <tr><td style="color:var(--muted);">Trigger / Source</td><td><code>{html_mod.escape(source or 'unknown')}</code></td></tr>
            <tr><td style="color:var(--muted);">Environment</td><td>{html_mod.escape(env)}</td></tr>
            <tr><td style="color:var(--muted);">Recovery / Resume</td><td>{'Yes' if resumed else 'No'}</td></tr>
            <tr><td style="color:var(--muted);">Status</td><td>{html_mod.escape(case.get('status', 'unknown') if case else 'unknown')}</td></tr>
        </tbody>
    </table>
    """

    # ── Timestamps section ──
    time_html = f"""
    <h2>Timestamps ({_TZ_NAME})</h2>
    <div class="stats-grid" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr));">
        <div class="stat-card"><div class="stat-value" style="font-size:0.95rem;">{_to_local(created_at)}</div><div class="stat-label">Created</div></div>
        <div class="stat-card"><div class="stat-value" style="font-size:0.95rem;">{_to_local(started_at)}</div><div class="stat-label">Started</div></div>
        <div class="stat-card"><div class="stat-value" style="font-size:0.95rem;">{_to_local(completed_at)}</div><div class="stat-label">Last Call</div></div>
        <div class="stat-card"><div class="stat-value" style="font-size:0.95rem;">{html_mod.escape(duration or '—')}</div><div class="stat-label">Duration</div></div>
    </div>
    """

    # ── Summary cards ──
    summary_html = f"""
    <h2>Usage Summary</h2>
    <div class="stats-grid">
        {_stat_card(f'{total_calls:,}', 'Gemini API Calls')}
        {_stat_card(f'{ok_calls:,}', 'Successful')}
        {_stat_card(f'{fail_calls:,}', 'Failed')}
        {_stat_card(f'{total_input:,}', 'Input Tokens')}
        {_stat_card(f'{total_output:,}', 'Output Tokens')}
        {_stat_card(f'{total_thinking:,}', 'Thinking Tokens')}
        {_stat_card(f'{total_cached:,}', 'Cached Input Tokens')}
        {_stat_card(f'{total_tokens:,}', 'Total Tokens (in+out+thinking)')}
        {_stat_card(f'${total_cost:.4f}', 'Estimated Cost')}
    </div>
    <p style="font-size:0.82em;color:var(--muted);">
        <strong>Total Tokens</strong> = Input Tokens + Output Tokens + Thinking Tokens.
        Cached tokens are a subset of Input already counted there; they reduce billing but not total count.<br/>
        <strong>Estimated Cost</strong> is calculated from ApolloSG&rsquo;s pricing table and may differ from actual Google billing.
    </p>
    """

    # ── Per-call table ──
    calls_tbody = ""
    for idx, c in enumerate(calls):
        tokens = c.get("tokens", {})
        inp = tokens.get("input") or 0
        out = tokens.get("output") or 0
        think = tokens.get("thinking") or 0
        cached = tokens.get("cached_input") or 0
        cost = c.get("estimated_cost_usd") or 0
        ok = c.get("success", False)
        fail_code = c.get("failure_code") or ""
        result = "OK" if ok else f"FAIL: {fail_code}" if fail_code else "FAIL"
        result_color = "var(--green)" if ok else "var(--red)"
        purpose = c.get("purpose", "")
        model = c.get("model", "")
        ts = c.get("timestamp")

        calls_tbody += f"""<tr>
            <td>{_to_local_short(ts)}</td>
            <td style="text-align:center;">{idx + 1}</td>
            <td>{html_mod.escape(purpose)}</td>
            <td style="font-size:0.82em;">{html_mod.escape(model)}</td>
            <td style="text-align:right;">{inp:,}</td>
            <td style="text-align:right;">{out:,}</td>
            <td style="text-align:right;">{think:,}</td>
            <td style="text-align:right;">{cached:,}</td>
            <td style="text-align:right;">${cost:.4f}</td>
            <td style="color:{result_color};font-size:0.82em;">{html_mod.escape(result)}</td>
        </tr>"""

    # Totals row
    calls_tbody += f"""<tr style="font-weight:700;background:var(--card);">
        <td colspan="2" style="text-align:right;">TOTALS</td>
        <td></td><td></td>
        <td style="text-align:right;">{total_input:,}</td>
        <td style="text-align:right;">{total_output:,}</td>
        <td style="text-align:right;">{total_thinking:,}</td>
        <td style="text-align:right;">{total_cached:,}</td>
        <td style="text-align:right;">${total_cost:.4f}</td>
        <td></td>
    </tr>"""

    calls_html = f"""
    <h2>Gemini API Calls ({total_calls:,})</h2>
    <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
        Every Gemini request generated during this investigation, in chronological order.
    </p>
    <div style="overflow-x:auto;">
    <table style="font-size:0.85em;">
        <thead><tr>
            <th>Date &amp; Time</th><th>Call #</th><th>Purpose</th><th>Model</th>
            <th>Input</th><th>Output</th><th>Thinking</th><th>Cached</th>
            <th>Estimated Cost</th><th>Result</th>
        </tr></thead>
        <tbody>{calls_tbody}</tbody>
    </table>
    </div>
    """

    # Magnum DI's full transactions and Higgins Triage's rule codes: the app's DI tab shows neither.
    from services.higgins.di_record import admin_records
    di_records = await admin_records(case_id)
    triage_doc = await db.triage_investigations.find_one({"investigation_case_id": case_id}, {"_id": 0, "record": 1},
                                                         sort=[("evaluated_at", -1)])

    body = f"""
    {provenance_html}
    {_routing_drilldown_html(case)}
    {_triage_rules_html((triage_doc or {}).get("record"))}
    {_fidelity_drilldown_html(case)}
    {time_html}
    {summary_html}
    {_di_transactions_html(di_records)}
    {calls_html}
    """

    extra_css = "td, th { white-space: nowrap; }"
    await _audit_log(adm.get("email", ""), "view_investigation_drilldown", f"case_id={case_id} calls={total_calls}")
    return _shell(f"Investigation #{case_id[:8]}", "/api/admin/investigations-cost", body, admin=adm, extra_css=extra_css)



@router.get("/admin/incident-analysis/json")
async def incident_analysis_json(request: Request):
    """JSON export of investigation classification for a given period.
    
    Designed for the 17 Oct incident but works for any date range.
    Query params: period=oct17 | period=custom&start=...&end=...
    """
    adm = await _admin(request)
    if not adm:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from services.higgins.repository import dec_json

    start_utc, end_utc, period_label = _parse_filter_dates(request)

    # Aggregate by correlation_id
    usage_pipeline = [
        {"$match": {"timestamp": {"$gte": start_utc, "$lte": end_utc}}},
        {"$group": {
            "_id": "$correlation_id",
            "calls": {"$sum": 1},
            "ok": {"$sum": {"$cond": ["$success", 1, 0]}},
            "fail": {"$sum": {"$cond": ["$success", 0, 1]}},
            "input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
            "thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
            "cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
            "first_call": {"$min": "$timestamp"},
            "last_call": {"$max": "$timestamp"},
            "purposes": {"$addToSet": "$purpose"},
            "models": {"$addToSet": "$model"},
            "sources": {"$addToSet": "$extra.trigger_source"},
        }},
        {"$sort": {"cost": -1}},
    ]
    all_groups = await db.gemini_usage.aggregate(usage_pipeline).to_list(5000)

    inv_groups = [g for g in all_groups if (g["_id"] or "").startswith("case-")]
    non_inv_groups = [g for g in all_groups if not (g["_id"] or "").startswith("case-")]

    case_ids = [g["_id"][5:] for g in inv_groups]
    cases_map = {}
    jobs_map = {}
    if case_ids:
        async for c in db.investigation_cases.find({"case_id": {"$in": case_ids}}, {"_id": 0}):
            cases_map[c["case_id"]] = c
        async for j in db.investigation_jobs.find(
            {"case_id": {"$in": case_ids}},
            {"_id": 0, "case_id": 1, "source": 1, "status": 1, "auto_resume_count": 1}
        ).sort("created_at", 1):
            if j["case_id"] not in jobs_map:
                jobs_map[j["case_id"]] = j

    rows = []
    by_initiator = {}
    for g in inv_groups:
        case_id = g["_id"][5:]
        case = cases_map.get(case_id, {})
        job = jobs_map.get(case_id, {})

        dev_profile = None
        if case.get("device_profile_ciphertext"):
            try:
                dev_profile = dec_json(case["device_profile_ciphertext"])
            except Exception:
                pass
        device = _device_name(dev_profile)
        gate_str = _gate_display(case.get("gates"))
        source = job.get("source") or (g["sources"][0] if g["sources"] else None)
        init_label = _initiator_label(source)
        init_cat = _initiator_category(source)
        env = _env_label(g["models"][0] if g["models"] else None)
        resumed = (job.get("auto_resume_count") or 0) > 0
        total_tokens = g["input_tokens"] + g["output_tokens"] + g["thinking_tokens"]

        row = {
            "case_id": case_id,
            "device": device,
            "gate": gate_str,
            "initiated_by": init_label,
            "category": init_cat,
            "source_raw": source,
            "environment": env,
            "calls": g["calls"],
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(g["cost"], 6),
            "first_call": g["first_call"].isoformat() if g["first_call"] else None,
            "last_call": g["last_call"].isoformat() if g["last_call"] else None,
            "resumed": resumed,
            "status": case.get("status", "unknown"),
        }
        rows.append(row)

        b = by_initiator.setdefault(init_cat, {"investigations": 0, "calls": 0, "tokens": 0, "cost": 0.0})
        b["investigations"] += 1
        b["calls"] += g["calls"]
        b["tokens"] += total_tokens
        b["cost"] += g["cost"]

    # Ensure all categories present
    for cat in ["User — Check", "ApolloSG — Mailbox Monitor", "ApolloSG — Automatic",
                 "System — Test/Validation", "Recovery/Resume", "Unknown/Unattributed"]:
        by_initiator.setdefault(cat, {"investigations": 0, "calls": 0, "tokens": 0, "cost": 0.0})

    result = {
        "period": {"start": start_utc.isoformat(), "end": end_utc.isoformat(), "label": period_label},
        "summary": {
            "total_correlation_ids": len(all_groups),
            "investigation_cases": len(inv_groups),
            "non_investigation_correlation_ids": len(non_inv_groups),
            "total_calls": sum(g["calls"] for g in all_groups),
            "total_investigation_calls": sum(g["calls"] for g in inv_groups),
            "total_estimated_cost_usd": round(sum(g["cost"] for g in all_groups), 6),
        },
        "by_initiator": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_initiator.items())},
        "investigations": rows,
        "non_investigation": [
            {
                "correlation_id": g["_id"],
                "purposes": g["purposes"],
                "sources": [s for s in g["sources"] if s],
                "calls": g["calls"],
                "total_tokens": g["input_tokens"] + g["output_tokens"] + g["thinking_tokens"],
                "estimated_cost_usd": round(g["cost"], 6),
            }
            for g in non_inv_groups
        ],
    }

    await _audit_log(adm.get("email", ""), "export_incident_analysis_json", f"period={period_label}")
    return JSONResponse(result)




# ── Triage Dashboard ─────────────────────────────────────────────────────────

async def _limited_by_cause_html(request: Request) -> str:
    """Triage outcomes and Limited-by-cause from device + server telemetry. Real phones only by default, so
    web previews and mock adapters (test traffic) don't skew the picture; ?scope=all includes them."""
    from services.triage.telemetry import CAUSE_LABELS, limited_by_cause
    days = 7 if request.query_params.get("days") == "7" else 30
    phones_only = request.query_params.get("scope") != "all"
    stats = await limited_by_cause(datetime.now(timezone.utc) - timedelta(days=days), phones_only=phones_only)
    total, outcomes = stats["total"], stats["outcomes"]
    limited = outcomes["LIMITED_UNABLE_TO_DETERMINE"]

    def pct(n: int, of: int) -> str:
        return f"{n / of * 100:.1f}%" if of else "—"

    cause_rows = "".join(
        f"<tr><td>{html_mod.escape(CAUSE_LABELS.get(cause, cause))}<div style='font-size:0.78em;color:var(--muted);'><code>{html_mod.escape(cause)}</code></div></td>"
        f"<td>{html_mod.escape(source or '—')}</td><td style='text-align:right;'>{n:,}</td><td style='text-align:right;'>{pct(n, limited)}</td></tr>"
        for cause, source, n in stats["by_cause"])
    retry_rows = "".join(f"<tr><td><code>{html_mod.escape(k)}</code></td><td style='text-align:right;'>{v:,}</td></tr>"
                         for k, v in sorted(stats["lookup_retries"].items()))
    incomplete_rows = "".join(
        f"<tr><td><code>{html_mod.escape(code)}</code></td><td>{html_mod.escape(outcome)}</td><td style='text-align:right;'>{n:,}</td></tr>"
        for code, outcome, n in stats.get("incomplete", []))

    def link(label: str, d: int, scope: str) -> str:
        active = d == days and (scope == "phones") == phones_only
        style = "font-weight:700;" if active else ""
        return f'<a href="/api/admin/triage?days={d}&scope={scope}" style="{style}" data-testid="triage-cause-{scope}-{d}">{label}</a>'

    return f"""
    <h2 data-testid="triage-limited-by-cause">Limited by cause</h2>
    <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
        Every Triage outcome reports its cause codes (no content). Showing the last {days} days ·
        {"real phones only (iOS/Android, not mock)" if phones_only else "all traffic, including web previews and test devices"}.
        {link("Phones · 30 days", 30, "phones")} · {link("Phones · 7 days", 7, "phones")} ·
        {link("All traffic · 30 days", 30, "all")} · {link("All traffic · 7 days", 7, "all")}
    </p>
    <table data-testid="triage-outcome-totals">
        <thead><tr><th>Outcome</th><th>Count</th><th>Share</th></tr></thead>
        <tbody>
            <tr><td>No threat identified</td><td style="text-align:right;">{outcomes['NO_THREAT_IDENTIFIED']:,}</td><td style="text-align:right;">{pct(outcomes['NO_THREAT_IDENTIFIED'], total)}</td></tr>
            <tr><td>Possible threat identified</td><td style="text-align:right;">{outcomes['POSSIBLE_THREAT_IDENTIFIED']:,}</td><td style="text-align:right;">{pct(outcomes['POSSIBLE_THREAT_IDENTIFIED'], total)}</td></tr>
            <tr><td>Limited / unable to determine</td><td style="text-align:right;">{limited:,}</td><td style="text-align:right;">{pct(limited, total)}</td></tr>
        </tbody>
    </table>
    <table data-testid="triage-limited-causes" style="margin-top:12px;">
        <thead><tr><th>Cause</th><th>Source type</th><th>Limited results</th><th>Share of Limited</th></tr></thead>
        <tbody>{cause_rows or '<tr><td colspan="4" style="color:var(--muted);">No Limited results reported in this period</td></tr>'}</tbody>
    </table>
    <p style="font-size:0.78em;color:var(--muted);">A result with two causes is counted once under each.</p>
    <h3 style="margin-top:12px;">Reputation lookup retries</h3>
    <table data-testid="triage-lookup-retries">
        <thead><tr><th>Lookup outcome</th><th>Count</th></tr></thead>
        <tbody>{retry_rows or '<tr><td colspan="2" style="color:var(--muted);">No lookups reported in this period</td></tr>'}</tbody>
    </table>
    <h3 style="margin-top:12px;">Checks that didn't complete</h3>
    <p style="font-size:0.78em;color:var(--muted);">Any outcome. A No Threat result with one of these is shown as "No threat found by available checks".</p>
    <table data-testid="triage-incomplete-checks">
        <thead><tr><th>Check and how it failed</th><th>Outcome</th><th>Count</th></tr></thead>
        <tbody>{incomplete_rows or '<tr><td colspan="3" style="color:var(--muted);">Every check completed in this period</td></tr>'}</tbody>
    </table>"""

@router.get("/admin/triage", response_class=HTMLResponse)
async def triage_dashboard(request: Request):
    """Higgins Triage performance dashboard — screening cost KPI tracker."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    from services.triage_engine import get_triage_stats, COLLECTION as TRIAGE_COLLECTION
    from services.higgins.provider import get_provider_mode

    # Get stats for different periods
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    stats_today = await get_triage_stats(start=today_start, end=now)
    stats_week = await get_triage_stats(start=week_ago, end=now)
    stats_all = await get_triage_stats()

    # Recent triage decisions
    recent = await db[TRIAGE_COLLECTION].find(
        {"record_type": "decision"},
        {"_id": 0},
    ).sort("decided_at", -1).limit(50).to_list(50)

    def _kpi_html(stats: dict, label: str) -> str:
        """Render a KPI card for a period."""
        avg = stats["avg_cost_per_item"]
        kpi_met = stats["kpi_met"]
        kpi_cls = "color:var(--green);" if kpi_met else "color:var(--red);"
        items = stats["items_screened"]
        d = stats["distribution"]
        prevented = stats.get("gemini_calls_prevented", 0)
        return f"""
        <div style="background:var(--card);border-radius:10px;padding:16px;flex:1;min-width:220px;">
            <h3 style="margin:0 0 8px;">{label}</h3>
            <div style="font-size:2em;font-weight:700;{kpi_cls}">${avg:.6f}</div>
            <div style="font-size:0.82em;color:var(--muted);margin-top:4px;">avg cost/item (target: $0 — Triage never calls Gemini)</div>
            <div style="margin-top:12px;font-size:0.88em;">
                <div>Items screened: <strong>{items:,}</strong></div>
                <div>No threat identified: <strong>{stats['outcomes']['NO_THREAT_IDENTIFIED']:,}</strong> ({d['no_threat_pct']}%)</div>
                <div>Limited / unable to determine: <strong>{stats['outcomes']['LIMITED_UNABLE_TO_DETERMINE']:,}</strong> ({d['limited_pct']}%)</div>
                <div>Possible threat → Magnum DI: <strong>{stats['magnum_di_escalations']:,}</strong> ({d['possible_threat_pct']}%)</div>
                <div>Cached: <strong>{stats['cached_resolutions']:,}</strong></div>
                <div>Gemini calls prevented: <strong>{prevented:,}</strong></div>
                <div>Total cost: <strong>${stats['total_cost_usd']:.6f}</strong></div>
            </div>
        </div>"""

    cards_html = f"""
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px;">
        {_kpi_html(stats_today, "Today")}
        {_kpi_html(stats_week, "Last 7 Days")}
        {_kpi_html(stats_all, "All Time")}
    </div>"""

    # Model config
    mode = get_provider_mode()
    config_html = f"""
    <h2>Triage Configuration</h2>
    <table>
        <tbody>
            <tr><td>Provider Mode</td><td><code>{html_mod.escape(mode)}</code></td></tr>
            <tr><td>KPI Target</td><td>&le; $0.001 avg/item</td></tr>
        </tbody>
    </table>"""

    # Recent decisions table
    recent_tbody = ""
    for r in recent:
        decided = r.get("decided_at")
        decided_str = _to_local_short(decided) if decided else "—"
        tier_val = r.get("tier", "?")
        verdict_val = r.get("verdict", "?")
        v_color = {"SAFE": "var(--green)", "SUSPICIOUS": "var(--red)", "UNCERTAIN": "var(--yellow)"}.get(verdict_val, "var(--muted)")
        cost = r.get("cost_usd", 0)
        cached = r.get("cached", False)
        src = r.get("source_type", "—")
        reason = html_mod.escape((r.get("reason") or "")[:100])
        recent_tbody += f"""<tr>
            <td>{decided_str}</td>
            <td>Tier {tier_val}</td>
            <td style="color:{v_color};font-weight:600;">{verdict_val}</td>
            <td>{src}</td>
            <td style="text-align:right;">${cost:.6f}</td>
            <td>{'Yes' if cached else 'No'}</td>
            <td style="font-size:0.82em;">{reason}</td>
        </tr>"""

    recent_html = f"""
    <h2>Recent Triage Decisions (Last 50)</h2>
    <div style="overflow-x:auto;max-height:500px;overflow-y:auto;">
    <table>
        <thead><tr>
            <th>Time</th><th>Tier</th><th>Verdict</th><th>Source</th>
            <th>Cost</th><th>Cached</th><th>Reason</th>
        </tr></thead>
        <tbody>{recent_tbody or '<tr><td colspan="7" style="color:var(--muted);">No triage decisions yet</td></tr>'}</tbody>
    </table>
    </div>"""

    # Verdict distribution
    v_all = stats_all["verdicts"]
    verdict_html = f"""
    <h2>Verdict Distribution (All Time)</h2>
    <table>
        <thead><tr><th>Verdict</th><th>Count</th><th>Percentage</th></tr></thead>
        <tbody>
            <tr><td style="color:var(--green);">SAFE</td><td style="text-align:right;">{v_all['SAFE']:,}</td><td style="text-align:right;">{v_all['SAFE']/max(stats_all['items_screened'],1)*100:.1f}%</td></tr>
            <tr><td style="color:var(--red);">SUSPICIOUS</td><td style="text-align:right;">{v_all['SUSPICIOUS']:,}</td><td style="text-align:right;">{v_all['SUSPICIOUS']/max(stats_all['items_screened'],1)*100:.1f}%</td></tr>
            <tr><td style="color:var(--yellow);">UNCERTAIN</td><td style="text-align:right;">{v_all['UNCERTAIN']:,}</td><td style="text-align:right;">{v_all['UNCERTAIN']/max(stats_all['items_screened'],1)*100:.1f}%</td></tr>
        </tbody>
    </table>"""

    # Provider utilisation table
    prov_util = stats_all.get("provider_utilisation", {})
    prov_tbody = ""
    for prov, count in sorted(prov_util.items(), key=lambda x: x[1], reverse=True):
        prov_tbody += f"<tr><td><code>{html_mod.escape(prov)}</code></td><td style='text-align:right;'>{count:,}</td></tr>"

    provider_html = f"""
    <h2>Provider Utilisation (All Time)</h2>
    <p style="font-size:0.82em;color:var(--muted);margin-bottom:8px;">
        Which specialist providers contributed to triage decisions.
        Higher counts = provider evidence is actively preventing unnecessary Gemini calls.
    </p>
    <table>
        <thead><tr><th>Provider</th><th>Decisions Contributed To</th></tr></thead>
        <tbody>{prov_tbody or '<tr><td colspan="2" style="color:var(--muted);">No provider data yet</td></tr>'}</tbody>
    </table>"""

    body = f"""
    <h1>Higgins Triage</h1>
    <p style="font-size:0.88em;color:var(--muted);margin-bottom:16px;">
        3-tier cost-optimised screening. Target: &le; $0.001 average cost per automatically screened item.
    </p>
    {await _limited_by_cause_html(request)}
    {cards_html}
    {config_html}
    {provider_html}
    {verdict_html}
    {recent_html}
    """
    return _shell("Triage", "/api/admin/triage", body, admin=adm)


# ── System ───────────────────────────────────────────────────────────────────

@router.get("/admin/system", response_class=HTMLResponse)
async def system_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    be = await check_backend()
    db_health = await check_database()
    models = await ai_settings.selection()

    try:
        migration_count = await db.apollo_migrations.count_documents({})
    except Exception:
        migration_count = "?"

    body = f"""
    <h2>Backend</h2>
    {_status_card("Backend Process", be['status'], be.get('detail',''))}
    <div class="stats-grid">
        {_stat_card(f"{be.get('uptime_hours', 0):.1f}h", "Uptime")}
        {_stat_card(str(be.get('pid','?')), "PID")}
        {_stat_card(str(migration_count), "Migrations Applied")}
    </div>

    <h2>Database</h2>
    {_status_card("MongoDB", db_health['status'], db_health.get('detail',''))}
    <div class="stats-grid">
        {_stat_card(str(db_health.get('collections','?')), "Collections")}
        {_stat_card(f"{db_health.get('data_size_mb','?')} MB", "Data Size")}
        {_stat_card(f"{db_health.get('storage_size_mb','?')} MB", "Storage Size")}
        {_stat_card(str(db_health.get('indexes','?')), "Indexes")}
        {_stat_card(f"{db_health.get('objects', 0):,}" if isinstance(db_health.get('objects'), int) else '?', "Documents")}
    </div>

    <h2>Environment</h2>
    <table>
        {_models_rows(models)}
        <tr><td>Admin Email</td><td><code>{html_mod.escape(ADMIN_EMAIL or 'not set')}</code></td></tr>
        <tr><td>Cookie Secure</td><td><code>{os.getenv('COOKIE_SECURE','false')}</code></td></tr>
    </table>
    """
    return _shell("System", "/api/admin/system", body, admin=adm)


# ── Knowledge Base (Tavily maintenance) ──────────────────────────────────────

def _kb_when(value) -> str:
    return _to_local(value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value) if value else "—"


@router.get("/admin/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import apollo_kb
    from services.kb_sources import TIER_LABEL
    state = await apollo_kb.status()
    esc = html_mod.escape
    total = sum(row["entries"] for row in state["breakdown"])
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for row in state["breakdown"]:
        by_kind[row.get("kind") or "?"] = by_kind.get(row.get("kind") or "?", 0) + row["entries"]
        by_status[row.get("status") or "current"] = by_status.get(row.get("status") or "current", 0) + row["entries"]
    rows = "".join(f"<tr><td>{esc(str(r.get('kind')))}</td><td>{esc(TIER_LABEL.get(r.get('tier') or '', r.get('tier') or '—'))}</td>"
                   f"<td>{esc(str(r.get('category') or '—'))}</td><td>{esc(str(r.get('status') or 'current'))}</td>"
                   f"<td style='text-align:right;'>{r['entries']:,}</td><td style='text-align:right;'>{r['hits']:,}</td></tr>" for r in state["breakdown"])
    runs = "".join(
        f"<tr><td>{_kb_when(r.get('started_at'))}</td><td>{esc(r.get('trigger', ''))}</td>"
        f"<td>{esc(r.get('status', ''))}{(' — ' + esc(r['error'])) if r.get('error') else ''}</td>"
        f"<td style='text-align:right;'>{r.get('searches', 0)}</td><td>{esc(', '.join(f'{k} {v}' for k, v in (r.get('counts') or {}).items()) or '—')}</td>"
        f"<td style='text-align:right;'>{r.get('alerts_published', 0)}</td><td style='text-align:right;'>{r.get('learn_published', 0)} new / {r.get('learn_updated', 0)} updated</td>"
        f"<td>{esc(', '.join(f'{k} {v}' for k, v in (r.get('rejections') or {}).items()) or '—')}</td></tr>" for r in state["runs"])
    rejected = "".join(f"<tr><td>{_kb_when(r.get('at'))}</td><td>{esc(r.get('reason', ''))}</td><td style='word-break:break-all;'>{esc(r.get('url', ''))}</td></tr>"
                       for r in state["rejections"])
    notice = {"started": '<div class="alert alert-ok">Refresh started. Reload this page in a few minutes to see the run.</div>',
              "busy": '<div class="alert alert-warning">A refresh is already running.</div>'}.get(request.query_params.get("refresh", ""), "")
    configured = '<span style="color:var(--green);">Tavily key set</span>' if state["configured"] else '<span style="color:var(--red);">Tavily key missing</span>'
    body = f"""
    <h2>ApolloSG Knowledge Base</h2>
    {notice}
    <p style="font-size:0.9em;color:var(--muted);">Tavily finds and re-reads pages on trusted sources once a week. Each page keeps its source, authority tier,
    jurisdiction and dates; changed pages are versioned (old versions kept as Superseded) and pages a source stops serving become Historical.
    New material goes live after the automatic checks. Tavily is never used by Magnum DI or for live questions.</p>
    <div class="stats-grid">
        {_stat_card(f"{total:,}", "KB entries")}
        {_stat_card(f"{by_kind.get('researched', 0):,}", "Researched pages")}
        {_stat_card(f"{state['history']:,}", "Superseded versions")}
        {_stat_card(f"{by_status.get('historical', 0):,}", "Historical")}
        {_stat_card(f"{state['tavilyCalls30d']:,}", "Tavily calls (30 days)")}
    </div>
    <div class="topbar-row">
        <div style="font-size:0.88em;">{configured} &middot; Next weekly run: {_kb_when(state['nextRunAt'])}</div>
        <form method="post" action="/api/admin/knowledge/refresh" style="margin:0;"><button class="btn">Refresh now</button></form>
    </div>
    <h2>What the KB holds</h2>
    <table><tr><th>Kind</th><th>Authority</th><th>Category</th><th>Status</th><th>Entries</th><th>Times used by Higgins</th></tr>{rows or '<tr><td colspan="6">Empty</td></tr>'}</table>
    <h2>Recent runs</h2>
    <table><tr><th>Started</th><th>Trigger</th><th>Status</th><th>Searches</th><th>Pages</th><th>Scam Alerts</th><th>Learn articles</th><th>Rejected</th></tr>{runs or '<tr><td colspan="8">No runs yet</td></tr>'}</table>
    <h2>Recently rejected by the automatic checks</h2>
    <table><tr><th>When</th><th>Reason</th><th>Page</th></tr>{rejected or '<tr><td colspan="3">None</td></tr>'}</table>
    {await _threat_feeds_section(request.query_params.get("feeds", ""))}
    """
    return _shell("Knowledge Base", "/api/admin/knowledge", body, admin=adm)


_FEED_HEALTH_COLOUR = {"healthy": "var(--green)", "stale": "#d29922", "failing": "var(--red)"}
_FEED_STORE = {"indicators": "Threat indicators (link, email and phone checks)", "knowledge": "ApolloSG KB (technical knowledge)",
               "enrich": "Adds severity to the KB's exploited vulnerabilities"}


async def _threat_feeds_section(notice_key: str) -> str:
    """Free threat feeds (services/threat_feeds.py): health, entries, last run, and Refresh now (all or one)."""
    from services import threat_feeds
    esc = html_mod.escape
    notice = {"started": '<div class="alert alert-ok" data-testid="threat-feeds-started">Refresh started. Reload this page in a few minutes to see the results.</div>',
              "busy": '<div class="alert alert-warning" data-testid="threat-feeds-busy">A threat feed refresh is already running.</div>'}.get(notice_key, "")
    rows = []
    for row in await threat_feeds.status():
        feed, state, last = row["feed"], row["state"], row["last_run"] or {}
        health = row["health"]
        counts = f" · +{last.get('added', 0):,} / −{last.get('removed', 0):,}" if last.get("status") == "success" else ""
        run_text = (f"{_kb_when(last.get('started_at'))} · {esc(last.get('trigger', ''))} · {esc(last.get('status', ''))}{counts}"
                    if last else "Never run")
        error = f"<br><span style='color:var(--red);font-size:0.85em;'>{esc(row['error'])}</span>" if row["error"] else ""
        rows.append(
            f"<tr data-testid='threat-feed-row-{feed.feed_id}'><td><b>{esc(feed.publisher)}</b><br><span style='font-size:0.85em;color:var(--muted);'>{esc(feed.name)}"
            f" · <a href='{esc(feed.terms)}' target='_blank' rel='noopener'>terms</a></span></td>"
            f"<td style='font-size:0.85em;'>{esc(_FEED_STORE[feed.store])}</td>"
            f"<td data-testid='threat-feed-health-{feed.feed_id}' style='color:{_FEED_HEALTH_COLOUR[health]};font-weight:600;'>{health.title()}{error}</td>"
            f"<td>{_kb_when(state.get('last_success_at'))}</td>"
            f"<td style='text-align:right;' data-testid='threat-feed-current-{feed.feed_id}'>{row['current']:,}</td>"
            f"<td style='font-size:0.85em;'>{run_text}</td>"
            f"<td><form method='post' action='/api/admin/threat-feeds/refresh' style='margin:0;'><input type='hidden' name='feed_id' value='{esc(feed.feed_id)}'>"
            f"<button class='btn' data-testid='threat-feed-refresh-{feed.feed_id}'>Refresh</button></form></td></tr>")
    return f"""
    <h2 id="threat-feeds" data-testid="threat-feeds-heading">Free threat feeds</h2>
    {notice}
    <p style="font-size:0.9em;color:var(--muted);">Free, public lists and catalogues, stored in ApolloSG's own threat indicators and KB with their source,
    reference, licence and dates. Each feed refreshes once a day; a failed refresh is retried every 2 hours. An entry a successful refresh no longer lists
    stops counting; a download with under half of last time's entries is refused. A list that isn't current is reported as not checked, never as clear.</p>
    <div class="topbar-row">
        <div style="font-size:0.88em;">{len(threat_feeds.FEEDS)} feeds &middot; no paid sources</div>
        <form method="post" action="/api/admin/threat-feeds/refresh" style="margin:0;"><button class="btn" data-testid="threat-feeds-refresh-all">Refresh now</button></form>
    </div>
    <table data-testid="threat-feeds-table"><tr><th>Feed</th><th>Goes into</th><th>Health</th><th>Last success</th><th>Current entries</th><th>Last run</th><th></th></tr>
    {''.join(rows)}</table>"""


_KB_TASKS: set = set()  # keeps a manual refresh alive until it finishes


# ── Intelligence Reuse: what Apollo reused instead of paying to ask again ─────
_REUSE_SITES = {"higgins_general_question": "Ask Higgins general question (ApolloSG's KB; no AI call)", "tc_flyby_search": "TC FlyBy targeted search (Brave web search; no AI call)",
                "ipqs_phone": "Phone reputation (IPQualityScore)", "ipqs_url": "Link reputation (IPQualityScore)", "rdap": "Domain registration (RDAP)"}


def _reuse_totals(rows: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        for event, n in (row.get("counts") or {}).items():
            totals[event] = totals.get(event, 0) + n
    return totals


@router.get("/admin/intel-reuse", response_class=HTMLResponse)
async def intel_reuse_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import reusable_intel
    esc = html_mod.escape
    rows = await reusable_intel.metrics(14)
    totals = _reuse_totals(rows)
    events = reusable_intel.EVENTS
    by_site: dict[str, list[dict]] = {}
    by_day: dict[str, list[dict]] = {}
    for row in rows:
        by_site.setdefault(row["site"], []).append(row)
        by_day.setdefault(row["day"], []).append(row)
    head = "".join(f"<th>{esc(e.replace('_', ' '))}</th>" for e in events)
    cells = lambda t: "".join(f"<td style='text-align:right;'>{t.get(e, 0):,}</td>" for e in events)  # noqa: E731
    site_rows = "".join(f"<tr><td>{esc(_REUSE_SITES.get(site, site))}</td>{cells(_reuse_totals(items))}</tr>" for site, items in sorted(by_site.items()))
    day_rows = "".join(f"<tr><td>{esc(day)}</td>{cells(_reuse_totals(items))}</tr>" for day, items in sorted(by_day.items(), reverse=True))
    inventory = "".join(
        f"<tr><td>{esc(str(r['_id'].get('provider')))}</td><td>{esc(str(r['_id'].get('source_type')))}</td>"
        f"<td>{'AI-derived' if r['_id'].get('ai') else 'Provider data'}</td><td style='text-align:right;'>{r['records']:,}</td>"
        f"<td style='text-align:right;'>{r['fresh']:,}</td><td style='text-align:right;'>{r['records'] - r['fresh']:,}</td>"
        f"<td style='text-align:right;'>{r['hits']:,}</td></tr>" for r in await reusable_intel.inventory())
    ttl_rows = "".join(f"<tr><td>{esc(k.replace('_', ' '))}</td><td>{esc(_ttl_words(v))}</td></tr>" for k, v in reusable_intel.TTL.items())
    avoided, required = totals.get("external_call_avoided", 0), totals.get("external_call_required", 0)
    body = f"""
    <h2 data-testid="intel-reuse-heading">Intelligence Reuse</h2>
    <p style="font-size:0.9em;color:var(--muted);">Before a paid external call, Apollo checks its knowledge base, then results it already bought that are
    still current. The sufficiency check answers KNOWN (reuse, no call), PARTIAL (stale, incomplete or contradicted: call as before) or UNKNOWN (call as
    before). Reused results are never promoted into the knowledge base, AI-derived ones stay labelled as AI-derived, and private case evidence is never stored.
    Counts only; no content is recorded.</p>
    <div class="stats-grid">
        {_stat_card(f"{avoided:,}", "Calls avoided (14 days)")}
        {_stat_card(f"{required:,}", "Calls still needed (14 days)")}
        {_stat_card(f"{(avoided / (avoided + required) * 100) if (avoided + required) else 0:.0f}%", "Share avoided")}
        {_stat_card(f"{totals.get('cache_write', 0):,}", "Results saved for reuse")}
        {_stat_card(f"{totals.get('cache_expired', 0):,}", "Expired, checked again")}
    </div>
    <h2>By call site (14 days)</h2>
    <table data-testid="intel-reuse-sites"><tr><th>Call site</th>{head}</tr>{site_rows or f'<tr><td colspan="{len(events) + 1}">No activity yet</td></tr>'}</table>
    <h2>By day</h2>
    <table data-testid="intel-reuse-days"><tr><th>Day</th>{head}</tr>{day_rows or f'<tr><td colspan="{len(events) + 1}">No activity yet</td></tr>'}</table>
    <h2>What the reusable cache holds</h2>
    <table data-testid="intel-reuse-inventory"><tr><th>Provider</th><th>Process</th><th>Kind</th><th>Records</th><th>Current</th><th>Expired (history only)</th><th>Times reused</th></tr>
    {inventory or '<tr><td colspan="7">Empty</td></tr>'}</table>
    <p style="font-size:0.82em;color:var(--muted);">Phone, URL and domain lookups keep their own established caches; they are counted here and their
    freshness comes from the same table below.</p>
    <h2>How long a result counts as current</h2>
    <table data-testid="intel-reuse-ttl"><tr><th>Information</th><th>Current for</th></tr>{ttl_rows}</table>
    """
    return _shell("Intelligence Reuse", "/api/admin/intel-reuse", body, admin=adm)


def _ttl_words(value) -> str:
    hours = int(value.total_seconds() // 3600)
    return f"{hours // 24} days" if hours % 24 == 0 and hours >= 48 else f"{hours} hours"


@router.post("/admin/knowledge/refresh")
async def knowledge_refresh(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    import asyncio
    from services import apollo_kb
    busy = await db.apollo_kb_state.find_one({"_id": "lock", "held_until": {"$gt": now_utc()}}, {"_id": 1})
    if not busy:
        task = asyncio.create_task(apollo_kb.run("manual"))
        _KB_TASKS.add(task)
        task.add_done_callback(_KB_TASKS.discard)
        await _audit_log(adm.get("email", ""), "knowledge_refresh", "manual ApolloSG KB refresh")
    return RedirectResponse(f"/api/admin/knowledge?refresh={'busy' if busy else 'started'}", status_code=303)


@router.post("/admin/threat-feeds/refresh")
async def threat_feeds_refresh(request: Request):
    """Refresh now: every free threat feed, or the one named by `feed_id`, in the background."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    import asyncio
    from urllib.parse import parse_qs
    from services import threat_feeds
    feed_id = (parse_qs((await request.body()).decode("utf-8", "replace")).get("feed_id") or [""])[0] or None
    if feed_id and feed_id not in threat_feeds.BY_ID:
        return RedirectResponse("/api/admin/knowledge#threat-feeds", status_code=303)
    busy = await db.apollo_kb_state.find_one({"_id": threat_feeds.LOCK_ID, "held_until": {"$gt": now_utc()}}, {"_id": 1})
    if not busy:
        task = asyncio.create_task(threat_feeds.run(feed_id, trigger="manual"))
        _KB_TASKS.add(task)
        task.add_done_callback(_KB_TASKS.discard)
        await _audit_log(adm.get("email", ""), "threat_feeds_refresh", f"manual refresh: {feed_id or 'all free threat feeds'}")
    return RedirectResponse(f"/api/admin/knowledge?feeds={'busy' if busy else 'started'}#threat-feeds", status_code=303)


# ── Official Organisation Directory (services/org_directory.py) and ApolloSG's observed patterns ──

_ORG_STATUS = {"confirmed": ("Confirmed", "var(--green)"), "curated": ("Shipped", "var(--green)"), "not_found": ("Not on its pages", "var(--red)"),
               "unchecked": ("Not checked yet", "var(--muted)"), "unconfirmed": ("Not confirmed", "#d29922"), "read": ("Read", "var(--green)"),
               "missing": ("Page gone", "var(--red)"), "unreadable": ("Couldn't read", "#d29922")}


def _org_pill(item: dict, now) -> str:
    from services import org_directory
    status = item.get("status") or "unchecked"
    if status == "confirmed" and not org_directory._fresh(item, now):
        status = "unconfirmed"
    label, colour = _ORG_STATUS.get(status, (status, "var(--muted)"))
    return f"<span style='color:{colour};font-size:0.85em;'>{html_mod.escape(label)}</span>"


def _org_row(doc: dict, now) -> str:
    from services import org_directory
    esc = html_mod.escape
    key = esc(doc["key"])
    domains = "<br>".join(f"{esc(d['domain'])} {_org_pill(d, now)}" for d in doc.get("domains") or [])
    phones = "<br>".join(f"{esc(p['number'])}{(' · ' + esc(p['label'])) if p.get('label') else ''} {_org_pill(p, now)}" for p in doc.get("phones") or []) or "—"
    emails = "<br>".join(f"{esc(e['address'])} {_org_pill(e, now)}" for e in doc.get("emails") or []) or "—"
    sources = "<br>".join(f"<a href='{esc(s['url'])}' target='_blank' rel='noopener'>{esc(s['url'][:60])}</a> {_org_pill(s, now)}"
                          + (f" <span style='font-size:0.8em;color:var(--muted);'>(archived copy)</span>" if s.get("via") == "internet_archive" else "")
                          for s in doc.get("sources") or [])
    return (f"<tr data-testid='org-row-{key}'><td><b>{esc(doc['name'])}</b><br><span style='font-size:0.8em;color:var(--muted);'>"
            f"{esc(org_directory.SECTORS.get(doc.get('sector') or '', '—'))} · {'edited by admin' if doc.get('origin') == 'admin' else 'shipped'}</span></td>"
            f"<td style='font-size:0.85em;'>{domains}</td><td style='font-size:0.85em;'>{phones}</td><td style='font-size:0.85em;'>{emails}</td>"
            f"<td style='font-size:0.8em;word-break:break-all;'>{sources}</td><td style='font-size:0.85em;'>{_kb_when(doc.get('last_verified_at'))}</td>"
            f"<td><a class='btn btn-sm' href='/api/admin/org-directory?edit={key}#org-form' data-testid='org-edit-{key}'>Edit</a>"
            f"<form method='post' action='/api/admin/org-directory/verify' style='margin:4px 0 0;'><input type='hidden' name='key' value='{key}'>"
            f"<button class='btn btn-sm' data-testid='org-verify-{key}'>Re-check</button></form></td></tr>")


def _org_form(values: dict, problems: list[str], editing: bool) -> str:
    from services import org_directory
    esc = html_mod.escape
    v = lambda k: esc(values.get(k) or "")  # noqa: E731
    sectors = "".join(f"<option value='{k}'{' selected' if values.get('sector') == k else ''}>{esc(label)}</option>" for k, label in org_directory.SECTORS.items())
    errors = ("<div class='alert alert-critical' data-testid='org-form-errors'><ul style='margin:0 0 0 18px;'>"
              + "".join(f"<li>{esc(p)}</li>" for p in problems) + "</ul></div>") if problems else ""
    archive = (f"<form method='post' action='/api/admin/org-directory/archive' style='margin-top:8px;' "
               f"onsubmit=\"return confirm('Remove {v('name')} from the directory? Checks stop using it straight away.');\">"
               f"<input type='hidden' name='key' value='{v('key')}'><button class='btn btn-danger' data-testid='org-archive'>Remove from directory</button></form>") if editing else ""
    return f"""<h2 id="org-form">{'Edit ' + v('name') if editing else 'Add an organisation'}</h2>{errors}
    <form method="post" action="/api/admin/org-directory/save" class="org-form" data-testid="org-form">
      <input type="hidden" name="key" value="{v('key')}">
      <label>Name<input name="name" value="{v('name')}" required maxlength="80" data-testid="org-name"></label>
      <label>Sector<select name="sector" data-testid="org-sector">{sectors}</select></label>
      <label>Other names people use (comma separated)<input name="aliases" value="{v('aliases')}" data-testid="org-aliases"></label>
      <label>Its own domains (one per line)<textarea name="domains" rows="2" required data-testid="org-domains">{v('domains')}</textarea></label>
      <label>Phone numbers, one per line as <code>number | what it's for</code><textarea name="phones" rows="3" data-testid="org-phones">{v('phones')}</textarea></label>
      <label>Email addresses, one per line as <code>address | what it's for</code><textarea name="emails" rows="2" data-testid="org-emails">{v('emails')}</textarea></label>
      <label>Official source pages (one https link per line, on its own domains or an official authority's site)<textarea name="sources" rows="3" required data-testid="org-sources">{v('sources')}</textarea></label>
      <button class="btn" type="submit" data-testid="org-save">Save</button>
      {'<a class="btn btn-sm" href="/api/admin/org-directory#org-form">Cancel</a>' if editing else ''}
    </form>{archive}
    <p style="font-size:0.85em;color:var(--muted);">Changes take effect straight away. A phone number or email address counts as official only once
    ApolloSG finds it on one of the source pages (re-checked weekly); until then it shows "Not checked yet" and checks don't use it.</p>"""


def _org_values(doc: dict | None) -> dict:
    if not doc:
        return {"sector": "bank"}
    return {"key": doc["key"], "name": doc["name"], "sector": doc.get("sector"), "aliases": ", ".join(doc.get("aliases") or []),
            "domains": "\n".join(d["domain"] for d in doc.get("domains") or []),
            "phones": "\n".join(f"{p['number']} | {p.get('label') or ''}".rstrip(" |") for p in doc.get("phones") or []),
            "emails": "\n".join(f"{e['address']} | {e.get('label') or ''}".rstrip(" |") for e in doc.get("emails") or []),
            "sources": "\n".join(s["url"] for s in doc.get("sources") or [])}


async def _observed_section() -> str:
    from services import observed_intel
    esc = html_mod.escape
    s = await observed_intel.summary()
    kinds = {"domain": "Website", "phone": "Phone number", "email": "Email address"}
    subjects = "".join(f"<tr><td>{kinds.get(r.get('subject_kind'), '?')}</td><td>{esc(r.get('hostname') or 'one-way code ' + r['key'][-8:])}</td>"
                       f"<td style='text-align:right;'>{r['devices_30d']}</td><td>{_kb_when(r.get('first_seen_at'))}</td><td>{_kb_when(r.get('last_verified_at'))}</td></tr>"
                       for r in s["subjects"])
    campaigns = "".join(f"<tr><td>{esc(r.get('a_name') or kinds.get(r.get('a_kind'), '?'))}</td><td>{esc(r.get('b_name') or kinds.get(r.get('b_kind'), '?'))}</td>"
                        f"<td style='text-align:right;'>{r['devices_30d']}</td><td>{_kb_when(r.get('last_verified_at'))}</td></tr>" for r in s["campaigns"])
    return f"""<h2 id="observed" data-testid="observed-heading">ApolloSG previous reports</h2>
    <p style="font-size:0.9em;color:var(--muted);">ApolloSG's cross-device intelligence, kept as one-way codes and per-device marks — never content.
    Devices counted here are independent supporting findings only (findings made while ApolloSG already asserted the same thing are dependent and
    never counted). With {s['threshold']} or more in the last {s['windowDays']} days and no contradicting finding, a device is told only "previously
    reported as malicious — High confidence"; never a count, a time or another device's case. A website's name is shown only once it reaches that
    threshold; numbers and addresses are never shown.</p>
    <div class="stats-grid">{_stat_card(f"{s['tracked']:,}", "Being counted")}{_stat_card(f"{s['atThreshold']:,}", f"Seen on {s['threshold']}+ devices")}
    {_stat_card(f"{len(s['campaigns']):,}", "Seen together (possible campaigns)")}</div>
    <table data-testid="observed-subjects"><tr><th>Kind</th><th>What</th><th>Devices (30 days)</th><th>First seen</th><th>Last seen</th></tr>
    {subjects or '<tr><td colspan="5" style="color:var(--muted);">Nothing has reached the threshold yet.</td></tr>'}</table>
    <h3>Seen together</h3><table data-testid="observed-campaigns"><tr><th>One</th><th>The other</th><th>Devices (30 days)</th><th>Last seen</th></tr>
    {campaigns or '<tr><td colspan="4" style="color:var(--muted);">None yet.</td></tr>'}</table>"""


async def _org_page(request: Request, adm: dict, *, values: dict | None = None, problems: list[str] | None = None) -> HTMLResponse:
    from services import org_directory
    entries = await org_directory.entries()
    now = now_utc()
    edit_key = (values or {}).get("key") or request.query_params.get("edit") or ""
    editing_doc = next((e for e in entries if e["key"] == edit_key), None)
    form_values = values if values is not None else _org_values(editing_doc)
    confirmed = sum(org_directory.counts(e, now)["phones"] + org_directory.counts(e, now)["emails"] for e in entries)
    listed = sum(org_directory.counts(e, now)["phones_total"] + org_directory.counts(e, now)["emails_total"] for e in entries)
    notice = {"saved": "Saved. ApolloSG is reading its source pages now; reload in a minute to see what was confirmed.",
              "removed": "Removed from the directory.", "verifying": "Re-checking the source pages now; reload in a minute."}.get(request.query_params.get("done", ""), "")
    by_sector: dict[str, list[str]] = {}
    for e in entries:
        by_sector.setdefault(e.get("sector") or "", []).append(_org_row(e, now))
    tables = "".join(f"<h3>{html_mod.escape(org_directory.SECTORS.get(sector, 'Other'))}</h3><table data-testid='org-table-{sector}'><tr><th>Organisation</th>"
                     f"<th>Domains</th><th>Phone numbers</th><th>Email addresses</th><th>Official source pages</th><th>Last checked</th><th></th></tr>{''.join(rows)}</table>"
                     for sector, rows in sorted(by_sector.items(), key=lambda kv: list(org_directory.SECTORS).index(kv[0]) if kv[0] in org_directory.SECTORS else 99))
    body = f"""
    {'<div class="alert alert-ok" data-testid="org-notice">' + html_mod.escape(notice) + '</div>' if notice else ''}
    <p style="font-size:0.9em;color:var(--muted);">The published websites, phone numbers and email addresses of the organisations scammers most often
    pretend to be. Every check uses it: a contact on this list is the organisation's own; a number or address presented as a listed organisation's
    that isn't on it is a warning sign, and the person is shown the official contact to use instead. Each entry is traced to the organisation's own pages.</p>
    <div class="stats-grid" data-testid="org-totals">{_stat_card(f"{len(entries):,}", "Organisations")}{_stat_card(f"{confirmed:,} of {listed:,}", "Contacts confirmed on their pages")}</div>
    <div class="topbar-row"><span></span><form method="post" action="/api/admin/org-directory/verify" style="margin:0;">
    <button class="btn" data-testid="org-verify-all">Re-check every source page now</button></form></div>
    {tables or '<p>No organisations yet.</p>'}
    {_org_form(form_values, problems or [], bool(editing_doc))}
    {await _observed_section()}"""
    css = (".org-form{display:grid;gap:10px;max-width:720px;} .org-form label{display:grid;gap:4px;font-size:0.88em;}"
           " .org-form input,.org-form select,.org-form textarea{background:var(--bg);border:1px solid var(--border);color:var(--fg);border-radius:6px;padding:6px 8px;font:inherit;}"
           " .btn-danger{border-color:var(--red);color:var(--red);}")
    return HTMLResponse(_shell("Official Organisations", "/api/admin/org-directory", body, admin=adm, extra_css=css), status_code=400 if problems else 200)


@router.get("/admin/org-directory", response_class=HTMLResponse)
async def org_directory_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    return await _org_page(request, adm)


async def _form(request: Request) -> dict:
    from urllib.parse import parse_qs
    return {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True).items()}


def _in_background(coro) -> None:
    import asyncio
    task = asyncio.create_task(coro)
    _KB_TASKS.add(task)
    task.add_done_callback(_KB_TASKS.discard)


@router.post("/admin/org-directory/save")
async def org_directory_save(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import org_directory
    form = await _form(request)
    record, problems = org_directory.parse_form({**form, "domains": (form.get("domains") or "").replace("\n", " ")})
    if problems:
        return await _org_page(request, adm, values=form, problems=problems)
    key = await org_directory.save(record, adm.get("email", ""))
    await _audit_log(adm.get("email", ""), "org_directory_save", f"{record['name']} ({key}): {len(record['domains'])} domains, "
                     f"{len(record['phones'])} numbers, {len(record['emails'])} addresses, {len(record['sources'])} source pages")
    _in_background(org_directory.run(key, trigger="admin_save"))
    return RedirectResponse(f"/api/admin/org-directory?done=saved&edit={key}#org-form", status_code=303)


@router.post("/admin/org-directory/archive")
async def org_directory_archive(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import org_directory
    key = (await _form(request)).get("key") or ""
    if key and await org_directory.archive(key, adm.get("email", "")):
        await _audit_log(adm.get("email", ""), "org_directory_archive", key)
    return RedirectResponse("/api/admin/org-directory?done=removed", status_code=303)


@router.post("/admin/org-directory/verify")
async def org_directory_verify(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import org_directory
    key = (await _form(request)).get("key") or None
    _in_background(org_directory.run(key, trigger="manual"))
    await _audit_log(adm.get("email", ""), "org_directory_verify", key or "all organisations")
    return RedirectResponse("/api/admin/org-directory?done=verifying", status_code=303)


# ── Releases ─────────────────────────────────────────────────────────────────

@router.get("/admin/releases", response_class=HTMLResponse)
async def releases(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    try:
        recent_migrations = await db.apollo_migrations.find(
            {}, {"_id": 0, "name": 1, "applied_at": 1}
        ).sort("applied_at", -1).limit(20).to_list(20)
    except Exception:
        recent_migrations = []

    mig_rows = ""
    for m in recent_migrations:
        mig_rows += f"<tr><td>{html_mod.escape(str(m.get('name','')))}</td><td>{_t(m.get('applied_at'))}</td></tr>"

    body = f"""
    <h2>Application Versions</h2>
    <table>
        <tr><td>Frontend</td><td><code>1.0.0</code></td></tr>
        <tr><td>Backend</td><td><code>Expo + FastAPI</code></td></tr>
        {_models_rows(await ai_settings.selection())}
    </table>

    <h2>Recent Migrations</h2>
    <table><thead><tr><th>Migration</th><th>Applied</th></tr></thead>
    <tbody>{mig_rows or '<tr><td colspan="2" style="color:var(--muted);">No migrations found</td></tr>'}</tbody></table>
    """
    return _shell("Releases", "/api/admin/releases", body, admin=adm)


# ── Screens (services/screen_gallery.py, services/screen_capture.py) ─────────

_SCREENS_CSS = """
.shot-bar{position:sticky;top:0;z-index:5;background:var(--bg);display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);margin-bottom:8px;}
.shot-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin:10px 0 20px;}
.shot{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:6px;}
.shot:has(input:checked){border-color:var(--accent);box-shadow:0 0 0 1px var(--accent);}
.shot img{width:100%;border-radius:6px;background:#fff;aspect-ratio:390/844;object-fit:cover;object-position:top;display:block;}
.shot.tablet img{aspect-ratio:820/1180;}
.shot.app img{aspect-ratio:1/1;object-fit:contain;background:#fff;}
.shot-title{font-size:.85em;color:#fff;font-weight:600;display:flex;gap:6px;align-items:flex-start;cursor:pointer;}
.shot-title input{margin-top:4px;}
.shot-meta{font-size:.75em;color:var(--muted);word-break:break-all;}
.shot-note{font-size:.75em;color:var(--yellow);}
.group-head{display:flex;align-items:center;gap:10px;}
.btn-primary{background:var(--accent);color:#0d1117;border-color:var(--accent);font-weight:600;}
.size-tabs a{margin-right:8px;} .size-tabs a.on{color:#fff;font-weight:700;}
"""
_SCREEN_GROUP_ORDER = ["Setup", "Tabs", "Screens", "Threats", "Family", "Learn & Higgins", "Settings"]
_SCREEN_MSG = {
    "started": ("ok", "Capture started. This page updates as it goes."),
    "queued": ("warning", "Request queued. The preview picks it up within a minute while it's running."),
    "busy": ("warning", "A capture is already running. Wait for it to finish, then try again."),
    "none": ("warning", "Tick at least one image first."),
}


def _screens_status(run: Optional[dict], state: Optional[str]) -> str:
    if not run:
        return ""
    done, total = run.get("done", 0), run.get("total", 0)
    copy = ""
    if run.get("live_copy_failed"):
        copy = (f"<br>{run['live_copy_failed']} image(s) couldn't be copied to the live admin panel "
                f"({html_mod.escape(str(run.get('live_copy_error', '')))}). The live panel gets them once it has this update.")
    errors = run.get("errors") or []
    err = f"<ul>{''.join(f'<li>{html_mod.escape(str(e))}</li>' for e in errors[:10])}</ul>" if errors else ""
    if state == "queued":
        return f'<div class="alert alert-warning">Waiting for the preview to pick up the request made {_t(run.get("requested_at"), "short")}. It must be running.</div>'
    if state == "running":
        return (f'<div class="alert alert-warning">Capturing {done} of {total}: {html_mod.escape(run.get("current") or "starting")}. '
                f'Started {_t(run.get("started_at"), "short")}.{copy}</div>')
    if state == "stalled":
        return (f'<div class="alert alert-critical">The last capture stopped at {done} of {total} (no progress since '
                f'{_t(run.get("updated_at"), "short")}). Regenerate to try again.</div>')
    if state == "failed":
        return f'<div class="alert alert-critical">The last capture failed: {html_mod.escape(str(run.get("error", "")))}{copy}{err}</div>'
    cls = "alert-warning" if errors or copy else "alert-ok"
    return (f'<div class="alert {cls}">Last capture finished {_t(run.get("finished_at"), "short")}: {total} image(s)'
            f'{f", {len(errors)} couldn&#39;t be taken" if errors else ""}.{copy}{err}</div>')


def _shot_card(row: dict) -> str:
    from urllib.parse import quote
    key = quote(row["key"], safe="")
    version = int(row["updated_at"].timestamp()) if isinstance(row.get("updated_at"), datetime) else 0
    is_app = row.get("kind") == "app_image"
    size = "" if is_app else gallery_size_label(row.get("size", ""))
    meta = (html_mod.escape(row.get("filename", "")) if is_app else
            f'{html_mod.escape(row.get("route", ""))} · {_t(row.get("captured_at"), "short")}')
    note = f'<span class="shot-note">{html_mod.escape(row["note"])}</span>' if row.get("note") else ""
    return (f'<div class="shot {"app" if is_app else html_mod.escape(row.get("size", ""))}" data-group="{html_mod.escape(row.get("group", ""))}">'
            f'<label class="shot-title"><input type="checkbox" name="key" value="{html_mod.escape(row["key"])}">'
            f'<span>{html_mod.escape(row.get("title", ""))}{f" · {size}" if size else ""}</span></label>'
            f'<a href="/api/admin/screens/image/{key}" target="_blank" rel="noopener"><img loading="lazy" '
            f'src="/api/admin/screens/thumb/{key}?v={version}" alt="{html_mod.escape(row.get("title", ""))}"></a>'
            f'<span class="shot-meta">{meta}</span>{note}</div>')


def gallery_size_label(size: str) -> str:
    from services.screen_gallery import SIZES
    return SIZES.get(size, {}).get("label", size)


@router.get("/admin/screens", response_class=HTMLResponse)
async def screens_page(request: Request, size: str = "all", msg: str = ""):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import screen_capture, screen_gallery as gallery
    rows = await gallery.items()
    here = await screen_capture.available()
    run = await gallery.latest_run()
    state = gallery.run_state(run)
    size = size if size in ("all", "phone", "tablet") else "all"
    screens = [r for r in rows if r.get("kind") == "screen" and (size == "all" or r.get("size") == size)]
    app_images = [r for r in rows if r.get("kind") == "app_image"]

    groups = ""
    names = sorted({r.get("group", "Screens") for r in screens}, key=lambda g: (_SCREEN_GROUP_ORDER.index(g) if g in _SCREEN_GROUP_ORDER else 99, g))
    for g in names:
        cards = "".join(_shot_card(r) for r in screens if r.get("group") == g)
        groups += (f'<div class="group-head"><h3>{html_mod.escape(g)}</h3><button type="button" class="btn btn-sm" '
                   f'onclick="pickGroup({html_mod.escape(json.dumps(g))})">Select group</button></div><div class="shot-grid">{cards}</div>')
    if not screens:
        groups = '<p style="color:var(--muted);">No screenshots yet. Press <b>Regenerate all</b> to capture every screen.</p>'
    tabs = "".join(f'<a class="{"on" if size == k else ""}" href="/api/admin/screens?size={k}">{label}</a>'
                   for k, label in (("all", "All sizes"), ("phone", "Phone"), ("tablet", "Tablet")))
    where = ("Captured here, from the preview app, and copied to the live admin panel." if here else
             "Captured in the preview and copied here. Regenerating from this panel queues a request; the preview picks it up within a minute while it's running.")
    kind, text = _SCREEN_MSG.get(msg, ("", ""))
    notice = f'<div class="alert alert-{kind}">{text}</div>' if text else ""
    active = state in ("queued", "running")
    body = f"""
    <h2>Screens</h2>
    <p style="color:var(--muted);">Every app screen at phone and tablet size (visible screen, light theme), with labelled sample data, plus the
    app's logos, icons and splash screen images. Tick what you need, then download or regenerate. {where}</p>
    {notice}{_screens_status(run, state)}
    <form method="post" action="/api/admin/screens/action" id="shots">
      <div class="shot-bar">
        <button type="button" class="btn btn-sm" onclick="pick(true)">Select all</button>
        <button type="button" class="btn btn-sm" onclick="pick(false)">Clear</button>
        <span class="size-tabs">{tabs}</span>
        <span id="shot-count" class="shot-meta">0 selected</span>
        <button class="btn btn-sm btn-primary" name="action" value="download">Download selected</button>
        <button class="btn btn-sm" name="action" value="regenerate">Regenerate selected</button>
        <button class="btn btn-sm" name="action" value="regenerate_all" onclick="return confirm('Regenerate every screen and app image? This takes about 15 minutes.')">Regenerate all</button>
      </div>
      {groups}
      <div class="group-head"><h3>Logos, icons and splash images</h3><button type="button" class="btn btn-sm" onclick="pickGroup('App images')">Select group</button></div>
      <div class="shot-grid">{''.join(_shot_card(r) for r in app_images) or '<p style="color:var(--muted);">Added with the next capture.</p>'}</div>
    </form>
    <script>
    (function(){{
      var boxes=function(){{return Array.prototype.slice.call(document.querySelectorAll('#shots input[name=key]'));}};
      var count=function(){{var n=boxes().filter(function(b){{return b.checked;}}).length;document.getElementById('shot-count').textContent=n+' selected';return n;}};
      window.pick=function(on){{boxes().forEach(function(b){{b.checked=on;}});count();}};
      window.pickGroup=function(g){{boxes().forEach(function(b){{if(b.closest('.shot').getAttribute('data-group')===g)b.checked=true;}});count();}};
      document.getElementById('shots').addEventListener('change',count);
      {"setTimeout(function(){if(!count())location.reload();},10000);" if active else ""}
    }})();
    </script>
    """
    return _shell("Screens", "/api/admin/screens", body, admin=adm, extra_css=_SCREENS_CSS)


@router.get("/admin/screens/image/{key:path}")
async def screens_image(key: str, request: Request):
    if not await _admin(request):
        return _login_redirect()
    from services import screen_gallery as gallery
    got = await gallery.image(key)
    if not got:
        return Response("Not found", status_code=404)
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=3600"})


@router.get("/admin/screens/thumb/{key:path}")
async def screens_thumb(key: str, request: Request):
    if not await _admin(request):
        return _login_redirect()
    from services import screen_gallery as gallery
    data = await gallery.thumbnail(key)
    if data is None:
        return Response("Not found", status_code=404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/admin/screens/action")
async def screens_action(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from urllib.parse import parse_qs
    from services import screen_capture, screen_gallery as gallery
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    action = (form.get("action") or [""])[0]
    keys = [k for k in form.get("key", []) if gallery.KEY_PATTERN.match(k)]
    email = adm.get("email", "")
    if action == "download":
        if not keys:
            return RedirectResponse("/api/admin/screens?msg=none", status_code=303)
        data, count = await gallery.zip_of(keys)
        await _audit_log(email, "screens_download", f"{count} image(s)")
        name = f"apollosg-screens-{now_utc().strftime('%Y%m%d-%H%M')}.zip"
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if action not in ("regenerate", "regenerate_all"):
        return RedirectResponse("/api/admin/screens", status_code=303)
    chosen = None if action == "regenerate_all" else keys
    if chosen == []:
        return RedirectResponse("/api/admin/screens?msg=none", status_code=303)
    here = await screen_capture.available()
    if here and screen_capture.busy():
        return RedirectResponse("/api/admin/screens?msg=busy", status_code=303)
    queued = await gallery.queue(chosen, email)
    if here:
        screen_capture.start(queued["run_id"], chosen)
    await _audit_log(email, "screens_regenerate", "all" if chosen is None else f"{len(chosen)} image(s)")
    return RedirectResponse(f"/api/admin/screens?msg={'started' if here else 'queued'}", status_code=303)


# ── Diagnostics ──────────────────────────────────────────────────────────────

@router.get("/admin/diagnostics", response_class=HTMLResponse)
async def diagnostics(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    lines = _read_logs(300)

    # Recent Gemini errors
    try:
        recent_errors = await db.gemini_usage.find(
            {"success": False}, {"_id": 0, "timestamp": 1, "failure_code": 1, "purpose": 1, "model": 1}
        ).sort("timestamp", -1).limit(20).to_list(20)
    except Exception:
        recent_errors = []

    err_rows = ""
    for e in recent_errors:
        err_rows += f"<tr><td>{_t(e.get('timestamp'))}</td><td>{e.get('purpose','')}</td><td>{e.get('failure_code','')}</td><td>{e.get('model','')}</td></tr>"

    body = f"""
    <h2>Recent Gemini Errors</h2>
    <table><thead><tr><th>Time</th><th>Purpose</th><th>Error</th><th>Model</th></tr></thead>
    <tbody>{err_rows or '<tr><td colspan="4" style="color:var(--muted);">No recent errors</td></tr>'}</tbody></table>

    <h2>Backend Logs (last 300 lines)</h2>
    <pre class="log-box">{lines}</pre>
    """
    return _shell("Diagnostics", "/api/admin/diagnostics", body, admin=adm)


# ── Audit ────────────────────────────────────────────────────────────────────

@router.get("/admin/audit-log", response_class=HTMLResponse)
async def audit(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    rows_data = await db.admin_audit.find({}, {"_id": 0}).sort("timestamp", -1).limit(100).to_list(100)
    rows = ""
    for r in rows_data:
        rows += f"<tr><td>{_t(r.get('timestamp'))}</td><td>{html_mod.escape(r.get('email',''))}</td><td>{html_mod.escape(r.get('action',''))}</td><td>{html_mod.escape(str(r.get('detail',''))[:120])}</td></tr>"

    body = f"""
    <h2>Admin Audit Log</h2>
    <table><thead><tr><th>Time</th><th>Account</th><th>Action</th><th>Detail</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="4" style="color:var(--muted);">No audit records</td></tr>'}</tbody></table>
    """
    return _shell("Audit", "/api/admin/audit", body, admin=adm)


# ── Rule Book ────────────────────────────────────────────────────────────────

_RULE_BOOK_STYLE = """<style>
.rb-tools{display:flex;gap:8px;margin:12px 0;}
details.rb-section{border:1px solid var(--border);border-radius:10px;margin:10px 0;background:var(--card);}
details.rb-section>summary{cursor:pointer;padding:12px 16px;list-style:none;display:flex;align-items:center;gap:10px;}
details.rb-section>summary::-webkit-details-marker{display:none;}
details.rb-section>summary::before{content:"\\25B8";font-size:0.9rem;color:var(--muted);}
details.rb-section[open]>summary::before{content:"\\25BE";}
details.rb-section>summary h2{display:inline;margin:0;font-size:1.1rem;}
details.rb-section>summary h3{display:inline;margin:0;font-size:1.05rem;}
details.rb-section>.rb-body{padding:0 16px 12px;}
.rb-body li{margin:4px 0;}
.rb-body ol,.rb-body ul{padding-left:24px;margin:6px 0 10px;}
section.rb-group{margin:26px 0 8px;}
section.rb-group>h2{font-size:1.3rem;margin:0 0 6px;padding-bottom:6px;border-bottom:1px solid var(--border);}
section.rb-group>.rb-lead{color:var(--muted);margin:6px 0;}
</style>"""

_RULE_BOOK_SCRIPT = """<script>
(function(){
  function openFromHash(){var id=decodeURIComponent(location.hash.slice(1));var el=id&&document.getElementById(id);if(el){if(el.tagName==='DETAILS'){el.open=true;}el.scrollIntoView();}}
  window.addEventListener('hashchange',openFromHash);openFromHash();
  document.querySelectorAll('[data-rb-all]').forEach(function(b){b.addEventListener('click',function(){var open=b.getAttribute('data-rb-all')==='open';document.querySelectorAll('details.rb-section').forEach(function(d){d.open=open;});});});
})();
</script>"""

_SECTION_HEADING = re.compile(r"^##\s+(.*?)(?:\s*\{#([\w-]+)\})?\s*$")


_BOOK_ITEM = re.compile(r"^( *)([-*]|\d+\.)\s+(.*)$")


def _blank_lines_for_markdown(text: str) -> str:
    """The book is written for the app's reader (frontend/src/domain/ruleBook.ts), which starts a list or a table on
    the line straight after a paragraph and nests items indented 2–3 spaces. Python-Markdown needs a blank line before
    a list or table and 4 spaces per level; without them every item and table row ran into one paragraph. This adds
    only blank lines and indentation, so the words stay exactly the same."""
    out: list[str] = []
    prev = "blank"
    for line in text.split("\n"):
        item = _BOOK_ITEM.match(line)
        if not line.strip():
            kind = "blank"
        elif line.lstrip().startswith("|"):
            kind = "table"
        elif re.match(r"^\s*-{3,}\s*$", line):
            kind = "rule"
        elif item:
            kind = "item"
            line = "    " * min(2, round(len(item.group(1)) / 3)) + f"{item.group(2)} {item.group(3)}"
        elif prev in ("item", "more") and line.startswith(" "):
            kind = "more"  # a wrapped continuation of the item above
        else:
            kind = "text"
        if prev != "blank" and kind != "blank" and kind != prev and {prev, kind} != {"item", "more"}:
            out.append("")
        out.append(line)
        prev = kind
    return "\n".join(out)


def _book_md(part: str) -> str:
    return markdown.markdown(_blank_lines_for_markdown(part), extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"])


_BOOK_TOOLS = ('<button class="btn btn-sm" type="button" data-rb-all="open" data-testid="rule-book-open-all">Open all</button>'
               '<button class="btn btn-sm" type="button" data-rb-all="close" data-testid="rule-book-close-all">Close all</button>')


def _book_section(anchor: str, title: str, body: str, heading: str) -> str:
    return (f'<details class="rb-section" id="{html_mod.escape(anchor)}" data-testid="rule-book-section-{html_mod.escape(anchor)}">'
            f'<summary><{heading}>{html_mod.escape(title)}</{heading}></summary><div class="rb-body">{_book_md(body)}</div></details>')


def _rule_book_sections(text: str) -> str:
    """A guide in closed sections (the Play Console guide, the Family Help two-phone test): the intro stays open;
    every `## ` section becomes its own closed <details>, opened by a tap, by "Open all", or by a link to its id.
    Every list item and table row is its own line."""
    from services.rulebook_export import split_sections
    intro, sections = split_sections(text)
    out = [_book_md(intro), f'<div class="rb-tools">{_BOOK_TOOLS}</div>']
    out += [_book_section(section["id"], section["title"], section["markdown"], "h2") for section in sections]
    return "".join(out)


def _rule_book_groups(text: str) -> str:
    """The rule book: the intro stays open, each part (Protection Gates, Investigation process…) is a heading, and
    every section under it (Link Gate, TC FlyBy…) is its own closed <details>, as in the app."""
    from services.rulebook_export import split_groups
    intro, groups = split_groups(text)
    out = [_book_md(intro), f'<div class="rb-tools">{_BOOK_TOOLS}'
           '<a class="btn btn-sm" href="/api/admin/rule-book/download/pdf" data-testid="rule-book-download-pdf">Download PDF</a>'
           '<a class="btn btn-sm" href="/api/admin/rule-book/download/json" data-testid="rule-book-download-json">Download JSON</a></div>']
    for group in groups:
        gid = html_mod.escape(group["id"])
        out.append(f'<section class="rb-group" id="{gid}" data-testid="rule-book-group-{gid}"><h2>{html_mod.escape(group["title"])}</h2>')
        if group["intro"]:
            out.append(f'<div class="rb-lead">{_book_md(group["intro"])}</div>')
        out += [_book_section(section["id"], section["title"], section["markdown"], "h3") for section in group["sections"]]
        out.append("</section>")
    return "".join(out)


def _rule_book_html() -> str:
    """The shared rule book (content/rulebook.md), word for word — the same file the app shows in Settings.
    Each section starts closed, as in the app."""
    from services import rulebook
    behind = rulebook.changed()
    banner = (f'<div class="alert alert-warning" data-testid="rule-book-behind">The rule book is behind the code: '
              f'{", ".join(html_mod.escape(p) for p in behind)} changed since it was last reviewed. Update '
              f'<code>backend/content/rulebook.md</code>, then run <code>python scripts/rulebook_stamp.py</code>.</div>' if behind else
              '<div class="alert alert-ok" data-testid="rule-book-in-step">In step with the code: every rule-defining file matches the last review.</div>')
    body = _rule_book_groups(rulebook.read()["markdown"])
    return f'{_RULE_BOOK_STYLE}{banner}<article data-testid="rule-book">{body}</article>{_RULE_BOOK_SCRIPT}'


@router.get("/admin/rule-book", response_class=HTMLResponse)
async def rule_book_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    await _audit_log(adm.get("email", ""), "view_rule_book")
    return _shell("Rule Book", "/api/admin/rule-book", _rule_book_html(), admin=adm)


_RULE_BOOK_DOWNLOADS = {"json": "application/json", "pdf": "application/pdf"}


@router.get("/admin/rule-book/download/{kind}")
async def rule_book_download(kind: str, request: Request):
    """The whole rule book as a file: JSON (every section, word for word) or PDF."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    if kind not in _RULE_BOOK_DOWNLOADS:
        return JSONResponse({"detail": "Choose json or pdf."}, status_code=404)
    import asyncio
    from services import rulebook_export
    await _audit_log(adm.get("email", ""), f"download_rule_book_{kind}")
    data = await asyncio.to_thread(rulebook_export.as_pdf if kind == "pdf" else rulebook_export.as_json)
    return Response(data, media_type=_RULE_BOOK_DOWNLOADS[kind],
                    headers={"Content-Disposition": f'attachment; filename="{rulebook_export.filename(kind)}"', "Cache-Control": "no-store"})


# ── Play Store: the Google Play Console declarations checklist ────────────────

PLAY_CONSOLE_GUIDE = REPORT_DIR / "content" / "play_console_declarations.md"


@router.get("/admin/play-console", response_class=HTMLResponse)
async def play_console_page(request: Request):
    """The owner's step-by-step guide to the Play Console forms, word for word from content/play_console_declarations.md.
    Each section starts closed, like the Rule Book."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    await _audit_log(adm.get("email", ""), "view_play_console_guide")
    body = (f'<div class="topbar-row"><span></span><a href="/api/admin/reports/play-console/pdf" class="btn btn-sm" '
            f'data-testid="play-console-pdf">Download PDF</a></div>'
            f'{_RULE_BOOK_STYLE}<article data-testid="play-console-guide">{_rule_book_sections(PLAY_CONSOLE_GUIDE.read_text())}</article>{_RULE_BOOK_SCRIPT}')
    return _shell("Play Store", "/api/admin/play-console", body, admin=adm)


# ── Family Help: the two-phone test checklist ─────────────────────────────────

FAMILY_HELP_TEST_GUIDE = REPORT_DIR / "content" / "family_help_two_phone_test.md"


def _family_help_ready_html() -> str:
    """The banner the checklist's first step looks for: is this server set up to run Family Help?"""
    from services.family_assist.config import load_config
    config = load_config()
    if config.available:
        return ('<div class="alert alert-ok" data-testid="family-help-server-ready"><strong>Server ready</strong> — '
                'Family Help is switched on and its secure relay is set up on this server.</div>')
    missing = ([] if config.enabled else ["Family Help is switched off (FAMILY_ASSIST_ENABLED)"]) + \
              ([] if config.turn_valid else ["the Cloudflare relay keys are missing or invalid"])
    return (f'<div class="alert alert-critical" data-testid="family-help-server-not-ready"><strong>Server not ready</strong> — '
            f'{html_mod.escape("; ".join(missing))}. Both phones will show "Not available yet".</div>')


def _phone_label(device: Optional[dict]) -> str:
    if not device:
        return "—"
    name = " ".join(p for p in (device.get("manufacturer"), device.get("model")) if p) or (device.get("platform") or "?").title()
    system = " ".join(p for p in (device.get("os_name"), device.get("os_version")) if p)
    return html_mod.escape(f"{name} ({system})" if system else name)


def _session_length(row: dict) -> str:
    start, end = row.get("activated_at"), row.get("ended_at")
    if not start or not end:
        return "—"
    seconds = int((end - start).total_seconds())
    return f"{seconds // 60}m {seconds % 60:02d}s"


async def _family_help_sessions_html() -> str:
    rows = await db.family_assist_sessions.find({}, {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)
    ids = {r.get(k) for r in rows for k in ("sharer_device_id", "helper_device_id") if r.get(k)}
    phones = {d["device_id"]: d async for d in db.devices.find({"device_id": {"$in": list(ids)}}, {"_id": 0, "token_hash": 0})}
    body = "".join(
        f"<tr><td>{_t(r.get('created_at'), 'short')}</td><td>{_phone_label(phones.get(r.get('sharer_device_id')))}</td>"
        f"<td>{_phone_label(phones.get(r.get('helper_device_id')))}</td><td>{html_mod.escape(str(r.get('capture_scope') or '—'))}</td>"
        f"<td>{html_mod.escape(str(r.get('state') or '—'))}</td>"
        f"<td>{html_mod.escape(' · '.join(str(v) for v in (r.get('end_reason'), r.get('failure_code')) if v) or '—')}</td>"
        f"<td>{_session_length(r)}</td><td>{'Yes' if r.get('ever_paused') else 'No'}</td></tr>" for r in rows)
    return (f'<h2 id="recent-sessions">Recent Family Help sessions</h2><table data-testid="family-help-sessions"><thead><tr>'
            f'<th>Started</th><th>Phone A (sharing)</th><th>Phone B (helping)</th><th>Shared</th><th>State</th><th>How it ended</th>'
            f'<th>Sharing time</th><th>Paused</th></tr></thead><tbody>'
            f'{body or "<tr><td colspan=8 style=color:var(--muted);>No Family Help sessions yet.</td></tr>"}</tbody></table>')


@router.get("/admin/family-help-test", response_class=HTMLResponse)
async def family_help_test_page(request: Request):
    """The two-phone Family Help test, word for word from content/family_help_two_phone_test.md, with tick boxes,
    whether this server is ready, and the latest sessions (how each one ended)."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    await _audit_log(adm.get("email", ""), "view_family_help_test")
    guide = FAMILY_HELP_TEST_GUIDE.read_text().replace("- [ ] ", '- <input type="checkbox" class="fh-tick"> ')
    body = (f'<div class="topbar-row"><span></span><a href="/api/admin/reports/family-help-test/pdf" class="btn btn-sm" '
            f'data-testid="family-help-test-pdf">Download PDF</a></div>{_family_help_ready_html()}'
            f'{_RULE_BOOK_STYLE}<article data-testid="family-help-test-guide">{_rule_book_sections(guide)}</article>'
            f'{await _family_help_sessions_html()}{_RULE_BOOK_SCRIPT}')
    return _shell("Family Help Test", "/api/admin/family-help-test", body, admin=adm,
                  extra_css=".fh-tick{margin-right:6px;transform:scale(1.15);vertical-align:middle;}")


# ── Devices: every registered phone, what it is, and how much each feature was used ──

_DEVICE_PAGE_SIZE = 50
_PLATFORMS = ("android", "ios", "web")
_OS_NAMES = {"android": "Android", "ios": "iOS", "web": "Web"}
_COUNT_COLUMNS = (("tc_flyby", "TC FlyBy"), ("magnum_di", "Magnum DI"), ("ask_higgins", "Ask Higgins"),
                  ("device_checks", "Device checks"), ("learn_read", "Learn with Higgins read"), ("scam_alerts_read", "Scam alerts read"))


def _device_row(d: dict, name: str | None) -> str:
    from services import device_stats
    esc = html_mod.escape
    n = device_stats.counts(d)
    installed = _t(d["installed_at"], "short") if d.get("installed_at") else f'{_t(d.get("created_at"), "short")}*'
    cells = "".join(f"<td class='num'>{n[key]:,}</td>" for key, _ in _COUNT_COLUMNS)
    kind = device_stats.record_type(d)
    badge = f"<span class='kind kind-{'phone' if kind == 'Phone' else 'other'}'>{esc(kind)}</span>"
    # The descriptive name ("Samsung Galaxy Z Fold6") with the model code the phone reported beside it.
    code = d.get("model")
    model_cell = esc(name or code or "—") + (f" <span class='kind'>{esc(code)}</span>" if name and code and name != code else "")
    return (f"<tr><td><code title='{esc(d['device_id'])}'>{esc(d['device_id'][:8])}</code></td><td>{badge}</td>"
            f"<td>{esc(d.get('manufacturer') or '—')}</td>"
            f"<td>{model_cell}</td>"
            f"<td>{esc(d.get('os_name') or _OS_NAMES.get(d.get('platform') or '', d.get('platform') or '—'))}</td>"
            f"<td>{esc(d.get('os_version') or '—')}</td><td>{esc(d.get('country') or '—')}</td><td>{installed}</td>"
            f"<td>{esc(d.get('app_version') or '—')}</td>{cells}<td>{_t(d.get('last_seen_at'), 'short')}</td></tr>")


async def _last_reset_html(just_reset: bool) -> str:
    last = await db.admin_audit.find_one({"action": "reset_stats"}, {"_id": 0}, sort=[("timestamp", -1)])
    if not last:
        return '<p style="color:var(--muted);">Stats have never been reset.</p>'
    cls = "alert alert-ok" if just_reset else ""
    return (f'<div class="{cls}" data-testid="stats-last-reset" style="margin:8px 0;"><strong>Stats last reset</strong> '
            f'{_t(last.get("timestamp"))} — {html_mod.escape(str(last.get("detail", "")))}</div>')


def _reset_form_html() -> str:
    from services.stats_reset import WHAT_IS_KEPT, WHAT_IS_RESET
    items = "".join(f"<li>{html_mod.escape(i)}</li>" for i in WHAT_IS_RESET)
    return f"""<details class="reset-box" data-testid="reset-stats-box"><summary><strong>Reset Stats</strong> — set every count in the
    admin panel back to zero</summary>
    <p>This permanently deletes:</p><ul>{items}</ul>
    <p>It keeps {html_mod.escape(", ".join(WHAT_IS_KEPT))}. It can't be undone.</p>
    <form method="post" action="/api/admin/reset-stats" onsubmit="return confirm('Permanently delete all usage and cost records and set every count to zero?');">
      <label>Type <code>RESET</code> to confirm <input name="confirm" required pattern="RESET" autocomplete="off" data-testid="reset-stats-confirm"></label>
      <button class="btn btn-danger" type="submit" data-testid="reset-stats-button">Reset Stats</button>
    </form></details>"""


@router.get("/admin/device-list", response_class=HTMLResponse)
async def device_list_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from services import device_stats
    platform = request.query_params.get("platform", "")
    # Real phones by default (services/device_stats.REAL_PHONES); "All records" keeps every registration, including
    # web, test and script registrations and Google's test phones.
    view = "all" if request.query_params.get("view") == "all" else "real"
    query = {**(device_stats.REAL_PHONES if view == "real" else {}), **({"platform": platform} if platform in _PLATFORMS else {})}
    page = int(request.query_params.get("page", "1")) if request.query_params.get("page", "1").isdigit() else 1
    page = max(page, 1)
    total = await db.devices.count_documents(query)
    pages = max(1, -(-total // _DEVICE_PAGE_SIZE))
    page = min(page, pages)
    rows = await db.devices.find(query, {"_id": 0, "token_hash": 0}).sort("last_seen_at", -1) \
        .skip((page - 1) * _DEVICE_PAGE_SIZE).limit(_DEVICE_PAGE_SIZE).to_list(_DEVICE_PAGE_SIZE)
    sums = await device_stats.totals(query)
    from services import device_models
    names = [await device_models.name_for(d.get("manufacturer"), d.get("model")) for d in rows]
    label = ("Real phones" if view == "real" else "All records") + (f" ({_OS_NAMES[platform]})" if platform in _PLATFORMS else "")
    cards = _stat_card(f"{total:,}", label) + "".join(_stat_card(f"{sums[key]:,}", label) for key, label in _COUNT_COLUMNS)
    if view == "real":
        everything = await db.devices.count_documents({})
        cards += _stat_card(f"{everything - await db.devices.count_documents(device_stats.REAL_PHONES):,}", "Other records (not counted)")
    params = lambda **kw: urlencode({k: v for k, v in {"view": view if view == "all" else "", "platform": platform, **kw}.items() if v})  # noqa: E731
    views = " ".join(f'<a class="btn btn-sm{" active" if view == v else ""}" href="/api/admin/device-list?{params(view=v if v == "all" else "", platform=platform)}" '
                     f'data-testid="device-view-{v}">{name}</a>' for v, name in (("real", "Real phones"), ("all", "All records")))
    filters = " ".join(f'<a class="btn btn-sm{" active" if platform == p else ""}" href="/api/admin/device-list?{params(platform=p)}" '
                       f'data-testid="device-filter-{p or "all"}">{_OS_NAMES.get(p, "Any system")}</a>' for p in ("", *_PLATFORMS))
    link = lambda n: f"/api/admin/device-list?{params(page=str(n))}"  # noqa: E731
    newer = f'<a class="btn btn-sm" href="{link(page - 1)}" data-testid="device-page-newer">&larr; Newer</a>' if page > 1 else ""
    older = f'<a class="btn btn-sm" href="{link(page + 1)}" data-testid="device-page-older">Older &rarr;</a>' if page < pages else ""
    pager = f'<div class="pager" data-testid="device-pager">{newer}<span>Page {page:,} of {pages:,}</span>{older}</div>'
    head = "".join(f"<th>{h}</th>" for h in ("ID", "Type", "Manufacturer", "Model", "OS", "OS version", "Country", "Date installed",
                                              "App version", *(label for _, label in _COUNT_COLUMNS), "Last seen"))
    body = f"""
    {await _last_reset_html(request.query_params.get("reset") == "done")}
    {_reset_form_html()}
    <h2>Totals</h2><div class="stats-grid" data-testid="device-totals">{cards}</div>
    <h2>Devices</h2>
    <div class="topbar-row"><span>{views} &nbsp;·&nbsp; {filters}</span>{pager}</div>
    <div class="table-scroll"><table data-testid="device-table"><thead><tr>{head}</tr></thead>
    <tbody>{"".join(_device_row(d, n) for d, n in zip(rows, names)) or '<tr><td colspan="16" style="color:var(--muted);">No devices.</td></tr>'}</tbody></table></div>
    <p style="color:var(--muted);font-size:0.82em;">Newest activity first. <b>Real phones</b> are the ApolloSG app on Android or iPhone using the
    phone's own protection, except Google's test phones (Play pre-launch testing, reported by the phone or marked by an admin).
    <b>All records</b> also shows web, test and script registrations. Make, model, system, country (from the phone's
    region setting) and install date arrive the next time each phone opens the app; phones on an older version show —.
    * the phone didn't report its install date, so this is when it first registered with ApolloSG. Learn and scam alert
    reads count different ones opened.</p>"""
    css = (".main{max-width:none;min-width:0;} .table-scroll{overflow-x:auto;max-width:100%;}"
           " .table-scroll table{font-size:0.8em;white-space:nowrap;} .kind{font-size:0.85em;padding:1px 6px;border-radius:8px;border:1px solid var(--border);}"
           " .kind-phone{color:var(--green);border-color:rgba(63,185,80,0.4);} .kind-other{color:var(--muted);}"
           " td.num{text-align:right;} .btn.active{border-color:var(--accent);color:#fff;} .pager{display:flex;gap:12px;align-items:center;}"
           " .reset-box{background:var(--card);border:1px solid rgba(248,81,73,0.35);border-radius:10px;padding:12px 16px;margin:12px 0;}"
           " .reset-box summary{cursor:pointer;} .reset-box ul{margin:6px 0 8px 22px;} .reset-box p{margin:8px 0;}"
           " .reset-box input{background:var(--bg);border:1px solid var(--border);color:var(--fg);border-radius:6px;padding:4px 8px;margin:0 8px;}"
           " .btn-danger{border-color:var(--red);color:var(--red);} .btn-danger:hover{background:rgba(248,81,73,0.12);color:#fff;}")
    return _shell("Devices", "/api/admin/device-list", body, admin=adm, extra_css=css)


# ── AI Map: every feature that calls the AI provider, and what it used this week ──
# Each AI usage record is put under the feature that made it: by its purpose, and for a shared purpose by the
# correlation id the feature gives its calls. Anything else is shown by its purpose, so the totals always add up.
# The provider and model are chosen in one place only: ApolloSG Settings → AI Provider & Model.

_GEMINI_FEATURES = (
    ("magnum_di", "Magnum DI", "The full investigation of a case, with web search when it needs it.",
     "services/higgins/coordinator.py → run_turn()",
     "When TC FlyBy and what ApolloSG already knows can't settle an investigation."),
    ("tc_flyby", "TC FlyBy web search", "Narrow searches about a link, number, company, ABN, ACN or licence.",
     "services/higgins/tc_flyby/search.py → run()",
     "During an investigation, only for what no saved answer from the last 7 days covers."),
    ("model_test", "Test this model", "One fixed, made-up sample check of a provider and model, shaped like a Magnum DI call.",
     "services/higgins/model_test.py → run()",
     "Only when an admin taps Test this model in ApolloSG Settings."),
)
_FEATURE_NAMES = {key: name for key, name, *_ in _GEMINI_FEATURES}
_RETIRED_FEATURES = {
    "ask_higgins": "Ask Higgins general answers (removed: Ask Higgins makes no AI call)",
    "page_signal_extraction": "Screenshot page reading (removed)", "page_crawl": "Web page reading (removed)",
    "protection": "Protection explanations (removed)", "public_advisory_analysis": "Scam alert analysis (retired)",
    "research": "Research lookups (retired)", "triage": "Triage screening (retired)", "msg_check": "Message second opinion (retired)",
}


def _starts(prefix: str) -> dict:
    return {"$regexMatch": {"input": {"$ifNull": ["$correlation_id", ""]}, "regex": f"^{prefix}"}}


_FEATURE_OF_RECORD = {"$switch": {"branches": [
    {"case": _starts("model-test-"), "then": "model_test"},
    {"case": {"$and": [{"$in": ["$purpose", ["investigation", "vision_investigation"]]}, _starts("case-")]}, "then": "magnum_di"},
    {"case": {"$eq": ["$purpose", "tc_flyby_search"]}, "then": "tc_flyby"},
    {"case": {"$and": [{"$eq": ["$purpose", "ordinary_chat"]}, _starts("chat-")]}, "then": "ask_higgins"},
    {"case": {"$and": [{"$eq": ["$purpose", "ordinary_chat"]}, _starts("protection-")]}, "then": "protection"},
    {"case": _starts("page-crawl"), "then": "page_crawl"},
    {"case": _starts("msg-check"), "then": "msg_check"},
], "default": {"$ifNull": ["$purpose", "unknown"]}}}


def _week_start(offset_minutes: int) -> datetime:
    """Monday 00:00 this week in the admin's time zone, as UTC."""
    zone = timezone(timedelta(minutes=offset_minutes))
    local = now_utc().astimezone(zone)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.astimezone(timezone.utc)


async def gemini_usage_by_feature(start: datetime, end: Optional[datetime] = None) -> dict[str, dict]:
    when: dict = {"$gte": start} if end is None else {"$gte": start, "$lt": end}
    rows = await db.gemini_usage.aggregate([
        {"$match": {"timestamp": when}},
        {"$group": {"_id": _FEATURE_OF_RECORD, "calls": {"$sum": 1}, "failed": {"$sum": {"$cond": ["$success", 0, 1]}},
                    "cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}}, "searches": {"$sum": {"$ifNull": ["$search_queries", 0]}},
                    "last": {"$max": "$timestamp"}}},
    ]).to_list(100)
    return {r["_id"]: r for r in rows}


_TREND_WEEKS = 4


def _change_html(now: float, before: float) -> str:
    """How this week's cost compares with the week before: up in red, down in green."""
    if not before and not now:
        return ""
    if not before:
        return " <span class='trend up'>new</span>"
    pct = (now - before) / before * 100
    if abs(pct) < 0.5:
        return " <span class='trend'>±0%</span>"
    return f" <span class='trend {'up' if pct > 0 else 'down'}'>{'▲' if pct > 0 else '▼'} {abs(pct):.0f}%</span>"


def _trend_table(weeks: list[datetime], usage: list[dict[str, dict]], tz: int) -> str:
    """The last four weeks side by side for each feature, oldest first, each cost compared with the week before."""
    zone = timezone(timedelta(minutes=tz))
    current = [key for key, *_ in _GEMINI_FEATURES]
    names = _FEATURE_NAMES

    def pick(week: dict[str, dict], which: str) -> tuple[int, float]:
        if which == "total":
            rows = list(week.values())
        elif which == "other":
            rows = [v for k, v in week.items() if k not in current]
        else:
            rows = [week[which]] if which in week else []
        return sum(r["calls"] for r in rows), sum(r["cost"] for r in rows)

    def row(label: str, which: str, strong: bool = False) -> str:
        cells, before = "", None
        for i, week in enumerate(usage):
            calls, cost = pick(week, which)
            # This week isn't finished, so comparing it with a whole week would always look like a drop.
            change = _change_html(cost, before) if before is not None and i < len(usage) - 1 else ""
            cells += f"<td class='num'>${cost:.4f}{change}<br><span class='muted'>{calls:,} calls</span></td>"
            before = cost
        name = f"<strong>{html_mod.escape(label)}</strong>" if strong else html_mod.escape(label)
        return f"<tr data-testid='gemini-trend-{which}'><td>{name}</td>{cells}</tr>"

    heads = "".join(f"<th class='num'>{'This week so far' if i == len(weeks) - 1 else 'Week of'}<br>"
                    f"{w.astimezone(zone).strftime('%a %-d %b')}</th>" for i, w in enumerate(weeks))
    body = "".join(row(names[k], k) for k in current) + row("Removed or retired features", "other") + row("All AI calls", "total", strong=True)
    return (f'<h2>Last four weeks</h2><p class="muted">Estimated cost and calls per week (Monday to Sunday), oldest first. '
            f'Each finished week is compared with the week before it; this week isn\'t finished, so it has no comparison yet.</p>'
            f'<div class="table-scroll"><table data-testid="gemini-trend-table"><thead><tr><th>Feature</th>{heads}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def _usage_cells(row: Optional[dict]) -> str:
    row = row or {}
    return (f"<td class='num'>{row.get('calls', 0):,}</td><td class='num'>{row.get('failed', 0):,}</td>"
            f"<td class='num'>{row.get('searches', 0):,}</td><td class='num'>${row.get('cost', 0):.4f}</td><td>{_t(row.get('last'), 'short')}</td>")


def _selection_text(sel: dict) -> str:
    return f"{ai_settings.label(sel['provider'])} · {sel['model']}"


def _models_rows(sel: dict) -> str:
    """The AI investigation provider and model in use, for the System and Releases pages."""
    return (f"<tr><td>AI investigation provider &amp; model (Magnum DI and TC FlyBy)</td><td><code>{html_mod.escape(_selection_text(sel))}</code> "
            f"<a href='/api/admin/apollosg-settings'>Change in ApolloSG Settings</a></td></tr>")


def _model_label(model: str) -> str:
    price = MODEL_PRICING.get(model)
    return f"{model} · ${price['input']:.2f} in / ${price['output']:.2f} out per 1M tokens" if price else f"{model} · no price on file"


def _model_cell(key: str, sel: dict) -> str:
    """The model a feature calls: always the one ApolloSG Settings selected. Read-only here."""
    if key == "model_test":
        return f"<td data-testid='gemini-model-{key}'>The model being tested<br><span class='muted'>+ web search, as Magnum DI</span></td>"
    note = "Always the same as Magnum DI" if key == "tc_flyby" else "+ web search when it needs it"
    return (f"<td data-testid='gemini-model-{key}'>{html_mod.escape(_selection_text(sel))}"
            f"<br><span class='muted'>{note} · <a href='/api/admin/apollosg-settings'>Change in ApolloSG Settings</a></span></td>")


@router.get("/admin/gemini-map", response_class=HTMLResponse)
async def gemini_map_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    tz = _tz_param(request)
    start = _week_start(tz)
    weeks = [start - timedelta(weeks=n) for n in range(_TREND_WEEKS - 1, -1, -1)]
    trend = [await gemini_usage_by_feature(w, w + timedelta(weeks=1) if w != start else None) for w in weeks]
    usage = trend[-1]
    sel = await ai_settings.selection()
    esc = html_mod.escape
    rows = "".join(
        f"<tr data-testid='gemini-feature-{key}'><td><strong>{esc(name)}</strong><br><span class='muted'>{esc(what)}</span></td>"
        f"<td><code>{esc(code)}</code></td>{_model_cell(key, sel)}<td class='muted'>{esc(when)}</td>{_usage_cells(usage.get(key))}</tr>"
        for key, name, what, code, when in _GEMINI_FEATURES)
    current = {key for key, *_ in _GEMINI_FEATURES}
    others = sorted(((k, v) for k, v in usage.items() if k not in current), key=lambda kv: -kv[1]["calls"])
    other_rows = "".join(f"<tr><td>{esc(_RETIRED_FEATURES.get(k, k))}</td>{_usage_cells(v)}</tr>" for k, v in others)
    total_calls = sum(v["calls"] for v in usage.values())
    total_cost = sum(v["cost"] for v in usage.values())
    head = "<th>Calls</th><th>Failed</th><th>Searches</th><th>Est. cost (USD)</th><th>Last call</th>"
    body = f"""
    <p class="muted" data-testid="gemini-map-week">This week: since Monday 00:00 {local_time.zone_label(tz)}
    ({_t(start)}). Each call is counted once; the free model check and token count before it are not.</p>
    <div class="stats-grid">{_stat_card(f"{total_calls:,}", "AI calls this week")}{_stat_card(f"${total_cost:.4f}", "Estimated cost this week")}</div>
    <p data-testid="gemini-map-selection">Provider and model: <strong>{esc(_selection_text(sel))}</strong> ·
    <a href="/api/admin/apollosg-settings">Change in ApolloSG Settings → AI Provider &amp; Model</a></p>
    <h2>Features that call the AI provider</h2>
    <div class="table-scroll"><table data-testid="gemini-map-table"><thead><tr><th>Feature</th><th>Where in the code</th><th>Model</th>
    <th>When it calls</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>
    <p class="muted">Every call goes through one gateway, <code>generate()</code> in <code>services/higgins/provider.py</code>,
    which records it and hands it to the selected provider's adapter. Magnum DI and TC FlyBy use the one provider and
    model selected in ApolloSG Settings; Ask Higgins makes no AI call.</p>
    {_trend_table(weeks, trend, tz)}
    {f'<h2>Other calls this week</h2><p class="muted">From features that have been removed or no longer call the AI provider.</p><table data-testid="gemini-map-other"><thead><tr><th>Feature</th>{head}</tr></thead><tbody>{other_rows}</tbody></table>' if other_rows else ""}
    <script>(function(){{if(!/[?&]tz=/.test(location.search)){{location.replace(location.pathname+'?tz='+(-new Date().getTimezoneOffset()));}}}})();</script>"""
    css = (".muted{color:var(--muted);font-size:0.85em;} td.num,th.num{text-align:right;white-space:nowrap;} .table-scroll{overflow-x:auto;}"
           " .trend{font-size:0.8em;margin-left:4px;color:var(--muted);} .trend.up{color:var(--red);} .trend.down{color:var(--green);}"
           " .main{min-width:0;} td code{font-size:0.8em;}"
           " td a{color:var(--accent);}")
    return _shell("AI Map", "/api/admin/gemini-map", body, admin=adm, extra_css=css)


# ── ApolloSG Settings → AI Provider & Model: the one place the investigation provider and model are chosen ──

def _ai_model_section(sel: dict, flash: str = "", error: str = "") -> str:
    esc = html_mod.escape
    opts = ai_settings.options()
    # Every approved model is listed; one that can't be used says why, can be tested (nothing is sent) but never saved.
    listed = {p["id"]: [{"id": m["id"], "label": _model_label(m["id"]) + (" — can't be used" if m["reasons"] else ""),
                         "reasons": m["reasons"]} for m in p["models"]] for p in opts}
    providers = "".join(f"<option value='{p['id']}'{' selected' if p['id'] == sel['provider'] else ''}>{esc(p['label'])}</option>" for p in opts)
    current = listed.get(sel["provider"], [])
    models = ("".join(f"<option value='{esc(m['id'])}'{' selected' if m['id'] == sel['model'] else ''}>{esc(m['label'])}</option>" for m in current)
              or "<option value='' disabled selected>No models available for this provider</option>")
    who = ("Default — nobody has changed it yet" if sel.get("default")
           else f"Changed by {esc(sel.get('changed_by') or 'an admin')}, {_t(sel.get('changed_at'), 'short')}")
    blocked = ai_settings.unavailable(sel["provider"], sel["model"])
    blocked_html = (f"<p class='warn' data-testid='ai-current-unavailable'>This model can't be used right now: it {esc('; '.join(blocked))}. "
                    f"Investigations fail and say so until it's fixed or another model is saved. ApolloSG never switches model by itself.</p>"
                    if blocked else "")
    not_listed = []
    for p in opts:
        if not p["models"]:
            not_listed.append(f"<li><strong>{esc(p['label'])}</strong>: no approved models yet"
                              + ("" if p["keyConfigured"] else "; no API key is set on the server") + "</li>")
        for m in (m for m in p["models"] if m["reasons"]):
            not_listed.append(f"<li><code>{esc(m['id'])}</code> ({esc(p['label'])}): {esc('; '.join(m['reasons']))}</li>")
    unavailable_html = (f"<details data-testid='ai-not-available'><summary>Not available for investigations ({len(not_listed)})</summary>"
                        f"<ul>{''.join(not_listed)}</ul></details>" if not_listed else "")
    return f"""
    <h2>AI Provider &amp; Model</h2>
    <p class="muted">The one provider and model Apollo's AI investigations use. Magnum DI uses it, and TC FlyBy always follows
    Magnum DI. Ask Higgins makes no AI call. API keys stay in the server's secure settings and are never shown here.</p>
    {f"<p class='flash' data-testid='ai-model-saved'>{flash}</p>" if flash else ""}
    {f"<p class='error' data-testid='ai-model-error'>{esc(error)}</p>" if error else ""}
    <div class="current" data-testid="ai-current">Active now: <strong data-testid="ai-current-value">{esc(_selection_text(sel))}</strong>
    <br><span class="muted" data-testid="ai-current-changed">{who}</span>{blocked_html}</div>
    <form method="post" action="/api/admin/apollosg-settings/ai-model" data-testid="ai-model-form" class="ai-form">
      <label>Provider<select name="provider" id="ai-provider" data-testid="ai-provider-select">{providers}</select></label>
      <label>Model<select name="model" id="ai-model" data-testid="ai-model-select">{models}</select></label>
      <p class="warn" data-testid="ai-model-warning">Changing this affects future investigations only. Existing results, and
      investigations already running, keep the model they used.</p>
      <p class="muted" id="ai-model-blocked" data-testid="ai-model-blocked"></p>
      <div class="ai-buttons">
        <button type="button" class="btn secondary" id="ai-test" data-testid="ai-model-test">Test this model</button>
        <button class="btn" id="ai-save" data-testid="ai-model-save" disabled>Save</button>
      </div>
      <p class="muted" id="ai-save-hint" data-testid="ai-model-save-hint">Test this model before saving: one fixed, made-up
      sample message is checked the way Magnum DI checks evidence (answer shape and web search). Nobody's data is sent.</p>
      <div id="ai-test-result" data-testid="ai-model-test-result" aria-live="polite"></div>
    </form>
    <p class="muted">Only approved models that can return ApolloSG's fixed answer shape, read images sent as evidence and
    search the web with sources can be saved, cheapest first.</p>
    {unavailable_html}
    <script>(function(){{var models={json.dumps(listed)};var saved={json.dumps([sel['provider'], sel['model']])};
    var p=document.getElementById('ai-provider'),m=document.getElementById('ai-model'),b=document.getElementById('ai-save'),
        t=document.getElementById('ai-test'),r=document.getElementById('ai-test-result'),why=document.getElementById('ai-model-blocked');
    var passed=null;
    function esc(s){{return String(s).replace(/[&<>"']/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];}});}}
    function picked(){{return (models[p.value]||[]).filter(function(x){{return x.id===m.value;}})[0];}}
    function refresh(){{var x=picked();var blocked=x&&x.reasons.length;
      why.textContent=blocked?('Can\\'t be saved — '+x.reasons.join('; ')+'.'):'';
      t.disabled=!x;b.disabled=!x||blocked||!(passed&&passed[0]===p.value&&passed[1]===m.value)||(saved[0]===p.value&&saved[1]===m.value);}}
    p.addEventListener('change',function(){{var list=models[p.value]||[];m.innerHTML='';
    if(!list.length){{var o=document.createElement('option');o.value='';o.disabled=true;o.selected=true;o.textContent='No models available for this provider';m.appendChild(o);}}
    list.forEach(function(x){{var o=document.createElement('option');o.value=x.id;o.textContent=x.label;m.appendChild(o);}});r.innerHTML='';refresh();}});
    m.addEventListener('change',function(){{r.innerHTML='';refresh();}});
    t.addEventListener('click',function(){{var pv=p.value,mv=m.value;t.disabled=true;b.disabled=true;
      r.innerHTML='<p class="muted" data-testid="ai-model-test-running">Testing '+esc(mv)+'… one sample check, usually under a minute.</p>';
      fetch('/api/admin/apollosg-settings/ai-model/test',{{method:'POST',credentials:'same-origin',
        headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:new URLSearchParams({{provider:pv,model:mv}}).toString()}})
      .then(function(res){{return res.json();}}).then(function(d){{
        passed=d.ok?[pv,mv]:null;
        var rows=(d.checks||[]).map(function(c){{return '<li>'+(c.ok?'&#10003; ':'&#10007; ')+esc(c.label)+(c.detail?' <span class="muted">— '+esc(c.detail)+'</span>':'')+'</li>';}}).join('');
        r.innerHTML='<div class="'+(d.ok?'flash':'error')+'" data-testid="ai-model-test-'+(d.ok?'passed':'failed')+'"><p>'+esc(d.message||'')+
          (d.simulated?' <span class="tag" data-testid="ai-model-test-simulated">Simulated</span>':'')+'</p>'+
          (d.simulated?'<p class="muted">Preview: the simulator stood in for the provider, as it does for every AI call here. No call was made.</p>':'')+
          (rows?'<ul>'+rows+'</ul>':'')+'</div>';
        refresh();}})
      .catch(function(){{r.innerHTML='<div class="error" data-testid="ai-model-test-failed"><p>The test couldn\\'t be run. Check your connection and try again.</p></div>';refresh();}});}});
    refresh();}})();</script>"""


_SETTINGS_CSS = (".muted{color:var(--muted);font-size:0.85em;} .current{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin:12px 0;}"
                 " .ai-form{display:flex;flex-direction:column;gap:12px;max-width:520px;margin:12px 0;}"
                 " .ai-form label{display:flex;flex-direction:column;gap:6px;font-weight:600;}"
                 " .ai-form select{background:var(--bg);border:1px solid var(--border);color:var(--fg);border-radius:6px;padding:8px;font-weight:400;}"
                 " .ai-form .btn{align-self:flex-start;} .ai-form .btn[disabled]{opacity:0.5;cursor:not-allowed;}"
                 " .ai-buttons{display:flex;gap:10px;flex-wrap:wrap;} .ai-buttons .btn[disabled]{opacity:0.5;cursor:not-allowed;} .btn.secondary{background:transparent;border:1px solid var(--accent);color:var(--accent);}"
                 " .tag{display:inline-block;border:1px solid #d29922;color:#d29922;border-radius:10px;padding:0 8px;font-size:0.8em;margin-left:6px;}"
                 " #ai-test-result ul{margin:6px 0 0 18px;} #ai-test-result p{margin:4px 0;}"
                 " .warn{border-left:3px solid #d29922;padding:6px 10px;margin:6px 0;font-size:0.9em;}"
                 " .error{border:1px solid var(--red);border-radius:8px;padding:10px 14px;}"
                 " .flash{background:var(--card);border:1px solid var(--green);border-radius:8px;padding:10px 14px;}"
                 " details ul{margin:6px 0 0 20px;} details{margin:8px 0;}")


async def _apollosg_settings(adm: dict, *, flash: str = "", error: str = "", status_code: int = 200) -> HTMLResponse:
    body = _ai_model_section(await ai_settings.selection(), flash, error)
    return HTMLResponse(_shell("ApolloSG Settings", "/api/admin/apollosg-settings", body, admin=adm, extra_css=_SETTINGS_CSS),
                        status_code=status_code)


@router.get("/admin/apollosg-settings", response_class=HTMLResponse)
async def apollosg_settings_page(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    sel = await ai_settings.selection()
    flash = (f"Saved. Magnum DI and TC FlyBy use <strong>{html_mod.escape(_selection_text(sel))}</strong> from the next "
             f"investigation. The change is in the audit log.") if request.query_params.get("saved") else ""
    return await _apollosg_settings(adm, flash=flash)


@router.post("/admin/apollosg-settings/ai-model")
async def apollosg_settings_save_model(request: Request):
    """Save the AI investigation provider and model (services/higgins/ai_settings.py). A model that can't be used is refused."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from urllib.parse import parse_qs
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
    chosen_provider, chosen_model = form.get("provider", ""), form.get("model", "")
    current = await ai_settings.selection()
    reasons = ai_settings.unavailable(chosen_provider, chosen_model)
    if (not reasons and (current["provider"], current["model"]) != (chosen_provider, chosen_model)
            and not await model_test.passed_recently(chosen_provider, chosen_model)):
        return await _apollosg_settings(adm, error=f"Nothing was changed: test {chosen_model} first. It hasn't passed the sample "
                                                   f"check in the last hour.", status_code=400)
    try:
        before = await ai_settings.choose(chosen_provider, chosen_model, adm.get("email", ""))
    except ValueError as exc:
        return await _apollosg_settings(adm, error=f"Nothing was changed: {exc}.", status_code=400)
    if (before["provider"], before["model"]) != (chosen_provider, chosen_model):
        await _audit_log(adm.get("email", ""), "ai_model_change",
                         f"AI investigation model: {_selection_text(before)} → {ai_settings.label(chosen_provider)} · {chosen_model}")
    return RedirectResponse("/api/admin/apollosg-settings?saved=1", status_code=303)


@router.post("/admin/apollosg-settings/ai-model/test")
async def apollosg_settings_test_model(request: Request):
    """Test this model: one safe sample check (services/higgins/model_test.py). Nothing is sent when it can't be used."""
    adm = await _admin(request)
    if not adm:
        return JSONResponse({"ok": False, "message": "Sign in again to test a model."}, status_code=401)
    from urllib.parse import parse_qs
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode("utf-8", "replace")).items()}
    result = await model_test.run(form.get("provider", ""), form.get("model", ""))
    await _audit_log(adm.get("email", ""), "ai_model_test",
                     f"Tested {ai_settings.label(result['provider'])} · {result['model']}: {'passed' if result['ok'] else 'failed'}"
                     + (" (simulated)" if result["simulated"] else ""))
    return JSONResponse(result)


@router.post("/admin/reset-stats")
async def reset_stats(request: Request):
    """Permanently deletes the usage and cost records and zeroes every count (services/stats_reset.py)."""
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    from urllib.parse import parse_qs
    from services.stats_reset import reset_stats as run_reset
    sent = parse_qs((await request.body()).decode("utf-8", "replace")).get("confirm", [""])[0]
    if sent.strip() != "RESET":
        return HTMLResponse("Type RESET to confirm.", status_code=400)
    done = await run_reset()
    detail = (f"{done['gemini_usage']:,} AI usage records, {done['triage_results']:,} triage records, "
              f"{done['trusted_search_usage'] + done['intel_reuse_metrics']:,} search and reuse records and "
              f"{done['investigation_cases']:,} finished investigations deleted; counts zeroed on {done['device_counts']:,} devices")
    await _audit_log(adm.get("email", ""), "reset_stats", detail)
    return RedirectResponse("/api/admin/device-list?reset=done", status_code=303)


# ── Admin Settings ───────────────────────────────────────────────────────────

@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()

    session_count = await db[_SESSIONS].count_documents({})

    body = f"""
    <h2>Admin Account</h2>
    <table>
        <tr><td>Email</td><td><code>{html_mod.escape(adm.get('email',''))}</code></td></tr>
        <tr><td>Name</td><td>{html_mod.escape(adm.get('name',''))}</td></tr>
        <tr><td>Session created</td><td>{_t(adm.get('created_at'))}</td></tr>
        <tr><td>Session expires</td><td>{_t(adm.get('expires_at'))}</td></tr>
        <tr><td>Active sessions</td><td>{session_count}</td></tr>
    </table>
    <p style="margin-top:16px;"><a class="btn" href="/api/admin/apollosg-settings" data-testid="admin-apollosg-settings-link">ApolloSG Settings →</a>
    <span style="color:var(--muted);font-size:0.85em;">AI Provider &amp; Model for investigations</span></p>
    <form method="post" action="/api/admin/logout" style="margin-top:16px;">
        <button class="btn">Sign out</button>
    </form>
    """
    return _shell("Admin", "/api/admin/settings", body, admin=adm)


# ── Reports (HTML + PDF) ────────────────────────────────────────────────────

@router.get("/admin/reports/{report_name}", response_class=HTMLResponse)
async def admin_report(request: Request, report_name: str):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    if report_name not in REPORTS:
        return HTMLResponse("Report not found", status_code=404)
    filename, title = REPORTS[report_name]
    md_file = REPORT_DIR / filename
    if not md_file.exists():
        return HTMLResponse("Report file not found", status_code=404)
    html_body = _render_md(md_file)
    body = f"""
    <div class="topbar-row">
        <a href="/api/admin/portal" style="color:var(--accent);text-decoration:none;">&larr; Dashboard</a>
        <a href="/api/admin/reports/{report_name}/pdf" class="btn btn-sm">Download PDF</a>
    </div>
    <article>{html_body}</article>
    """
    await _audit_log(adm.get("email", ""), "view_report", report_name)
    return _shell(title, f"/api/admin/reports/{report_name}", body, admin=adm)


@router.get("/admin/reports/{report_name}/pdf")
async def admin_report_pdf(request: Request, report_name: str):
    adm = await _admin(request)
    if not adm:
        return _login_redirect()
    if report_name not in REPORTS:
        return HTMLResponse("Report not found", status_code=404)
    filename, title = REPORTS[report_name]
    md_file = REPORT_DIR / filename
    if not md_file.exists():
        return HTMLResponse("Report file not found", status_code=404)

    html_body = _render_md(md_file)
    full_html = _pdf_html(title, html_body, _tz_param(request))

    from xhtml2pdf import pisa
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(full_html), dest=pdf_buffer)
    if pisa_status.err:
        return HTMLResponse("PDF generation failed", status_code=500)
    pdf_buffer.seek(0)

    safe_name = report_name.replace("/", "_")
    await _audit_log(adm.get("email", ""), "download_pdf", report_name)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="apollo_{safe_name}.pdf"'},
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_TZ_NAME = '<span class="tz-name">your local time</span>'

# Times are sent in UTC and shown on the admin's own computer clock, 12-hour, by _LOCAL_TIME_SCRIPT.
_LOCAL_TIME_SCRIPT = """<script>
(function(){
  var styles={full:{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true},
              short:{day:'numeric',month:'short',hour:'numeric',minute:'2-digit',hour12:true}};
  document.querySelectorAll('time.lt').forEach(function(el){var d=new Date(el.getAttribute('datetime'));
    if(!isNaN(d.getTime()))el.textContent=d.toLocaleString(undefined,styles[el.getAttribute('data-f')]||styles.full);});
  var zone=(Intl.DateTimeFormat().resolvedOptions().timeZone)||'your local time';
  document.querySelectorAll('.tz-name').forEach(function(el){el.textContent=zone;});
  var offset=-new Date().getTimezoneOffset();
  document.querySelectorAll('a[href$="/pdf"]').forEach(function(a){a.setAttribute('href',a.getAttribute('href')+'?tz='+offset);});
})();
</script>"""


def _is_time(value: Any) -> bool:
    return isinstance(value, datetime) or (isinstance(value, str) and bool(_ISO.match(value)))


def _t(value: Any, style: str = "full") -> str:
    """A stored time, shown in the admin's own time zone on the 12-hour clock (by _LOCAL_TIME_SCRIPT).
    Without JavaScript the page still reads it, in UTC and labelled as such."""
    dt = local_time.parse(value) if _is_time(value) else None
    if not dt:
        return "—"
    utc = dt.astimezone(timezone.utc)
    fallback = f"{local_time.label(utc, 0)} UTC"
    return f'<time class="lt" data-f="{style}" datetime="{utc.isoformat()}">{fallback}</time>'


def _tz_param(request: Request) -> int:
    """The admin browser's UTC offset in minutes, sent with a PDF link (?tz=). UTC when absent."""
    sent = request.query_params.get("tz", "")
    return local_time.clamp(sent) if re.fullmatch(r"-?\d{1,3}", sent) else 0


def _render_md(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace("\u2705", "[DONE]").replace("\u23f3", "[PENDING]")
    text = text.replace("\u274c", "[NO]")
    return markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])


def _pdf_html(title: str, body: str, tz: int = 0) -> str:
    """A printable admin report. Its times are the admin's local time (the browser's offset, sent as ?tz=)."""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11px; line-height: 1.5; color: #222; padding: 20px; }}
h1 {{ font-size: 18px; margin: 0 0 8px; }} h2 {{ font-size: 14px; margin: 20px 0 8px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }}
h3 {{ font-size: 12px; margin: 14px 0 6px; }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 10px; }}
th, td {{ padding: 4px 6px; border: 1px solid #ccc; text-align: left; }}
th {{ background: #f0f0f0; font-weight: bold; }}
code {{ background: #f5f5f5; padding: 1px 3px; font-size: 10px; }}
pre {{ background: #f5f5f5; padding: 8px; font-size: 9px; overflow-wrap: break-word; }}
strong {{ color: #000; }}
.footer {{ margin-top: 24px; font-size: 9px; color: #999; border-top: 1px solid #ccc; padding-top: 8px; }}
</style></head><body>
<img src="{BANNER_PATH}" width="320" height="109" alt="{BANNER_ALT}" />
<h1>{title}</h1>
<p style="font-size:9px;color:#666;">Generated: {local_time.label(now_utc(), tz)} — ApolloSG Admin Portal. Times are local time ({local_time.zone_label(tz)}).</p>
{body}
<div class="footer">ApolloSG Admin Portal — Confidential</div>
</body></html>"""


def _status_color(status: str) -> str:
    return {"healthy": "#3fb950", "degraded": "#d29922", "down": "#f85149",
            "connected": "#3fb950"}.get(status, "#8b949e")


def _integration_color(status: str) -> str:
    return {CONNECTED: "#3fb950", DEGRADED: "#d29922", NOT_CONFIGURED: "#8b949e",
            UNABLE: "#f85149", OK: "#3fb950", DOWN: "#f85149"}.get(status, "#8b949e")


def _integration_label(status: str) -> str:
    return {CONNECTED: "Connected", DEGRADED: "Degraded", NOT_CONFIGURED: "Not Configured",
            UNABLE: "Unable to Verify", OK: "Connected", DOWN: "Down"}.get(status, "Unknown")


def _status_card(label: str, status: str, detail: str) -> str:
    c = _status_color(status)
    return f"""<div class="s-card"><div class="s-card-head"><span class="dot" style="background:{c};"></span><strong>{html_mod.escape(label)}</strong></div>
    <div class="s-card-status" style="color:{c};">{status.replace('_',' ').title()}</div>
    <div class="s-card-detail">{html_mod.escape(detail)}</div></div>"""


def _mini_status(label: str, status: str, detail: str) -> str:
    c = _status_color(status)
    return f"""<div class="m-card"><span class="dot" style="background:{c};"></span><strong>{html_mod.escape(label)}</strong><br/><span style="font-size:0.82em;color:var(--muted);">{html_mod.escape(detail)}</span></div>"""


def _stat_card(value: str, label: str) -> str:
    return f'<div class="stat-card"><div class="stat-value">{html_mod.escape(str(value))}</div><div class="stat-label">{html_mod.escape(label)}</div></div>'


def _read_logs(count: int = 200) -> str:
    for p in ["/var/log/supervisor/backend-stdout.log", "/var/log/backend.log", "/tmp/backend.log"]:
        try:
            with open(p) as f:
                return html_mod.escape("".join(f.readlines()[-count:]))
        except (FileNotFoundError, PermissionError):
            continue
    return "(No log file found)"


def _ai_mode_badge() -> str:
    """This server's AI mode, at the top of every page: Live AI (the selected provider, billed) or Simulated (the preview
    server — no provider calls). Read from the provider gateway itself, so it can't disagree with what runs."""
    sel = ai_settings.last_known()
    name = ai_settings.label(sel["provider"])
    if provider.get_provider_mode() == "preview":
        cls, label = "mode-sim", "Simulated"
        detail = "Preview server — no AI provider calls are made. AI answers come from the simulator and ApolloSG's knowledge base."
    elif ai_settings.key_configured(sel["provider"]):
        cls, label = "mode-live", "Live AI"
        detail = f"Every AI request on this server goes to {name} ({sel['model']}) and is billed."
    else:
        cls, label = "mode-off", "Live AI — no key"
        detail = f"This server would call {name}, but no {name} key is set, so AI requests fail."
    return (f'<div class="mode-bar {cls}" id="ai-mode-badge" data-mode="{provider.get_provider_mode()}">'
            f'<span class="mode-pill"><span class="dot"></span>{label}</span>'
            f'<span class="mode-detail">{detail}</span></div>')


def _shell(title: str, active_path: str, body: str, *, admin: dict | None = None,
           show_nav: bool = True, extra_css: str = "") -> str:
    nav_html = ""
    if show_nav and admin:
        for label, path, icon in NAV:
            act = " active" if path == active_path else ""
            nav_html += f'<a class="nav-item{act}" href="{path}"><span class="nav-icon">{icon}</span>{label}</a>'
        pic = admin.get("picture", "")
        name = admin.get("name", admin.get("email", "Admin"))
        nav_html += f"""<div class="nav-footer">
            {'<img src="' + pic + '" class="nav-avatar" />' if pic else ''}
            <span class="nav-user">{html_mod.escape(name)}</span>
            <form method="post" action="/api/admin/logout" style="margin:0;"><button class="btn btn-sm" style="width:100%;margin-top:8px;">Sign out</button></form>
        </div>"""

    sidebar = f'<nav class="sidebar">{nav_html}</nav>' if show_nav and admin else ""
    main_cls = "main" if show_nav and admin else "main-full"
    mode_bar = _ai_mode_badge() if admin else ""

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(title)} — ApolloSG Admin</title>
<style>
:root {{ --bg:#0d1117; --fg:#c9d1d9; --muted:#8b949e; --border:#30363d;
         --accent:#58a6ff; --card:#161b22; --green:#3fb950; --red:#f85149; --yellow:#d29922; }}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);line-height:1.6;display:flex;min-height:100vh;}}
.sidebar{{width:220px;background:var(--card);border-right:1px solid var(--border);padding:16px 0;display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;overflow-y:auto;z-index:10;}}
.nav-item{{display:flex;align-items:center;gap:10px;padding:9px 20px;color:var(--muted);text-decoration:none;font-size:0.9em;transition:background 0.15s;}}
.nav-item:hover{{background:rgba(255,255,255,0.04);color:var(--fg);}}
.nav-item.active{{color:#fff;background:rgba(88,166,255,0.1);border-right:2px solid var(--accent);}}
.nav-icon{{width:20px;text-align:center;font-size:1.05em;}}
.nav-footer{{margin-top:auto;padding:16px 20px;border-top:1px solid var(--border);}}
.nav-avatar{{width:28px;height:28px;border-radius:50%;}}
.nav-user{{font-size:0.82em;color:var(--muted);display:block;margin-top:4px;word-break:break-all;}}
.main{{margin-left:220px;padding:24px 32px;flex:1;max-width:960px;}}
.main-full{{padding:24px 32px;flex:1;max-width:960px;margin:0 auto;}}
h2{{font-size:1.15rem;margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--border);color:#fff;}}
h3{{font-size:1rem;margin:20px 0 6px;color:var(--accent);}}
a{{color:var(--accent);text-decoration:none;}} a:hover{{text-decoration:underline;}}
table{{width:100%;border-collapse:collapse;margin:0 0 16px;font-size:0.88em;}}
th,td{{padding:7px 10px;border:1px solid var(--border);text-align:left;}}
th{{background:var(--card);color:#fff;font-weight:600;font-size:0.85em;}}
td{{background:var(--bg);}}
tr:hover td{{background:var(--card);}}
code{{background:var(--card);padding:2px 6px;border-radius:4px;font-size:0.88em;}}
pre{{background:var(--card);padding:12px;border-radius:8px;overflow-x:auto;margin:0 0 16px;border:1px solid var(--border);font-size:0.82em;}}
.btn{{display:inline-block;padding:6px 14px;border-radius:6px;background:var(--card);border:1px solid var(--border);color:var(--fg);cursor:pointer;font-size:0.88em;text-decoration:none;}}
.btn:hover{{border-color:var(--accent);color:#fff;}}
.btn-sm{{padding:4px 10px;font-size:0.8em;}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:12px 0 20px;}}
.stat-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center;}}
.stat-value{{font-size:1.25rem;font-weight:700;color:#fff;}}
.stat-label{{font-size:0.78em;color:var(--muted);margin-top:4px;}}
.status-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin:12px 0;}}
.s-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;}}
.s-card-head{{display:flex;align-items:center;gap:8px;margin-bottom:6px;}}
.s-card-status{{font-size:0.9em;font-weight:600;margin-bottom:4px;}}
.s-card-detail{{font-size:0.82em;color:var(--muted);}}
.mini-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin:12px 0;}}
.m-card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px;}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.78em;font-weight:600;}}
.overall-banner{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 18px;display:flex;align-items:center;gap:12px;margin-bottom:16px;}}
.alert{{padding:12px 16px;border-radius:8px;margin-bottom:12px;font-size:0.9em;}}
.alert-ok{{background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.2);color:var(--green);}}
.alert-warning{{background:rgba(210,153,34,0.08);border:1px solid rgba(210,153,34,0.2);color:var(--yellow);}}
.alert-critical{{background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.2);color:var(--red);}}
.alert ul{{margin:6px 0 0;padding-left:20px;}}
.report-list{{display:flex;flex-direction:column;gap:8px;}}
.report-row{{display:flex;align-items:center;justify-content:space-between;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;}}
.topbar-row{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;margin-bottom:12px;border-bottom:1px solid var(--border);}}
.mode-bar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-radius:8px;padding:8px 14px;margin-bottom:16px;font-size:0.85em;border:1px solid;}}
.mode-pill{{display:inline-flex;align-items:center;gap:6px;font-weight:700;padding:2px 10px;border-radius:10px;white-space:nowrap;}}
.mode-detail{{color:var(--muted);}}
.mode-live{{background:rgba(63,185,80,0.08);border-color:rgba(63,185,80,0.3);}}
.mode-live .mode-pill{{background:rgba(63,185,80,0.15);color:var(--green);}} .mode-live .dot{{background:var(--green);}}
.mode-sim{{background:rgba(210,153,34,0.08);border-color:rgba(210,153,34,0.3);}}
.mode-sim .mode-pill{{background:rgba(210,153,34,0.15);color:var(--yellow);}} .mode-sim .dot{{background:var(--yellow);}}
.mode-off{{background:rgba(248,81,73,0.08);border-color:rgba(248,81,73,0.3);}}
.mode-off .mode-pill{{background:rgba(248,81,73,0.15);color:var(--red);}} .mode-off .dot{{background:var(--red);}}
.log-box{{max-height:60vh;overflow-y:auto;white-space:pre-wrap;word-break:break-all;line-height:1.4;}}
.spinner{{width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto;}}
@keyframes spin{{to{{transform:rotate(360deg);}}}}
article table{{width:100%;}} article h1{{font-size:1.5rem;}} article h2{{font-size:1.2rem;}} article h3{{font-size:1rem;}}
@media(max-width:700px){{.sidebar{{width:180px;}} .main{{margin-left:180px;padding:16px;}} }}
{extra_css}
</style></head><body>
{sidebar}
<div class="{main_cls}">{mode_bar}{body}</div>
{_LOCAL_TIME_SCRIPT}
</body></html>"""
