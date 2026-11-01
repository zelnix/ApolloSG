// "New" on a case: it arrived on this phone after ApolloSG started keeping track, and the person hasn't opened it yet.
// Cases already on the phone when tracking started are never New. Pure: no React, no storage, unit-tested in node.
import type { PatrolEvent } from "./types";

export interface SeenCases {
  /** When tracking started on this phone (ISO). Cases recorded before then are never New. */
  startedAt: string;
  /** Cases the person has opened. */
  ids: string[];
}

export function isNewCase(e: Pick<PatrolEvent, "event_id" | "occurred_at">, seen: SeenCases | null): boolean {
  if (!seen) return false;
  const at = Date.parse(e.occurred_at ?? "");
  return !Number.isNaN(at) && at > Date.parse(seen.startedAt) && !seen.ids.includes(e.event_id);
}

/** `seen` with this case opened, keeping the newest `max` ids. */
export function withSeen(seen: SeenCases, eventId: string, max = 5000): SeenCases {
  if (seen.ids.includes(eventId)) return seen;
  return { ...seen, ids: [...seen.ids, eventId].slice(-max) };
}
