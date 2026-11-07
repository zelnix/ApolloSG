// Gate 4 — Phone Call Protection. Call Risk Engine + Scam/Social-Engineering rules (C01–C20).
// Works from what the user *selects* during a live call (no audio, no covert recording) plus an
// optional typed description and the claimed identity. Unknown number ≠ scam; caller ID ≠ proof.

import { extractSignals } from "./messageAnalysis.ts";
import type { ApolloState } from "./types";

export type CallAsk = "transfer" | "code" | "password" | "install" | "remote" | "giftcards" | "crypto" | "screen" | "bankdetails" | "dont_hangup" | "refund" | "subscription" | "callback" | "nothing" | "other";
export type CallClaim = "bank" | "government" | "techsupport" | "family" | "telco" | "business" | "delivery" | "investment" | "relationship" | "unknown";

export const CALL_ASKS: { id: CallAsk; label: string }[] = [
  { id: "transfer", label: "Transfer money" }, { id: "code", label: "Give a verification code" }, { id: "password", label: "Give a password / PIN" },
  { id: "install", label: "Install an app" }, { id: "remote", label: "Allow remote access" }, { id: "giftcards", label: "Buy gift cards" },
  { id: "crypto", label: "Send cryptocurrency" }, { id: "screen", label: "Share my screen" }, { id: "bankdetails", label: "Give bank / card details" },
  { id: "dont_hangup", label: "Stay on the line / tell no one" }, { id: "refund", label: "Accept a refund" }, { id: "subscription", label: "Cancel a renewal" },
  { id: "callback", label: "Call a number back" }, { id: "nothing", label: "Nothing unusual" }, { id: "other", label: "Something else" },
];
export const CALL_CLAIMS: { id: CallClaim; label: string }[] = [
  { id: "bank", label: "My bank" }, { id: "government", label: "Government / police / ATO" }, { id: "techsupport", label: "Tech support (Microsoft, Apple…)" },
  { id: "family", label: "A family member" }, { id: "telco", label: "Telco / NBN" }, { id: "business", label: "A business / appointment" },
  { id: "delivery", label: "Delivery / parcel company" },
  { id: "investment", label: "An investment offer" }, { id: "relationship", label: "Someone I met online" }, { id: "unknown", label: "Didn't say / not sure" },
];

export interface CallInput { asks: CallAsk[]; claim: CallClaim; number?: string; transcript?: string; brandName?: string | null }
export interface CallAnalysis {
  scenario: string; title: string; state: ApolloState; verdict: string; why: string[]; recommendation: string; verifyCaller: string;
  claimedBrand: string | null; requestedActions: CallAsk[]; basis: string[];
}

const VERIFY: Record<CallClaim, string> = {
  bank: "Hang up. Open your bank's official app, or call the number on the back of your card. Banks will never mind you calling back — scammers will.",
  government: "Hang up. Find the agency's number yourself (e.g. ato.gov.au, servicesaustralia.gov.au) and call that. Agencies never demand payment by phone.",
  techsupport: "Hang up. Microsoft, Apple and Google do not cold-call about viruses. If you're worried, open your device's own settings or the official website yourself.",
  family: "Call the family member on the number you already have saved, or another relative you trust. Don't rely on the number that called you.",
  telco: "Hang up and call your provider using the number on your bill or in their official app.",
  business: "Look the business up yourself (their website or a directory) and call the number listed there.",
  delivery: "Hang up. Track the parcel in the courier's official app or a website address you type yourself. Couriers don't call to ask for fees or card details.",
  investment: "Check the adviser and company on the ASIC register yourself. Never commit money on a cold call.",
  relationship: "Talk it over with someone you trust before sending anything. Never send money to someone you haven't met in person.",
  unknown: "If they claim to be from an organisation, hang up and contact it using details you find yourself — never a number they give you.",
};
const CLAIM_LABEL: Record<CallClaim, string> = { bank: "your bank", government: "a government agency", techsupport: "tech support", family: "a family member", telco: "your telco", business: "a business", delivery: "a delivery company", investment: "an investment firm", relationship: "someone you met online", unknown: "an unnamed caller" };

// The call as the person described it, in their own plain sentences: what an investigation receives as the call's
// details (never the screen's option ids), so TC Hawkeye can compare it with Scamwatch's phone-scam patterns.
const CLAIM_SENTENCE: Record<CallClaim, string> = {
  bank: "The caller said they were from my bank", government: "The caller said they were from the government, the police or the ATO",
  techsupport: "The caller said they were from tech support", family: "The caller said they were a family member",
  telco: "The caller said they were from my telco or the NBN", business: "The caller said they were from a business or about an appointment",
  delivery: "The caller said they were from a delivery or parcel company", investment: "The caller offered me an investment",
  relationship: "The caller is someone I met online", unknown: "I'm not sure who the caller said they were",
};
const ASK_SENTENCE: Record<CallAsk, string> = {
  transfer: "They asked me to transfer money.", code: "They asked me to give a verification code.", password: "They asked me to give a password or PIN.",
  install: "They asked me to install an app.", remote: "They asked me to allow remote access.", giftcards: "They asked me to buy gift cards.",
  crypto: "They asked me to send cryptocurrency.", screen: "They asked me to share my screen.", bankdetails: "They asked me to give my bank or card details.",
  dont_hangup: "They asked me to stay on the line and tell no one.", refund: "They offered me a refund.", subscription: "They asked me to cancel a renewal.",
  callback: "They asked me to call a number back.", nothing: "They didn't ask me to do anything unusual.", other: "They asked me to do something else.",
};

/** The call's details for an investigation, one plain sentence per thing the person told ApolloSG. `note`: a line that
 *  comes first (a provider's own rating of the number). */
export function describeCall(input: CallInput, note?: string | null): string {
  const brand = input.brandName?.trim();
  return [
    note || null,
    `${CLAIM_SENTENCE[input.claim]}${brand ? ` (${brand})` : ""}.`,
    ...input.asks.map((ask) => ASK_SENTENCE[ask]),
    input.number?.trim() ? `The number that called: ${input.number.trim()}` : null,
    input.transcript?.trim() ? `What the caller said, in my words: ${input.transcript.trim()}` : null,
  ].filter(Boolean).join("\n");
}

export function analyseCall(input: CallInput): CallAnalysis {
  const asks = new Set(input.asks);
  const text = (input.transcript ?? "").trim();
  const sig = text ? extractSignals(input.number ?? "", text) : null;
  // A transcript can reveal who the caller claims to be when the user didn't pick.
  const inferred: Partial<Record<NonNullable<typeof sig>["brandKind"] & string, CallClaim>> = { bank: "bank", government: "government", tech: "techsupport", telco: "telco", courier: "delivery", toll: "business", marketplace: "business" };
  const claim: CallClaim = input.claim !== "unknown" ? input.claim : (sig?.brandKind && inferred[sig.brandKind]) || (sig?.familyClaim ? "family" : sig?.guaranteedReturns ? "investment" : "unknown");
  // Fold description signals into asks so typed descriptions drive the same rules.
  if (sig) {
    if (sig.codeRequest) asks.add("code"); if (sig.giftCards) asks.add("giftcards"); if (sig.remoteAccess) asks.add("remote"); if (sig.crypto) asks.add("crypto");
    if (sig.moneyRequest || (sig.paymentRequest && sig.threat)) asks.add("transfer"); if (sig.identityRequest) asks.add("bankdetails");
  }
  const brand = input.brandName ?? sig?.claimedBrand ?? null;
  const who = brand ?? CLAIM_LABEL[claim];
  const basis = ["What you reported the caller asked for", ...(text ? ["What you described the caller said"] : []), ...(input.number ? ["Caller number (reputation not available on this build)"] : []), "Recent ApolloSG events (Threat Scent)"];
  const base = { claimedBrand: brand, requestedActions: [...asks], basis, verifyCaller: VERIFY[claim] };
  const R = (scenario: string, title: string, state: ApolloState, verdict: string, why: string[], recommendation: string): CallAnalysis => ({ ...base, scenario, title, state, verdict, why, recommendation });
  const urgencyWhy = sig?.urgency || sig?.threat ? [`It uses pressure: ${sig?.threat ? "threats or penalties" : "urgency"}.`] : [];

  if (asks.has("code")) return R("C03", "Verification code request", "barking", "Do not share the code.", [`The caller (${who}) asked you to read out a security code.`, "A verification code can let someone into your account — it's for you, not for callers.", "Real organisations never ask you to read a code back to them."], "Don't share the code. Hang up and contact the organisation independently.");
  if (asks.has("password")) return R("C04", "Password / PIN request", "barking", "Do not give the caller your password or PIN.", [`The caller (${who}) asked for a password, PIN or security answers.`, "No bank, agency or company needs your password to help you.", ...urgencyWhy], "Hang up. If you're worried about the account, open the official app yourself.");
  if (asks.has("transfer") && (claim === "bank" || sig?.brandKind === "bank" || /safe account|secure account|protected account/i.test(text))) return R("C02", "\u201cSafe account\u201d transfer", "barking", "Do not transfer the money.", ["A caller telling you to move money into a new \u201csafe\u201d account is a major scam warning sign.", "Banks never move your money by phone instruction — they can freeze it themselves.", `They claim to be ${who}, but that isn't verified by caller ID.`], "Hang up and contact your bank independently using its official app or the number on your card.");
  if (asks.has("remote") || asks.has("screen")) return R(asks.has("screen") ? "C15" : "C05", asks.has("screen") ? "Screen sharing request" : "Remote access request", "barking", asks.has("screen") ? "Do not share your screen with this caller." : "Do not install or open remote-access software for this caller.", [`${who[0].toUpperCase()}${who.slice(1)} asked to see or control your device.`, "Screen sharing or remote-control apps let a stranger watch your banking and codes.", "Genuine support never needs this on an unsolicited call."], "Hang up. If you already installed something or allowed access, use the recovery steps now.");
  if (asks.has("giftcards")) return R("C08", "Gift card payment", "barking", "Do not buy or provide gift-card codes to this caller.", ["No bank, agency, company or boss takes payment in gift cards.", "Gift-card codes can't be traced or refunded.", ...urgencyWhy], "Hang up. If you already bought cards, don't send the codes.");
  if (asks.has("dont_hangup")) return R("C14", "\u201cDon't hang up / tell no one\u201d", "barking", "A caller trying to stop you from independently checking their story is a serious warning sign.", ["They want you isolated: stay on the line, tell no one, don't call your bank.", "Legitimate organisations are happy for you to hang up and call back.", ...urgencyWhy], "Hang up now. Then call the organisation yourself using details you find independently.");
  if (asks.has("install")) return R(claim === "techsupport" ? "C06" : "C05", "App install request", "barking", "Do not install anything for this caller.", [`${who[0].toUpperCase()}${who.slice(1)} asked you to install an app during the call.`, "Unsolicited callers who need software on your device are almost always after control of it.", ...urgencyWhy], "Hang up. If you already installed it, use the recovery steps.");
  if (claim === "government" && (asks.has("transfer") || asks.has("crypto") || asks.has("bankdetails") || sig?.threat)) return R("C07", "Government / police impersonation", "barking", "Government agencies don't demand payment or threaten arrest by phone.", [`The caller claims to be ${who}.`, asks.has("crypto") ? "They want payment in cryptocurrency." : "They demand payment or bank details.", ...urgencyWhy], "Hang up. Check any real debt yourself via myGov or the agency's official number.");
  if (asks.has("crypto")) return R("C09", "Cryptocurrency payment", asks.has("transfer") || claim !== "investment" ? "barking" : "growling", "Don't send cryptocurrency on a caller's instruction.", [`${who[0].toUpperCase()}${who.slice(1)} wants you to buy or send crypto.`, "Crypto payments can't be reversed.", "\u201cMove your money into crypto for safety\u201d is a scam script."], "Hang up. Don't visit a crypto ATM or wallet for this caller.");
  if (asks.has("bankdetails")) return R(asks.has("refund") ? "C16" : "C01", asks.has("refund") ? "Fake refund" : "Bank / card details request", "growling", "Don't give bank or card details to someone who called you.", [asks.has("refund") ? "An unexpected refund that needs your bank details is a common scam." : `The caller (${who}) asked for bank or card details.`, "If money is owed to you, the organisation already knows how to pay you.", ...urgencyWhy], "Hang up and check with the organisation yourself.");
  if (asks.has("transfer")) return R(claim === "family" ? "C10" : claim === "relationship" ? "C13" : "C02", claim === "family" ? "Family emergency money request" : "Money transfer request", claim === "family" || claim === "relationship" ? "ears_up" : "barking", claim === "family" ? "Verify this independently before sending money." : "Don't transfer money on a phone call.", [claim === "family" ? "A family emergency with an urgent money request is a common impersonation pattern — and sometimes real." : `${who[0].toUpperCase()}${who.slice(1)} wants a transfer now.`, "Scammers rely on urgency and secrecy.", "ApolloSG can't tell who is really calling — only that the request is risky."], claim === "family" ? "Hang up and call the family member on their saved number, or another relative." : "Hang up and verify with the organisation independently.");
  if (asks.has("refund")) return R("C16", "Unexpected refund", "growling", "Unexpected refunds by phone usually lead to a payment or remote-access request.", [`The caller (${who}) offers a refund you weren't expecting.`, "The next step is usually \u201cwe need your bank details\u201d or \u201cinstall this\u201d.", ...urgencyWhy], "Hang up. If a refund is real, the company can pay you without your help.");
  if (asks.has("subscription")) return R("C17", "Subscription renewal scare", "growling", "\u201cYour subscription renews today for $499\u201d is a scam opener.", ["It pushes you to \u201ccancel\u201d by giving bank details or installing software.", "Real companies email invoices; they don't cold-call about renewals.", ...urgencyWhy], "Hang up. Check the subscription in the app store or your bank statement yourself.");
  if (asks.has("callback")) return R("C18", "Callback request", "ears_up", "Be careful calling unknown numbers back.", ["Missed-call and callback scams use premium or overseas numbers.", "Not every international number is a scam — but don't call back one you don't recognise.", ...urgencyWhy], "Look the number up first. If it matters, they'll contact you again or leave a clear message.");
  if (claim === "investment") return R("C12", "Investment cold call", "growling", "Guaranteed returns on a cold call are a scam pattern.", ["Unsolicited investment offers with guaranteed or high returns.", "Pressure to decide quickly.", "Often ends in crypto or offshore payments."], "Hang up. Check any adviser on the ASIC register yourself.");
  if (claim === "techsupport") return R("C06", "Unsolicited tech support", "growling", "Tech companies don't cold-call about hacked devices.", ["The caller claims to be tech support you didn't contact.", "Next step is usually remote access, payment or a login.", ...urgencyWhy], "Hang up. Your device isn't broken because a caller says so.");
  if (claim === "family" || claim === "relationship") return R(claim === "family" ? "C11" : "C13", claim === "family" ? "Unexpected family call" : "Relationship call", "ears_up", "Nothing dangerous asked yet — stay alert if money comes up.", ["Voices can be imitated; Apollo can't verify who is speaking.", "Watch for an emergency plus a money request plus secrecy.", "If in doubt, hang up and call them back on their saved number."], "If they ask for money, verify through another trusted channel first.");
  if (claim === "bank" || claim === "government" || claim === "telco") return R(claim === "bank" ? "C20" : "C01", claim === "bank" ? "Possible genuine bank call" : `${who[0].toUpperCase()}${who.slice(1)} call`, "ears_up", `Nothing dangerous asked. Caller ID isn't proof they are ${who}, so verify if you need to act.`, [`The caller claims to be ${who}.`, "They have NOT asked for a password, code, transfer or remote access — a good sign.", "You can always hang up and call back on the official number."], "If they want you to do anything, hang up and call the organisation back yourself.");
  return R("C19", "Ordinary call", "resting", "Nothing suspicious from what you've described.", ["No request for money, codes, passwords or software.", "No impersonation of a bank or agency.", "Unknown number alone is not a warning sign."], "Carry on — and come back to ApolloSG if the call changes.");
}
