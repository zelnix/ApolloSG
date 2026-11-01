// Gate 2 — Text & Messaging rule engine. Deterministic local analysis remains the first layer.
// A disclosed item can receive purpose-limited Gemini investigation only after the user taps Check.
// URL reputation and the contextual explanation are layered on afterwards and never override
// a verdict downward from "barking" or upward past what the evidence supports.

import type { ApolloState } from "./types";
import { OFFICIAL_DOMAINS, registrableDomain as brandRegistrableDomain } from "./brand.ts";
import { negated, clauses, readRequests } from "./requestSignals.ts";

export type Scenario = "M01" | "M02" | "M03" | "M04" | "M05" | "M06" | "M07" | "M08" | "M09" | "M10" | "M11" | "M12" | "M13" | "M14" | "M15" | "M16" | "M17" | "M18";

export interface MessageSignals {
  urls: string[];
  /** Who the message says it is from, as the message writes it ("UNIﬁed Energy"), or a known brand's name. */
  claimedBrand: string | null;
  brandKind: "bank" | "courier" | "government" | "toll" | "telco" | "tech" | "marketplace" | "energy" | null;
  /** Characters that look like ordinary letters but aren't (ﬁ, full-width or another alphabet's letters, invisible joiners). */
  lookalikeChars: string[];
  /** The name of the organisation the message claims to be is written with one of those characters. */
  lookalikeName: boolean;
  /** The message's own words asking for a reply ("Reply YES"); a "reply STOP" opt-out is never one. */
  replyRequest: string | null;
  /** The message's own words putting a deadline on an offer ("before rebates drop next week"). */
  timePressure: string | null;
  /** The message's own words claiming a government rebate or subsidy ("Government STCs"). */
  governmentRebate: string | null;
  requestedAction: string | null;
  paymentRequest: boolean;
  smallPayment: boolean;
  codeRequest: boolean;
  urgency: boolean;
  threat: boolean;
  giftCards: boolean;
  crypto: boolean;
  remoteAccess: boolean;
  newNumber: boolean;
  familyClaim: boolean;
  moneyRequest: boolean;
  platformSwitch: boolean;
  guaranteedReturns: boolean;
  jobOffer: boolean;
  advanceFee: boolean;
  fakePayment: boolean;
  extortion: boolean;
  romanceEscalation: boolean;
  identityRequest: boolean;
  loginRequest: boolean;
  callbackNumber: string | null;
  callbackRequest: boolean;
  allegedCharge: boolean;
  deadlineThreat: boolean;
  namedEntities: string[];
  unknownSender: boolean;
}

export interface MessageAnalysis {
  state: ApolloState;
  scenario: Scenario;
  scenarioTitle: string;
  verdict: string;
  why: string[];
  recommendation: string;
  signals: MessageSignals;
  signalLabels: string[];
  /** Verify Sender guidance specific to who the message claims to be. */
  verifySender: string;
}

const URL_RE = /\b((?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>"')\]]*)?)/gi;
const BRANDS: { re: RegExp; name: string; kind: MessageSignals["brandKind"] }[] = [
  { re: /\bcomm(?:onwealth)?\s?bank\b|\bcba\b|\bnetbank\b/i, name: "CommBank", kind: "bank" },
  { re: /\bwestpac\b/i, name: "Westpac", kind: "bank" },
  { re: /\banz\b/i, name: "ANZ", kind: "bank" },
  { re: /\bnab\b|\bnational australia bank\b/i, name: "NAB", kind: "bank" },
  { re: /\bpaypal\b/i, name: "PayPal", kind: "bank" },
  { re: /\bmacquarie\b/i, name: "Macquarie", kind: "bank" },
  { re: /\bbendigo\s?bank\b/i, name: "Bendigo Bank", kind: "bank" },
  { re: /\bing\b|\bsuncorp\b|\bbank\b/i, name: "your bank", kind: "bank" },
  { re: /\bauspost\b|\baustralia post\b|\bstartrack\b/i, name: "Australia Post", kind: "courier" },
  { re: /\bdhl\b|\bfedex\b|\bups\b|\btoll\b(?=.*(parcel|deliver))|\bcourier\b|\bparcel\b|\bpackage\b|\bdelivery\b/i, name: "a delivery company", kind: "courier" },
  { re: /\blinkt\b|\be-?toll\b|\btoll\s?(road|payment|notice|charge)\b|\bcitylink\b|\beastlink\b/i, name: "a toll operator", kind: "toll" },
  { re: /\bato\b|\btax office\b|\bmygov\b|\bcentrelink\b|\bservices australia\b|\bmedicare\b|\bafp\b|\bpolice\b|\bgovernment\b/i, name: "a government agency", kind: "government" },
  { re: /\btelstra\b|\boptus\b|\bvodafone\b|\bnbn\b/i, name: "your telco", kind: "telco" },
  { re: /\bapple\b|\bmicrosoft\b|\bgoogle\b|\bnetflix\b|\bamazon\b/i, name: "a tech company", kind: "tech" },
  { re: /\bmarketplace\b|\bgumtree\b|\bebay\b|\bbuyer\b|\bseller\b|\bitem\b.*\b(sold|listed)\b/i, name: "a marketplace", kind: "marketplace" },
];

const has = (t: string, re: RegExp) => re.test(t);
// Mirror of backend services/triage_engine.py (_CALLBACK_RE, _CHARGE_*): a supplied Australian number — including
// 1800/1300 and 13 numbers written without a leading 0 — and an unexpected charge or payment claim.
const CALLBACK_RE = /(?:\+?61[\s().-]*|\b0)(?:1800|1300|[2-478])(?:[\s().-]*\d){6,8}|\b1[38]00(?:[\s.-]*\d){6}\b|\b13[\s-]?\d{2}[\s-]?\d{2}\b/i;
const CHARGE_STRONG = /\bunauthori[sz]ed charge\b|\bunrecogni[sz]ed (?:charge|transaction)\b|\bsuspicious transaction\b|\bmerchant\s*:|\bamount\s*:|\bfunds (?:are|will be) released\b/;
const CHARGE_CLAIM = /\b(?:been|was|were|being) (?:charged|debited|billed)\b|\b(?:charge|payment|transaction|purchase|debit|withdrawal|order) of (?:aud\s?)?\$\s?\d/;
const CHARGE_DISPUTE = /\bif (?:you|this) (?:did ?n[o']?t|was ?n[o']?t)\b|\bnot you\b|\bdid ?n[o']?t (?:make|authori[sz]e|recogni[sz]e)\b|\bto (?:cancel|dispute|stop|reverse) (?:this|the) (?:charge|payment|transaction|order|purchase)\b/;

// Mirror of backend services/triage_engine.py (_DISGUISE, _INVISIBLE, _OTHER_SCRIPT, organisation_named, …).
// Look-alike characters: typographic ligatures (ﬁ ﬂ ﬀ), full-width and mathematical letters/digits, letters from the
// Greek or Cyrillic alphabet inside a word written in English letters, and invisible joiners inside a word.
const DISGUISE = /[\uFB00-\uFB06\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A\u{1D400}-\u{1D7FF}]/u;
const INVISIBLE = /[\u200B-\u200D\u2060\uFEFF]/u;
const OTHER_SCRIPT = /[\u0370-\u03FF\u0400-\u04FF]/u;
const LATIN = /[A-Za-z]/;

/** Each word that contains a look-alike character, with those characters. */
export function disguisedWords(text: string): { word: string; chars: string[] }[] {
  const out: { word: string; chars: string[] }[] = [];
  for (const word of text.split(/[\s.,;:!?()"“”‘’']+/u)) {
    if (!word) continue;
    const latin = LATIN.test(word);
    const chars = Array.from(new Set(Array.from(word).filter((ch) => DISGUISE.test(ch) || (latin && (INVISIBLE.test(ch) || OTHER_SCRIPT.test(ch))))));
    if (chars.length) out.push({ word, chars });
  }
  return out;
}

// Words that make a name an organisation's rather than a person's.
const ORG_WORD = /\b(?:energy|solar|power|electric(?:al|ity)?|gas|bank|banking|group|australian?|pty|ltd|limited|services?|insurance|telco|telecom|mobile|finance|financial|super|health|support|team|company|corp(?:oration)?|inc|homes?|realty|motors|logistics|express|post|retail|solutions|renewables?|batter(?:y|ies)|installations?|installers?|utilities|water)\b/i;
const NAME_END = /[.,;:!?)]+$/;
/** The run of capitalised words at the start of `rest` (at most four), stopping at punctuation. */
function capitalisedRun(rest: string): { name: string; next: string | null } {
  const tokens = rest.trim().split(/\s+/);
  const name: string[] = [];
  for (const token of tokens) {
    const word = token.replace(NAME_END, "");
    if (!word || !/^\p{Lu}/u.test(word) || name.length === 4) return { name: name.join(" "), next: word.toLowerCase() || null };
    name.push(word);
    if (word !== token) return { name: name.join(" "), next: null };
  }
  return { name: name.join(" "), next: null };
}
/** The organisation a message introduces itself as: "It's UNIﬁed Energy here", "This is Sam from Bright Solar",
 *  "calling from AGL Energy". Only a name with an organisation word counts — never a person's name. */
export function organisationNamed(text: string): string | null {
  const isOrg = (name: string) => !!name && ORG_WORD.test(name.normalize("NFKC"));
  for (const m of text.matchAll(/\b(?:it'?s|it’s|this is|we are|we'?re|we’re)\s+/giu)) {
    const rest = text.slice((m.index ?? 0) + m[0].length);
    const run = capitalisedRun(rest);
    if (run.next && /^(?:here|calling|team|again|with)$/.test(run.next) && isOrg(run.name)) return run.name;
    const from = rest.match(/^\S+\s+from\s+/i);
    if (from) { const org = capitalisedRun(rest.slice(from[0].length)).name; if (isOrg(org)) return org; }
  }
  for (const m of text.matchAll(/\bcalling (?:you )?from\s+/giu)) {
    const org = capitalisedRun(text.slice((m.index ?? 0) + m[0].length)).name;
    if (isOrg(org)) return org;
  }
  return null;
}

// A request to reply (never a "reply STOP" opt-out), a deadline on an offer, and a claimed government rebate.
const REPLY_RE = /\breply\s+(?:with\s+)?["“']?(?:yes|y|ok(?:ay)?|confirm|interested|[1-9])\b["”']?|\breply (?:to (?:confirm|book|claim|secure))\b|\btext (?:back|us back|yes)\b|\brespond (?:with )?yes\b/i;
const OFFER = String.raw`(?:rebates?|prices?|offers?|discounts?|savings?|subsid(?:y|ies)|incentives?|stcs?|deals?|spots?|places?)`;
const PRESSURE_RE = new RegExp([
  String.raw`\bbefore (?:the )?(?:\w+\s+){0,2}${OFFER}\s+(?:drops?|dropping|ends?|expires?|changes?|go(?:es)?|closes?|runs? out|disappears?|reduces?|falls?)\b(?:\s+(?:next|this) (?:week|month|year))?`,
  String.raw`\b${OFFER}\s+(?:are|is)\s+(?:dropping|ending|expiring|closing|running out|going up|changing|reducing|disappearing)\b`,
  String.raw`\bbefore (?:the )?(?:year[- ]end|end of (?:the )?(?:year|month|week|financial year)|eofy)\b`,
  String.raw`\b(?:limited time|limited (?:spots|places)|while (?:stocks?|spots?|places?) last|ends? soon|only \d+ (?:spots|places) left)\b`,
].join("|"), "i");
const REBATE_RE = /\b(?:government|govt|federal|state)(?:[- ](?:funded|backed))?\s+(?:[\w-]+\s+){0,3}?(?:rebates?|grants?|subsid(?:y|ies)|incentives?|stcs?|schemes?|programs?|programmes?|bonus(?:es)?)\b|\bsmall[- ]scale technology certificates?\b|\b(?:solar|battery|batteries|energy|electricity|heat pump|hot water)\s+(?:[\w-]+\s+){0,2}?(?:rebates?|subsid(?:y|ies)|grants?|incentives?)\b|\bcheaper home batteries\b/i;
const STC_RE = /\bstcs?\b(?:\s+(?:savings?|rebates?|discounts?))?/i;
const ENERGY_CONTEXT = /\brebates?\b|\bsolar\b|\bbatter(?:y|ies)\b|\bsavings?\b|\binstall(?:ation)?\b/i;

/** The message's own words for a government rebate claim: an explicit one, or STCs offered as savings or rebates. */
function rebateClaim(text: string): string | null {
  const explicit = text.match(REBATE_RE)?.[0];
  if (explicit) return explicit.trim();
  return ENERGY_CONTEXT.test(text) ? text.match(STC_RE)?.[0]?.trim() ?? null : null;
}

const IDENTITY_ASK = /\b(?:send|provide|confirm|verify|reply with|enter|upload|submit|give|tell)\b[^.!?]{0,40}\b(?:date of birth|medicare (?:number|card)|passport|driver'?s? licen[cs]e|tax file number|tfn)\b/i;
/** Some clause asks this of the reader (a negated one — "never send …" — doesn't). */
function askedIn(text: string, pattern: RegExp): boolean {
  return clauses(text).some((c) => { const m = pattern.exec(c); return !!m && !negated(c, m.index); });
}

export function extractSignals(sender: string, text: string): MessageSignals {
  const t = text.toLowerCase();
  const urls = Array.from(new Set((text.match(URL_RE) ?? []).map((u) => u.replace(/[.,;:!?]+$/, "")).filter((u) => /\.[a-z]{2,}(\/|$)/i.test(u) && !/^\d+(\.\d+)+$/.test(u))));
  // Brand names are matched with look-alike characters read as the letters they imitate ("CommBaｎk" is CommBank);
  // the name itself is kept exactly as the message wrote it.
  const plain = text.normalize("NFKC");
  const introduced = organisationNamed(text);
  const known = BRANDS.find((b) => b.re.test(introduced ? introduced.normalize("NFKC") : plain));
  const brand = introduced && !known ? { name: introduced, kind: (/\b(?:energy|solar|power|electric(?:al|ity)?|gas|renewables?|batter(?:y|ies))\b/i.test(introduced.normalize("NFKC")) ? "energy" : null) as MessageSignals["brandKind"] } : known;
  const disguised = disguisedWords(text);
  const lookalikeName = !!brand && disguised.some(({ word }) => (introduced ? introduced.includes(word) : !!known?.re.test(word.normalize("NFKC"))));
  const replyRequest = text.match(REPLY_RE)?.[0]?.trim() ?? null;
  const timePressure = text.match(PRESSURE_RE)?.[0]?.trim() ?? null;
  const governmentRebate = rebateClaim(text);
  const paymentRequest = has(t, /\bpay(ment)?\b|\bfee\b|\bowe|\boverdue\b|\binvoice\b|\bbill\b|\btransfer\b|\bdeposit\b/);
  const smallPayment = has(t, /\$\s?[0-9]{1,2}(\.\d{2})?\b(?!\d)/) && !has(t, /\$\s?[0-9]{3,}/);
  // What the message asks of the reader, read clause by clause (requestSignals.ts): a code delivered for you to use,
  // a security notice or advice never to share is not a request.
  const asks = readRequests(text);
  const codeRequest = asks.code_request;
  const urgency = !!timePressure || has(t, /\bimmediately\b|\burgent(ly)?\b|\bright now\b|\bwithin \d{1,2} (?:minutes?|hours?|days?)\b|\btoday\b|\bexpires?\b|\bfinal notice\b|\blast chance\b|\bact now\b|\bnow\b/);
  const threat = has(t, /\brestrict(ed)?\b|\bsuspend(ed)?\b|\blocked\b|\bpenalt(y|ies)\b|\bfine\b|\blegal action\b|\barrest\b|\bwarrant\b|\bcancel(led)?\b|\bdebt\b/);
  const giftCards = has(t, /\bgift ?cards?\b|\bitunes\b|\bgoogle play card\b|\bsteam card\b|\bvoucher codes?\b/);
  const crypto = has(t, /\bbitcoin\b|\bbtc\b|\bcrypto\b|\busdt\b|\bethereum\b|\bwallet address\b|\bbinance\b/);
  const remoteAccess = has(t, /\banydesk\b|\bteamviewer\b|\bremote (access|support|desktop)\b|\binstall (this|the|our) (app|software|support)\b|\bdownload (this|the|our) (app|tool|software)\b/);
  const newNumber = has(t, /\bnew (phone|number|mobile)\b|\btemporary number\b|\bthis is my (new|temp)\b|\bsmashed my phone\b|\bbroke(n)? my phone\b|\blost my phone\b|\bold (phone|number)\b/);
  const familyClaim = has(t, /\bhi (mum|mom|dad|nan|nanna|grandma|grandpa|pop)\b|\bit'?s (me|your (son|daughter|grandson|granddaughter))\b|\bmum\b|\bdad\b/);
  const moneyRequest = has(t, /\bcan you (help|send|pay|transfer|lend)\b|\bneed (some |the )?money\b|\bsend (me )?\$?\d|\bpay (a|the|my) bill\b|\btransfer\b|\blend me\b|\burgent(ly)? need\b/);
  const platformSwitch = has(t, /\b(on|via|through|to) (telegram|whatsapp|signal|wechat)\b|\bmessage (our|the) recruiter\b|\bcontact (me|us) on\b/);
  const guaranteedReturns = has(t, /\bguaranteed\b|\b\d{1,3}%\s?(weekly|daily|monthly|returns?|profit)\b|\bpassive income\b|\bdouble your\b|\brisk[- ]free\b|\bselected investors\b/);
  const jobOffer = has(t, /\bjob\b|\brecruit(er|ment)\b|\bwork(ing)? from home\b|\bper day\b|\bper week\b|\bhiring\b|\bposition\b|\bearn \$/);
  const advanceFee = has(t, /\brelease fee\b|\bprocessing fee\b|\bclearance fee\b|\bunlock\b.*\bfee\b/) || (has(t, /\bfee\b/) && has(t, /\bto (access|receive|release) (the |your )?(funds|money|payment)\b/));
  const fakePayment = has(t, /\byou'?ve (been paid|received)\b|\bi'?ve (already )?paid\b|\bpayment (has been )?(sent|made|confirmed)\b|\bawaiting your confirmation\b/);
  const extortion = has(t, /\bhacked\b|\brecorded you\b|\bwebcam\b|\bvideo of you\b|\bsend (it|the video) to (everyone|your contacts|your family)\b|\bexpose\b|\bor i will\b|\bor else\b/);
  const romanceEscalation = has(t, /\b(babe|baby|honey|my love|darling|sweetheart)\b/) && (moneyRequest || crypto || giftCards || has(t, /\btravel\b|\bflight\b|\bvisa\b|\bcustoms\b|\bhospital\b|\bemergency\b/));
  const identityRequest = asks.card_request || askedIn(text, IDENTITY_ASK);
  const callbackNumber = text.match(CALLBACK_RE)?.[0] ?? null;
  const callbackRequest = !!callbackNumber && has(t, /\b(call|contact|phone|ring|fraud response|support line|helpline)\b/);
  // An unexpected charge or payment: the explicit forms, or a charge claim with dispute or urgency wording.
  const allegedCharge = has(t, CHARGE_STRONG) || (has(t, CHARGE_CLAIM) && (has(t, CHARGE_DISPUTE) || urgency));
  const deadlineThreat = has(t, /\bwithin \d{1,2} (?:minutes?|hours?|days?)\b|\baccounts? .{0,30}\blocked\b|\bfunds .{0,25}released\b/);
  // A password, PIN or login-detail request; an ordinary sign-in request only with a threat, a deadline or a disguised name.
  const loginRequest = asks.secret_request || ((asks.sign_in_request || asks.payment_detail_update) && (threat || deadlineThreat || lookalikeName));
  const namedEntities = Array.from(new Set(Array.from(text.matchAll(/\b(?:Merchant|from|to)\s*:\s*([A-Z][A-Za-z0-9&'’.-]+(?:\s+[A-Z][A-Za-z0-9&'’.-]+){0,4})/g), (match) => match[1].replace(/\s+(?:Pty|Ltd).*$/i, " $&").trim()))).slice(0, 6);
  const unknownSender = !sender.trim() || /unknown|private|no caller id/i.test(sender) || /^\+?\d[\d\s()-]{6,}$/.test(sender.trim());

  const requestedAction = callbackRequest && allegedCharge ? "call a supplied number about an alleged charge" : codeRequest ? "share a verification code" : giftCards ? "buy gift cards" : remoteAccess ? "install software / allow remote access"
    : advanceFee ? "pay a fee to receive money" : paymentRequest && urls.length ? "pay via a link" : loginRequest ? "log in via a link" : identityRequest ? "share identity details"
    : moneyRequest ? "send money" : crypto ? "send cryptocurrency" : urls.length ? "open a link" : null;

  return { urls, claimedBrand: brand?.name ?? null, brandKind: brand?.kind ?? null,
    lookalikeChars: Array.from(new Set(disguised.flatMap((d) => d.chars))), lookalikeName, replyRequest, timePressure, governmentRebate,
    requestedAction: requestedAction ?? (replyRequest ? "reply to the message" : null), paymentRequest, smallPayment, codeRequest, urgency, threat, giftCards, crypto,
    remoteAccess, newNumber, familyClaim, moneyRequest, platformSwitch, guaranteedReturns, jobOffer, advanceFee, fakePayment, extortion, romanceEscalation, identityRequest, loginRequest,
    callbackNumber, callbackRequest, allegedCharge, deadlineThreat, namedEntities, unknownSender };
}

const VERIFY: Record<NonNullable<MessageSignals["brandKind"]> | "family" | "person" | "none", string> = {
  bank: "Open your bank's official app, or call the number printed on the back of your card. Never use a number or link from the message.",
  courier: "Open the courier's official app or type their website address yourself and use your tracking number. Real couriers don't charge small fees by text.",
  government: "Log in to myGov or the agency's official website yourself. Government agencies don't ask for payment or identity details by text link.",
  toll: "Open the toll operator's official app or website yourself and check your account there.",
  telco: "Open your provider's official app or call the number on your bill.",
  tech: "Open the company's official app or website yourself and check for any notices there.",
  marketplace: "Check payment inside the marketplace app or your own bank app. Never follow a courier or payment link a buyer sends you.",
  energy: "Contact your energy retailer using the number on your bill or its official website. For rebates, check the Clean Energy Regulator or your state government's website yourself.",
  family: "Call the family member on the number you already have saved. If they don't answer, try another family member before sending anything.",
  person: "Contact the person through a channel you already trust and have used before — not the one in this message.",
  none: "If a message claims to be from someone, contact them using details you already have or find yourself — never from the message.",
};

function scenarioFor(s: MessageSignals): { scenario: Scenario; title: string; state: ApolloState; verdict: string; why: string[]; rec: string; verify: string } {
  const brand = s.claimedBrand ?? "the sender";
  const courierHosts = ["auspost.com.au", "startrack.com.au", "dhl.com", "fedex.com", "ups.com", "sendle.com"];
  const courierLinksOfficial = s.brandKind === "courier" && s.urls.length > 0 && s.urls.every((raw) => {
    try { const host = new URL(raw.startsWith("http") ? raw : `https://${raw}`).hostname.toLowerCase(); return courierHosts.some((domain) => host === domain || host.endsWith(`.${domain}`)); }
    catch { return false; }
  });

  // MF-3 + MF-4: Check whether ALL URLs in the message resolve to the claimed brand's official
  // domains. Used by M02/M01/M04 to avoid asserting "the link is not official" when it actually is.
  // IMPORTANT: An official-looking URL does NOT authenticate the sender — trust only influences
  // the url-related `why` text and reduces urgency, NOT the identity verification.
  const allUrlsOfficialForBrand = (brandName: string | null): boolean => {
    if (!brandName || !s.urls.length) return false;
    const record = OFFICIAL_DOMAINS.find((b) => b.name.toLowerCase() === brandName.toLowerCase());
    if (!record) return false;
    return s.urls.every((raw) => {
      try {
        const host = new URL(raw.startsWith("http") ? raw : `https://${raw}`).hostname.toLowerCase();
        return record.official.some((d) => host === d || host.endsWith(`.${d}`));
      } catch { return false; }
    });
  };
  const urlsOfficial = allUrlsOfficialForBrand(s.claimedBrand);
  // For government messages, also accept any .gov.au domain as consistent with a government claim.
  const urlsGovOfficial = s.brandKind === "government" && s.urls.length > 0 && s.urls.every((raw) => {
    try { const host = new URL(raw.startsWith("http") ? raw : `https://${raw}`).hostname.toLowerCase(); return host.endsWith(".gov.au") || host === "gov.au"; }
    catch { return false; }
  });
  if (s.callbackRequest && s.allegedCharge) {
    const paypal = s.claimedBrand === "PayPal";
    return { scenario: "M16", title: "Alleged-charge callback trap", state: "barking",
      verdict: "This message tries to make you call a supplied number about an alleged charge.",
      why: [s.claimedBrand ? `It claims to be ${s.claimedBrand} and names a charge or transaction.` : "It alleges a charge or transaction.",
        s.callbackNumber ? `It directs you to call ${s.callbackNumber}, a number supplied by the message itself.` : "It directs you to a callback number supplied by the message.",
        s.deadlineThreat ? "It combines a short deadline with a threat that funds will be released or the account locked." : "It pressures you to resolve the alleged charge by phone."],
      rec: paypal
        ? "Do not call the supplied number. Open your existing PayPal app independently and check Activity. If the charge appears there, report it from inside PayPal."
        : `Do not call the supplied number. Open ${s.claimedBrand ? `${s.claimedBrand}'s` : "your bank or card provider's"} official app yourself and check your recent activity. If the charge appears there, report it from inside the app.`,
      verify: paypal
        ? "Open the PayPal app you already use or type paypal.com yourself. Do not use the number in this message."
        : VERIFY[s.brandKind ?? "bank"] };
  }
  if (s.codeRequest) return { scenario: "M06", title: "Verification code request", state: "barking", verdict: "Someone is asking for a code that is meant only for you.",
    why: ["It asks you to share a verification or security code.", "Codes like this are used to take over accounts.", s.urgency ? "It pushes you to act quickly." : "No legitimate service asks you to read a code back to them."],
    rec: "Don't share that code. Verification codes are meant for you, not for someone contacting you.", verify: VERIFY[s.brandKind ?? "person"] };
  if (s.giftCards) return { scenario: "M10", title: "Gift card scam", state: "barking", verdict: "This is asking you to pay with gift cards — a classic scam.",
    why: ["It asks for gift cards or their codes.", s.claimedBrand ? `It claims to be ${brand}, who never ask for gift cards.` : "No real business, agency or boss asks for payment in gift cards.", s.urgency || s.threat ? "It uses pressure or secrecy." : "Gift card codes can't be traced or refunded."],
    rec: "Don't buy the cards or send any codes. Check with the real person or organisation using details you already have.", verify: VERIFY[s.brandKind ?? "person"] };
  if (s.remoteAccess) return { scenario: "M13", title: "Remote access scam", state: "barking", verdict: "This asks you to install software so someone can 'help' you — don't.",
    why: ["It claims your account or device has a problem you didn't notice.", "It asks you to install an app or allow remote access.", "That software would give a stranger control of your device."],
    rec: "Don't install anything or share your screen. If you're worried about an account, open the official app yourself.", verify: VERIFY[s.brandKind ?? "tech"] };
  if (s.advanceFee || (s.fakePayment && s.paymentRequest && !s.brandKind)) return { scenario: "M12", title: "Fake payment / refund", state: "barking", verdict: "You're being asked to pay to 'receive' money — that's the scam.",
    why: ["It says money is waiting for you.", "It asks for a fee before you can get it.", "Real payments never need a fee to release them."],
    rec: "Don't pay anything. Check your real bank or payment app for the money — if it isn't there, it isn't real.", verify: VERIFY[s.brandKind ?? "marketplace"] };
  // MF-3: When URLs are the ONLY trigger (no loginRequest/identityRequest), check whether they
  // all resolve to the claimed brand's official domains. An official-looking URL does not
  // authenticate the sender, so the message still deserves attention (ears_up), not dismissal.
  // MF-4: The why text now states only what the code actually verified.
  if (s.brandKind === "bank" && (s.loginRequest || s.identityRequest || s.urls.length)) {
    const urlOnly = !s.loginRequest && !s.identityRequest && s.urls.length > 0;
    if (urlOnly && urlsOfficial) {
      // All URLs match the brand's official domains. Still flag as ears_up because Apollo cannot
      // verify who actually sent this message — only that the links appear to match.
      return { scenario: "M02", title: "Bank notification to verify", state: "ears_up",
        verdict: `This message claims to be from ${brand}. The link appears to match ${brand}'s official website, but Apollo cannot verify who sent the message.`,
        why: [`It claims to be ${brand}.`, `The link destination matches ${brand}'s known official domain.`, "Apollo cannot verify the SMS sender. Open your bank's app independently to check."],
        rec: "Don't use the link in the message. Open your bank's official app yourself to check for any notices.", verify: VERIFY.bank };
    }
    const urlWhy = s.urls.length
      ? (urlOnly && !urlsOfficial ? `The link leads to a domain that is not one of ${brand}'s official websites.` : "It asks you to act on your account via a link.")
      : "It asks for details a bank already has.";
    return { scenario: "M02", title: "Bank fraud message", state: "barking", verdict: `This message appears to impersonate ${brand}.`,
      why: [`It claims to be ${brand}.`, s.threat || s.urgency ? "It uses fear and urgency about your account or money." : "It asks you to act on your account.", urlWhy],
      rec: "Don't enter your password or verification code. Open your bank's app yourself to check.", verify: VERIFY.bank };
  }
  // A disguised organisation name, and a government-rebate deadline pushing for a reply: the message's own words are quoted.
  const pressureWhy = [
    s.governmentRebate ? `It claims a government rebate (“${s.governmentRebate}”).` : "",
    s.timePressure ? `It puts a deadline on it to hurry you (“${s.timePressure}”).` : "",
    s.replyRequest ? `It asks you to reply (“${s.replyRequest}”) so someone can contact you.` : s.callbackRequest ? "It asks you to call a number it supplies." : "",
  ].filter(Boolean);
  const pressureRec = "Don't reply. If you want solar or battery advice, find an installer yourself and check rebates on the Clean Energy Regulator's or your state government's website.";
  if (s.lookalikeName) {
    const chars = s.lookalikeChars.map((c) => `“${c}”`).join(" and ");
    return { scenario: "M17", title: "Disguised business name", state: "growling",
      verdict: `This message writes the name ${brand} with a look-alike character, so Apollo can't take it at face value.`,
      why: [`It writes “${brand}” with ${chars} in place of ordinary letters.`,
        "Look-alike characters are a common way to get scam texts past message filters. A real business has no reason to use them.",
        ...pressureWhy],
      rec: pressureWhy.length ? pressureRec : `Don't reply or act on it. Contact ${brand} only through details you find yourself.`,
      verify: VERIFY[s.brandKind ?? "none"] };
  }
  if (s.governmentRebate && s.timePressure && (s.replyRequest || s.callbackRequest)) return { scenario: "M18", title: "Rebate deadline pressure", state: "growling",
    verdict: "This message uses a government-rebate deadline to rush you into replying.",
    why: [...pressureWhy, s.claimedBrand ? `It says it's from ${brand}, but Apollo can't confirm who sent it.` : "It doesn't say clearly who it's from."],
    rec: pressureRec, verify: VERIFY[s.brandKind === "government" ? "government" : s.brandKind ?? "energy"] };
  if (s.extortion) return { scenario: "M14", title: "Threat / extortion", state: s.crypto || s.paymentRequest ? "barking" : "growling", verdict: "This is an extortion attempt. A claim is not evidence.",
    why: ["It claims to have hacked or recorded you.", s.crypto ? "It demands payment in cryptocurrency." : "It demands payment to stay quiet.", "These are sent in bulk; the claim is almost always false."],
    rec: "Don't pay and don't reply. Apollo sees no evidence your device is compromised from this message alone — change reused passwords if you're worried.", verify: VERIFY.none };
  if (s.familyClaim && (s.newNumber || s.moneyRequest)) return { scenario: "M05", title: "Hi Mum / Hi Dad pattern", state: "ears_up", verdict: "This matches a common family-impersonation scam pattern.",
    why: ["It claims to be a family member on a new or temporary number.", s.moneyRequest ? "It asks for help paying something." : "It sets up a reason for a later money request.", "It uses emotion to hurry you."],
    rec: "Before sending money, contact your family member using the number you already know.", verify: VERIFY.family };
  if (courierLinksOfficial && !s.paymentRequest && !s.loginRequest && !s.identityRequest && !s.threat) return { scenario: "M15", title: "Delivery notification to verify", state: "ears_up", verdict: "The visible tracking link matches a configured courier domain, but the message sender is not authenticated.",
    why: ["The destination matches a configured official courier domain.", "A visible domain match supports the claim but does not prove who sent the message.", "No payment, login, identity or threat request was found."],
    rec: "Prefer the courier's official app or type its known address yourself. Use the message link only if you independently expected this delivery.", verify: VERIFY.courier };
  if (s.brandKind === "courier") {
    // MF-4: Only assert link destination when actually checked.
    const linkWhy = s.urls.length
      ? (courierLinksOfficial ? "The link matches a known courier domain, but Apollo cannot verify who sent the message." : "The link leads to a domain that is not a known official courier website.")
      : "Real couriers don't text payment links.";
    // Parcel-redelivery lures stay at growling (credible suspicion) unless threat intelligence
    // later marks the destination malicious — see the urlVerdict escalation below. This keeps
    // barking reserved for evidence of an active, confirmed threat.
    const courierState: ApolloState = (s.paymentRequest || s.urls.length) ? "growling" : "ears_up";
    return { scenario: "M01", title: "Parcel delivery scam", state: courierState, verdict: "This looks like a parcel-delivery scam.",
      why: ["It claims to be from a delivery company.", s.smallPayment || s.paymentRequest ? "It asks for an unexpected (often small) payment." : "It asks you to act on a parcel you may not be expecting.", linkWhy],
      rec: "Don't use the link. Track any parcel through the courier's official app or website.", verify: VERIFY.courier };
  }
  if (s.brandKind === "toll") return { scenario: "M03", title: "Toll / road payment scam", state: "growling", verdict: "This looks like a toll-payment scam.",
    why: ["It claims to be a toll or road operator.", s.threat ? "It threatens penalties to hurry you." : "It asks for a payment you weren't expecting.", s.urls.length ? "Payment is via a link, not the official app." : "Toll operators don't chase payment by text link."],
    rec: "Don't pay via the link. Check your toll account in the official app yourself.", verify: VERIFY.toll };
  if (s.brandKind === "government") {
    // MF-3/MF-4: Check government URLs against .gov.au and official brand domains.
    const govUrlWhy = s.urls.length
      ? ((urlsOfficial || urlsGovOfficial) ? "The link appears to match an official government domain, but Apollo cannot verify who sent the message." : "The link leads to a domain that is not an official government address.")
      : "Agencies don't do this by text.";
    // Evidence-based escalation:
    // - Direct identity/payment request → barking (strong deceptive ask)
    // - Non-official URLs present → barking (brand claim + non-official URL = strong phishing evidence)
    // - Official URLs, no pressure → ears_up (could be legitimate, monitor)
    // - Else → growling (credible suspicion, insufficient for barking)
    const urlsAreNonOfficial = s.urls.length > 0 && !(urlsOfficial || urlsGovOfficial);
    const govState = (s.identityRequest || s.paymentRequest) ? "barking" as ApolloState
      : urlsAreNonOfficial ? "barking" as ApolloState
      : (s.urls.length && (urlsOfficial || urlsGovOfficial) && !s.threat && !s.urgency) ? "ears_up" as ApolloState : "growling" as ApolloState;
    return { scenario: "M04", title: "Government / tax impersonation", state: govState, verdict: govState === "ears_up" ? "This message claims to be from a government agency. The link matches an official domain, but Apollo cannot verify the sender." : "This looks like a government impersonation scam.",
      why: ["It claims to be a government agency.", s.paymentRequest ? "It demands a payment." : s.identityRequest ? "It asks for identity details." : s.urls.length ? govUrlWhy : "It offers a refund to get you to click.", govUrlWhy],
      rec: "Don't click or reply. Log in to myGov or the agency's website yourself to check for real notices.", verify: VERIFY.government };
  }
  if (s.guaranteedReturns || (s.crypto && (s.moneyRequest || s.paymentRequest))) return { scenario: "M08", title: "Investment / crypto scam", state: "growling", verdict: "This looks like an investment scam.",
    why: ["It offers guaranteed or unrealistic returns.", "It wasn't something you asked for.", s.crypto ? "It involves cryptocurrency, which can't be reversed." : "It rushes you to commit money."],
    rec: "Don't send money. Guaranteed returns don't exist — check any adviser on the ASIC register yourself.", verify: VERIFY.none };
  if (s.romanceEscalation) return { scenario: "M09", title: "Romance scam escalation", state: "growling", verdict: "A relationship message has turned into a request for money.",
    why: ["Affectionate language is paired with a money, gift-card or crypto request.", "Emergencies and travel costs are common pressure stories.", "Apollo is flagging the money request, not the relationship."],
    rec: "Pause before sending anything. Talk it through with someone you trust, and never send money to someone you haven't met.", verify: VERIFY.person };
  if (s.jobOffer && (s.platformSwitch || s.guaranteedReturns || has(text_cache, /\$\s?\d{3,}/))) return { scenario: "M07", title: "Fake job offer", state: s.paymentRequest || s.crypto ? "growling" : "ears_up", verdict: "This matches a fake job-offer pattern.",
    why: ["It promises unusually high, easy earnings.", s.platformSwitch ? "It moves you to another messaging app." : "It's unsolicited.", "These usually end in asking you to pay or 'invest'."],
    rec: "Don't pay any deposit or share ID documents. Apply through the company's official careers page yourself.", verify: VERIFY.none };
  if (s.brandKind === "marketplace" || (s.fakePayment && s.urls.length)) return { scenario: "M11", title: "Marketplace scam", state: "growling", verdict: "This looks like a marketplace payment scam.",
    why: ["It claims payment is done or waiting.", "It sends you to an outside courier or payment link.", "Those links collect card or login details."],
    rec: "Only trust payment you can see in your own bank or the marketplace app. Don't use the link.", verify: VERIFY.marketplace };
  if (s.urls.length && (s.urgency || s.threat || s.loginRequest || s.paymentRequest)) return { scenario: "M04", title: "Suspicious link with pressure", state: "growling", verdict: "This message pushes you to a link with urgency.",
    why: ["It contains a link.", s.threat ? "It threatens a consequence." : "It hurries you.", s.loginRequest ? "It asks you to log in." : "It asks you to act via the link."],
    rec: "Don't tap the link. Check the link with ApolloSG first, or go to the organisation yourself.", verify: VERIFY[s.brandKind ?? "none"] };
  return { scenario: "M15", title: "No concern identified", state: "resting", verdict: "No concern was identified within the checks completed for this message.",
    why: ["No suspicious links.", "No payment, code or identity request.", "No impersonation or threat language."],
    rec: "Nothing to do. If it's from a number you don't know, reply cautiously and never share codes or payment details.", verify: VERIFY.none };
}

let text_cache = "";

export function analyseMessage(sender: string, text: string): MessageAnalysis {
  text_cache = text.toLowerCase();
  const signals = extractSignals(sender, text);
  const r = scenarioFor(signals);
  const labels: string[] = [];
  if (signals.claimedBrand) labels.push(`Claims to be ${signals.claimedBrand}`);
  if (signals.urls.length) labels.push(`${signals.urls.length} link${signals.urls.length > 1 ? "s" : ""}`);
  if (signals.urgency && !signals.timePressure) labels.push("Urgency");
  if (signals.timePressure) labels.push("Deadline pressure");
  if (signals.lookalikeChars.length) labels.push(signals.lookalikeName ? "Disguised business name" : "Look-alike characters");
  if (signals.replyRequest) labels.push("Asks for a reply");
  if (signals.governmentRebate) labels.push("Government rebate claim");
  if (signals.threat) labels.push("Threat / penalty");
  if (signals.paymentRequest) labels.push("Payment request");
  if (signals.codeRequest) labels.push("Code request");
  if (signals.identityRequest) labels.push("Identity request");
  if (signals.loginRequest) labels.push("Login request");
  if (signals.giftCards) labels.push("Gift cards");
  if (signals.crypto) labels.push("Crypto");
  if (signals.remoteAccess) labels.push("Remote access");
  if (signals.callbackRequest) labels.push("Callback request");
  if (signals.allegedCharge) labels.push("Alleged charge");
  if (signals.deadlineThreat) labels.push("Deadline / account threat");
  if (signals.newNumber) labels.push("New number");
  if (signals.unknownSender) labels.push("Unknown sender");
  return { state: r.state, scenario: r.scenario, scenarioTitle: r.title, verdict: r.verdict, why: r.why, recommendation: r.rec, signals, signalLabels: labels, verifySender: r.verify };
}

/** Link hand-off: a confirmed-malicious URL raises the message to Guarding (biting) semantics — verified evidence. */
export function escalateForUrl(state: ApolloState, urlVerdict: "clean" | "malicious" | "unknown"): ApolloState {
  // Reputation is a warning, never packet-backed enforcement evidence.
  if (urlVerdict === "malicious") return "barking";
  return state;
}
