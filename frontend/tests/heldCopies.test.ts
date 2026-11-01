// ApolloSG's own copy of what was checked on this phone is kept for 24 hours, then deleted (owner's rule, 2026-11).
import assert from "node:assert/strict";
import { test } from "node:test";

import { HELD_COPY_DELETED, HELD_COPY_HOURS, HELD_COPY_KINDS, heldCopyDue, heldCopyExpired } from "../src/domain/heldCopies.ts";

const NOW = Date.parse("2026-11-01T12:00:00Z");
const ago = (hours: number) => new Date(NOW - hours * 3600_000).toISOString();

test("a held copy goes exactly 24 hours after it was made, never sooner", () => {
  assert.equal(HELD_COPY_HOURS, 24);
  assert.equal(heldCopyExpired(ago(23.99), NOW), false, "inside 24 hours it stays");
  assert.equal(heldCopyExpired(ago(24), NOW), true, "at 24 hours it is deleted");
  assert.equal(heldCopyExpired(ago(72), NOW), true);
});

test("a copy with no time recorded can't be shown to be within its 24 hours, so it is deleted", () => {
  assert.equal(heldCopyExpired(null, NOW), true);
  assert.equal(heldCopyExpired("not a date", NOW), true);
});

test("only copies of what the person checked are held copies; Apollo's own device readings are its records", () => {
  for (const kind of ["email", "text", "link", "website", "screenshot", "file", "app", "account"]) {
    assert.ok(HELD_COPY_KINDS.has(kind), kind);
    assert.equal(heldCopyDue({ kind, capturedAt: ago(25) }, NOW), true, kind);
    assert.equal(heldCopyDue({ kind, capturedAt: ago(1) }, NOW), false, kind);
  }
  for (const kind of ["network", "device", "call"]) assert.equal(heldCopyDue({ kind, capturedAt: ago(25) }, NOW), false, kind);
});

test("where the original was, the case says ApolloSG deleted its copy and kept what it found", () => {
  assert.match(HELD_COPY_DELETED, /deleted its copy of the original 24 hours after it was checked/);
  assert.match(HELD_COPY_DELETED, /What Apollo found is kept/);
});
