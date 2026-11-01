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


def _negated(clause: str, match: re.Match) -> bool:
    """A negation before the ask, in the same clause: "never share", "we will never ask you to send"."""
    return bool(_NEGATION.search(clause[: match.start()]))


def read(text: str) -> dict:
    """What the text asks of the reader, clause by clause, with the clause that shows each one."""
    out: dict = {"secret_request": False, "code_request": False, "card_request": False, "payment_detail_update": False,
                 "sign_in_request": False, "code_delivery": False, "security_notice": False, "negated_advice": False, "quotes": {}}

    def mark(kind: str, clause: str) -> None:
        out[kind] = True
        out["quotes"].setdefault(kind, clause[:200])

    for clause in _clauses(text):
        if _DELIVERY.search(clause):
            mark("code_delivery", clause)
        if _NOTICE.search(clause):
            mark("security_notice", clause)
        for kind, pattern in (("secret_request", _SECRET_ASK), ("code_request", _CODE_ASK), ("card_request", _CARD_ASK)):
            m = pattern.search(clause)
            if not m:
                continue
            if _negated(clause, m):
                mark("negated_advice", clause)
            elif kind == "secret_request" and _PASSWORD_CHOICE.search(clause) and not re.search(r"\b(?:current|old|existing)\s+password\b", clause, re.I):
                mark("sign_in_request", clause)          # choosing a new password is done on the site, not disclosed
            elif kind == "code_request" and _DELIVERY.search(clause) and not re.search(rf"\b{_STRONG}\b[^.!?]{{0,25}}\b(?:to (?:us|me)|back)\b", clause, re.I):
                continue                                  # "Use this code …": the code is the reader's to use
            else:
                mark(kind, clause)
        m = _CARD_ENTRY.search(clause)
        if m and not out["card_request"] and not _negated(clause, m):
            mark("payment_detail_update", clause)
        m = _SIGN_IN.search(clause)
        if m and not _negated(clause, m):
            mark("sign_in_request", clause)
    return out


def disclosure(read_result: dict) -> bool:
    """A request to give a password, PIN, login details, a one-time code or card details to someone."""
    return bool(read_result["secret_request"] or read_result["code_request"] or read_result["card_request"])
