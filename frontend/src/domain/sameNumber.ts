// Same Number Reminder: when a person checks a number, what Apollo said about the same number in the last 30 days —
// an earlier check on this phone, or a case about it — so they see the earlier result before today's.
// Pure: unit-tested in node (tests/sameNumber.test.ts).
import type { ApolloState, PatrolEvent } from "./types";

export const REMINDER_DAYS = 30;
const DAY_MS = 86_400_000;
const SAME_OCCASION_MS = 5 * 60_000;

/** The same number however it was written: digits only, an Australian +61 number in its 0 form. */
export function numberDigits(n: string): string {
  const d = n.replace(/\D/g, "");
  return d.startsWith("61") && d.length >= 11 ? `0${d.slice(2)}` : d;
}

/** An earlier check as the check history keeps it: the number only as a one-way code (`numberKey`). */
export interface EarlierHistoryEntry { at: string; state: ApolloState; summary: string; numberKey?: string }

export interface EarlierCheck {
  /** "check": the person checked it before; "case": a case on this phone is about it. */
  source: "check" | "case";
  /** Who started the case, when it is one. */
  origin: "user" | "apollo" | "sample_check" | null;
  at: string;
  state: ApolloState;
  summary: string;
  /** The latest case about the number, to open — whichever record is shown. */
  eventId: string | null;
  /** Every earlier record of the number in the window. */
  count: number;
}

const isCall = (e: PatrolEvent) => e.category === "call" || e.source_metadata?.type === "call";

/** The latest earlier result for the number within the window, or null. `events` and `history` must be read BEFORE
 *  today's check, so today's never counts as earlier. */
export function earlierCheck({ number, key, events, history, now }: {
  number: string; key: string | null; events: PatrolEvent[]; history: EarlierHistoryEntry[]; now: number;
}): EarlierCheck | null {
  const digits = numberDigits(number);
  if (digits.length < 6) return null;
  const since = now - REMINDER_DAYS * DAY_MS;
  const recent = (at: string) => { const t = Date.parse(at); return Number.isFinite(t) && t >= since && t <= now; };
  const cases = events
    .filter((e) => isCall(e) && recent(e.occurred_at) && [e.local_indicator, e.source_metadata?.sender].some((n) => !!n && numberDigits(n) === digits))
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));
  const checks = key ? history.filter((h) => h.numberKey === key && recent(h.at)) : [];
  // A check that opened a case is one occasion, not two: the case is filed moments before the check is recorded.
  const openedByCheck = (e: PatrolEvent) => e.origin === "user"
    && checks.some((h) => Math.abs(Date.parse(h.at) - Date.parse(e.occurred_at)) <= SAME_OCCASION_MS);
  const all = [
    ...checks.map((h) => ({ source: "check" as const, origin: null, at: h.at, state: h.state, summary: h.summary })),
    ...cases.filter((e) => !openedByCheck(e))
      .map((e) => ({ source: "case" as const, origin: e.origin ?? null, at: e.occurred_at, state: e.state, summary: e.headline })),
  ].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  if (!all.length) return null;
  return { ...all[0], eventId: cases[0]?.event_id ?? null, count: all.length };
}

/** "today", "yesterday", "5 days ago". */
export function daysAgo(at: string, now: number): string {
  const days = Math.floor((startOfDay(now) - startOfDay(Date.parse(at))) / DAY_MS);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}
const startOfDay = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };

/** The reminder's heading: who looked at the number before. */
export function reminderTitle(e: EarlierCheck): string {
  if (e.source === "case" && e.origin === "sample_check") return "This number was checked in a Sample Check";
  return e.source === "case" && e.origin === "apollo" ? "Apollo has seen this number before" : "You checked this number before";
}
