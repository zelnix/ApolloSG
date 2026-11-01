// Higgins Triage — shared investigation contract (mirror of backend services/triage/contract.py).
// Three outcomes only. Only a threat-producing rule (DETECT or CORRELATE) can create POSSIBLE THREAT. A ROUTE rule
// hands part of the item to another gate and is recorded as "routed"; a Coverage Gap can prevent NO THREAT but can
// never create POSSIBLE THREAT, and never downgrades threat evidence Apollo actually has. ZERO Gemini calls.

import catalogue from "./catalogue.ts";
import { AVAILABLE_CHECKS, type IncompleteCheck } from "./completeness.ts";

export type TriageOutcome = "NO_THREAT_IDENTIFIED" | "POSSIBLE_THREAT_IDENTIFIED" | "LIMITED_UNABLE_TO_DETERMINE";
export type RuleResult = "met" | "not_met" | "not_applicable" | "coverage_gap" | "routed";
/** DETECT and CORRELATE are threat-producing; ROUTE, COVERAGE and ENFORCE never make a Possible Threat on their own. */
export type RuleClass = "DETECT" | "CORRELATE" | "ROUTE" | "COVERAGE" | "ENFORCE";

export interface CatalogueRule {
  id: string;
  category: string;
  class: RuleClass;
  title: string;
  evidence?: string[];
  platformDependent?: boolean;
  gapCode?: string;
  /** The rule needs an observation this context may not offer (e.g. "browser_observation"). Without it the rule
   *  cannot execute here, so it is NOT APPLICABLE — recorded with the reason — never a coverage gap. */
  notApplicableWithout?: string;
}

export interface RuleRecord {
  ruleId: string;
  title: string;
  category: string;
  /** The rule's class (absent on records from before rule classes). */
  class?: RuleClass;
  applicable: boolean;
  checked: boolean;
  result: RuleResult;
  evidence: string[];
  coverageGap: string | null;
  detail: string;
}

export interface CoverageGapRecord {
  code: string;
  detail: string;
  recoverable: boolean;
  ruleIds: string[];
  /** How the lookup behind this gap failed, when known (timeout, quota_exhausted, auth_failure, …). */
  failure?: string | null;
}

export interface RetryRecord {
  check: string;
  attempts: number;
  outcome: "succeeded" | "recovered" | "failed" | "not_retried_permanent";
}

export interface TriageInvestigationRecord {
  investigationId: string;
  catalogueVersion: number;
  sourceType: string;
  outcome: TriageOutcome;
  reason: string;
  rulesApplicable: string[];
  rulesChecked: string[];
  rulesMet: string[];
  /** ROUTE rules that handed part of the item to another gate (absent on records from before rule classes). */
  rulesRouted?: string[];
  rules: RuleRecord[];
  coverageGaps: CoverageGapRecord[];
  /** Checks Apollo needed but couldn't finish (see completeness.ts). Absent on records from before this existed. */
  incompleteChecks?: IncompleteCheck[];
  /** "incomplete" whenever any check Apollo needed didn't finish — never shown as a complete examination. */
  coverage?: "complete" | "incomplete";
  retries: RetryRecord[];
  correlation: Record<string, unknown>;
  recheckUseful: boolean;
  geminiCalls: 0;
  /** Set when a past case was judged again under a later rule catalogue (triage/rejudge.ts). */
  rejudgedUnder?: string;
  evaluatedAt: string;
}

export const CATALOGUE_VERSION: number = (catalogue as unknown as { version: number }).version;
export const RULES: CatalogueRule[] = (catalogue as unknown as { rules: CatalogueRule[] }).rules;
export const RULES_BY_ID: Record<string, CatalogueRule> = Object.fromEntries(RULES.map((r) => [r.id, r]));
const THREAT_PRODUCING = new Set<string>((catalogue as unknown as { ruleClasses: { threatProducing: string[] } }).ruleClasses.threatProducing);
/** Only DETECT and CORRELATE rules can make a Possible Threat. */
export const threatProducing = (ruleId: string): boolean => THREAT_PRODUCING.has(RULES_BY_ID[ruleId]?.class);
export const RULES_BY_CATEGORY: Record<string, CatalogueRule[]> = RULES.reduce((acc, r) => {
  (acc[r.category] ||= []).push(r);
  return acc;
}, {} as Record<string, CatalogueRule[]>);

const GAP_META: Record<string, { recoverable: boolean; plain: string }> = Object.fromEntries(
  (catalogue as unknown as { coverageGapCodes: { code: string; recoverable: boolean; plain: string }[] })
    .coverageGapCodes.map((g) => [g.code, { recoverable: g.recoverable, plain: g.plain }]),
);

export const RETRY_ATTEMPTS: number = (catalogue as unknown as { retryPolicy: { attempts: number } }).retryPolicy.attempts;

export function gapIsRecoverable(code: string): boolean {
  return GAP_META[code]?.recoverable ?? false;
}

/** Plain-English translation of a Coverage Gap code — Higgins' wording, never a technical code. */
export function gapPlainEnglish(code: string): string {
  return GAP_META[code]?.plain ?? "ApolloSG couldn't complete part of this check.";
}

/** What a Limited result tells the person — never "safe", never "nothing to worry about". */
export const LIMITED_CAUTION = "Treat this with caution. ApolloSG couldn't check it fully, so it can't say it's safe. Don't act on it until you've confirmed it another way.";
export const LIMITED_TODO = "Don't tap links, reply, call back or pay until you've confirmed it through a contact you already trust, like the official app or website.";

const CODE_LIST = /\b[A-Z]+(?:_[A-Z]+)+(?:,\s*[A-Z]+(?:_[A-Z]+)+)*\b/g;

/** Person-facing wording (Overview, Higgins): every Coverage Gap code — or list of them — becomes its
 *  plain-English sentence. The codes themselves stay on the record, and the DI tab shows them. */
export function plainTriageText(text: string): string {
  if (!text) return text;
  return text
    .replace(/^Coverage gap:\s*/, "Couldn't check: ")
    .replace(CODE_LIST, (list) => list.split(",").map((c) => c.trim())
      .map((code) => GAP_META[code]?.plain ?? code.replace(/_/g, " ").toLowerCase()).join(" "));
}

/** Historical SAFE/SUSPICIOUS/UNCERTAIN results, mapped for display only. */
export function legacyOutcome(verdict: string): TriageOutcome {
  const value = (verdict || "").toUpperCase();
  if (value === "SAFE") return "NO_THREAT_IDENTIFIED";
  if (value === "SUSPICIOUS") return "POSSIBLE_THREAT_IDENTIFIED";
  return "LIMITED_UNABLE_TO_DETERMINE";
}

export const OUTCOME_LABEL: Record<TriageOutcome, string> = {
  NO_THREAT_IDENTIFIED: "No threat identified",
  POSSIBLE_THREAT_IDENTIFIED: "Possible threat identified",
  LIMITED_UNABLE_TO_DETERMINE: "Limited — unable to determine",
};

/** The outcome as the person sees it: a No Threat whose checks didn't all complete is
 *  "No threat found by available checks", never the unqualified "No threat identified". */
export function outcomeLabel(record: Pick<TriageInvestigationRecord, "outcome" | "incompleteChecks">): string {
  if (record.outcome === "NO_THREAT_IDENTIFIED" && record.incompleteChecks?.length) return AVAILABLE_CHECKS;
  return OUTCOME_LABEL[record.outcome] ?? record.outcome;
}

/** Whether a "Check again" affordance can actually achieve something. */
export function recheckCanHelp(record: TriageInvestigationRecord | null | undefined): boolean {
  return !!record?.coverageGaps.some((gap) => gap.recoverable);
}
