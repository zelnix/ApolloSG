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
        assert.match(messages[0].content, /Use only supplied evidence IDs/i);
        assert.match(messages[0].content, /Return one JSON object only/i);
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

test("native decoding requires a JSON object and uses the answer channel, without bypassing citations", async () => {
  let calls = 0;
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
    completion: async options => {
      assert.deepEqual(options.response_format, { type: "json_object", schema: { type: "object" } });
      assert.equal(options.enable_thinking, false);
      calls++;
      return { text: "Reasoning is not the answer {and is not JSON}.", content: result };
    },
    release: async () => undefined,
  }));
  const first = await runSLM({ ...base, evidence: [{ evidenceId: "current", text: "Claim" }] }, runtime);
  assert.equal(first.status, "completed");
  const other = await runSLM({ ...base, evidence: [{ evidenceId: "different-case", text: "Other claim" }] }, runtime);
  assert.equal(other.status, "invalid_output", "constrained decoding never authorises a citation from another case");
  assert.equal(calls, 2);
  await runtime.release();
});

for (const [flags, code] of [
  [{ stopped_limit: 1 }, "output_limit_reached"],
  [{ context_full: true }, "context_limit_reached"],
  [{ truncated: true }, "context_limit_reached"],
  [{ interrupted: true }, "interrupted"],
] as const) {
  test(`native ${code} cannot commit even when the partial response contains valid JSON`, async () => {
    const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
      completion: async () => ({ text: result, ...flags }),
      release: async () => undefined,
    }));
    const response = await runSLM({ ...base, evidence: [{ evidenceId: "current", text: "Claim" }] }, runtime);
    assert.equal(response.status, "unavailable");
    if (response.status !== "completed") assert.match(response.reason, new RegExp(code));
    await runtime.release();
  });
}

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
        assert.match(messages[0].content, /Also include "escalationAssessment"/);
        assert.match(messages[0].content, /Do not include caseFinding/i);
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

test("oversized native input fails closed before model initialization, without truncation", async () => {
  let initialized = 0;
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local", async () => {
    initialized++;
    return { completion: async () => ({ text: result }), release: async () => undefined };
  }, 4096);
  const response = await runSLM({
    ...base, evidence: [{ evidenceId: "current", text: "X".repeat(10000) }],
  }, runtime);
  assert.equal(response.status, "unavailable");
  assert.equal(initialized, 0);
  await runtime.release();
});

test("native context preflight accounts for system instructions as well as evidence", async () => {
  let invoked = 0;
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local", async () => {
    invoked++;
    return { completion: async () => ({ text: result }), release: async () => undefined };
  }, 4096);
  const response = await runSLM({
    ...base, evidence: [{ evidenceId: "current", text: "X".repeat(3500) }],
  }, runtime);
  assert.equal(response.status, "unavailable");
  assert.equal(invoked, 0);
  await runtime.release();
});
