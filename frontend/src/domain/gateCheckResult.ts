// Source-specific presentation of intake and recorded Gate checks. It never creates an investigation Finding.
import type { PatrolEvent } from "./types";
import type { Report } from "./reportSections";
import type { OriginalSource } from "../store/originalSource";
import { NATIVE_PROTECTION_PROVENANCE } from "./nativeClassification.ts";
import { emailRecord } from "./emailRecord.ts";
import { describeArtefact } from "./evidencePresentation.ts";
import { triageAdmission } from "./triage/admission.ts";
import { triageShortfalls, shortfallLine } from "./caseFacts.ts";
import { sentences } from "./luddish/patterns.ts";
import { redactInvestigationSecrets } from "./privacy.ts";

export function gateCheckResult(event: PatrolEvent, original?: OriginalSource | null) {
  const record = event.triage_investigation;
  if (!record || !["email", "message"].includes(event.category)
    || event.case_briefing || event.investigation_case_id || event.patrol_record?.investigationCaseId
    || event.investigation_completed_at
    || event.verified_block || event.evidence_provenance === NATIVE_PROTECTION_PROVENANCE
    || event.why?.some((line) => /is a known malicious destination|ends at a known malicious host|^Displayed link says /i.test(line))) return null;
  const admission = triageAdmission(record);
  const email = emailRecord(event, original);
  const body = original ? describeArtefact(original, false).body : event.source_metadata?.preview ?? null;
  const excerpt = body ? sentences(redactInvestigationSecrets(body)).slice(0, 2).join(" ") : null;
  const item = email.subject ? `the email “${email.subject}”` : event.category === "email" ? "this email" : "this message";
  const found: Report["found"] = [
    ...(email.sender ? [{ text: `Visible sender: ${email.sender}. This is what the source shows; it does not authenticate the sender.`, detail: null }] : []),
    ...(excerpt ? [{ text: `The ${event.category === "email" ? "email" : "message"} says: “${excerpt}”`, detail: original ? "Read from the original retained on this device." : "Read from the recorded intake excerpt; this may not be the full message." }] : []),
    ...admission.flags.map((flag) => ({ text: `Recorded warning flag: ${flag}`, detail: "This warrants investigation; it is not a final scam Finding." })),
    { text: `Screened ${record.rulesChecked.length} of ${record.rulesApplicable.length} applicable warning-sign rules for ${item}; ${admission.flags.length ? `${admission.flags.length} matched` : "none matched"}.`, detail: null },
  ];
  const shortfalls = triageShortfalls(record).map(shortfallLine);
  const report: Report = {
    answer: [`For ${item}, ${admission.reason.charAt(0).toLowerCase()}${admission.reason.slice(1)}`],
    found,
    means: [admission.decision === "investigate" ? "TC Hawkeye investigation is warranted, but no investigation is recorded for this check. The available screening result is retained."
      : admission.decision === "insufficient_evidence" ? "No TC Hawkeye investigation was opened. The unavailable evidence and checks below limit what can be concluded; this is not a Not a Scam Finding."
      : "No TC Hawkeye investigation was requested because no warning flags were recorded. This screening decision is not proof that the message is genuine.",
      ...(admission.decision === "investigate" && event.what_to_do ? [event.what_to_do] : [`Review ${item} through an independently known contact for the claimed sender before acting on it.`])],
    uncertain: [...shortfalls, ...(!excerpt ? ["The message content is not included in this summary. Consult Evidence for any retained original."] : []),
      "Visible sender details and message wording alone do not establish authenticity."],
    how: ["Triage identifies the supplied evidence and flags that warrant investigation. Recorded protection Gate checks remain separate from Hawkeye's investigation."],
    more: [], sources: [],
  };
  return { label: admission.label, report, admission: admission.decision,
    status: admission.decision === "investigate" ? "attention" : admission.incomplete ? "not_fully_checked" : "no_threat" } as const;
}
