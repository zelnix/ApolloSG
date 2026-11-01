// Check This Call reads `options?.origin`; `options` must be a declared parameter, or every
// suspicious call check throws "options is not defined" before its case is recorded.
// Run: node --test tests/checkCallOptions.test.ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const ctx = readFileSync(new URL("../src/store/ApolloContext.tsx", import.meta.url), "utf8");

test("checkCall declares the options it reads", () => {
  assert.match(ctx, /const checkCall = useCallback\(async \(input: CallInput, options\?: CallCheckOptions\) =>/);
  assert.match(ctx, /checkCall\(input: CallInput, options\?: CallCheckOptions\): Promise</);
  const body = ctx.slice(ctx.indexOf("const checkCall = useCallback"), ctx.indexOf("const checkNumberRisk = useCallback"));
  assert.ok(body.includes('origin: options?.origin ?? "user"'), "a described call is a real user check unless Sample Checks says otherwise");
});
