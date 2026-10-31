// The Deep Investigation (DI) record as the app receives it: whether Magnum DI ran, live or on the preview
// simulator, and what it was handed — plus the recorded decision path. It is NOT evidence: evidence stays the
// original source Apollo received. Token counts, cost, timings, the prompts, the full reply, rule-book codes, the
// provider and the model are Apollo's own diagnostics: they stay in the Admin Portal and never reach the device.

import type { TriageInvestigationRecord } from "./triage/contract.ts";

export interface DiAttachment {
  mimeType: string;
  sizeBytes: number;
  dimensions?: { width: number; height: number };
  privacyScreening: string;
  redactionStatus: string;
  transmittedForm: string;
}

export interface DiTransaction {
  investigationId: string;
  engine: string;
  environment: string;
  mode: "Live" | "Simulated";
  simulated: boolean;
  status: string | null;
  failureCode: string | null;
  occurredAt: string | null;
  request: { attachments?: DiAttachment[]; attachmentCount?: number; tools?: string[] };
  notice: string | null;
}

/** What TC FlyBy recorded for the case (server `routing.tc_flyby`, without the model). */
export interface FlybyTrace {
  ranAt: string | null;
  resolved: boolean;
  answeredBy: string | null;
  outcome: string | null;
  basis: string | null;
  messageType: string | null;
  pattern: { key: string; stage: string } | null;
  checks: { kind: string; status: string; route: string | null }[];
  searchCalls: number | null;
  searchQueries: number | null;
  cacheHits: number | null;
  magnumNeeded: boolean | null;
  magnumSearch: boolean | null;
  gaps: { item: string; what: string }[] | null;
  issues: { capability: string; text: string }[] | null;
  simulated: boolean | null;
}

/** The recorded decision path: Higgins Triage → TC FlyBy → Magnum DI → Evidence Lock. A stage with no
 *  record is null — never inferred. */
export interface DiTrace {
  triage: TriageInvestigationRecord | null;
  flyby: FlybyTrace | null;
  magnum: { webSearch: boolean; searchQueries: number; itemsSent: number; simulated: boolean; at: string | null } | null;
  answeredBy: string | null;
  outcome: string | null;
  completion: string | null;
  /** The settling rule by name and sentence (its rule-book code stays in the Admin Portal). */
  settledReason: { rule: string; by: string; sentence: string } | null;
  higgins: { status: "PASS" | "FAIL" | null; mode: string | null; attempts: number | null } | null;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "not recorded";
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
