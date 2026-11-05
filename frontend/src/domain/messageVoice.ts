// Apollo's single message voice (standing requirement). ONE place that turns internal codes into
// plain, evidence-based English so no screen, notification or history ever shows a developer identifier
// (known_threat, ears_up, server_projection_of_recorded_outcome, user_started …) or a vague
// "Something changed". Every helper answers part of: What happened · Where · Why it matters ·
// What Apollo is doing · What to do · Where to go. Pure and unit-tested.
import type { ApolloState, EventCategory, PatrolDisplayState } from "./types";

// --- Where did it happen? (the security area, in plain words) ----------------------------------------
const AREA: Record<EventCategory, string> = {
  link: "a link you checked",
  website: "a website safety check",
  known_threat: "a website safety check",
  protection: "Apollo's protection",
  connection: "your network connection",
  system: "this device",
  device: "this device",
  message: "a text message",
  call: "a phone call",
  app: "an app",
  account: "an online account",
  email: "an email",
  file: "a file",
  family: "a family alert",
};
export function areaLabel(category: EventCategory | string): string {
  return AREA[category as EventCategory] ?? "a security check";
}

// --- What is Apollo doing? (never overstate — "blocked" only with verified enforcement) --------------
export function apolloStatusLabel(state: ApolloState, opts: { verifiedBlock?: boolean; resolved?: boolean; active?: boolean } = {}): string {
  if (state === "biting") return opts.verifiedBlock ? (opts.resolved ? "Threat stopped and contained" : "Threat stopped") : "Flagged for your attention";
  if (opts.resolved) return "Resolved";
  switch (state) {
    case "resting": return "No concern found";
    case "ears_up": return "Worth a look";
    case "growling": return "Being checked";
    case "barking": return "Needs your attention";
    default: return "Checked";
  }
}

// --- Short result chip (replaces "Something changed") ------------------------------------------------
export function resultChip(state: ApolloState, resolved = false): string {
  if (resolved) return "Resolved";
  switch (state) {
    case "resting": return "No concern found";
    case "ears_up": return "Worth a look";
    case "growling": return "Worth checking";
    case "barking": return "Needs your attention";
    case "biting": return "Threat stopped";
    default: return "Checked";
  }
}

// --- Who/what started it (replaces "user started", "higgins", raw source codes) ----------------------
export function sourceLabel(source: string): string {
  switch (source) {
    case "user_started": return "Started by you";
    case "background": return "Checked automatically in the background";
    case "higgins": return "From a Higgins investigation";
    case "family": return "From a family alert";
    default: return "ApolloSG";
  }
}

// --- Synced cross-device state (replaces raw effectiveState codes in timelines) ----------------------
const DISPLAY_STATE: Record<PatrolDisplayState, string> = {
  safe: "no concern found", monitoring: "being watched", warning: "worth checking",
  danger: "needs attention", blocked: "threat stopped", resolved: "resolved", unknown: "checked",
};
export function displayStateLabel(state: PatrolDisplayState | string): string {
  return DISPLAY_STATE[state as PatrolDisplayState] ?? "checked";
}

/** A code-looking reason (snake_case, no spaces — e.g. "server_projection_of_recorded_outcome") must
 *  never reach the user. Replace it with an honest, state-based sentence; keep genuine prose as-is. */
export function humanizeReason(reason: string | null | undefined, state: ApolloState): string {
  const text = (reason ?? "").trim();
  const looksLikeCode = !!text && !/\s/.test(text) && /^[a-z0-9]+(?:_[a-z0-9]+)+$/i.test(text);
  if (!text || looksLikeCode) {
    switch (state) {
      case "biting": return "A verified enforcement record confirms Apollo blocked supported traffic.";
      case "barking": return "Apollo recorded something that needs your attention.";
      case "growling":
      case "ears_up": return "Apollo recorded something worth a closer look.";
      case "resting": return "This check finished with no known concern in its scope.";
      default: return "Apollo recorded the outcome of this check.";
    }
  }
  return text;
}

// --- The projected (synced) event text, in plain English, with no detail leaked (privacy preserved) --
// Used both on the wire (privacy.ts) and when a synced-back event is displayed. It tells the person what the check
// was and what Apollo found at a high level. It never says where a copy is kept: the case is this device's own.
export interface ProjectedVoice { headline: string; whatHappened: string; why: string; whatToDo: string }
export const PRIVACY_SUMMARY_WHY = "ApolloSG's servers keep only this privacy-protected summary, not the content that was checked.";
export function projectedEventVoice(category: EventCategory | string, state: ApolloState, verifiedBlock: boolean): ProjectedVoice {
  if (verifiedBlock) return {
    headline: "Apollo blocked a connection it had flagged",
    whatHappened: "Apollo blocked a connection on your device that it had flagged as a threat.",
    why: "Packet-backed enforcement evidence is attached.",
    whatToDo: "No action needed — the block is confirmed.",
  };
  const area = areaLabel(category);
  const headline = `ApolloSG ran ${area}`;
  if (state === "barking") return {
    headline,
    whatHappened: `Apollo checked ${area} and found something that needs your attention.`,
    why: PRIVACY_SUMMARY_WHY,
    whatToDo: "Don't tap links, reply, call back or pay until you've confirmed it through a contact you already trust.",
  };
  if (state === "growling" || state === "ears_up") return {
    headline,
    whatHappened: `Apollo checked ${area} and found something worth a closer look.`,
    why: PRIVACY_SUMMARY_WHY,
    whatToDo: "Treat it with care until you've confirmed it through a contact you already trust.",
  };
  return {
    headline,
    whatHappened: `Apollo checked ${area} and found no concern.`,
    why: PRIVACY_SUMMARY_WHY,
    whatToDo: "No action needed. A past check doesn't confirm current safety.",
  };
}

const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** True when a string still carries an internal identifier the user should never see. */
export function looksLikeInternalCode(text: string): boolean {
  return /\b(known_threat|ears_up|user_started|server_projection|recorded_outcome|[a-z]+_[a-z]+(?:_[a-z]+)+)\b/.test(text);
}

/** @deprecated hasLegacyJargon removed per P1 directive — cosmetic UI masking must not replace
 *  root data fixes. The merge layer (ApolloContext) now preserves local findings so projected
 *  server text never overwrites real content Apollo recorded for the case. Callers should show
 *  actual data or mark incomplete records honestly. Do not re-add. */

// --- Live scrubber for Higgins' free-text replies (Scan Gate Chat) -----------------------------------
// Higgins' overview/explanation/findings come from the model and could echo an internal token. This is
// the last line of defence: it rewrites any code token to plain English before it reaches the user, and
// in dev it warns so the leak gets fixed at the source too.
const CODE_REPLACEMENTS: Record<string, string> = {
  known_threat: "website safety", ears_up: "worth a look", user_started: "started by you",
  server_projection_of_recorded_outcome: "privacy-protected summary", recorded_outcome: "recorded outcome",
  action_needed: "action needed", no_concern_found_within_scope: "no concern found in the checks performed",
  concern_found: "concern found", off_by_choice: "turned off", not_activated: "not set up yet",
  permission_needed: "permission needed", setup_needed: "setup needed", temporarily_unavailable: "temporarily unavailable",
};
export function scrubMessage(text: string | null | undefined): string {
  if (!text) return text ?? "";
  let flagged = false;
  const out = text.replace(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g, (m) => { flagged = true; return CODE_REPLACEMENTS[m] ?? m.replace(/_/g, " "); });
  if (flagged && typeof (globalThis as { __DEV__?: boolean }).__DEV__ !== "undefined" && (globalThis as { __DEV__?: boolean }).__DEV__) {
    console.warn(`[Apollo message guardrail] scrubbed an internal code from a Higgins reply: "${text}"`);
  }
  return out;
}

// --- Investigation status history (History Everywhere) -----------------------------------------------
/** TC FlyBy settled the result (the case's `answeredBy` is "tc_flyby_*"): the one place this is decided on this device.
 *  Results saved on a phone before TC FlyBy's rename carry its old prefix, "teddy_*", and still count as TC FlyBy's. */
const FLYBY_PREFIXES = ["tc_flyby", "teddy"];
export function settledByFlyby(answeredBy: string | null | undefined): boolean {
  return FLYBY_PREFIXES.some((prefix) => (answeredBy ?? "").startsWith(prefix));
}

/** Who settled an investigation result, by name (the case's `answeredBy`). Results recorded before
 *  routing existed were Magnum DI's. */
export function investigatorName(answeredBy: string | null | undefined): "TC FlyBy" | "Magnum DI" {
  return settledByFlyby(answeredBy) ? "TC FlyBy" : "Magnum DI";
}

/** Plain-English "what has been done so far", derived from the turns and current phase, credited to whichever
 *  investigator settled the result. Only Magnum DI asks questions or requests a device reading. */
export function investigationHistory(args: {
  turns: { question: string; overview: string }[]; phase: string; completion?: string | null; answeredBy?: string | null;
}): HistoryEntry[] {
  const name = investigatorName(args.answeredBy);
  const entries: { text: string }[] = [{ text: "ApolloSG opened this investigation." }];
  args.turns.forEach((t, i) => { if (i > 0 || args.turns.length > 1) entries.push({ text: `You asked a follow-up — ${name} answered: ${scrubMessage(t.overview)}` }); });
  const current = args.phase === "working" || args.phase === "creating" || args.phase === "reconnecting" ? "Apollo is still investigating."
    : args.phase === "waiting_user" ? "Magnum DI is waiting on your answer to continue."
    : args.phase === "waiting_device" ? "Magnum DI is checking this device for a fresh observation."
    : args.phase === "failed" || args.phase === "expired" ? "This investigation stopped before finishing."
    : args.completion === "complete" ? `${name} completed the investigation within scope.`
    : args.completion === "partial" ? `${name} answered, with more still to examine.`
    : "Magnum DI has a question before it can finish.";
  entries.push({ text: current });
  return entries.map((e) => ({ at: "", text: e.text }));
}

// --- Higgins investigation verdicts (plain English, never raw enum values) ---------------------------
export function assessmentLabel(assessment: string): string {
  switch (assessment) {
    case "concern_found": return "Suspicious indicators found";
    case "no_concern_found_within_scope": return "No concerns found in the checks performed";
    case "uncertain": return "Apollo couldn't fully determine the risk";
    default: return "Checked";
  }
}
export function attentionLabel(attention: string): string {
  switch (attention) {
    case "none": return "No action needed";
    case "review": return "Worth a review";
    case "action_needed": return "Action needed";
    case "urgent": return "Needs attention now";
    default: return "Review";
  }
}

/** Apollo's case outcome, as the person sees it. Null/unknown (a general question) shows no label. */
export function outcomeLabel(outcome: string | null | undefined): string | null {
  switch (outcome) {
    case "no_scam_indicators": return "This appears safe and legitimate";
    case "concerning": return "This is suspicious — exercise caution";
    case "likely_scam": return "This is a scam — do not engage";
    case "confirmed_threat": return "This is a confirmed scam or threat";
    case "unable_to_determine": return "Apollo couldn't fully determine the risk";
    default: return null;
  }
}

export function outcomeTone(outcome: string | null | undefined): "barking" | "ears_up" | "sniffing" | "resting" {
  if (outcome === "confirmed_threat" || outcome === "likely_scam") return "barking";
  if (outcome === "concerning") return "ears_up";
  if (outcome === "unable_to_determine") return "sniffing";
  return "resting";
}

// --- Plain-English status history for an event detail screen (Status Timeline) -----------------------
export interface HistoryEntry { at: string; text: string }
/** Builds a human-readable history from the event's own facts plus any synced revisions. Never shows a
 *  code; a revision summary that still looks like a code is replaced by a state-based sentence. */
export function eventHistory(
  e: { category: EventCategory | string; state: ApolloState; occurred_at: string; resolved_at?: string | null; verified_block?: boolean | null },
  revisions: { occurredAt: string; effectiveState: PatrolDisplayState | string; summary: string; revision: number }[] = [],
): HistoryEntry[] {
  const area = areaLabel(e.category);
  const entries: HistoryEntry[] = [{ at: e.occurred_at, text: `ApolloSG ran ${area} and ${e.verified_block ? "blocked a connection it had flagged" : apolloStatusLabel(e.state, {}).toLowerCase()}.` }];
  for (const r of revisions) {
    const summary = r.summary && !looksLikeInternalCode(r.summary) ? r.summary : `now ${displayStateLabel(r.effectiveState)}`;
    entries.push({ at: r.occurredAt, text: `Update: ${summary}.` });
  }
  if (e.resolved_at) entries.push({ at: e.resolved_at, text: "Apollo marked this resolved." });
  return entries.sort((a, b) => a.at.localeCompare(b.at));
}
