// Higgins Luddish L1 — the Evidence Lock for each kind of result ApolloSG shows: a check result worked out on the device,
// a TC Hawkeye / Magnum DI investigation, and a Patrol finding handed to Ask Higgins. Each takes the state and findings
// exactly as recorded; nothing is recomputed or inferred. Pure: type imports only.
import type { CheckResultModel } from "../checkResult.ts";
import type { HigginsIssueContext } from "../higginsHandoff.ts";
import type { HigginsResponse } from "../../investigation/types.ts";
import { lockEvidence, type Basis, type EvidenceLock, type RaisedBy } from "./lock.ts";
import { stateFromAssessment, stateFromOutcome, stateFromPatrol, stateFromTone, type StateId } from "./rules.ts";

const OPEN_STATUSES = new Set(["incomplete", "unavailable", "error", "not_performed", "not_configured"]);

/** A check result worked out on the device (link, message, call, email, file, app, account, device, internet). */
export function lockFromCheckResult(model: CheckResultModel): EvidenceLock {
  return lockEvidence({
    state: stateFromTone(model.tone),
    subject: model.subject,
    headline: model.headline,
    findings: model.items.filter((i) => !OPEN_STATUSES.has(i.status)).map((i) => ({ text: i.finding, basis: "recorded" as Basis, by: "Apollo" })),
    explanation: model.higginsSays,
    uncertainties: model.items.filter((i) => OPEN_STATUSES.has(i.status)).map((i) => `${i.name}: ${i.finding}`),
    actions: model.whatToDo ? [model.whatToDo] : [],
    blockedBy: null,
    by: "Apollo",
    confidence: model.confidence,
  });
}

const BASIS: Record<string, Basis> = { observation: "observed", user_report: "reported", inference: "inferred" };

/** A general question answered from ApolloSG's library or a search (no case outcome and no findings): information,
 *  not a result about anything checked, so there's nothing for the question buttons to explain. */
export const isGeneralAnswer = (response: Pick<HigginsResponse, "outcome" | "findings">): boolean => !response.outcome && !(response.findings ?? []).length;

/** A finished TC Hawkeye or Magnum DI result. A finding's confidence that related history raised keeps where the extra
 *  weight came from (this device's earlier cases or ApolloSG's previous reports), so it never reads as the case's own
 *  evidence; history notes themselves are never findings. */
export function lockFromInvestigation(response: HigginsResponse, by: string): EvidenceLock {
  const raisedBy = (id: string): RaisedBy[] => (response.history ?? [])
    .filter((n) => n.findingIds.includes(id)).map((n) => (n.kind === "related_case" ? "this_device" : "previous_reports"));
  return lockEvidence({
    state: response.outcome ? stateFromOutcome(response.outcome) : stateFromAssessment(response.assessment),
    headline: response.overview,
    findings: (response.findings ?? []).map((f) => ({ text: f.text, basis: BASIS[f.basis] ?? "recorded", confidence: f.confidence ?? null, by, raisedBy: raisedBy(f.id) })),
    reason: response.attentionReason,
    uncertainties: response.uncertainties ?? [],
    actions: (response.actions ?? []).map((a) => a.instruction || a.label).filter(Boolean),
    how: response.scope,
    by,
  });
}

const PROVENANCE: Record<string, Basis> = { observed: "observed", inferred: "inferred", user_reported: "reported" };

/** A Patrol finding, incident or Device Check result handed to Ask Higgins. `state`: the state Apollo recorded on the
 *  case when it isn't the patrol state (a Limited Triage result is "limited", never "safe"). */
export function lockFromIssue(context: HigginsIssueContext, state?: StateId): EvidenceLock {
  return lockEvidence({
    state: state ?? stateFromPatrol(context.assessment_state),
    by: "Apollo",
    headline: context.issue_summary,
    findings: context.findings.map((f) => ({ text: f.summary, basis: PROVENANCE[f.provenance] ?? "recorded", by: "Apollo" })),
    uncertainties: context.uncertainty,
    actions: (context.available_actions ?? []).map((a) => a.instruction || a.label).filter(Boolean),
  });
}
