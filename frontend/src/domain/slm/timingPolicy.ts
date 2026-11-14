export const CHAT_DEADLINE_MS = 45000;
export const NATIVE_GENERATION_MAX_MS = 90000;
export function stageBudgetMs(windows: number, windowLatencyMs: number, overheadMs = 15000) {
  if (!Number.isSafeInteger(windows) || windows < 1 || !Number.isFinite(windowLatencyMs) || windowLatencyMs <= 0 || overheadMs < 0) throw Error("Invalid timing measurements");
  return Math.min(300000, Math.max(90000, Math.ceil(windows * windowLatencyMs * 1.25 + overheadMs)));
}
export function remainingMs(deadline: number, now = Date.now()) {
  if (!Number.isFinite(deadline)) throw Error("Invalid deadline");
  return Math.max(0, deadline - now);
}
