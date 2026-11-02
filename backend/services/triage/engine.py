"""Deterministic Triage evaluator. No AI, no network of its own, zero Gemini calls.

Callers normalise their evidence into the shared evidence dict and pass it here.
Each rule reports: applicable / checked, evidence evaluated, result and any Coverage Gap.

Rule classes (catalogue `class`, rule book "Rule classes"): only DETECT and CORRELATE rules are threat-producing.
A ROUTE rule hands part of the item to the gate whose rules judge it and is recorded as routed; when that gate's
threat-producing rule was met, that rule is the one recorded as met, and this item's record cites it. A COVERAGE
rule only records what couldn't be examined. Neither ever makes a Possible Threat on its own.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from services.triage.catalogue import RETRY_ATTEMPTS, RULES, RULES_BY_CATEGORY, gap_plain, threat_producing
from services.triage.completeness import AVAILABLE_CHECKS, incomplete_plain
from services.triage.contract import CoverageGap, Outcome, RetryRecord, RuleRecord, RuleResult, TriageInvestigation

_log = logging.getLogger("apollo.triage")

Verdict = tuple[RuleResult, list[str], Optional[str]]
NA: Verdict = (RuleResult.NOT_APPLICABLE, [], None)

# Why the browser-observation rules (BITM-01..04) can't execute in a phone app's context.
BROWSER_OBSERVATION_NA = ("Not applicable here: this rule needs the page's live content and WebSocket traffic "
                          "as a browser sees them, which ApolloSG can't observe from an app.")


def na_because(reason: str) -> Verdict:
    """Not applicable, with the reason — so the DI shows the rule was considered and why it couldn't run here."""
    return (RuleResult.NOT_APPLICABLE, [reason], None)


def met(*evidence: str) -> Verdict:
    return (RuleResult.MET, [e for e in evidence if e], None)


def unmet(*evidence: str) -> Verdict:
    return (RuleResult.NOT_MET, [e for e in evidence if e], None)


def gap(code: str, *evidence: str) -> Verdict:
    return (RuleResult.COVERAGE_GAP, [e for e in evidence if e], code)


#: What each ROUTE rule hands over, and the gate that judges it. The routed part's own triage is supplied as
#: `<part>_outcome` and, when it was a Possible Threat, the threat-producing rules it met as `<part>_rules_met`.
#: QR-01 routes the QR address to the Link Gate rules, which run in the same evaluation.
ROUTED_PART: dict[str, Optional[str]] = {"QR-01": None, "MSG-12": "link", "EMAIL-09": "link", "EMAIL-10": "attachment",
                                         "CAL-01": "link", "FILE-10": "link", "FQR-01": "link", "PUSH-03": "link", "NET-02": "link"}
_JUDGED_BY = {"link": "the Link Gate", "attachment": "the File Gate"}


def routed(*evidence: str) -> Verdict:
    return (RuleResult.ROUTED, [e for e in evidence if e], None)


def route(part: str, label: str) -> Callable[[dict], Verdict]:
    """A ROUTE rule: hands `part` to the gate whose rules judge it. Never a Possible Threat by itself."""
    def check(ev: dict) -> Verdict:
        outcome = ev.get(f"{part}_outcome")
        if outcome is None:
            return NA
        return routed(f"{label} handed to {_JUDGED_BY[part]}, which found: {outcome}")
    return check


def _b(ev: dict, path: str) -> Any:
    """Dotted lookup: _b(ev, "signals.code_request")."""
    node: Any = ev
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _sig(ev: dict, name: str) -> bool:
    return bool(_b(ev, f"signals.{name}"))


def _provider(ev: dict, name: str) -> dict:
    value = ev.get(name)
    return value if isinstance(value, dict) else {}


def _correlated(ev: dict, *mechanics: str) -> bool:
    """Evidence-gated correlation: a related event, a compatible mechanic and supporting evidence.
    Time proximity alone is never sufficient — the caller must assert supporting evidence."""
    corr = _provider(ev, "correlation")
    related = corr.get("related") or []
    if not related or not corr.get("supporting_evidence"):
        return False
    if not mechanics:
        return True
    present = {str(m) for m in (corr.get("mechanics") or [])}
    return any(m in present for m in mechanics)


# ── Websites & Links ────────────────────────────────────────────────────────

def _link_rules() -> dict[str, Callable[[dict], Verdict]]:
    def reputation(ev: dict) -> Verdict:
        rep = _provider(ev, "reputation")
        if not rep:
            return NA
        if rep.get("status") in ("unavailable", "not_configured", "error"):
            failure = f" ({rep['failure']})" if rep.get("failure") else ""
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", f"reputation lookup did not complete{failure}")
        if rep.get("verdict") == "malicious":
            return met(f"reputation verdict: malicious ({rep.get('source', 'threat intelligence')})")
        return unmet("reputation verdict: not listed as malicious")

    def redirect_malicious(ev: dict) -> Verdict:
        red = _provider(ev, "redirect")
        if not red or not red.get("hops"):
            return NA
        if red.get("status") in ("unavailable", "error", "incomplete"):
            # The final destination couldn't be verified. That check is recorded as incomplete (incomplete_checks),
            # never as a completed one — and on its own it is not a coverage gap.
            return unmet(f"final destination could not be verified ({red.get('failure') or 'redirect_failure'})")
        if red.get("final_verdict") == "malicious":
            return met(f"redirect destination confirmed malicious: {red.get('final_url', 'unknown')}")
        return unmet(f"redirect chain of {red.get('hops')} hop(s) contains no confirmed malicious destination")

    def local_engine(ev: dict) -> Verdict:
        level = ev.get("local_level")
        if level is None:
            return NA
        if level == "malicious":
            return met(f"local URL engine: malicious via deception-gated rules ({', '.join(ev.get('local_signals') or [])})")
        return unmet(f"local URL engine level: {level}")

    def indicator(ev: dict) -> Verdict:
        if "indicator_match" not in ev:
            return NA
        return met("known deterministic threat indicator matched") if ev["indicator_match"] else unmet("no known threat indicator matched")

    def lookalike_credential(ev: dict) -> Verdict:
        signals = set(ev.get("local_signals") or [])
        if "brand_lookalike" not in signals and not ev.get("brand_mismatch"):
            return unmet("no brand-lookalike domain observed")
        if ev.get("credential_interaction"):
            return met("brand-lookalike domain", "credential/login/payment interaction")
        return unmet("brand-lookalike domain without credential or payment interaction")

    def creds_in_url(ev: dict) -> Verdict:
        if "credentials_in_url" not in ev:
            return NA
        return met("credentials embedded in the URL") if ev["credentials_in_url"] else unmet("no credentials embedded in the URL")

    def credential_lure(ev: dict) -> Verdict:
        if not ev.get("credential_interaction"):
            return unmet("no credential lure observed")
        if ev.get("brand_mismatch") or "brand_in_path" in set(ev.get("local_signals") or []):
            return met("credential lure", "destination unrelated to the brand presented")
        return unmet("credential lure without an unrelated or deceptive destination")

    def displayed_mismatch(ev: dict) -> Verdict:
        displayed, actual = ev.get("displayed_host"), ev.get("actual_host")
        if not displayed or not actual:
            return NA
        if displayed != actual and not actual.endswith("." + displayed) and not displayed.endswith("." + actual):
            return met(f"displayed link {displayed} resolves to {actual}")
        return unmet("displayed and actual destinations are consistent")

    def brand_in_path(ev: dict) -> Verdict:
        signals = set(ev.get("local_signals") or [])
        if "brand_in_path" not in signals:
            return unmet("no brand presented in the link path")
        if ev.get("credential_interaction"):
            return met("brand presented in the link path", "destination belongs to an unrelated domain", "sensitive action requested")
        return unmet("brand in path without a sensitive action")

    def new_domain_form(ev: dict) -> Verdict:
        if not ev.get("credential_interaction"):
            return unmet("no sensitive form — domain age is irrelevant to this rule")
        age = _provider(ev, "domain_age")
        if not age:
            return NA
        if age.get("status") in ("unavailable", "error", "not_configured"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "domain registration age unavailable")
        if age.get("newly_registered"):
            return met("domain registered within 30 days", "credential, payment or identity form")
        return unmet("no newly registered domain combined with a sensitive form")

    def unresolved_threshold(ev: dict) -> Verdict:
        if ev.get("local_level") != "suspicious":
            return unmet("URL-risk indicators below the suspicious threshold")
        rep = _provider(ev, "reputation")
        if rep.get("status") in ("unavailable", "not_configured", "error"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "multiple URL-risk indicators, intelligence unavailable")
        return unmet("URL-risk indicators did not resolve to a deterministic threat")

    def correlates(ev: dict) -> Verdict:
        if ev.get("local_level") in (None, "clean"):
            return unmet("no suspicious URL evidence to correlate")
        return met("suspicious URL evidence correlates with another event") if _correlated(ev) else unmet("no compatible correlated evidence")

    def qr_link(ev: dict) -> Verdict:
        if not ev.get("qr_payload"):
            return NA
        return routed("QR payload contains a URL — judged by the Link Gate rules") if ev.get("qr_is_url") else unmet("QR payload is not a URL")

    def qr_deception(ev: dict) -> Verdict:
        if not ev.get("qr_payload"):
            return NA
        return met("QR destination with brand or domain deception") if ev.get("brand_mismatch") else unmet("QR destination shows no brand deception")

    def qr_lure(ev: dict) -> Verdict:
        if not ev.get("qr_payload"):
            return NA
        age = _provider(ev, "domain_age")
        rep = _provider(ev, "reputation")
        # Unrated only when the lookup answered without a rating: a lookup that failed never supplies evidence.
        unrated = rep.get("status") not in ("unavailable", "not_configured", "error") and rep.get("verdict") == "unknown"
        if not ev.get("credential_interaction"):
            return unmet("QR destination has no credential or payment lure")
        if age.get("newly_registered") or unrated or ev.get("local_level") in ("suspicious", "malicious"):
            return met("QR destination credential/payment lure", "destination suspicious, unrated or newly registered")
        if rep.get("status") in ("unavailable", "not_configured", "error"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "QR destination reputation unavailable")
        return unmet("QR destination has a credential lure but no suspicious, unrated or newly registered destination")

    def data_scheme(ev: dict) -> Verdict:
        if ev.get("scheme") not in ("data", "blob"):
            return NA
        if not _b(ev, "visibility.browser"):
            return gap("BROWSER_VISIBILITY_UNAVAILABLE", "data:/blob: content could not be observed")
        if ev.get("credential_interaction") and ev.get("brand_mismatch"):
            return met("data:/blob: credential collection", "deceptive brand context")
        return unmet("data:/blob: scheme without credential collection in a deceptive context")

    def bitm(rule_id: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            # Without browser/WebSocket observation the rule cannot execute in this context: NOT APPLICABLE
            # (reason recorded) — different from a check that should have run but failed.
            if not _b(ev, "visibility.browser") or not _b(ev, "visibility.websocket"):
                return na_because(BROWSER_OBSERVATION_NA)
            if not ev.get("credential_interaction") and not _b(ev, "code_interaction"):
                return unmet("no sensitive authentication interaction observed")
            relay = bool(ev.get("realtime_relay"))
            inconsistent = bool(ev.get("auth_origin_unrelated") or ev.get("brand_mismatch"))
            deception = bool(ev.get("deception_evidence") or ev.get("local_level") in ("suspicious", "malicious"))
            if rule_id == "BITM-03":
                return met("correlated source", "unrelated authentication origin", "observed relay") if (relay and inconsistent and _correlated(ev)) else unmet("no correlated relay sequence")
            if relay and inconsistent and (deception or rule_id == "BITM-04"):
                return met("sensitive authentication interaction", "unrelated authentication origin", "observed real-time relay")
            return unmet("relay behaviour and destination inconsistency not both observed")
        return check

    def bitm_intel(ev: dict) -> Verdict:
        rep = _provider(ev, "reputation")
        if not rep:
            return NA
        if rep.get("status") in ("unavailable", "not_configured", "error"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "phishing-infrastructure intelligence unavailable")
        if rep.get("verdict") == "malicious" and "phishing" in [str(t).lower() for t in (rep.get("threat_types") or [])]:
            return met("destination matches active phishing/AiTM infrastructure")
        return unmet("destination does not match known AiTM infrastructure")

    return {
        "LINK-01": reputation, "LINK-02": redirect_malicious, "LINK-03": local_engine, "LINK-04": indicator,
        "LINK-05": lookalike_credential, "LINK-06": creds_in_url, "LINK-07": credential_lure,
        "LINK-08": displayed_mismatch, "LINK-09": brand_in_path, "LINK-10": new_domain_form,
        "LINK-11": unresolved_threshold, "LINK-12": correlates,
        "QR-01": qr_link, "QR-02": qr_deception, "QR-03": qr_lure, "DATA-01": data_scheme,
        "BITM-01": bitm("BITM-01"), "BITM-02": bitm("BITM-02"), "BITM-03": bitm("BITM-03"),
        "BITM-04": bitm("BITM-04"), "BITM-05": bitm_intel,
    }


# ── Messages ────────────────────────────────────────────────────────────────

def _message_rules() -> dict[str, Callable[[dict], Verdict]]:
    def flag(name: str, label: str, *, needs: tuple[str, ...] = ()) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if not _sig(ev, name):
                return unmet(f"no {label} observed")
            if needs and not any(_sig(ev, extra) for extra in needs):
                return unmet(f"{label} without a supporting mechanic")
            return met(label)
        return check

    def combination(trigger: str, label: str, *, consequential: tuple[str, ...], anomalies: tuple[str, ...]) -> Callable[[dict], Verdict]:
        """Spec shape: trigger + consequential action + ANOTHER deterministic anomaly."""
        def check(ev: dict) -> Verdict:
            if not _sig(ev, trigger):
                return unmet(f"no {label} observed")
            if not any(_sig(ev, name) for name in consequential):
                return unmet(f"{trigger} without a consequential action")
            extra = [name for name in anomalies
                     if _sig(ev, name) or (name == "brand_mismatch" and ev.get("brand_mismatch"))
                     or (name == "link_threat" and ev.get("link_outcome") == Outcome.POSSIBLE_THREAT.value)]
            if not extra:
                return unmet(f"{trigger} with a consequential action but no supporting anomaly")
            return met(label, f"supporting anomaly: {extra[0]}")
        return check

    def authority(ev: dict) -> Verdict:
        if _b(ev, "signals.brand_kind") != "government":
            return unmet("no authority impersonation observed")
        if any(_sig(ev, s) for s in ("payment_request", "identity_request", "code_request", "threat")):
            return met("government/authority impersonation", "payment, credential, code or threat")
        return unmet("authority claim without a consequential demand")

    def family(ev: dict) -> Verdict:
        if not _sig(ev, "family_claim") and not _sig(ev, "new_number"):
            return unmet("no family or new-number impersonation")
        if any(_sig(ev, s) for s in ("money_request", "code_request", "identity_request")):
            return met("family/new-number impersonation", "money, credential or code request")
        return unmet("family claim without a money, credential or code request")

    def brand_impersonation(ev: dict) -> Verdict:
        if not _b(ev, "signals.claimed_brand"):
            return unmet("no brand claimed")
        consequential = any(_sig(ev, s) for s in ("payment_request", "login_request", "identity_request", "code_request"))
        if consequential and (ev.get("brand_mismatch") or ev.get("link_outcome") == Outcome.POSSIBLE_THREAT.value):
            return met("brand impersonation", "consequential action", "inconsistent contact or destination")
        return unmet("brand claim without both a consequential action and an inconsistent destination")

    def pattern(ev: dict) -> Verdict:
        moderate = [name for name in ("urgency", "threat", "payment_request", "unknown_sender", "platform_switch",
                                      "job_offer", "guaranteed_returns", "crypto", "new_number", "login_request")
                    if _sig(ev, name)]
        if len(moderate) >= 3 and any(_sig(ev, s) for s in ("payment_request", "login_request", "crypto", "identity_request")):
            return met("coherent scam pattern: " + ", ".join(moderate))
        return unmet(f"{len(moderate)} moderate indicator(s) — no coherent scam pattern")

    def rebate_pressure(ev: dict) -> Verdict:
        if not _sig(ev, "government_rebate"):
            return unmet("no government rebate or subsidy claim")
        if not _sig(ev, "time_pressure"):
            return unmet("rebate claim without deadline pressure")
        if _sig(ev, "reply_request") or _sig(ev, "callback_request"):
            return met("government rebate or subsidy claim", "deadline pressure", "request to reply or call")
        return unmet("rebate claim with deadline pressure but no request to reply or call")

    def instant_payment(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if not _sig(ev, "instant_payment"):
                return unmet("no instant-payment request observed")
            if kind == "impersonation" and (_b(ev, "signals.claimed_brand") or _sig(ev, "family_claim")):
                return met("instant-payment request", "authority, family or business impersonation")
            if kind == "urgency" and (_sig(ev, "urgency") or _sig(ev, "threat")) and _sig(ev, "unknown_sender"):
                return met("instant-payment request", "urgency or threat", "sender anomaly")
            if kind == "change" and _sig(ev, "payment_change"):
                return met("unexpected change of payment destination", "immediate-payment request")
            return unmet("instant-payment use alone is not a threat")
        return check

    def forwarding(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if kind == "code":
                if not _sig(ev, "forwarding_code"):
                    return unmet("no forwarding service code instruction")
                if _b(ev, "signals.claimed_brand") or _sig(ev, "threat") or _sig(ev, "login_request"):
                    return met("instruction to enter a call/SMS forwarding code", "suspicious account, security or authority context")
                return unmet("service code without a relevant suspicious context")
            if not _sig(ev, "forwarding_intent"):
                return unmet("no instruction to redirect calls, messages or codes")
            return met("instruction designed to redirect calls, messages or security codes")
        return check

    def callback(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if not _sig(ev, "callback_request"):
                return unmet("no supplied callback number")
            if kind == "charge" and _sig(ev, "alleged_charge"):
                return met("claimed charge or account problem", "callback number supplied by the message")
            if kind == "urgent" and (_sig(ev, "urgency") or _sig(ev, "threat")):
                return met("urgent cancellation, refund or security lure", "suspicious callback number")
            if kind == "clean_reputation":
                # Without a claimed charge or brand this rule can't be met whatever the number's reputation says,
                # so a failed lookup can't change it — it is not a coverage gap.
                # A brand mention alone is weak: the impersonation must be strong (a claimed charge, or a claimed
                # organisation whose contact or destination doesn't match it).
                if not (_sig(ev, "alleged_charge") or (_b(ev, "signals.claimed_brand") and ev.get("brand_mismatch"))):
                    return unmet("callback number without strong impersonation evidence")
                rep = _provider(ev, "phone_reputation")
                if rep.get("status") in ("unavailable", "not_configured", "error"):
                    return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "callback number reputation unavailable")
                if rep.get("verdict") == "clean":
                    return met("clean callback reputation does not override impersonation evidence")
            return unmet("callback lure conditions not met")
        return check

    return {
        "MSG-01": flag("code_request", "OTP/MFA/security code request"),
        "MSG-02": flag("login_request", "password, PIN or login credential request"),
        "MSG-03": flag("identity_request", "banking or card credential request"),
        "MSG-04": flag("safe_account", "transfer to a safe/protected account"),
        "MSG-05": flag("gift_cards", "gift-card payment request"),
        "MSG-06": flag("remote_access", "remote access or screen sharing request"),
        "MSG-07": flag("install_request", "app or software installation request"),
        "MSG-08": authority,
        "MSG-09": flag("extortion", "extortion"),
        "MSG-10": flag("advance_fee", "advance-fee mechanics"),
        "MSG-11": flag("fake_payment", "fake-payment mechanics"),
        "MSG-12": route("each link in the message", "Each link in the message"),
        "MSG-13": family,
        "MSG-14": brand_impersonation,
        "MSG-15": flag("guaranteed_returns", "guaranteed-return approach", needs=("payment_request", "crypto", "money_request")),
        "MSG-16": flag("job_offer", "job offer with payment or credential harvesting", needs=("payment_request", "crypto", "gift_cards", "identity_request")),
        "MSG-17": flag("romance_escalation", "romance interaction with a financial request"),
        "MSG-18": flag("identity_request", "sensitive identity request with impersonation", needs=("claimed_brand", "unknown_sender")),
        "MSG-19": flag("platform_switch", "platform switching with another scam mechanic", needs=("payment_request", "crypto", "job_offer", "guaranteed_returns", "identity_request")),
        "MSG-20": combination("threat", "urgency or threat with a consequential action and a supporting anomaly",
                              consequential=("payment_request", "login_request", "identity_request", "code_request", "money_request"),
                              anomalies=("unknown_sender", "new_number", "platform_switch", "brand_mismatch", "link_threat")),
        "MSG-21": combination("unknown_sender", "uncertain identity with a consequential action and another anomaly",
                              consequential=("payment_request", "login_request", "identity_request", "code_request", "money_request"),
                              anomalies=("urgency", "threat", "new_number", "platform_switch", "brand_mismatch", "link_threat")),
        "MSG-22": pattern,
        "PAY-01": instant_payment("impersonation"), "PAY-02": instant_payment("urgency"), "PAY-03": instant_payment("change"),
        "FWD-01": forwarding("code"), "FWD-02": forwarding("intent"),
        "CB-01": callback("charge"), "CB-02": callback("urgent"), "CB-03": callback("clean_reputation"),
        # A real organisation has no reason to write its own name with look-alike characters: on its own this is enough.
        "MSG-23": flag("lookalike_name", "organisation name written with look-alike characters"),
        "MSG-24": rebate_pressure,
    }


# ── Calls ───────────────────────────────────────────────────────────────────

def _call_rules() -> dict[str, Callable[[dict], Verdict]]:
    def ask(name: str, label: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            asks = set(ev.get("asks") or [])
            return met(f"caller asked: {label}") if name in asks else unmet(f"caller did not ask: {label}")
        return check

    def safe_account(ev: dict) -> Verdict:
        asks = set(ev.get("asks") or [])
        if "transfer" not in asks:
            return unmet("no transfer requested")
        if ev.get("claim") == "bank" or ev.get("safe_account"):
            return met("caller requested a transfer to a safe/protected account")
        return unmet("transfer requested without a safe-account framing")

    def authority_payment(ev: dict) -> Verdict:
        if ev.get("claim") != "government":
            return unmet("caller did not claim government authority")
        asks = set(ev.get("asks") or [])
        if asks & {"transfer", "crypto", "bankdetails", "giftcards"} or ev.get("threat"):
            return met("claimed authority", "payment demand or threat")
        return unmet("authority claim without a payment demand")

    def tech_support(ev: dict) -> Verdict:
        if ev.get("claim") != "techsupport":
            return unmet("caller did not claim technical support")
        asks = set(ev.get("asks") or [])
        return met("unsolicited technical support", "device access requested") if asks & {"remote", "screen", "install"} else unmet("tech-support claim without a device-access request")

    def investment(ev: dict) -> Verdict:
        if ev.get("claim") != "investment":
            return unmet("no investment solicitation")
        asks = set(ev.get("asks") or [])
        return met("investment solicitation", "consequential financial action") if asks & {"transfer", "crypto", "bankdetails"} else unmet("investment solicitation without a financial action")

    def claimed_authority(ev: dict) -> Verdict:
        if ev.get("claim") in (None, "unknown"):
            return unmet("caller identity not claimed")
        asks = set(ev.get("asks") or [])
        if asks & {"transfer", "code", "password", "bankdetails", "remote", "screen"} and (ev.get("threat") or ev.get("dont_hangup")):
            return met("claimed authority", "sensitive action", "suspicious behaviour")
        return unmet("claimed authority without both a sensitive action and suspicious behaviour")

    def reputation_behaviour(ev: dict) -> Verdict:
        rep = _provider(ev, "phone_reputation")
        if not rep:
            return NA
        if rep.get("status") in ("unavailable", "not_configured", "error"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "caller reputation unavailable")
        asks = set(ev.get("asks") or [])
        risky_ask = bool(asks - {"nothing", "other"})
        if rep.get("verdict") in ("malicious", "high_risk") and risky_ask:
            return met("negative caller reputation", "matching scam behaviour")
        return unmet("reputation evidence without matching scam behaviour")

    def sequence(ev: dict) -> Verdict:
        return met("call followed by remote-access/permission/device change") if _correlated(ev, "remote_access", "permission_change", "device_change") else unmet("no coherent post-call sequence")

    return {
        "CALL-01": ask("code", "a verification or security code"),
        "CALL-02": ask("password", "a password or PIN"),
        "CALL-03": ask("bankdetails", "banking or card credentials"),
        "CALL-04": safe_account,
        "CALL-05": ask("giftcards", "gift-card payment"),
        "CALL-06": ask("crypto", "a cryptocurrency transfer"),
        "CALL-07": ask("remote", "remote access or screen sharing"),
        "CALL-08": ask("install", "software or app installation"),
        "CALL-09": ask("forwarding", "a call/SMS forwarding instruction"),
        "CALL-10": authority_payment, "CALL-11": tech_support, "CALL-12": investment,
        "CALL-13": claimed_authority, "CALL-14": ask("refund", "an unexpected refund or payment change"),
        "CALL-15": reputation_behaviour, "CALL-16": sequence,
    }


# ── Email & Accounts ────────────────────────────────────────────────────────

_FREEMAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me", "aol.com", "mail.com"}
_FORM_HOSTS = ("docs.google.com", "forms.gle", "forms.office.com", "forms.microsoft.com", "typeform.com", "airtable.com", "jotform.com")


def _email_rules() -> dict[str, Callable[[dict], Verdict]]:
    """Structured checks on the email itself (see services/triage_engine._rule_evidence): who it presents itself as,
    what it asks, and where its links really go. Apollo's own observation wording is never matched as evidence."""
    def _quote(ev: dict, *kinds: str) -> str:
        quotes = (_provider(ev, "requests").get("quotes") or {})
        said = next((quotes[k] for k in kinds if quotes.get(k)), "")
        return f"it asks: “{said}”" if said else ""

    def _brand(ev: dict) -> str:
        return str(ev.get("claimed_brand") or "")

    def brand_mismatch(ev: dict) -> Verdict:
        brand = _brand(ev)
        if not brand:
            return unmet("the email doesn't present itself as an organisation on ApolloSG's register")
        if not ev.get("sender_domain"):
            return unmet("sender address unavailable")
        if not ev.get("sender_domain_mismatch"):
            return unmet(f"sent from {brand}'s own domain")
        if not ev.get("consequential_action"):
            return unmet(f"presents itself as {brand} from {ev['sender_domain']}, but asks nothing consequential")
        return met(f"presents itself as {brand}", f"sent from {ev['sender_domain']}, not one of {brand}'s domains",
                   _quote(ev, "secret_request", "code_request", "card_request", "sign_in_request", "payment_detail_update") or "consequential action")

    def freemail(ev: dict) -> Verdict:
        domain = (ev.get("sender_domain") or "").lower()
        if not domain:
            return na_because("Not applicable here: ApolloSG didn't receive the sender's address.")
        if domain in _FREEMAIL and _brand(ev) and ev.get("consequential_action"):
            return met(f"freemail sender {domain} presenting itself as {_brand(ev)}", "sensitive request")
        return unmet("sender domain is not an impersonating freemail account")

    def security_link(ev: dict) -> Verdict:
        if not ev.get("security_alert"):
            return unmet("no account or security alert")
        if not _brand(ev):
            return unmet("security alert without an organisation it claims to be from")
        if ev.get("displayed_host") and ev.get("actual_host"):
            return met(f"{_brand(ev)} account or security alert", f"a link shows {ev['displayed_host']} but goes to {ev['actual_host']}")
        deceptive = [d["host"] for d in ev.get("action_destinations") or [] if d.get("kind") in ("lookalike", "shared_service")]
        if deceptive:
            return met(f"{_brand(ev)} account or security alert", f"its link goes to {deceptive[0]}, a lookalike of {_brand(ev)}'s address")
        elsewhere = [d["host"] for d in ev.get("action_destinations") or [] if d.get("kind") == "unrelated"]
        if elsewhere and ev.get("credential_request"):
            return met(f"{_brand(ev)} account or security alert", f"it asks you to act at {elsewhere[0]}, which isn't {_brand(ev)}'s")
        return unmet(f"the alert's links go to {_brand(ev)}'s own addresses, or ask nothing of you")

    def credential(ev: dict) -> Verdict:
        asks = _provider(ev, "requests")
        if asks.get("secret_request") or asks.get("card_request"):
            return met(_quote(ev, "secret_request", "card_request"))
        if ev.get("credential_request"):
            return met(_quote(ev, "sign_in_request", "payment_detail_update"), *[f"supported by: {s}" for s in (ev.get("request_support") or [])[:2]])
        if asks.get("sign_in_request") or asks.get("payment_detail_update"):
            return unmet("an ordinary sign-in or update request, with nothing to suggest it isn't genuine")
        return unmet("no request for a password, PIN, login or card details" + (" (it advises never to share them)" if asks.get("negated_advice") else ""))

    def code(ev: dict) -> Verdict:
        asks = _provider(ev, "requests")
        if ev.get("code_request"):
            return met(_quote(ev, "code_request"))
        if asks.get("code_delivery"):
            return unmet("a code delivered for you to use, not a request to send one")
        return unmet("no request to send or read out a one-time code")

    def payment_change(ev: dict) -> Verdict:
        return met("invoice or payment with new or changed bank details") if ev.get("payment_change") else unmet("no change of payment details")

    def executive(ev: dict) -> Verdict:
        if not ev.get("executive_request"):
            return unmet("no executive request for an unusual payment")
        anomaly = ev.get("reply_to_mismatch") or ev.get("sender_domain_mismatch") or (ev.get("sender_domain") or "") in _FREEMAIL
        return met("executive request for an urgent transfer", "sender anomaly") if anomaly else unmet("executive request without a sender anomaly")

    def reply_to(ev: dict) -> Verdict:
        if ev.get("reply_to_mismatch") is None:
            return na_because("Not applicable here: ApolloSG didn't receive the email's Reply-To header.")
        if ev["reply_to_mismatch"] and ev.get("consequential_action"):
            return met("material From/Reply-To mismatch", "consequential action")
        return unmet("no material From/Reply-To mismatch")

    def auth_failure(ev: dict) -> Verdict:
        auth = _provider(ev, "auth_results")
        if not auth:
            # A check that couldn't run (recorded as incomplete by the evidence), never a gap that holds the result.
            return na_because("Not applicable here: the receiving mail server's SPF, DKIM and DMARC results weren't available.")
        failed = [m for m in ("spf", "dkim", "dmarc") if auth.get(m) in ("fail", "softfail", "permerror")]
        if failed and ev.get("consequential_action"):
            by = ev.get("auth_recorded_by") or "the receiving mail server"
            return met(f"authentication failure recorded by {by} ({', '.join(failed)})", "consequential request")
        return unmet("no authentication failure combined with a consequential request")

    def authenticated_anomaly(ev: dict) -> Verdict:
        auth = _provider(ev, "auth_results")
        if not auth or not any(auth.get(m) == "pass" for m in ("spf", "dkim", "dmarc")):
            return unmet("sender not authenticated — rule not applicable")
        # A sign-in request from an authenticated sender is ordinary; a credential request counts only with an anomaly.
        strong = [name for name, flag in (("changed payment details", ev.get("payment_change")),
                                          ("malicious link", ev.get("link_outcome") == Outcome.POSSIBLE_THREAT.value),
                                          ("unusual credential request", ev.get("credential_request") and (ev.get("sender_domain_mismatch") or ev.get("reply_to_mismatch"))),
                                          ("dangerous attachment", ev.get("attachment_outcome") == Outcome.POSSIBLE_THREAT.value)) if flag]
        return met("authenticated sender", *strong) if strong else unmet("authenticated sender with no strong anomaly")

    def coherent(ev: dict) -> Verdict:
        auth = _provider(ev, "auth_results")
        anomalies = [name for name, flag in (("sender isn't the organisation it claims", ev.get("sender_domain_mismatch")),
                                             ("its link goes elsewhere", ev.get("destination_mismatch")),
                                             ("replies go elsewhere", ev.get("reply_to_mismatch")),
                                             ("authentication failed", any(auth.get(m) in ("fail", "softfail", "permerror") for m in ("spf", "dkim", "dmarc"))),
                                             ("shown link differs from its destination", ev.get("displayed_host"))) if flag]
        if len(anomalies) >= 2 and ev.get("consequential_action"):
            return met("coherent scam pattern: " + ", ".join(anomalies), "consequential request")
        return unmet(f"{len(anomalies)} email anomaly(ies)" + ("" if ev.get("consequential_action") else ", nothing consequential asked"))

    def calendar(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            cal = _provider(ev, "calendar")
            if not cal:
                return NA
            if cal.get("status") in ("unavailable", "error"):
                return gap("CONTENT_NOT_ACCESSIBLE", "calendar/.ics content could not be inspected")
            if kind == "link":
                return route("link", "The invitation's link")(ev)
            if kind == "callback" and _sig(ev, "callback_request"):
                return met("calendar invitation", "financial/account lure with a callback number")
            if kind == "credential" and ev.get("credential_interaction"):
                return met("calendar invitation", "credential or payment collection destination")
            return unmet("calendar invitation alone is not a threat")
        return check

    def form(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            hosts = [str(h).lower() for h in (ev.get("link_domains") or [])]
            host = next((h for h in hosts if any(h == f or h.endswith("." + f) for f in _FORM_HOSTS)), None)
            if not host:
                return unmet("no legitimate form-builder host in the links")
            if kind == "credential" and (ev.get("credential_request") or ev.get("code_request") or _sig(ev, "code_request")):
                return met(f"form service {host}", "password/MFA/security-code request")
            if kind == "banking" and ev.get("banking_request") and (ev.get("sender_domain_mismatch") or ev.get("consequential_action")):
                return met(f"form service {host}", "banking or card credentials", "suspicious originating context")
            if kind == "identity" and ev.get("identity_request") and ev.get("claimed_brand"):
                return met(f"form service {host}", "sensitive identity collection", "impersonation or account-security lure")
            return unmet("form-builder domain alone is not suspicious")
        return check

    def breach(ev: dict) -> Verdict:
        data = _provider(ev, "breach")
        if not data:
            return NA
        if data.get("status") in ("unavailable", "not_configured", "error"):
            return gap("INTELLIGENCE_PROVIDER_UNAVAILABLE", "breach intelligence unavailable")
        if data.get("status") == "found" and (ev.get("credential_request") or ev.get("account_takeover_activity")):
            return met("confirmed exposed credential", "current credential-harvesting or takeover activity")
        return unmet("breach appearance alone is a security history finding, not current malicious activity")

    return {
        "EMAIL-01": brand_mismatch, "EMAIL-02": freemail,
        "EMAIL-03": security_link, "EMAIL-04": credential, "EMAIL-05": code,
        "EMAIL-06": payment_change, "EMAIL-07": executive,
        "EMAIL-08": reply_to, "EMAIL-09": route("link", "Each embedded link"), "EMAIL-10": route("attachment", "Each attachment"),
        "EMAIL-11": auth_failure, "EMAIL-12": authenticated_anomaly, "EMAIL-13": coherent,
        "CAL-01": calendar("link"), "CAL-02": calendar("callback"), "CAL-03": calendar("credential"),
        "FORM-01": form("credential"), "FORM-02": form("banking"), "FORM-03": form("identity"),
        "BREACH-01": breach,
    }


# ── Files (server-side inspectable subset) ──────────────────────────────────

_RISKY_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs", ".wsf", ".msi", ".dll",
              ".hta", ".ps1", ".reg", ".lnk", ".iso", ".img", ".cab", ".jar", ".apk"}
_MACRO_EXT = {".docm", ".xlsm", ".pptm", ".dotm", ".xlam"}
_PROFILE_EXT = {".mobileconfig", ".plist", ".cer", ".crt", ".pem", ".p12", ".pfx"}


def harmful_payload(entries: list[str]) -> list[str]:
    """Archive entries that are a harmful or suspicious payload: a program, script, installer or app package, a
    profile or certificate, a macro-enabled document, or a disguised or path-traversing name."""
    def ext(name: str) -> str:
        return ("." + name.lower().rsplit(".", 1)[-1]) if "." in name else ""
    return [e for e in entries if ext(e) in _RISKY_EXT | _MACRO_EXT | _PROFILE_EXT
            or e.startswith("/") or ".." in e or "\u202e" in e]


def _file_rules() -> dict[str, Callable[[dict], Verdict]]:
    def name_of(ev: dict) -> str:
        return str(ev.get("filename") or "")

    def ext_of(ev: dict) -> str:
        name = name_of(ev).lower()
        return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""

    def disguised(ev: dict) -> Verdict:
        declared, actual = ev.get("declared_type"), ev.get("actual_type")
        if not actual:
            return gap("UNSUPPORTED_FILE_TYPE", "file content type could not be determined") if ev.get("inspection") == "unsupported" else NA
        if declared and actual and declared != actual and actual in ("executable", "script"):
            return met(f"file presented as {declared} but is actually {actual}")
        return unmet("file type presentation is consistent")

    def double_ext(ev: dict) -> Verdict:
        name = name_of(ev).lower()
        parts = name.split(".")
        if len(parts) >= 3 and ("." + parts[-1]) in _RISKY_EXT and parts[-2] in ("pdf", "doc", "docx", "jpg", "jpeg", "png", "txt", "xls", "xlsx"):
            return met(f"dangerous double extension: {name}")
        return unmet("no dangerous double extension")

    def rtl(ev: dict) -> Verdict:
        name = name_of(ev)
        return met("right-to-left override character in the filename") if any(ch in name for ch in ("\u202e", "\u202b", "\u202a")) else unmet("no right-to-left filename deception")

    def unexpected_exec(ev: dict) -> Verdict:
        ext = ext_of(ev)
        if ext not in _RISKY_EXT:
            return unmet("file is not an executable or script")
        return met(f"unexpected executable/script ({ext})") if not ev.get("expected") else unmet("executable was expected by the person")

    def apk(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if ext_of(ev) != ".apk":
                return unmet("file is not an APK")
            # An unknown provenance is not a suspicious one: unknown is never unsafe.
            if kind == "suspicious" and (ev.get("provenance") in ("sideload", "message", "link") or not ev.get("expected")):
                return met("suspicious APK provenance")
            if kind == "brand" and ev.get("brand_mismatch"):
                return met("APK impersonates a brand or update")
            return unmet("APK without suspicious provenance or brand deception")
        return check

    def ext_rule(exts: set[str], label: str, *, needs_provenance: bool = False) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            if ext_of(ev) not in exts:
                return unmet(f"file is not {label}")
            if needs_provenance and ev.get("provenance") in ("store", "expected", None) and ev.get("expected"):
                return unmet(f"{label} with expected provenance")
            if not needs_provenance and ev.get("expected"):
                return unmet(f"{label} the person expected")
            return met(f"{label} ({ext_of(ev)})")
        return check

    def embedded_url(ev: dict) -> Verdict:
        if ev.get("embedded_urls") is None:
            return NA
        return route("link", "Each link inside the file")(ev)

    def features(key: str, label: str, code: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            data = _provider(ev, key)
            if not data:
                return NA
            if data.get("status") in ("unavailable", "error", "unsupported"):
                return gap(code, f"{label} could not be inspected")
            dangerous = [name for name in (data.get("dangerous") or [])]
            return met(f"{label}: {', '.join(dangerous[:4])}") if dangerous else unmet(f"{label} contains nothing dangerous")
        return check

    def archive(kind: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            data = _provider(ev, "archive")
            if not data:
                return NA
            if data.get("encrypted") and not data.get("entries"):
                if kind in ("entries", "traversal"):
                    return gap("ENCRYPTED_CONTENT", "archive contents are encrypted and could not be inspected")
                if kind == "unreadable":
                    # ARCH-03 is COVERAGE: contents that can't be inspected are a coverage gap, never a threat. A suspicious
                    # sender or lure that came with it is judged by the Text Gate or Email Gate rules.
                    lure = " (it came with a suspicious sender or lure)" if (ev.get("suspicious_source") or _correlated(ev)) else ""
                    return gap("ENCRYPTED_CONTENT", f"archive contents are encrypted and could not be inspected{lure}")
                if kind in ("password_in_message", "password_correlated"):
                    return unmet("archive contents not available to evaluate")
            entries = [str(e) for e in (data.get("entries") or [])]
            dangerous = [e for e in entries if ("." + e.lower().rsplit(".", 1)[-1]) in _RISKY_EXT] if entries else []
            traversal = [e for e in entries if e.startswith("/") or ".." in e or any(ch in e for ch in ("\u202e",))]
            if kind == "entries":
                return met(f"archive contains dangerous content: {', '.join(dangerous[:3])}") if dangerous else unmet("archive contains no executable or script")
            if kind == "traversal":
                return met(f"archive contains path traversal or deceptive filenames: {', '.join(traversal[:3])}") if traversal else unmet("archive filenames are ordinary")
            if kind in ("password_in_message", "password_correlated") and data.get("encrypted") and dangerous:
                if kind == "password_in_message" and data.get("password_source") == "originating_message":
                    return met("password-protected archive", "password supplied in the originating message", "dangerous payload")
                if kind == "password_correlated" and _correlated(ev):
                    return met("password-protected archive", "password correlated to the same case", "dangerous payload")
            return unmet("password protection alone is not a threat")
        return check

    def qr(ev: dict) -> Verdict:
        if not ev.get("qr_payload"):
            return NA
        return route("link", "The QR code's address")(ev)

    return {
        "FILE-01": disguised, "FILE-02": double_ext, "FILE-03": rtl, "FILE-04": unexpected_exec,
        "FILE-05": apk("suspicious"), "FILE-06": apk("brand"),
        "FILE-07": ext_rule({".mobileconfig", ".plist"}, "a configuration profile"),
        "FILE-08": ext_rule({".cer", ".crt", ".pem", ".p12", ".pfx"}, "a trust certificate"),
        "FILE-09": ext_rule(_MACRO_EXT, "a macro-enabled document", needs_provenance=True),
        "FILE-10": embedded_url,
        "FILE-11": features("pdf_features", "PDF active content", "UNSUPPORTED_FILE_TYPE"),
        "FILE-12": features("office_features", "Office macro/template content", "UNSUPPORTED_FILE_TYPE"),
        "FILE-13": archive("entries"), "FILE-14": archive("traversal"), "FILE-15": disguised,
        "ARCH-01": archive("password_in_message"), "ARCH-02": archive("password_correlated"),
        "ARCH-03": archive("unreadable"), "FQR-01": qr,
    }


# ── Apps, Device, Internet (evaluated on device; server records applicability) ──

def _device_side_rules(category: str) -> dict[str, Callable[[dict], Verdict]]:
    def unavailable(rule_id: str) -> Callable[[dict], Verdict]:
        definition = RULES[rule_id]

        def check(ev: dict) -> Verdict:
            if not ev.get(definition["category"] + "_evidence"):
                return NA
            return gap(definition.get("gapCode", "PLATFORM_CAPABILITY_UNAVAILABLE"),
                       "this signal is only observable on the device")
        return check

    return {row["id"]: unavailable(row["id"]) for row in RULES_BY_CATEGORY.get(category, [])}


def _correlation_rules() -> dict[str, Callable[[dict], Verdict]]:
    mechanics = {
        "CORR-01": ("remote_access",), "CORR-02": ("app_install", "pwa_install"), "CORR-03": ("payment_change", "instant_payment"),
        "CORR-04": ("auth_relay",), "CORR-05": ("callback",), "CORR-06": ("dns_change", "vpn_change", "permission_change"),
        "CORR-07": ("download", "malicious_destination"), "CORR-08": ("archive_password",), "CORR-09": ("web_push",),
    }

    def check_for(rule_id: str) -> Callable[[dict], Verdict]:
        def check(ev: dict) -> Verdict:
            corr = _provider(ev, "correlation")
            if not corr.get("related"):
                return NA
            if not _correlated(ev, *mechanics[rule_id]):
                return unmet("no compatible correlated mechanic with supporting evidence")
            if rule_id == "CORR-08":
                # CORR-08 needs payload evidence: the archive's contents must show a harmful or suspicious payload.
                data = _provider(ev, "archive")
                entries = [str(e) for e in (data.get("entries") or [])]
                if data.get("encrypted") and not entries:
                    return gap("ENCRYPTED_CONTENT", "archive contents are encrypted and could not be inspected")
                payload = harmful_payload(entries)
                if not payload:
                    return unmet("password supplied with the archive, but its contents show no harmful payload")
                return met(f"correlated sequence: {RULES[rule_id]['title']}", f"harmful payload: {', '.join(payload[:3])}")
            return met(f"correlated sequence: {RULES[rule_id]['title']}")
        return check

    return {rule_id: check_for(rule_id) for rule_id in mechanics}


_REGISTRY: dict[str, dict[str, Callable[[dict], Verdict]]] = {
    "link": _link_rules(), "message": _message_rules(), "call": _call_rules(), "email": _email_rules(),
    "account": _email_rules(), "file": _file_rules(), "app": _device_side_rules("app"),
    "device": _device_side_rules("device"), "network": _device_side_rules("network"),
    "correlation": _correlation_rules(),
}

#: Which catalogue categories are evaluated for each source type.
_SCOPE: dict[str, tuple[str, ...]] = {
    "link": ("link", "correlation"), "url": ("link", "correlation"), "site": ("link", "correlation"),
    "qr": ("link", "correlation"),
    "message": ("message", "link", "correlation"), "text": ("message", "link", "correlation"),
    "sms": ("message", "link", "correlation"),
    "call": ("call", "correlation"), "email": ("email", "link", "correlation"),
    "account": ("account", "correlation"), "file": ("file", "link", "correlation"),
    "app": ("app", "correlation"), "device": ("device", "correlation"), "network": ("network", "correlation"),
}


async def run_with_retries(check: str, operation: Callable[[], Any], *, attempts: int = RETRY_ATTEMPTS,
                           permanent: bool = False) -> tuple[Any, RetryRecord]:
    """Bounded deterministic retry for TRANSIENT non-AI failures only (initial + 2 retries).

    Permanent platform/capability limitations are never retried.
    """
    if permanent:
        return None, RetryRecord(check=check, attempts=0, outcome="not_retried_permanent")
    last: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            result = operation()
            if asyncio.iscoroutine(result):
                result = await result
            return result, RetryRecord(check=check, attempts=attempt, outcome="recovered" if attempt > 1 else "succeeded")
        except Exception as exc:  # transient provider/network/deterministic failure
            last = exc
            if attempt < attempts:
                await asyncio.sleep(0)
    _log.info("triage_retry_exhausted check=%s attempts=%d error=%s", check, attempts, type(last).__name__ if last else "?")
    return None, RetryRecord(check=check, attempts=attempts, outcome="failed")


def evaluate(evidence: dict, *, investigation_id: Optional[str] = None,
             retries: Optional[list[RetryRecord]] = None) -> TriageInvestigation:
    """Run every applicable catalogue rule for this evidence. Zero Gemini calls."""
    source_type = str(evidence.get("source_type") or "unknown")
    categories = _SCOPE.get(source_type, ("correlation",))
    records: list[RuleRecord] = []

    for category in categories:
        for definition in RULES_BY_CATEGORY.get(category, []):
            predicate = _REGISTRY.get(category, {}).get(definition["id"])
            if predicate is None:
                records.append(RuleRecord(definition["id"], RuleResult.NOT_APPLICABLE,
                                          detail="runs in Higgins Triage on the phone, not on ApolloSG's servers"))
                continue
            try:
                result, used, gap_code = predicate(evidence)
            except Exception as exc:  # a broken predicate must never silently pass as safe
                _log.warning("triage_rule_error rule=%s error=%s", definition["id"], type(exc).__name__)
                records.append(RuleRecord(definition["id"], RuleResult.COVERAGE_GAP, gap_code="DETERMINISTIC_CHECK_ERROR",
                                          detail=type(exc).__name__))
                continue
            records.append(RuleRecord(definition["id"], result, evidence=used, gap_code=gap_code))

    _cite_routed(records, evidence)

    gaps: dict[str, CoverageGap] = {}
    for record in records:
        if record.result is RuleResult.COVERAGE_GAP and record.gap_code:
            entry = gaps.setdefault(record.gap_code, CoverageGap(record.gap_code, record.detail or "", []))
            entry.rule_ids.append(record.rule_id)
            if not entry.detail and record.evidence:
                entry.detail = record.evidence[0]
            # How the lookup this rule needed failed (timeout, quota_exhausted, …) — from the rule's own evidence.
            entry.failure = entry.failure or _failure_for(record.rule_id, evidence)
    incomplete = [dict(c) for c in (evidence.get("incomplete_checks") or []) if isinstance(c, dict) and c.get("check")]

    # Only a threat-producing rule (DETECT or CORRELATE) makes a Possible Threat.
    met_records = [r for r in records if r.result is RuleResult.MET and threat_producing(r.rule_id)]
    if met_records:
        outcome = Outcome.POSSIBLE_THREAT
        reason = met_records[0].title + (f" (+{len(met_records) - 1} more deterministic rule(s) met)" if len(met_records) > 1 else "")
    elif gaps:
        outcome = Outcome.LIMITED
        # Plain English for the person; the codes stay on the record's coverage gaps for the DI view.
        reason = "ApolloSG couldn't obtain enough evidence to decide. " + " ".join(gap_plain(code) for code in sorted(gaps))
    elif evidence.get("unresolved_concern"):
        outcome = Outcome.LIMITED
        gaps["INSUFFICIENT_EVIDENCE"] = CoverageGap("INSUFFICIENT_EVIDENCE",
                                                    str(evidence.get("unresolved_concern_detail") or
                                                        "Concerning indicators did not satisfy any deterministic threat rule."), [])
        reason = "Concerning indicators did not satisfy a deterministic Possible Threat rule."
    elif incomplete:
        # Never present an incomplete examination as a complete one.
        outcome = Outcome.NO_THREAT
        reason = f"{AVAILABLE_CHECKS}. Not completed: " + " ".join(incomplete_plain(c) for c in incomplete)
    else:
        outcome = Outcome.NO_THREAT
        reason = "No deterministic threat rule was met and every applicable check completed."

    return TriageInvestigation(
        investigation_id=investigation_id or str(uuid.uuid4()),
        source_type=source_type,
        outcome=outcome,
        reason=reason,
        rules=records,
        coverage_gaps=list(gaps.values()),
        incomplete_checks=incomplete,
        retries=list(retries or []),
        correlation=_provider(evidence, "correlation"),
        evaluated_at=datetime.now(timezone.utc),
        gemini_calls=0,
    )


def _cite_routed(records: list[RuleRecord], evidence: dict) -> None:
    """A ROUTE rule's part was a Possible Threat at its own gate: the threat-producing rules met there are the ones
    recorded as met, and this item's record cites them."""
    for record in [r for r in records if r.result is RuleResult.ROUTED]:
        part = ROUTED_PART.get(record.rule_id)
        if not part or evidence.get(f"{part}_outcome") != Outcome.POSSIBLE_THREAT.value:
            continue
        for rule_id in evidence.get(f"{part}_rules_met") or []:
            if rule_id not in RULES or not threat_producing(rule_id):
                continue
            existing = next((i for i, r in enumerate(records) if r.rule_id == rule_id), None)
            if existing is not None and records[existing].result is RuleResult.MET:
                continue
            cited = RuleRecord(rule_id, RuleResult.MET, evidence=[f"met at {_JUDGED_BY[part]} for the part handed over by {record.rule_id}"],
                               detail=f"cited from {record.rule_id}")
            if existing is None:
                records.append(cited)
            else:
                records[existing] = cited


def _failure_for(rule_id: str, evidence: dict) -> Optional[str]:
    """The failure kind recorded on the first provider this rule reads (catalogue `evidence`), if any."""
    for name in RULES.get(rule_id, {}).get("evidence") or []:
        value = evidence.get(name)
        if isinstance(value, dict) and value.get("failure"):
            return str(value["failure"])
    return None
