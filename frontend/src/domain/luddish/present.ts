// The shared Higgins Luddish presentation contract for a Patrol event. Home, Threats, alerts, triage history and the
// Threat Case show an event's words ONLY through here — never its stored headline, summary, reasons or next step
// directly. Each line goes through Higgins Luddish (a line whose plain wording would change anything keeps Apollo's
// words), internal codes are removed, and a Triage record's codes become plain words. Words quoted from the source
// (a sender, a subject, the message itself) are identifiers, not Apollo's wording: they are shown as recorded and
// never pass through here. Pure: no React, unit-tested in node.
import { briefed } from "../caseBriefing.ts";
import { looksLikeInternalCode, scrubMessage } from "../messageVoice.ts";
import { plainTriageText } from "../triage/contract.ts";
import type { PatrolEvent } from "../types";
import { luddishText } from "./index.ts";

export interface PresentedEvent {
  title: string;
  summary: string;
  why: string[];
  whatToDo: string;
}

const clean = (text: string | null | undefined) => (text ?? "").replace(/\s+/g, " ").trim();

/** One of Apollo's lines about an event, in Luddish. Empty when there is nothing a person should see.
 *  `strong`: a headline or a step of what to do, which keeps every "not" in full. */
export function say(text: string | null | undefined, strong = false): string {
  const plain = scrubMessage(plainTriageText(clean(text)));
  return plain && !looksLikeInternalCode(plain) ? luddishText(plain, strong) : "";
}

/** A Limited Triage result that rests only on checks that couldn't run — a lookup that didn't answer, headers that
 *  weren't available — with nothing concerning behind it. That is an incomplete check, never a detected threat.
 *  Mirror of backend services/triage/store.py incomplete_only. */
export function incompleteOnly(event: Pick<PatrolEvent, "triage_investigation" | "investigation_case_id">): boolean {
  const t = event.triage_investigation;
  return !event.investigation_case_id && t?.outcome === "LIMITED_UNABLE_TO_DETERMINE"
    && !(t.coverageGaps ?? []).some((g) => g.code === "INSUFFICIENT_EVIDENCE");
}

export const INCOMPLETE_TITLE = "Not every check could run";
export const INCOMPLETE_TODO = "Nothing found to act on. Because some checks couldn't run, this isn't a confirmation that it's safe.";
/** An investigation that couldn't decide either way, with no concrete actionable concern left (backend
 *  services/investigation_projector.NOT_FULLY_CHECKED_TODO, word for word). */
export const INCONCLUSIVE_TODO = "Nothing found to act on. This isn't confirmation that it's safe.";
export const REJUDGED_LINE = "Apollo checked this again under its updated rules, using the original kept on this device.";

/** An investigation that ended without deciding, filed as not fully checked: no warning and no alert (its result
 *  says so — caseBriefing.caseResult notFullyChecked — and nothing established apart from it, a verified block or a
 *  listed link, keeps it raised). */
export function inconclusive(event: Pick<PatrolEvent, "investigation_outcome" | "state" | "case_briefing">): boolean {
  if (event.state !== "resting") return false;
  return event.case_briefing ? !!event.case_briefing.notFullyChecked : event.investigation_outcome === "unable_to_determine";
}

/** Not every check could run, or the investigation couldn't decide either way: never a detected threat, never safe. */
export function notFullyChecked(event: Pick<PatrolEvent, "triage_investigation" | "investigation_case_id" | "investigation_outcome" | "state" | "case_briefing">): boolean {
  return incompleteOnly(event) || inconclusive(event);
}

// Lines a record carries that say how it was kept or checked, never what was found (backend patrol_policy.SUMMARY_WHY
// and the investigation placeholder, word for word).
const NOT_A_REASON = new Set([
  REJUDGED_LINE,
  "ApolloSG's servers keep only this privacy-protected summary, not the content that was checked.",
  "The investigation is still running.",
]);

// The ordinary words a reason starts with. Anything else (a name: "PhishTank lists …", "Google Safe Browsing …") keeps
// its capital inside a sentence.
const ORDINARY_START = /^(?:The|This|That|These|Those|A|An|It|Its|Their|There|One|Some|No|Nothing|Someone|Asks|Uses|Claims|Says|Contains|Links|Sends|Comes|Pretends|Wants|Mentions|Offers|Promises|Threatens|Requests|Tells|Gives|Points|Goes|Leads|Looks|Has|Is|Was|Matches|Names|Shows|Appears)\b/;

/** A reason inside a sentence ("…, asks for a one-time code"): no closing stop, and its first word lower-cased only
 *  when it is an ordinary word, never a name. Mirror: backend services/notification_text._in_sentence. */
export function reasonInSentence(reason: string): string {
  const r = reason.replace(/[.!?…]+$/, "").trim();
  return ORDINARY_START.test(r) ? r[0].toLowerCase() + r.slice(1) : r;
}

/** The first concrete thing Apollo recorded about the event — a rule it met, a finding — in Luddish; null when it
 *  recorded none. Home and notifications name this instead of a posture ("a possible threat", "be careful"). */
export function firstReason(event: Pick<PatrolEvent, "why">): string | null {
  const raw = (event.why ?? []).find((w) => clean(w) && !NOT_A_REASON.has(clean(w)));
  return raw ? say(raw) || null : null;
}

/** The event's words for any screen: its Higgins Case Briefing's when it has one, else what Apollo recorded. */
export function presentEvent(event: PatrolEvent): PresentedEvent {
  const b = briefed(event);
  const incomplete = incompleteOnly(event);
  return {
    title: say(b?.headline ?? (incomplete ? INCOMPLETE_TITLE : event.headline), true),
    summary: say(b?.summary ?? event.what_happened),
    why: (event.why ?? []).map((w) => say(w)).filter(Boolean),
    whatToDo: say(incomplete ? INCOMPLETE_TODO : inconclusive(event) ? INCONCLUSIVE_TODO : (b?.recommendedAction?.instruction ?? event.what_to_do), true),
  };
}
