// Incomplete checks, granular failures, stale number scores and callback-scam detection — device mirror of
// backend tests/test_incomplete_checks.py. Run: node --test tests/incompleteChecks.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { evaluateTriage } from "../src/domain/triage/engine.ts";
import { outcomeLabel, OUTCOME_LABEL } from "../src/domain/triage/contract.ts";
import { AVAILABLE_CHECKS, fromSources, incompleteCheck, incompletePlain, urlIncompleteChecks } from "../src/domain/triage/completeness.ts";
import { linkTriageEvidence, messageTriageEvidence, numberRiskTriageEvidence } from "../src/domain/triage/evidence.ts";
import { incompleteCodes, limitedCauses, numberLookupFailure, triageTelemetry } from "../src/domain/triage/limitedCause.ts";
import { phoneIncompleteChecks, phoneTriageReputation, type EvidencePhoneResult } from "../src/domain/phoneNumbers.ts";
import type { MessageUrlResult } from "../src/domain/urlIntel.ts";
import { analyseMessage } from "../src/domain/messageAnalysis.ts";
import { analyseUrlLocally } from "../src/domain/risk.ts";
import { decide } from "../src/domain/decision.ts";
import { parseIntelResult } from "../src/domain/intelContract.ts";

const phone = (over: Partial<EvidencePhoneResult>): EvidencePhoneResult => ({
  raw: "0412 345 678", number: "+61412345678", decision: "unknown", fraud_score: null, recent_abuse: null, voip: null,
  line_type: null, carrier: null, country: null, source: "unavailable", checked_at: "2026-06-01T00:00:00Z", ...over,
});

test("Safe Browsing down with the blocklist answering: No threat found by available checks, worded by check", () => {
  const local = analyseUrlLocally("https://www.abc.net.au/news");
  const record = evaluateTriage(linkTriageEvidence({ local, intel: { verdict: "clean", coverage: "partial", sources: [
    { name: "apollo_blocklist", status: "clear" },
    { name: "google_safe_browsing", status: "unavailable", check: "reputation", failure: "quota_exhausted" },
  ] } }));
  assert.equal(record.outcome, "NO_THREAT_IDENTIFIED");
  assert.equal(outcomeLabel(record), AVAILABLE_CHECKS);
  assert.equal(record.coverage, "incomplete");
  assert.match(record.reason, /^No threat found by available checks\. Not completed: Website threat checking: A reputation check didn't complete \(its lookup allowance is used up for now\)\./);
  assert.doesNotMatch(record.reason, /Google|Safe Browsing/);
  assert.deepEqual(incompleteCodes(record), ["reputation_quota_exhausted"]);
});

test("every check completed keeps the unqualified No threat identified", () => {
  const local = analyseUrlLocally("https://www.abc.net.au/news");
  const record = evaluateTriage(linkTriageEvidence({ local, intel: { verdict: "clean", coverage: "full", sources: [{ name: "b", status: "clear" }] } }));
  assert.equal(outcomeLabel(record), OUTCOME_LABEL.NO_THREAT_IDENTIFIED);
  assert.equal(record.coverage, "complete");
  assert.deepEqual(record.incompleteChecks, []);
});

test("an unverified final destination is an incomplete check, never a coverage gap or Limited", () => {
  const local = analyseUrlLocally("https://bit.ly/abc");
  const record = evaluateTriage(linkTriageEvidence({ local, intel: {
    verdict: "clean", coverage: "partial", redirect_chain: ["bit.ly", "gone.example"], final_url: null,
    sources: [{ name: "b", status: "clear" }, { name: "redirect_expansion", status: "unavailable", check: "final_destination", failure: "nonexistent_domain" }],
  } }));
  const link02 = record.rules.find((r) => r.ruleId === "LINK-02");
  assert.equal(link02?.result, "not_met");
  assert.ok(!record.coverageGaps.some((g) => g.code === "NETWORK_CHECK_FAILED"));
  assert.notEqual(record.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  assert.ok(record.reason.includes("Apollo couldn't verify where this link finally leads (the website's address doesn't exist)."), record.reason);
});

test("no source answering stays Limited, with the failure kind on the gap", () => {
  const local = analyseUrlLocally("https://www.abc.net.au/news");
  const record = evaluateTriage(linkTriageEvidence({ local, intel: null, intelError: "x", intelFailure: "timeout" }));
  assert.equal(record.outcome, "LIMITED_UNABLE_TO_DETERMINE");
  assert.equal(record.coverageGaps.find((g) => g.code === "INTELLIGENCE_PROVIDER_UNAVAILABLE")?.failure, "timeout");
  assert.deepEqual(limitedCauses(record), ["reputation_timeout"]);
});

test("an ordinary message with a failed number lookup is not Limited", () => {
  const analysis = analyseMessage("Sam", "Hi, it's Sam from the gym. Call me back on 0412 345 678 when you're free.");
  assert.equal(analysis.signals.callbackRequest, true);
  assert.equal(analysis.signals.allegedCharge, false);
  const phones = [phone({ lookupFailure: "quota_exhausted" })];
  const record = evaluateTriage(messageTriageEvidence({ analysis, linkOutcome: null,
    phoneReputation: phoneTriageReputation(phones), incompleteChecks: phoneIncompleteChecks(phones) }));
  assert.equal(record.outcome, "NO_THREAT_IDENTIFIED");
  assert.equal(outcomeLabel(record), AVAILABLE_CHECKS);
  assert.deepEqual(incompleteCodes(record), ["number_reputation_quota_exhausted"]);
});

test("a stale number score is used, and recorded as incomplete", () => {
  const record = evaluateTriage(numberRiskTriageEvidence({ decision: "allow", fraudScore: 10, freshness: "stale", failure: "timeout", checkedAt: "2026-06-01T00:00:00Z" }));
  assert.equal(record.outcome, "NO_THREAT_IDENTIFIED");
  assert.equal(outcomeLabel(record), AVAILABLE_CHECKS);
  assert.deepEqual(incompleteCodes(record), ["number_reputation_stale"]);
  assert.deepEqual(phoneIncompleteChecks([phone({ decision: "allow", freshness: "stale", lookupFailure: "timeout", source: "ipqualityscore" })])
    .map((c) => c.status), ["stale"]);
  assert.deepEqual(phoneIncompleteChecks([phone({ decision: "allow", freshness: "cached", source: "ipqualityscore" })]), []);
});

test("number telemetry carries the server's failure kind", () => {
  assert.equal(numberLookupFailure({ decision: "unknown", source: "unavailable", failure: "quota_exhausted" }), "quota_exhausted");
  const record = evaluateTriage(numberRiskTriageEvidence({ decision: "unknown", failure: "auth_failure" }));
  assert.deepEqual(limitedCauses(record), ["reputation_auth_failure"]);
  const allowed = triageTelemetry(evaluateTriage(numberRiskTriageEvidence({ decision: "allow", fraudScore: 5 })));
  assert.equal(allowed.outcome, "NO_THREAT_IDENTIFIED");
  assert.deepEqual(allowed.incomplete, []);
});

test("an unexpected charge with urgency and a callback number is a high-risk callback scam", () => {
  const analysis = analyseMessage("", "Your account has been charged $899 for an Apple order. Call 1800 123 456 now to cancel.");
  assert.equal(analysis.signals.callbackNumber, "1800 123 456");
  assert.equal(analysis.signals.allegedCharge, true);
  assert.equal(analysis.state, "barking");
  assert.equal(analysis.scenarioTitle, "Alleged-charge callback trap");
  assert.doesNotMatch(analysis.recommendation, /PayPal/);
  const record = evaluateTriage(messageTriageEvidence({ analysis, linkOutcome: null, phoneReputation: { status: "unavailable", verdict: "unknown" } }));
  assert.equal(record.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  assert.ok(record.rulesMet.includes("CB-01"));
});

test("a charge with dispute wording and a 13 number counts; a charge or a number alone does not", () => {
  assert.equal(analyseMessage("", "A payment of $450 was made. If this wasn't you call 13 22 21.").signals.allegedCharge, true);
  const order = analyseMessage("Shop", "Your order of $45 has shipped. Track it in the app.");
  assert.equal(order.signals.allegedCharge, false);
  assert.equal(order.state, "resting");
  assert.equal(analyseMessage("Sam", "My number is 0412 345 678").signals.callbackRequest, false);
});

test("message link lookups that didn't complete become incomplete checks", () => {
  const urls: MessageUrlResult[] = [
    { url: "https://a.example", host: "a.example", verdict: "unknown", threat_types: [], coverage: "unavailable", failure: "timeout" },
    { url: "https://b.example", host: "b.example", verdict: "clean", threat_types: [], coverage: "partial",
      incomplete: fromSources([{ name: "redirect_expansion", status: "unavailable", check: "final_destination", failure: "redirect_limit" }]) },
  ];
  assert.deepEqual(urlIncompleteChecks(urls).map((c) => `${c.check}:${c.failure}`), ["reputation:timeout", "final_destination:redirect_limit"]);
});

test("the link result names what didn't complete instead of a generic line", () => {
  const good = { verdict: "clean", threat_types: [], indicator_digest: "d".repeat(64), checked_at: "2026-06-01T00:00:00Z", cached: false };
  const d = decide(analyseUrlLocally("https://www.abc.net.au"), parseIntelResult({ ...good, coverage: "partial", sources: [
    { name: "b", status: "clear", detail: "", threat_types: [] },
    { name: "redirect_expansion", status: "unavailable", detail: "", threat_types: [], check: "final_destination", failure: "timeout" }] }), false);
  assert.equal(d.state, "resting");
  assert.match(d.what_happened, /No threat found by available checks/);
  assert.ok(d.why.some((w) => w.includes("Apollo couldn't verify where this link finally leads (it timed out).")), d.why.join(" | "));
});

test("completeness wording mirrors the server", () => {
  assert.equal(incompletePlain(incompleteCheck("number_reputation", "timeout", { status: "stale" })),
    "The phone number's reputation check didn't complete: the live lookup failed (it timed out), so Apollo used the result of its last check.");
  assert.equal(incompletePlain(incompleteCheck("reputation", null)), "A reputation check didn't complete.");
});
