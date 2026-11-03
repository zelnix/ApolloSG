/**
 * Threat Case presentation model — shared adapter that combines PatrolEvent +
 * optional Magnum DI CaseState into a single Threat Case view model.
 *
 * Rules:
 * - PatrolEvent is the primary source of truth for detection/enforcement data.
 * - CaseState is optional — its presence adds investigation information.
 * - The UI must only show states/actions supported by real data.
 * - No fabricated investigation stages, block claims, evidence, or timeline events.
 */

import { needsYou } from "./caseBriefing.ts";
import { notFullyChecked } from "./luddish/present.ts";
import { investigatorName } from "./messageVoice.ts";
import type {
  ApolloState,
  HigginsBriefing,
  PatrolEnforcementEvidence,
  PatrolEvent,
  PatrolRecord,
  SourceMetadata,
} from "./types";

/** Who settled this threat's investigation, once it has finished and this device recorded who did.
 *  Null when there was no investigation, it is still running, or who settled it wasn't recorded. */
export function settledBy(event: Pick<PatrolEvent, "investigation_completed_at" | "investigation_answered_by">): "TC FlyBy" | "Magnum DI" | null {
  return event.investigation_completed_at && event.investigation_answered_by ? investigatorName(event.investigation_answered_by) : null;
}

/** The case came from a preview sample, or an outside source behind its investigation was simulated. It was
 *  processed exactly as in production; this only tags it. Never true in a production build: nothing there is simulated. */
export function isSimulated(event: Pick<PatrolEvent, "evidence_profile" | "investigation_simulated">): boolean {
  return !!(event.evidence_profile?.simulated || event.investigation_simulated);
}

/** True when this event originated from a Sample Check — a production test, not a preview simulation. */
export function isSampleCheck(event: Pick<PatrolEvent, "origin">): boolean {
  return event.origin === "sample_check";
}

// ── Threat Case ID ──────────────────────────────────────────────────────────

export function threatCaseId(event: PatrolEvent): string {
  const record = event.patrol_record;
  const raw = record?.recordId ?? event.event_id;
  const suffix = raw.replace(/[^a-zA-Z0-9]/g, "").slice(-5).toUpperCase();
  const year = new Date(event.occurred_at).getFullYear();
  return `TC-${year}-${suffix}`;
}

// ── Case grouping ───────────────────────────────────────────────────────────

/** The key that decides what counts as ONE case in the Threats list. Repeat checks of the same
 *  subject (today: device checks) carry a stable case_key, so they collapse into a single case
 *  showing the latest result while every individual check stays visible in patrol history.
 *  Two records that name the SAME Magnum DI investigation are the same case — this device's own
 *  record and anything Apollo's servers filed for that investigation collapse into one row. */
export function caseGroupKey(event: PatrolEvent): string {
  const investigation = event.investigation_case_id ?? event.patrol_record?.investigationCaseId;
  return event.case_key ?? event.patrol_record?.logicalIssueKey ?? (investigation ? `inv:${investigation}` : event.event_id);
}

/** One row per case, the latest record of each first — what the Threats list shows.
 *
 *  Governing rule: automatic checking creates Patrol History. A possible, unresolved
 *  or confirmed threat creates a Threats entry. Cases whose latest event resolved as
 *  "no threat" are excluded — they remain in Patrol History for audit but do not
 *  clutter the Threats list or inflate its badge counts. */
export function threatCases(events: PatrolEvent[]): PatrolEvent[] {
  const seen = new Set<string>();
  return [...events]
    .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime())
    .filter((event) => {
      const key = caseGroupKey(event);
      if (seen.has(key)) return false;
      seen.add(key);
      // Exclude "no threat" — only possible, unresolved or confirmed threats qualify.
      return threatCaseStatus(event) !== "no_threat";
    });
}

// ── Status ──────────────────────────────────────────────────────────────────

export type ThreatCaseStatus =
  | "investigating"
  | "blocked"
  | "attention"
  | "resolved"
  | "no_threat"
  | "not_fully_checked"
  | "monitoring";

export function threatCaseStatus(event: PatrolEvent): ThreatCaseStatus {
  // Checks that couldn't run, or an investigation that couldn't decide with nothing concrete to act on, are a case
  // not fully checked: never a threat and never "no threat".
  if (notFullyChecked(event) && !event.verified_block) return "not_fully_checked";
  if (event.resolved_at) {
    if (event.state === "resting") return "no_threat";
    return "resolved";
  }
  // Only claim "blocked" when genuine enforcement evidence confirms it
  if (event.verified_block && event.enforcement_evidence) return "blocked";
  // An investigation is only "investigating" while it is actually running. Once Magnum DI has
  // answered (its result is committed to this device) the case is reported by what it found.
  const hasInvestigation = !!(event.investigation_case_id ?? event.patrol_record?.investigationCaseId);
  if (hasInvestigation && !event.investigation_completed_at) return "investigating";
  // "Needs you" only when the case owes the person a decision with a concrete reason (caseBriefing.needsYou) —
  // never from a Barking, review or keeping-watch state on its own.
  if (needsYou(event)) return "attention";
  return "monitoring";
}

export const STATUS_LABELS: Record<ThreatCaseStatus, string> = {
  investigating: "Investigating",
  blocked: "Blocked",
  attention: "Needs you",
  resolved: "Handled",
  no_threat: "No threat",
  not_fully_checked: "Not fully checked",
  monitoring: "Keeping watch",
};

export const STATUS_COLORS: Record<ThreatCaseStatus, { bg: string; text: string }> = {
  investigating: { bg: "#DC2626", text: "#FFFFFF" },
  blocked: { bg: "#059669", text: "#FFFFFF" },
  attention: { bg: "#DC2626", text: "#FFFFFF" },
  resolved: { bg: "#059669", text: "#FFFFFF" },
  no_threat: { bg: "#6B7280", text: "#FFFFFF" },
  not_fully_checked: { bg: "#6B7280", text: "#FFFFFF" },
  monitoring: { bg: "#D97706", text: "#FFFFFF" },
};

// ── Source identity ─────────────────────────────────────────────────────────

export interface SourceIdentity {
  type: string;
  typeLabel: string;
  title: string;
  subtitle: string;
  timestamp: string;
  Icon: React.ComponentType<{ size: number; color: string }>;
  iconBg: string;
  iconFg: string;
}

// ── Risk level ──────────────────────────────────────────────────────────────

export function riskLevel(state: ApolloState): { label: string; color: string } {
  switch (state) {
    case "biting": return { label: "Critical", color: "#DC2626" };
    case "barking": return { label: "High", color: "#DC2626" };
    case "growling": return { label: "Medium", color: "#D97706" };
    case "ears_up": return { label: "Low", color: "#D97706" };
    case "resting": return { label: "None", color: "#059669" };
    default: return { label: "Unknown", color: "#6B7280" };
  }
}

// ── Category label ──────────────────────────────────────────────────────────

export function categoryLabel(cat: string, recordClass?: string | null): string {
  if (recordClass) {
    const MAP: Record<string, string> = {
      phishing: "Phishing (Scam)",
      malware: "Malware",
      impersonation: "Impersonation",
      social_engineering: "Social engineering",
      credential_theft: "Credential theft",
      financial_fraud: "Financial fraud",
      tech_support_scam: "Tech support scam",
      investment_scam: "Investment scam",
      romance_scam: "Romance scam",
      security_threat: "Security threat",
      protection_issue: "Protection issue",
    };
    if (MAP[recordClass]) return MAP[recordClass];
  }
  switch (cat) {
    case "website": return "Website";
    case "call": return "Call";
    case "message": return "Message";
    case "email": return "Email";
    case "device": return "Device";
    case "file": return "File";
    case "app": return "App";
    case "link": return "Link";
    case "account": return "Account";
    default: return "Security";
  }
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString([], {
    day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

/** Just the time of day, as Ask Higgins shows it under "Higgins". */
export function formatTime(iso: string | null | undefined): string | null {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d.getTime()) ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : null;
}
