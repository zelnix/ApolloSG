"""ApolloSG User Guide — the single authoritative source for how ApolloSG works
and how users operate it.

This module powers:
  • Higgins' answers to product questions (via task lookup)
  • The user-facing ApolloSG User Guide screen (via GUIDE_SECTIONS)
  • Product-help navigation (via task routes)
  • Automated tests (via task IDs and expected questions)

Structure: tasks organised by section, each containing:
  name, questions (common user phrasings), what_it_does, steps, route, fallbacks,
  platform, limitations, related.

Higgins selects the relevant task(s) for a question and extracts the minimum answer.
A keyword match never means 'display this whole section.'
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

# ── Guide entry ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GuideTask:
    id: str
    name: str
    section: str
    questions: tuple[str, ...]         # common user phrasings this task answers
    what_it_does: str                  # 1-2 sentence explanation
    steps: tuple[str, ...] = ()        # ordered steps to do it
    route: str = ""                    # primary deep link
    route_label: str = ""              # human label for the route
    fallbacks: tuple[str, ...] = ()    # when the primary path isn't available
    platform: str = ""                 # "Android", "iOS", "" = both
    limitations: tuple[str, ...] = ()  # honest limitations
    related: tuple[str, ...] = ()      # IDs of related tasks
    last_verified: str = "2026-11"     # year-month of last review

# ── Sections and tasks ───────────────────────────────────────────────────────

TASKS: list[GuideTask] = [
    # ── Getting Started ──
    GuideTask(
        id="getting_started", name="Getting started", section="Getting Started",
        questions=("how do I set up apollosg", "how do I get started", "first time setup", "how to start using apollo"),
        what_it_does="Set up ApolloSG: accept the privacy statement, turn on protections, and run your first check.",
        steps=("Open ApolloSG.", "Read and accept the privacy statement.", "Choose which protections to turn on.", "Run your first check — tap Check It and pick what to check."),
        route="/(tabs)/home", route_label="Home",
    ),
    # ── Home ──
    GuideTask(
        id="home", name="Home screen", section="Home",
        questions=("what does the home screen show", "what is on the home page", "what does the main screen do"),
        what_it_does="Shows your current protection status, recent activity, and anything that needs your attention.",
        route="/(tabs)/home", route_label="Home",
    ),
    # ── Check It ──
    GuideTask(
        id="check_it", name="Check It", section="Check It",
        questions=("what can I check", "how do I check something", "what checks are available", "where do I go to check"),
        what_it_does="The hub for all manual checks: messages, links, emails, files, calls, apps, screenshots, your device and your internet.",
        route="/(tabs)/check-it", route_label="Check It",
    ),
    # ── Sharing ──
    GuideTask(
        id="sharing", name="Sharing into ApolloSG", section="Sharing",
        questions=(
            "how do I share something into apollosg", "how do I share to apollo", "how can I send something to apollosg",
            "how do I share a message", "how do I send apollo a screenshot", "can I share something from another app",
            "how do I get something into apollo for checking", "share into apollo", "send to apollo",
            "how do I share a link to apollo", "how do I add something to apollo",
        ),
        what_it_does="Send content from another app to ApolloSG for checking, using your phone's Share function.",
        steps=(
            "Open the message, link, screenshot or other item in the app you're using.",
            "Tap Share (the share icon).",
            "Choose ApolloSG from the share sheet.",
            "ApolloSG opens, shows what it received, and waits for you to confirm.",
        ),
        route="/message", route_label="Check a message",
        fallbacks=(
            "If ApolloSG isn't in the Share menu, copy and paste the content into ApolloSG instead.",
            "You can also take a screenshot and check that.",
        ),
        related=("share_troubleshoot", "check_message", "check_screenshot"),
    ),
    GuideTask(
        id="share_troubleshoot", name="ApolloSG not in Share menu", section="Sharing",
        questions=(
            "apollo isn't in my share menu", "apollosg not showing in share", "can't find apollo in share",
            "share menu doesn't show apollo", "apollo not in sharing options",
        ),
        what_it_does="Troubleshoot when ApolloSG doesn't appear in another app's Share menu.",
        steps=(
            "Make sure ApolloSG is installed as an app (not just a web shortcut).",
            "Some apps don't offer Share for every content type — use copy/paste or a screenshot instead.",
            "On Android, you can long-press ApolloSG in the share sheet to pin it to the top.",
        ),
        fallbacks=("Copy and paste the content into ApolloSG.", "Take a screenshot and check that instead."),
        related=("sharing",),
    ),
    # ── Messages ──
    GuideTask(
        id="check_message", name="Check a message", section="Messages",
        questions=("how do I check a message", "check a text", "where do I paste a message", "check sms"),
        what_it_does="Check whether a text message or chat message is suspicious. Paste it, share it, or screenshot it.",
        steps=("Open Check It or tap Check a message.", "Paste the message text or share it from the messaging app.", "Apollo analyses it and shows the result."),
        route="/message", route_label="Check a message",
        related=("sharing", "check_screenshot"),
    ),
    # ── Links ──
    GuideTask(
        id="check_link", name="Check a link", section="Links",
        questions=("how do I check a link", "check a url", "is this link safe", "where do I check a website"),
        what_it_does="Check where a link really goes and whether it's safe, before you tap it.",
        steps=("Copy the link.", "Open Check It and tap Check a link.", "Paste the link.", "Apollo resolves where it goes and checks it."),
        route="/check", route_label="Check a website link",
    ),
    # ── Screenshots ──
    GuideTask(
        id="check_screenshot", name="Check a screenshot", section="Screenshots",
        questions=("how do I check a screenshot", "can I check a photo", "check an image", "screenshot check"),
        what_it_does="Check a screenshot or photo of something suspicious — a text, email, social media post, or anything else.",
        steps=("Take a screenshot of the suspicious item.", "Open Check It and tap Check a screenshot.", "Pick the screenshot from your photos.", "Apollo reads and analyses it."),
        route="/vision", route_label="Check a screenshot",
    ),
    # ── Emails ──
    GuideTask(
        id="check_email", name="Check an email", section="Emails",
        questions=("how do I check an email", "check my email", "email checking", "connect gmail"),
        what_it_does="Check a single email by pasting or sharing it, or connect your Gmail for ongoing checking.",
        steps=("Open Check It and tap Check an email.", "Paste or share the email — or connect your Gmail for automatic checks."),
        route="/email", route_label="Check an email",
    ),
    # ── Calls / Numbers ──
    GuideTask(
        id="check_number", name="Check a phone number", section="Calls",
        questions=("how do I check a phone number", "check a number", "who called me", "is this number safe"),
        what_it_does="Check the reputation of a phone number — whether it's been reported, spoofed, or associated with scams.",
        steps=("Open Check It and tap Check a number.", "Type or paste the phone number.", "Apollo checks it against known sources."),
        route="/call-guard", route_label="Check a number",
        related=("call_screening",),
    ),
    GuideTask(
        id="call_screening", name="Call screening", section="Calls",
        questions=("how do I turn on call screening", "call screener", "screen incoming calls", "default call screener"),
        what_it_does="On Android, ApolloSG can screen incoming calls automatically. iOS does not allow third-party call screening.",
        steps=("Go to Settings.", "Set ApolloSG as your default Caller ID & spam app.", "Incoming calls from unknown numbers are checked automatically."),
        platform="Android",
        limitations=("iOS: Apple does not allow any app to be the call screener. Use manual number checks instead.",),
        related=("check_number",),
    ),
    # ── Files ──
    GuideTask(
        id="check_file", name="Check a file", section="Files",
        questions=("how do I check a file", "check a download", "is this file safe", "check attachment"),
        what_it_does="Check whether a downloaded file or email attachment is safe before opening it.",
        steps=("Open Check It and tap Check a file.", "Pick the file from your device.", "Apollo inspects it."),
        route="/file", route_label="Check a file",
    ),
    # ── Apps ──
    GuideTask(
        id="check_app", name="Check an app", section="Apps",
        questions=("how do I check an app", "is this app safe", "check installed app", "app safety"),
        what_it_does="Check whether an installed app or an app you're considering is safe.",
        steps=("Open Check It and tap Check an app.", "Pick the app or enter its details.", "Apollo checks permissions, source and developer."),
        route="/app-check", route_label="Check an app",
    ),
    # ── Protections ──
    GuideTask(
        id="protections", name="Your protections", section="Protections",
        questions=("what protections do I have", "is my protection on", "which protections are active", "view protections"),
        what_it_does="See every protection ApolloSG provides and its real status: active, ready, or unavailable.",
        route="/(tabs)/guard", route_label="Your protections",
    ),
    # ── Threats ──
    GuideTask(
        id="threats", name="Threats", section="Threats",
        questions=("where are my threats", "view threat cases", "what threats has apollo found", "threat list"),
        what_it_does="Every threat Apollo has found or you've checked — with full details, evidence and investigation results.",
        route="/(tabs)/patrol", route_label="Threats",
    ),
    # ── Ask Higgins ──
    GuideTask(
        id="ask_higgins", name="Ask Higgins", section="Ask Higgins",
        questions=("what can I ask higgins", "how do I talk to higgins", "ask a question", "chat with higgins"),
        what_it_does="Ask Higgins anything about scams, ApolloSG, or your device's security. Higgins explains in plain English.",
        route="/(tabs)/ask", route_label="Ask Higgins",
    ),
    # ── Investigations ──
    GuideTask(
        id="investigations", name="Investigations (TC FlyBy / Magnum DI)", section="Investigations",
        questions=("what is tc flyby", "what is magnum di", "how do investigations work", "what happens after triage"),
        what_it_does="When a check can't be settled by rules alone, TC FlyBy investigates quickly. If more depth is needed, Magnum DI takes over. You see the findings in your Threat Case.",
        route="/(tabs)/patrol", route_label="Threats",
    ),
    # ── Scam Alerts ──
    GuideTask(
        id="scam_alerts", name="Scam Alerts", section="Scam Alerts",
        questions=("what are scam alerts", "where do I see scam alerts", "government scam warnings"),
        what_it_does="Current scam campaigns from government sources (Australia, USA, UK, EU), each analysed from the source itself.",
        route="/(tabs)/scams", route_label="Scam Alerts",
    ),
    # ── Learn ──
    GuideTask(
        id="learn", name="Learn with Higgins", section="Learn",
        questions=("learn about scams", "scam education", "how do scams work", "what is phishing"),
        what_it_does="Articles and guides about scams and cybersecurity, explained by Higgins in plain English.",
        route="/higgins/learning", route_label="Learn with Higgins",
    ),
    # ── History ──
    GuideTask(
        id="history", name="Patrol history", section="History",
        questions=("where is my history", "check history", "past checks", "activity log"),
        what_it_does="A record of Apollo's detection, protection and device security activity on this device.",
        route="/patrol/history", route_label="Patrol history",
    ),
    # ── Privacy ──
    GuideTask(
        id="privacy", name="Privacy and personal data", section="Privacy",
        questions=("what does apollo store", "is my data private", "what information does apollo share",
                   "does anything leave my device", "who can see my data", "privacy policy",
                   "what personal data does apollo collect", "how long is my data retained",
                   "what happens to my screenshots", "are my messages stored"),
        what_it_does="ApolloSG has no account, no email, no ad tracking. Checks run on-device first. Only what the assessment needs leaves the device, only for that one assessment.",
        steps=(
            "No account or email required — anonymous device ID only.",
            "Checks run on-device first; only assessment data leaves the device temporarily.",
            "Credentials, verification codes and secret URL fragments are stripped before sending.",
            "Cases keep summary and safe references — not full messages, screenshots or files.",
            "Background access and mailbox connections each need separate opt-in.",
        ),
        route="/privacy-data", route_label="What ApolloSG stores",
        related=("privacy_statement",),
    ),
    GuideTask(
        id="privacy_statement", name="Privacy statement", section="Privacy",
        questions=("where is the privacy statement", "privacy disclosure", "full privacy policy"),
        what_it_does="The full privacy statement explains exactly what ApolloSG collects, processes and shares.",
        route="/privacy-disclosure", route_label="Privacy statement",
    ),
    # ── Device ──
    GuideTask(
        id="check_device", name="Check my device", section="Device",
        questions=("check my device", "is my device secure", "device security check", "screen lock check"),
        what_it_does="Check your device's security settings: screen lock, biometrics, OS updates and more.",
        route="/device", route_label="Check my device",
    ),
    # ── Network ──
    GuideTask(
        id="check_network", name="Check my internet", section="Network",
        questions=("check my internet", "is my wifi safe", "network check", "vpn check"),
        what_it_does="Check your current Wi-Fi or mobile connection for security issues.",
        route="/network", route_label="Check my internet",
    ),
    # ── Settings ──
    GuideTask(
        id="settings", name="Settings", section="Settings",
        questions=("where are settings", "open settings", "change settings", "configure apollo"),
        what_it_does="Everything configurable: protections, alerts, accounts, data, diagnostics, help and policies.",
        route="/(tabs)/settings", route_label="Settings",
    ),
    # ── Sample Checks ──
    GuideTask(
        id="sample_checks", name="Sample checks", section="Testing",
        questions=("what are sample checks", "try a sample", "test apollo", "sample check"),
        what_it_does="Exercise ApolloSG's real production pipeline with known sample threats. The input is a sample; Apollo's processing is real.",
        route="/sample-checks", route_label="Sample checks",
    ),
    # ── Troubleshooting ──
    GuideTask(
        id="troubleshoot_general", name="General troubleshooting", section="Troubleshooting",
        questions=("something isn't working", "apollo isn't working", "help", "problem with apollo"),
        what_it_does="Get help with ApolloSG. Check your protections, restart the app, or contact support.",
        route="/support", route_label="Get help",
    ),
]

# Index by ID for fast lookup
TASK_BY_ID: dict[str, GuideTask] = {t.id: t for t in TASKS}

# Index by section for the User Guide screen
GUIDE_SECTIONS: list[tuple[str, list[GuideTask]]] = []
_section_order: list[str] = []
for _t in TASKS:
    if _t.section not in _section_order:
        _section_order.append(_t.section)
for _s in _section_order:
    GUIDE_SECTIONS.append((_s, [t for t in TASKS if t.section == _s]))


# ── Task lookup for Higgins ──────────────────────────────────────────────────

def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()


def find_tasks(question: str, limit: int = 3) -> list[GuideTask]:
    """Find the most relevant tasks for a user question.
    Scores each task by how many of the task's question phrasings overlap with the query."""
    q = _normalise(question)
    q_words = set(q.split())
    scored: list[tuple[float, GuideTask]] = []
    for task in TASKS:
        best = 0.0
        for phrasing in task.questions:
            p_words = set(_normalise(phrasing).split())
            if not p_words:
                continue
            overlap = len(q_words & p_words) / max(len(p_words), 1)
            best = max(best, overlap)
        # Also check against the task name
        name_words = set(_normalise(task.name).split())
        name_overlap = len(q_words & name_words) / max(len(name_words), 1)
        best = max(best, name_overlap)
        if best > 0.3:
            scored.append((best, task))
    scored.sort(key=lambda x: -x[0])
    return [task for _, task in scored[:limit]]


def task_answer(task: GuideTask) -> str:
    """Build a concise answer from a guide task. Direct Answer First."""
    parts: list[str] = [task.what_it_does]
    if task.steps:
        parts.append("\n".join(f"{i+1}. {s}" for i, s in enumerate(task.steps)))
    if task.fallbacks:
        parts.append("\n".join(task.fallbacks))
    if task.limitations:
        parts.append("\n".join(f"Note: {l}" for l in task.limitations))
    return "\n\n".join(parts)


def guide_answer(question: str) -> dict | None:
    """Find the best guide task(s) for a question and return a concise answer.
    Returns None if no task matches well enough."""
    tasks = find_tasks(question, limit=2)
    if not tasks:
        return None
    primary = tasks[0]
    answer = task_answer(primary)
    # If a second task is relevant AND different, append briefly
    if len(tasks) > 1 and tasks[1].section != primary.section:
        secondary = tasks[1]
        answer += f"\n\n{secondary.name}: {secondary.what_it_does}"
    navigate = [primary.route] if primary.route else []
    if len(tasks) > 1 and tasks[1].route and tasks[1].route not in navigate:
        navigate.append(tasks[1].route)
    return {"answer": answer, "navigate": navigate[:2], "limitation": False, "task_id": primary.id}
