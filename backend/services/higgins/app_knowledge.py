"""Authoritative Apollo product knowledge for Higgins.

Higgins is the savant of Apollo and of scams. That requires one written source of
truth about the product itself: what every screen is, where it lives, what each
check does, how the flows work and what the privacy rules are. This module is
that source.

Exports:

* ``knowledge_block(modules)`` — curated text injected into Higgins turns, with
  only the classifier-selected modules included.  The permanent core (roles,
  protection names) is always present; conditional modules are included when
  the classifier determines the question needs them.
* ``NAV_ROUTES`` / ``valid_route()`` — the deep-link allow-list, always complete
  regardless of which modules the prompt includes.
* ``ROUTE_GROUPS`` — the segmented route registry used by the classifier.

The route strings mirror the Expo Router file tree in ``frontend/app``. Keep the
two in step: a route removed from the app must be removed here, or Higgins will
offer a tap that goes nowhere.
"""
from __future__ import annotations

from typing import Sequence

# ── Deep-link allow-list ─────────────────────────────────────────────────────
# route → the words a person would tap. Dynamic routes (/patrol/[id] and the
# like) are deliberately absent: they need an id Higgins does not hold.

NAV_ROUTES: dict[str, str] = {
    # Main tabs
    "/(tabs)/home": "Home",
    "/(tabs)/patrol": "Threats",
    "/(tabs)/scams": "Scam Alerts",
    "/(tabs)/ask": "Ask Higgins",
    "/(tabs)/settings": "Settings",
    "/(tabs)/check-it": "Check It",
    "/(tabs)/guard": "Your protections",
    "/(tabs)/protection": "Protections",
    "/(tabs)/learn": "Learn",
    # Manual checks
    "/message": "Check a message",
    "/check": "Check a website link",
    "/file": "Check a file",
    "/call-guard": "Check a number",
    "/scan": "Scan a code",
    "/email": "Check an email",
    "/app-check": "Check an app",
    "/account": "Check an account alert",
    "/device": "Check my device",
    "/device-protection": "Device capabilities",
    "/network": "Check my internet",
    "/vision": "Check a screenshot",
    "/text-guard": "Message screening",
    "/recheck": "Re-check my device",
    # Records and history
    "/patrol/history": "Threat history",
    "/saved-checks": "Saved checks",
    "/saved-reports": "Saved reports",
    "/higgins/history": "Conversation history",
    "/app-reports": "App reports",
    "/digest": "Weekly digest",
    "/account-monitor": "Account monitoring",
    # Learning and alerts
    "/higgins/learning": "Learn with Higgins",
    "/higgins/scams": "Scam Alerts",
    "/how-apollo-checks": "How Apollo checks",
    "/alerts": "Your alerts",
    # Protections
    "/gates": "All protections",
    # Records, samples and help
    "/patrol/search": "Search cases",
    "/sample-checks": "Sample checks",
    "/user-guide": "User Guide",
    "/privacy": "Privacy",
    # Settings and policies
    "/settings/personal-data": "My personal data",
    "/settings/email-accounts": "Email accounts",
    "/settings/feed-health": "Feed health",
    "/settings/rule-book": "Rule book",
    "/privacy-data": "What ApolloSG stores",
    "/privacy-disclosure": "Privacy statement",
    "/third-party-register": "Third-party services",
    "/compliance-matrix": "Compliance matrix",
    "/notification-check": "Notification check",
    "/family": "Family sharing",
    "/support": "Get help with ApolloSG",
}


def valid_route(route: str) -> bool:
    """True when the route is a real Apollo destination Higgins may offer."""
    return route in NAV_ROUTES


def route_label(route: str) -> str:
    return NAV_ROUTES.get(route, "")


def navigation(routes: list[str], limit: int = 2) -> list[tuple[str, str]]:
    """(route, label) for the first `limit` genuine Apollo destinations, each once, so a tap never lands nowhere."""
    out: list[tuple[str, str]] = []
    for route in routes:
        candidate = str(route or "").strip()
        if valid_route(candidate) and all(candidate != taken for taken, _ in out):
            out.append((candidate, route_label(candidate)))
        if len(out) == limit:
            break
    return out


# ── Route groups (classifier picks relevant slices) ──────────────────────────

ROUTE_GROUPS: dict[str, dict[str, str]] = {
    "tabs": {
        "/(tabs)/home": "Home — protection status, recent activity",
        "/(tabs)/patrol": "Threats — every threat found or checked",
        "/(tabs)/scams": "Scam Alerts — government feed campaigns",
        "/(tabs)/ask": "Higgins — this conversation",
        "/(tabs)/settings": "Settings — everything configurable",
        "/(tabs)/check-it": "Check It — hub for all manual checks",
        "/(tabs)/guard": "Your protections — every protection and its real status",
    },
    "checks": {
        "/message": "Check a message — paste, screenshot, or share from apps that offer Share",
        "/check": "Check a website link — see where it really goes",
        "/file": "Check a file — a download or attachment",
        "/call-guard": "Check a number — type/paste a number, Calls Apollo screened (Android), call screener setup",
        "/scan": "Scan a code — QR code or barcode",
        "/email": "Check an email — plus connect Gmail for ongoing checking",
        "/app-check": "Check an app — installed or being considered",
        "/account": "Check an account alert — login/breach/recovery warning",
        "/device": "Check my device — screen lock, biometrics, OS updates",
        "/device-protection": "Device capabilities — what this device protects by itself, what ApolloSG may use, what the OS withholds, and which native settings to turn on",
        "/network": "Check my internet — current Wi-Fi or mobile connection",
        "/vision": "Check a screenshot — any picture of something suspicious",
        "/text-guard": "Message screening — paste text or turn on auto-screening (Android)",
        "/recheck": "Re-check my device — repeat checks and compare",
    },
    "records": {
        "/patrol/history": "Threat history — full record including resolved",
        "/saved-checks": "Saved checks — kept with original analysis",
        "/saved-reports": "Saved reports — completed investigation briefings (TC Hawkeye or Magnum DI) on this phone",
        "/higgins/history": "Conversation history — past Higgins conversations",
        "/app-reports": "App reports — results of app checks",
        "/digest": "Weekly digest — the week in one summary",
        "/account-monitor": "Account monitoring — email breach monitoring (weekly)",
    },
    "settings": {
        "/(tabs)/settings": "Settings — eight groups below",
        "/gates": "View all protections — every protection and its real status",
        "/notification-check": "Notification check",
        "/settings/email-accounts": "Email accounts",
        "/family": "Family sharing",
        "/settings/personal-data": "My personal data",
        "/settings/feed-health": "Feed health — sync status of each government feed",
        "/settings/rule-book": "Rule book — every rule Apollo, TC Hawkeye, Magnum DI and Higgins follow, word for word",
        "/privacy-data": "What ApolloSG stores",
        "/privacy-disclosure": "Privacy statement",
        "/third-party-register": "Third-party services",
        "/compliance-matrix": "Compliance matrix",
        "/support": "Get help with ApolloSG",
    },
    "learning": {
        "/higgins/learning": "Learn with Higgins — article library on scams",
        "/higgins/scams": "Scam Alerts — government feeds",
        "/how-apollo-checks": "How Apollo checks — the rules Apollo, Higgins Triage, TC Hawkeye, Magnum DI and Higgins follow, and what each result means",
    },
}


def _render_route_group(name: str) -> str:
    """Render one route group as compact text."""
    routes = ROUTE_GROUPS.get(name, {})
    if not routes:
        return ""
    lines = [f"{name.upper()} ROUTES:"]
    for route, desc in routes.items():
        lines.append(f"- `{route}` — {desc}")
    return "\n".join(lines)


# ── Knowledge modules ────────────────────────────────────────────────────────
# Each module is a named block of product knowledge. The permanent core is
# always included; conditional modules are included when the classifier says so.

# PERMANENT: role separation (always in prompt — safety invariant)
_ROLES = """WHO DOES WHAT — NEVER BLUR THESE:
- APOLLO: protection and detection. Watches, detects, blocks, records. Acts on the device.
- TC FLYBY: fast, low-cost investigation. Checks official sources, ApolloSG's knowledge base and one targeted search, and stops as soon as more checking couldn't change the answer. When it settles a check, Magnum DI is not called.
- MAGNUM DI: deep investigation, only when TC Hawkeye can't settle something that could change the answer. Examines just what's still open and produces the full briefing.
- You do NOT investigate or search externally.
- HIGGINS (you): knows this app completely and knows scams. Explains, guides, navigates, hands off. When investigation is needed, say so and hand it to Apollo's investigators (TC Hawkeye first, Magnum DI only if needed)."""

# PERMANENT: protection names (always needed for snapshot interpretation)
_PROTECTION_NAMES = """USER-FACING PROTECTIONS:
- Websites & Links — automatic blocking + manual link checking
- Messages & Calls — message screening + call/number risk checks
- Email & Accounts — email monitoring + account compromise checks
- Apps & Files — app and file safety checks
- Device & Internet — device settings + network monitoring
- Vision — photograph/screenshot safety checks
A 'ready' or 'manual checks available' gate is NOT offline. Only 'offline' or 'unavailable/service_down' means offline."""

# CONDITIONAL: screens and routes (classifier picks relevant groups)
def _screens_block(route_groups: Sequence[str]) -> str:
    """Build the screens/routes section from classifier-selected groups."""
    if not route_groups:
        return ""
    parts = ["APOLLO DESTINATIONS (selected for this question):"]
    for group in route_groups:
        rendered = _render_route_group(group)
        if rendered:
            parts.append(rendered)
    parts.append("Only offer routes from the list above. At most two per answer, only when the destination genuinely answers the question.")
    return "\n\n".join(parts)

# CONDITIONAL: how flows work
_FLOWS = """HOW APOLLO'S FLOWS WORK:
- Sharing into ApolloSG: in apps that offer Share, tap Share and choose ApolloSG. Not every app offers Share — copy/paste or a screenshot always works. ApolloSG asks which app, shows what it received, waits for confirmation.
- One case per check: checking the same thing twice reuses and updates the existing case.
- Triage then investigation: every check runs deterministic triage first (rules + reputation, no AI). If clean, that's the answer. If possible threat or inconclusive, it is investigated: TC Hawkeye first, and Magnum DI only if a deeper look could change the answer. The full rules are on the How Apollo checks screen.
- Deliberate checks escalate; background screening stays deterministic and never silently starts an investigation.
- Phone numbers in checked messages/emails/screenshots are extracted and reputation-checked during triage.
- Apollo states: Patrolling (clear), Sniffing (looking closer), Growling (possible concern), Barking (significant concern), Biting (confirmed block).
- Setup: welcome → privacy statement → turn on protections → first check.
- Evidence on-device: original item + redacted analysis copy, viewable side by side."""

# CONDITIONAL: privacy rules
_PRIVACY = """APOLLO'S PRIVACY RULES (state accurately):
- No account, no email, no ad tracking. Anonymous device ID only.
- Checks run on-device first. Only what the assessment needs leaves the device, only for that one assessment.
- Credentials, verification codes, secret URL fragments stripped before sending.
- Cases keep summary and safe references — not full messages, screenshots, files or tokens.
- Conversations and speech: encrypted, max 15 minutes on server. Clearing temporary history invalidates immediately.
- Background access, mailbox connections, ongoing monitoring each need separate opt-in.
- Phone number shared only if added for family calling.
- Full details: Privacy statement `/privacy-disclosure`, What ApolloSG stores `/privacy-data`, Third-party services `/third-party-register`."""

# CONDITIONAL: call screening detail
_CALL_SCREENING = """CALL SCREENING:
- Android: ApolloSG can become default call screener via Settings > Default apps > Caller ID & spam blocking. Offered during setup and on Check a number `/call-guard`.
- Android: "Calls Apollo screened" on `/call-guard` lists the incoming numbers Android passed to Apollo's call screening (usually numbers not in contacts), kept on the phone for up to 30 days; tap one to check it. Apollo does not read the call log or SMS inbox in this version — never offer "pick from your call log" or "pick from your inbox".
- Text Gate (Android) checks new texts through opt-in notification access. Otherwise: paste the text, use a screenshot, or Share → ApolloSG where the source app offers Share.
- iOS: Apple provides no equivalent. No app can be the call screener. ApolloSG works from numbers the person checks and a blocked-number list. Say this plainly; never imply parity."""

# CONDITIONAL: settings structure
_SETTINGS_DETAIL = """SETTINGS `/(tabs)/settings` — eight groups:
1. Protection — View all protections `/gates`.
2. Alerts — notification permission, Notification check, alert preview, quiet hours.
3. Accounts & family — Email accounts, Family sharing, trusted links.
4. Your data — Personal data, What ApolloSG stores, clear Threat history.
5. App — battery saver, show why each result was settled (one line naming the settling rule, on by default), minimise ApolloSG, retrofit past investigations.
6. Diagnostics — Feed health `/settings/feed-health`: each government feed's last successful sync, records loaded, last error, and a Healthy / Stale (no sync in 24 hours) / Failing badge.
7. Help & about — Get help, how to share into ApolloSG, About ApolloSG, Rule book `/settings/rule-book` (the full rules, word for word; also linked from How Apollo checks).
8. Policies — Privacy statement, Third-party services, Compliance matrix."""


# ── Module registry ──────────────────────────────────────────────────────────
# Keys match what the classifier returns in knowledge_modules.

KNOWLEDGE_MODULES: dict[str, str] = {
    "flows": _FLOWS,
    "privacy": _PRIVACY,
    "call_screening": _CALL_SCREENING,
    "settings_detail": _SETTINGS_DETAIL,
}


def knowledge_block(
    modules: Sequence[str] = (),
    route_groups: Sequence[str] = (),
) -> str:
    """Build the Apollo knowledge section for the Higgins prompt.

    Args:
        modules: Which conditional knowledge modules to include (e.g. ["flows", "privacy"]).
        route_groups: Which route groups to include (e.g. ["checks", "settings"]).

    The permanent core (_ROLES, _PROTECTION_NAMES) is always included regardless
    of the arguments.
    """
    parts: list[str] = [
        "=== APOLLO PRODUCT KNOWLEDGE (authoritative) ===",
        _ROLES,
        _PROTECTION_NAMES,
    ]

    # Conditional route groups
    screens = _screens_block(route_groups)
    if screens:
        parts.append(screens)

    # Conditional knowledge modules
    for mod in modules:
        text = KNOWLEDGE_MODULES.get(mod)
        if text:
            parts.append(text)

    parts.append("=== END APOLLO PRODUCT KNOWLEDGE ===")
    return "\n\n".join(parts)
