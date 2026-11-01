// The "New" badge (src/domain/newCases.ts): a case that arrived after tracking started, until the person opens it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { isNewCase, withSeen, type SeenCases } from "../src/domain/newCases.ts";

const SEEN: SeenCases = { startedAt: "2026-11-01T06:00:00.000Z", ids: [] };
const at = (event_id: string, occurred_at: string) => ({ event_id, occurred_at });

test("a case that arrived after tracking started is New until it is opened", () => {
  const fresh = at("e-new", "2026-11-01T06:30:00.000Z");
  assert.equal(isNewCase(fresh, SEEN), true);
  const opened = withSeen(SEEN, "e-new");
  assert.equal(isNewCase(fresh, opened), false, "opening it clears New");
  assert.equal(withSeen(opened, "e-new"), opened, "opening it again changes nothing");
});

test("cases already on the phone when tracking started are never New", () => {
  assert.equal(isNewCase(at("e-old", "2026-10-30T01:40:51.000Z"), SEEN), false);
  assert.equal(isNewCase(at("e-bad", "not a time"), SEEN), false);
  assert.equal(isNewCase(at("e-new", "2026-11-01T06:30:00.000Z"), null), false, "nothing is New before the record is read");
});

test("only the newest opened cases are remembered", () => {
  let seen = SEEN;
  for (let i = 0; i < 5; i++) seen = withSeen(seen, `e${i}`, 3);
  assert.deepEqual(seen.ids, ["e2", "e3", "e4"]);
});
