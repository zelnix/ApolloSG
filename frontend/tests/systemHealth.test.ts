import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { test } from "node:test";

import { reportHtml, validReport } from "../src/investigation/reportHtml.ts";
import { healthyProbe, overallStatus } from "../src/health/systemHealthPolicy.ts";

const checkedAt = "2026-09-24T12:00:00.000Z";
const healthy = { status: "healthy" as const, code: null, checkedAt };
const fixture = { reportId: "synthetic", caseId: "health-synthetic", gates: ["device"], savedAt: checkedAt,
  overview: "<script>alert(1)</script>", explanationMarkdown: "Fictional reminder only.", assessment: "uncertain", attention: "none",
  scope: "Synthetic health check", responseRevision: 1, findings: ["No real device"], uncertainties: ["Not observed"],
  actions: [], sources: [], historical: false, retentionNotice: "Deleted immediately" };

test("public probe accepts only schema-one 200 liveness, never 4xx or HTML", () => {
  const body = { schemaVersion: 1, status: "ok", service: "apollo-v1", checkedAt };
  assert.equal(healthyProbe(200, body), true);
  assert.equal(healthyProbe(404, body), false);
  assert.equal(healthyProbe(503, body), false);
  assert.equal(healthyProbe(200, "<html>OK</html>"), false);
  assert.equal(healthyProbe(200, { ...body, schemaVersion: 2 }), false);
  assert.equal(healthyProbe(200, { ...body, checkedAt: "not-a-date" }), false);
});

test("a partial or privacy-cleanup failure cannot be shown as healthy", () => {
  const all = { device: healthy, backend: healthy, higgins: healthy, report: healthy };
  assert.equal(overallStatus(all), "healthy");
  assert.equal(overallStatus({ ...all, higgins: { status: "degraded", code: "provider_timeout", checkedAt } }), "degraded");
  assert.equal(overallStatus({ ...all, device: { status: "unavailable", code: "native_build_required", checkedAt } }), "degraded");
  assert.equal(overallStatus({ ...all, backend: { status: "unavailable", code: "db_unreachable", checkedAt } }), "unavailable");
  assert.equal(overallStatus({ ...all, report: { status: "unavailable", code: "cleanup_not_confirmed", checkedAt } }), "unavailable");
  assert.equal(overallStatus({ ...all, report: { status: "unavailable", code: "device_cleanup_failed", checkedAt } }), "unavailable");
});

test("health fixture uses the normal saved-report renderer and escapes model text", () => {
  assert.equal(validReport(fixture), true);
  const html = reportHtml(fixture);
  assert.match(html, /Apollo Investigation Report/);
  assert.match(html, /Synthetic health check/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
  assert.equal(validReport({ ...fixture, actions: [{}] }), false);
  assert.equal(validReport({ ...fixture, savedAt: "invalid" }), false);
});

test("benchmark, acceptance and notification probes are not mobile routes", () => {
  assert.equal(existsSync("app/benchmark.tsx"), false);
  assert.equal(existsSync("app/guarddog-acceptance.tsx"), false);
  assert.equal(existsSync("src/benchmark/corpus.json"), false);
  assert.doesNotMatch(readFileSync("app/settings/index.tsx", "utf8"), /settings-push-test/);
  assert.doesNotMatch(readFileSync("app/_layout.tsx", "utf8"), /<Stack.Screen name="benchmark"/);
});

test("Support has exactly four health results and the approved plain-English labels", () => {
  const support = readFileSync("app/support.tsx", "utf8");
  for (const label of ["Apollo protection", "ApolloSG services", "Higgins investigations", "Higgins reports"]) assert.match(support, new RegExp(`label="${label}"`));
  for (const label of ["Checking", "Working", "Needs attention", "Could not check"]) assert.match(support, new RegExp(label));
  assert.match(support, /testID="support-go-to-check" label="Ask Higgins"/);
  assert.doesNotMatch(support, /support-health-overall|support-services-card|support-build-card/);
  assert.match(support, /support-more-details-panel/);
});