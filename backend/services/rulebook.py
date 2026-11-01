"""Apollo's rule book — one shared file, `content/rulebook.md`, read word for word by the app (Settings → Rule
book) and the admin portal — and the one plain sentence each result shows for the rule that settled it.

Kept in step with the code: `content/rulebook.lock.json` records a fingerprint of every file that defines a
rule or process, on the server and on the phone (Ask Higgins). `tests/test_rulebook.py` fails as soon as one
of them changes, until the book has been reviewed and re-stamped with `python scripts/rulebook_stamp.py`.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from services.higgins import outcomes

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
BOOK = BACKEND / "content" / "rulebook.md"
LOCK = BACKEND / "content" / "rulebook.lock.json"

# Every file that defines a rule or process the book describes (paths from the project root).
WATCHED = (
    "backend/content/triage_catalogue.json",
    "backend/services/triage/engine.py",
    "backend/services/triage_engine.py",
    "backend/services/patrol_policy.py",
    "backend/services/higgins/tc_flyby/__init__.py",
    "backend/services/higgins/tc_flyby/triage.py",
    "backend/services/higgins/tc_flyby/official.py",
    "backend/services/higgins/tc_flyby/patterns.py",
    "backend/services/higgins/tc_flyby/search.py",
    "backend/services/higgins/tc_flyby/decide.py",
    "backend/services/higgins/coordinator.py",
    "backend/services/higgins/validation.py",
    "backend/services/higgins/outcomes.py",
    "backend/services/higgins/jobs.py",
    "backend/services/higgins/presenter.py",
    "backend/services/higgins/chat.py",
    # Higgins' plain English and its Fidelity Check.
    "backend/services/higgins/explain/__init__.py",
    "backend/services/higgins/explain/facts.py",
    "backend/services/higgins/explain/render.py",
    "backend/services/higgins/explain/fidelity.py",
    "backend/services/higgins/explain/words.py",
    "backend/services/rulebook.py",
    # Ask Higgins: what the server does with a chat message, and what it keeps.
    "backend/services/higgins/pipeline_submit.py",
    "backend/services/higgins/context.py",
    # Ask Higgins on the phone: where a message goes, the check forms, handoffs, memory and suggestions.
    "frontend/app/(tabs)/ask.tsx",
    "frontend/src/higgins/checkIntent.ts",
    "frontend/src/higgins/intentRouter.ts",
    "frontend/src/higgins/localResponder.ts",
    "frontend/src/higgins/issueExplanation.ts",
    "frontend/src/higgins/followUp.ts",
    "frontend/src/higgins/chatMemory.ts",
    "frontend/src/higgins/quickQuestions.ts",
    "frontend/src/higgins/starterMemoryCore.ts",
    "frontend/src/components/HigginsCheckSheet.tsx",
    "frontend/src/components/HigginsArtifactInput.tsx",
    "frontend/src/investigation/resubmit.ts",
    # Privacy and redaction: what is removed on the phone and the server, what may leave the phone, what is kept.
    "backend/core/redaction.py",
    "backend/services/higgins/llm_boundary.py",
    "backend/services/higgins/capacity.py",
    "backend/services/higgins/retention.py",
    "backend/services/higgins/repository.py",
    "frontend/src/store/imageEvidence.ts",
    "frontend/src/domain/privacyPolicy.ts",
    "frontend/src/domain/privacy.ts",
    "frontend/src/domain/imagePrivacy.ts",
    "frontend/src/store/personalDataStore.ts",
    # Apollo's knowledge base: trusted sources, Tavily maintenance, the page checks, search and quoting.
    "backend/services/apollo_kb.py",
    "backend/services/kb_sources.py",
    "backend/services/tavily_client.py",
    "backend/services/higgins/knowledge.py",
    # Reusable intelligence (not KB knowledge) and the sufficiency check, and the call sites that reuse it.
    "backend/services/reusable_intel.py",
    "backend/services/sufficiency.py",
    "backend/services/phonerisk.py",
    "backend/services/urlrisk.py",
    "backend/services/rdap.py",
    "frontend/src/domain/checkedAgo.ts",
    # Your data: what is kept on the phone and the server, for how long, and Delete My Apollo Data.
    "backend/services/account_deletion.py",
    "backend/services/family_assist/sessions.py",
    "backend/core/config.py",
    "frontend/src/higgins/chatMemory.ts",
    "frontend/src/domain/privacyData.ts",
    "frontend/src/domain/serverCopyNote.ts",
    # Threats list: one record per check, statuses, Biting, repeats and alerts.
    "backend/routers/patrol.py",
    "backend/routers/push.py",
    "backend/services/patrol_records.py",
    "frontend/src/domain/threatCase.ts",
    # Threat Case facts: origin, evidence source, processing, completeness and privacy kept apart.
    "backend/core/evidence_model.py",
    "frontend/src/domain/evidenceModel.ts",
    "frontend/src/domain/caseFacts.ts",
    "frontend/src/domain/caseSources.ts",
    # The check areas: websites and links, messages and calls, email and accounts, apps and files, device and internet.
    "backend/services/intel.py",
    "backend/services/triage/catalogue.py",
    "backend/routers/analysis.py",
    "backend/services/gmail.py",
    "backend/services/mailbox_monitor.py",
    "backend/services/breach_check.py",
    "frontend/src/domain/screenedCalls.ts",
    "frontend/modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloCallScreeningService.kt",
    "frontend/modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloSmsListenerService.kt",
    "frontend/src/store/accountMonitorStore.ts",
    "frontend/src/domain/fileAnalysis.ts",
    "frontend/src/domain/fileInspection.ts",
    "frontend/src/domain/appAnalysis.ts",
    "frontend/src/domain/deviceAnalysis.ts",
    "frontend/src/domain/deviceReview.ts",
    "frontend/src/domain/networkAnalysis.ts",
    # Evidence received: levels, what could be examined, signals and upgrades (email first).
    "frontend/src/domain/triage/evidenceProfile.ts",
    "frontend/src/domain/triage/emailEvidence.ts",
    "frontend/src/domain/triage/emailOriginal.ts",
    "frontend/src/domain/triage/emailIntake.ts",
    "frontend/src/domain/triage/linkEvidence.ts",
    "frontend/src/domain/triage/messageEvidence.ts",
    "frontend/src/domain/triage/callEvidence.ts",
    "frontend/src/domain/triage/fileEvidence.ts",
    "frontend/src/domain/triage/appEvidence.ts",
    "frontend/src/domain/triage/imageEvidence.ts",
    "frontend/src/store/originalEmail.ts",
    # Held copies: the phone keeps its own until the person deletes it; the server's waits for the phone's confirmation.
    "backend/services/held_copies.py",
    "backend/services/device_pickup.py",
    "frontend/src/store/originalSource.ts",
    "frontend/src/investigation/pickup.ts",
    "backend/services/email_evidence.py",
    # Scam Alerts and the government feeds.
    "backend/services/government_alerts.py",
    "backend/services/feed_health.py",
    "backend/services/learning_feeds.py",
    # Phone permissions: what is declared, what is asked for, and when.
    "frontend/app.config.js",
    "frontend/plugins/withRestrictedPhonePermissions.js",
    "frontend/src/domain/gatePermissions.ts",
)

_REVIEWED = re.compile(r"^_Last reviewed against the code: (\d{4}-\d{2}-\d{2})\._$", re.M)


def fingerprints() -> dict[str, str]:
    """A watched file that isn't on this server is skipped: a published backend may ship without the app's code.
    The tests check that every watched file exists in the project."""
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in WATCHED if (ROOT / path).is_file()}


def changed() -> list[str]:
    """Rule-defining files that changed since the book was last reviewed against them."""
    locked = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    return [path for path, digest in fingerprints().items() if locked.get(path) != digest]


def stamp(today: Optional[date] = None) -> None:
    """The book has been reviewed against the code: record the fingerprints and the review date."""
    LOCK.write_text(json.dumps(fingerprints(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    text = BOOK.read_text(encoding="utf-8")
    BOOK.write_text(_REVIEWED.sub(f"_Last reviewed against the code: {(today or date.today()).isoformat()}._", text, count=1), encoding="utf-8")


def read() -> dict:
    text = BOOK.read_text(encoding="utf-8")
    reviewed = _REVIEWED.search(text)
    return {"markdown": text, "reviewedAt": reviewed.group(1) if reviewed else None}


# ── Settling rules: the one sentence on each result ─────────────────────────
# (who, rule name). The book's "Settling rules" table lists every one of these, word for word.
SETTLING_RULES: dict[str, tuple[str, str]] = {
    "FLYBY-THREAT": ("TC FlyBy", "Confirmed threat"),
    "FLYBY-PATTERN": ("TC FlyBy", "Known scam, every step"),
    "FLYBY-IMPERSONATION": ("TC FlyBy", "Corroborated impersonation"),
    "FLYBY-OPENING": ("TC FlyBy", "Known scam opening"),
    "FLYBY-SIGNS": ("TC FlyBy", "Established warning signs"),
    "FLYBY-CLEAR": ("TC FlyBy", "Nothing found, everything checked"),
    "FLYBY-UNKNOWN": ("TC FlyBy", "Can't establish more"),
    "FLYBY-ANSWERED": ("TC FlyBy", "Question answered from a source"),
    "MAGNUM-READING": ("Magnum DI", "Reading"),
    "MAGNUM-REASONING": ("Magnum DI", "Reasoning"),
    "MAGNUM-RELATING": ("Magnum DI", "Relating"),
    "MAGNUM-QUESTION": ("Magnum DI", "Open general question"),
    "MAGNUM-SAFETY-NET": ("Magnum DI", "Safety net"),
}

# ── EXPLAIN rules: Higgins' explanation rules ───────────────────────────────
# id → (rule book section, rule, the code that applies it as "module:name"). EXPLAIN rules present or explain a
# result and never change it. The book lists every one under its section, word for word; the Fidelity Check's
# failure codes (explain/fidelity.CODES) and the settling rules above are EXPLAIN rules too.
EXPLAIN_RULES: dict[str, tuple[str, str, str]] = {
    "HIG-01": ("higgins-explanation", "Every follow-up on an investigated case is answered from its locked findings, with no AI, and the case is never reopened",
               "routers.investigations:_follow_up"),
    "HIG-02": ("higgins-explanation", "Something to check goes to the investigation pipeline", "services.higgins.pipeline_submit:submit_to_investigation_pipeline"),
    "HIG-03": ("higgins-explanation", "A scam alert the person opened is shown in the source's own words", "services.higgins.presenter:scam_alert_explanation"),
    "HIG-04": ("higgins-explanation", "A Learn article is shown in its own words", "services.higgins.presenter:learn_article"),
    "HIG-05": ("higgins-explanation", "Patrol records, the phone's live state, recent investigations and ApolloSG product knowledge are shown as they are",
               "services.higgins.chat:_from_apollo"),
    "HIG-06": ("higgins-explanation", "ApolloSG's KB is quoted with publisher and link, labelled as general knowledge", "services.higgins.knowledge:present"),
    "HIG-07": ("higgins-explanation", "An off-topic question gets a fixed reply, word for word", "services.higgins.presenter:OUT_OF_SCOPE"),
    "HIG-08": ("higgins-explanation", "A question nothing above answers is told plainly that ApolloSG's trusted knowledge doesn't cover it; no general AI model is asked",
               "services.higgins.presenter:not_in_trusted_knowledge"),
    "HIG-09": ("higgins-explanation", "The phone's live reading is the truth: Higgins never contradicts it, guesses past it or invents a concern",
               "services.higgins.presenter:device_state"),
    "HIG-10": ("higgins-explanation", "A case gets at most one Magnum DI call: answering its pending question doesn't reopen the investigation",
               "services.higgins.repository:claim_magnum_call"),
    "HIG-11": ("higgins-explanation", "Plain Australian English, no internal codes, 2–4 short paragraphs", "services.higgins.presenter:STATE_TEXT"),
    "PER-01": ("plain-english-renderer", "The evidence lock: no fact, identifier, certainty, severity, step or attribution is added, dropped or changed",
               "services.higgins.explain.fidelity:check"),
    "PER-02": ("plain-english-renderer", "The facts come only from the validated result and the case's own records", "services.higgins.explain.facts:build"),
    "PER-03": ("plain-english-renderer", "Identifiers survive word for word", "services.higgins.explain.facts:ENTITY_PATTERNS"),
    "PER-04": ("plain-english-renderer", "The draft follows the fixed order", "services.higgins.explain.render:render"),
    "PER-05": ("plain-english-renderer", "How serious is one fixed line for the attention level", "services.higgins.explain.words:SEVERITY"),
    "PER-06": ("plain-english-renderer", "Every finding is labelled with who established it and how firmly", "services.higgins.explain.words:BASIS"),
    "PER-07": ("plain-english-renderer", "Markdown is removed, and a link keeps its address", "services.higgins.explain.facts:strip_markdown"),
    "PER-08": ("plain-english-renderer", "Formal words are swapped only from the fixed list", "services.higgins.explain.words:PLAIN_SWAPS"),
    "PER-09": ("plain-english-renderer", "Each point is said once, and every finding is always listed", "services.higgins.explain.render:repeats"),
    "PER-10": ("plain-english-renderer", "Jargon is explained once per result, in Apollo's fixed words", "services.higgins.explain.words:GLOSSARY"),
    "FID-01": ("fidelity-check", "The plain English is shown only when nothing was lost, added or changed", "services.higgins.explain:explain_case"),
    "FID-02": ("fidelity-check", "At most 2 checks run on each result: plain, then repaired, then Apollo's own wording", "services.higgins.explain:MAX_ATTEMPTS"),
    "FID-03": ("fidelity-check", "A renderer error never fails an investigation, and Apollo's own wording is shown", "services.higgins.explain:renderer_error"),
}

_MAGNUM_WHY = {
    "MAGNUM-READING": "part of what you sent (a picture or scanned page) had to be read directly",
    "MAGNUM-REASONING": "the message asks you to send money, details or access through a route no official source has verified",
    "MAGNUM-RELATING": "TC FlyBy's findings pointed in different directions and needed weighing up",
    "MAGNUM-QUESTION": "neither ApolloSG's knowledge base nor a targeted search could answer the question",
}
_CAPABILITY_RULE = {"reading": "MAGNUM-READING", "reasoning": "MAGNUM-REASONING", "relating": "MAGNUM-RELATING"}


def _pattern_name(pattern: Optional[dict]) -> str:
    from services.higgins.tc_flyby.patterns import PATTERNS
    key = (pattern or {}).get("key")
    return next((p["name"] for p in PATTERNS if p["key"] == key), "a known scam")


def _flyby(flyby: dict, answered_by: str) -> Optional[tuple[str, str]]:
    basis, outcome = flyby.get("basis"), flyby.get("outcome")
    if basis == "threat":
        return "FLYBY-THREAT", ("an official source found in TC FlyBy's search names this exact item as a scam or threat" if answered_by == "tc_flyby_search"
                                else "a direct safety check (Google Safe Browsing, Apollo's blocklist or an official scam advisory) lists this exact item as a threat")
    if basis == "pattern":
        name = _pattern_name(flyby.get("pattern"))
        if outcome == "likely_scam":
            return "FLYBY-PATTERN", f"it matches every step of the {name} that Scamwatch describes, and nothing in it contradicts that"
        return "FLYBY-OPENING", f"it opens the same way as the {name} that Scamwatch describes, though it hasn't asked for anything yet"
    return {
        "impersonation": ("FLYBY-IMPERSONATION", "it names an organisation but links somewhere that isn't the organisation's website, "
                                                 "and a separate check on that link backs this up"),
        "signals": ("FLYBY-SIGNS", "its checks found real warning signs, but not enough to call it a scam"),
        "clear": ("FLYBY-CLEAR", "every planned check ran over everything you sent and none found a scam indicator"),
        "unknown": ("FLYBY-UNKNOWN", "its checks couldn't establish more, and a deeper look couldn't change what you should do"),
        "knowledge": ("FLYBY-ANSWERED", "a targeted search answered the question, backed by a real web page" if answered_by == "tc_flyby_search"
                      else "ApolloSG's knowledge base answers the question from a named source"),
    }.get(basis or "")


def _magnum(flyby: dict) -> Optional[tuple[list[str], str]]:
    issues = flyby.get("issues") or []
    if not issues:
        # TC FlyBy reached a result, but it failed validation and Magnum DI took the whole case.
        return (["MAGNUM-SAFETY-NET"], "TC FlyBy's own result didn't pass Apollo's checks, so Magnum DI looked at the whole case") if flyby.get("basis") else None
    rule_ids: list[str] = []
    for issue in issues:
        rule_id = "MAGNUM-QUESTION" if (issue.get("text") or "").startswith("Answer the general question") else _CAPABILITY_RULE.get(issue.get("capability") or "")
        if rule_id and rule_id not in rule_ids:
            rule_ids.append(rule_id)
    if not rule_ids:
        return None
    return rule_ids, "a deeper look was needed because " + ", and ".join(_MAGNUM_WHY[r] for r in rule_ids)


def settled_reason(routing: Optional[dict]) -> Optional[dict]:
    """The rule that settled this case, as one plain sentence. None when the case's record doesn't say (results
    from before routing was recorded) — never guessed. Names no value from the material."""
    routing = routing or {}
    flyby = routing.get("tc_flyby")
    if not flyby:
        return None
    answered_by = routing.get("answeredBy") or flyby.get("answeredBy") or ""
    if outcomes.settled_by_flyby(answered_by):
        found = _flyby(flyby, answered_by)
        if not found:
            return None
        rule_ids, why = [found[0]], found[1]
    else:
        magnum = _magnum(flyby)
        if not magnum:
            return None
        rule_ids, why = magnum
    who = SETTLING_RULES[rule_ids[0]][0]
    names = [SETTLING_RULES[r][1] for r in rule_ids]
    rule = " and ".join([names[0]] + [n.lower() for n in names[1:]])
    return {"ruleId": rule_ids[0], "rule": rule, "by": who, "sentence": f"Settled by {who} — {rule}: {why}."}
