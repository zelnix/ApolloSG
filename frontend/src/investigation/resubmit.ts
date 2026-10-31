// Resubmitting a stopped investigation. Magnum DI makes at most one Gemini call per case and never retries it; only a
// case stopped before that call was made can be resubmitted. The server sets `resubmitAt` and the Resubmit button waits until then.
// The case keeps everything the person submitted, so resubmitting sends the same material again. Pure — no React Native imports.
import type { Failure } from "./types";

/** Whole seconds until resubmitting is allowed; 0 when it already is (or the server set no pause). */
export function resubmitWaitSeconds(failure: Pick<Failure, "resubmitAt"> | null | undefined, now = Date.now()): number {
  const at = failure?.resubmitAt ? Date.parse(failure.resubmitAt) : NaN;
  return Number.isFinite(at) ? Math.max(0, Math.ceil((at - now) / 1000)) : 0;
}

/** m:ss, e.g. 4:05. */
export function formatWait(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** A failure another attempt cannot fix (e.g. a configuration fault) offers no Resubmit. */
export function canResubmit(failure: Pick<Failure, "retryable"> | null | undefined): boolean {
  return failure?.retryable !== false;
}

export function resubmitLabels(waitSeconds: number, busy: boolean): { title: string; description: string } {
  if (busy) return { title: "Resubmitting…", description: "Magnum DI is starting again with what you submitted" };
  if (waitSeconds > 0) return { title: `Resubmit in ${formatWait(waitSeconds)}`, description: "Magnum DI needs a short pause first. Everything you submitted is kept." };
  return { title: "Resubmit", description: "Sends what you submitted again — nothing to re-enter" };
}

// ── Quiet reminder on Ask Higgins ────────────────────────────────────────────
// When a stopped investigation is not on screen, Ask Higgins shows one quiet note once it can be resubmitted.
// The note goes when the case is resubmitted, answered, removed, dismissed or past its own expiry.

export interface StoppedCase { caseId: string; jobId: string; resubmitAt: string; expiresAt: string; status: "waiting" | "dismissed" }

/** The stopped case to remind about now: ready to resubmit, not dismissed, not expired, not already on screen. */
export function dueReminder(items: StoppedCase[], now: number, openCaseId: string | null): StoppedCase | null {
  // A malformed time parses to NaN and every comparison with NaN is false, so it never reminds.
  return items.find((item) => item.status === "waiting" && item.caseId !== openCaseId
    && Date.parse(item.resubmitAt) <= now && now < Date.parse(item.expiresAt)) ?? null;
}

/** Remember (or refresh) one stopped case; drop cases that have expired. A new pause re-arms a dismissed note. */
export function withStopped(items: StoppedCase[], stopped: Omit<StoppedCase, "status">, now: number): StoppedCase[] {
  const kept = items.filter((item) => item.caseId !== stopped.caseId && now < Date.parse(item.expiresAt));
  const previous = items.find((item) => item.caseId === stopped.caseId);
  const status = previous && previous.resubmitAt === stopped.resubmitAt ? previous.status : "waiting";
  return [...kept, { ...stopped, status }];
}
