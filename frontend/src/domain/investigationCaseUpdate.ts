// The case must say what the investigation actually found.
//
// The server keeps nothing: a completed investigation is committed to this device and the server copy
// is purged immediately, so the server's patrol projection can only ever carry the "Apollo is
// investigating this" placeholder. Without this, every investigated case stays on that placeholder
// while the real answer sits in device storage — general statements instead of the findings.
//
// This turns the stored result into the case's own content: the overview, the findings, the
// recommended action and the severity the investigation actually reached. Pure and unit-tested.
import type { DeviceInvestigation } from "../investigation/deviceStore";
import { caseResult, eventBriefing } from "./caseBriefing.ts";
import { withEvidenceModel } from "./evidenceModel.ts";
import { INCONCLUSIVE_TODO } from "./luddish/present.ts";
import { handled } from "./patrolStatus.ts";
import { STATE_RANK } from "./stateMachine.ts";
import type { PatrolEvent } from "./types";

/** First sentence of the overview — the specific statement, not a category name. Whole: never cut short. */
export function headlineFrom(overview: string): string {
  const clean = overview.replace(/\s+/g, " ").trim();
  return clean.split(/(?<=[.!?])\s/)[0] ?? clean;
}

/** The overview with its headline sentence removed — the card already shows that sentence as the
 *  title, so repeating it in the body says the same thing twice. Falls back to the full overview
 *  when the conclusion is a single sentence and there is nothing else to show. */
export function bodyFrom(overview: string): string {
  const clean = overview.replace(/\s+/g, " ").trim();
  const [, ...rest] = clean.split(/(?<=[.!?])\s/);
  return rest.join(" ").trim() || clean;
}

const LISTED = /is a known malicious destination|ends at a known malicious host/;
/** A threat established apart from the investigation — a verified block, or a threat list naming its link — which an
 *  answer that doesn't settle it never lowers. */
export function establishedThreat(e: Pick<PatrolEvent, "verified_block" | "triage_investigation" | "why">): boolean {
  return !!e.verified_block || (e.triage_investigation?.rulesMet ?? []).includes("LINK-01") || (e.why ?? []).some((w) => LISTED.test(w));
}

function actionFrom(inv: DeviceInvestigation): string {
  const response = inv.response;
  const actions = response.actions ?? [];
  const recommended = response.recommendedActionId
    ? actions.find((a) => a.id === response.recommendedActionId)
    : undefined;
  const chosen = recommended ?? actions[0];
  if (chosen?.instruction?.trim()) return chosen.instruction.trim();
  // A safe assessment means no concern was found within what was checked — it is NOT a guarantee and
  // NOT administrative closure. The person should know what was covered and that what wasn't covered
  // could still matter. Never say "nothing to do" as if closure is a safety determination.
  if (response.assessment === "no_concern_found_within_scope")
    return "No concern was found in what Apollo checked. If anything about it changes or you receive a follow-up, check again.";
  return "Review the findings above and verify anything you are unsure of directly with the organisation.";
}

/** The patch that makes an event carry its investigation's actual result, or null when there is
 *  nothing to change (no stored response, or the event already carries this revision). */
export function investigationPatch(event: PatrolEvent, inv: DeviceInvestigation | null): PatrolEvent | null {
  const response = inv?.response;
  if (!inv || !response || !response.overview?.trim()) return null;
  if (event.resolved_at && event.status === "trusted") return null;
  // The case's own words come from its Higgins Case Briefing when it has one: the headline names the organisation
  // and what was checked, the summary keeps every material subject, and each finding keeps its subject.
  const briefing = eventBriefing(response);
  const fromBriefing = briefing?.from === "briefing" && !!briefing.headline && !!briefing.summary;
  const findings = (fromBriefing ? briefing!.findings : (response.findings ?? []).map((f) => f.text.trim())).filter(Boolean).slice(0, 6);
  const overview = response.overview.replace(/\s+/g, " ").trim();
  // The case's severity is the case result's — the same one the Findings Brief shows — never worked out again here.
  // An investigation that couldn't decide, with nothing concrete left to act on, is filed as not fully checked
  // (caseResult.notFullyChecked); a threat established apart from it is never lowered.
  const result = caseResult(response);
  const established = establishedThreat(event);
  const notFullyChecked = result.notFullyChecked && !established;
  const state = result.notFullyChecked && established && STATE_RANK[event.state] > STATE_RANK[result.severity] ? event.state : result.severity;
  const closes = result.noConcern || notFullyChecked;
  const whatToDo = notFullyChecked ? INCONCLUSIVE_TODO
    : fromBriefing && briefing!.recommendedAction?.instruction ? briefing!.recommendedAction.instruction : actionFrom(inv);
  const headline = fromBriefing ? briefing!.headline : headlineFrom(overview);
  const whatHappened = fromBriefing ? briefing!.summary : bodyFrom(overview);
  // What couldn't be established, when it couldn't decide; else its findings.
  const why = notFullyChecked && (response.uncertainties ?? []).length ? response.uncertainties.map((u) => u.trim()).filter(Boolean) : findings;
  const outcome = result.verdictCode ?? null;

  // Already applied — same findings and same conclusion, so nothing to write.
  const unchanged = event.headline === headline
    && event.what_happened === whatHappened
    && JSON.stringify(event.why ?? []) === JSON.stringify(why)
    && event.what_to_do === whatToDo
    && event.state === state
    && (event.investigation_outcome ?? null) === outcome
    && event.investigation_completed_at === inv.committedAt
    && (event.investigation_answered_by ?? null) === (inv.answeredBy ?? event.investigation_answered_by ?? null)
    && !!event.investigation_simulated === !!(inv.simulated || event.investigation_simulated)
    && JSON.stringify(event.case_briefing ?? null) === JSON.stringify(briefing);
  if (unchanged) return null;

  // A record the person handled or trusted stays as they left it: an investigation's answer never reopens it.
  const kept = handled(event) || event.status === "blocked";
  return {
    ...withEvidenceModel(event),
    state,
    // A finished investigation leaves the case open unless it found nothing at all, or couldn't decide with nothing
    // concrete left to act on.
    status: kept ? event.status : closes ? "resolved" : "active",
    resolved_at: kept ? event.resolved_at : closes ? event.resolved_at ?? inv.committedAt : null,
    headline,
    what_happened: whatHappened,
    why: why.length ? why : event.why,
    what_to_do: whatToDo,
    investigation_outcome: outcome,
    // The result is now held in full on this device. What supplied the evidence, and where the case began, never
    // change because an investigation answered.
    evidence_representation: "full_record",
    investigation_case_id: event.investigation_case_id ?? inv.caseId,
    // The investigation has answered — the case is no longer "investigating".
    investigation_completed_at: inv.committedAt,
    // Who settled it (TC Hawkeye or Magnum DI), when the committed result recorded it — never guessed.
    investigation_answered_by: inv.answeredBy ?? event.investigation_answered_by ?? null,
    // Tagged when an outside source behind it was simulated in the preview — never untagged once it was.
    ...(inv.simulated || event.investigation_simulated ? { investigation_simulated: true } : {}),
    // The same briefing Home, Threats and notifications project (device-local, never synced).
    case_briefing: briefing,
  };
}
