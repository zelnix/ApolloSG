import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL("../" + path, import.meta.url), "utf8");

test("iOS Call Directory status uses native enabled status, not a local preference", () => {
  const swift = read("modules/apollo-security/ios/ApolloSecurityModule.swift");
  const start = swift.indexOf('AsyncFunction("getCallDirectoryStatus")');
  assert.ok(start > -1);
  const section = swift.slice(start, swift.indexOf('AsyncFunction("requestCallScreeningRole")', start));
  assert.match(section, /getEnabledStatusForExtension/);
  assert.match(section, /case \.enabled:/);
  assert.match(section, /case \.disabled:/);
  assert.match(section, /"status": "error"/);
  assert.doesNotMatch(section, /UserDefaults|setBool|setValue/);
});

test("setup refreshes on foreground and never infers enforcement from role ownership", () => {
  const hook = read("src/hooks/useCallScreener.ts");
  assert.match(hook, /AppState\.addEventListener\("change"/);
  assert.match(hook, /CallSdk\.getCallDirectoryStatus\(\)/);
  assert.match(hook, /CallSdk\.getCallScreeningRoleStatus\(\)/);
  assert.match(hook, /does not confirm that any particular call was blocked/);
  assert.match(hook, /iOS does not confirm individual blocked calls/);
});

test("existing Call Gate uses one setup card and one screened-call list", () => {
  const page = read("app/call-guard.tsx");
  assert.equal((page.match(/<CallScreenerCard\b/g) ?? []).length, 1);
  assert.equal((page.match(/<ScreenedCallsList\b/g) ?? []).length, 1);
  assert.ok(page.indexOf("<CallScreenerCard") < page.indexOf("<ScreenedCallsList"));
  assert.ok(page.indexOf("<ScreenedCallsList") < page.indexOf('testID="callguard-search-section"'));
});

test("setup does not create verified enforcement evidence", () => {
  const card = read("src/components/CallScreenerCard.tsx");
  const hook = read("src/hooks/useCallScreener.ts");
  assert.doesNotMatch(card + hook, /verifiedCallBlock|THREAT_BLOCKED|blockEvent\(/);
  assert.match(card, /Check status again/);
});

test("recent caller-first list only uses native observed screening history", () => {
  const list = read("src/components/ScreenedCallsList.tsx");
  assert.match(list, /Recent callers/);
  assert.match(list, /ScreenedCalls\.list\(\)/);
  assert.match(list, /this is not your phone/);
  assert.doesNotMatch(list, /PhonePickers|listRecentCalls|READ_CALL_LOG/);
});

test("caller details reuse existing phone identity component, not an invented logo source", () => {
  const page = read("app/call-guard.tsx");
  const card = read("src/components/PhoneIdentityCard.tsx");
  assert.match(page, /<PhoneIdentityCard number=\{result\.number\}/);
  assert.match(card, /identifyNumber\(number, country\)/);
  assert.doesNotMatch(card, /logo\.clearbit|google\.com\/s2\/favicons/);
});
