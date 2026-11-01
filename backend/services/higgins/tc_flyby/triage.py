"""Higgins Triage — makes every input investigation-ready and identifies what needs checking.

    Apollo detects and protects. Higgins Triage extracts, structures and identifies what needs checking.
    TC FlyBy does the fly-by investigation. Magnum DI investigates deeply only when doing so could change
    the finding or action. Higgins explains and guides.

Triage does not investigate and never decides whether something is a scam. From the content of every
supported input — submitted text and links, the text the phone read from screenshots and images, the text
layer of documents — it extracts and structures links and domains, phone numbers, email addresses,
organisations, companies and people, ABN/ACN/licence numbers, payment requests and amounts, payment and
account details, claims, requests and instructions (with what each one points at), the message type, and
how the extracted items relate in context. It records what could not be extracted (the reading of the
items themselves happens in tc_flyby/__init__.py), then plans only the checks that are relevant.

It is deterministic and local: no network, no AI, no cost.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.higgins.brand_domains import registrable
from services.higgins.indicators import BRANDS, read_indicators
from services.triage.requests import negated_before

# ── Entity patterns ──────────────────────────────────────────────────────────
ABN_RE = re.compile(r"\bABN[\s:#.]*((?:\d[\s-]?){10}\d)\b", re.I)
ACN_RE = re.compile(r"\bACN[\s:#.]*((?:\d[\s-]?){8}\d)\b", re.I)
LICENCE_RE = re.compile(
    r"\b(AFSL|AFS\s+licen[cs]e|Australian\s+financial\s+services\s+licen[cs]e|ACL|Australian\s+credit\s+licen[cs]e)"
    r"(?:\s*(?:no\.?|number|#))?[\s:#]*(\d{5,7})\b", re.I)
URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.I)
PHONE_RE = re.compile(r"(?<![\w@.+/])(\+?\d[\d\s().-]{6,}\d)(?![\w@])")
DATE_RE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")
NOT_A_PHONE_BEFORE = re.compile(r"(bsb|account|acc\.?|card|ref(erence)?|invoice|order|abn|acn|afsl|licen[cs]e|tracking|po box)[\s:#no.]*$", re.I)
COMPANY_SUFFIX = (r"Pty\.?\s+Ltd\.?|Pty\.?\s+Limited|Limited|Ltd\.?|Inc\.?|LLC|PLC|Group|Holdings|Capital|Investments?|"
                  r"Trading|Markets|Securities|Financial|Finance|Wealth|Partners|Asset\s+Management|Funds?")
COMPANY_RE = re.compile(r"\b((?:[A-Z][\w&'.-]*\s+){0,3}[A-Z][\w&'.-]*)\s+(" + COMPANY_SUFFIX + r")(?![\w])")
LEADING_WORDS = {"the", "our", "your", "at", "from", "with", "dear", "hi", "hello", "this", "join", "contact", "call", "visit",
                 "and", "or", "by", "for", "via", "a", "an", "invest", "trade", "welcome", "to", "i", "we", "you"}
PERSON_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
                       r"|(?i:\bmy name is|\bthis is|\bi am|\bi'm)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)")
CLAIM_RE = re.compile(
    r"guarantee[ds]?\s+(?:\w+\s+){0,2}(?:returns?|profits?|income|interest|payouts?)"
    r"|\b\d{1,3}(?:\.\d+)?\s?%\s*(?:(?:per|a|each|every)\s+)?(?:day|daily|week|weekly|month|monthly|year|annually|p\.a\.|returns?|profit|interest|roi)\b"
    r"|risk[- ]free|no risk|double your (?:money|investment)|can'?t lose|passive income", re.I)
QUOTED_RE = re.compile(r"[“\"]([^”\"]{40,300})[”\"]")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
QUESTION_START = re.compile(r"^(what|how|who|where|when|which|why|can|could|does|do|is|are|should|will|would)\b", re.I)
FACTUAL_START = re.compile(r"^(what|how|who|where|when|which|why|is there|are there|does|do)\b", re.I)
JUDGEMENT = re.compile(r"\b(should i|should we|is it safe|is it legit|legitimate|can i trust|safe to|worth it|a good idea)\b", re.I)
SITUATION = re.compile(
    r"\b(i|i'?ve|i'?m|we|we'?ve|my|me|us|our)\b.*\b(got|received|been sent|was sent|texted|emailed|called|rang|messaged|sent me|"
    r"asked me|told me|contacted|clicked|paid|gave)\b|\bthis (message|text|sms|email|call|link|site|website|number|offer|person|page|app)\b", re.I)
FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "live.com", "aol.com", "proton.me",
             "protonmail.com", "gmx.com", "mail.com", "bigpond.com"}

# ── Payment and account details ──────────────────────────────────────────────
BSB_RE = re.compile(r"\bBSB[\s:#.-]*(\d{3}[\s-]?\d{3})\b", re.I)
ACCOUNT_RE = re.compile(r"\b(?:account|acc|a/c)(?:\s+(?:number|no\.?|#))?[\s:#.]*(\d(?:[\s-]?\d){4,14})\b", re.I)
PAYID_RE = re.compile(r"\bPayID[\s:]*(?:is\s+|to\s+|of\s+)?([\w.+-]+@[\w-]+(?:\.[\w-]+)+|\+?\d(?:[\s-]?\d){7,13})", re.I)
WALLET_RE = re.compile(r"\b(bc1[a-z0-9]{20,60}|0x[a-fA-F0-9]{40}|T[1-9A-HJ-NP-Za-km-z]{33})\b")
# Financial claims that are warning signs in themselves (Scamwatch: "over-the-top promises of big returns").
# An annual rate on its own (a term deposit's 5% p.a.) is not one.
RED_FLAG_CLAIM = re.compile(
    r"guarantee[ds]?\s+(?:\w+\s+){0,2}(?:returns?|profits?|income|interest|payouts?)"
    r"|\b\d{1,3}(?:\.\d+)?\s?%\s*(?:(?:per|a|each|every)\s+)?(?:day|daily|week|weekly|month|monthly)\b"
    r"|risk[- ]free|no risk|double your (?:money|investment)|can'?t lose", re.I)

# ── Requests and instructions ────────────────────────────────────────────────
# Each is a request construction (a verb bound to what it asks for), never a lone keyword. A negated one
# ("we will never ask for your password") is not a request; a negation that belongs to something else ("Do not
# delay, send …") never cancels one (services/triage/requests.negated_before).
REQUESTS: tuple[tuple[str, str], ...] = (
    ("payment", r"(?:\b(?:send|transfer|pay|deposit|wire|lend|loan)\b|\b(?:must|should|needs?\s+to|to)\s+be\s+(?:paid|transferred|deposited)\b|\bpayable\s+to\b)"
                r"[^.?!\n]{0,60}?(?:\$\s?\d|\bmoney\b|\bfunds\b|\bcash\b|\bpayment\b|\bfees?\b"
                r"|\binvoice\b|\bbill\b|\bamount\b|\bbalance\b|\blevy\b|\brent\b|\btoll\b|\bfine\b|\bBSB\b|\baccount\b|\bPayID\b)"),
    ("credentials", r"\b(?:enter|provide|confirm|verify|share|send|give|tell|update|re-?enter|reply\s+with)\b[^.?!\n]{0,40}?\b(?:password|passcode|pin"
                    r"|one[- ]time\s+(?:code|password|passcode)|otp|verification\s+code|security\s+code|code\s+(?:we|you)|card\s+(?:number|details)|cvv"
                    r"|netbank|login\s+details)\b|\b(?:log|sign)\s?(?:in|on)\b[^.?!\n]{0,30}?(?:https?://|\blink\b|\bhere\b|\bbelow\b)"),
    ("personal_details", r"\b(?:enter|provide|confirm|verify|send|give|update|share)\b[^.?!\n]{0,40}?\b(?:date\s+of\s+birth|dob|driver'?s?\s+licen[cs]e"
                         r"|passport|tax\s+file\s+number|tfn|medicare\s+(?:number|card)|bank\s+(?:details|account)|bsb|account\s+number"
                         r"|personal\s+(?:details|information)|identity|id\s+documents?)\b"),
    ("remote_access", r"\b(?:download|install|open|run)\s+(?:the\s+|this\s+|our\s+)?(?:anydesk|teamviewer|ultraviewer|quick\s?support|quick\s+assist|apk"
                      r"|remote\s+(?:access|desktop|support))\b|\b(?:give|allow|grant|let)\s+(?:us|me|our\s+technician)\s+(?:remote\s+)?access\b"
                      r"|\b(?:share|start)\s+(?:your\s+)?screen\b"),
    ("gift_cards_crypto", r"\b(?:buy|purchase|get|send|pay)\b[^.?!\n]{0,40}?\b(?:gift\s?cards?|vouchers?|itunes|google\s+play\s+cards?|steam\s+cards?"
                          r"|bitcoin|crypto(?:currency)?|usdt)\b"),
    ("payment_details_change", r"\b(?:bank|account|payment)\s+(?:details|account)\s+(?:have|has)\s+(?:changed|been\s+updated)\b"
                               r"|\b(?:new|updated|different)\s+(?:bank\s+)?(?:account|bank\s+details|payment\s+details|bsb)\b"
                               r"|\binstead\s+of\s+(?:the|our|your)\s+usual\s+account\b"),
    ("call_back", r"\b(?:call|ring|phone)\s+(?:us|me|our\s+\w+(?:\s+team)?|the\s+\w+\s+team|back)?\s*(?:on|at|now|immediately|urgently|today)\b"),
    ("reply", r"\breply\s+(?:with|y|yes|stop|to\s+this)\b|\b(?:text|message)\s+(?:us|me)\s+back\b"),
    ("open_link", r"\b(?:click|tap|visit|open|follow|go\s+to)\b[^.?!\n]{0,30}?(?:https?://|\blink\b|\bhere\b|\bbelow\b)"),
)
# Requests that move money, access or identity. Acting on one through a route nobody verified is where harm happens.
CONSEQUENTIAL = ("payment", "credentials", "personal_details", "remote_access", "gift_cards_crypto", "payment_details_change")
# When the request's own sentence names no route, the material's routes of the kind it would use.
_TARGET_FALLBACK = {"payment": ("payment",), "payment_details_change": ("payment",), "gift_cards_crypto": ("payment",),
                    "credentials": ("link",), "personal_details": ("link", "email"), "remote_access": ("link",),
                    "call_back": ("phone",), "open_link": ("link",), "reply": ("phone", "email")}

MESSAGE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("investment", ("invest", "investment", "returns", "trading", "crypto", "bitcoin", "forex", "portfolio", "shares", "profit",
                    "dividend", "wealth", "financial advice")),
    ("family_impersonation", ("hi mum", "hi mom", "hi dad", "new number", "lost my phone", "broke my phone")),
    ("tech_support", ("remote access", "anydesk", "teamviewer", "virus", "your computer", "tech support", "microsoft support")),
    ("delivery_toll", ("parcel", "delivery", "package", "toll", "linkt", "redeliver", "tracking number", "shipment")),
    ("government", ("ato", "mygov", "centrelink", "medicare", "tax refund", "tax return", "services australia")),
    ("bank", ("bank", "netbank", "card", "account", "transaction", "payid")),
    ("job", ("job", "recruit", "recruiter", "salary", "work from home", "hiring", "position", "task")),
    ("romance", ("darling", "sweetheart", "my love", "dating", "relationship")),
    ("prize", ("winner", "you won", "you've won", "prize", "lottery", "reward", "congratulations")),
    ("invoice", ("invoice", "bank details", "payment details", "remittance", "overdue")),
)

MAX_LINKS, MAX_PHONES, MAX_EMAILS, MAX_COMPANIES, MAX_CLAIMS = 5, 3, 3, 2, 2


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def abn_valid(abn: str) -> bool:
    """The Australian Business Register's published ABN check-digit algorithm."""
    d = [int(c) for c in digits(abn)]
    if len(d) != 11:
        return False
    d[0] -= 1
    return sum(w * v for w, v in zip((10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19), d)) % 89 == 0


def acn_valid(acn: str) -> bool:
    """ASIC's published ACN check-digit algorithm."""
    d = [int(c) for c in digits(acn)]
    if len(d) != 9:
        return False
    remainder = sum(w * v for w, v in zip((8, 7, 6, 5, 4, 3, 2, 1), d[:8])) % 10
    return (10 - remainder) % 10 == d[8]


@dataclass
class Entities:
    urls: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    brands: list[tuple[str, str]] = field(default_factory=list)   # (organisation named, its official domain)
    companies: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    abns: list[str] = field(default_factory=list)
    acns: list[str] = field(default_factory=list)
    licences: list[tuple[str, str]] = field(default_factory=list)  # (licence type, number)
    claims: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    payments: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    urgency: list[str] = field(default_factory=list)
    payment_details: list[str] = field(default_factory=list)   # BSB / account numbers, PayIDs, crypto wallets
    requests: list[dict] = field(default_factory=list)          # what the material asks the person to do, and what it points at
    relationships: list[dict] = field(default_factory=list)     # how extracted items relate, with their context

    def any_identifier(self) -> bool:
        return bool(self.urls or self.hosts or self.phones or self.emails or self.companies or self.abns or self.acns or self.licences
                    or self.payment_details)

    def wire(self) -> dict:
        return {k: [list(v) if isinstance(v, tuple) else v for v in getattr(self, k)] for k in self.__dataclass_fields__}


def _phones(text: str) -> list[str]:
    found: list[str] = []
    for match in PHONE_RE.finditer(text):
        value = match.group(1).strip(" .-()")
        count = len(digits(value))
        if not 8 <= count <= 15 or DATE_RE.match(value.replace(" ", "")):
            continue
        if NOT_A_PHONE_BEFORE.search(text[max(0, match.start() - 24):match.start()]):
            continue
        found.append(re.sub(r"\s+", " ", value))
    unique: dict[str, str] = {}
    for value in found:
        unique.setdefault(digits(value), value)
    return list(unique.values())


def _companies(text: str) -> list[str]:
    names: list[str] = []
    for match in COMPANY_RE.finditer(text):
        words = match.group(1).split()
        while words and words[0].lower().strip(".,") in LEADING_WORDS:
            words.pop(0)
        if not words:
            continue
        names.append(re.sub(r"\s+", " ", " ".join(words) + " " + match.group(2)).strip())
    return _dedupe(names)


def _claims(text: str) -> list[str]:
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]
    return _dedupe([s for s in sentences if CLAIM_RE.search(s)])


def _brands(text: str) -> list[tuple[str, str]]:
    """Organisations named in the material, matched as whole words ("ING" is not the end of "lodging")."""
    low = text.lower()
    found: list[tuple[str, str]] = []
    for needle, brand in BRANDS.items():
        if brand not in found and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
            found.append(brand)
    return found


def _payment_details(text: str) -> list[str]:
    return _dedupe([f"BSB {m}" for m in BSB_RE.findall(text)] + [f"account {m}" for m in ACCOUNT_RE.findall(text)]
                   + [f"PayID {m}" for m in PAYID_RE.findall(text)] + [f"wallet {m}" for m in WALLET_RE.findall(text)])


def _sentences(text: str) -> list[tuple[int, int, str]]:
    spans, start = [], 0
    for match in SENTENCE_SPLIT.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    return [(a, b, text[a:b].strip()) for a, b in spans if text[a:b].strip()]


def _context(pos: int, sentences: list[tuple[int, int, str]]) -> str:
    """The sentence a match sits in — and the next one when it ends in a colon ("pay to:")."""
    for index, (a, b, sentence) in enumerate(sentences):
        if a <= pos <= b:
            follow = sentences[index + 1][2] if sentence.endswith(":") and index + 1 < len(sentences) else ""
            return f"{sentence} {follow}".strip()
    return ""


def _routes(ent: "Entities") -> list[tuple[str, str]]:
    """Everything in the material a person could be sent to: links, numbers, addresses, payment details."""
    return ([("link", u) for u in ent.urls] + [("link", h) for h in ent.hosts if not any(h in u.lower() for u in ent.urls)]
            + [("phone", p) for p in ent.phones] + [("email", e) for e in ent.emails] + [("payment", d) for d in ent.payment_details])


def _mentions(kind: str, value: str, context: str) -> bool:
    if kind == "phone":
        return digits(value)[-8:] in digits(context)
    if kind == "payment":
        return digits(value) and digits(value) in digits(context) or value.split(" ", 1)[-1].lower() in context.lower()
    return value.lower() in context.lower()


def _requests(text: str, ent: "Entities") -> list[dict]:
    """What the material asks the person to do, each with the routes it points at (one per kind of request)."""
    sentences, routes, out = _sentences(text), _routes(ent), []
    for kind, pattern in REQUESTS:
        for match in re.finditer(pattern, text, re.I):
            if negated_before(text[:match.start()]):
                continue
            context = _context(match.start(), sentences)
            targets = [v for k, v in routes if _mentions(k, v, context)] or [v for k, v in routes if k in _TARGET_FALLBACK.get(kind, ())]
            out.append({"type": kind, "quote": " ".join(match.group(0).split()), "context": context, "targets": _dedupe(targets)})
            break
    return out


def _relationships(text: str, ent: "Entities") -> list[dict]:
    """How extracted items relate where they appear together: an organisation and the link, address or number
    given for it; a company and its ABN/ACN/licence; a person and the company they speak for."""
    found: list[tuple[str, str, str, str]] = []
    for _a, _b, sentence in _sentences(text):
        low, numbers = sentence.lower(), digits(sentence)
        for name, domain in ent.brands:
            needles = [n for n, brand in BRANDS.items() if brand == (name, domain)] + [name.lower()]
            if not any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", low) for n in needles):
                continue
            found += [("organisation_link", name, h, sentence) for h in ent.hosts if h in low]
            found += [("organisation_email", name, e, sentence) for e in ent.emails if e.lower() in low]
            found += [("organisation_phone", name, p, sentence) for p in ent.phones if digits(p)[-8:] in numbers]
        for company in ent.companies:
            if company.lower() not in low:
                continue
            found += [("company_registration", company, n, sentence) for n in ent.abns + ent.acns if n in numbers]
            found += [("company_licence", company, f"{kind} {number}", sentence) for kind, number in ent.licences if number in numbers]
            found += [("person_company", person, company, sentence) for person in ent.people if person.lower() in low]
    unique = list(dict.fromkeys(found))
    return [{"kind": k, "a": a, "b": b, "context": s} for k, a, b, s in unique][:12]


def extract(text: str) -> Entities:
    """Every entity and signal the material itself states. No inference, no lookup."""
    ind = read_indicators(text)
    ent = Entities()
    ent.urls = _dedupe([u.rstrip(".,;") for u in URL_RE.findall(text)])
    url_hosts = {re.sub(r"^https?://", "", u, flags=re.I).split("/")[0].split("?")[0].split(":")[0].lower().removeprefix("www.")
                 for u in ent.urls}
    ent.emails = _dedupe([e.rstrip(".") for e in ind.emails])
    email_domains = {e.split("@")[-1].lower() for e in ent.emails}
    ent.hosts = _dedupe([h for h in ind.hosts if h in url_hosts or h not in email_domains])
    ent.brands = _brands(text)
    ent.abns = _dedupe([digits(m) for m in ABN_RE.findall(text)])
    ent.acns = _dedupe([digits(m) for m in ACN_RE.findall(text)])
    ent.licences = list(dict.fromkeys(("ACL" if "credit" in kind.lower() or kind.upper() == "ACL" else "AFSL", number)
                                      for kind, number in LICENCE_RE.findall(text)))
    masked = ABN_RE.sub(" ", ACN_RE.sub(" ", LICENCE_RE.sub(" ", URL_RE.sub(" ", text))))
    ent.phones = _phones(masked)
    ent.companies = _companies(text)
    ent.people = _dedupe([(a or b).strip() for a, b in PERSON_RE.findall(text)])
    ent.claims = _claims(text)
    ent.phrases = _dedupe([q.strip() for q in QUOTED_RE.findall(text) if 8 <= len(q.split()) <= 40])
    ent.payments, ent.amounts, ent.credentials, ent.urgency = ind.payments, ind.amounts, ind.credentials, ind.urgency
    ent.payment_details = _payment_details(text)
    ent.requests = _requests(text, ent)
    ent.relationships = _relationships(text, ent)
    return ent


def message_type(text: str, ent: Entities) -> str:
    low = text.lower()
    best, score = "unknown", 0
    for kind, terms in MESSAGE_TYPES:
        hits = sum(1 for term in terms if re.search(rf"\b{re.escape(term)}\b", low))
        if kind == "investment" and ent.claims:
            hits += 2
        if hits > score:
            best, score = kind, hits
    return best


def general_question(question: str, material: list[str], ent: Entities) -> bool:
    """A question about the world rather than material to check: nothing submitted beyond the question itself,
    no identifier in it, short, phrased as a question and not describing something that happened to the person."""
    q = " ".join((question or "").split())
    norm = q.lower().strip(" ?.!")
    if not q or any(" ".join(m.split()).lower().strip(" ?.!") not in (norm, "") for m in material):
        return False
    if ent.any_identifier() or ent.amounts or len(q.split()) > 40:
        return False
    if not (q.endswith("?") or QUESTION_START.match(q)):
        return False
    return not SITUATION.search(q)


def factual(question: str) -> bool:
    """Straightforward factual retrieval (who/what/where/how…), not a judgement call about the person's situation."""
    q = (question or "").strip()
    return bool(FACTUAL_START.match(q)) and not JUDGEMENT.search(q)


# ── The check plan ───────────────────────────────────────────────────────────
@dataclass
class Check:
    id: str
    kind: str
    subject: str
    question: str = ""                         # the narrow factual question for TC FlyBy's search, when that stage applies
    statuses: tuple[str, ...] = ()             # the answers that question allows
    status: str = "open"                       # open | resolved | not_found | unavailable | needs_reasoning | not_needed
    route: str | None = None                   # official_source | apollo_kb | web_search | magnum_di
    facts: list[dict] = field(default_factory=list)
    open_issue: str = ""                       # what only Magnum DI can settle
    urls: list[str] = field(default_factory=list)

    def wire(self) -> dict:
        return {"id": self.id, "kind": self.kind, "subject": self.subject, "question": self.question, "statuses": list(self.statuses),
                "status": self.status, "route": self.route, "facts": self.facts, "openIssue": self.open_issue, "urls": self.urls}

    @classmethod
    def from_wire(cls, data: dict) -> "Check":
        return cls(id=data["id"], kind=data["kind"], subject=data["subject"], question=data.get("question", ""),
                   statuses=tuple(data.get("statuses") or ()), status=data.get("status", "open"), route=data.get("route"),
                   facts=data.get("facts") or [], open_issue=data.get("openIssue", ""), urls=data.get("urls") or [])


@dataclass
class Plan:
    entities: Entities
    message_type: str
    checks: list[Check]
    has_message: bool
    link_only: bool
    general: bool
    gaps: list[dict]                           # what Triage couldn't extract: {"evidenceId", "item", "what", "magnum"}
    advisories: list[dict] = field(default_factory=list)   # official advisories TC FlyBy's stage 1 matched
    pattern: dict | None = None                            # the established scam pattern (Apollo KB) the material matches best
    channel: str | None = None                             # "call": a phone call the person describes (a Call Gate check)


WARNING_STATUSES = ("WARNING", "NO_WARNING_FOUND")
CALL_GATE = "call"


def plan(question: str, material: list[str], *, gaps: list[dict] | None = None, gate: str | None = None) -> Plan:
    """Decide which checks are relevant to what came in. Nothing is looked up here. A case opened from a call check is
    a call to assess, never a question for the library."""
    gaps = gaps or []
    text = "\n".join(material)
    ent = extract(text if material else question)
    channel = CALL_GATE if gate == CALL_GATE else None
    general = not channel and general_question(question, material, ent) and not gaps
    urls_only = bool(material) and all(URL_RE.fullmatch(m.strip()) for m in material if m.strip())
    has_message = bool(text.strip()) and not urls_only and not general
    checks: list[Check] = []

    def add(kind: str, subject: str, **kwargs) -> Check:
        check = Check(id=f"c{len(checks) + 1}", kind=kind, subject=subject, **kwargs)
        checks.append(check)
        return check

    if general:
        add("general_question", question.strip(), question=question.strip() if factual(question) else "", statuses=("ANSWER", "NO_RECORD_FOUND"))
        return Plan(ent, "general_question", checks, False, False, True, gaps)

    for host in ent.hosts[:MAX_LINKS]:
        urls = [u for u in ent.urls if host in u.lower()]
        add("link", host, question=f'Is the exact domain "{host}" named in any scam, phishing, fraud or security warning?',
            statuses=WARNING_STATUSES, urls=urls)
    for name, official in ent.brands[:2]:
        add("impersonation", name, urls=[official])
    brand = ent.brands[0][0] if ent.brands else ""
    for phone in ent.phones[:MAX_PHONES]:
        add("phone", phone, question=(f'Is the phone number "{phone}" named in scam warnings or scam reports, or is it a published official '
                                      f'contact number of an organisation{f" such as {brand}" if brand else ""}?'),
            statuses=("WARNING", "OFFICIAL", "NO_RECORD_FOUND"))
    for email in ent.emails[:MAX_EMAILS]:
        add("email", email, question=(f'Is the email address "{email}" named in scam warnings or scam reports, or is it a published official '
                                      f'address of an organisation{f" such as {brand}" if brand else ""}?'),
            statuses=("WARNING", "OFFICIAL", "NO_RECORD_FOUND"))
    for name in ent.companies[:MAX_COMPANIES]:
        add("company", name, question=(f'Is "{name}" a registered business, and is it named on ASIC\'s Investor Alert List or in any regulator '
                                       'or scam warning?'), statuses=("WARNING", "REGISTERED", "NO_RECORD_FOUND"))
    for abn in ent.abns[:2]:
        add("abn", abn, question=f"Which entity is ABN {abn} registered to on the Australian Business Register, and is the ABN active?",
            statuses=("FOUND", "NO_RECORD_FOUND"))
    for acn in ent.acns[:2]:
        add("acn", acn, question=f"Which company has ACN {acn} on ASIC's companies register, and is it currently registered?",
            statuses=("FOUND", "NO_RECORD_FOUND"))
    for kind, number in ent.licences[:2]:
        label = "Australian credit licence" if kind == "ACL" else "Australian financial services licence"
        add("licence", f"{kind} {number}", question=f"Who holds {label} {number} on ASIC's professional register, and is it current?",
            statuses=("FOUND", "NO_RECORD_FOUND"))
    if ent.people and ent.companies:
        person, company = ent.people[0], ent.companies[0]
        add("person", person, question=(f'Is "{person}" publicly associated with "{company}" (for example as a director, representative '
                                        'or adviser)?'), statuses=("CONFIRMED", "NOT_CONFIRMED"))
    for phrase in ent.phrases[:1]:
        add("phrase", phrase, question=(f'Does this exact text appear elsewhere online — copied on other websites, or quoted in scam '
                                        f'warnings: "{phrase}"?'), statuses=("WARNING", "FOUND_ELSEWHERE", "NO_RECORD_FOUND"))
    for claim in ent.claims[:MAX_CLAIMS]:
        add("claim", claim)
    mtype = message_type(text, ent)
    if has_message:
        add("scam_alerts", mtype)
        # Planned, not automatic: it reaches Magnum DI only if the deciding test says its reasoning could change the result.
        add("message_analysis", "the submitted material",
            open_issue="Message and deception analysis of the submitted material (requests, pressure, persuasion, intent).")
    return Plan(ent, "link_only" if urls_only else mtype, checks, has_message, urls_only, False, gaps, channel=channel)
