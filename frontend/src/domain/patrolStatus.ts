// Whether a Patrol record is closed, and whether the person closed it. Mirror of backend services/patrol_status.py.
//   closed:  resolved, trusted or carrying a resolved time. A migration or re-judge never reopens a closed record.
//   handled: the person's own decision — trusted, or resolved while Apollo still had a concern (a record Apollo
//            resolved itself is resting). An investigation's answer never reopens a handled record; only the person can.
// Pure: no React, unit-tested in node.
import type { PatrolEvent } from "./types";

export const closed = (e: Pick<PatrolEvent, "status" | "resolved_at">): boolean =>
  e.status === "resolved" || e.status === "trusted" || !!e.resolved_at;

export const handled = (e: Pick<PatrolEvent, "status" | "state">): boolean =>
  e.status === "trusted" || (e.status === "resolved" && e.state !== "resting");
