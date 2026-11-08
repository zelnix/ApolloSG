"""Apollo's own plain words: the only wording the Plain-English Renderer may add to a validated result.

Everything else it shows is the result's own wording. These lists are fixed: nothing here is generated, and the
Fidelity Check holds the renderer to them.
"""
from __future__ import annotations

import re

# Formal → plain. Swaps that change the words but never what is said, how sure it is or how serious it is.
PLAIN_SWAPS: tuple[tuple[str, str], ...] = (
    ("in order to", "to"), ("prior to", "before"), ("approximately", "about"),
    ("utilised", "used"), ("utilized", "used"), ("utilising", "using"), ("utilizing", "using"),
    ("utilises", "uses"), ("utilizes", "uses"), ("utilise", "use"), ("utilize", "use"),
    ("commenced", "started"), ("commences", "starts"), ("commence", "start"),
    ("insufficient", "not enough"), ("sufficient", "enough"), ("additional", "more"),
    ("obtained", "got"), ("obtain", "get"), ("assistance", "help"), ("regarding", "about"), ("numerous", "many"),
    ("subsequently", "later"), ("furthermore", "also"), ("moreover", "also"), ("additionally", "also"),
    ("nevertheless", "still"), ("nonetheless", "still"),
    ("indicates", "shows"), ("indicated", "showed"), ("indicating", "showing"), ("indicate", "show"),
    ("demonstrates", "shows"), ("demonstrated", "showed"),
    ("attempts to", "tries to"), ("attempted to", "tried to"), ("attempt to", "try to"),
    ("is unable to", "can't"), ("are unable to", "can't"), ("was unable to", "couldn't"), ("were unable to", "couldn't"),
    ("cannot", "can't"), ("can not", "can't"),
    ("do not", "don't"), ("does not", "doesn't"), ("did not", "didn't"), ("is not", "isn't"), ("are not", "aren't"),
    ("was not", "wasn't"), ("were not", "weren't"), ("has not", "hasn't"), ("have not", "haven't"), ("had not", "hadn't"),
    ("could not", "couldn't"), ("would not", "wouldn't"), ("should not", "shouldn't"), ("will not", "won't"),
)
_SWAP_RE = [(re.compile(rf"\b{re.escape(formal)}\b", re.I), plain) for formal, plain in PLAIN_SWAPS]


def swap(text: str) -> str:
    """Apply the plain swaps, keeping a capital first letter where the original had one."""
    for pattern, plain in _SWAP_RE:
        text = pattern.sub(lambda m, p=plain: p[0].upper() + p[1:] if m.group(0)[0].isupper() else p, text)
    return text


# Jargon, explained once per result in Apollo's own fixed words. Explanatory only, never case evidence.
GLOSSARY: tuple[tuple[str, str, str], ...] = (
    ("registration record", r"\b(?:registration record|RDAP|registrar|registered (?:less than|\d+|on|in)|newly registered)\b",
     "A web address's registration record is the public record of when it was set up and who it was registered through."),
    ("domain", r"\bdomains?\b", "A domain is the name part of a web or email address, the part that says who runs it."),
    ("phishing", r"\bphishing\b", "Phishing is a fake message or website made to trick you into handing over passwords, codes or money."),
    ("malware", r"\bmalware\b", "Malware is software made to harm your device or steal from it."),
    ("redirect", r"\bredirect(?:s|ed|ing)?\b", "A redirect sends you on from the address you tapped to a different one."),
    ("Safe Browsing", r"\bSafe Browsing\b", "Google Safe Browsing is Google's list of websites known to be harmful."),
    ("IPQualityScore", r"\b(?:IPQualityScore|IPQS|fraud score)\b",
     "IPQualityScore rates how risky a link or phone number looks. Its score is a likelihood estimate, not proof — many legitimate new websites score high."),
    ("blocklist", r"\bblocklist(?:ed)?\b", "A blocklist is a list of addresses already known to be harmful."),
    ("VoIP", r"\bVoIP\b", "A VoIP number runs over the internet, and anyone can set one up in minutes."),
    ("ABN", r"\bA[BC]N\b", "An ABN or ACN is the public number of a business registered in Australia."),
    ("ASIC", r"\bASIC\b", "ASIC is Australia's company regulator. Its registers list companies and licence holders."),
    ("AFSL", r"\bAFSL\b", "An AFSL is the licence a business needs in Australia to sell investments or give financial advice."),
    ("PayID", r"\bPayID\b", "PayID sends a bank payment to a phone number or email address instead of account details."),
    ("impersonation", r"\bimpersonat\w*", "Impersonation means pretending to be a real person or organisation."),
    ("lookalike", r"\blook-?alike\b", "A lookalike address copies a real organisation's name with small changes."),
    ("one-time code", r"\b(?:one-time|verification|security) codes?\b", "A one-time code is the short code a service sends to prove it's you."),
    ("remote access", r"\bremote(?:-| )access\b", "Remote access lets someone else control your device from somewhere else."),
    ("spoofing", r"\bspoof\w*", "Spoofing makes a call or message look like it comes from someone it doesn't."),
    ("cryptocurrency", r"\bcrypto(?:currency|currencies)?\b", "A cryptocurrency payment is very hard to trace or get back."),
    # Added for Higgins' explanation-quality pass (ApolloSG PRD v2.3 edge cases): terms the glossary had
    # no entry for yet, flagged as unexplained jargon by manual and AI-assisted review of the new BEC and
    # malicious-attachment scenarios.
    ("email authentication", r"\bSPF\b|\bDKIM\b|\bDMARC\b",
     "SPF, DKIM and DMARC are checks that confirm a message really travelled through the domain it claims to be from — they don't confirm who personally wrote it."),
    ("YARA", r"\bYARA\b", "YARA matching compares a file against patterns already known from real malware."),
    ("sandbox", r"\bsandbox(?:ed|ing)?\b", "A sandbox is a safe, isolated test area where a file can be run without risk to a real device."),
    ("PowerShell", r"\bPowerShell\b", "PowerShell is a Windows tool for running commands — a legitimate tool that malware often misuses."),
    ("credential-harvesting pattern", r"\bcredential[- ]harvest\w*\b",
     "A credential-harvesting pattern is a message or page structure built to collect logins or passwords, matched against patterns already on file — not a guess about this specific sender."),
)
GLOSSARY_TEXTS = frozenset(text for _, _, text in GLOSSARY)
_GLOSSARY_RE = [(term, re.compile(pattern, re.I), text) for term, pattern, text in GLOSSARY]


def jargon(text: str, explained: set[str]) -> str:
    """The first unexplained term in `text`, explained; '' when there is none. `explained` is updated."""
    for term, pattern, explanation in _GLOSSARY_RE:
        if term not in explained and pattern.search(text):
            explained.add(term)
            return explanation
    return ""


# How serious it is, in plain words: one fixed line per attention level, never anything else.
SEVERITY = {
    "none": "How serious: nothing Apollo found needs action.",
    "review": "How serious: worth a careful look, but nothing here is proven harmful.",
    "action_needed": "How serious: you need to act. See what you can do.",
    "urgent": "How serious: urgent. Act now.",
}

# Who established a finding, and how firmly. {by} is TC Hawkeye or Magnum DI.
BASIS = {"observation": "Seen directly by {by}", "user_report": "From what you told Apollo",
         "inference": "{by}'s reading of the evidence, not seen directly"}
CONFIDENCE = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence — supporting context only"}


def detail(basis: str, confidence: str, by: str) -> str:
    return f"{BASIS[basis].format(by=by)} · {CONFIDENCE[confidence]}"


# Words the plain English may use no more often than Apollo's own wording does.
CERTAINTY = ("definitely", "certainly", "guaranteed", "proven", "proves", "100%", "without doubt", "no doubt", "for sure", "confirmed", "always")
SAFETY = ("safe", "safely", "genuine", "legitimate", "legit", "trustworthy", "harmless", "nothing to worry", "no need to worry", "don't worry", "fine")
SOFTENERS = ("probably", "just", "only", "minor", "slightly", "a little", "low risk", "unlikely", "maybe")
ESCALATORS = ("urgent", "urgently", "immediately", "dangerous", "emergency", "right now", "critical", "serious", "seriously")

# ── Connecting the material findings into one line of reasoning (ApolloSG PRD v2.3, Higgins explanation
# quality) ───────────────────────────────────────────────────────────────────
# Apollo's own fixed, general knowledge — never a case-specific fact, never an identifier, never a verdict.
# Selected only by the (check, result) pairs facts.classify() already assigns a finding; added to the existing
# "What it means" prose (facts.connecting_knowledge), never as a new field or a caption on an individual finding.
# SIGNIFICANCE: why a single kind of finding matters, used only when nothing more specific (CONNECTIONS) applies.
SIGNIFICANCE: dict[tuple[str, str], str] = {
    ("reputation", "LISTED"): "A listing like this is added only after independent evidence of real harm, so it rarely happens to a genuine address by mistake.",
    ("impersonation", "NOT_OFFICIAL"): "Carrying an organisation's name without being that organisation's own address is a common way messages impersonate a real brand.",
    ("registration", "RECENT"): "An address set up only shortly before it's used is unusual for an established organisation, and common in scam infrastructure that's abandoned quickly.",
    ("email_authentication", "PASS"): "Passing SPF, DKIM and DMARC confirms a message travelled through the claimed domain's own mail system; it doesn't confirm who personally wrote it, or that they authorised what it asks for.",
    ("payment_procedure", "BYPASSED"): "Payment instructions that skip an organisation's normal approval steps are a common way genuine-looking requests get used to redirect money.",
    ("sandbox_behavior", "OBSERVED"): "What a file does when it's run is a direct observation, not a guess; it doesn't by itself establish who controls the address it tried to reach, or what they intended.",
    ("file_disguise", "DISGUISED"): "A file made to look like one kind of document while actually being a program has no legitimate reason to be made that way.",
    ("pattern_match", "MATCHED"): "A pattern match is a direct comparison against known scam structures already on file, not a guess about intent.",
}
# CONNECTIONS: fixed sentences for specific, named combinations of (check, result) pairs that are more telling
# read together than apart. A list, most specific first: the first whose pairs are all present among the
# material findings wins, so a 3-way combination is preferred over a 2-way subset of it. At most one of these
# (or one SIGNIFICANCE sentence, never both) is ever added to a single result.
CONNECTIONS: list[tuple[frozenset[tuple[str, str]], str]] = [
    (frozenset({("impersonation", "NOT_OFFICIAL"), ("registration", "RECENT"), ("pattern_match", "MATCHED")}),
     "Together, these point the same way: an address that only carries the organisation's name, a destination set "
     "up shortly before this message was sent, and a message structure that matches a known credential-"
     "harvesting pattern. On their own, none of these proves intent; together, they fit a page built to collect "
     "logins, not a genuine mistake."),
    (frozenset({("impersonation", "NOT_OFFICIAL"), ("registration", "RECENT")}),
     "Together, an address that only carries the organisation's name and a destination set up shortly before "
     "this message was sent point the same way: this looks built for this message, not a long-standing part of "
     "the organisation."),
    (frozenset({("official_domain", "NOT_OFFICIAL"), ("registration", "RECENT")}),
     "Together, a destination that isn't the organisation's own domain and one only just set up point the same "
     "way: this looks built for this message, not a long-standing part of the organisation."),
    (frozenset({("impersonation", "NOT_OFFICIAL"), ("pattern_match", "MATCHED")}),
     "Together, an address that only carries the organisation's name and a message structure that matches a "
     "known credential-harvesting pattern point the same way: this fits a page built to collect logins, not a "
     "genuine mistake."),
    (frozenset({("file_disguise", "DISGUISED"), ("sandbox_behavior", "OBSERVED")}),
     "Together, a file disguised as a document and a program that then tried to run further commands and reach "
     "outside the device once opened point the same way: the disguise exists to get a harmful program run."),
    (frozenset({("file_disguise", "DISGUISED"), ("malware_signature", "MATCHED")}),
     "Together, a file disguised as a document and known malicious patterns found inside it point the same way: "
     "the disguise exists to get a harmful program run."),
    (frozenset({("email_authentication", "PASS"), ("payment_procedure", "BYPASSED")}),
     "Passing authentication only confirms the message's technical path, so on its own it doesn't resolve the "
     "more telling sign here: payment instructions that skip the organisation's normal approval steps."),
]


def pick_connection(pairs: frozenset) -> str | None:
    """The one fixed sentence (if any) for the most specific known combination of material (check, result) pairs
    present. At most one is ever returned — never stacked, never built from a case's own identifiers."""
    return next((sentence for required, sentence in CONNECTIONS if required <= pairs), None)


# ── The Higgins Case Briefing: Apollo's fixed words for its short forms ─────
# What it is, as the first line of the plain English. {who} is "Stoko " when the organisation is known.
SUBJECT_LINE = "What it is: the {who}{noun} {subject}."
# When the organisation is only named and the subject isn't its ("st0ko-login.co is not Stoko's domain").
SUBJECT_LINE_CLAIMED = "What it is: the {noun} {subject}, which isn't {org}'s."
# The briefing's headline (Home, Threats, notifications): "Stoko email checked".
HEADLINE = {"email": "email", "url": "link", "domain": "website", "phone": "number", "registration": "business number"}
HEADLINE_WITH_ORG = "{org} {noun} checked"
HEADLINE_CLAIMED_ORG = "{noun} using {org}'s name checked"
HEADLINE_NO_ORG = "{noun} checked"
HEADLINE_NO_SUBJECT = "Check finished"
# A finding said in fewer words, only where these fixed words keep its subject, check and result exactly. Any other
# finding is shown in its own (plain) words.
SUMMARY = {
    ("official_contact", "OFFICIAL"): '"{subject}" is a published {org} contact.',
    ("official_contact", "NOT_OFFICIAL"): '"{subject}" is not a published {org} contact.',
    ("reputation", "NOT_LISTED"): 'No scam warning was found for "{subject}".',
}
# What is still open, after the findings in the short summary.
UNRESOLVED_LINE = "Still unresolved: {reason}"
