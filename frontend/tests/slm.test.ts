import assert from "node:assert/strict";
import test from "node:test";
import { runSLM } from "../src/domain/slm/index.ts";

const request = {
  role: "tc_hawkeye" as const,
  operation: "evidence_reasoning" as const,
  evidence: [{ evidenceId: "case-local-1", text: "A message claims guaranteed 15% monthly returns." }],
  question: "What needs independent verification?",
};
const valid = {
  observations: [{ text: "The return is claimed in the submitted message.", evidenceIds: ["case-local-1"] }],
  contradictions: [],
  alternativeExplanations: [],
  verificationSuggestions: [{ text: "Verify claimed authorisation independently.", evidenceIds: ["case-local-1"] }],
  draftExplanation: null,
};

test("unavailable device runtime does not invoke a fallback model", async () => {
  assert.deepEqual(await runSLM(request, null), {
    status: "unavailable", execution: "none", reason: "on_device_model_unavailable",
  });
});

test("accepts validated advisory output tied to current evidence IDs", async () => {
  const result = await runSLM(request, { modelId: "test-local", infer: async () => valid });
  assert.equal(result.status, "completed");
  if (result.status === "completed") {
    assert.equal(result.execution, "on_device");
    assert.equal(result.answer.observations[0].evidenceIds[0], "case-local-1");
  }
});

test("rejects unsupported evidence references", async () => {
  const answer = { ...valid, observations: [{ text: "Unrelated case", evidenceIds: ["other-device"] }] };
  const result = await runSLM(request, { modelId: "test-local", infer: async () => answer });
  assert.equal(result.status, "invalid_output");
});

test("rejects model-authored verdict and score fields", async () => {
  const result = await runSLM(request, {
    modelId: "test-local", infer: async () => ({ ...valid, verdict: "This is a Scam", score: 99 }),
  });
  assert.equal(result.status, "invalid_output");
});

test("rejects duplicate references in a request", async () => {
  const result = await runSLM({
    ...request, evidence: [...request.evidence, ...request.evidence],
  }, { modelId: "test-local", infer: async () => valid });
  assert.equal(result.status, "invalid_output");
});

test("does not use a network provider or disclose errors when inference throws", async () => {
  const result = await runSLM(request, {
    modelId: "test-local", infer: async () => { throw new Error("sensitive message content"); },
  });
  assert.deepEqual(result, {
    status: "unavailable", execution: "none", reason: "on_device_inference_failed",
  });
});

test("Qantas-style email is assessed by SLM, not a Hawkeye score", async () => {
  const evidenceId = "email-qantas-1";
  const input = {
    role: "case_finding" as const,
    operation: "case_finding" as const,
    evidence: [{ evidenceId, text: "From: Qantas <news@e.qantas.com>\\nSubject: Your points update" }],
    question: "Assess the complete case evidence; cite each reason.",
  };
  const result = await runSLM(input, {
    modelId: "fixture-local-slm",
    infer: async () => ({
      observations: [], contradictions: [], alternativeExplanations: [],
      verificationSuggestions: [], draftExplanation: null,
      caseFinding: {
        outcome: "unlikely_scam",
        explanation: "This resembles a Qantas points update, but sender authentication was not supplied.",
        reasons: [{ text: "The displayed sender uses e.qantas.com.", evidenceIds: [evidenceId] }],
        uncertainty: "The sender and actual link destinations were not authenticated.",
        advice: "Open the Qantas app directly to check your points.",
      },
    }),
  });
  assert.equal(result.status, "completed");
  if (result.status === "completed") {
    assert.equal(result.answer.caseFinding?.outcome, "unlikely_scam");
    assert.equal(result.answer.caseFinding?.reasons[0].evidenceIds[0], evidenceId);
  }
});
