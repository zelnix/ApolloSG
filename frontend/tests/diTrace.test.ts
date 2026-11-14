import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { HigginsResponse, SourceReference } from "../src/investigation/types.ts";
import type { DiTrace, DiTransaction } from "../src/domain/diTransaction.ts";
import { buildDecisionTrace, checkLine, outsideResearch } from "../src/domain/diTrace.ts";
import { LIMITED_CAUTION, plainTriageText, type TriageInvestigationRecord } from "../src/domain/triage/contract.ts";
import { evaluateTriage } from "../src/domain/triage/engine.ts";

const limited: TriageInvestigationRecord = {
  investigationId: "tri-1", catalogueVersion: 1, sourceType: "message", outcome: "LIMITED_UNABLE_TO_DETERMINE",
  reason: "ApolloSG couldn't obtain enough evidence to decide.", rulesApplicable: ["M01", "M02"], rulesChecked: ["M01"], rulesMet: [],
  rules: [], coverageGaps: [{ code: "EMAIL_HEADERS_UNAVAILABLE", detail: "", recoverable: false, ruleIds: ["M02"] }],
  retries: [], correlation: {}, recheckUseful: false, geminiCalls: 0, evaluatedAt: "2026-06-10T09:01:00.000Z",
};

function record(partial: Partial<DiTransaction> = {}): DiTransaction {
  return {
    investigationId: "case-1", engine: "Magnum DI", environment: "Production", mode: "Live", simulated: false, status: "success",
    failureCode: null, occurredAt: "2026-06-10T09:02:00.000Z", request: { tools: ["web_search"], attachmentCount: 0 }, notice: null, ...partial,
  };
}

const flybyTrace = (resolved: boolean): DiTrace => ({
  triage: null, answeredBy: resolved ? "tc_flyby_official" : "magnum_di", outcome: resolved ? "concerning" : "likely_scam", completion: "complete",
  flyby: {
    ranAt: null, resolved, answeredBy: resolved ? "tc_flyby_official" : "magnum_di", outcome: resolved ? "concerning" : null, basis: resolved ? "impersonation" : null,
    messageType: "sms", pattern: null, checks: [{ kind: "link", status: "resolved", route: "official_source" }], searchCalls: 0, searchQueries: 0,
    cacheHits: 0, magnumNeeded: !resolved, magnumSearch: false, gaps: [], issues: resolved ? [] : [{ capability: "reasoning", text: "Weigh the money request." }], simulated: false,
  },
  magnum: resolved ? null : { webSearch: false, searchQueries: 0, itemsSent: 3, simulated: false, at: null },
  settledReason: resolved
    ? { rule: "Corroborated impersonation", by: "TC Hawkeye", sentence: "Settled by TC Hawkeye — corroborated impersonation: x." }
    : { rule: "Reasoning", by: "Magnum DI", sentence: "Settled by Magnum DI — reasoning: y." },
  higgins: { status: "PASS", mode: "plain", attempts: 1 },
});

const CODES = /\b[A-Z]{2,}(?:_[A-Z]+)+\b|\bM0\d\b|catalogue|tokens?\b|cost|US\$|\b[a-z]+_[a-z_]+\b/i;
const everyLine = (steps: ReturnType<typeof buildDecisionTrace>) => steps.flatMap((s) => [s.label, s.summary, ...s.details]);

test("the path runs Higgins Triage → TC Hawkeye → Magnum DI → Evidence Lock", () => {
  const steps = buildDecisionTrace({ trace: flybyTrace(false), records: [record()], triage: null, hasCase: true });
  assert.deepEqual(steps.map((s) => s.name), ["Higgins Triage", "TC Hawkeye", "Magnum DI", "Evidence Lock"]);
});

test("a limited screening record keeps Gate limits separate and does not claim an investigation Finding", () => {
  const steps = buildDecisionTrace({ trace: null, records: [], triage: limited, hasCase: false, presented: { verdict: "Unable to determine", risk: null } });
  const intake = steps.find((step) => step.id === "triage")!;
  assert.equal(intake.status, "ran");
  assert.equal(intake.label, "Not Fully Investigated");
  assert.match(intake.summary, /No TC Hawkeye investigation was opened/);
  assert.equal(steps.find((step) => step.id === "gate")?.status, "failed");
  assert.equal(steps.find((step) => step.id === "flyby")?.status, "not_engaged");
  assert.equal(steps.find((step) => step.id === "magnum")?.summary, "Magnum DI was not engaged because Higgins Triage did not open an investigation.");
  assert.equal(steps.find((step) => step.id === "lock")?.status, "not_engaged");
  for (const line of everyLine(steps)) assert.doesNotMatch(line, CODES, line);
});

test("TC Hawkeye settled: its checks are shown and a missing triage intake remains unrecorded", () => {
  const steps = buildDecisionTrace({ trace: flybyTrace(true), records: [], triage: null, hasCase: true });
  assert.equal(steps[0].label, "No intake record");
  assert.match(steps[0].summary, /no separate triage intake record is available/);
  assert.deepEqual(steps[0].details, []);
  assert.equal(steps[1].label, "Settled · This is likely a scam");
  assert.match(steps[1].summary, /^Settled by TC Hawkeye/);
  assert.deepEqual(steps[1].details, ["This is an administrative determination from rule-based checks, not a deep investigation by Magnum DI.", "The website: checked with official sources"]);
  assert.equal(steps[2].summary, "Magnum DI was not engaged because TC Hawkeye's automated checks resolved all identified questions.");
  assert.match(steps[3].summary, /^The Evidence Lock preserves TC Hawkeye's original decision/);
  for (const line of everyLine(steps)) assert.doesNotMatch(line, CODES, line);
});

test("escalated to Magnum DI: what was left for it, what it was given, and the lock", () => {
  const response = { evidence: [{ stance: "supporting" }, { stance: "contrary" }, { stance: "supporting" }] } as unknown as HigginsResponse;
  const steps = buildDecisionTrace({ trace: flybyTrace(false), records: [record({ request: { attachmentCount: 1 } })], triage: null, hasCase: true,
    presented: { verdict: "Likely scam", risk: "High risk" }, response });
  assert.equal(steps[1].label, "Escalated to Magnum DI");
  assert.ok(steps[1].details.includes("Left for Magnum DI: Weigh the money request."));
  assert.equal(steps[2].summary, "Magnum DI investigated 3 evidence items without web search.");
  assert.ok(steps[2].details.includes("Given 3 evidence items."));
  assert.ok(steps[2].details.some((d) => /1 picture or file sent, each screened/.test(d)));
  assert.equal(steps[3].label, "Preserved");
  assert.deepEqual(steps[3].details.slice(0, 2), ["Recorded verdict: Likely scam · High risk", "Captured 3 facts, 1 pointing the other way."]);
  assert.match(steps[3].details[2], /checked against the recorded result and matched it/);
  for (const line of everyLine(steps)) assert.doesNotMatch(line, CODES, line);
});

test("escalated but no Magnum DI record yet, a failed call and a simulated answer are each said plainly", () => {
  assert.equal(buildDecisionTrace({ trace: flybyTrace(false), records: [], triage: null, hasCase: true })[2].status, "pending");
  const failed = buildDecisionTrace({ trace: flybyTrace(false), records: [record({ status: "failed", failureCode: "provider_timeout" })], triage: null, hasCase: true })[2];
  assert.equal(failed.status, "failed");
  assert.equal(failed.summary, "Magnum DI was engaged but didn't finish (provider timeout).");
  const simulated = buildDecisionTrace({ trace: flybyTrace(false), records: [record({ simulated: true, mode: "Simulated" })], triage: null, hasCase: true })[2];
  assert.equal(simulated.status, "simulated");
  assert.match(simulated.summary, /the preview stood in for the outside service Magnum DI calls/);
});

test("a case with no Triage or TC Hawkeye record says so for each; no result yet means nothing locked", () => {
  const steps = buildDecisionTrace({ trace: null, records: [], triage: null, hasCase: true });
  assert.equal(steps[0].summary, "No Higgins Triage record is stored for this case.");
  assert.equal(steps[1].summary, "No TC Hawkeye record is stored for this case.");
  assert.equal(steps[3].summary, "There's no result to lock yet.");
});

test("a stopped on-device assessment preserves evidence without claiming a final decision was locked", () => {
  for (const outcome of ["device_unavailable", "invalid_output", "failed", null]) {
    const trace = { ...flybyTrace(false), answeredBy: "tc_hawkeye", outcome, completion: null, flyby: null, magnum: null, higgins: null };
    const lock = buildDecisionTrace({ trace, records: [], triage: null, hasCase: true })[3];
    assert.equal(lock.status, "pending");
    assert.equal(lock.label, "Not yet");
    assert.doesNotMatch(lock.summary, /preserves .*decision/i);
  }
});

test("a completed Unlikely a Scam result still has its decision preserved", () => {
  const trace = { ...flybyTrace(true), outcome: "unlikely_scam" };
  const lock = buildDecisionTrace({ trace, records: [], triage: null, hasCase: true })[3];
  assert.equal(lock.label, "Preserved");
});

test("check lines are plain words for every recorded status", () => {
  assert.equal(checkLine({ kind: "phone", status: "not_found", route: "web_search" }), "The phone number: no record found");
  assert.equal(checkLine({ kind: "claim", status: "resolved", route: "web_search" }), "A claim it makes: checked with a web search");
  assert.equal(checkLine({ kind: "message_analysis", status: "needs_reasoning", route: null }), "The message as a whole: left for Magnum DI");
});

test("outside research lists each source with the facts it supports or points against", () => {
  const sources: SourceReference[] = [
    { id: "s1", url: "https://www.scamwatch.gov.au/alert", title: "Scamwatch alert", retrievedAt: "2026-06-10T09:00:00Z", retrieval: "fetched", authority: "official", authorityBasis: "" },
    { id: "s2", url: "https://example.com/about", title: "", retrievedAt: "", retrieval: "search_result", authority: "independent", authorityBasis: "" },
    { id: "s3", url: "", title: "Threat-list lookup", retrievedAt: "", retrieval: "fetched", authority: "independent", authorityBasis: "" },
  ];
  const response = { evidence: [
    { text: "The link is on a scam warning.", stance: "supporting", sourceIds: ["s1"] },
    { text: "The business is registered.", stance: "contrary", sourceIds: ["s2", "s1"] },
  ] } as unknown as HigginsResponse;
  const rows = outsideResearch(sources, response);
  assert.deepEqual(rows.map((r) => r.id), ["s1", "s2", "s3"]);
  assert.deepEqual(rows[0].supports, ["The link is on a scam warning."]);
  assert.deepEqual(rows[0].against, ["The business is registered."]);
  assert.equal(rows[0].site, "scamwatch.gov.au");
  assert.equal(rows[0].standing, "Official source");
  assert.equal(rows[1].title, "example.com");
  assert.equal(rows[1].how, "Found by a web search");
  assert.equal(rows[2].site, null);
  assert.deepEqual([rows[2].supports, rows[2].against, rows[2].other], [[], [], []]);
  assert.deepEqual(outsideResearch([], response), []);
});

test("the DI tab shows no token counts, cost, raw replies or rule-book codes", () => {
  const src = readFileSync(new URL("../src/components/DiReport.tsx", import.meta.url), "utf8");
  for (const hidden of [/Tokens/, /Cost/, /investigationPrompt|Complete response|response\.text/, /ruleId|catalogueVersion|RESULT_LABEL/, /TriageSummary/]) {
    assert.doesNotMatch(src, hidden);
  }
});

test("Coverage Gap codes become plain English for the person", () => {
  assert.equal(plainTriageText("Coverage gap: EMAIL_HEADERS_UNAVAILABLE, BROWSER_VISIBILITY_UNAVAILABLE"),
    "Couldn't check: The technical sender information wasn't available. ApolloSG can't observe the page itself: its content, or the website an installed web app or notification came from.");
  assert.equal(plainTriageText("ApolloSG couldn't obtain enough evidence to decide: INSUFFICIENT_EVIDENCE"),
    "ApolloSG couldn't obtain enough evidence to decide: There wasn't enough evidence to decide either way.");
  assert.equal(plainTriageText("No codes here."), "No codes here.");
  assert.match(LIMITED_CAUTION, /^Treat this with caution\. .*can't say it's safe\./);
  assert.doesNotMatch(LIMITED_CAUTION, /nothing to worry/i);
});

test("a Limited Triage reason is written in plain English; the codes stay on the coverage gaps", () => {
  const record = evaluateTriage({ source_type: "link", unresolved_concern: true });
  assert.equal(record.outcome, "LIMITED_UNABLE_TO_DETERMINE");
  assert.doesNotMatch(record.reason, /[A-Z]+_[A-Z]+/);
});
