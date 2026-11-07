// "How Apollo checks": every part of Apollo is described, in the order a check moves through them, with all
// five results — in plain English, with no internal codes.
import { test } from "node:test";
import assert from "node:assert/strict";

import { CHECK_ROLES, HOW_INTRO, OUTCOME_GUIDE, PROMISES } from "../src/domain/howApolloChecks.ts";
import { looksLikeInternalCode, outcomeLabel } from "../src/domain/messageVoice.ts";

test("the five parts of Apollo appear in the order a check moves through them", () => {
  assert.deepEqual(CHECK_ROLES.map((r) => r.name), ["Apollo", "Higgins Triage", "TC Hawkeye", "Magnum DI", "Higgins"]);
  for (const role of CHECK_ROLES) assert.ok(role.rules.length >= 3 && role.job.trim(), `${role.name} needs a job and its rules`);
});

test("all five results are explained, each with its on-screen label", () => {
  assert.deepEqual(new Set(OUTCOME_GUIDE.map((o) => o.outcome)),
    new Set(["no_scam_indicators", "concerning", "likely_scam", "confirmed_threat", "unable_to_determine"]));
  for (const item of OUTCOME_GUIDE) assert.ok(outcomeLabel(item.outcome));
});

test("plain English only: no internal codes, and nothing is ever promised safe", () => {
  const lines = [HOW_INTRO, ...PROMISES, ...OUTCOME_GUIDE.map((o) => o.meaning), ...CHECK_ROLES.flatMap((r) => [r.job, ...r.rules])];
  for (const line of lines) assert.ok(!looksLikeInternalCode(line), `internal code in: ${line}`);
  for (const line of lines.filter((l) => /\bsafe\b/i.test(l))) assert.match(line, /never|isn't|not/i, `"safe" must only appear negated: ${line}`);
});
