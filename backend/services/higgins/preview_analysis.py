"""Evidence-specific analysis for the PREVIEW simulator only.

The preview simulator replaces the external Gemini call. It must still return a result that is about
THE ACTUAL EVIDENCE — naming the sender, the link, the amount, the request and the pressure found in
the submitted material — otherwise every preview investigation reads as a vague "characteristics that
may warrant caution" statement and tells the person nothing.

This is deterministic, rule-based and quotes only what is present in the evidence. It never claims a
source was contacted, never invents a verdict the text does not support, and marks every finding it
reasons (rather than reads) as an inference. Production uses the real model; analyse() runs only
when the preview simulator is installed. The indicator reader it uses lives in indicators.py, so Apollo
Triage can use it in every environment without production loading this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.higgins.brand_domains import genuine
from services.higgins.indicators import Indicators, read_indicators


@dataclass
class EvidenceBlock:
    """One evidence item as it was sent to the model."""
    evidence_id: str | None
    kind: str
    label: str
    text: str



# ── The simulated investigation result ───────────────────────────────────────

def _finding(text: str, basis: str, confidence: str, evidence_ids: list[str]) -> dict:
    return {"text": text, "basis": basis if (basis != "observation" or evidence_ids) else "inference",
            "confidence": confidence, "evidenceIds": evidence_ids, "sourceIds": [], "supersedesFindingIds": []}


def _action(label: str, instruction: str) -> dict:
    return {"kind": "instruction", "label": label, "instruction": instruction,
            "capabilityId": None, "sourceIds": [], "desiredField": None, "desiredValue": None}


def _article(word: str) -> str:
    """"a" or "an" for the brand name that follows — "an ING", "a CommBank"."""
    return "an" if word[:1].upper() in ("A", "E", "F", "H", "I", "L", "M", "N", "O", "R", "S", "X") else "a"


def _briefing(ind: Indicators, subject: str | None, assessment: str) -> str:
    """Why the findings matter and how they fit together.

    This is the briefing, not a second copy of the result: the findings, uncertainties, scope and
    actions are returned in their own fields and are displayed (and printed) from those fields. So
    nothing here re-lists them — it explains the reasoning that connects them.
    """
    paras: list[str] = []
    if assessment == "concern_found":
        if ind.mismatched:
            official = ind.mismatched[0][1]
            paras.append(
                "Impersonation works by borrowing a name you already trust, so the destination is never questioned. "
                f"Here the name and the destination disagree, and that is what this conclusion rests on: the link "
                f"isn't {official}, {subject or 'the organisation'}'s published domain.")
        if ind.credentials:
            paras.append(
                "Credentials are the point of a request like this. Once they are typed in they can be used straight "
                "away, which is why it matters before anything is entered rather than afterwards.")
        if ind.amounts or ind.payments:
            paras.append(
                "A payment demand carries its own pressure: it is framed so that paying feels cheaper than checking. "
                "Transfers, gift cards and cryptocurrency are chosen precisely because they are hard to reverse.")
        if ind.urgency:
            paras.append(
                "The deadline exists to stop you checking. Taking the time pressure away costs you nothing — a real "
                "debt, fine or account problem will still be there tomorrow.")
    elif assessment == "uncertain":
        paras.append(
            "Nothing in the material settles intent either way. An unattributed link is not proof of a scam, but it is "
            "not a reason to trust it either: who operates it cannot be established from the material alone, so the "
            "sensible position is to treat it as unverified rather than as safe or as dangerous.")
    else:
        paras.append(
            "There is no request, no link and no deadline to weigh up here, so nothing in the material points to a "
            "concern. That is a statement about this material only, not about the sender or the account behind it.")
    return "\n\n".join(paras)


def analyse(blocks: list[EvidenceBlock], question: str = "") -> dict:
    """Build the investigation payload from the evidence that was actually sent."""
    # TC FlyBy's brief restates official domains and lookups; it is Apollo's record, not the person's material.
    blocks = [b for b in blocks if "TC FlyBy" not in (b.label or "")]
    text_blocks = [b for b in blocks if b.text.strip()]
    evidence_ids = [b.evidence_id for b in text_blocks if b.evidence_id]
    all_ids = [b.evidence_id for b in blocks if b.evidence_id]
    combined = "\n".join(b.text for b in text_blocks)
    ind = read_indicators(combined)

    findings: list[dict] = []
    actions: list[dict] = []
    examined: list[str] = []

    for block in blocks:
        words = len(block.text.split())
        examined.append(f"{block.label or block.kind}{f' ({words} words)' if words else ''}")

    # What the evidence says, quoted.
    if ind.mismatched:
        for name, official, host in ind.mismatched[:3]:
            findings.append(_finding(
                f"The content presents itself as {name} but the link goes to {host}, which is not {name}'s domain ({official}).",
                "observation", "high", evidence_ids[:2]))
    elif ind.brands and ind.hosts:
        name, official = ind.brands[0]
        findings.append(_finding(
            f"The link {ind.hosts[0]} matches {name}'s published domain ({official}).",
            "observation", "medium", evidence_ids[:2]))
    elif ind.hosts:
        findings.append(_finding(
            f"The content contains the link {ind.hosts[0]}. Nothing in the material identifies who operates it.",
            "observation", "medium", evidence_ids[:2]))

    if ind.credentials:
        asked = ", ".join(ind.credentials[:3])
        who = ind.brands[0][0] if ind.brands else "A genuine organisation"
        findings.append(_finding(
            f"It asks for {asked}. {who} does not ask for this by text, email or phone.",
            "observation", "high", evidence_ids[:2]))

    if ind.amounts or ind.payments:
        amount = ind.amounts[0] if ind.amounts else None
        payment_word = ind.payments[0] if ind.payments else "a payment"
        findings.append(_finding(
            f"It refers to {payment_word}{f' of {amount}' if amount else ''} and asks you to act on it."
            + (" Gift cards, vouchers and cryptocurrency are not used by legitimate organisations for bills or fines."
               if any(p in ("gift card", "voucher", "itunes", "bitcoin", "crypto", "steam card") for p in ind.payments) else ""),
            "observation", "high" if ind.amounts else "medium", evidence_ids[:2]))

    if ind.urgency:
        findings.append(_finding(
            f"It pressures you to act — the material says \"{ind.urgency[0]}\". Pressure to act fast is a common scam technique.",
            "observation", "medium", evidence_ids[:2]))

    if ind.phones:
        findings.append(_finding(
            f"The number shown is {ind.phones[0]}. A mobile number is not an official contact channel for a bank, government agency or toll operator.",
            "observation", "medium", evidence_ids[:2]))
    if ind.emails:
        domain = ind.emails[0].split("@")[-1]
        brand_match = any(genuine(name, domain) for name, _ in ind.brands)
        findings.append(_finding(
            f"The sender address is {ind.emails[0]}" + ("." if brand_match else f" — the domain {domain} is not an official address for the organisation it claims to be."),
            "observation", "high" if (ind.brands and not brand_match) else "medium", evidence_ids[:2]))

    images = [b for b in blocks if b.kind == "image"]
    if images and not text_blocks:
        findings.append(_finding(
            f"{len(images)} image{'s were' if len(images) > 1 else ' was'} submitted. No readable text accompanied it, so this result rests on the image alone.",
            "observation", "low", all_ids[:2]))

    if not findings:
        findings.append(_finding(
            "Nothing in the submitted material asks for money, credentials or urgent action, and no link was found in it.",
            "observation" if evidence_ids else "inference", "medium", evidence_ids[:2]))

    # Severity follows what was found — never a fixed level.
    serious = bool(ind.mismatched or ind.credentials
                   or (ind.payments and ind.urgency)
                   or any(p in ("gift card", "voucher", "itunes", "bitcoin", "crypto", "steam card") for p in ind.payments))
    watchful = bool(ind.hosts or ind.urgency or ind.payments or ind.phones or ind.emails)

    subject = (ind.brands[0][0] if ind.brands else None)
    host_phrase = ind.mismatched[0][2] if ind.mismatched else (ind.hosts[0] if ind.hosts else None)

    if serious:
        assessment, attention = "concern_found", "action_needed"
        outcome = "likely_scam" if ind.mismatched and (ind.credentials or ind.payments) else "likely_scam"
        # The overview is the conclusion and the one thing to do now. It does not enumerate the
        # evidence — the link, the request and the amount are already stated once, in the findings.
        overview = (
            f"This looks like {_article(subject)} {subject} impersonation attempt." if subject and ind.mismatched
            else "This asks for information a genuine organisation would never request this way." if ind.credentials
            else "This pushes you to pay quickly, which is how scam demands work."
        )
        overview += (f" Don't act on it — check with {subject} yourself using contact details you already have."
                     if subject else
                     " Don't act on it — check with the organisation yourself using contact details you already have.")
        # Why it needs attention: the consequence of acting on it, not a second copy of a finding.
        attention_reason = (
            "Entering those details would give someone else access to the account they belong to." if ind.credentials
            else "Money sent this way is almost never recovered." if (ind.amounts or ind.payments)
            else f"A page built to look like {subject} exists to collect whatever is typed into it." if subject
            else "Acting on this before it has been verified is exactly what the sender is relying on."
        )
        if host_phrase:
            actions.append(_action("Don't open the link", f"Do not open {host_phrase} and do not enter any details on it."))
        if subject:
            actions.append(_action(f"Contact {subject} yourself", f"Contact {subject} using the number on your card, your statement or their official app — not any number or link in this material."))
        else:
            actions.append(_action("Verify independently", "Contact the organisation using contact details you already have, not the ones in this material."))
        if ind.credentials:
            actions.append(_action("Change it if you entered it", f"If you already gave {ind.credentials[0]}, change it now and tell your bank."))
    elif watchful:
        assessment, attention, outcome = "uncertain", "review", "unable_to_determine"
        overview = ("Nothing here proves a scam, but it can't be confirmed as genuine either. "
                    "Treat it as unverified until you've checked with the organisation directly.")
        attention_reason = "Unverified material can still turn out to be a scam, so it is worth confirming before acting on it."
        actions.append(_action("Check before acting", "Confirm this with the organisation using contact details you already have before clicking anything or replying."))
    else:
        assessment, attention, outcome = "no_concern_found_within_scope", "none", "not_scam"
        overview = ("Nothing in this material asks for money, credentials or urgent action, and it contains no link. "
                    "This covers only what was submitted.")
        attention_reason = None

    uncertainties: list[str] = []
    if ind.hosts:
        uncertainties.append(f"Whether {ind.hosts[0]} is currently live or what it serves was not opened or fetched in this investigation.")
    if ind.phones:
        uncertainties.append(f"Whether {ind.phones[0]} belongs to the organisation named cannot be established from this material.")
    if ind.brands:
        uncertainties.append(f"Whether {ind.brands[0][0]} actually sent this can only be settled by contacting them directly.")
    if not uncertainties:
        uncertainties.append("Anything outside the submitted material — earlier messages, the sender's history, the account itself — was not examined.")

    explanation = _briefing(ind, subject, assessment)

    return {
        "overview": overview[:900],
        "explanationMarkdown": explanation,
        "assessment": assessment,
        "outcome": outcome,
        "attention": attention,
        "attentionReason": attention_reason,
        "findings": findings[:8],
        "uncertainties": uncertainties[:4],
        "scope": "Examined: " + ("; ".join(examined[:8]) if examined else "the submitted material")
                 + ". No website was opened, no sender was contacted and no account was accessed.",
        "sourceIds": [],
        "remainingEvidenceIds": [],
        "actions": actions,
        "recommendedActionIndex": 0 if actions else None,
        "question": None,
        "completion": "complete",
    }
