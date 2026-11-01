// Deleting cases (Threats / Patrol history → Select → Delete): which records go with each choice, and a deleted
// record is never sent to the server again from the phone's delivery queue.
import assert from "node:assert/strict";
import { test } from "node:test";

import { countLabel, deletionSet } from "../src/domain/caseDelete.ts";
import { DeliveryQueue } from "../src/store/deliveryQueue.ts";
import type { PatrolEvent } from "../src/domain/types";

const ev = (id: string, over: Partial<PatrolEvent> = {}): PatrolEvent =>
  ({ event_id: id, device_id: "d1", category: "message", state: "growling", status: "active", occurred_at: "2026-11-01T00:00:00Z", ...over }) as PatrolEvent;

const ALL = [
  ev("a1", { case_key: "device-check" }), ev("a2", { case_key: "device-check" }),   // two checks of one case
  ev("b1", { investigation_case_id: "inv-b" }), ev("b2", { investigation_case_id: "inv-b", case_key: "b-run" }),  // one investigation
  ev("c1"),
];

test("deleting a Threats row deletes the whole case: every check of it and every record of its investigation", () => {
  const a = deletionSet(ALL, [ALL[0]], true);
  assert.deepEqual(a.eventIds.sort(), ["a1", "a2"]);
  const b = deletionSet(ALL, [ALL[2]], true);
  assert.deepEqual([b.eventIds.sort(), b.caseIds], [["b1", "b2"], ["inv-b"]]);
  assert.deepEqual(deletionSet(ALL, [ALL[4]], true).eventIds, ["c1"]);
});

test("deleting a Patrol history row deletes that record and its investigation's records, never another check", () => {
  assert.deepEqual(deletionSet(ALL, [ALL[0]], false).eventIds, ["a1"]);
  assert.deepEqual(deletionSet(ALL, [ALL[3]], false).eventIds.sort(), ["b1", "b2"]);
});

test("select all deletes everything once", () => {
  const all = deletionSet(ALL, ALL, true);
  assert.equal(new Set(all.eventIds).size, ALL.length);
  assert.equal(all.eventIds.length, ALL.length);
});

test("counts read naturally", () => {
  assert.deepEqual([countLabel(1, "case"), countLabel(3, "record")], ["1 case", "3 records"]);
});

test("a deleted record pending in the delivery queue is never sent, and isn't queued again", async () => {
  let stored: string | null = null;
  const sent: string[] = [];
  const queue = new DeliveryQueue({
    read: async () => stored, write: async (v) => { stored = v; },
    send: async (body) => { sent.push(String(body.event_id)); return body; }, changed: () => undefined,
  });
  await queue.enqueue({ event_id: "x", device_id: "d1", state: "growling", status: "active", verified_block: false, resolved_at: null });
  await queue.enqueue({ event_id: "y", device_id: "d1", state: "growling", status: "active", verified_block: false, resolved_at: null });
  await queue.forget("d1", ["x"]);
  await queue.enqueue({ event_id: "x", device_id: "d1", state: "barking", status: "active", verified_block: false, resolved_at: null });
  await queue.flush("d1", true);
  assert.deepEqual(sent, ["y"]);
});
