import type { ApolloState, PatrolEvent, PatrolRecord } from "./types";

const APOLLO_STATE: Record<PatrolRecord["effectiveState"], ApolloState> = {
  safe: "resting", resolved: "resting", monitoring: "ears_up", warning: "growling", danger: "barking", blocked: "biting", unknown: "ears_up",
};
const RECORDED: ReadonlySet<string> = new Set<ApolloState>(["sniffing", "resting", "ears_up", "growling", "barking"]);

/** The state a record is shown in. A record the person closed keeps the state it was closed in ("resolved" says only
 *  that it is closed), so a case they handled reads "Handled", never "No threat". A Biting claim is never restored:
 *  only a fresh verified block is Biting. */
function shownState(record: PatrolRecord): ApolloState {
  if (record.effectiveState !== "resolved") return APOLLO_STATE[record.effectiveState];
  if (record.rawState === "biting") return "barking";
  return RECORDED.has(record.rawState) ? (record.rawState as ApolloState) : "resting";
}

export function patrolRecordToEvent(record: PatrolRecord): PatrolEvent {
  const source = record.event;
  return {
    ...source,
    event_id: record.sourceEventId,
    state: shownState(record),
    headline: record.headline,
    what_happened: record.summary,
    verified_block: record.effectiveState === "blocked" && !!record.observedBlockReference,
    occurred_at: record.occurredAt,
    investigation_case_id: record.investigationCaseId,
    patrol_record: record,
  };
}
