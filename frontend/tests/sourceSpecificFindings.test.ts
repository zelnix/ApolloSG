import assert from "node:assert/strict";
import test from "node:test";
import { gateCheckResult } from "../src/domain/gateCheckResult.ts";
import { phoneIncompleteChecks, type EvidencePhoneResult } from "../src/domain/phoneNumbers.ts";
import { threatCaseStatus } from "../src/domain/threatCase.ts";
import { buildDecisionTrace } from "../src/domain/diTrace.ts";
import { fromSources, urlIncompleteChecks } from "../src/domain/triage/completeness.ts";
import { serviceFunction, plainServiceText, serviceSubject } from "../src/domain/checkServicePresentation.ts";
import type { TriageInvestigationRecord } from "../src/domain/triage/contract.ts";
import type { PatrolEvent } from "../src/domain/types.ts";
import type { OriginalSource } from "../src/store/originalSource.ts";

const source: OriginalSource = { kind: "email", origin: "this_device", capturedAt: "2026-11-14T00:00:00Z",
  fields: [{ label: "From", value: "Google <no-reply@accounts.google.com>" }, { label: "Subject", value: "Account access notification" }],
  text: "You allowed account-tools.example access to your Google account. If this was not you, review account activity through your account settings." };
const record = (over: Partial<TriageInvestigationRecord> = {}): TriageInvestigationRecord => ({
  investigationId: "intake-1", catalogueVersion: 5, sourceType: "email", outcome: "NO_THREAT_IDENTIFIED", reason: "Historical wording",
  rulesApplicable: ["EMAIL-01"], rulesChecked: ["EMAIL-01"], rulesMet: [], rules: [], coverageGaps: [], retries: [],
  correlation: {}, recheckUseful: false, geminiCalls: 0, evaluatedAt: "2026-11-14T00:01:00Z", ...over,
});
const event = (t = record()): PatrolEvent => ({ event_id: "email-1", device_id: "this-device", category: "email", state: "barking", status: "active",
  headline: "Old warning", occurred_at: "2026-11-14T00:00:00Z", resolved_at: null, triage_investigation: t,
  why: [], what_to_do: "Delete this scam email.", source_metadata: { type: "email", sender: "old-summary@example.test", subject: "Old summary" },
} as unknown as PatrolEvent);

test("Findings describes the retained email and its exact unavailable check without rewriting evidence", () => {
  const t = record({ incompleteChecks: [{ check: "reputation", status: "unavailable", failure: "dns_failed",
    source: "spamhaus_drop", subject: "https://mail-link.example/path?token=private", at: null,
    detail: "Apollo could not find this website's IP address to compare with Spamhaus DROP." }] });
  const before = JSON.stringify({ t, source });
  const result = gateCheckResult(event(t), source)!;
  const report = JSON.stringify(result.report);
  assert.match(report, /Account access notification/);
  assert.match(report, /no-reply@accounts.google.com/);
  assert.match(report, /allowed account-tools.example access/);
  assert.match(report, /Internet address validation for mail-link.example/);
  assert.doesNotMatch(report, /Spamhaus|IP address|old-summary|Delete this scam|token=private/);
  assert.equal(result.label, "Not fully checked");
  assert.equal(result.status, "not_fully_checked");
  assert.equal(JSON.stringify({ t, source }), before);
});

test("two different emails produce different source observations even with identical screening counts", () => {
  const other: OriginalSource = { ...source, fields: [{ label: "From", value: "Shop <shop@example.test>" }, { label: "Subject", value: "Delivery confirmation" }], text: "Your order has been delivered to the collection point." };
  const a = gateCheckResult(event(), source)!.report;
  const b = gateCheckResult(event(), other)!.report;
  assert.notDeepEqual(a.found, b.found);
  assert.match(JSON.stringify(b), /Delivery confirmation|order has been delivered/);
  assert.doesNotMatch(JSON.stringify(b), /Google account|account-tools/);
});

test("zero flags is a routing result, and missing evidence does not become Not a Scam", () => {
  assert.equal(gateCheckResult(event(), source)!.admission, "no_flags");
  const missing = gateCheckResult(event(record({ outcome: "LIMITED_UNABLE_TO_DETERMINE", rulesChecked: [] })), null)!;
  assert.equal(missing.admission, "insufficient_evidence");
  assert.equal(missing.status, "not_fully_checked");
  assert.match(missing.report.uncertain.join(" "), /content is not included/);
});

test("triage records flags for Hawkeye and never claims its own investigation Finding", () => {
  const t = record({ outcome: "POSSIBLE_THREAT_IDENTIFIED", rulesMet: ["EMAIL-01"] });
  const result = gateCheckResult(event(t), source)!;
  assert.equal(result.admission, "investigate");
  assert.equal(result.label, "Investigation warranted");
  const trace = buildDecisionTrace({ trace: null, records: [], triage: t, hasCase: false, presented: { verdict: result.label, risk: null } });
  assert.equal(trace.find((s) => s.id === "triage")?.label, "Investigation warranted");
  assert.equal(trace.find((s) => s.id === "flyby")?.status, "not_engaged");
  assert.equal(trace.find((s) => s.id === "lock")?.status, "not_engaged");
});

test("Gate failures keep their function and target outside triage's admission details", () => {
  const incomplete = fromSources([{ name: "google_web_risk", status: "unavailable", check: "reputation", failure: "quota_exhausted" }], "https://one.example/path");
  const t = record({ incompleteChecks: incomplete });
  const trace = buildDecisionTrace({ trace: null, records: [], triage: t, hasCase: false });
  const limits = trace.find((s) => s.id === "gate")!;
  assert.match(limits.details.join(" "), /Website threat checking for one.example/);
  assert.match(limits.details.join(" "), /allowance is used up/);
  assert.doesNotMatch(limits.details.join(" "), /Google|google_web_risk/);
  assert.doesNotMatch(trace.find((s) => s.id === "triage")!.details.join(" "), /allowance|quota|Website threat checking/);
});

test("different targets and services are retained when their failure codes match", () => {
  const first = fromSources([{ name: "spamhaus_drop", status: "unavailable", failure: "timeout" }], "https://one.example");
  const second = fromSources([{ name: "google_web_risk", status: "unavailable", failure: "timeout" }], "https://two.example");
  assert.equal(urlIncompleteChecks([{ coverage: "partial", incomplete: first }, { coverage: "partial", incomplete: second }]).length, 2);
  assert.equal(serviceFunction("Spamhaus DROP", "reputation"), "Internet address validation");
  assert.equal(plainServiceText("Google security alert: Spamhaus DROP couldn't find its IP address."), "Google security alert: Internet address validation couldn't find its internet address.");
});


test("closing a screening record does not turn its unfinished checks into clearance", () => {
  const e = { ...event(record({ incompleteChecks: [{ check: "reputation", status: "unavailable", failure: "timeout", source: "spamhaus_drop", detail: "", at: null }] })), state: "resting" as const, resolved_at: "2026-11-14T00:02:00Z" };
  assert.equal(threatCaseStatus(e), "not_fully_checked");
  assert.equal(e.resolved_at, "2026-11-14T00:02:00Z", "the recorded closure is unchanged");
});


test("two failed phone checks keep their respective numbers", () => {
  const checks = phoneIncompleteChecks(["+61400000001", "+61400000002"].map((number) => ({ number, raw: number, decision: "unknown", lookupFailure: "quota_exhausted", source: "unavailable" } as EvidencePhoneResult)));
  assert.deepEqual(checks.map((c) => c.subject), ["+61400000001", "+61400000002"]);
  assert.equal(serviceSubject("1800123"), "1800123", "a number must not be reformatted as a website address");
});
