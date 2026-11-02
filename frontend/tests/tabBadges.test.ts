import assert from "node:assert/strict";
import { test } from "node:test";

import { badgeText, countNeedingYou, countNewSevereAlerts } from "../src/domain/tabBadges.ts";

const event = (id: string, state: string, at: string, extra: Record<string, unknown> = {}) =>
  ({ event_id: id, case_key: extra.case_key ?? id, state, occurred_at: at, ...extra }) as never;

// "Needs you" needs a concrete reason: Apollo's own Barking record with its reason and next step, or a case whose
// Higgins Case Briefing says a decision is owed and why (src/domain/caseBriefing.ts needsYou).
const decided = { why: ["The link goes to st0ko-login.co, not stoko.com."], what_to_do: "Don't open the link." };
const briefing = (userActionRequired: boolean, actionReason: string | null) =>
  ({ investigation_case_id: "case-1", investigation_completed_at: "2026-06-01T09:05:00Z", case_briefing: { from: "briefing", headline: "Stoko link checked", summary: "…", subject: "st0ko-login.co",
    findings: [], unresolved: [], status: "", statusReason: "", userActionRequired, actionReason, recommendedAction: null } });

test("Threats counts each case that still needs the person, once, by its latest event", () => {
  const events = [
    event("a1", "barking", "2026-06-01T10:00:00Z", { case_key: "a", ...decided }),
    event("a2", "barking", "2026-06-01T11:00:00Z", { case_key: "a", ...decided }),
    event("b1", "biting", "2026-06-01T09:00:00Z", decided),
    event("c1", "growling", "2026-06-01T09:00:00Z", decided),
    event("d1", "barking", "2026-06-01T09:00:00Z", { resolved_at: "2026-06-01T12:00:00Z", ...decided }),
    event("e1", "barking", "2026-06-01T09:00:00Z"), // no recorded reason or next step
    event("f1", "barking", "2026-06-01T09:00:00Z", briefing(true, "Anything typed into that link goes to whoever runs st0ko-login.co.")),
    event("g1", "barking", "2026-06-01T09:00:00Z", briefing(true, null)), // a decision flag without its reason
    event("h1", "barking", "2026-06-01T09:00:00Z", briefing(false, null)),
  ];
  assert.equal(countNeedingYou(events), 3);
});

test("a handled case stops counting when its latest event is handled", () => {
  const events = [
    event("a1", "barking", "2026-06-01T10:00:00Z", { case_key: "a", ...decided }),
    event("a2", "barking", "2026-06-01T11:00:00Z", { case_key: "a", resolved_at: "2026-06-01T11:00:00Z", ...decided }),
  ];
  assert.equal(countNeedingYou(events), 0);
  assert.equal(countNeedingYou([]), 0);
});

test("Scam Alerts counts only new High and Extreme alerts that apply here", () => {
  const alerts = [
    { url: "u1", severity: "HIGH", appliesIn: "everywhere", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u2", severity: "EXTREME", appliesIn: "AU", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u3", severity: "MODERATE", appliesIn: "everywhere", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u4", severity: "LOW", appliesIn: "AU", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u5", severity: "HIGH", appliesIn: "US", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u6", severity: "HIGH", appliesIn: "AU", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
    { url: "u1", severity: "HIGH", appliesIn: "everywhere", australianRelevance: "confirmed", tier: "specific_scam", verifiedOngoing: true },
  ];
  assert.equal(countNewSevereAlerts(alerts, new Set(["u6"]), "AU"), 3);
  assert.equal(countNewSevereAlerts(alerts, new Set(["u1", "u2", "u6"]), "AU"), 1);
  assert.equal(countNewSevereAlerts(alerts, new Set(), "US"), 4);
});

test("the badge shows nothing at zero and caps at 9+", () => {
  assert.equal(badgeText(0), undefined);
  assert.equal(badgeText(-1), undefined);
  assert.equal(badgeText(3), "3");
  assert.equal(badgeText(9), "9");
  assert.equal(badgeText(12), "9+");
});
