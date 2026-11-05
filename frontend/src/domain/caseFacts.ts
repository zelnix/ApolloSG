// Threat Case facts, kept apart (Apollo's origin rule). Five separate things, none inferred from another — the
// fields behind them are read through src/domain/evidenceModel.ts:
//   origin         — every Threat Case begins on the device that detected it. Server processing, Magnum DI, syncing,
//                    privacy projection and missing evidence never change that, and never point anywhere else;
//   evidence       — what supplied the evidence (`evidence_provenance`). Never a server: processing is not a source;
//   processing     — what checked it: Higgins Triage on this device or on ApolloSG's servers, TC FlyBy, Magnum DI;
//   completeness   — what this case's record holds, and every check that didn't finish with its recorded reason;
//   representation — the privacy step that shaped what ApolloSG's servers worked from or keep.
// Missing evidence is never evidence of a threat: it only narrows what ApolloSG could verify. Pure, no Expo imports.

import catalogue from "./triage/catalogue.ts";
import { RULES_BY_ID, gapPlainEnglish, type CoverageGapRecord, type TriageInvestigationRecord } from "./triage/contract.ts";
import type { IncompleteCheck } from "./triage/completeness.ts";
import { evidenceModel, hasServerFindings } from "./evidenceModel.ts";
import { investigatorName } from "./messageVoice.ts";
import type { PatrolEvent } from "./types";

const WORDS = (catalogue as unknown as {
  completeness: {
    checks: Record<string, string>; failures: Record<string, string>; stale: string; checkNames: Record<string, string>;
    failureSentences: Record<string, string>; noReasonRecorded: string; statusLabels: Record<string, string>;
    evidenceNames: Record<string, string>; unverifiedLabel: string; unverified: Record<string, string>;
    unverifiedEvidence: Record<string, string>; unverifiedGaps: Record<string, string>;
    unrecorded: { name: string; status: string; reason: string; unverified: string };
  };
}).completeness;

// ── Origin ──────────────────────────────────────────────────────────────────

export const ORIGIN_LABEL = "Detected on this device";

/** Where the Threat Case began: the device that detected it, always. Nothing later in its life changes this. */
export function caseOrigin(event: Pick<PatrolEvent, "device_id">): { deviceId: string; label: string } {
  return { deviceId: event.device_id, label: ORIGIN_LABEL };
}

// ── Evidence source and what the record holds ───────────────────────────────

const provider = (e: PatrolEvent) => (e.source_metadata?.provider ?? "").trim();

/** Whether this case's record carries Apollo's findings, or only the privacy-protected summary ApolloSG's servers keep
 *  of a check (its kind and result). Decided by what the record holds, never by where a copy might be: a DNS block,
 *  the device's own protection, server-assisted analysis and an incomplete record all carry what Apollo recorded. */
export function hasRecordedFindings(e: PatrolEvent): boolean {
  return evidenceModel(e).representation !== "privacy_summary" || hasServerFindings(e);
}

/** What supplied the evidence — never a server, and never a statement about where it is kept. */
export const SOURCE_NOT_RECORDED = "Not recorded";
export function evidenceSourceLabel(e: PatrolEvent): string {
  const account = (e.source_metadata?.account ?? "").trim();
  switch (evidenceModel(e).source) {
    case "local_device": return "Apollo's check on this device";
    case "dns_observation": return "Apollo's DNS filter";
    case "native_protection": return provider(e) || "Your device's built-in protection";
    case "device_submission": return "Sent from this device for checking";
    case "connected_mailbox":
      // Show the actual email account when available so users with multiple mailboxes
      // can identify which inbox the evidence came from; fall back to provider name.
      if (account) return account;
      return provider(e) ? `${provider(e)} mailbox` : "Your connected mailbox";
    default: return SOURCE_NOT_RECORDED;
  }
}

/** What checked it. Server processing is part of this same case — it never moves the case's origin, and it never
 *  becomes the evidence source. */
export function processingLabels(e: PatrolEvent): string[] {
  const out: string[] = [];
  const m = evidenceModel(e);
  if (e.triage_investigation) out.push(m.processing === "apollosg_servers" ? "Higgins Triage on ApolloSG's servers" : "Higgins Triage on this device");
  else if (m.source === "dns_observation") out.push("Apollo's DNS filter on this device");
  else if (m.source === "native_protection") out.push(provider(e) || "Your device's built-in protection");
  else if (m.processing === "this_device") out.push("Apollo on this device");
  if (e.investigation_case_id ?? e.patrol_record?.investigationCaseId) {
    out.push(e.investigation_completed_at || e.investigation_answered_by
      ? `${investigatorName(e.investigation_answered_by)} on ApolloSG's servers` : "ApolloSG's investigators");
  }
  return out;
}

/** How complete the record is. Unfinished checks reduce what ApolloSG could verify; they never add a concern. */
export function completenessLabel(e: PatrolEvent): string {
  if (!hasRecordedFindings(e)) return "Summary only: the kind of check and its result, not the content that was checked";
  const n = caseShortfalls(e).length;
  if (n) return `${n} check${n === 1 ? "" : "s"} couldn't be completed — each is listed with its reason`;
  if (evidenceModel(e).completeness === "partial") return "Part of this case's evidence wasn't recorded, and no reason was recorded for it";
  return "No unfinished checks recorded";
}

/** The privacy step behind what ApolloSG's servers worked from or keep, when there was one. */
export function privacyNote(e: PatrolEvent): string | null {
  const representation = evidenceModel(e).representation;
  if (representation !== "privacy_protected_copy" && representation !== "privacy_summary") return null;
  return hasRecordedFindings(e)
    ? "ApolloSG's servers worked from a privacy-protected copy of this case's evidence. Their result belongs to this case."
    : "ApolloSG's servers keep a privacy-protected summary of this check, not the content that was checked.";
}

// ── Checks that didn't finish, each with its recorded reason ─────────────────

/** One check that didn't finish, in the order it is shown: what was checked → what happened → why it failed → what
 *  ApolloSG therefore couldn't verify. Every part comes from the record; a known error is never replaced by generic
 *  "unavailable" wording. */
export interface Shortfall {
  id: string;
  /** What was checked: the actual evidence or check ("Final destination", "Domain registration age"). */
  name: string;
  /** What happened: "didn't answer" · "couldn't be verified" · "used an earlier result" · "couldn't be checked". */
  status: string;
  /** Why it failed: the recorded reason, in a sentence. Never invented. */
  reason: string;
  /** What couldn't be verified because of it ("where the link finally leads"). */
  unverified: string;
  at: string | null;
}

/** "Couldn't verify where the link finally leads." */
export function unverifiedSentence(row: Pick<Shortfall, "unverified">): string {
  return sentence(`${WORDS.unverifiedLabel} ${row.unverified}`);
}

/** The full row in one line: "Final destination — couldn't be verified: The website's address doesn't exist.
 *  Couldn't verify where the link finally leads." */
export function shortfallLine(row: Shortfall): string {
  return `${row.name} — ${row.status}: ${row.reason} ${unverifiedSentence(row)}`;
}

function sentence(text: string): string {
  const t = text.trim().replace(/\.+$/, "");
  return t ? `${t[0].toUpperCase()}${t.slice(1)}.` : "";
}

/** A recorded reason, with any failure code it carries ("… (timeout)") in plain words. */
function recordedReason(text: string): string {
  return sentence(text.replace(/\(([a-z_]+)\)\s*$/, (m, code: string) => (WORDS.failures[code] ? `(${WORDS.failures[code]})` : m)));
}

export function incompleteReason(c: Pick<IncompleteCheck, "status" | "failure" | "detail">): string {
  if (c.status === "stale") return sentence(WORDS.stale.replace("{failure}", WORDS.failures[c.failure ?? ""] ?? "no answer"));
  return WORDS.failureSentences[c.failure ?? ""] ?? (c.detail ? recordedReason(c.detail) : WORDS.noReasonRecorded);
}

/** The first piece of evidence a rule needed that has a name, in the rule's own order — what it needed most. */
function ruleEvidenceKey(ruleId: string | undefined): string | null {
  const rule = ruleId ? RULES_BY_ID[ruleId] : undefined;
  return (rule?.evidence ?? []).find((key) => !!WORDS.evidenceNames[key]) ?? null;
}

/** The evidence a rule needed, named — never a vague catch-all. Falls back to the rule's own title. */
function evidenceName(ruleId: string | undefined): string | null {
  const key = ruleEvidenceKey(ruleId);
  if (key) return WORDS.evidenceNames[key];
  return ruleId ? RULES_BY_ID[ruleId]?.title ?? null : null;
}

/** What a coverage gap was about, when the record doesn't say which rule raised it. */
const GAP_NAME: Record<string, string> = {
  INTELLIGENCE_PROVIDER_UNAVAILABLE: "Reputation check",
  EMAIL_HEADERS_UNAVAILABLE: "Sender authentication",
  BROWSER_VISIBILITY_UNAVAILABLE: "Page content and origin",
  UNSUPPORTED_FILE_TYPE: "File contents",
  ENCRYPTED_CONTENT: "Encrypted contents",
  CONTENT_NOT_ACCESSIBLE: "Content inspection",
  PLATFORM_CAPABILITY_UNAVAILABLE: "Information this device doesn't share",
  PERMISSION_UNAVAILABLE: "A check that needs a permission",
  NETWORK_CHECK_FAILED: "Network check",
  INSUFFICIENT_EVIDENCE: "Available evidence",
  DETERMINISTIC_CHECK_ERROR: "A Triage check",
};

/** A gap's reason when its rule recorded none: the gap's own detail, its failure, else what its code means. */
function gapReason(gap: Pick<CoverageGapRecord, "detail" | "failure">, code: string): string {
  if (gap.detail) return recordedReason(gap.detail);
  if (gap.failure && WORDS.failureSentences[gap.failure]) return WORDS.failureSentences[gap.failure];
  return gapPlainEnglish(code);
}

/** What a gap left unverified: the rule's evidence, else the gap's code, else what the rule looks for. */
function gapUnverified(ruleId: string | undefined, code: string): string {
  const key = ruleEvidenceKey(ruleId);
  if (key && WORDS.unverifiedEvidence[key]) return WORDS.unverifiedEvidence[key];
  if (WORDS.unverifiedGaps[code]) return WORDS.unverifiedGaps[code];
  const title = ruleId ? RULES_BY_ID[ruleId]?.title : undefined;
  return title ? `whether this applies: ${title}` : WORDS.unrecorded.unverified;
}

/** One unfinished check, as recorded (Triage's incompleteChecks, or a gap recorded on the case itself). */
function incompleteRow(c: IncompleteCheck, id: string, at: string | null): Shortfall {
  return {
    id,
    name: WORDS.checkNames[c.check] ?? sentence(WORDS.checks[c.check] ?? c.check.replace(/_/g, " ")).replace(/\.$/, ""),
    status: WORDS.statusLabels[c.status] ?? WORDS.statusLabels.unavailable,
    reason: incompleteReason(c),
    unverified: WORDS.unverified[c.check] ?? WORDS.unrecorded.unverified,
    at: c.at ?? at,
  };
}

/** Every check Apollo needed but couldn't finish, with the actual check and its recorded reason. Incomplete checks
 *  come first; a coverage gap that names the same check isn't repeated in generic words. */
export function triageShortfalls(record: TriageInvestigationRecord | null | undefined): Shortfall[] {
  if (!record) return [];
  const out: Shortfall[] = [];
  const seen = new Set<string>();
  const add = (row: Shortfall) => {
    const key = `${row.name}|${row.reason}`;
    if (!seen.has(key)) { seen.add(key); out.push(row); }
  };
  (record.incompleteChecks ?? []).forEach((c, i) => add(incompleteRow(c, `incomplete:${c.check}:${i}`, record.evaluatedAt)));
  const covered = new Set(out.map((row) => row.name));
  const gapRules = (record.rules ?? []).filter((r) => r.result === "coverage_gap");
  const rows = gapRules.length
    ? gapRules.map((r) => ({ ruleId: r.ruleId, code: r.coverageGap ?? "", reason: r.evidence[0] ? recordedReason(r.evidence[0]) : "", detail: "" }))
    : record.coverageGaps.map((g) => ({ ruleId: g.ruleIds[0], code: g.code, reason: "", detail: g.detail }));
  for (const row of rows) {
    const name = evidenceName(row.ruleId) ?? GAP_NAME[row.code] ?? "A check ApolloSG couldn't complete";
    if (covered.has(name)) continue;
    const gap = record.coverageGaps.find((g) => g.code === row.code);
    add({ id: `gap:${row.ruleId ?? row.code}`, name, status: WORDS.statusLabels.coverage_gap,
      reason: row.reason || gapReason({ failure: gap?.failure ?? null, detail: row.detail }, row.code),
      unverified: gapUnverified(row.ruleId, row.code), at: record.evaluatedAt });
  }
  return out;
}

/** Every shortfall recorded for a case: its Triage record's, then any gap recorded on the case itself (such as a
 *  block claim the packet truth gate couldn't verify). */
export function caseShortfalls(e: PatrolEvent): Shortfall[] {
  const recorded = evidenceModel(e).gaps.map((c, i) => incompleteRow(c, `evidence:${c.check}:${i}`, e.occurred_at));
  return [...triageShortfalls(e.triage_investigation), ...recorded];
}

/** Only when the record says evidence is missing and no check, gap or failure records why: the fixed row saying so. */
export function unrecordedShortfall(e: PatrolEvent): Shortfall | null {
  if (evidenceModel(e).completeness !== "partial" || caseShortfalls(e).length) return null;
  const w = WORDS.unrecorded;
  return { id: "unrecorded", name: w.name, status: w.status, reason: w.reason, unverified: w.unverified, at: e.occurred_at };
}
