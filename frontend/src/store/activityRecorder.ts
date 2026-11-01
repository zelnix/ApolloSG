/**
 * Activity Recorder — captures device security changes and protection events as
 * immutable activity entries for the Patrol History timeline.
 *
 * Hooks into:
 * - Posture monitor (device setting changes: VPN, screen lock, permissions, etc.)
 * - Protection health coordinator (gate status changes, check completions/failures)
 *
 * Rules:
 * - Entries are immutable once recorded.
 * - A gate switched on is "configured"; verified operational is separate.
 * - A change discovered after restart says "Change detected at [restart time]"
 *   unless the actual occurrence time is known.
 * - Initial settings are a baseline, not changes.
 * - Successful checks with no concerns are recorded.
 * - Failed checks never appear as successful.
 * - No AI calls.
 */
import { recordActivity, recordActivities, hasTodayEntry, type ActivityEntry } from "@/src/store/activityLog";
import { onPostureChange, type PostureChange, type PostureSnapshot } from "@/src/security/devicePosture";
import type { ProtectionHealthSnapshot, GateHealthRecord } from "@/src/protection/healthTypes";

let _previousHealth: ProtectionHealthSnapshot | null = null;
let _baselineRecorded = false;
let _unsubPosture: (() => void) | null = null;

// ── Posture Changes → Activity Entries ───────────────────────────────────────

function postureChangeEntry(change: PostureChange, snapshot: PostureSnapshot): Omit<ActivityEntry, "id"> {
  const now = new Date().toISOString();
  return {
    type: "device_change",
    timestamp: now,
    title: `${change.label} changed`,
    detail: `${change.previousValue} → ${change.currentValue}`,
    actor: "System",
    outcome: change.severity === "critical" ? "concern" : "change",
    expandedDetail: change.detail,
    beforeValue: change.previousValue,
    afterValue: change.currentValue,
    source: "device_posture",
    detectedAt: now,
    // We know the snapshot time, not the exact change time
    occurredAt: undefined,
    checkId: change.id,
    groupKey: undefined, // device changes are always individually visible
  };
}

function handlePostureChanges(changes: PostureChange[], snapshot: PostureSnapshot): void {
  if (!changes.length) return;
  const entries = changes.map((c) => postureChangeEntry(c, snapshot));
  void recordActivities(entries);
}

// ── Protection Health → Activity Entries ─────────────────────────────────────

/** Record a completed background health check. */
function recordHealthCheck(health: ProtectionHealthSnapshot): void {
  if (!health.checkedAt || health.checking) return;

  const now = health.checkedAt;
  const failed = health.lastCheckFailure;

  if (failed) {
    // Failed check — record honestly as a failure
    void recordActivity({
      type: "check",
      timestamp: failed.at,
      title: "Protection check failed",
      detail: failed.reason,
      actor: "Apollo",
      outcome: "failure",
      expandedDetail: `Trigger: ${failed.trigger ?? "unknown"}. The previous readings are shown; this check did not complete.`,
      source: "protection_health",
      detectedAt: failed.at,
    });
    return;
  }

  // Successful check — record it (group routine successes)
  const groupKey = `health-check-${now.slice(0, 10)}`;

  void hasTodayEntry(groupKey).then((exists) => {
    // Always record a health check entry; grouping happens in the timeline builder
    void recordActivity({
      type: "check",
      timestamp: now,
      title: "Protection health check",
      detail: `${health.gates.length} gates checked. No issues found.`,
      actor: "Apollo",
      outcome: "success",
      expandedDetail: health.gates.map((g) => `${g.title}: ${g.resolved?.coverageState ?? "unknown"}`).join("\n"),
      source: "protection_health",
      detectedAt: now,
      groupKey: `routine-health-check`,
      verified: true,
    });
  });
}

/** Detect gate status changes between consecutive health snapshots. */
function detectGateChanges(prev: ProtectionHealthSnapshot, next: ProtectionHealthSnapshot): void {
  if (!prev.gates.length || !next.gates.length) return;

  const prevMap = new Map(prev.gates.map((g) => [g.id, g]));
  const now = next.checkedAt ?? new Date().toISOString();

  for (const gate of next.gates) {
    const prevGate = prevMap.get(gate.id);
    if (!prevGate) continue;

    const prevState = prevGate.resolved?.coverageState;
    const nextState = gate.resolved?.coverageState;
    if (prevState === nextState) continue;

    // State changed — record it. Distinguish configured from verified.
    const configured = nextState === "active_verified" || nextState === "active_unverified";
    const verified = nextState === "active_verified";
    const wasActive = prevState === "active_verified" || prevState === "active_unverified";

    let title: string;
    let outcome: ActivityEntry["outcome"];
    let detail: string;

    if (configured && !wasActive) {
      title = verified
        ? `${gate.title}: protection verified active`
        : `${gate.title}: configured but not verified`;
      outcome = verified ? "restored" : "change";
      detail = verified
        ? `${gate.title} is now confirmed operational.`
        : `${gate.title} is configured on, but Apollo has not verified it is actively protecting.`;
    } else if (!configured && wasActive) {
      title = `${gate.title}: protection stopped`;
      outcome = "concern";
      detail = `${gate.title} was active and is no longer running. Previous state: ${prevState ?? "unknown"}.`;
    } else {
      title = `${gate.title}: status changed`;
      outcome = "change";
      detail = `${prevState ?? "unknown"} → ${nextState ?? "unknown"}`;
    }

    void recordActivity({
      type: "protection_action",
      timestamp: now,
      title,
      detail,
      actor: "Apollo detected a change",
      outcome,
      beforeValue: prevState ?? "unknown",
      afterValue: nextState ?? "unknown",
      source: "protection_health",
      detectedAt: now,
      gateId: gate.id,
      verified,
    });
  }
}

/** Record the initial baseline when the app first starts (not a "change"). */
function recordBaseline(health: ProtectionHealthSnapshot): void {
  if (_baselineRecorded || !health.checkedAt || !health.gates.length) return;
  _baselineRecorded = true;

  const now = health.checkedAt;
  const lines = health.gates.map((g) => {
    const state = g.resolved?.coverageState ?? "unknown";
    return `${g.title}: ${state}`;
  });

  void recordActivity({
    type: "check",
    timestamp: now,
    title: "Protection baseline recorded",
    detail: `Initial protection state: ${health.gates.length} gates observed.`,
    actor: "Apollo",
    outcome: "baseline",
    expandedDetail: lines.join("\n"),
    source: "protection_health",
    detectedAt: now,
    groupKey: "baseline",
    verified: true,
  });
}

// ── Public API ───────────────────────────────────────────────────────────────

/** Call when protection health updates (from ApolloContext or health coordinator). */
export function onProtectionHealthUpdate(health: ProtectionHealthSnapshot): void {
  if (health.checking) return; // wait for the check to complete

  if (!_previousHealth) {
    // First observation: record baseline
    recordBaseline(health);
    _previousHealth = health;
    return;
  }

  // Record the completed check
  recordHealthCheck(health);

  // Detect gate changes
  detectGateChanges(_previousHealth, health);

  _previousHealth = health;
}

/** Start capturing device posture changes. Call once at app bootstrap. */
export function startActivityRecorder(): void {
  if (_unsubPosture) return;
  _unsubPosture = onPostureChange(handlePostureChanges);
}

/** Stop capturing. */
export function stopActivityRecorder(): void {
  _unsubPosture?.();
  _unsubPosture = null;
}

/** Record a manual check completion (for checks initiated by the user). */
export async function recordManualCheck(props: {
  title: string;
  detail: string;
  outcome: ActivityEntry["outcome"];
  linkedEventId?: string;
  limitations?: string[];
}): Promise<void> {
  await recordActivity({
    type: "check",
    timestamp: new Date().toISOString(),
    title: props.title,
    detail: props.detail,
    actor: "User submission",
    outcome: props.outcome,
    source: "background_check",
    linkedEventId: props.linkedEventId,
    limitations: props.limitations,
  });
}

/** Record a verified block with enforcement evidence. */
export async function recordVerifiedBlock(props: {
  title: string;
  detail: string;
  actor: string;
  linkedEventId?: string;
}): Promise<void> {
  await recordActivity({
    type: "protection_action",
    timestamp: new Date().toISOString(),
    title: props.title,
    detail: props.detail,
    actor: props.actor,
    outcome: "blocked",
    source: "protection_health",
    linkedEventId: props.linkedEventId,
    verified: true,
  });
}
