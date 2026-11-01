// The owner's rules (2026-11-01): ApolloSG's copy on the phone (text, headers, .eml files, pictures) is kept until the
// person deletes it — no clock on the phone; the 24-hour rule is the server's only, and it waits for the phone.
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { test } from "node:test";

import { HELD_COPY_DELETED } from "../src/domain/heldCopies.ts";

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

test("where an earlier version deleted its copy after 24 hours, the case still says so", () => {
  assert.match(HELD_COPY_DELETED, /An earlier version of ApolloSG deleted its copy of the original 24 hours after it was checked/);
  assert.match(HELD_COPY_DELETED, /What Apollo found is kept/);
});
