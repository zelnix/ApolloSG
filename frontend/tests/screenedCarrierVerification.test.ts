import { describe, expect, it } from "@jest/globals";
import { parseScreenedCalls } from "../src/domain/screenedCalls";

describe("screened call carrier number verification", () => {
  const call = (numberVerification?: string) => JSON.stringify([{ number: "+61412345678", at: 1730000000000, outcome: "rang", ...(numberVerification ? { numberVerification } : {}) }]);
  it("retains an explicit carrier verification failure", () => {
    expect(parseScreenedCalls(call("failed"))[0].numberVerification).toBe("failed");
  });
  it("retains passed without claiming business identity", () => {
    expect(parseScreenedCalls(call("passed"))[0].numberVerification).toBe("passed");
  });
  it("treats missing or unknown native data as unavailable", () => {
    expect(parseScreenedCalls(call())[0].numberVerification).toBe("unavailable");
    expect(parseScreenedCalls(call("verified_business"))[0].numberVerification).toBe("unavailable");
  });
});
