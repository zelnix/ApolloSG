import { caseCardText, needsYou } from "./caseBriefing.ts";
import { STATE_RANK } from "./stateMachine.ts";
import { humanizeReason, resultChip } from "./messageVoice.ts";
import { inconclusive, incompleteOnly, notFullyChecked, presentEvent } from "./luddish/present.ts";
import type { UserAction } from "./userActions.ts";
import type { ApolloState, PatrolEvent } from "./types.ts";

export type PatrolCategory = "site" | "link" | "text" | "call" | "file" | "app" | "network" | "account" | "email" | "device" | "investigation" | "family";
export type PatrolSource = "background" | "user_started" | "higgins" | "family";
export type PatrolFilter = "all_activity" | "needs_you" | "warnings" | "threats_stopped" | "resolved";
export type PatrolState = Exclude<ApolloState, "sniffing">;
export interface PatrolOutcome {
  outcomeId: string; category: PatrolCategory; state: PatrolState; title: string; summary: string; occurredAt: string; source: PatrolSource;
  repeatCount: number; result: string; resultBasis: string; whyThisRating: string[]; whatToDo: string; primaryAction?: UserAction; secondaryActions: UserAction[]; event: PatrolEvent;
}

const WINDOW_MS = 4 * 60 * 60 * 1000;
const COMMAND_TEXT = /\b(requested|request submitted|queue|worker|retry|heartbeat|diagnostic|command)\b/i;
const safeKey = (value: string | null | undefined) => (value ?? "").toLowerCase().replace(/[^a-z0-9.-]/g, "").slice(0, 160);

export function isConsumerPatrolEvent(event: PatrolEvent): boolean {
  if (event.category === "system") return false;
  if (event.category === "protection") return false; // Gate/protection items belong on Protection tab only
  if (COMMAND_TEXT.test(event.headline) && !event.verified_block) return false;
  // Retrofit: exclude records classified as protection/infrastructure issues from the Threats feed
  const rc = event.patrol_record?.recordClass;
  if (rc === "protection_issue" || rc === "reduced_protection" || rc === "diagnostic_result" || rc === "informational") return false;
  return !!event.headline.trim() && !!event.what_happened.trim();
}
const category = (event: PatrolEvent): PatrolCategory => event.investigation_case_id ? "investigation" : event.category === "website" || event.category === "known_threat" || event.category === "protection" ? "site" : event.category === "message" ? "text" : event.category === "connection" ? "network" : event.category === "system" ? "device" : event.category;
const source = (event: PatrolEvent): PatrolSource => event.category === "family" ? "family" : event.investigation_case_id ? "higgins" : event.background ? "background" : "user_started";
const result = (state: PatrolState): string => resultChip(state);
const investigationTitle = (event: PatrolEvent, state: PatrolState): string =>
  state === "resting" ? "Higgins found no remaining concern"
  : state === "biting" ? "Higgins confirmed a threat was stopped"
  : presentEvent(event).title
    || (state === "barking" ? "Higgins found something that needs your attention" : "Higgins found something worth a look");
// A case with a Higgins Case Briefing is titled by its headline ("Stoko email checked"), never a generic line. Every
// title is read through the shared Luddish contract (luddish/present.ts).
const title = (event: PatrolEvent, state: PatrolState) => state === "biting" ? "Apollo stopped a threat"
  : event.investigation_case_id && !caseCardText(event, "").summary ? investigationTitle(event, state)
  : presentEvent(event).title;
const incidentKey = (event: PatrolEvent, state: PatrolState) => event.patrol_record?.logicalIssueKey ?? `${category(event)}:${safeKey(event.scent_id || event.investigation_case_id || event.indicator_digest || event.indicator_host || event.claimed_brand || event.scenario || event.event_id)}:${state}`;
const actionFor = (event: PatrolEvent, state: PatrolState): UserAction | undefined => event.investigation_case_id ? { id: "continue_case", label: "Open investigation" } : state === "growling" || state === "barking" ? { id: "start_investigation", label: "Ask Higgins to investigate" } : state === "biting" ? { id: "open_check_it", label: "Review what was stopped" } : undefined;

export function projectPatrolOutcomes(events: PatrolEvent[]): PatrolOutcome[] {
  const sorted = events.filter(isConsumerPatrolEvent).sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));
  const outcomes: PatrolOutcome[] = [];
  for (const event of sorted) {
    // RELIABILITY FIX: When the user has resolved/trusted an event, the display state must
    // reflect that — not the original threat level. The raw event.state is preserved for history,
    // but the OUTCOME state must show the event as handled so it leaves "Needs you" and enters "Resolved".
    const isResolved = event.status === "resolved" || event.status === "trusted" || !!event.resolved_at || notFullyChecked(event);
    const shown = presentEvent(event);
    const rawState: PatrolState = event.state === "sniffing" ? "ears_up" : event.state === "biting" && !event.verified_block ? "barking" : event.state;
    const state: PatrolState = isResolved ? "resting" : rawState;
    const key = incidentKey(event, state); const time = Date.parse(event.occurred_at);
    const existing = outcomes.find((outcome) => outcome.outcomeId === key && Math.abs(Date.parse(outcome.occurredAt) - time) <= WINDOW_MS);
    if (!existing) {
      outcomes.push({ outcomeId: key, category: category(event), state, title: title(event, state), summary: shown.summary, occurredAt: event.occurred_at, source: source(event), repeatCount: 1,
        result: notFullyChecked(event) ? "Not Fully Investigated" : isResolved ? (event.status === "trusted" ? "Trusted" : "Handled") : result(state),
        resultBasis: incompleteOnly(event) ? "Some checks couldn't run. Nothing found to act on." : inconclusive(event) ? "Apollo couldn't decide either way. Nothing found to act on." : isResolved ? (event.status === "trusted" ? "You trusted this exact item." : "You marked this event as handled.") : humanizeReason(event.patrol_record?.effectiveReason, state),
        whyThisRating: shown.why.slice(0, 4), whatToDo: shown.whatToDo, primaryAction: isResolved ? undefined : actionFor(event, state), secondaryActions: [], event });
      continue;
    }
    existing.repeatCount += 1;
    if (STATE_RANK[state] > STATE_RANK[existing.state]) existing.state = state;
  }
  return outcomes;
}

export function matchesPatrolFilter(outcome: PatrolOutcome, filter: PatrolFilter): boolean {
  if (filter === "all_activity") return true;
  // Only a case that owes the person a decision, with its concrete reason (caseBriefing.needsYou).
  if (filter === "needs_you") return outcome.state !== "resting" && !!outcome.primaryAction && needsYou(outcome.event);
  if (filter === "warnings") return ["ears_up", "growling", "barking"].includes(outcome.state);
  if (filter === "threats_stopped") return outcome.state === "biting" && outcome.event.verified_block;
  return outcome.state === "resting" || outcome.event.status === "resolved" || outcome.event.status === "trusted";
}

/** UX-06: plain-English answer to "do I need to act?", derived from existing outcome state only.
 *  Priority: things that need the person → concerns Apollo is still tracking → nothing. Never claims
 *  "all clear"/"fully protected"/"no threats exist". */
export function patrolConsumerSummary(outcomes: PatrolOutcome[]): string {
  const needsYou = outcomes.filter((outcome) => matchesPatrolFilter(outcome, "needs_you")).length;
  if (needsYou > 0) return needsYou === 1 ? "1 thing needs you" : `${needsYou} things need you`;
  const checking = outcomes.filter((outcome) => outcome.event.status === "active" && ["ears_up", "growling", "barking"].includes(outcome.state)).length;
  if (checking > 0) return checking === 1 ? "Apollo is checking 1 concern" : `Apollo is checking ${checking} concerns`;
  return "Nothing needs you right now";
}