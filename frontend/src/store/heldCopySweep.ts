// The clean-up sweep for ApolloSG's held copies on this phone (domain/heldCopies.ts): every original text, email
// fields, .eml file and picture kept for more than 24 hours is deleted, whether or not its case is ever opened again.
// Run when the app starts, when it comes back to the foreground and every few minutes while it is open.
import type { PatrolEvent } from "@/src/domain/types";

import { sweepImageEvidence } from "./imageEvidence";
import { getOriginalSource } from "./originalSource";
import { sweepOriginalEmails } from "./originalEmail";

export const HELD_COPY_SWEEP_MS = 5 * 60 * 1000;

export async function sweepHeldCopies(events: PatrolEvent[], now: number = Date.now()): Promise<void> {
  const keys = new Set<string>();
  for (const e of events) {
    keys.add(e.event_id);
    const caseId = e.investigation_case_id ?? e.patrol_record?.investigationCaseId;
    if (caseId) keys.add(caseId);
  }
  // Reading an original past its 24 hours deletes it (originalSource.getOriginalSource).
  for (const k of keys) await getOriginalSource(k, now);
  await sweepImageEvidence(now);
  await sweepOriginalEmails(now);
}
