"""What a message actually asks the reader to do with a secret — read from the source's own sentences, never from
Apollo's observations about it. Mirror: frontend/src/domain/requestSignals.ts (same patterns, same results).

A word such as "password", "verify", "login" or "security code" is never, on its own, a request to disclose a secret.
Each clause is read for what it does:
  code delivery      — gives the reader a code to use ("Your verification code is 123456").
  security notice    — reports an account event ("Your password was changed", "New sign-in to your account").
  negated advice     — tells the reader not to share ("We will never ask for your password", "Never share this code").
  discussion         — mentions the word without asking anything of the reader ("Tips for a strong password").
  disclosure request — asks the reader to give a secret to someone: reply with, send, tell, read out, enter or confirm
                       a password, PIN or login details (secret), a one-time code (code), or card or bank details (card).
  sign-in request    — asks the reader to log in, verify an account or update payment details. Ordinary on its own:
                       it counts only with supporting context the caller establishes (an off-brand destination, a
                       claimed sender that doesn't match, a failed authentication, a Reply-To elsewhere, a threat).
Pure: no I/O.
"""
from __future__ import annotations

import re

_CLAUSE = re.compile(r"(?<=[.!?])\s+|\n+|;\s+|\s+[—–]\s+")
_NEGATION = re.compile(r"\b(?:never|don'?t|do not|doesn'?t|does not|won'?t|will not|wouldn'?t|would not|shouldn'?t|should not|"
                       r"must not|mustn'?t|cannot|can'?t|no one|nobody|not)\b", re.I)

_STRONG = r"(?:send|tell|give|share|reply(?:\s+(?:to us|back))?(?:\s+with)?|respond with|provide|email|text|read(?:\s+(?:it|them))?\s+(?:out|back)|read\s+(?:me|us)|forward|confirm|verify|disclose)"
_ENTRY = r"(?:enter|type|input|submit|fill in|re-?enter|key in)"
_SECRET = r"(?:password|passcode|passphrase|pin(?:\s+number)?|login details|log-?in details|sign-?in details|login credentials|credentials|username and password|security answers?|netbank password)"
_CODE = r"(?:(?:verification|security|one[- ]time|authentication|access|sms|6[- ]digit|six[- ]digit|4[- ]digit|four[- ]digit)\s+(?:code|pin|passcode|number)|otp|2fa code|mfa code|the code|that code|this code|your code)"
_BACK = r"(?:read|send|tell|give|forward|text|reply with)\s+(?:it|that|them)\s+(?:back|out|to (?:me|us))\b"   # "… code, read it back to me"
_CARD = r"(?:card number|card details|credit card|debit card|cvv|cvc|security number on the back|expiry date|bank details|banking details|bsb|account number|bank login|internet banking details)"

_SECRET_ASK = re.compile(rf"\b(?:{_STRONG}|{_ENTRY})\b[^.!?]{{0,40}}?\b(?:your|the|my|our)?\s*{_SECRET}\b", re.I)
_CODE_ASK = re.compile(rf"\b{_STRONG}\b[^.!?]{{0,40}}?\b{_CODE}\b|\b{_CODE}\b[^.!?]{{0,60}}?\b{_BACK}|\bwhat(?:'s| is) the code\b|\bcode (?:that |which )?(?:we|i) (?:just )?sent\b[^.!?]{{0,30}}\b(?:back|to (?:me|us))\b", re.I)
_CARD_ASK = re.compile(rf"\b{_STRONG}\b[^.!?]{{0,40}}?\b(?:your|the)?\s*{_CARD}\b", re.I)
_CARD_ENTRY = re.compile(rf"\b(?:{_ENTRY}|update)\b[^.!?]{{0,30}}?\b(?:your|the)?\s*(?:{_CARD}|payment (?:method|details|information))\b", re.I)
_PASSWORD_CHOICE = re.compile(r"\b(?:new|change|reset|create|choose|set)\b[^.!?]{0,20}\bpassword\b|\bpassword\b[^.!?]{0,15}\b(?:reset|change)\b", re.I)

_DELIVERY = re.compile(r"\b(?:code|otp|passcode|pin)\b[^.!?]{0,25}?(?:\bis\b|:)\s*[A-Z0-9][A-Z0-9 -]{2,10}\b|\b\d{4,8}\b[^.!?]{0,25}\bis your\b[^.!?]{0,30}\b(?:code|otp|pin)\b"
                       r"|\buse (?:the )?(?:code |this code |otp )?\d{4,8}\b|\bhere(?:'s| is) your\b[^.!?]{0,30}\bcode\b|\benter (?:this|the) code\b", re.I)
_NOTICE = re.compile(r"\bpassword (?:was|has been|is) (?:changed|reset|updated)\b|\bnew sign-?in\b|\bnew (?:device|login|log-?in)\b"
                     r"|\b(?:signed|logged) in (?:on|from|to|with) a new\b|\bif (?:this|it) was you\b|\bif you (?:did ?n[o']?t|did not) (?:make|request|do|recogni[sz]e|sign)\b"
                     r"|\bsecurity alert\b|\bunusual (?:sign-?in|activity)\b|\bwe noticed\b|\bwas used to sign in\b", re.I)
_SIGN_IN = re.compile(r"\b(?:log ?in|sign ?in|login)\b\s+(?:to|now|here|below|at|and|with|again|using|within|before|today|immediately)\b|^(?:please\s+)?(?:log ?in|sign ?in)\b|\b(?:log ?in|sign ?in)\s*(?:now|here)?\s*[:>]"
                      r"|\bverify (?:your )?(?:account|identity|email|details|information)\b|\bconfirm (?:your )?(?:account|identity|details|information)\b"
                      r"|\bupdate (?:your )?(?:account|details|information|billing)\b|\breactivate\b|\bunlock your account\b"
                      r"|\brestore (?:your )?(?:account|access)\b|\bsecure your account\b|\b(?:reset|change) your password\b", re.I)


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE.split(text or "") if c and c.strip()]


# What may stand between a negation and the ask it governs: nothing but "ever"/"please"/"under any circumstances"
# ("Never, ever share …"), or an "ask you to" construction ("No one from CommBank will ever ask you to send …",
# "you should never be asked to share …"). Anything else — "Do not delay, send me …", "was not changed, send me …" —
# means the negation belongs to something else, and the ask stands.
_GOVERNS = re.compile(
    r"^(?:\s*,?\s*(?:ever|you|please|again|under any circumstances)\s*,?)*\s*$"
    r"|^(?:\s+[\w'’-]+){0,6}?\s+(?:(?:will|would|should|shall|can|could|may|might|must)\s+)?(?:ever\s+)?(?:be\s+)?"
    r"(?:ask|asks|asked|request|requests|requested|require|requires|required|want|wants|need|needs|expect|expects|expected)"
    r"(?:\s+(?:you|anyone|customers|members|that you|for))?(?:\s+to)?\s*$", re.I)
_WORD_START = re.compile(r"\b\w")


def negated_before(before: str) -> bool:
    """The text just before an ask holds a negation that governs it: the nearest one in the same clause, with only
    what _GOVERNS allows in between. Used by every reader of requests (Higgins Triage on the phone and in a case,
    TC Hawkeye's patterns), so "Do not delay, send me your password" is a request everywhere."""
    clause = _CLAUSE.split(before)[-1] if before else ""
    last = None
    for last in _NEGATION.finditer(clause):
        pass
    return bool(last) and bool(_GOVERNS.match(clause[last.end():]))


def _negated(clause: str, match: re.Match) -> bool:
    """A negation that governs this ask, in its clause."""
    return negated_before(clause[: match.start()])


def ask_in(pattern: re.Pattern, clause: str) -> tuple[re.Match | None, bool]:
    """The first ask in the clause that isn't negated, else (the first negated one, True), else (None, False). Every
    starting point is tried, so a negated ask earlier in the clause never hides a real one after it."""
    negated = None
    for start in _WORD_START.finditer(clause):
        m = pattern.match(clause, start.start())
        if not m:
            continue
        if not _negated(clause, m):
            return m, False
        negated = negated or m
    return negated, negated is not None


def read(text: str) -> dict:
    """What the text asks of the reader, clause by clause, with the clause that shows each one."""
    out: dict = {"secret_request": False, "code_request": False, "card_request": False, "payment_detail_update": False,
                 "sign_in_request": False, "code_delivery": False, "security_notice": False, "negated_advice": False, "quotes": {}}

    def mark(kind: str, clause: str) -> None:
        out[kind] = True
        out["quotes"].setdefault(kind, clause)

    for clause in _clauses(text):
        if _DELIVERY.search(clause):
            mark("code_delivery", clause)
        if _NOTICE.search(clause):
            mark("security_notice", clause)
        for kind, pattern in (("secret_request", _SECRET_ASK), ("code_request", _CODE_ASK), ("card_request", _CARD_ASK)):
            m, negated = ask_in(pattern, clause)
            if not m:
                continue
            if negated:
                mark("negated_advice", clause)
            elif kind == "secret_request" and _PASSWORD_CHOICE.search(clause) and not re.search(r"\b(?:current|old|existing)\s+password\b", clause, re.I):
                mark("sign_in_request", clause)          # choosing a new password is done on the site, not disclosed
            elif kind == "code_request" and _DELIVERY.search(clause) and not re.search(rf"\b{_STRONG}\b[^.!?]{{0,25}}\b(?:to (?:us|me)|back)\b", clause, re.I):
                continue                                  # "Use this code …": the code is the reader's to use
            else:
                mark(kind, clause)
        m, negated = ask_in(_CARD_ENTRY, clause)
        if m and not out["card_request"] and not negated:
            mark("payment_detail_update", clause)
        m, negated = ask_in(_SIGN_IN, clause)
        if m and not negated:
            mark("sign_in_request", clause)
    return out


def disclosure(read_result: dict) -> bool:
    """A request to give a password, PIN, login details, a one-time code or card details to someone."""
    return bool(read_result["secret_request"] or read_result["code_request"] or read_result["card_request"])
