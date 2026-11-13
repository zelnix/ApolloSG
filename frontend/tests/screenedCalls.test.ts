// "Calls Apollo screened": history is built only from what CallScreeningService receives, written only
// after the screening response, and parsed strictly.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isRejectionRequest, parseScreenedCalls, repeatAlertLine, repeatAlertLogRows, SCREENED_OUTCOME_LABEL, screenedOutcomeLabel, screenedWhen } from "../src/domain/screenedCalls.ts";

const read = (p: string) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");

test("parses valid rows newest first and drops malformed ones", () => {
  const rows = parseScreenedCalls(JSON.stringify([
    { number: "+61400000001", at: 1000, outcome: "rang" },
    { number: "+61400000002", at: 3000, outcome: "rejection_requested_block" },
    { number: "", at: 4000, outcome: "rang" },
    { number: "+61400000003", at: "x", outcome: "rang" },
    { number: "+61400000004", at: 5000, outcome: "verified_block" },
    { number: " +61400000005 ", at: 2000, outcome: "allowed_by_you" },
  ]));
  assert.deepEqual(rows.map((r) => r.number), ["+61400000002", "+61400000005", "+61400000001"]);
});

test("garbage input yields an empty list, never a throw", () => {
  for (const bad of [null, undefined, "", "not json", "{}", "42"]) assert.deepEqual(parseScreenedCalls(bad), []);
});

test("rejections are described as requests, never as verified blocks", () => {
  assert.equal(isRejectionRequest("rejection_requested_block"), true);
  assert.equal(isRejectionRequest("rang"), false);
  for (const label of Object.values(SCREENED_OUTCOME_LABEL)) assert.doesNotMatch(label, /\bblocked\b|verified/i);
  assert.match(SCREENED_OUTCOME_LABEL.rejection_requested_risky, /asked Android to reject/);
});

test("day labels", () => {
  const now = new Date(2026, 9, 23, 12, 0, 0);
  assert.equal(screenedWhen(new Date(2026, 9, 23, 9, 5).getTime(), now).day, "Today");
  assert.equal(screenedWhen(new Date(2026, 9, 22, 9, 5).getTime(), now).day, "Yesterday");
});

test("screening service records history only after responding, in its own guard, and never from the call log", () => {
  const kt = read("modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloCallScreeningService.kt");
  const body = kt.slice(kt.indexOf("override fun onScreenCall"));
  assert.match(body, /\} finally \{[\s\S]*try \{ if \(isIncoming\(callDetails\)\) recordScreenedCall\(ctx, number, outcome, numberVerification\) \} catch/);
  // Every record decision follows the respond() call that answers Android.
  for (const outcome of ["allowed_by_you", "rang"]) {
    const at = body.indexOf(`"${outcome}"`);
    assert.ok(at > 0 && body.lastIndexOf("respond(callDetails", at) > 0, outcome);
  }
  assert.doesNotMatch(kt, /android\.provider\.CallLog|READ_CALL_LOG/);
  assert.match(kt, /MAX_SCREENED = 50/);
  assert.match(kt, /SCREENED_RETENTION_MS = 30L \* 24 \* 60 \* 60 \* 1000/);
  // The screening decisions themselves are unchanged.
  assert.match(body, /respond\(callDetails, disallow = true, reject = true, skipNotification = true\)/);
  assert.match(body, /catch \(_: Exception\) \{\s*\/\/ Never let a screening failure hang up a real call — always fall through to allow\.\s*respond\(callDetails, disallow = false, reject = false\)/);
});

test("Delete My Apollo Data also clears the screened-call history", () => {
  assert.match(read("src/store/ApolloContext.tsx"), /await wipeLocalApolloData\(\);[\s\S]{0,200}ScreenedCalls\.clear\(\)/);
});

// ── Repeat Caller Alert ──────────────────────────────────────────────────────────────────────────
const alerted = (at: number, reason: string, alert = "shown") => ({ number: "+61400000009", at, outcome: reason === "worth_checking" ? "rang" : "rejection_requested_risky", repeat: reason, alert, alertTitle: `T${at}`, alertBody: `B${at}` });

test("a Repeat Caller Alert on a screened call is parsed strictly; anything malformed is just a plain row", () => {
  const rows = parseScreenedCalls(JSON.stringify([
    alerted(3000, "high_risk"),
    { ...alerted(2000, "worth_checking"), alert: "maybe" },
    { ...alerted(1000, "nonsense") },
  ]));
  assert.deepEqual(rows[0].repeat, { reason: "high_risk", shown: true, title: "T3000", body: "B3000" });
  assert.equal(rows[1].repeat, undefined);
  assert.equal(rows[2].repeat, undefined);
});

test("a worth-checking number that rang with an alert never reads as 'no warning'", () => {
  const [worth, plain] = parseScreenedCalls(JSON.stringify([alerted(2000, "worth_checking", "not_shown"), { number: "+61400000001", at: 1000, outcome: "rang" }]));
  assert.equal(screenedOutcomeLabel(worth), "Found worth checking earlier — rang through");
  assert.match(repeatAlertLine(worth) ?? "", /notifications are off/);
  assert.equal(screenedOutcomeLabel(plain), SCREENED_OUTCOME_LABEL.rang);
  assert.equal(repeatAlertLine(plain), null);
});

test("only alerts newer than the last copy join the alert history, oldest first; a hidden one is a failed delivery", () => {
  const calls = parseScreenedCalls(JSON.stringify([alerted(3000, "high_risk"), alerted(2000, "worth_checking", "not_shown"), alerted(1000, "block_list"), { number: "+6140", at: 4000, outcome: "rang" }]));
  const rows = repeatAlertLogRows(calls, 1000);
  assert.deepEqual(rows.map((r) => r.id), ["repeat-2000", "repeat-3000"]);
  assert.equal(rows[0].state, "failed");
  assert.equal(rows[1].state, "shown");
  assert.equal(rows[1].detail, null);
});

test("the alert is raised only after Android has its answer, inside the history guard, and never reads the call log", () => {
  const kt = read("modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloCallScreeningService.kt");
  const record = kt.slice(kt.indexOf("private fun recordScreenedCall"));
  assert.match(record, /try \{\s*repeatCallerAlert\(ctx, number, outcome, at\)[\s\S]*?\} catch \(_: Exception\) \{ \}/);
  const body = kt.slice(kt.indexOf("override fun onScreenCall"));
  assert.doesNotMatch(body.slice(0, body.indexOf("} finally {")), /repeatCallerAlert|notify\(/);
  // On a locked screen the number is hidden; tapping opens Check a number on that number.
  assert.match(kt, /setVisibility\(NotificationCompat\.VISIBILITY_PRIVATE\)[\s\S]*setPublicVersion\(locked\)/);
  assert.match(kt, /apollo:\/\/call-guard\?number=\$\{Uri\.encode\(number\)\}&repeat=\$at/);
  assert.match(read("modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloSecurityModule.kt"), /AsyncFunction\("setNumberWorthChecking"\)/);
});

test("a worth-checking result is remembered for the alert and a clean one forgets it", () => {
  assert.match(read("src/store/ApolloContext.tsx"), /if \(result\.decision === "review" \|\| result\.decision === "allow"\) void CallSdk\.setNumberWorthChecking\(result\.number, result\.decision === "review"\)/);
});
