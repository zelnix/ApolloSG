// What a notification actually says. Two jobs, both at the notification boundary only:
//  1. A purpose-built short summary of an event — from the case's Higgins Case Briefing when it has one (its first
//     finding, subject always named), otherwise ("Higgins: The Instagram link you sent has signs that need
//     checking. Open ApolloSG to see what I found.") — never the full Higgins explanation, which stays in
//     the Threat Case untouched.
//  2. presentAlertText(): decode HTML entities (&quot; &amp; &#39; &lt; …) exactly once, tidy whitespace and
//     fit the OS limits, just before the text is handed to Android/iOS. The stored investigation and
//     evidence are never altered.
// Pure + unit-tested.

import { briefed, firstFinding, needsYou } from "../domain/caseBriefing.ts";
import { luddishText } from "../domain/luddish/index.ts";
import { firstReason, reasonInSentence } from "../domain/luddish/present.ts";
import { shortDomain } from "../domain/threatSubject.ts";
import type { PatrolEvent } from "../domain/types";
import type { LocalAlert } from "./notifications";

const NAMED: Record<string, string> = {
  amp: "&", quot: "\"", apos: "'", lt: "<", gt: ">", nbsp: " ", ndash: "–", mdash: "—", hellip: "…",
  lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”", laquo: "«", raquo: "»", middot: "·", bull: "•",
  copy: "©", reg: "®", trade: "™", euro: "€", pound: "£", cent: "¢", deg: "°", times: "×",
};
const ENTITY = /&(#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,15});/g;

function fromCodePoint(code: number): string | null {
  const valid = code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
  return valid ? String.fromCodePoint(code) : null;
}

/** Decode HTML entities in ONE pass: "&amp;quot;" becomes "&quot;", never '"'. Unknown or invalid
 *  entities are left exactly as written. */
export function decodeHtmlEntities(text: string): string {
  return text.replace(ENTITY, (whole, body: string) => {
    if (body.startsWith("#")) {
      const hex = body[1] === "x" || body[1] === "X";
      return fromCodePoint(parseInt(body.slice(hex ? 2 : 1), hex ? 16 : 10)) ?? whole;
    }
    return NAMED[body.toLowerCase()] ?? whole;
  });
}

function tidy(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** The notification presentation boundary — call once, on the finished alert, right before the OS. Every line goes
 *  through Higgins Luddish here (the title as a headline), so no alert, whoever composed it, reaches the person in
 *  other words than the app's (the server does the same: services/notification_text.present_push). Nothing is cut
 *  short: only the OS's own display limit ever shortens a notification. */
export function presentAlertText(alert: LocalAlert): LocalAlert {
  return { ...alert, title: luddishText(tidy(decodeHtmlEntities(alert.title)), true), body: luddishText(tidy(decodeHtmlEntities(alert.body))) };
}

// ── The short summary ────────────────────────────────────────────────────────

const NOUN: Partial<Record<PatrolEvent["category"], string>> = {
  link: "link", website: "website", connection: "website", known_threat: "website", message: "text",
  email: "email", call: "call", app: "app", file: "file", account: "account alert",
};
const SENT_TO_CHECK = new Set<string>(["link", "message", "email", "file"]);
const RECEIVED = new Set<string>(["message", "email"]);
const SITES = new Set<string>(["website", "connection", "known_threat"]);
// Recorded identifiers, whole: only the OS's own length limit (presentAlertText) ever shortens a notification.
const named = (value: string | null | undefined): string => (value ?? "").replace(/\s+/g, " ").trim();

/** "The Instagram link you sent", "The email from billing@acme.co", "The paypal-secure.top link you sent",
 *  "The call from +61 412 345 678" — from recorded identifiers only; never guessed. */
export function notificationSubject(event: PatrolEvent): string {
  const noun = NOUN[event.category] ?? "item";
  const brand = named(event.claimed_brand);
  const sender = named(event.source_metadata?.sender);
  const yours = event.background ? (RECEIVED.has(event.category) ? " you received" : "") : (SENT_TO_CHECK.has(event.category) ? " you sent" : "");
  if (event.category === "call") {
    const caller = named(event.local_indicator) || sender;
    return caller ? `The call from ${caller}` : brand ? `The ${brand} call` : "The call";
  }
  if (brand) return `The ${brand} ${noun}${yours}`;
  if (RECEIVED.has(event.category) && sender) return `The ${noun} from ${sender}`;
  if (event.category === "file") {
    const file = named(event.source_metadata?.attachment_names?.find((n) => !!n?.trim()));
    if (file) return `The file ${file}`;
  }
  const host = shortDomain(event.source_metadata?.url ?? event.local_indicator ?? event.indicator_host);
  if (host && event.category === "link") return `The ${host} link${yours}`;
  if (host && SITES.has(event.category)) return `The website ${host}`;
  return `The ${noun}${yours}`;
}

const inSentence = (subject: string) => subject.replace(/^The /, "the ");
const OPEN = "Open ApolloSG to see what I found.";
const OPEN_IN_SENTENCE = "open ApolloSG to see what I found.";

/** The case's own briefing, short: its first finding (which always names its subject) and, when the case owes the
 *  person a decision (caseBriefing.needsYou, as Home and Threats decide it), that it does. Null when the event has no
 *  Higgins Case Briefing. */
function briefingSummary(event: PatrolEvent): string | null {
  const b = briefed(event);
  return b ? `Higgins: ${firstFinding(b)}${needsYou(event) ? " This needs your decision." : ""} ${OPEN}` : null;
}

/** The summary before Luddish: the briefing's first finding, else the subject, the recorded state and the first
 *  concrete thing Apollo recorded about it. Mirror of backend services/notification_text._composed. */
function composed(event: PatrolEvent): string {
  const briefedText = briefingSummary(event);
  if (briefedText) return briefedText;
  const subject = notificationSubject(event);
  const reason = firstReason(event);
  const because = reason ? `: ${reasonInSentence(reason)}` : "";
  switch (event.state) {
    case "biting": return `Higgins: Apollo blocked ${inSentence(subject)}. ${OPEN}`;
    case "barking": return `Higgins: ${subject} looks like a scam${because}. Don't act on it — ${OPEN_IN_SENTENCE}`;
    case "growling": return `Higgins: ${subject} has ${reason ? "a warning sign" : "signs that need checking"}${because}. ${OPEN}`;
    default:
      // A Limited result is never presented as safe.
      return event.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE"
        ? `Higgins: I couldn't fully check ${inSentence(subject)}${because}. Treat it with caution — ${OPEN_IN_SENTENCE}`
        : `Higgins: ${subject} needs a closer look${because}. ${OPEN}`;
  }
}

/** The short, specific notification body for an event, in Higgins Luddish (the server words its pushes the same way). */
export function notificationSummary(event: PatrolEvent): string {
  return luddishText(composed(event));
}

/** The body for "ApolloSG completed an investigation". */
export function completedSummary(event: PatrolEvent): string {
  return luddishText(briefingSummary(event) ?? `Higgins: I've finished checking ${inSentence(notificationSubject(event))}. ${OPEN}`);
}
