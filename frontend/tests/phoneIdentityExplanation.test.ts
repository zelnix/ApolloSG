import assert from "node:assert/strict";
import test from "node:test";
import type { PhoneIdentityResult } from "../src/api/phoneIdentity.ts";
import { explainIdentity } from "../src/domain/phoneIdentityExplanation.ts";

const unknown: PhoneIdentityResult = {
  canonical: "+61299363990", original: "0299363990", country: "Australia", number_type: "Landline",
  geographic: "New South Wales, ACT", valid: true, network: null,
  associated_entity: null, association_confidence: "unknown", evidence: [], scam_intel: null,
  known_impersonation: false, prefix_intelligence: [], checked_at: null, freshness: "fresh",
  lookup_status: { org_directory: "no_match", apollo_kb: "no_match", web_search: "not_checked" },
};

test("an unknown number shows useful facts and advice without creating a scam verdict or claiming web checks", () => {
  const before = JSON.stringify(unknown);
  const explanation = explainIdentity(unknown);
  assert.match(explanation.headline, /couldn't identify/);
  assert.match(explanation.body, /landline number from Australia/);
  assert.match(explanation.body, /New South Wales, ACT/);
  assert.match(explanation.body, /doesn't mean the call is genuine or a scam/);
  assert.match(explanation.whatToDo, /verify independently/);
  assert.doesNotMatch(explanation.headline + explanation.body + explanation.whatToDo, /likely a scam|unregistered|checked.*public web|try calling the number back/i);
  assert.equal(JSON.stringify(unknown), before, "presentation must not modify the source evidence");
});

test("unavailable lookup providers are not reported as completed checks", () => {
  const explanation = explainIdentity({ ...unknown, lookup_status: { org_directory: "unavailable", web_search: "timeout" } });
  assert.doesNotMatch(explanation.body, /checked its|checked.*web|no.*fraud|safe/i);
});

test("recorded abuse intelligence is still shown for an unknown owner", () => {
  const explanation = explainIdentity({ ...unknown, scam_intel: "Recent abuse reports recorded." });
  assert.equal(explanation.scamWarning, "Recent abuse reports recorded.");
  assert.match(explanation.whatToDo, /flagged in fraud or abuse reports/);
});
