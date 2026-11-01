// What a message actually asks the reader to do with a secret — read from what each clause does, never from the words
// it contains. Mirror of backend services/triage/requests.py (same patterns, same results).
//
// "password", "verify", "login" or "security code" on their own are never a request to disclose a secret:
//   code delivery      — gives the reader a code to use ("Your verification code is 123456").
//   security notice    — reports an account event ("Your password was changed", "New sign-in to your account").
//   negated advice     — tells the reader not to share ("We will never ask for your password").
//   discussion         — mentions the word without asking anything ("Tips for a strong password").
//   disclosure request — asks the reader to give a password, PIN or login details (secret), a one-time code (code),
//                        or card or bank details (card) to someone.
//   sign-in request    — asks the reader to log in, verify an account or update payment details: ordinary on its own,
//                        it counts only with supporting context the caller establishes.
// Pure: no I/O.

const CLAUSE = /(?<=[.!?])\s+|\n+|;\s+|\s+[—–]\s+/;
const NEGATION = /\b(?:never|don'?t|do not|doesn'?t|does not|won'?t|will not|wouldn'?t|would not|shouldn'?t|should not|must not|mustn'?t|cannot|can'?t|no one|nobody|not)\b/i;

const STRONG = String.raw`(?:send|tell|give|share|reply(?:\s+(?:to us|back))?(?:\s+with)?|respond with|provide|email|text|read(?:\s+(?:it|them))?\s+(?:out|back)|read\s+(?:me|us)|forward|confirm|verify|disclose)`;
const ENTRY = String.raw`(?:enter|type|input|submit|fill in|re-?enter|key in)`;
const SECRET = String.raw`(?:password|passcode|passphrase|pin(?:\s+number)?|login details|log-?in details|sign-?in details|login credentials|credentials|username and password|security answers?|netbank password)`;
const CODE = String.raw`(?:(?:verification|security|one[- ]time|authentication|access|sms|6[- ]digit|six[- ]digit|4[- ]digit|four[- ]digit)\s+(?:code|pin|passcode|number)|otp|2fa code|mfa code|the code|that code|this code|your code)`;
const BACK = String.raw`(?:read|send|tell|give|forward|text|reply with)\s+(?:it|that|them)\s+(?:back|out|to (?:me|us))\b`; // "… code, read it back to me"
const CARD = String.raw`(?:card number|card details|credit card|debit card|cvv|cvc|security number on the back|expiry date|bank details|banking details|bsb|account number|bank login|internet banking details)`;

const SECRET_ASK = new RegExp(String.raw`\b(?:${STRONG}|${ENTRY})\b[^.!?]{0,40}?\b(?:your|the|my|our)?\s*${SECRET}\b`, "i");
const CODE_ASK = new RegExp(String.raw`\b${STRONG}\b[^.!?]{0,40}?\b${CODE}\b|\b${CODE}\b[^.!?]{0,60}?\b${BACK}|\bwhat(?:'s| is) the code\b|\bcode (?:that |which )?(?:we|i) (?:just )?sent\b[^.!?]{0,30}\b(?:back|to (?:me|us))\b`, "i");
const CARD_ASK = new RegExp(String.raw`\b${STRONG}\b[^.!?]{0,40}?\b(?:your|the)?\s*${CARD}\b`, "i");
const CARD_ENTRY = new RegExp(String.raw`\b(?:${ENTRY}|update)\b[^.!?]{0,30}?\b(?:your|the)?\s*(?:${CARD}|payment (?:method|details|information))\b`, "i");
const PASSWORD_CHOICE = /\b(?:new|change|reset|create|choose|set)\b[^.!?]{0,20}\bpassword\b|\bpassword\b[^.!?]{0,15}\b(?:reset|change)\b/i;
const SENT_BACK = new RegExp(String.raw`\b${STRONG}\b[^.!?]{0,25}\b(?:to (?:us|me)|back)\b`, "i");

const DELIVERY = /\b(?:code|otp|passcode|pin)\b[^.!?]{0,25}?(?:\bis\b|:)\s*[A-Z0-9][A-Z0-9 -]{2,10}\b|\b\d{4,8}\b[^.!?]{0,25}\bis your\b[^.!?]{0,30}\b(?:code|otp|pin)\b|\buse (?:the )?(?:code |this code |otp )?\d{4,8}\b|\bhere(?:'s| is) your\b[^.!?]{0,30}\bcode\b|\benter (?:this|the) code\b/i;
const NOTICE = /\bpassword (?:was|has been|is) (?:changed|reset|updated)\b|\bnew sign-?in\b|\bnew (?:device|login|log-?in)\b|\b(?:signed|logged) in (?:on|from|to|with) a new\b|\bif (?:this|it) was you\b|\bif you (?:did ?n[o']?t|did not) (?:make|request|do|recogni[sz]e|sign)\b|\bsecurity alert\b|\bunusual (?:sign-?in|activity)\b|\bwe noticed\b|\bwas used to sign in\b/i;
const SIGN_IN = /\b(?:log ?in|sign ?in|login)\b\s+(?:to|now|here|below|at|and|with|again|using|within|before|today|immediately)\b|^(?:please\s+)?(?:log ?in|sign ?in)\b|\b(?:log ?in|sign ?in)\s*(?:now|here)?\s*[:>]|\bverify (?:your )?(?:account|identity|email|details|information)\b|\bconfirm (?:your )?(?:account|identity|details|information)\b|\bupdate (?:your )?(?:account|details|information|billing)\b|\breactivate\b|\bunlock your account\b|\brestore (?:your )?(?:account|access)\b|\bsecure your account\b|\b(?:reset|change) your password\b/i;

export type RequestKind = "secret_request" | "code_request" | "card_request" | "payment_detail_update" | "sign_in_request"
  | "code_delivery" | "security_notice" | "negated_advice";
export type RequestReading = Record<RequestKind, boolean> & { quotes: Partial<Record<RequestKind, string>> };

export const clauses = (text: string): string[] => (text ?? "").split(CLAUSE).map((c) => (c ?? "").trim()).filter(Boolean);

// What may stand between a negation and the ask it governs: nothing but "ever"/"please"/"under any circumstances"
// ("Never, ever share …"), or an "ask you to" construction ("No one from CommBank will ever ask you to send …",
// "you should never be asked to share …"). Anything else — "Do not delay, send me …", "was not changed, send me …" —
// means the negation belongs to something else, and the ask stands. Mirror of requests.py _GOVERNS.
const GOVERNS = new RegExp(String.raw`^(?:\s*,?\s*(?:ever|you|please|again|under any circumstances)\s*,?)*\s*$`
  + String.raw`|^(?:\s+[\w'’-]+){0,6}?\s+(?:(?:will|would|should|shall|can|could|may|might|must)\s+)?(?:ever\s+)?(?:be\s+)?`
  + String.raw`(?:ask|asks|asked|request|requests|requested|require|requires|required|want|wants|need|needs|expect|expects|expected)`
  + String.raw`(?:\s+(?:you|anyone|customers|members|that you|for))?(?:\s+to)?\s*$`, "i");
const NEGATION_ALL = new RegExp(NEGATION.source, "gi");

/** A negation that governs the ask at `at`: the nearest one before it, with only what GOVERNS allows in between. */
export function negated(clause: string, at: number): boolean {
  const before = clause.slice(0, at);
  const last = [...before.matchAll(NEGATION_ALL)].pop();
  return !!last && GOVERNS.test(before.slice((last.index ?? 0) + last[0].length));
}

/** The first ask in the clause that isn't negated, else the first negated one; every starting point is tried, so a
 *  negated ask earlier in the clause never hides a real one after it. Mirror of requests.py ask_in. */
export function askIn(pattern: RegExp, clause: string): { match: RegExpExecArray | null; negated: boolean } {
  const sticky = new RegExp(pattern.source, pattern.flags.replace(/[gy]/g, "") + "y");
  let negatedHit: RegExpExecArray | null = null;
  for (const start of clause.matchAll(/\b\w/g)) {
    sticky.lastIndex = start.index ?? 0;
    const m = sticky.exec(clause);
    if (!m) continue;
    if (!negated(clause, m.index)) return { match: m, negated: false };
    negatedHit ??= m;
  }
  return { match: negatedHit, negated: !!negatedHit };
}

/** What the text asks of the reader, clause by clause, with the clause that shows each one. */
export function readRequests(text: string): RequestReading {
  const out: RequestReading = { secret_request: false, code_request: false, card_request: false, payment_detail_update: false,
    sign_in_request: false, code_delivery: false, security_notice: false, negated_advice: false, quotes: {} };
  const mark = (kind: RequestKind, clause: string) => { out[kind] = true; out.quotes[kind] ??= clause; };
  for (const clause of clauses(text)) {
    if (DELIVERY.test(clause)) mark("code_delivery", clause);
    if (NOTICE.test(clause)) mark("security_notice", clause);
    for (const [kind, pattern] of [["secret_request", SECRET_ASK], ["code_request", CODE_ASK], ["card_request", CARD_ASK]] as const) {
      const { match: m, negated: isNegated } = askIn(pattern, clause);
      if (!m) continue;
      if (isNegated) mark("negated_advice", clause);
      else if (kind === "secret_request" && PASSWORD_CHOICE.test(clause) && !/\b(?:current|old|existing)\s+password\b/i.test(clause)) mark("sign_in_request", clause);
      else if (kind === "code_request" && DELIVERY.test(clause) && !SENT_BACK.test(clause)) continue;
      else mark(kind, clause);
    }
    const entry = askIn(CARD_ENTRY, clause);
    if (entry.match && !out.card_request && !entry.negated) mark("payment_detail_update", clause);
    const signIn = askIn(SIGN_IN, clause);
    if (signIn.match && !signIn.negated) mark("sign_in_request", clause);
  }
  return out;
}

/** A request to give a password, PIN, login details, a one-time code or card details to someone. */
export function asksToDisclose(r: RequestReading): boolean {
  return r.secret_request || r.code_request || r.card_request;
}
