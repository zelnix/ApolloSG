import test from "node:test";
import assert from "node:assert/strict";
import { validateWrightReadiness } from "../src/domain/slm/wrightReadinessContract.ts";
import { runSLM } from "../src/domain/slm/index.ts";
import { LocalLlamaRuntime } from "../src/domain/slm/llamaRnRuntime.ts";

const sources = [{ evidenceId: "src", text: "0299363990" }];
const ready = { version: "wright.readiness.v1", evidence: [{ evidenceId: "src", availability: "readable" }] };

test("readiness covers the exact inventory once", () => {
  assert.ok(validateWrightReadiness(ready, sources));
  for (const evidence of [[], [...ready.evidence, ...ready.evidence], [{ evidenceId: "foreign-device", availability: "readable" }]])
    assert.equal(validateWrightReadiness({ ...ready, evidence }, sources), null);
  assert.equal(validateWrightReadiness(ready, [...sources, { evidenceId: "missing", text: "text" }]), null);
});

for (const key of ["classification", "scamTypes", "intent", "coercion", "exposure", "narrative", "risk", "score", "outcome", "advice", "caseFinding", "escalationAssessment"]) {
  test("Wright rejects extra " + key + " at both record and item boundaries", () => {
    assert.equal(validateWrightReadiness({ ...ready, [key]: "finding-like claim" }, sources), null);
    assert.equal(validateWrightReadiness({ ...ready, evidence: [{ ...ready.evidence[0], [key]: "claim" }] }, sources), null);
  });
}

test("inventory metadata cannot be promoted to examined source content", () => {
  assert.equal(validateWrightReadiness(ready, [{ evidenceId: "src", representation: "inventory_only" }]), null);
  assert.equal(validateWrightReadiness({ ...ready, evidence: [{ evidenceId: "src", availability: "inventory_only" }] }, sources), null);
});

test("native Wright prompt requests readability, not a scam determination", async () => {
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "native-test", async () => ({
    async completion(options) {
      assert.match(options.messages[0].content, /Check only whether.*readable/);
      assert.doesNotMatch(options.messages[0].content, /scam_indicators|legitimate_context|CONFIRMED/);
      const submitted = JSON.parse(options.messages[1].content).untrustedEvidence[0];
      return { text: JSON.stringify({ ...ready, evidence: [{ evidenceId: submitted.evidenceId, availability: "readable" }] }) };
    }, release: async () => undefined,
  }));
  const result = await runSLM({ role: "wright_triage", operation: "investigation_readiness", question: "Check readability", evidence: sources }, runtime);
  assert.equal(result.status, "completed");
  await runtime.release();
});
