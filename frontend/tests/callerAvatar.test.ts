import { test } from "node:test";
import assert from "node:assert/strict";
import { callerAvatarForIdentity } from "../src/domain/callerAvatar";

const identity = (overrides: Partial<Parameters<typeof callerAvatarForIdentity>[0]> = {}) => ({
  associated_entity: null,
  association_confidence: "unknown" as const,
  known_impersonation: false,
  scam_intel: null,
  ...overrides,
});

test("unknown caller remains unknown", () => {
  assert.equal(callerAvatarForIdentity(identity()), "unknown");
});
test("possible business association does not earn business identity avatar", () => {
  assert.equal(callerAvatarForIdentity(identity({ associated_entity: "Example Company", association_confidence: "possible" })), "unknown");
});
test("strong association receives business-association icon, not an official logo", () => {
  assert.equal(callerAvatarForIdentity(identity({ associated_entity: "Example Company", association_confidence: "strong" })), "business_association");
});
test("impersonation warning takes precedence over even a verified number association", () => {
  assert.equal(callerAvatarForIdentity(identity({ associated_entity: "Example Company", association_confidence: "verified", known_impersonation: true })), "risk_warning");
});
test("scam intelligence takes precedence over an associated business", () => {
  assert.equal(callerAvatarForIdentity(identity({ associated_entity: "Example Company", association_confidence: "strong", scam_intel: "Reported scam activity" })), "risk_warning");
});
