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

/** The event's words for any screen: its Higgins Case Briefing's when it has one, else what Apollo recorded. */
export function presentEvent(event: PatrolEvent): PresentedEvent {
  const b = briefed(event);
  const incomplete = incompleteOnly(event);
  return {
    title: say(b?.headline ?? (incomplete ? INCOMPLETE_TITLE : event.headline), true),
    summary: say(b?.summary ?? event.what_happened),
    why: (event.why ?? []).map((w) => say(w)).filter(Boolean),
    whatToDo: say(incomplete ? INCOMPLETE_TODO : (b?.recommendedAction?.instruction ?? event.what_to_do), true),
  };
}
