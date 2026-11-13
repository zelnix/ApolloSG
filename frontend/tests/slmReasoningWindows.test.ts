import assert from "node:assert/strict";
import test from "node:test";
import { runSLM, type SLMAdapter, type SLMRequest } from "../src/domain/slm/index.ts";

const empty = { observations: [], contradictions: [], alternativeExplanations: [], verificationSuggestions: [], draftExplanation: null };
const request: SLMRequest = { role: "higgins_escalation_assessment", operation: "escalation_assessment", question: "Assess coverage",
  evidence: [{ evidenceId: "source", text: "Evidence ".repeat(350) }] };
test("later SLM stages examine all windows before a case-wide assessment", async () => {
  const seen: SLMRequest[] = [];
  const adapter: SLMAdapter = {
    modelId: "local-test", canFit: r => r.evidence.reduce((n, e) => n + e.text.length, 0) < 1800,
    async infer(r) {
      seen.push(r);
      if (r.operation === "evidence_reasoning") return { ...empty,
        observations: [{ text: "A source claim, not verification", evidenceIds: [r.evidence[0].evidenceId] }] };
      return { ...empty, escalationAssessment: { decision: "escalate", rationale: "Independent verification required", evidenceIds: ["source"], materialGaps: ["Identity unverified"] } };
    },
  };
  const result = await runSLM(request, adapter);
  assert.equal(result.status, "completed");
  assert.ok(seen.filter(r => r.operation === "evidence_reasoning").length > 1);
  assert.equal(seen.at(-1)?.operation, "escalation_assessment");
  const notes = JSON.parse(seen.at(-1)!.evidence[0].text);
  assert.equal(notes.representation, "unverified_local_interpretations_not_source_facts");
  assert.equal(notes.windows[0].start, 0);
  assert.equal(notes.windows.at(-1).end, request.evidence[0].text.length);
});
test("one failed source window prevents a final Finding", async () => {
  let calls = 0;
  const result = await runSLM(request, { modelId: "local-test", canFit: r => r.operation === "evidence_reasoning",
    async infer(r) {
      calls++; if (calls === 2) throw new Error("unavailable");
      return { ...empty, observations: [{ text: "Claim", evidenceIds: [r.evidence[0].evidenceId] }] };
    } });
  assert.equal(result.status, "unavailable");
  assert.equal(calls, 2);
});
test("an oversized complete synthesis stops instead of dropping source windows", async () => {
  let finalCalls = 0;
  const result = await runSLM(request, { modelId: "local-test", canFit: r => r.operation === "evidence_reasoning",
    async infer(r) {
      if (r.operation !== "evidence_reasoning") finalCalls++;
      return { ...empty, observations: [{ text: "Claim", evidenceIds: [r.evidence[0].evidenceId] }] };
    } });
  assert.equal(result.status, "unavailable");
  if (result.status === "unavailable") assert.equal(result.reason, "complete_window_synthesis_context_exceeded");
  assert.equal(finalCalls, 0);
});
