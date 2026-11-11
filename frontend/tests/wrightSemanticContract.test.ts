import test from "node:test";
import assert from "node:assert/strict";
import { validateWrightSemantic } from "../src/domain/slm/wrightSemanticContract.ts";

function sample(): Record<string, unknown> {
  return { version: "wright.semantic.v1", classification: "ambiguous", scamTypes: [],
    intent: "Asks for a reply", coercion: "uncertain",
    exposure: { payment: "UNKNOWN", credentials: "UNKNOWN", identity: "UNKNOWN", remoteAccess: "UNKNOWN" },
    narrative: "The source asks for a reply without proof of deception.", uncertainty: "Identity not verified",
    supportingEvidenceIds: [] };
}
test("uncertain semantic case accepted", () => assert.ok(validateWrightSemantic(sample(), ["source-1"])));
for (const [label, change] of [
  ["unknown field", { verdict: "NO_THREAT_IDENTIFIED" }],
  ["unsupported evidence", { supportingEvidenceIds: ["another-device"] }],
  ["unsupported coercion", { coercion: "present" }],
  ["unsupported confirmed exposure", { exposure: { payment: "CONFIRMED", credentials: "UNKNOWN", identity: "UNKNOWN", remoteAccess: "UNKNOWN" } }],
  ["unknown version", { version: "wright.semantic.v2" }],
] as const) {
  test(`rejects ${label}`, () => assert.equal(validateWrightSemantic({ ...sample(), ...change }, ["source-1"]), null));
}
test("grounded interpretation accepted", () => assert.ok(validateWrightSemantic(
  { ...sample(), classification: "scam_indicators", supportingEvidenceIds: ["source-1"] }, ["source-1"])));
