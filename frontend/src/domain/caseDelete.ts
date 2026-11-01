// Which records go when the person deletes cases (Threats or Patrol history → Select → Delete). Pure, unit-tested.
//   Threats: each row is a whole case — every check filed against it (the same case group) and every record of the
//            investigations behind it.
//   Patrol history: each chosen record, and every record of the investigations it was part of.
// The server deletes its copies of the same set (backend services/case_delete.py).
import { caseGroupKey } from "./threatCase.ts";
import type { PatrolEvent } from "./types";

export const caseIdOf = (e: PatrolEvent): string | null => e.investigation_case_id ?? e.patrol_record?.investigationCaseId ?? null;

export interface DeletionSet { events: PatrolEvent[]; eventIds: string[]; caseIds: string[] }

export function deletionSet(all: PatrolEvent[], chosen: PatrolEvent[], wholeCase: boolean): DeletionSet {
  const ids = new Set(chosen.map((e) => e.event_id));
  const groups = new Set(wholeCase ? chosen.map(caseGroupKey) : []);
  const cases = new Set(chosen.map(caseIdOf).filter((c): c is string => !!c));
  let events: PatrolEvent[] = [];
  // Until nothing more joins: a record brought in by its case group can bring in another investigation's records.
  for (let size = -1; size !== events.length;) {
    size = events.length;
    events = all.filter((e) => ids.has(e.event_id) || groups.has(caseGroupKey(e)) || (!!caseIdOf(e) && cases.has(caseIdOf(e)!)));
    for (const e of events) { const c = caseIdOf(e); if (c) cases.add(c); }
  }
  // A chosen record this phone no longer lists still goes (the server holds its copy).
  for (const e of chosen) if (!events.some((x) => x.event_id === e.event_id)) events.push(e);
  return { events, eventIds: events.map((e) => e.event_id), caseIds: [...cases] };
}

/** "1 case" / "3 cases", "1 record" / "4 records". */
export function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}
