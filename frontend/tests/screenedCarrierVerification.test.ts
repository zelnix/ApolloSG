import { describe, expect, it } from "node:test";\nimport assert from "node:assert/strict";
import { parseScreenedCalls } from "../src/domain/screenedCalls";

describe("screened call carrier number verification", () => {
  const call = (numberVerification?: string) => JSON.stringify([{ number: "+61412345678", at: 1730000000000, outcome: "rang", ...(numberVerification ? { numberVerification } : {}) }]);
  it("retains an explicit carrier verification failure", () => {
    assert.equal(parseScreenedCalls(call("failed"))[0].numberVerification, "failed");
  });
  it("retains passed without claiming business identity", () => {
    assert.equal(parseScreenedCalls(call("passed"))[0].numberVerification, "passed");
  });
  it("treats missing or unknown native data as unavailable", () => {
    assert.equal(parseScreenedCalls(call())[0].numberVerification, "unavailable");
    assert.equal(parseScreenedCalls(call("verified_business"))[0].numberVerification, "unavailable");
  });
});
