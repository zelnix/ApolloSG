// "Calls Apollo screened" — the incoming numbers Android handed to Apollo's CallScreeningService.
// Pure parsing and wording only; the native read lives in src/security/screenedCalls.ts.
// This is NOT the device's call log: Android usually only passes Apollo calls from numbers that
// aren't in your contacts, and only while Apollo is the device's caller ID & spam app.

export type ScreenedOutcome = "rang" | "allowed_by_you" | "rejection_requested_block" | "rejection_requested_risky";
/** A Repeat Caller Alert the screening service raised for this call, and whether Android showed it. */
export type RepeatReason = "block_list" | "high_risk" | "worth_checking";
export interface RepeatAlert { reason: RepeatReason; shown: boolean; title: string; body: string }
export type NumberVerification = "passed" | "failed" | "not_verified" | "unavailable";\nexport interface ScreenedCall { number: string; at: number; outcome: ScreenedOutcome; numberVerification: NumberVerification; repeat?: RepeatAlert }

const OUTCOMES: ReadonlySet<string> = new Set(["rang", "allowed_by_you", "rejection_requested_block", "rejection_requested_risky"]);
const VERIFICATIONS: ReadonlySet<string> = new Set(["passed", "failed", "not_verified", "unavailable"]);\nconst REPEAT_REASONS: ReadonlySet<string> = new Set(["block_list", "high_risk", "worth_checking"]);

/** What Apollo did when Android handed it the call. Rejections are requests — Android gives no receipt. */
export const SCREENED_OUTCOME_LABEL: Record<ScreenedOutcome, string> = {
  rang: "Rang through — no warning on this device",
  allowed_by_you: "On your allow list — rang through",
  rejection_requested_block: "On your block list — ApolloSG asked Android to reject it",
  rejection_requested_risky: "Found high-risk earlier — ApolloSG asked Android to reject it",
};

export function isRejectionRequest(outcome: ScreenedOutcome): boolean {
  return outcome === "rejection_requested_block" || outcome === "rejection_requested_risky";
}

/** Strict parse of the native JSON. Malformed rows are dropped; newest first. */
export function parseScreenedCalls(json: string | null | undefined): ScreenedCall[] {
  if (!json) return [];
  let raw: unknown;
  try { raw = JSON.parse(json); } catch { return []; }
  if (!Array.isArray(raw)) return [];
  const rows: ScreenedCall[] = [];
  for (const item of raw) {
    const row = item as { number?: unknown; at?: unknown; outcome?: unknown; repeat?: unknown; alert?: unknown; alertTitle?: unknown; alertBody?: unknown; numberVerification?: unknown };
    if (typeof row?.number !== "string" || !row.number.trim()) continue;
    if (typeof row.at !== "number" || !Number.isFinite(row.at)) continue;
    if (typeof row.outcome !== "string" || !OUTCOMES.has(row.outcome)) continue;
    const repeat = typeof row.repeat === "string" && REPEAT_REASONS.has(row.repeat) && (row.alert === "shown" || row.alert === "not_shown")
      && typeof row.alertTitle === "string" && typeof row.alertBody === "string"
      ? { reason: row.repeat as RepeatReason, shown: row.alert === "shown", title: row.alertTitle, body: row.alertBody }
      : undefined;
    rows.push({ number: row.number.trim(), at: row.at, outcome: row.outcome as ScreenedOutcome, numberVerification: typeof row.numberVerification === "string" && VERIFICATIONS.has(row.numberVerification) ? row.numberVerification as NumberVerification : "unavailable", ...(repeat ? { repeat } : {}) });
  }
  return rows.sort((a, b) => b.at - a.at);
}

/** The row's outcome line. A number found worth checking still rings, but Apollo did warn — so never "no warning". */
export function screenedOutcomeLabel(call: ScreenedCall): string {
  return call.outcome === "rang" && call.repeat?.reason === "worth_checking" ? "Found worth checking earlier — rang through" : SCREENED_OUTCOME_LABEL[call.outcome];
}

/** Whether the Repeat Caller Alert for this call was shown, in plain words. */
export function repeatAlertLine(call: ScreenedCall): string | null {
  if (!call.repeat) return null;
  return call.repeat.shown ? "Repeat caller — ApolloSG alerted you" : "Repeat caller — not shown, because ApolloSG's notifications are off";
}

/** Repeat Caller Alerts newer than `sinceMs`, oldest first, as rows for the on-device alert history. */
export function repeatAlertLogRows(calls: ScreenedCall[], sinceMs: number) {
  return calls
    .filter((c): c is ScreenedCall & { repeat: RepeatAlert } => !!c.repeat && c.at > sinceMs)
    .sort((a, b) => a.at - b.at)
    .map((c) => ({
      id: `repeat-${c.at}`, title: c.repeat.title, body: c.repeat.body, at: new Date(c.at).toISOString(),
      state: c.repeat.shown ? "shown" as const : "failed" as const,
      detail: c.repeat.shown ? null : "Notifications for ApolloSG are off on this device, so Android didn't show this alert.",
    }));
}

/** "Today" / "Yesterday" / "Tue 21 Oct" plus a time, for a screened-call row. */
export function screenedWhen(at: number, now: Date = new Date()): { day: string; time: string } {
  const d = new Date(at);
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  const day = d.toDateString() === now.toDateString() ? "Today"
    : d.toDateString() === yesterday.toDateString() ? "Yesterday"
    : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return { day, time: d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) };
}
