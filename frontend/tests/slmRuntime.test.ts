import assert from "node:assert/strict";
import test from "node:test";
import { runSLM } from "../src/domain/slm/index.ts";
import { LocalLlamaRuntime, type InitLlama } from "../src/domain/slm/llamaRnRuntime.ts";

const base = {
  role: "tc_hawkeye" as const,
  operation: "evidence_reasoning" as const,
  question: "What must be checked?",
};
const result = JSON.stringify({
  observations: [{ text: "A return was claimed.", evidenceIds: ["current"] }],
  contradictions: [],
  alternativeExplanations: [],
  verificationSuggestions: [{ text: "Check the licence.", evidenceIds: ["current"] }],
  draftExplanation: null,
});

test("native adapter passes case evidence to the model but never calls a network provider", async () => {
  const calls: string[] = [];
  let released = 0;
  const init: InitLlama = async (options) => {
    assert.equal(options.n_gpu_layers, 0);
    calls.push(options.model);
    return {
      completion: async ({ messages }) => {
        calls.push(messages[1].content);
        assert.match(messages[0].content, /An evidenceIds entry must cite ONLY IDs supplied in the input/i);
        assert.match(messages[0].content, /For case_finding include caseFinding/i);
        return { text: result };
      },
      release: async () => { released++; },
    };
  };
  const runtime = new LocalLlamaRuntime("file:///private/models/apollo.gguf", "local-test", init);
  const response = await runSLM({ ...base, evidence: [{ evidenceId: "current", text: "Guaranteed 15% monthly" }] }, runtime);
  assert.equal(response.status, "completed");
  assert.equal(calls.length, 2);
  assert.match(calls[1], /Guaranteed 15% monthly/);
  await runtime.release();
  assert.equal(released, 1);
});

test("reuses one model context, isolates requests, and rejects fabricated references", async () => {
  let initialized = 0;
  const prompts: string[] = [];
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => {
    initialized++;
    return {
      completion: async ({ messages }) => {
        prompts.push(messages[1].content);
        return { text: result };
      },
      release: async () => undefined,
    };
  });
  const first = await runSLM({ ...base, evidence: [{ evidenceId: "current", text: "first message" }] }, runtime);
  const second = await runSLM({ ...base, evidence: [{ evidenceId: "next", text: "second message" }] }, runtime);
  assert.equal(first.status, "completed");
  assert.equal(second.status, "invalid_output"); // local model cited prior case
  assert.equal(initialized, 1);
  assert.doesNotMatch(prompts[1], /first message/); // no retained conversation history
  await runtime.release();
});

test("fails closed on invalid JSON without forwarding content", async () => {
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
    completion: async () => ({ text: "not JSON" }),
    release: async () => undefined,
  }));
  const response = await runSLM({ ...base, evidence: [] }, runtime);
  assert.equal(response.status, "unavailable");
  await runtime.release();
});

test("requires a local GGUF, and release prevents future execution", async () => {
  const init: InitLlama = async () => ({ completion: async () => ({ text: result }), release: async () => undefined });
  assert.throws(() => new LocalLlamaRuntime("https://example.com/a.gguf", "remote", init));
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local", init);
  await runtime.release();
  const response = await runSLM({ ...base, evidence: [] }, runtime);
  assert.equal(response.status, "unavailable");
});

for (const decision of ["proceed_local", "escalate", "additional_evidence_required"] as const) {
  test(`native escalation prompt and validation accept ${decision}`, async () => {
    const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
      completion: async ({ messages }) => {
        assert.match(messages[0].content, /For escalation_assessment include escalationAssessment/);
        assert.match(messages[0].content, /For all other operations omit escalationAssessment/);
        return { text: JSON.stringify({
          observations: [], contradictions: [], alternativeExplanations: [],
          verificationSuggestions: [], draftExplanation: null,
          escalationAssessment: {
            decision, rationale: "Assessment cites the supplied source.",
            evidenceIds: ["current"], materialGaps: decision === "proceed_local" ? [] : ["Independent verification unavailable"],
          },
        }) };
      },
      release: async () => undefined,
    }));
    const response = await runSLM({
      role: "higgins_escalation_assessment", operation: "escalation_assessment",
      question: "Assess escalation", evidence: [{ evidenceId: "current", text: "Unverified claim" }],
    }, runtime);
    assert.equal(response.status, "completed");
    if (response.status === "completed") assert.equal(response.answer.escalationAssessment?.decision, decision);
    await runtime.release();
  });
}

test("native escalation rejects fabricated citations", async () => {
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
    completion: async () => ({ text: JSON.stringify({
      observations: [], contradictions: [], alternativeExplanations: [],
      verificationSuggestions: [], draftExplanation: null,
      escalationAssessment: {
        decision: "escalate", rationale: "Needs verification",
        evidenceIds: ["other-device"], materialGaps: ["Missing verification"],
      },
    }) }),
    release: async () => undefined,
  }));
  const response = await runSLM({
    role: "higgins_escalation_assessment", operation: "escalation_assessment",
    question: "Assess escalation", evidence: [{ evidenceId: "current", text: "Claim" }],
  }, runtime);
  assert.equal(response.status, "invalid_output");
  await runtime.release();
});
