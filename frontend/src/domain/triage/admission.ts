// An intake/routing decision from the recorded flags and evidence limits, never a scam Finding.
import { RULES_BY_ID, type TriageInvestigationRecord } from "./contract.ts";

export function triageAdmission(record: TriageInvestigationRecord) {
  const flags = record.rulesMet.map((id) => record.rules.find((r) => r.ruleId === id)?.title ?? RULES_BY_ID[id]?.title ?? "Recorded warning flag");
  const incomplete = !record.rulesChecked.length || !!record.incompleteChecks?.length || !!record.coverageGaps.length
    || record.outcome === "LIMITED_UNABLE_TO_DETERMINE" || record.rulesChecked.length < record.rulesApplicable.length;
  const decision = flags.length ? "investigate" : incomplete ? "insufficient_evidence" : "no_flags";
  return {
    decision, flags, incomplete,
    label: flags.length ? "Investigation warranted" : incomplete ? "Not fully checked" : "No warning flags found",
    reason: flags.length ? `${flags.length} recorded warning flag${flags.length === 1 ? " warrants" : "s warrant"} an investigation by TC Hawkeye.`
      : incomplete ? "No warning flags were recorded, but missing evidence or unfinished checks prevent a complete assessment."
      : "No warning flags were recorded in the supplied material, so this screening did not request an investigation.",
  } as const;
}
