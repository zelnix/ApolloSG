import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL("../" + path, import.meta.url), "utf8");

test("Android contact lookup is permission gated and does not use call-log permission", () => {
  const native = read("modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloSecurityModule.kt");
  const start = native.indexOf('AsyncFunction("lookupCallerContact")');
  assert.ok(start >= 0);
  const method = native.slice(start, native.indexOf('AsyncFunction("listRecentCalls")', start));
  assert.match(method, /READ_CONTACTS/);
  assert.match(method, /PERMISSION_GRANTED/);
  assert.match(method, /PhoneLookup.CONTENT_FILTER_URI/);
  assert.doesNotMatch(method, /READ_CALL_LOG|apiPost|http/);
});

test("contact photos require explicit user action and do not auto-load", () => {
  const ui = read("src/components/CallerContactPhoto.tsx");
  assert.match(ui, /Show saved contact photo \(optional\)/);
  assert.match(ui, /requestRuntimePermission\("contacts"\)/);
  assert.match(ui, /Caller identity not verified/);
  assert.doesNotMatch(ui, /useEffect\(/);
});

test("Call Gate keeps observed screening history separate from optional contact lookup", () => {
  const list = read("src/components/ScreenedCallsList.tsx");
  assert.match(list, /ScreenedCalls\.list\(\)/);
  assert.match(list, /<CallerContactPhoto/);
});
