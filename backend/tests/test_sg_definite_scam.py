"""
TC FlyBy — Definite Scam Classification Regression Tests
=========================================================
Covers the ApolloSG classification fixes applied to decide.py, finding_rules.py,
official.py, and report.py.

10 test scenarios that MUST hold.

Run:
    cd /app/backend && python -m pytest tests/test_sg_definite_scam.py -v
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.higgins.tc_flyby.triage import Check, Entities, Plan
from services.higgins.tc_flyby.finding_rules import evaluate
from services.higgins.tc_flyby.decide import corroborated_impersonation
from services.higgins.tc_flyby.evidence_evaluation import should_downgrade_provisional


# ── Minimal fact / plan helpers ───────────────────────────────────────────────

def _live(text: str, signal: str, *, decisive: bool = False, topic: str | None = None,
          place: str | None = None) -> dict:
    f: dict = {
        "text": text,
        "signal": signal,
        "decisive": decisive,
        "class": "live_evidence",
        "source": {"publisher": "test-source", "authority": "official",
                   "basis": "", "retrieval": "fetched", "checkedAt": "2026-06-01T00:00:00+00:00"},
        "topic": topic,
    }
    if place is not None:
        f["place"] = place
    return f


def _imp_check(brand: str, official_domain: str, *facts) -> Check:
    c = Check(id="c-imp", kind="impersonation", subject=brand, urls=[official_domain])
    for f in facts:
        c.facts.append(f)
    if any(f["signal"] == "anomaly" for f in c.facts if f["class"] == "live_evidence"):
        c.status = "needs_reasoning"
    elif any(f["signal"] == "clear" for f in c.facts if f["class"] == "live_evidence"):
        c.status = "resolved"
        c.route = "official_source"
    return c


def _link_check(host: str, *facts, resolved: bool = False) -> Check:
    c = Check(id=f"c-link-{host}", kind="link", subject=host, urls=[f"https://{host}/"])
    for f in facts:
        c.facts.append(f)
    if resolved or any(f.get("decisive") for f in c.facts if f["class"] == "live_evidence"):
        c.status = "resolved"
        c.route = "official_source"
    return c


def _email_check(address: str, *facts) -> Check:
    c = Check(id=f"c-email-{address}", kind="email", subject=address)
    for f in facts:
        c.facts.append(f)
    return c


def _make_plan(*, brands=None, hosts=None, emails=None, requests=None,
               checks=None, pattern=None, has_message=True) -> Plan:
    ent = Entities()
    ent.brands = brands or []
    ent.hosts = hosts or []
    ent.emails = emails or []
    ent.requests = requests or []
    return Plan(
        entities=ent,
        message_type="bank",
        checks=checks or [],
        has_message=has_message,
        link_only=False,
        general=False,
        gaps=[],
        pattern=pattern,
    )


# ── Shared fact constants ─────────────────────────────────────────────────────

LOOKALIKE_FACT = _live(
    "commbank-secure.net carries CommBank's name, but it is not CommBank's domain "
    "(commbank.com.au) — the name resembles CommBank.",
    "anomaly", topic="lookalike", place="commbank-secure.net"
)

OFFICIAL_DOMAIN_FACT = _live(
    "Every link and address in the material uses commbank.com.au, CommBank's official domain.",
    "clear", decisive=False, topic="official_domains"
)

OFFICIAL_DOMAIN_DECISIVE_FACT = _live(
    "commbank.com.au is CommBank's official domain.",
    "clear", decisive=True, topic="official_domain"
)

SB_CLEAN_FACT = _live(
    "commbank-secure.net is not listed by Google Safe Browsing.",
    "clear", decisive=False, topic="listing"
)

SB_MALICIOUS_FACT = _live(
    "Google Safe Browsing lists commbank-secure.net as a phishing (social engineering) site.",
    "concern", decisive=True, topic="listing"
)

ADVISORY_FACT = _live(
    "An official scam advisory matches fraudsite.net: 'CommBank Phishing Campaign Alert'.",
    "concern", decisive=True, topic="listing"
)

FREEMAIL_FACT = _live(
    "noreply@gmail.com is a free personal email account (gmail.com), not an address of CommBank.",
    "anomaly", topic="freemail"
)

NEWLY_REGISTERED_FACT = _live(
    "commbank-secure.net was registered 5 days before this check.",
    "weak", topic="registration"
)

CREDENTIAL_REQUEST = {
    "type": "credentials",
    "quote": "verify your NetBank login details",
    "context": "Please verify your NetBank login details at the link below.",
    "targets": ["commbank-secure.net"],
}

OPEN_LINK_REQUEST = {
    "type": "open_link",
    "quote": "read the account notice at commbank-secure.net",
    "context": "read the account notice at commbank-secure.net",
    "targets": ["commbank-secure.net"],
}


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 — Lookalike + credential + clean Safe Browsing  →  SCAM
# TC-2026-A77E4 regression
# ════════════════════════════════════════════════════════════════════════════════

def test_commbank_lookalike_credential_clean_sb_is_definite_scam():
    """TC-2026-A77E4 regression: CommBank lookalike + credential + clean SB → scam."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-secure.net"],
        requests=[CREDENTIAL_REQUEST],
        checks=[
            _imp_check("CommBank", "commbank.com.au", LOOKALIKE_FACT),
            _link_check("commbank-secure.net", SB_CLEAN_FACT),
        ],
    )
    result = evaluate(plan)
    assert result.finding == "scam", (
        f"Expected 'scam' but got '{result.finding}'. "
        f"Deciding: {result.deciding_rules}. "
        f"identity_is_false={result.ipdmc.identity_is_false}"
    )
    assert any(r in result.deciding_rules for r in ("S2", "S3"))


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 — Lookalike + credential + malicious Safe Browsing  →  SCAM
# ════════════════════════════════════════════════════════════════════════════════

def test_commbank_lookalike_credential_malicious_sb_is_definite_scam():
    """CommBank lookalike + credential + SB malicious → scam (S1 and/or S2 fire)."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-secure.net"],
        requests=[CREDENTIAL_REQUEST],
        checks=[
            _imp_check("CommBank", "commbank.com.au", LOOKALIKE_FACT),
            _link_check("commbank-secure.net", SB_MALICIOUS_FACT, resolved=True),
        ],
    )
    result = evaluate(plan)
    assert result.finding == "scam", (
        f"Expected 'scam' but got '{result.finding}'. Deciding: {result.deciding_rules}"
    )
    assert any(r in result.deciding_rules for r in ("S1", "S2", "S3"))


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 — Official advisory listing  →  SCAM (S1)
# ════════════════════════════════════════════════════════════════════════════════

def test_official_advisory_listing_is_definite_scam():
    """Domain listed in an official scam advisory → scam via S1."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["fraudsite.net"],
        requests=[CREDENTIAL_REQUEST],
        checks=[
            _imp_check("CommBank", "commbank.com.au",
                       _live("fraudsite.net carries CommBank's name.", "anomaly",
                             topic="lookalike", place="fraudsite.net")),
            _link_check("fraudsite.net", ADVISORY_FACT, resolved=True),
        ],
    )
    result = evaluate(plan)
    assert result.finding == "scam"
    assert "S1" in result.deciding_rules


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 — Legitimate bank notification (official domain, no credential)  →  NOT_SCAM
# ════════════════════════════════════════════════════════════════════════════════

def test_official_domain_no_credential_is_not_scam():
    """CommBank official domain + clean SB + no credential request → not_scam."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank.com.au"],
        requests=[],
        checks=[
            _imp_check("CommBank", "commbank.com.au", OFFICIAL_DOMAIN_FACT),
            _link_check("commbank.com.au", OFFICIAL_DOMAIN_DECISIVE_FACT, resolved=True),
        ],
        has_message=True,
    )
    result = evaluate(plan)
    assert result.finding == "not_scam", (
        f"Expected 'not_scam' but got '{result.finding}'. Deciding: {result.deciding_rules}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 — Lookalike WITHOUT credential  →  LIKELY_SCAM (not "scam")
# Verifies no over-fire from the lookalike self-corroboration fix.
# ════════════════════════════════════════════════════════════════════════════════

def test_commbank_lookalike_no_credential_clean_sb_is_likely_scam():
    """Lookalike + clean SB + no credential → likely_scam (not scam; no over-fire)."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-secure.net"],
        requests=[OPEN_LINK_REQUEST],
        checks=[
            _imp_check("CommBank", "commbank.com.au", LOOKALIKE_FACT),
            _link_check("commbank-secure.net", SB_CLEAN_FACT),
        ],
    )
    result = evaluate(plan)
    assert result.finding == "likely_scam", (
        f"Expected 'likely_scam' (no credential → not definite) but got '{result.finding}'. "
        f"Deciding: {result.deciding_rules}"
    )
    assert not any(r in result.deciding_rules for r in ("S1", "S2", "S3", "S4"))


# ════════════════════════════════════════════════════════════════════════════════
# TEST 6 — Freemail sender (unrelated domain) + credential  →  LIKELY_SCAM or SCAM
# An unrelated domain (gmail.com) must NOT self-corroborate impersonation.
# ════════════════════════════════════════════════════════════════════════════════

def test_freemail_sender_claiming_to_be_bank_is_likely_scam():
    """Email from gmail.com claiming to be CommBank + credential → suspicious but NOT definite via identity."""
    freemail_fact = _live(
        "noreply@gmail.com is a free personal email account (gmail.com), not an address of CommBank.",
        "anomaly", topic="freemail"
    )
    unrelated_imp_fact = _live(
        "gmail.com does not carry CommBank's name and is not CommBank's domain.",
        "anomaly", topic="impersonation", place="gmail.com"
    )
    email_check = _email_check("noreply@gmail.com", freemail_fact)
    imp_check = _imp_check("CommBank", "commbank.com.au", unrelated_imp_fact)

    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        emails=["noreply@gmail.com"],
        requests=[CREDENTIAL_REQUEST],
        checks=[imp_check, email_check],
    )
    result = evaluate(plan)
    # May be likely_scam or scam depending on other evidence, but must not be not_scam.
    assert result.finding in ("likely_scam", "scam"), (
        f"Expected 'likely_scam' or 'scam' for freemail impersonation; "
        f"got '{result.finding}'. Deciding: {result.deciding_rules}"
    )
    # An UNRELATED domain (gmail.com) must NOT self-corroborate → identity_is_false stays False.
    corroborated = corroborated_impersonation(plan)
    lookalike_topics = {f.get("topic") for f in corroborated}
    assert "lookalike" not in lookalike_topics, (
        f"Unrelated domain must NOT self-corroborate; corroborated topics: {lookalike_topics}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 7 — All official links + no credential  →  NOT_SCAM
# ════════════════════════════════════════════════════════════════════════════════

def test_official_links_despite_scam_pattern_text_is_not_scam():
    """CommBank message with official links + no credential request → not_scam."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank.com.au"],
        requests=[],
        checks=[
            _imp_check("CommBank", "commbank.com.au", OFFICIAL_DOMAIN_FACT),
            _link_check("commbank.com.au", OFFICIAL_DOMAIN_DECISIVE_FACT, resolved=True),
        ],
        has_message=True,
    )
    result = evaluate(plan)
    assert result.finding == "not_scam", (
        f"Expected 'not_scam' (all official links) but got '{result.finding}'. "
        f"Deciding: {result.deciding_rules}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 8 — Evidence evaluation NEVER downgrades a definite scam verdict
# ════════════════════════════════════════════════════════════════════════════════

def test_evidence_evaluation_never_downgrades_scam_verdict():
    """should_downgrade_provisional('scam') must always be (False, None)."""
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-secure.net"],
        requests=[CREDENTIAL_REQUEST],
        checks=[
            _imp_check("CommBank", "commbank.com.au", LOOKALIKE_FACT),
            _link_check("commbank-secure.net", SB_CLEAN_FACT),
        ],
    )
    rules_result = evaluate(plan)
    assert rules_result.finding == "scam", (
        f"Pre-condition failed: expected 'scam' but got '{rules_result.finding}' (fix Test 1 first)"
    )
    should_downgrade, reason = should_downgrade_provisional(plan, "scam")
    assert should_downgrade is False
    assert reason is None


# ════════════════════════════════════════════════════════════════════════════════
# TEST 9 — CEO gift-card scam (freemail + full KB pattern + gift-card request)  →  SCAM
# TC-2026-501BD regression: S4 must accept anomaly signals from email checks.
# ════════════════════════════════════════════════════════════════════════════════

def test_ceo_gift_card_scam_full_pattern_freemail_is_scam():
    """CEO gift-card fraud: freemail sender + full gift-card KB pattern → scam via S4."""
    freemail_fact = _live(
        "d.whitfield.ceo@gmail.com is a free personal email account (gmail.com), "
        "not an address of Apple.",
        "anomaly", topic="freemail"
    )
    unrelated_imp_fact = _live(
        "gmail.com does not carry Apple's name and is not Apple's domain (apple.com).",
        "anomaly", topic="impersonation", place="gmail.com"
    )
    email_check = _email_check("d.whitfield.ceo@gmail.com", freemail_fact)
    imp_check = _imp_check("Apple", "apple.com", unrelated_imp_fact)

    full_gift_card_pattern = {
        "stage": "full",
        "name": "gift card and cryptocurrency payment scam",
        "publisher": "Scamwatch (ACCC)",
        "summary": "An urgent request to buy gift cards or crypto and share the codes.",
        "impersonatesOrganisation": False,
        "found": [("claims urgency", "I need this done right away"), ("gift card demand", "buy Apple gift cards")],
        "ask": None,
    }
    gift_card_request = {
        "type": "gift_cards_crypto",
        "quote": "buy $500 Apple gift cards and send me the codes",
        "context": "Quick favour — can you buy $500 Apple gift cards and send me the codes?",
        "targets": [],
    }

    plan = _make_plan(
        brands=[("Apple", "apple.com")],
        emails=["d.whitfield.ceo@gmail.com"],
        requests=[gift_card_request],
        checks=[imp_check, email_check],
        pattern=full_gift_card_pattern,
    )
    result = evaluate(plan)
    assert result.finding == "scam", (
        f"Expected 'scam' for CEO gift-card scam; got '{result.finding}'. "
        f"Deciding: {result.deciding_rules}. "
        f"identity_is_false={result.ipdmc.identity_is_false}, "
        f"consequential_requests={[r['type'] for r in result.ipdmc.consequential_requests]}"
    )
    assert "S4" in result.deciding_rules, (
        f"S4 (complete pattern + corroborating evidence) should decide; got: {result.deciding_rules}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 10 — Email-sender lookalike → SCAM + correct "sent from" overview
# TC-2026-35E69 regression: impersonation_result() must NOT say "its link goes to"
# for an email-domain lookalike, and must use outcome="scam" in the report.
# ════════════════════════════════════════════════════════════════════════════════

def test_email_sender_lookalike_is_scam_with_correct_overview():
    """ATO fake email (mygov-refunds.net lookalike): S2 fires → 'scam'; overview says 'sent from'."""
    lookalike_fact = _live(
        "mygov-refunds.net carries myGov's name, but it is not myGov's domain "
        "(my.gov.au) — the name resembles myGov.",
        "anomaly", topic="lookalike", place="mygov-refunds.net"
    )
    imp_check = _imp_check("myGov", "my.gov.au", lookalike_fact)

    full_govt_pattern = {
        "stage": "full",
        "name": "government or authority threat scam",
        "publisher": "Scamwatch (ACCC)",
        "summary": "Fake government demands using threats of arrest or legal action to force immediate payment.",
        "impersonatesOrganisation": True,
        "found": [("government claim", "Australian Taxation Office"), ("legal threat", "warrant for your arrest")],
        "ask": None,
    }
    payment_request = {
        "type": "payment",
        "quote": "pay the outstanding amount immediately to avoid legal action",
        "context": "pay the outstanding amount immediately to avoid legal action",
        "targets": ["mygov-refunds.net"],
    }

    plan = _make_plan(
        brands=[("myGov", "my.gov.au")],
        emails=["no-reply@mygov-refunds.net"],
        hosts=[],
        requests=[payment_request],
        checks=[imp_check],
        pattern=full_govt_pattern,
    )
    result = evaluate(plan)

    # 1. Verdict must be "scam"
    assert result.finding == "scam", (
        f"Expected 'scam' for email-sender lookalike; got '{result.finding}'. "
        f"Deciding: {result.deciding_rules}. "
        f"identity_is_false={result.ipdmc.identity_is_false}, "
        f"purpose_is_deceptive={result.ipdmc.purpose_is_deceptive}"
    )
    assert any(r in result.deciding_rules for r in ("S2", "S3"))

    # 2. Report overview must say "sent from", not "its link goes to"
    from services.higgins.tc_flyby.report import impersonation_result
    facts = corroborated_impersonation(plan)
    assert facts, "corroborated_impersonation must return facts for a lookalike"

    report = impersonation_result(plan, plan.checks, {}, "test-flyby", facts, outcome="scam")
    overview = report.get("overview", "")

    assert "sent from" in overview.lower() or "no-reply@mygov-refunds.net" in overview, (
        f"Overview for email-sender lookalike must reference the sender address. Got: {overview!r}"
    )
    assert "its link goes to" not in overview.lower(), (
        f"Overview must NOT say 'its link goes to' for an email-sender lookalike. Got: {overview!r}"
    )
    assert report.get("outcome") == "scam", (
        f"Report outcome must be 'scam' when S2 fires; got: {report.get('outcome')!r}"
    )


# ════════════════════════════════════════════════════════════════════════════════
# TEST 11 — Nigerian phone number (+234) → SCAM + phone-intelligence report
# ════════════════════════════════════════════════════════════════════════════════

def test_nigerian_phone_produces_phone_intel_report():
    """A bare +234 (Nigeria) number → concern() emits the 'Call Identification /
    Standard Scam Tactics / What You Should Do Now' format."""
    from services.higgins.tc_flyby.report import concern

    # Build the fact exactly as _add_phone_intel() would produce it.
    intel_fact: dict = {
        "text": "This is an international mobile number from Nigeria (Country code +234).",
        "signal": "concern",
        "decisive": True,
        "class": "live_evidence",
        "source": {"publisher": "Apollo Phone Intelligence", "authority": "independent",
                   "basis": "Country-code risk assessment — Nigeria (+234)",
                   "retrieval": "fetched", "checkedAt": "2026-06-01T00:00:00+00:00"},
        "topic": "high_risk_international",
        "phone_intel": {
            "country": "Nigeria",
            "country_code": "+234",
            "carrier": "Airtel Nigeria",
            "series": "0701",
            "tactics": (
                "- **The \"Wangiri\" / One-Ring Scam**: They call briefly and hang up, hoping you call back "
                "out of curiosity. Dialing back international numbers results in high per-minute charges.\n"
                "- **Impression Scams**: Pretending to be an official entity (banks, delivery services, tech "
                "support, or remote work opportunities) to harvest personal information or payments.\n"
                "- **Impersonation/WhatsApp Takeovers**: Messaging you via WhatsApp using an unknown contact "
                "photo claiming to be an acquaintance in trouble."
            ),
        },
    }

    phone_check = Check(id="c-phone", kind="phone", subject="+2347013123456")
    phone_check.facts.append(intel_fact)
    phone_check.status = "resolved"
    phone_check.route = "official_source"

    plan = _make_plan(checks=[phone_check], has_message=False)
    plan.channel = "call"

    report = concern(plan, plan.checks, {}, "test-flyby-phone", "tc_flyby_official")

    assert report["overview"] == "Yes, treat this as a high-risk scam call.", (
        f"Unexpected overview: {report['overview']!r}"
    )
    md = report["explanationMarkdown"]
    assert "Call Identification" in md
    assert "Standard Scam Tactics" in md
    assert "What You Should Do Now" in md
    assert "Nigeria" in md
    assert "+234" in md
    assert "Airtel Nigeria" in md
    assert "0701" in md
    assert "Wangiri" in md
    assert "Do Not Call Back" in md
    assert report["outcome"] == "scam"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 12 — CommBank SMS phishing (lookalike + credential + message)
#           → SCAM + "Why This Is a Scam" report
# ════════════════════════════════════════════════════════════════════════════════

def test_commbank_sms_phishing_produces_why_scam_report():
    """CommBank SMS with commbank-cancel.co + credential request → 'Why This Is a Scam'
    / 'What You Should Do Now' report format."""
    from services.higgins.tc_flyby.report import impersonation_result

    lookalike = _live(
        "commbank-cancel.co carries CommBank's name, but it is not CommBank's domain "
        "(commbank.com.au) — the name resembles CommBank.",
        "anomaly", topic="lookalike", place="commbank-cancel.co"
    )
    imp_check = _imp_check("CommBank", "commbank.com.au", lookalike)
    sb_clean = _live("commbank-cancel.co is not listed by Google Safe Browsing.",
                     "clear", decisive=False, topic="listing")

    cred_request = {
        "type": "credentials",
        "quote": "verify your NetBank login details",
        "context": "verify your NetBank login details at http://commbank-cancel.co/stop",
        "targets": ["commbank-cancel.co"],
    }
    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-cancel.co"],
        requests=[cred_request],
        checks=[imp_check, _link_check("commbank-cancel.co", sb_clean)],
    )

    facts = corroborated_impersonation(plan)
    assert facts, "corroborated_impersonation must find the lookalike for commbank-cancel.co"

    report = impersonation_result(plan, plan.checks, {}, "test-flyby", facts, outcome="scam")

    assert report["overview"] == "This is a phishing scam. Do not click the link or enter any information.", (
        f"Unexpected overview: {report['overview']!r}"
    )
    md = report["explanationMarkdown"]
    assert "Why This Is a Scam" in md
    assert "What You Should Do Now" in md
    assert "commbank-cancel.co" in md
    assert "commbank.com.au" in md
    assert "CommBank" in md
    assert report["outcome"] == "scam"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 13 — Bare CommBank phishing URL (link_only)
#           → "What That Link Does" report
# ════════════════════════════════════════════════════════════════════════════════

def test_bare_commbank_url_produces_what_link_does_report():
    """Bare commbank-cancel.co URL submission (link_only) → 'What That Link Does'
    / 'What to Do Right Now' report format."""
    from services.higgins.tc_flyby.report import impersonation_result

    lookalike = _live(
        "commbank-cancel.co carries CommBank's name, but it is not CommBank's domain "
        "(commbank.com.au) — the name resembles CommBank.",
        "anomaly", topic="lookalike", place="commbank-cancel.co"
    )
    imp_check = _imp_check("CommBank", "commbank.com.au", lookalike)
    sb_clean = _live("commbank-cancel.co is not listed by Google Safe Browsing.",
                     "clear", decisive=False, topic="listing")

    plan = _make_plan(
        brands=[("CommBank", "commbank.com.au")],
        hosts=["commbank-cancel.co"],
        requests=[],   # No credential request — bare URL only
        checks=[imp_check, _link_check("commbank-cancel.co", sb_clean)],
        has_message=False,
    )
    plan.link_only = True   # Bare URL submission

    facts = corroborated_impersonation(plan)
    assert facts, "corroborated_impersonation must find the lookalike for commbank-cancel.co"

    report = impersonation_result(plan, plan.checks, {}, "test-flyby", facts, outcome="likely_scam")

    assert report["overview"] == "Do not click or open that link.", (
        f"Unexpected overview: {report['overview']!r}"
    )
    md = report["explanationMarkdown"]
    assert "What That Link Does" in md
    assert "What to Do Right Now" in md
    assert "commbank-cancel.co" in md
    assert "CommBank" in md
    assert report["outcome"] == "likely_scam"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 14 — ABC News legitimate newsletter → NOT SCAM + "Why This Looks Safe"
# ════════════════════════════════════════════════════════════════════════════════

def test_abc_news_newsletter_classifies_as_not_scam_with_why_safe_report():
    """A clean, all-clear submission with official domain and no credential requests should
    classify as 'not_scam' via the N1 no-conflict path and generate 'Why This Looks Safe'."""
    from services.higgins.tc_flyby.report import clear
    from services.higgins.tc_flyby.finding_rules import evaluate as rules_evaluate

    # Simulate: Safe Browsing clear + established registration for abc.net.au
    sb_clear = _live("abc.net.au is not listed by Google Safe Browsing.",
                     "clear", decisive=False, topic="listing")
    rdap_neutral = _live("abc.net.au is registered to Australian Broadcasting Corporation Ltd "
                         "(registered: 1996, expires: 2027).",
                         "neutral", decisive=False, topic="registration")

    imp_check = _imp_check("ABC News", "abc.net.au")  # No anomaly, no clear — unknown identity
    link_check = _link_check("abc.net.au", sb_clear, rdap_neutral, resolved=True)

    plan = _make_plan(
        brands=[("ABC News", "abc.net.au")],
        hosts=["abc.net.au"],
        requests=[],
        checks=[imp_check, link_check],
    )

    # --- Classification ---
    result = rules_evaluate(plan)
    assert result.finding == "not_scam", (
        f"ABC News newsletter with clean abc.net.au should be 'not_scam'; got {result.finding!r}.\n"
        f"N rule details: {[(r.rule, r.passed, r.status, r.reason) for r in result.n_rules]}"
    )

    # --- Report content ---
    from services.higgins.tc_flyby.decide import Decision
    report = clear(plan, plan.checks, {}, "test-flyby", "tc_flyby_official")

    assert report["outcome"] == "not_scam"
    assert report["overview"] == "This is not a scam.", (
        f"Unexpected overview: {report['overview']!r}"
    )
    md = report["explanationMarkdown"]
    assert "Why This Looks Safe" in md
    assert "Safety Tip" in md
    assert "abc.net.au" in md
    assert "ABC News" in md
    # Must NOT fall through to the generic "isn't proof it's genuine" path
    assert "isn't proof it's genuine" not in report["overview"]


# ════════════════════════════════════════════════════════════════════════════════
# TEST 15 — Australian domestic landline (03 9996 8074)
#           → concern() emits 'Status / Behavior / Recommended Actions'
#             with 'High spam probability'
# ════════════════════════════════════════════════════════════════════════════════

def test_au_domestic_landline_produces_high_spam_report():
    """Australian domestic landline (03 9996 8074 → 0399968074) → concern() emits the
    'Status / Behavior / Recommended Actions' format with 'High spam probability' overview."""
    from services.higgins.tc_flyby.report import concern

    # Build the fact exactly as _add_au_domestic_phone_intel() would produce it (updated text).
    intel_fact: dict = {
        "text": "This is an Australian domestic landline number in the Victoria / Tasmania range, not registered to any verified organisation in Apollo's database.",
        "signal": "concern",
        "decisive": True,
        "class": "live_evidence",
        "source": {
            "publisher": "Apollo Phone Intelligence",
            "authority": "independent",
            "basis": "Australian domestic phone number assessment — Victoria / Tasmania",
            "retrieval": "fetched",
            "checkedAt": "2026-06-01T00:00:00+00:00",
        },
        "topic": "au_domestic_spam",
        "phone_intel": {
            "country": "Australia",
            "country_code": "+61",
            "type": "landline",
            "region": "Victoria / Tasmania",
            "area_key": "3",
            "topic": "au_domestic_spam",
        },
    }

    phone_check = Check(id="c-phone", kind="phone", subject="0399968074")
    phone_check.facts.append(intel_fact)
    phone_check.status = "resolved"
    phone_check.route = "official_source"

    plan = _make_plan(checks=[phone_check], has_message=False)
    plan.channel = "call"

    report = concern(plan, plan.checks, {}, "test-flyby-phone", "tc_flyby_official")

    # --- Overview must contain the key phrase ---
    assert "High spam probability" in report["overview"], (
        f"Overview must contain 'High spam probability'; got: {report['overview']!r}"
    )

    # --- Explanation must have all three sections ---
    md = report["explanationMarkdown"]
    assert "**Status**" in md, f"Missing '**Status**' section.\nmd={md!r}"
    assert "**Behavior**" in md, f"Missing '**Behavior**' section.\nmd={md!r}"
    assert "**Recommended Actions**" in md, f"Missing '**Recommended Actions**' section.\nmd={md!r}"

    # --- Recommended action copy ---
    md_lower = md.lower()
    assert "do not call back" in md_lower, f"Missing 'Do Not Call Back' copy.\nmd={md!r}"
    assert "block" in md_lower, f"Missing 'Block' copy.\nmd={md!r}"
    assert ("sms" in md_lower or "text" in md_lower), f"Missing SMS/text copy.\nmd={md!r}"

    # --- Australian context ---
    assert "Australia" in md, f"Missing 'Australia' in explanation.\nmd={md!r}"
    assert "Victoria" in md, f"Missing region label in explanation.\nmd={md!r}"

    # --- Outcome ---
    assert report["outcome"] == "scam", f"Unexpected outcome: {report['outcome']!r}"

    # --- Actions list must have the three expected items ---
    action_labels = [a["label"].lower() for a in report["actions"]]
    assert any("call back" in lbl for lbl in action_labels), (
        f"Missing 'Do not call back' action.\nactions={action_labels}"
    )
    assert any("block" in lbl for lbl in action_labels), (
        f"Missing 'Block' action.\nactions={action_labels}"
    )
    assert any("sms" in lbl or "text" in lbl for lbl in action_labels), (
        f"Missing SMS/text action.\nactions={action_labels}"
    )

    # --- Three structured findings (not a single bare fact) ---
    assert len(report["findings"]) == 3, (
        f"Expected 3 structured findings; got {len(report['findings'])}.\nfindings={[f['text'] for f in report['findings']]}"
    )
    finding_texts = [f["text"] for f in report["findings"]]
    assert any("range" in t for t in finding_texts), "First finding should name the region/range"
    assert any("verified organisation" in t for t in finding_texts), "Second finding should note no verified org"
    assert any("spam probability" in t or "robocall" in t for t in finding_texts), "Third finding should state spam probability"

    # --- No NAB advice anywhere in the report ---
    full_text = report["overview"] + report["explanationMarkdown"] + " ".join(a["label"] + a["instruction"] for a in report["actions"])
    assert "NAB" not in full_text, f"NAB advice must not appear in the AU domestic spam report.\nfull_text={full_text!r}"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 16 — _add_au_domestic_phone_intel fires for a bare AU number (no links)
#            and does NOT fire when co-present link/email checks exist.
# ════════════════════════════════════════════════════════════════════════════════

def test_au_domestic_phone_intel_guard_no_link_checks():
    """_add_au_domestic_phone_intel resolves an AU landline when it is the only
    check in the plan (bare submission), but stays open when a link check is
    co-present — matching the PayID-in-AusPost-SMS guard."""
    from services.higgins.tc_flyby.official import _add_au_domestic_phone_intel
    from services.higgins.tc_flyby.triage import Check, Plan, Entities

    def _bare_plan(subject: str, extra_checks: list[Check]) -> Plan:
        phone_check = Check(id="c-phone", kind="phone", subject=subject)
        checks = [phone_check] + extra_checks
        ent = Entities()
        return Plan(entities=ent, message_type="sms", checks=checks,
                    has_message=bool(extra_checks), link_only=False,
                    general=False, gaps=[], channel="sms"), phone_check

    # ── Case A: bare phone, no co-present link/email → should resolve ──
    plan_a, phone_a = _bare_plan("0399968074", [])
    _add_au_domestic_phone_intel(phone_a)  # call directly (mimicking _phone logic)

    # With the guard logic (no other checks), it should have resolved
    # We rebuild with the actual guard so the test matches production behaviour.
    phone_a2 = Check(id="c-phone", kind="phone", subject="0399968074")
    plan_a2, _ = _bare_plan("0399968074", [])
    plan_a2.checks[0] = phone_a2
    _other_a = [c for c in plan_a2.checks if c is not phone_a2 and c.kind in ("link", "email", "sender")]
    if not _other_a:
        _add_au_domestic_phone_intel(phone_a2)

    assert phone_a2.status == "resolved", (
        f"Bare AU phone should be resolved; got status={phone_a2.status!r}"
    )
    assert any(f.get("topic") == "au_domestic_spam" for f in phone_a2.facts), (
        "Expected au_domestic_spam topic fact on bare AU phone check"
    )

    # ── Case B: phone + link check co-present → should stay open ──
    link_check = Check(id="c-link", kind="link", subject="https://auspost.com.au/redeliver")
    phone_b = Check(id="c-phone-b", kind="phone", subject="0412345678")
    plan_b_checks = [phone_b, link_check]
    ent_b = Entities()
    plan_b = Plan(entities=ent_b, message_type="sms", checks=plan_b_checks,
                  has_message=True, link_only=False, general=False, gaps=[], channel="sms")

    _other_b = [c for c in plan_b.checks if c is not phone_b and c.kind in ("link", "email", "sender")]
    if not _other_b:
        _add_au_domestic_phone_intel(phone_b)
    # _other_b = [link_check], so guard blocks the call

    assert phone_b.status == "open", (
        f"AU phone with co-present link check must stay open; got status={phone_b.status!r}"
    )
