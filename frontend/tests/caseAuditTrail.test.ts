// The Threat Case History tab is a strict audit trail: only recorded events, with their recorded times, oldest first.
import assert from "node:assert/strict";
import test from "node:test";

import type { DeviceInvestigation } from "../src/investigation/deviceStore";
import type { DiTrace, DiTransaction } from "../src/domain/diTransaction.ts";
import { caseAuditTrail } from "../src/domain/caseAuditTrail.ts";
import type { TriageInvestigationRecord } from "../src/domain/triage/contract.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

const triage = (outcome: TriageInvestigationRecord["outcome"], at: string) => ({
  investigationId: `t-${at}`, catalogueVersion: 1, sourceType: "link", outcome, reason: "", rulesApplicable: [], rulesChecked: [], rulesMet: [],
  rules: [], coverageGaps: [], retries: [], correlation: {}, recheckUseful: false, geminiCalls: 0, evaluatedAt: at,
}) as TriageInvestigationRecord;

const base = {
  event_id: "ev1", device_id: "d1", category: "link", state: "growling", status: "active", origin: "user", headline: "Suspicious link",
  what_happened: "", why: [], what_to_do: "", indicator_host: "commbank-notice.net", indicator_digest: null, verified_block: false,
  adapter_label: "test", occurred_at: "2026-10-28T01:00:00Z", resolved_at: null, triage_investigation: triage("POSSIBLE_THREAT_IDENTIFIED", "2026-10-28T01:00:02Z"),
} as unknown as PatrolEvent;

const flyby = (resolved: boolean): DiTrace => ({
  triage: null, answeredBy: resolved ? "tc_flyby_official" : "magnum_di", outcome: "likely_scam", completion: "complete",
  flyby: { ranAt: "2026-10-28T01:00:20Z", resolved, answeredBy: null, outcome: resolved ? "concerning" : null, basis: null, messageType: null, pattern: null,
    checks: [], searchCalls: 0, searchQueries: 0, cacheHits: 0, magnumNeeded: !resolved, magnumSearch: false, gaps: [],
    issues: resolved ? [] : [{ capability: "reasoning", text: "Weigh the payment request." }], simulated: false },
  magnum: resolved ? null : { webSearch: true, searchQueries: 2, itemsSent: 4, simulated: false, at: "2026-10-28T01:00:50Z" },
  settledReason: null, higgins: { status: "PASS", mode: "plain", attempts: 1 },
});

const record: DiTransaction = { investigationId: "case-1", engine: "Magnum DI", environment: "Production", mode: "Live", simulated: false,
  status: "success", failureCode: null, occurredAt: "2026-10-28T01:00:50Z", request: {}, notice: null };

const inv = (answeredBy: string): DeviceInvestigation => ({
  caseId: "case-1", gates: ["link"], status: "complete", createdAt: "2026-10-28T01:00:05Z", completedAt: "2026-10-28T01:01:00Z",
  committedAt: "2026-10-28T01:01:02Z", question: "q", sources: [], evidenceItems: [], patrolEventId: "ev1", answeredBy,
  turns: [{ question: "Walk me through it", committedAt: "2026-10-28T01:01:00Z" }] as never,
  response: { evidence: [{ stance: "supporting" }, { stance: "contrary" }] } as never,
});

const ids = (trail: ReturnType<typeof caseAuditTrail>) => trail.map((e) => e.id);

test("a case Magnum DI settled: created → Triage → opened → TC FlyBy → escalated → Magnum DI → Evidence locked → verdict", () => {
  const event = { ...base, investigation_case_id: "case-1", investigation_completed_at: "2026-10-28T01:01:00Z", investigation_answered_by: "magnum_di" } as PatrolEvent;
  const trail = caseAuditTrail({ event, investigation: inv("magnum_di"), trace: flyby(false), records: [record], verdict: "Likely scam" });
  assert.deepEqual(ids(trail), ["created", "triage-0", "opened", "flyby", "escalated", "magnum-0", "lock", "verdict"]);
  assert.equal(trail.find((e) => e.id === "escalated")!.description, "Left for Magnum DI: Weigh the payment request.");
  assert.equal(trail.find((e) => e.id === "magnum-0")!.description, "It examined 4 evidence items.");
  assert.match(trail.find((e) => e.id === "lock")!.description, /^Magnum DI's result was locked with 2 facts, 1 pointing the other way, before Higgins explained it\./);
  assert.equal(trail.find((e) => e.id === "verdict")!.description, "Verdict: Likely scam.");
  assert.ok(trail.every((e) => e.at));
});

test("TC FlyBy settled it: no escalation and no Magnum DI entry", () => {
  const event = { ...base, investigation_case_id: "case-1", investigation_completed_at: "2026-10-28T01:01:00Z", investigation_answered_by: "tc_flyby_official" } as PatrolEvent;
  const trail = caseAuditTrail({ event, investigation: inv("tc_flyby_official"), trace: flyby(true), records: [], verdict: "Concerning" });
  assert.deepEqual(ids(trail), ["created", "triage-0", "opened", "flyby", "lock", "verdict"]);
  assert.equal(trail.find((e) => e.id === "flyby")!.title, "TC FlyBy settled the case");
  assert.ok(!trail.some((e) => /Magnum DI (completed|didn't)/.test(e.title)));
});

test("a Triage-only check: no investigation entries, and no sources or related cases on the trail", () => {
  const trail = caseAuditTrail({ event: base, investigation: null, trace: null, records: [], verdict: "Possible threat" });
  assert.deepEqual(ids(trail), ["created", "triage-0", "verdict"]);
  assert.equal(trail[0].description, "You submitted commbank-notice.net for checking.");
  assert.ok(!trail.some((e) => /^(Checked|Couldn't check|Related)/.test(e.title)));
});

test("earlier results and earlier closes stay on the trail; a running investigation says so last", () => {
  const event = { ...base, triage_history: [triage("LIMITED_UNABLE_TO_DETERMINE", "2026-10-27T09:00:00Z")], investigation_case_id: "case-2",
    previously_resolved_at: "2026-10-27T10:00:00Z", reopened_at: "2026-10-28T00:30:00Z" } as PatrolEvent;
  const trail = caseAuditTrail({ event, investigation: null, trace: null, records: [], verdict: null });
  assert.deepEqual(ids(trail), ["triage-0", "closed-0", "reopened", "created", "triage-1", "opened", "pending"]);
  assert.match(trail[0].description, /This earlier result is kept on record\.$/);
  assert.equal(trail.find((e) => e.id === "opened")!.at, null);
  assert.equal(trail[trail.length - 1].pending, true);
});

test("a Magnum DI call that didn't finish is recorded as such", () => {
  const event = { ...base, investigation_case_id: "case-1" } as PatrolEvent;
  const trail = caseAuditTrail({ event, investigation: null, trace: flyby(false), records: [{ ...record, status: "failed", failureCode: "provider_timeout" }], verdict: null });
  const magnum = trail.find((e) => e.id === "magnum-0")!;
  assert.equal(magnum.title, "Magnum DI didn't finish");
  assert.equal(magnum.description, "It stopped before answering (provider timeout).");
});
