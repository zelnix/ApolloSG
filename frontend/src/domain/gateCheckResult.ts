// Presentation of a recorded Gate result, never a new investigation verdict or proof of authenticity.
import type { PatrolEvent } from "./types";
import type { Report } from "./reportSections";
import { NATIVE_PROTECTION_PROVENANCE } from "./nativeClassification.ts";

export function gateCheckResult(event: PatrolEvent): { label: string; report: Report } | null {
  const record = event.triage_investigation;
  if (!record || !["email", "message"].includes(event.category)
    || event.case_briefing || event.investigation_case_id || event.patrol_record?.investigationCaseId
    || event.investigation_completed_at || !record.rulesChecked.length
    || event.verified_block || event.evidence_provenance === NATIVE_PROTECTION_PROVENANCE
    || record.outcome !== "NO_THREAT_IDENTIFIED" || record.rulesMet.length
    // A separately recorded malicious destination or deceptive displayed link must remain actionable.
    || event.why?.some((line) => /is a known malicious destination|ends at a known malicious host|^Displayed link says /i.test(line))) return null;
  return {
    label: "No threat identified by available checks",
    report: {
      answer: ["The recorded automatic checks found no matching warning signs. This is not a finding that the message is genuine."],
      found: [{ text: `Checked ${record.rulesChecked.length} of ${record.rulesApplicable.length} applicable rules; none matched.`, detail: null }],
      means: ["No TC Hawkeye or Magnum DI investigation was opened for this check. If the message concerns your account, review it through the service’s official app or a known address."],
      uncertain: ["Visible sender details and message wording alone do not establish authenticity.",
        ...(record.incompleteChecks?.length ? ["Some checks could not finish; see DI for the recorded coverage limits."] : [])],
      how: ["This summary uses the recorded Gate checks. It does not add a new investigation or change the preserved source."],
      more: [], sources: [],
    },
  };
}
