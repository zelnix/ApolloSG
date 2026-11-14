import test from "node:test";
import assert from "node:assert/strict";
import { assessMandatoryWright, respondToWrightStage } from "../src/domain/slm/wrightPhase6.ts";
import { runSLM, type SLMAdapter } from "../src/domain/slm/index.ts";

const evidence = [{ evidenceId: "source-1", text: "0299363990" }];
const adapter: SLMAdapter = {
  modelId: "native-test",
  async infer(request) {
    return { version: "wright.readiness.v1",
      evidence: request.evidence.map(e => ({ evidenceId: e.evidenceId, availability: "readable" })) };
  },
};

test("missing native model returns limited, never a Finding", async () => {
  assert.equal((await assessMandatoryWright(evidence, null)).status, "limited");
});

test("a bare phone number is evidence available for investigation without an identity or scam decision", async () => {
  const result = await assessMandatoryWright(evidence, adapter);
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.deepEqual(result.readiness, { version: "wright.readiness.v1",
      evidence: [{ evidenceId: "source-1", availability: "readable" }] });
    assert.doesNotMatch(JSON.stringify(result.readiness), /classification|scam|exposure|intent|verdict|risk/i);
  }
});

test("existing stage handoff carries only readiness and the original request identifiers", async () => {
  const result = await respondToWrightStage({
    caseId: "case-1234", caseRevision: 1, requestId: "request-1234",
    role: "wright_triage", operation: "investigation_readiness", evidence,
  }, adapter);
  assert.equal(result.status, "ready");
  if (result.status === "ready") {
    const answer = result.payload.answer as Record<string, unknown>;
    assert.ok(answer.wrightReadiness);
    assert.equal(answer.caseFinding, undefined);
    assert.equal(answer.wrightSemantic, undefined);
    assert.equal(result.payload.requestId, "request-1234");
  }
});

test("generic handoff checks every window and maps references back to the original source", async () => {
  let invocations = 0;
  const result = await runSLM({
    role: "wright_triage", operation: "investigation_readiness",
    question: "Check evidence availability", evidence: [{ evidenceId: "source-long", text: "Readable invoice. ".repeat(250) }],
  }, { ...adapter, async infer(request) { invocations++; return adapter.infer(request); } });
  assert.equal(result.status, "completed");
  assert.ok(invocations > 1);
  if (result.status === "completed")
    assert.deepEqual(result.answer.wrightReadiness?.evidence, [{ evidenceId: "source-long", availability: "readable" }]);
});

test("one failed window blocks completion rather than silently omitting content", async () => {
  let calls = 0;
  const result = await assessMandatoryWright([{ evidenceId: "long", text: "Invoice. ".repeat(400) }], {
    ...adapter, async infer(request) { if (++calls === 2) throw new Error("native unavailable"); return adapter.infer(request); },
  });
  assert.equal(result.status, "limited");
});

test("all 64 permitted source IDs are retained, without the old semantic 32-citation limit", async () => {
  const many = Array.from({ length: 64 }, (_, i) => ({ evidenceId: "source-" + i, text: "Readable source" }));
  const result = await assessMandatoryWright(many, adapter);
  assert.equal(result.status, "complete");
  if (result.status === "complete") assert.equal(result.readiness.evidence.length, 64);
});

for (const operation of ["case_finding", "escalation_assessment", "evidence_reasoning", "wright_semantic"] as const) {
  test("Wright cannot invoke " + operation, async () => {
    let invoked = false;
    const result = await runSLM({ role: "wright_triage", operation, question: "Do not judge", evidence },
      { ...adapter, async infer() { invoked = true; return {}; } });
    assert.equal(result.status, "invalid_output");
    assert.equal(invoked, false);
  });
}

test("scam-like and ordinary readable sources have the same readiness shape", async () => {
  for (const text of ["Invoice already paid.", "Send your password now.", "A quoted scam warning."]) {
    const result = await assessMandatoryWright([{ evidenceId: "source-1", text }], adapter);
    assert.equal(result.status, "complete");
    if (result.status === "complete") assert.equal(result.readiness.evidence[0].availability, "readable");
  }
});
