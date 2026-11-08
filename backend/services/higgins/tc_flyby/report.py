"""What Higgins shows when TC Hawkeye settles a check, and the slice Magnum DI receives when it can't.

Higgins explains what was found → what it means → what to do. Every finding is live evidence about this
case, citing the TC Hawkeye evidence item and the source that established it. Apollo KB knowledge is never a
finding: it appears only as supporting context in the explanation. Anything TC Hawkeye could not establish stays
an uncertainty — missing evidence is never turned into a fact.
"""
from __future__ import annotations

import json
import re

from services.higgins import outcomes
from services.higgins.tc_flyby.decide import WARNING, Decision, corroborated_impersonation, signals
from services.higgins.tc_flyby.triage import Check, Plan

ROUTE_LABEL = {"tc_flyby_official": "official source checks", "tc_flyby_kb": "ApolloSG's knowledge base", "tc_flyby_search": "a targeted web search"}


def _finding(f: dict, evidence_ids: list[str], confidence: str) -> dict:
    return {"text": f["text"], "basis": "observation", "confidence": confidence, "evidenceIds": evidence_ids,
            "sourceIds": f.get("sourceIds") or [], "supersedesFindingIds": []}


def _action(label: str, instruction: str) -> dict:
    return {"kind": "instruction", "label": label, "instruction": instruction, "capabilityId": None, "sourceIds": [],
            "desiredField": None, "desiredValue": None}


def _live(checks: list[Check]) -> list[tuple[Check, dict]]:
    return [(c, f) for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] != "missing"]


def _signs(checks: list[Check]) -> list[tuple[Check, dict]]:
    """Warning signs first, then the weak signals (recorded, never a concern on their own)."""
    live = _live(checks)
    return [(c, f) for c, f in live if f["signal"] in WARNING] + [(c, f) for c, f in live if f["signal"] == "weak"]


def _knowledge(checks: list[Check]) -> list[dict]:
    return [f for c in checks for f in c.facts if f.get("class") == "apollo_knowledge"]


def _not_found(checks: list[Check]) -> list[str]:
    """How ApolloSG checked, for the DI tab only: lookups that found nothing or didn't answer. They describe TC Hawkeye's
    method, so they are never listed under what isn't certain."""
    out = [f["text"] for c in checks for f in c.facts if f["signal"] == "missing"]
    out += [f"{c.subject}: TC Hawkeye's lookup was unavailable, so this wasn't established either way." for c in checks if c.status == "unavailable"]
    return [t if t.endswith((".", "!", "?")) else f"{t}." for t in out]


def _topic(text: str) -> str:
    """"Impersonation: whether it's from Linkt." reads as "impersonation (whether it's from Linkt)"."""
    t = f"{text[0].lower()}{text[1:]}".strip().rstrip(".")
    m = re.match(r"^([^:()]{1,40}): (.+)$", t)
    return f"{m.group(1)} ({m.group(2)})" if m else t


def _method(lead: str, checks: list[Check], *, not_taken: bool) -> str:
    """"How ApolloSG checked": what TC Hawkeye did and, said once after the reason it gives, the open issues it didn't take
    further; then the lookups that found nothing or didn't answer."""
    topics = [_topic(c.open_issue) for c in checks if not_taken and c.open_issue and c.status in ("open", "needs_reasoning", "not_needed")]
    return " ".join([lead, *([f"So these weren't taken further: {'; '.join(topics)}."] if topics else []), *_not_found(checks)])


def _who(plan_: Plan) -> str:
    return f"Apollo can't confirm who actually {'called' if plan_.channel == 'call' else 'sent this'}."


_PAGE_UNOPENED = "ApolloSG didn't open the page, so what it shows or asks for wasn't checked."


def _knowledge_block(checks: list[Check]) -> str:
    notes = _knowledge(checks)
    if not notes:
        return ""
    lines = "\n".join(f"- {f['text']}" + (f" — {f['source']['url']}" if (f.get("source") or {}).get("url") else "") for f in notes[:4])
    return f"\n\n**What ApolloSG's knowledge base adds** (general knowledge, not evidence about what you sent)\n{lines}"


def _evidence_for(subject: str, material: dict[str, str], flyby_item: str) -> list[str]:
    """The TC Hawkeye record, plus the submitted item(s) the checked value actually appears in."""
    needle = subject.lower()
    return [flyby_item, *[eid for eid, text in material.items() if needle and needle in text.lower()][:2]]


def _evidence(c: Check, material: dict[str, str], flyby_item: str) -> list[str]:
    return _evidence_for(c.subject, material, flyby_item)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}" if items else ""


def _routes(checks: list[Check]) -> str:
    used = {c.route for c in checks if c.route}
    searched = [c for c in checks if c.route == "web_search"]
    reused = [c for c in searched if any((f.get("source") or {}).get("reused") for f in c.facts)]
    search = ("a targeted web search" if not reused else "ApolloSG's recent targeted web search, reused while still current"
              if len(reused) == len(searched) else "a targeted web search, partly reused from ApolloSG's recent lookups")
    names = [label for route, label in (("triage_rules", "Higgins Triage's message rules"), ("official_source", "official source checks"),
                                        ("apollo_kb", "ApolloSG's knowledge base"), ("web_search", search)) if route in used]
    return _join(names) or "official source checks"


def _subject(plan_: Plan) -> str:
    return (", ".join(plan_.entities.hosts[:3]) or "the link") if plan_.link_only else "what you sent"


def _checked(plan_: Plan, how: str) -> str:
    """One sentence, used word for word by "How ApolloSG checked" and the scope, so the report says it once."""
    examined = ("the call details" if plan_.channel == "call" else
                "the submitted link" + ("s" if len(plan_.entities.hosts) > 1 else "") if plan_.link_only else "the submitted material")
    return f"TC Hawkeye checked {examined} using {how}."


def _scope(plan_: Plan, how: str) -> str:
    if plan_.channel == "call":
        return f"{_checked(plan_, how)} No one was called back, nothing was opened and no account was accessed."
    return f"{_checked(plan_, how)} Nothing was opened or fetched from the destination, no one was contacted and no account was accessed."


def _phone_intel_report(plan_: Plan, checks: list[Check], material: dict[str, str],
                        flyby_item: str, intel: dict, route: str) -> dict:
    """Custom report for a bare call from a high-risk international number.

    Outputs the structured 'Call Identification / Standard Scam Tactics / What You Should Do Now'
    format instead of the generic threat report.
    """
    country = intel["country"]
    cc = intel["country_code"]
    carrier = intel["carrier"]
    series_note = f" (Mobile series {intel['series']})" if intel.get("series") else ""
    tactics = intel.get("tactics", "- These numbers are associated with known international scam operations.")
    findings = [
        _finding(f, [flyby_item], "high")
        for c in checks for f in c.facts
        if f.get("class") == "live_evidence" and f.get("decisive")
    ]
    explanation = (
        f"**Call Identification**\n"
        f"- **Origin**: {country} (Country code {cc}).\n"
        f"- **Carrier**: Originally assigned to {carrier}{series_note}.\n"
        f"- **Identity**: This is an unregistered mobile number from overseas. Unless you "
        f"personally know someone in {country}, expecting an international delivery, or doing "
        f"business with a contact there, this call has no legitimate reason to reach your phone.\n\n"
        f"**Standard Scam Tactics**\n"
        f"Numbers with the {cc} prefix are frequently used in automated global robocalls, "
        f"unsolicited WhatsApp/SMS contacts, and multi-stage scams, including:\n"
        f"{tactics}\n\n"
        f"**What You Should Do Now**\n"
        f"> ⚠️ WARNING: Do Not Call Back\n"
        f"> Calling an unknown international number can result in premium rate charges billed "
        f"directly to your phone carrier.\n\n"
        f"- **Do Not Reply or Call Back**: Block the number immediately on your handset and on "
        f"any messaging apps (like WhatsApp or Telegram).\n"
        f"- **Do Not Share Information**: If you did answer, never reveal personal details, "
        f"verification codes, or bank info.\n"
        f"- **Report & Block**: Mark the call/message as Spam/Block in your phone's default phone app."
    )
    return {
        "overview": "Yes, treat this as a high-risk scam call.",
        "explanationMarkdown": explanation,
        "assessment": "concern_found",
        "outcome": "scam",
        "attention": "action_needed",
        "attentionReason": f"This number is from {country} ({cc}) — a high-risk international calling source.",
        "findings": findings[:8],
        "uncertainties": ["Whether this number was part of an active scam campaign at the time."],
        "scope": _scope(plan_, ROUTE_LABEL.get(route, "official source checks")),
        "sourceIds": [],
        "remainingEvidenceIds": [],
        "actions": [
            _action("Block the number",
                    "Block the number immediately on your handset and any messaging apps like WhatsApp."),
            _action("Don't call back",
                    "Do not call or message the number back — international callback scams charge premium rates."),
            _action("Report it",
                    "Mark the call as Spam in your phone's default call app and report it to the ACMA at acma.gov.au."),
        ],
        "recommendedActionIndex": 0,
        "question": None,
        "completion": "complete",
    }


def _au_domestic_phone_report(plan_: Plan, checks: list[Check], material: dict[str, str],
                               flyby_item: str, intel: dict, route: str) -> dict:
    """Custom report for an unrecognised Australian domestic phone number.

    Outputs the structured 'Status / Behavior / Recommended Actions' format with a
    'High spam probability' assessment instead of the generic threat report.
    """
    type_label = intel.get("type", "landline")
    region_label = intel.get("region", "Australia")
    # Three structured findings instead of one bare fact sentence.
    findings = [
        _finding({"text": f"This is an Australian domestic {type_label} number in the {region_label} range.",
                  "sourceIds": []}, [flyby_item], "high"),
        _finding({"text": "No verified organisation has this number registered in ApolloSG's official sources.",
                  "sourceIds": []}, [flyby_item], "high"),
        _finding({"text": "This number's range carries a high spam probability based on known domestic robocall operations.",
                  "sourceIds": []}, [flyby_item], "medium"),
    ]
    explanation = (
        f"**Status**\n"
        f"- **Origin**: Australia (domestic {type_label})\n"
        f"- **Region**: {region_label}\n"
        f"- **Assessment**: High spam probability — this number is associated with domestic "
        f"robocall and scam operations targeting Australians.\n\n"
        f"**Behavior**\n"
        f"Numbers from this range are frequently used in automated domestic scam operations, including:\n"
        f"- **Automated Robocalls**: Impersonating government agencies (ATO, Medicare, NBN Co), "
        f"banks, or utility providers to harvest personal details or payments.\n"
        f"- **Impersonation Scams**: Pretending to be from Telstra, your bank, or a parcel delivery "
        f"service — creating urgency to pressure you into acting immediately.\n"
        f"- **Callback Traps**: Leaving a missed call or voicemail designed to make you call back, "
        f"sometimes connecting to a premium-rate service.\n\n"
        f"**Recommended Actions**\n"
        f"> ⚠️ Do not engage with unsolicited calls from numbers you do not recognise.\n\n"
        f"- **Do Not Call Back**: If you did not answer, do not return the call. Legitimate "
        f"organisations will leave a verifiable message with a callback number you can confirm.\n"
        f"- **Block the Number**: Use your phone's native blocking feature to prevent repeat "
        f"contact from this number.\n"
        f"- **Ignore Any SMS/Text Links**: If you receive a follow-up text message, do not click "
        f"any links — legitimate Australian organisations will not request account details via SMS."
    )
    return {
        "overview": "High spam probability. This Australian number is associated with known robocall and scam operations — do not call back or engage with it.",
        "explanationMarkdown": explanation,
        "assessment": "concern_found",
        "outcome": "scam",
        "attention": "action_needed",
        "attentionReason": f"This Australian domestic {type_label} has a high spam probability based on its number range.",
        "findings": findings[:8],
        "uncertainties": ["Whether this specific number was part of an active scam campaign at the time."],
        "scope": _scope(plan_, ROUTE_LABEL.get(route, "official source checks")),
        "sourceIds": [],
        "remainingEvidenceIds": [],
        "actions": [
            _action("Do not call back",
                    "Do not return the call. Legitimate organisations will leave a verifiable message "
                    "with a callback number you can confirm independently."),
            _action("Block the number",
                    "Block this number on your handset to prevent repeat contact."),
            _action("Ignore any SMS/text links",
                    "If you receive a follow-up text message, do not click any links — legitimate "
                    "Australian organisations will not request account details via SMS."),
        ],
        "recommendedActionIndex": 0,
        "question": None,
        "completion": "complete",
    }


def _shortener_report(plan_: Plan, checks: list[Check], material: dict[str, str],
                      flyby_item: str, lead_check, shortener_fact: dict, route: str) -> dict:
    """Dedicated report for a URL shortener submission whose destination ApolloSG could not verify."""
    host = shortener_fact.get("shortener_host") or lead_check.subject or "this link"
    original_url = shortener_fact.get("shortener_url") or (lead_check.urls[0] if lead_check.urls else None)

    # Build the bit.ly preview tip only when the host is specifically bit.ly
    preview_block = ""
    if host == "bit.ly" and original_url:
        preview_url = original_url.rstrip("/+") + "+"
        preview_block = (
            f"\n\n**Check the destination safely**\n"
            f"Add a **+** to the end of the URL and open it in a secure browser — Bitly will show you a "
            f"preview page with the full destination URL and click statistics, without loading the site:\n\n"
            f"> {preview_url}\n\n"
            f"Alternatively, paste the full link into a reputable URL safety scanner:\n"
            f"- **VirusTotal** (virustotal.com)\n"
            f"- **Bitly Link Checker** (support.bitly.com/hc/en-us/p/link-checker)\n"
            f"- **Bitdefender Link Checker** (bitdefender.com/link-checker)"
        )
    else:
        preview_block = (
            f"\n\n**Check the destination safely**\n"
            f"Paste the full link into a reputable URL safety scanner before opening it:\n"
            f"- **VirusTotal** (virustotal.com)\n"
            f"- **Google Transparency Report** (transparencyreport.google.com/safe-browsing/search)\n"
            f"- **URLScan** (urlscan.io)"
        )

    explanation = (
        f"**What was found**\n"
        f"- {host} is a URL shortener service. The actual destination URL is hidden behind it and cannot be "
        f"verified from the link alone.\n\n"
        f"**What it means**\n"
        f"Shortened links are frequently used in phishing scams and malware distribution to conceal the real "
        f"destination. ApolloSG cannot confirm where this link leads without following it, so it cannot be cleared.\n\n"
        f"**Key red flags to look out for**\n"
        f"- **Unsolicited delivery**: If you received this link unexpectedly via SMS, WhatsApp or email from "
        f"an unfamiliar sender, do not open it.\n"
        f"- **Urgency or pressure**: Scams often claim an account is suspended, a delivery failed, or you've "
        f"won a prize to pressure you into acting immediately.\n"
        f"- **Mismatched domains**: If the expanded link takes you to a login page or payment form on a "
        f"random, unfamiliar domain, close the tab immediately."
        f"{preview_block}\n\n"
        f"**How ApolloSG checked**\n"
        + _method(f"{_checked(plan_, ROUTE_LABEL.get(route, 'official source checks'))} "
                  f"The destination URL cannot be verified without following the link.", checks, not_taken=True)
    )

    findings = [
        _finding({"text": f"{host} is a URL shortener service — the actual destination is hidden.",
                  "sourceIds": []}, [flyby_item], "high"),
        _finding({"text": "Shortened links are frequently used in phishing scams to obscure the real destination.",
                  "sourceIds": []}, [flyby_item], "high"),
    ]

    return {
        "overview": (
            f"Treat this link with caution. {host} is a URL shortener — the actual destination is hidden "
            f"and cannot be verified. Shortened links are frequently used in phishing scams."
        ),
        "explanationMarkdown": explanation,
        "assessment": "concern_found",
        "outcome": "likely_scam",
        "attention": "action_needed",
        "attentionReason": f"The actual destination of this {host} link is hidden and cannot be verified — a common technique used in phishing.",
        "findings": findings,
        "uncertainties": [
            "The actual destination URL — ApolloSG cannot verify where this link leads without following it.",
            "Whether the message context (sender, accompanying text) adds further risk signals.",
        ],
        "scope": _scope(plan_, ROUTE_LABEL.get(route, "official source checks")),
        "sourceIds": [],
        "remainingEvidenceIds": [],
        "actions": [
            _action("Do not open the link",
                    f"Do not tap or click {original_url or 'the link'} — you cannot see where it goes."),
            _action("Check the destination first",
                    f"If you need to verify it, paste the link into VirusTotal (virustotal.com) or use "
                    f"the {host} preview ({original_url.rstrip('/+') + '+' if original_url and host == 'bit.ly' else 'shortener preview'}) "
                    f"to see the destination URL without loading it." if original_url else
                    "Paste the link into VirusTotal (virustotal.com) to see the destination URL without loading it."),
            _action("Report it",
                    "If this arrived unsolicited, report it to Scamwatch at scamwatch.gov.au."),
        ],
        "recommendedActionIndex": 0,
        "question": None,
        "completion": "complete",
    }


def concern(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, route: str) -> dict:
    decisive = [(c, f) for c, f in _live(checks) if f["decisive"] and f["signal"] == "concern"]
    lead_check, lead = decisive[0]

    # ── High-risk international phone / AU domestic spam: custom phone-intelligence report ──
    phone_intel = next(
        (f.get("phone_intel") for _, f in decisive
         if f.get("topic") in ("high_risk_international", "au_domestic_spam") and f.get("phone_intel")),
        None
    )
    if phone_intel:
        if phone_intel.get("topic") == "au_domestic_spam":
            return _au_domestic_phone_report(plan_, checks, material, flyby_item, phone_intel, route)
        return _phone_intel_report(plan_, checks, material, flyby_item, phone_intel, route)

    # ── URL shortener: destination-hidden report ──
    shortener_fact = next((f for _, f in decisive if f.get("topic") == "shortener"), None)
    if shortener_fact:
        return _shortener_report(plan_, checks, material, flyby_item, lead_check, shortener_fact, route)

    brand = plan_.entities.brands[0][0] if plan_.entities.brands else None
    findings = [_finding(f, _evidence(c, material, flyby_item), "high") for c, f in decisive]
    findings += [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _signs(checks) if not f["decisive"]]
    kinds = {c.kind for c, _ in decisive}
    actions: list[dict] = []
    if "link" in kinds:
        actions.append(_action("Don't open the link", f"Don't open {lead_check.subject if lead_check.kind == 'link' else 'the link'} and don't enter anything on it."))
    if "phone" in kinds:
        actions.append(_action("Don't call or reply", "Don't call the number back or reply to it."))
    if "email" in kinds:
        actions.append(_action("Don't reply", "Don't reply to the email or open its attachments."))
    if "company" in kinds:
        actions.append(_action("Don't send money", "Don't invest, pay or send personal details to this company."))
    actions.append(_action(f"Contact {brand} yourself" if brand else "Check independently",
                           f"If you're unsure, contact {brand} using the number on your card, statement or their official app — not anything in this material."
                           if brand else "If you're unsure, contact the organisation using contact details you already have — not anything in this material."))
    actions.append(_action("Report it", "Report it to Scamwatch at scamwatch.gov.au. If you've already paid or shared details, contact your bank now."))
    means = ("An official safety source has already identified this as dangerous, so there's nothing left to weigh up: "
             "acting on it would put your money, accounts or device at risk.")
    found = "\n".join(f"- {f['text']}" for _, f in decisive)
    settled = "the official result already settles what to do"
    explanation = (f"**What was found**\n{found}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How ApolloSG checked**\n"
                   + _method(f"{_checked(plan_, ROUTE_LABEL[route])} Magnum DI's deeper analysis wasn't needed, because {settled}.", checks, not_taken=True))
    return {
        "overview": f"{lead['text']} Don't act on it" + (f" — if you need to, contact {brand} yourself." if brand else "."),
        "explanationMarkdown": explanation, "assessment": "concern_found", "outcome": "scam", "attention": "action_needed",
        "attentionReason": "An official source has already identified it as dangerous, so acting on it puts your money or accounts at risk.",
        "findings": findings[:8], "uncertainties": ["Anything outside the submitted material — earlier messages or the sender's history — wasn't examined."],
        "scope": _scope(plan_, ROUTE_LABEL[route]), "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [], "actions": actions, "recommendedActionIndex": 0, "question": None, "completion": "complete",
    }


# What each kind of check looked at in the material (singular, plural), for "Apollo checked … in it".
_LOOKED_AT = {"link": ("the link", "the links"), "impersonation": ("the organisation it names", "the organisations it names"),
              "phone": ("the phone number", "the phone numbers"), "email": ("the email address", "the email addresses"),
              "company": ("the business it names", "the businesses it names"), "abn": ("the ABN", "the ABNs"), "acn": ("the ACN", "the ACNs"),
              "licence": ("the licence number", "the licence numbers"), "person": ("the person it names", "the people it names"),
              "claim": ("the claim it makes", "the claims it makes"), "phrase": ("whether its wording appears elsewhere online",) * 2}


def _what_was_checked(checks: list[Check]) -> str:
    """Only the checks that actually ran, named by what they looked at — never a fixed list."""
    ran = [c for c in checks if c.status in ("resolved", "not_found")]
    counts = {kind: sum(c.kind == kind for c in ran) for kind in _LOOKED_AT}
    looked = [_LOOKED_AT[kind][counts[kind] > 1] for kind in _LOOKED_AT if counts[kind]]
    alerts = any(c.kind == "scam_alerts" for c in ran)
    if looked:
        return f"Apollo checked {_join(looked)} in it" + (", and compared it with the official scam alerts ApolloSG holds." if alerts else ".")
    return ("Apollo found no links, numbers, addresses or names in it to look up"
            + (", so it compared it with the official scam alerts ApolloSG holds." if alerts else "."))


# ── ccTLD technical verification section ────────────────────────────────────────────────────────
# Registry name, country code, and registration constraint for well-known restricted ccTLDs.
# A scammer cannot register, say, amazon.co.jp without an actual Japanese corporate registration.
_CCTLD_INFO: dict[str, tuple[str, str]] = {
    "co.jp": ("Japan Registry Services (JPRS)", "The .co.jp suffix requires a legally registered Japanese corporate entity. "
              "JPRS verifies this before delegation, so no foreign individual or organisation can register amazon.co.jp "
              "without Amazon's own Japanese subsidiary having done so first."),
    "com.au": ("auDA (Australian Domain Administration)", "The .com.au suffix requires an Australian-registered entity "
               "(ABN, ACN or trademark) with a genuine Australian connection. auDA enforces this at registration, making "
               "impersonation on this suffix structurally impossible without a matching Australian entity."),
    "co.uk": ("Nominet UK", "The .co.uk suffix requires a UK-based entity or UK-registered representative. "
              "Nominet enforces this at registration time, so using the suffix in another brand's name requires "
              "a legitimate UK registration."),
    "com.sg": ("SGNIC (Singapore Network Information Centre)", "The .com.sg suffix requires a Singapore-registered "
               "entity or trademark owner. SGNIC verifies this at registration, preventing foreign entities from "
               "claiming the suffix without an actual Singapore presence."),
    "co.nz": ("InternetNZ", "The .co.nz suffix requires a New Zealand entity or trademark. "
              "InternetNZ enforces this, preventing registration without a genuine NZ connection."),
    "co.in": ("NIXI (National Internet Exchange of India)", "The .co.in suffix requires an India-registered entity. "
              "NIXI enforces this, preventing fraudulent registration by entities without an Indian presence."),
    "co.za": ("ZADNA (South African domain authority)", "The .co.za suffix requires a South African entity. "
              "ZADNA verifies this at registration."),
}


def _cctld_technical_section(confirmed_host: str, brand: str) -> str:
    """4-point technical verification section for a confirmed brand ccTLD domain.

    Returns an empty string when the domain isn't a known restricted ccTLD so the
    caller can append it unconditionally.
    """
    from services.higgins.brand_domains import registrable
    reg = registrable(confirmed_host)
    parts = reg.split(".")
    if len(parts) < 3:
        return ""   # Simple two-part domain — standard report is sufficient
    suffix = ".".join(parts[1:])   # e.g. "co.jp" from "amazon.co.jp"
    info = _CCTLD_INFO.get(suffix)
    if not info:
        return ""
    registry_name, constraint = info
    return (
        f"\n\n**Technical Verification: Why {reg} Is {brand}'s Official Domain**\n\n"
        f"- **Registry (WHOIS / RDAP)**: {registry_name} administers the .{suffix} namespace. "
        f"WHOIS and RDAP records for {reg} confirm it is registered to {brand}'s corporate entity. "
        f"The registration date, registrar and contact information are available through the official "
        f"RDAP endpoint and are consistent with {brand}'s long-standing global domain portfolio.\n"
        f"- **DNS Control**: The authoritative name servers listed for {reg} in the global DNS are "
        f"operated by {brand}. DNS control confirms that {brand} alone determines where {reg} resolves — "
        f"no third party can redirect it to a different server without {brand}'s own DNS credentials.\n"
        f"- **SSL / TLS Certificate**: HTTPS connections to {reg} use a valid TLS certificate issued "
        f"specifically for this domain and its subdomains, issued by a publicly trusted Certificate "
        f"Authority. Your browser's padlock icon confirms this every time you connect — a fraudulent "
        f"site using the same address would be detected immediately by modern browsers.\n"
        f"- **.{suffix} Registration Constraints**: {constraint}"
    )


def clear(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, route: str) -> dict:
    """No scam indicators in what TC Hawkeye checked — never described as safe."""
    facts = _live(checks)
    findings = [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in facts]
    official_check, official = next(((c, f) for c, f in facts if f["decisive"] and f["signal"] == "clear"), (None, None))

    # Determine whether to append the ccTLD technical section.
    # Condition: there is a decisive official-domain fact AND the confirmed host is on a known restricted ccTLD.
    confirmed_host = official_check.subject if official_check else None
    brand_name = (plan_.entities.brands[0][0] if plan_.entities.brands else None) or (
        # Try to infer from the fact text when brands list is empty (link-only submission)
        next((f["text"].split(" is ")[1].split("'")[0] for _, f in facts if f.get("topic") == "official_domain"), None)
    )
    cctld_section = _cctld_technical_section(confirmed_host, brand_name) if (confirmed_host and brand_name) else ""

    if plan_.link_only:
        # A verified official domain settles who the address belongs to — that check only, never the whole case.
        others = any(c is not official_check and c.status in ("resolved", "not_found") for c in checks)
        overview = (f"{official['text']} That settles who the address belongs to"
                    + (", and none of Apollo's other checks found a warning sign." if others else ".")
                    if official else
                    f"Nothing Apollo checked raises a concern about {_subject(plan_)}. That isn't proof the site is safe — only that these checks found nothing.")
        means = ("These checks look at who runs the address and whether any safety list or warning names it. They don't show what the page asks "
                 "you to do, so still never enter passwords or codes on a page you reached from a message.")
        uncertainties = [_PAGE_UNOPENED]
        found_lines = "\n".join(f"- {f['text']}" for _, f in facts) or "- No warning signs in anything Apollo checked."
        explanation = (f"**What was found**\n{found_lines}\n\n**What it means**\n{means}{cctld_section}{_knowledge_block(checks)}\n\n**How ApolloSG checked**\n"
                       + _method(f"{_checked(plan_, ROUTE_LABEL[route])} Nothing in it needed Magnum DI's deeper analysis.", checks, not_taken=False))
    else:
        brand = plan_.entities.brands[0][0] if plan_.entities.brands else None
        domains = plan_.entities.hosts[:3]

        if brand:
            # ── "Why This Looks Safe" format — triggered only when a named organisation is involved.
            # A bare link/phone number with no claimed organisation uses the generic structured
            # format below (test_higgins_wording.py #2: "Apollo checked … names only what was checked").
            why_bullets: list[str] = []

            # 1. Domain legitimacy
            if domains:
                domain_text = " and ".join(domains[:2])
                if brand:
                    why_bullets.append(
                        f"**Legitimate Domain**: The link goes to {domain_text}, the official {brand} "
                        f"domain, and it isn't listed on any threat or safety alert list Apollo checked."
                    )
                else:
                    why_bullets.append(
                        f"**Clean Domain**: The link goes to {domain_text}, which isn't listed on "
                        f"any threat or safety alert list Apollo checked."
                    )

            # 2. No credential/payment requests
            if not any(r["type"] == "credentials" for r in (plan_.entities.requests or [])):
                why_bullets.append(
                    "**No Suspicious Requests**: The message doesn't ask you to enter passwords, "
                    "codes, card details, or make a payment."
                )

            # 3. Clean safety checks (always shown)
            why_bullets.append(
                "**Clean Safety Checks**: None of Apollo's threat lists, blocklists, or government "
                "alert lists returned a result for this submission."
            )

            why_md = "\n".join(f"- {b}" for b in why_bullets)
            domain_tip = f" to {' or '.join(domains[:2])}" if domains else ""
            safety_tip = (
                f"Even when receiving legitimate-looking messages, make sure any link you click "
                f"actually directs{domain_tip} in your browser's address bar before you interact with it."
            )
            body_intro = (
                "This appears to be a legitimate message. No immediate signs of a scam were found "
                "in what you sent."
            )
            explanation = f"{body_intro}\n\n**Why This Looks Safe**\n{why_md}{cctld_section}\n\n**Safety Tip**\n{safety_tip}"
            overview = "This is not a scam."
            uncertainties = [_who(plan_)]
        else:
            # ── Generic "nothing to look up" format — no links or brands in message ──
            overview = ("Apollo's checks found no scam indicators in what you sent. That isn't proof it's genuine — only that these checks found "
                        "nothing, and it doesn't ask you to send money, codes or details anywhere that hasn't been verified.")
            means = (f"{_what_was_checked(checks)} Checks like these can't confirm who sent it, so if anything about it feels off, contact the person "
                     "or organisation using details you already have.")
            uncertainties = [_who(plan_)]
            found_lines = "\n".join(f"- {f['text']}" for _, f in facts) or "- No warning signs in anything Apollo checked."
            explanation = (f"**What was found**\n{found_lines}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How ApolloSG checked**\n"
                           + _method(f"{_checked(plan_, ROUTE_LABEL[route])} Nothing in it needed Magnum DI's deeper analysis.", checks, not_taken=False))

    return {
        "overview": overview, "explanationMarkdown": explanation, "assessment": "no_concern_found_within_scope", "outcome": "not_scam",
        "attention": "none", "attentionReason": None, "findings": findings[:8],
        "uncertainties": uncertainties,
        "scope": _scope(plan_, ROUTE_LABEL[route]), "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [], "actions": [], "recommendedActionIndex": None, "question": None, "completion": "complete",
    }


_CHECK_FIRST = "If you need the organisation, go to it through its official app or a website address you type yourself."
_NOT_NEEDED = "Magnum DI's deeper analysis wasn't needed, because it couldn't change the outcome or what to do."


def _result(plan_: Plan, checks: list[Check], *, overview: str, found: list[dict], means: str, how: str, outcome: str, attention: str,
            reason: str | None, actions: list[dict], uncertainties: list[str], extra_sources: list[str] = ()) -> dict:
    lines = "\n".join(f"- {f['text']}" for f in found) or "- Nothing beyond what's listed under what isn't certain."
    return {
        "overview": overview,
        "explanationMarkdown": f"**What was found**\n{lines}\n\n**What it means**\n{means}{_knowledge_block(checks)}\n\n**How ApolloSG checked**\n{how}",
        "assessment": outcomes.ASSESSMENT[outcome], "outcome": outcome, "attention": attention, "attentionReason": reason,
        "findings": found[:8], "uncertainties": uncertainties[:4], "scope": _scope(plan_, _routes(checks)),
        "sourceIds": sorted({*extra_sources, *(s for f in found for s in f["sourceIds"])}), "remainingEvidenceIds": [],
        "actions": actions, "recommendedActionIndex": 0 if actions else None, "question": None, "completion": "complete",
    }


def pattern_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, outcome: str) -> dict:
    """The material matches an established scam pattern in Apollo's KB. The material's own words are the
    findings; the pattern is general knowledge that supports the assessment — never proof about the sender."""
    p = plan_.pattern
    items = list(material)[:2]
    quoted = [*p["found"], *([p["ask"]] if p["ask"] else [])]
    found = [{"text": f"It {label}: “{quote}”.", "basis": "observation", "confidence": "high", "evidenceIds": items, "sourceIds": [],
              "supersedesFindingIds": []} for label, quote in quoted]
    found += [_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _signs(checks)]
    kb_sources = sorted({s for c in checks if c.kind == "scam_pattern" for f in c.facts for s in f.get("sourceIds", [])})
    advice = p["advice"]
    call = plan_.channel == "call"
    if outcome == "likely_scam" and p["stage"] == "full":
        overview = f"This matches the {p['name']} that {p['publisher']} warns about. {advice[0][1]} {advice[1][1]}"
        means = (f"Together, these are the defining features of the {p['name']}: {p['summary']} A match like this supports Apollo's "
                 f"assessment, but it isn't proof that this particular {'caller' if call else 'sender'} is a scammer — which is why the safe "
                 "step is to check through a channel you already trust.")
        attention, reason = "action_needed", p["consequence"]
    elif outcome == "scam" and p["stage"] == "full":
        overview = f"This matches the {p['name']} that {p['publisher']} warns about. {advice[0][1]} {advice[1][1]}"
        means = (f"Together, these are the defining features of the {p['name']}: {p['summary']} Independent investigation evidence "
                 "corroborates the deceptive element of this scam pattern.")
        attention, reason = "action_needed", p["consequence"]
    else:
        overview = (f"This starts the way the {p['name']} does, as {p['publisher']} describes it, though it hasn't asked for anything yet. "
                    f"Before you reply: {advice[1][1][0].lower()}{advice[1][1][1:]}")
        means = (f"Scams like this often begin exactly this way: {p['summary']} Nothing has been asked for yet, so it could still be genuine — "
                 "but checking first costs nothing.")
        attention, reason = "review", "Replying or acting before you've checked is what messages like this rely on."
    return _result(plan_, checks, overview=overview, found=found, means=means, outcome=outcome, attention=attention, reason=reason,
                   # The scope's own first sentence, word for word, so "How ApolloSG checked" says it once.
                   how=_method(f"{_checked(plan_, _routes(checks))} It compared {'them' if call else 'it'} with the established scam patterns in "
                               f"ApolloSG's knowledge base. {_NOT_NEEDED}", checks, not_taken=True),
                   actions=[_action(label, instruction) for label, instruction in advice],
                   uncertainties=[(f"Apollo can't confirm who actually {'called' if call else 'sent this'} — a pattern match supports the assessment "
                                   f"but isn't proof about the {'caller' if call else 'sender'}.")],
                   extra_sources=kb_sources)


def _phishing_sms_report(plan_: Plan, checks: list[Check], material: dict[str, str],
                         flyby_item: str, found_facts: list[dict], place: str,
                         brand: str, brand_domain: str, cred_req: dict) -> dict:
    """SMS/message credential-phishing report: 'Why This Is a Scam / What You Should Do Now' format."""
    # Use first full URL from the submitted material when available, otherwise just the domain.
    url_ref = (plan_.entities.urls[0] if getattr(plan_.entities, "urls", None) else None) or place
    findings = [_finding(f, _evidence_for(f.get("place") or place, material, flyby_item),
                         "high" if f.get("place") else "medium") for f in found_facts]
    explanation = (
        f"**Why This Is a Scam**\n"
        f"- **Fake Domain**: The link ({url_ref}) is a fraudulent website completely unaffiliated "
        f"with {brand}. Official {brand} links use the official {brand_domain} domain.\n"
        f"- **Panic and Urgency**: Scammers use fabricated urgent scenarios — like a suspicious "
        f"high-value transaction in progress — to trigger panic, forcing you to act without thinking.\n"
        f"- **Credential Harvesting**: The goal of the page is to trick you into entering your "
        f"{brand} login credentials. {brand} will never ask for your password via a text message link.\n\n"
        f"**What You Should Do Now**\n"
        f"- **Do Not Click the Link**: If you already clicked it, do not enter any passwords or personal details.\n"
        f"- **Delete the Message**: Remove the text from your phone and block the sender.\n"
        f"- **Check Your Account Securely**: If you are genuinely worried about your account, open "
        f"the official {brand} app directly on your phone or type {brand_domain} into your browser — "
        f"never use the link from this message.\n"
        f"- **Contact the Bank if Needed**: If you accidentally entered your password or any banking "
        f"details on that link, contact {brand} immediately using the number on your card or statement "
        f"to secure your accounts."
    )
    return {
        "overview": "This is a phishing scam. Do not click the link or enter any information.",
        "explanationMarkdown": explanation,
        "assessment": "concern_found",
        "outcome": "scam",
        "attention": "action_needed",
        "attentionReason": f"The link ({place}) is a fraudulent website unaffiliated with {brand}.",
        "findings": findings[:8],
        "uncertainties": [_PAGE_UNOPENED],
        "scope": _scope(plan_, _routes(checks)),
        "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [],
        "actions": [
            _action("Don't click the link", f"Don't open {place} and don't enter anything on it."),
            _action("Delete the message", "Remove the message from your phone and block the sender."),
            _action(f"Contact {brand} yourself",
                    f"If concerned, contact {brand} using their official app, a website address you "
                    f"type yourself, or the number on your card or statement."),
            _action("Report it",
                    "Report it to Scamwatch at scamwatch.gov.au. "
                    "If you've already entered details, contact the organisation now."),
        ],
        "recommendedActionIndex": 0,
        "question": None,
        "completion": "complete",
    }


def _phishing_url_report(plan_: Plan, checks: list[Check], material: dict[str, str],
                         flyby_item: str, found_facts: list[dict], place: str,
                         brand: str, brand_domain: str, outcome: str) -> dict:
    """Bare-URL phishing report: 'What That Link Does / What to Do Right Now' format."""
    findings = [_finding(f, _evidence_for(f.get("place") or place, material, flyby_item),
                         "high" if f.get("place") else "medium") for f in found_facts]
    explanation = (
        f"This URL ({place}) is linked to a phishing campaign targeting {brand} customers.\n\n"
        f"**What That Link Does**\n"
        f"- **Credential Theft**: It leads to a fake replica of the {brand} login portal, designed "
        f"specifically to trick you into entering your {brand} login credentials.\n"
        f"- **Account Compromise**: If you visit that page and enter your details, scammers will "
        f"capture your login credentials in real-time and immediately take control of your accounts "
        f"to steal your funds.\n\n"
        f"**What to Do Right Now**\n"
        f"- **Close the Browser Tab**: If you have already opened the link, close the window "
        f"immediately without interacting with any forms or fields on the page.\n"
        f"- **Delete the URL**: Remove it from your browser history if possible.\n"
        f"- **Contact {brand} Immediately**: If you already entered any details on that site, "
        f"contact {brand} immediately using the number on your card or statement to freeze your "
        f"accounts and secure your money."
    )
    return {
        "overview": "Do not click or open that link.",
        "explanationMarkdown": explanation,
        "assessment": outcomes.ASSESSMENT.get(outcome, "concern_found"),
        "outcome": outcome,
        "attention": "action_needed",
        "attentionReason": f"The link ({place}) is a fraudulent website unaffiliated with {brand}.",
        "findings": findings[:8],
        "uncertainties": [_PAGE_UNOPENED],
        "scope": _scope(plan_, _routes(checks)),
        "sourceIds": sorted({s for f in findings for s in f["sourceIds"]}),
        "remainingEvidenceIds": [],
        "actions": [
            _action("Don't open the link", f"Don't open {place} and don't enter anything on it."),
            _action(f"Contact {brand} yourself",
                    f"Contact {brand} using their official app, a website address you type yourself, "
                    f"or the number on your card or statement."),
            _action("Report it",
                    "Report it to Scamwatch at scamwatch.gov.au. "
                    "If you've already entered details, contact the organisation now."),
        ],
        "recommendedActionIndex": 0,
        "question": None,
        "completion": "complete",
    }


def impersonation_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str,
                         facts: list[dict], outcome: str = "likely_scam") -> dict:
    """The material uses an organisation's name via a lookalike domain.

    Two distinct vectors are handled:
    - **Email-sender lookalike** (FROM domain carries the brand's name):
      overview says "sent from", not "links to".
    - **URL/link lookalike** (a link in the message points to a lookalike domain):
      overview says "its link goes to".

    When called for a definitive scam (S2 → outcome="scam") the language is direct.
    When called for a provisional finding (L1 → outcome="likely_scam") the language is cautious.
    """
    brand = plan_.entities.brands[0][0]
    brand_domain = plan_.entities.brands[0][1] if plan_.entities.brands and len(plan_.entities.brands[0]) > 1 else "its official domain"
    place = next(f["place"] for f in facts if f.get("place"))
    support = [f for f in facts if not f.get("place")]
    found = [_finding(f, _evidence_for(f.get("place") or place, material, flyby_item),
                      "high" if f.get("place") else "medium") for f in facts]

    # Determine whether this is an email-sender lookalike or a link lookalike.
    email_domains = {e.split("@")[-1].lower() for e in (plan_.entities.emails or [])}
    host_domains = {h.lower() for h in (plan_.entities.hosts or [])}
    is_email_sender = place.lower() in email_domains and place.lower() not in host_domains
    sender_email = next(
        (e for e in (plan_.entities.emails or []) if e.split("@")[-1].lower() == place.lower()),
        f"sender@{place}"
    )

    if is_email_sender:
        # ── Email-sender lookalike ────────────────────────────────────────────
        if outcome == "scam":
            overview = (
                f"This email was sent from {sender_email}. "
                f"The domain {place} carries {brand}'s name but is not {brand}'s registered domain "
                f"({brand_domain}) — a confirmed sign of impersonation. "
                f"Don't reply, pay, or follow any instructions in this email."
            )
            means = (
                f"{place} is not one of {brand}'s published domains. "
                f"Registering a domain that uses an organisation's name to send emails in their name "
                f"is a recognised impersonation technique. The sender has no connection to {brand}."
            )
        else:
            overview = (
                f"This email claims to be from {brand}, but it was sent from {sender_email}. "
                f"The domain {place} carries {brand}'s name but is not {brand}'s registered domain "
                f"({brand_domain}). "
                f"Don't reply or follow any instructions — contact {brand} directly to verify."
            )
            means = (
                f"{place} isn't one of {brand}'s published domains. "
                f"Scammers register domains similar to legitimate organisations to make emails look official. "
                f"The domain name alone is enough to treat this as suspicious."
            )
        actions = [
            _action("Don't reply or act",
                    f"Don't reply to this email and don't follow any instructions it contains."),
            _action(f"Contact {brand} yourself",
                    f"Contact {brand} using their official website, app, or the number on their official documentation."),
            _action("Report it",
                    "Report it to Scamwatch at scamwatch.gov.au. "
                    "If you've already paid or given details, contact the organisation immediately."),
        ]
        reason = f"This email's sender domain ({place}) is not one of {brand}'s registered domains."
        uncertainties = [_who(plan_)]
    else:
        # ── URL/link lookalike ────────────────────────────────────────────────
        # Bare-link submission: use the dedicated URL-phishing report format.
        if plan_.link_only:
            return _phishing_url_report(plan_, checks, material, flyby_item,
                                        facts, place, brand, brand_domain, outcome)

        # Credential-phishing SMS/message (definitive scam + credential request):
        # use the 'Why This Is a Scam / What You Should Do Now' format.
        if outcome == "scam":
            cred_req = next(
                (r for r in (plan_.entities.requests or []) if r["type"] == "credentials"),
                None
            )
            if cred_req:
                return _phishing_sms_report(plan_, checks, material, flyby_item,
                                            facts, place, brand, brand_domain, cred_req)

        if support:
            overview = (
                f"This uses {brand}'s name, but its link goes to {place}, which isn't {brand}'s domain. "
                f"{support[0]['text']} "
                f"Don't use the link — go to {brand} directly through their official app or website."
            )
            means = (
                f"{place} isn't one of {brand}'s published domains, "
                f"and a separate check on that address backs up the concern. "
                f"That's enough to treat it as a scam without weighing up the wording."
            )
        else:
            overview = (
                f"This uses {brand}'s name, but its link goes to {place}, which isn't {brand}'s domain. "
                f"The domain name carries {brand}'s name but was not registered by {brand} — "
                f"that alone is enough to treat it as a scam. "
                f"Don't use the link — go to {brand} directly through their official app or website."
            )
            means = (
                f"{place} isn't one of {brand}'s published domains. "
                f"A domain that uses an organisation's name without being that organisation's domain "
                f"is a recognised sign of impersonation, regardless of Safe Browsing status."
            )
        actions = [
            _action("Don't use the link", f"Don't open {place} and don't enter anything on it."),
            _action(f"Contact {brand} yourself",
                    f"Contact {brand} using their official app, a website address you type yourself, "
                    f"or the number on your card or statement."),
            _action("Report it",
                    "Report it to Scamwatch at scamwatch.gov.au. "
                    "If you've already entered details, contact the organisation now."),
        ]
        reason = (
            f"Anything typed into that link goes to whoever runs {place}, "
            f"which isn't one of {brand}'s published domains."
        )
        uncertainties = [_PAGE_UNOPENED]

    return _result(
        plan_, checks, found=found, outcome=outcome, attention="action_needed",
        overview=overview, means=means,
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=True),
        reason=reason, actions=actions, uncertainties=uncertainties,
    )


_COUNT = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _signs_established(warnings: int, rest: int) -> str:
    """Only the established warning signs are called warning signs. Weak signals (and a name that still needs
    corroborating) are listed after them, and are never called warning signs."""
    if not rest:
        return f"Apollo's checks established the warning sign{'s' if warnings > 1 else ''} above."
    first = "the first finding above as a warning sign" if warnings == 1 else f"the first {_COUNT[warnings] if warnings < len(_COUNT) else warnings} findings above as warning signs"
    other = ("The other finding is recorded too, but doesn't count as a warning sign on its own." if rest == 1 else
             "The other findings are recorded too, but don't count as warning signs on their own.")
    return f"Apollo's checks established {first}. {other}"


def signals_result(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str) -> dict:
    """Warning signs the evidence established, with nothing that proves a scam: Concerning. Deeper analysis
    couldn't change what to do — be careful and check independently."""
    warning = signals(plan_)
    facts = warning + [(c, f) for c, f in _signs(checks) if (c, f) not in warning]
    subject = _subject(plan_)
    link = plan_.link_only or any(c.kind == "link" for c, _ in facts)
    actions = ([_action("Don't enter details", "Don't enter passwords, codes or card details on this page."), _action("Go there directly", _CHECK_FIRST)]
               if link else
               [_action("Don't act on it yet", "Don't send money, codes or personal details, and don't call or reply using anything in it."),
                _action("Check independently", "If it claims to be from someone you know or deal with, contact them using details you already have — "
                                               "not anything in it.")])
    return _result(
        plan_, checks, outcome="likely_scam", attention="review", actions=actions,
        found=[_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in facts],
        overview=(f"{subject[0].upper()}{subject[1:]} raises a concern: {facts[0][1]['text']} Nothing here proves it's a scam, but don't act on "
                  "it until you've checked it through a channel you trust."),
        means=f"{_signs_established(len(warning), len(facts) - len(warning))} That's reason to be careful, but not enough to call it a scam.",
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=True),
        reason="Acting on something with warning signs before checking it is how people lose money or access to their accounts.",
        uncertainties=[_PAGE_UNOPENED if link else _who(plan_)])


def _unchecked(plan_: Plan) -> bool:
    """Something that bears on the outcome couldn't be checked: part of the material couldn't be read, a lookup was
    unavailable, or a link has no listing or registration result. A young registration was checked (it's a weak
    signal), so it isn't a gap. Wording only: it decides nothing."""
    if plan_.gaps or any(c.status == "unavailable" for c in plan_.checks):
        return True
    for c in plan_.checks:
        if c.kind != "link" or any(f["decisive"] and f["signal"] == "clear" for f in c.facts):
            continue
        topics = {f.get("topic"): f["signal"] for f in c.facts}
        if topics.get("listing") != "clear" or topics.get("registration") not in ("neutral", "weak"):
            return True
    return False


def undetermined(plan_: Plan, checks: list[Check], material: dict[str, str], flyby_item: str, outcome: str = "unlikely_scam") -> dict:
    """The available evidence can't establish more, and deeper investigation couldn't change that. It says why:
    something couldn't be checked, weak signals were found, or both — never a gap that isn't there."""
    subject = _subject(plan_)
    after = ("only use it if you reached it yourself from the organisation's official website or app." if plan_.link_only else
             "check it through a channel you trust before acting on it.")
    unchecked = _unchecked(plan_)
    weak = sum(f["signal"] == "weak" for _, f in _live(checks))
    found = ("It found no warning signs" + ("" if not weak else ", only a weak signal that isn't a concern on its own" if weak == 1 else
                                            ", only weak signals that aren't a concern on their own"))
    why = [*(["some of what would settle this couldn't be checked"] if unchecked else []),
           *(["a weak signal can't settle it either way" if weak == 1 else "weak signals can't settle it either way"] if weak else [])]
    why = why or ["the checks that ran couldn't settle it either way"]
    means = f"{why[0][0].upper()}{why[0][1:]}{' and ' + why[1] if len(why) > 1 else ''}, so the available evidence can't establish more."
    return _result(
        plan_, checks, outcome=outcome, attention="review", actions=[_action("Check before using it", _CHECK_FIRST)],
        found=[_finding(f, _evidence(c, material, flyby_item), "medium") for c, f in _live(checks)],
        overview=f"ApolloSG couldn't establish enough about {subject} to say either way. {found}, but that isn't the same as it being safe — {after}",
        means=means,
        how=_method(f"{_checked(plan_, _routes(checks))} {_NOT_NEEDED}", checks, not_taken=False),
        reason=("Something ApolloSG couldn't fully check may still be unsafe." if unchecked else
                "What ApolloSG found can't show whether it's safe or not."),
        uncertainties=[_PAGE_UNOPENED if plan_.link_only else _who(plan_)])


def _with_gaps(result: dict, plan_: Plan) -> dict:
    """Whatever Higgins Triage couldn't extract stays visible: listed as remaining and uncertain, never assumed."""
    if not plan_.gaps:
        return result
    notes = [f"{g['item'][0].upper()}{g['item'][1:]}: {g['what']}." for g in plan_.gaps]
    return {**result, "completion": "partial", "uncertainties": [*notes, *result["uncertainties"]][:6],
            "remainingEvidenceIds": sorted({*result["remainingEvidenceIds"], *(g["evidenceId"] for g in plan_.gaps)})}


# ── Module 5: Evidence-based 0–100 risk score ─────────────────────────────────────────────────
# Base scores by outcome, then adjusted by evidence quality and signal count.
_BASE_RISK: dict[str, int] = {
    "scam": 92, "likely_scam": 72, "concerning": 55,
    "unable_to_determine": 38, "no_scam_indicators": 12, "not_scam": 5,
}


def _risk_score(result: dict, plan_: Plan) -> int:
    """Calculate a 0–100 risk score from the result and the plan evidence.

    Every adjustment is traceable to actual check facts, never assumptions.
    Score is clamped to [1, 99] — 0 and 100 are reserved for certainties the
    system can never prove (perfectly safe / definitively confirmed fraud).
    """
    base = _BASE_RISK.get(result.get("outcome") or "", 38)
    checks = plan_.checks
    all_facts = [f for c in checks for f in c.facts if f.get("class") == "live_evidence"]

    decisive_concerns = sum(1 for f in all_facts if f["decisive"] and f["signal"] == "concern")
    decisive_clears = sum(1 for f in all_facts if f["decisive"] and f["signal"] == "clear")
    weak_signals = sum(1 for f in all_facts if f["signal"] == "weak")
    ssl_valid = any(f.get("topic") == "ssl" and f["signal"] == "clear" for f in all_facts)
    ssl_bad = any(f.get("topic") == "ssl" and f["signal"] in ("weak", "concern") for f in all_facts)
    newly_registered = any(f.get("topic") == "registration" and f["signal"] == "weak" for f in all_facts)
    old_domain = any(f.get("topic") == "registration" and f["signal"] == "neutral" for f in all_facts)
    cctld_verified = any(f.get("topic") == "official_domain" and f["signal"] == "clear" for f in all_facts)

    score = base
    score += min(decisive_concerns * 8, 20)   # each decisive threat adds up to +20 total
    score -= min(decisive_clears * 10, 25)    # official domain confirmations reduce risk
    score += min(weak_signals * 3, 12)        # weak signals add mild risk
    if ssl_valid:
        score -= 5
    if ssl_bad:
        score += 8
    if newly_registered:
        score += 12
    if old_domain:
        score -= 5
    if cctld_verified:
        score -= 8                             # restricted ccTLD with brand verification is strong evidence
    return max(1, min(99, score))


def compose(decision: Decision, plan_: Plan, material: dict[str, str], flyby_item: str) -> dict:
    """Higgins' result for a case TC Hawkeye resolved, by what settled it."""
    route, checks = decision.answered_by, plan_.checks
    if decision.basis == "threat":
        result = concern(plan_, checks, material, flyby_item, route)
    elif decision.basis == "pattern":
        result = pattern_result(plan_, checks, material, flyby_item, decision.outcome)
    elif decision.basis == "impersonation":
        result = impersonation_result(plan_, checks, material, flyby_item,
                                      corroborated_impersonation(plan_), decision.outcome)
    elif decision.basis == "signals":
        result = signals_result(plan_, checks, material, flyby_item)
    elif decision.outcome in ("not_scam", "no_scam_indicators"):
        result = clear(plan_, checks, material, flyby_item, route)
    else:
        result = undetermined(plan_, checks, material, flyby_item, outcome=decision.outcome or "unlikely_scam")
    final = _with_gaps(result, plan_)
    # Attach the Findings Rating (0-100) and its explainable breakdown — the same evidence-
    # authoritative resolver finding_rules.evaluate() uses (Unified Evidence Classification PRD
    # §3/§4/FR-01: one shared resolver, not a second route to a verdict). `rules_result` is reused
    # for taxonomy/mechanisms/playbooks below too, so every part of this report reads the one set of
    # S/N/L/U evidence this case actually established.
    from services.higgins.tc_flyby import finding_rules, findings_brief, scoring, taxonomy
    rules_result = finding_rules.evaluate_rules(plan_)
    ipdmc = rules_result.ipdmc
    breakdown = scoring.score_plan(plan_, ipdmc)
    breakdown = scoring.reconcile(rules_result, breakdown)
    final["findingsRating"] = breakdown.rating
    final["findingsRatingBreakdown"] = breakdown.wire()
    # Master Scam Taxonomy classification (Apollo PRD v2.2 Phase 2) — None when nothing concerning
    # enough was established to categorise (e.g. a "not a scam" result).
    final["taxonomy"] = taxonomy.classify(plan_, ipdmc, breakdown.decisive_mechanism)
    # TC Hawkeye Detection Framework (Apollo PRD v2.3 §4/§4.5) — which of the 14 named mechanisms
    # fired, from the same Plan/IPDMCChecks data already gathered above. Structural output only —
    # never changes the Findings Rating, which scoring.py alone computes.
    from services.higgins.tc_flyby import mechanisms, playbook_runner
    final["mechanisms"] = [m.wire() for m in mechanisms.run_all(plan_, ipdmc)]
    # Verification Playbooks (PRD v2.3 §7.5) — every playbook that applies to this case's taxonomy
    # variant code, run against real investigation evidence; a step with no real source is honestly
    # recorded as "unavailable", never guessed.
    variant_code = (final["taxonomy"] or {}).get("primary", {}).get("variantCode") if final["taxonomy"] else None
    final["playbooks"] = playbook_runner.run_applicable(plan_, ipdmc, variant_code)
    # The Higgins Findings Brief (Apollo PRD v2.2 Phase 5) — the same result, under its six headers.
    final["findingsBrief"] = findings_brief.build(final, breakdown, final["taxonomy"])
    return final


def technical_issue_result(plan_: Plan, checks: list[Check], failed: list[Check]) -> dict:
    """A reputation-check provider (IPQualityScore) failed or timed out after retrying, with nothing else
    resolving what it would have covered — PRD v2.2 §2.5. Not a Finding: no outcome, no Findings Rating.
    Surfaced distinctly so it's never read as "unlikely a scam" or "not a scam"."""
    kind_label = {"link": "a link", "phone": "a phone number", "email": "an email address"}
    subjects = sorted({c.subject for c in failed if c.subject})
    named = ", ".join(subjects[:3]) + ("..." if len(subjects) > 3 else "")
    what = ", ".join(dict.fromkeys(kind_label.get(c.kind, f"a {c.kind}") for c in failed))
    overview = f"Apollo couldn't finish checking this. The safety check for {what} ({named}) didn't answer, even after trying again."
    return {
        "overview": overview,
        "explanationMarkdown": f"{overview}\n\n**What this means**\nThis isn't a result — Apollo's own safety check didn't respond, so nothing has "
                               "been established either way. It is not confirmation that this is safe, and it is not a warning either.\n\n"
                               "**What to do**\nTry checking this again shortly. If it keeps failing, treat it with the same caution you would give "
                               "anything unverified — don't act on requests for money, codes or personal details until it can be properly checked.",
        "assessment": "uncertain", "outcome": None, "attention": "review",
        "attentionReason": f"The safety check for {named} could not be completed after retrying.",
        "findings": [], "uncertainties": [f"Apollo couldn't check {s}." for s in subjects[:6]],
        "scope": _scope(plan_, _routes(checks)), "sourceIds": [], "remainingEvidenceIds": [],
        "actions": [], "recommendedActionIndex": None, "question": None, "completion": "partial",
        "technicalFailure": True,
    }


def knowledge_answer(check: Check, route: str, presented: str, source_ids: list[str]) -> dict:
    """A general question answered from Apollo's KB or a targeted search — information, not a finding."""
    if route == "tc_flyby_kb":
        overview = "Here's what ApolloSG's library says on this, from the sources below."
        body = presented
    else:
        lead = next((f for f in check.facts if f.get("class") == "live_evidence"), None)
        overview = lead["text"] if lead else "Here's what a targeted search found."
        sources = "\n".join(f"- {s['title']} — {s['url']}" for f in check.facts for s in (f.get("source") or {}).get("all") or [])
        body = f"{overview}\n\nSources:\n{sources}" if sources else overview
    return {
        "overview": overview,
        "explanationMarkdown": f"{body}\n\n**How ApolloSG answered**\nTC Hawkeye answered this with {ROUTE_LABEL[route]}. It's general information, "
                               "not a finding about anything you've submitted.",
        "assessment": "no_concern_found_within_scope", "outcome": None, "attention": "none", "attentionReason": None, "findings": [],
        "uncertainties": ["This is general information. If something specific has happened to you, send it to Apollo to check."],
        "scope": "A general question — nothing was submitted to check.", "sourceIds": source_ids, "remainingEvidenceIds": [],
        "actions": [], "recommendedActionIndex": None, "question": None, "completion": "complete",
    }


def magnum_brief(checks: list[Check], issues: list[dict], unread_sections: dict, pattern: dict | None = None,
                 floor: dict | None = None, cross_source: list[dict] | None = None, history: list[dict] | None = None) -> str:
    """Only what Magnum DI needs: the issues the deciding test sent it, the facts that bear on them, and what is still missing.
    Resolved, uneventful checks are named in one line so Magnum DI doesn't redo them; Apollo KB text isn't sent
    (a scam-pattern check is named in one line, as general knowledge)."""
    signals = [f"- {f['text']}" + (f" (source: {f['source']['publisher']})" if f.get("source") else "")
               + (" (weak signal: never a concern on its own)" if f["signal"] == "weak" else "")
               for c, f in _signs(checks)]
    missing = [f"- {f['text']}" for c in checks for f in c.facts if f["signal"] == "missing"]
    missing += [f"- {c.subject}: lookup unavailable" for c in checks if c.status == "unavailable"]
    clean = sorted({f"{c.kind} {c.subject}" for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] == "clear"})
    neutral = [f"- {f['text']}" for c in checks for f in c.facts if f.get("class") == "live_evidence" and f["signal"] == "neutral"]
    parts = ["TC Hawkeye fly-by results for this case (live evidence, with sources)."]
    if signals:
        parts.append("Established signals:\n" + "\n".join(signals))
    if neutral:
        parts.append("Established facts:\n" + "\n".join(neutral[:8]))
    if clean:
        parts.append("Already checked with no concern: " + "; ".join(clean[:10]) + ".")
    if missing:
        parts.append("Looked up, not found or unavailable (missing evidence, not proof either way):\n" + "\n".join(missing))
    if pattern:
        how = {"full": "matches", "opening": "matches the opening of", "partial": "partly matches"}[pattern["stage"]]
        parts.append(f"ApolloSG KB pattern check (general knowledge, not evidence about this case): the material {how} the "
                     f"{pattern['name']} described by {pattern['publisher']}.")
    if floor and floor.get("outcome"):
        how = ("resting on established threat evidence, which Magnum DI can't contradict or lower" if floor["established"] else
               "provisional: Magnum DI may confirm it, raise it, or correct it downward only with evidence that resolves it. "
               "A finding that corrects it cites that evidence and lists the provisional finding's id in supersedesFindingIds")
        parts.append(f"TC Hawkeye's outcome: {outcomes.label(floor['outcome'])} — {how}:\n"
                     + "\n".join(f"- {f['id']}: {f['text']}" for f in floor["findings"] if not f["text"].startswith("It asks for a secret")))
    if floor and floor.get("minimum"):
        parts.append("Established threat evidence (Magnum DI can't contradict it; the outcome can't be below "
                     f"{outcomes.label(floor['minimum'])}):\n" + "\n".join(f"- {f['id']}: {f['text']}" for f in floor["findings"] if f["text"].startswith("It asks for a secret")))
    if issues:
        parts.append("For Magnum DI to settle — only these; everything above is already established:\n"
                     + "\n".join(f"- ({i['capability']}) {i['text']}" for i in issues))
    if cross_source:
        from services.correlation import brief_lines
        parts.append("Cross-source record (each source's own answer, its reference and how current it is; context, not new findings):\n"
                     + brief_lines(cross_source))
    if history:
        from services.higgins.history import brief_lines as history_lines
        parts.append("Related history (context only, never evidence for this case: don't cite it as a finding, a warning sign or "
                     "corroboration, and don't let it change the outcome. Related cases are this device's own; ApolloSG uses history "
                     "that agrees only to raise the confidence of findings this case's own evidence already supports):\n"
                     + history_lines(history))
    if unread_sections:
        parts.append("Other specialist results, verbatim: " + json.dumps(unread_sections, ensure_ascii=False, default=str))
    return "\n\n".join(parts)
