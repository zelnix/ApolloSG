// Counts shown on the bottom tabs. Pure: no React Native, so the rules are unit-tested in node.
import { caseGroupKey, threatCaseStatus } from "./threatCase.ts";
import type { PatrolEvent } from "./types";

/** Threats tab: threat cases that still need the person ("Needs you"). One per case — the case's latest event —
 *  the same way the Threats list groups them; it falls as each case is handled. */
export function countNeedingYou(events: PatrolEvent[]): number {
  const latest = new Map<string, PatrolEvent>();
  for (const event of events) {
    const key = caseGroupKey(event);
    const held = latest.get(key);
    if (!held || Date.parse(event.occurred_at) > Date.parse(held.occurred_at)) latest.set(key, event);
  }
  let count = 0;
  for (const event of latest.values()) if (threatCaseStatus(event) === "attention") count += 1;
  return count;
}

export interface BadgeAlert { url: string; severity: string; appliesIn: string; australianRelevance: string; tier: string; verifiedOngoing?: boolean; effectiveDate?: string | null }
const SEVERE = new Set(["HIGH", "EXTREME"]);
const ELIGIBLE_TIERS = new Set(["specific_scam", "emerging_pattern"]);
const ELIGIBLE_RELEVANCE = new Set(["confirmed", "potential"]);
const RECENCY_DAYS = 60;

/** Single eligibility rule: same relevance, audience and freshness checks as the feed and Apollo state.
 *  Includes verified global consumer threats applicable to Australia — not just "confirmed". */
function isEligible(alert: BadgeAlert): boolean {
  if (!ELIGIBLE_TIERS.has(alert.tier)) return false;
  if (!ELIGIBLE_RELEVANCE.has(alert.australianRelevance)) return false;
  // Freshness
  if (alert.effectiveDate) {
    const age = Date.now() - Date.parse(alert.effectiveDate);
    if (age > RECENCY_DAYS * 86_400_000) {
      // Older than 60 days: only keep if verified ongoing
      if (!alert.verifiedOngoing) return false;
    }
  } else {
    // Undated: require verified ongoing activity
    if (!alert.verifiedOngoing) return false;
  }
  return true;
}

/** Scam Alerts tab: High and Extreme eligible alerts the person hasn't seen yet. */
export function countNewSevereAlerts(alerts: BadgeAlert[], seen: ReadonlySet<string>, home: string): number {
  const counted = new Set<string>();
  for (const alert of alerts) {
    if (!SEVERE.has(alert.severity) || seen.has(alert.url)) continue;
    if (!isEligible(alert)) continue;
    counted.add(alert.url);
  }
  return counted.size;
}

/** What the badge shows: nothing at zero, the number up to 9, then "9+". */
export function badgeText(count: number): string | undefined {
  if (count <= 0) return undefined;
  return count > 9 ? "9+" : String(count);
}
