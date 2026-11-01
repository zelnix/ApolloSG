// The owner's rules (2026-11-01): ApolloSG's copy on the phone (text, headers, .eml files, pictures) is kept until the
// person deletes it — no clock on the phone; the 24-hour rule is the server's only, and it waits for the phone.
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { test } from "node:test";

import { heldCopyDeletedNote } from "../src/domain/heldCopies.ts";

const read = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("nothing on the phone deletes a kept copy by its age", () => {
  assert.equal(existsSync(new URL("../src/store/heldCopySweep.ts", import.meta.url)), false, "the phone's 24-hour sweep is gone");
  for (const path of ["src/store/originalSource.ts", "src/store/originalEmail.ts", "src/store/imageEvidence.ts", "src/store/ApolloContext.tsx", "src/domain/triage/rejudge.ts"]) {
    const code = read(path);
    assert.doesNotMatch(code, /heldCopyExpired|heldCopyDue|sweepHeldCopies|sweepOriginalEmails|sweepImageEvidence/, path);
  }
});

test("a saved original is enriched, never replaced or skipped, when more arrives", () => {
  const code = read("src/store/originalSource.ts");
  assert.match(code, /enrichOriginal\(found, record\)/);
  assert.doesNotMatch(code, /!\(await read\(k\)\)/, "an existing record no longer makes a save skip");
});

test("where an earlier version deleted its copy after 24 hours, the case says when, why it's gone and where the message still is", () => {
  const note = heldCopyDeletedNote("Oct 31, 2026, 9:41 AM");
  assert.match(note, /^This phone's copy of the original was deleted on Oct 31, 2026, 9:41 AM by an earlier version of ApolloSG/);
  assert.match(note, /24-hour rule that has since been removed/);
  assert.match(note, /can't be recovered/);
  assert.match(note, /Messages or email app was never touched/);
  assert.match(note, /What Apollo found is kept above\.$/);
  assert.match(heldCopyDeletedNote(null), /^This phone's copy of the original was deleted by an earlier version/);
});
