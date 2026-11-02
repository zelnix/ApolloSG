import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { CARRIER_WARNING_LABEL, carrierWarningFinding, isCarrierWarning } from "../src/domain/carrierWarning.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a carrier warning is the person's report, never something ApolloSG saw", () => {
  assert.equal(CARRIER_WARNING_LABEL.potential_fraud, "Warning: Potential Fraud");
  assert.match(carrierWarningFinding("potential_fraud"), /The person reported .*“Warning: Potential Fraud”\. ApolloSG did not see the label itself\./);
  assert.equal(isCarrierWarning("potential_fraud"), true);
  assert.equal(isCarrierWarning("anything_else"), false);
});

test("Australian phones can say they got the warning, from Check a Number and from the carrier row", () => {
  const screen = read("../app/call-guard.tsx");
  assert.match(screen, /inAustralia \? \(\s*<Button testID="callguard-carrier-warning-button" variant="secondary" label="I got a ‘Potential Fraud’ warning"/);
  assert.match(screen, /checkNumberRisk\(number\.trim\(\), undefined, \{ deliberate: true, carrierWarning: carrierWarning \?\? undefined, simulated, origin \}\)/);
  assert.match(screen, /if \(params\.number\) void runInvestigation\(String\(params\.number\)\)/);
  assert.match(screen, /provenance: "user_reported" as const/);
  const row = read("../app/capability/[id].tsx");
  assert.match(row, /row\.id === "au_carrier_scam_blocking"[\s\S]*testID="capability-carrier-warning"[\s\S]*params: \{ carrierWarning: "potential_fraud" \}/);
});

test("with a carrier warning the number always goes to Magnum DI, whatever its reputation", () => {
  const ctx = read("../src/store/ApolloContext.tsx");
  assert.match(ctx, /const reported = options\?\.carrierWarning \? carrierWarningFinding\(options\.carrierWarning\) : null;/);
  assert.match(ctx, /triage\.outcome === "LIMITED_UNABLE_TO_DETERMINE" \|\| reported\) && !investigationCaseId/);
  assert.match(ctx, /\(options\?\.deliberate \|\| reported\) && result\.decision === "unknown"/);
  assert.match(ctx, /\} else if \(reported\) \{[\s\S]*initial_findings: \[reported\]/);
});
