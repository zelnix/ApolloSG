/**
 * Patrol Activity — builds the unified activity timeline for the Patrol History screen.
 *
 * Merges PatrolEvents (existing threat/check records) with the on-device ActivityLog
 * (device posture changes, protection health events, background check records) into a
 * single, filtered, grouped timeline.
 *
 * Rules:
 * - PatrolEvents are labelled as existing records; their outcomes are never rewritten.
 * - Routine successful checks are grouped with counts and expandable timestamps.
 * - Concerns, protection failures and important changes stay individually visible.
 * - Blocks require enforcement_evidence to be labelled "blocked".
 * - Failed checks are never presented as successful.
 * - No AI calls.
 */
import type { PatrolEvent } from "@/src/domain/types";
import type { ActivityEntry, ActivityType } from "@/src/store/activityLog";
import {
  threatCaseStatus,
  threatCaseId,
  STATUS_LABELS,
  isSimulated,
  formatDateTime,
  type ThreatCaseStatus,
} from "@/src/domain/threatCase";
import { presentEvent } from "@/src/domain/luddish/present";

// ── Unified timeline item ────────────────────────────────────────────────────

export type FilterKey = "all" | "checks" | "detections" | "protection_actions" | "device_changes";
export const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "checks", label: "Checks" },
  { key: "detections", label: "Detections" },
  { key: "protection_actions", label: "Protection" },
  { key: "device_changes", label: "Device" },
];

export interface TimelineItem {
  id: string;
  type: ActivityType;
  timestamp: string;
  title: string;
  detail: string;
  actor: string;
  outcome: string;
  /** The Lucide icon name hint for the UI. */
  iconHint: "shield-check" | "shield-alert" | "shield-x" | "search" | "settings" | "monitor" | "lock" | "unlock" | "zap" | "activity" | "check-circle" | "alert-triangle" | "x-circle" | "refresh-cw";
  /** Colour tone for the outcome. */
  tone: "success" | "concern" | "failure" | "neutral" | "change";

  // ── Expansion ──
  expandedDetail?: string;
  limitations?: string[];
  beforeValue?: string;
  afterValue?: string;

  // ── Linking ──
  linkedEventId?: string;
  linkedCaseRef?: string;

  // ── Source ──
  source: "patrol_event" | "activity_log";
  simulated?: boolean;
  verified?: boolean;

  // ── Grouping ──
  groupKey?: string;
}

/** A group of routine items that are collapsed into a single row with a count. */
export interface TimelineGroup {
  kind: "group";
  groupKey: string;
  title: string;
  count: number;
  latestTimestamp: string;
  items: TimelineItem[];
  tone: "success" | "neutral";
  iconHint: TimelineItem["iconHint"];
}

/** A single, individually visible timeline entry. */
export interface TimelineSingle {
  kind: "single";
  item: TimelineItem;
}

export type TimelineRow = TimelineGroup | TimelineSingle;

/** A day section in the timeline. */
export interface TimelineDay {
  label: string;
  date: string;
  rows: TimelineRow[];
}

// ── PatrolEvent → TimelineItem ───────────────────────────────────────────────

function patrolEventType(e: PatrolEvent): ActivityType {
  if (e.verified_block && e.enforcement_evidence) return "protection_action";
  if (e.state === "biting" && e.enforcement_evidence) return "protection_action";
  if (e.state === "barking" || e.state === "growling" || e.state === "ears_up") return "detection";
  return "check";
}

function patrolEventOutcome(e: PatrolEvent): { outcome: string; tone: TimelineItem["tone"] } {
  // A block MUST have enforcement_evidence to be labelled "blocked"
  if (e.verified_block && e.enforcement_evidence) return { outcome: "Blocked", tone: "success" };
  if (e.state === "biting" && e.enforcement_evidence) return { outcome: "Blocked", tone: "success" };
  if (e.state === "barking") return { outcome: "Threat detected", tone: "concern" };
  if (e.state === "growling") return { outcome: "Warning", tone: "concern" };
  if (e.state === "ears_up") return { outcome: "Under review", tone: "concern" };
  if (e.state === "sniffing") return { outcome: "Checking", tone: "neutral" };
  // resting = successful check with no concerns
  return { outcome: "No concerns", tone: "success" };
}

function patrolEventActor(e: PatrolEvent): string {
  if (e.origin === "sample_check") return "Sample Check";
  if (e.enforcement_evidence) {
    const mechanism = e.enforcement_evidence.mechanism;
    if (mechanism === "dns_sinkhole" || mechanism === "vpn_filter") return "Apollo";
    if (mechanism === "native_protection" || mechanism === "os_protection") return "Device protection";
    return "Apollo";
  }
  if (e.evidence_provenance === "native_protection") return "Device protection";
  if (e.origin === "user") return "User submission";
  return "Apollo";
}

function patrolEventIcon(e: PatrolEvent): TimelineItem["iconHint"] {
  if (e.verified_block && e.enforcement_evidence) return "shield-check";
  if (e.state === "barking" || e.state === "biting") return "shield-alert";
  if (e.state === "growling") return "alert-triangle";
  if (e.state === "ears_up") return "search";
  if (e.state === "sniffing") return "activity";
  return "check-circle";
}

function patrolEventExpandedDetail(e: PatrolEvent): string {
  const lines: string[] = [];
  if (e.what_happened) lines.push(e.what_happened);
  if (e.why?.length) lines.push(e.why.join(". "));
  if (e.what_to_do) lines.push(`Recommendation: ${e.what_to_do}`);
  if (e.evidence_completeness === "partial") lines.push("Some evidence was incomplete.");
  if (e.evidence_gaps?.length) {
    for (const gap of e.evidence_gaps) {
      lines.push(`Check limitation: ${gap.name} — ${gap.reason}`);
    }
  }
  return lines.join("\n") || "";
}

function patrolEventLimitations(e: PatrolEvent): string[] {
  const lims: string[] = [];
  if (e.evidence_completeness === "partial") lims.push("Partial evidence — some checks could not complete.");
  if (e.evidence_gaps?.length) {
    for (const gap of e.evidence_gaps) lims.push(`${gap.name}: ${gap.reason}`);
  }
  const triage = e.triage_investigation;
  if (triage?.outcome === "LIMITED_UNABLE_TO_DETERMINE") lims.push("Triage outcome: limited — unable to determine.");
  if (triage) {
    const incomplete = triage.rules?.filter((r) => r.result === "not_checked");
    if (incomplete?.length) {
      for (const r of incomplete) lims.push(`Not checked: ${r.name}${r.reason ? ` (${r.reason})` : ""}`);
    }
  }
  return lims;
}

/** Convert a PatrolEvent to a TimelineItem. Labels it as an existing patrol record. */
export function patrolEventToTimeline(e: PatrolEvent): TimelineItem {
  const presented = presentEvent(e);
  const { outcome, tone } = patrolEventOutcome(e);
  const status = threatCaseStatus(e);
  const caseRef = threatCaseId(e);

  // Routine successful checks get a groupKey for collapsing
  const isRoutineSuccess = e.state === "resting" && !e.verified_block;
  const groupKey = isRoutineSuccess ? `routine-check-${e.category}` : undefined;
  const sampleCheck = e.origin === "sample_check";

  return {
    id: `pe:${e.event_id}`,
    type: patrolEventType(e),
    timestamp: e.occurred_at,
    title: presented.title || e.headline || `${e.category} check`,
    detail: `${outcome} · ${STATUS_LABELS[status]}${sampleCheck ? " · Sample Check" : ""}`,
    actor: patrolEventActor(e),
    outcome,
    iconHint: patrolEventIcon(e),
    tone,
    expandedDetail: patrolEventExpandedDetail(e),
    limitations: patrolEventLimitations(e),
    linkedEventId: e.event_id,
    linkedCaseRef: caseRef,
    source: "patrol_event",
    simulated: isSimulated(e),
    verified: e.verified_block ? true : undefined,
    groupKey,
  };
}

// ── ActivityEntry → TimelineItem ─────────────────────────────────────────────

function activityIcon(e: ActivityEntry): TimelineItem["iconHint"] {
  switch (e.type) {
    case "check":
      return e.outcome === "success" ? "check-circle" : e.outcome === "failure" ? "x-circle" : "activity";
    case "detection":
      return "shield-alert";
    case "protection_action":
      return e.outcome === "blocked" ? "shield-check" : e.outcome === "failure" ? "shield-x" : e.outcome === "restored" ? "refresh-cw" : "zap";
    case "device_change":
      return e.outcome === "baseline" ? "monitor" : "settings";
    default:
      return "activity";
  }
}

function activityTone(e: ActivityEntry): TimelineItem["tone"] {
  switch (e.outcome) {
    case "success": case "blocked": case "restored": return "success";
    case "concern": return "concern";
    case "failure": return "failure";
    case "change": return "change";
    case "baseline": return "neutral";
    default: return "neutral";
  }
}

export function activityEntryToTimeline(e: ActivityEntry): TimelineItem {
  return {
    id: `ae:${e.id}`,
    type: e.type,
    timestamp: e.occurredAt ?? e.detectedAt ?? e.timestamp,
    title: e.title,
    detail: e.detail,
    actor: e.actor,
    outcome: e.outcome === "success" ? "No concerns" : e.outcome === "blocked" ? "Blocked" : e.outcome === "failure" ? "Failed" : e.outcome === "concern" ? "Concern" : e.outcome === "change" ? "Changed" : e.outcome === "baseline" ? "Baseline" : e.outcome === "restored" ? "Restored" : e.outcome,
    iconHint: activityIcon(e),
    tone: activityTone(e),
    expandedDetail: e.expandedDetail,
    limitations: e.limitations,
    beforeValue: e.beforeValue,
    afterValue: e.afterValue,
    linkedEventId: e.linkedEventId,
    source: "activity_log",
    verified: e.verified,
    groupKey: e.groupKey,
  };
}

// ── Build unified timeline ───────────────────────────────────────────────────

function matchesFilter(item: TimelineItem, filter: FilterKey): boolean {
  if (filter === "all") return true;
  switch (filter) {
    case "checks": return item.type === "check";
    case "detections": return item.type === "detection";
    case "protection_actions": return item.type === "protection_action";
    case "device_changes": return item.type === "device_change";
    default: return true;
  }
}

const dayLabel = (iso: string): string => {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86_400_000);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(date, today)) return "Today";
  if (same(date, yesterday)) return "Yesterday";
  return date.toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
};

const dayKey = (iso: string) => new Date(iso).toISOString().slice(0, 10);

/** Build the complete timeline: merge PatrolEvents + ActivityEntries, filter, group, day-section. */
export function buildTimeline(
  events: PatrolEvent[],
  activities: ActivityEntry[],
  filter: FilterKey,
): TimelineDay[] {
  // Convert all sources to TimelineItems
  const items: TimelineItem[] = [
    ...events.map(patrolEventToTimeline),
    ...activities.map(activityEntryToTimeline),
  ];

  // Filter
  const filtered = items.filter((item) => matchesFilter(item, filter));

  // Sort newest first
  filtered.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));

  // Group by day
  const dayMap = new Map<string, TimelineItem[]>();
  for (const item of filtered) {
    const dk = dayKey(item.timestamp);
    const list = dayMap.get(dk) ?? [];
    list.push(item);
    dayMap.set(dk, list);
  }

  // Build day sections with grouping
  const days: TimelineDay[] = [];
  const sortedDays = [...dayMap.keys()].sort().reverse();

  for (const dk of sortedDays) {
    const dayItems = dayMap.get(dk)!;
    const rows: TimelineRow[] = [];

    // Group routine successes by groupKey
    const groupable = new Map<string, TimelineItem[]>();
    const singles: TimelineItem[] = [];

    for (const item of dayItems) {
      if (item.groupKey && item.tone === "success") {
        const list = groupable.get(item.groupKey) ?? [];
        list.push(item);
        groupable.set(item.groupKey, list);
      } else {
        singles.push(item);
      }
    }

    // Add grouped items (only group if 3+ items; otherwise keep individual)
    for (const [gk, gItems] of groupable) {
      if (gItems.length >= 3) {
        rows.push({
          kind: "group",
          groupKey: gk,
          title: `${gItems.length} routine checks — no concerns`,
          count: gItems.length,
          latestTimestamp: gItems[0].timestamp,
          items: gItems,
          tone: "success",
          iconHint: "check-circle",
        });
      } else {
        for (const item of gItems) rows.push({ kind: "single", item });
      }
    }

    // Add singles
    for (const item of singles) rows.push({ kind: "single", item });

    // Sort rows by timestamp (newest first)
    rows.sort((a, b) => {
      const ta = a.kind === "group" ? a.latestTimestamp : a.item.timestamp;
      const tb = b.kind === "group" ? b.latestTimestamp : b.item.timestamp;
      return Date.parse(tb) - Date.parse(ta);
    });

    days.push({ label: dayLabel(dayItems[0].timestamp), date: dk, rows });
  }

  return days;
}

// ── Filter counts ────────────────────────────────────────────────────────────

export function filterCounts(events: PatrolEvent[], activities: ActivityEntry[]): Record<FilterKey, number> {
  const items: TimelineItem[] = [
    ...events.map(patrolEventToTimeline),
    ...activities.map(activityEntryToTimeline),
  ];
  const counts: Record<FilterKey, number> = { all: items.length, checks: 0, detections: 0, protection_actions: 0, device_changes: 0 };
  for (const item of items) {
    if (item.type === "check") counts.checks++;
    else if (item.type === "detection") counts.detections++;
    else if (item.type === "protection_action") counts.protection_actions++;
    else if (item.type === "device_change") counts.device_changes++;
  }
  return counts;
}
