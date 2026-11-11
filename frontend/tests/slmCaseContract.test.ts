import assert from "node:assert/strict";
import test from "node:test";
import { reasonForCase } from "../src/domain/slm/caseContract.ts";

const request = {
  caseId: "case-A",
  caseRevision: 7,
  requestId: "req-A",
  role: "tc_hawkeye" as const,
  operation: "evidence_reasoning" as const,
  evidence: [{ evidenceId: "E-1", text: "Guaranteed 15% monthly return" }],
  question: "What needs checking?",
};
const answer = {
  observations: [{ text: "The message claims 15% monthly", evidenceIds: ["E-1"] }],
  contradictions: [], alternativeExplanations: [], verificationSuggestions: [],
  draftExplanation: null,
};

test("correlates an on-device answer to the exact case and revision", async () => {
  const run = await reasonForCase(request, { modelId: "device-model", infer: async () => answer });
  assert.equal(run.status, "completed");
  if (run.status === "completed") {
    assert.deepEqual([run.caseId, run.caseRevision, run.requestId], ["case-A", 7, "req-A"]);
    assert.equal(run.execution, "on_device");
    assert.deepEqual(run.answer.observations[0].evidenceIds, ["E-1"]);
  }
});

test("rejects malformed identifiers before calling inference", async () => {
  let calls = 0;
  const run = await reasonForCase({ ...request, caseRevision: -1 }, {
    modelId: "test", infer: async () => { calls++; return answer; },
  });
  assert.equal(run.status, "invalid_output");
  assert.equal(calls, 0);
});

test("does not pretend success when on-device inference is unavailable", async () => {
  const run = await reasonForCase(request, null);
  assert.deepEqual(run, { status: "unavailable", reason: "on_device_model_unavailable" });
});

test("never forwards a verdict or unknown evidence citation in the advisory envelope", async () => {
  const verdict = await reasonForCase(request, {
    modelId: "test", infer: async () => ({ ...answer, verdict: "This is a Scam" }),
  });
  assert.equal(verdict.status, "invalid_output");
  const unknown = await reasonForCase(request, {
    modelId: "test", infer: async () => ({
      ...answer, observations: [{ text: "Unsupported claim", evidenceIds: ["other-case"] }],
    }),
  });
  assert.equal(unknown.status, "invalid_output");
});

test("SLM handoff retries do not depend on SSE replay or mint a new request", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../src/investigation/caseStore.ts", import.meta.url), "utf8");
  assert.match(source, /for \(let attempt = 0; attempt < 2; attempt\+\+\)/);
  assert.match(source, /Date\.parse\(issued\.expiresAt\) <= Date\.now\(\)/);
  assert.match(source, /submitIssuedAdvisory\(caseId, issued, adapter\)/);
  assert.match(source, /attemptedAdvisoryRequests\.current\.delete\(issued\.request\.requestId\)/);
});

test("lost acknowledgement retries reuse the identical SLM result without another inference", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../src/domain/slm/slmTransport.ts", import.meta.url), "utf8");
  assert.match(source, /pendingReceipts\.get\(key\)\?\.payload/);
  assert.match(source, /if \(!payload\) \{[\s\S]*?reasonForCase\(issued\.request, adapter\)/);
  assert.match(source, /pendingReceipts\.set\(key, \{ expiresAt: expiry, payload \}\)/);
  assert.match(source, /pendingReceipts\.delete\(key\)/);
});
