import assert from "node:assert/strict";
import test from "node:test";
import { explainHigginsWithSLM } from "../src/higgins/slmExplanation.ts";
import { getSharedSLM, setSharedSLM } from "../src/domain/slm/sharedRuntime.ts";
import type { HigginsChatReply } from "../src/higgins/chatClient.ts";

const reply: HigginsChatReply = {
  turnId: "turn123", conversationId: "conv123",
  answer: "Apollo has not checked that link. Open the Link Gate to run a check.",
  evidenceBasis: ["apollo_product_guidance"], uncertainty: [], clarification: null,
  contextUsed: [], suggestedActions: [], navigation: [], investigationAvailable: false,
  investigativeWorkStarted: false,
  retention: { serverContentExpiresAt: "", localContentMaxSeconds: 3600, receiptOnlyAfterExpiry: true },
};
const output = (draftExplanation: string | null) => ({
  observations: [], contradictions: [], alternativeExplanations: [],
  verificationSuggestions: [], draftExplanation,
});

test("keeps verified Higgins answer when the shared model is absent", async () => {
  assert.equal(getSharedSLM(), null);
  assert.deepEqual(await explainHigginsWithSLM("Explain links", reply, null), reply);
});

test("accepts fidelity-preserving on-device language refinement", async () => {
  const refined = "Apollo has not checked that link. Open the Link Gate to run a check.";
  let calls = 0;
  const result = await explainHigginsWithSLM("Explain links", { ...reply, answer: "Apollo has not checked that link. Open the Link Gate to run a check.  " }, {
    modelId: "device-local", infer: async () => { calls++; return output(refined); },
  });
  assert.equal(calls, 1);
  assert.equal(result.answer, refined);
  assert.deepEqual(result.navigation, reply.navigation);
});

test("rejects model rewrites that reverse negation or invent safety", async () => {
  const bad = "Apollo has checked that link. Open the Link Gate to run a check.";
  const result = await explainHigginsWithSLM("Explain links", reply, {
    modelId: "device-local", infer: async () => output(bad),
  });
  assert.equal(result.answer, reply.answer);
});

test("never rewords source quotes, current device state, or investigation answers", async () => {
  let called = 0;
  const adapter = { modelId: "device-local", infer: async () => { called++; return output("Anything"); } };
  await explainHigginsWithSLM("Question", { ...reply, evidenceBasis: ["scam_alert_card"] }, adapter);
  await explainHigginsWithSLM("Question", { ...reply, contextUsed: [{ source: "phone", status: "live", provenance: [], observedAt: null }] }, adapter);
  await explainHigginsWithSLM("Question", { ...reply, investigationAvailable: true }, adapter);
  assert.equal(called, 0);
});

test("rejects injected model score or verdict fields", async () => {
  const result = await explainHigginsWithSLM("Question", reply, {
    modelId: "local", infer: async () => ({ ...output("Something else"), verdict: "This is a Scam" }),
  });
  assert.equal(result.answer, reply.answer);
});

test("shared registry reuses an explicit adapter without auto-installing a model", () => {
  const adapter = { modelId: "local", infer: async () => output(null) };
  setSharedSLM(adapter);
  assert.equal(getSharedSLM(), adapter);
  setSharedSLM(null);
  assert.equal(getSharedSLM(), null);
});
