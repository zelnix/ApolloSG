import test from "node:test";
import assert from "node:assert/strict";
import { assessMandatoryWright, respondToWrightStage } from "../src/domain/slm/wrightPhase6.ts";

const evidence = [{ evidenceId: "source-1", text: "Invoice for completed services." }];
const adapter = {
  modelId: "native-test",
  async infer(request: { evidence: readonly { evidenceId: string }[] }) {
    return {
      version: "wright.semantic.v1", classification: "legitimate_context",
      scamTypes: [], intent: "Routine invoice", coercion: "absent",
      exposure: { payment: "UNKNOWN", credentials: "UNKNOWN",
        identity: "UNKNOWN", remoteAccess: "UNKNOWN" },
      narrative: "An ordinary invoice does not establish a scam.",
      uncertainty: "Sender not independently verified",
      supportingEvidenceIds: [request.evidence[0].evidenceId],
    };
  },
};

test("missing native model returns limited, never a verdict", async () => {
  const result = await assessMandatoryWright(evidence, null);
  assert.equal(result.status, "limited");
});

test("native assessment cites original source IDs rather than window IDs", async () => {
  const result = await assessMandatoryWright(evidence, adapter);
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.deepEqual(result.semantic.supportingEvidenceIds, ["source-1"]);
    assert.equal(result.semantic.classification, "legitimate_context");
  }
});

test("existing stage handoff carries semantic JSON, not a verdict", async () => {
  const result = await respondToWrightStage({
    caseId: "case-1234", caseRevision: 1, requestId: "request-1234",
    role: "wright_triage", operation: "wright_semantic", evidence,
  }, adapter);
  assert.equal(result.status, "ready");
  if (result.status === "ready") {
    const answer = result.payload.answer as Record<string, unknown>;
    assert.ok(answer.wrightSemantic);
    assert.equal(answer.caseFinding, undefined);
  }
});

test("invalid stage is rejected before inference", async () => {
  const result = await respondToWrightStage({
    caseId: "case-1234", caseRevision: 1, requestId: "request-1234",
    role: "higgins_triage", operation: "investigation_readiness", evidence,
  }, adapter);
  assert.equal(result.status, "limited");
});

test("existing generic SLM event consumer dispatches mandatory multi-window assessment", async () => {
  const { runSLM } = await import("../src/domain/slm/index.ts");
  let invocations = 0;
  const result = await runSLM({
    role: "wright_triage", operation: "wright_semantic",
    question: "Server-issued mandatory triage", evidence: [
      { evidenceId: "source-long", text: "Routine invoice. ".repeat(250) },
    ],
  }, {
    modelId: "native-test",
    async infer(request) {
      invocations++;
      return adapter.infer(request);
    },
  });
  assert.equal(result.status, "completed");
  assert.ok(invocations > 1, "all evidence windows must be examined");
  if (result.status === "completed") {
    assert.deepEqual(result.answer.wrightSemantic?.supportingEvidenceIds, ["source-long"]);
  }
});

test("one failed native window blocks the entire stage", async () => {
  const { runSLM } = await import("../src/domain/slm/index.ts");
  let invocations = 0;
  const result = await runSLM({
    role: "wright_triage", operation: "wright_semantic",
    question: "Server-issued mandatory triage", evidence: [
      { evidenceId: "source-long", text: "Invoice. ".repeat(400) },
    ],
  }, {
    modelId: "native-test",
    async infer(request) {
      invocations++;
      if (invocations === 2) throw new Error("native inference unavailable");
      return adapter.infer(request);
    },
  });
  assert.equal(result.status, "unavailable");
});

test("Phase 8: more than 32 cited sources must fail rather than silently discard references", async () => {
  const many = Array.from({ length: 33 }, (_, index) => ({
    evidenceId: "source-" + index, text: "Payment requested from source " + index,
  }));
  const result = await assessMandatoryWright(many, adapter);
  assert.equal(result.status, "limited");
  if (result.status === "limited") assert.equal(result.reason, "synthesis_contract_failed");
});

test("Phase 8: contradictory scam and legitimate windows remain ambiguous", async () => {
  const result = await assessMandatoryWright([
    { evidenceId: "legit", text: "Receipt for an order already paid." },
    { evidenceId: "scam", text: "Send your password to an unknown contact." },
  ], {
    modelId: "native-test",
    async infer(request) {
      const isScam = request.evidence[0].text.includes("password");
      return {
        ...(await adapter.infer(request)),
        classification: isScam ? "scam_indicators" : "legitimate_context",
      };
    },
  });
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.equal(result.semantic.classification, "ambiguous");
    assert.match(result.semantic.uncertainty ?? "", /Conflicting/);
  }
});
