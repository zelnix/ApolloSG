import assert from "node:assert/strict";
import { test } from "node:test";

import { buildHomeAttention } from "../src/domain/homeAttention.ts";
import type { GatePresentation } from "../src/domain/gates.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

const gate = (over: Partial<GatePresentation> & Pick<GatePresentation, "id" | "tone">): GatePresentation => ({
  id: over.id, title: over.title ?? "Internet Gate", purpose: "", currentHelp: over.currentHelp ?? "Protection stopped.",
  statusLabel: "Action needed", tone: over.tone,
  capability: over.capability ?? { automatic: { kind: "monitoring", state: "interrupted", limitation: "Reconnect to restore protection." } },
  primaryAction: over.primaryAction ?? { id: "check_network", label: "Reconnect Internet Gate" },
  resolved: over.resolved ?? { coverageState: "temporarily_unavailable", isAutomatic: true },
});

const event = (over: Partial<PatrolEvent>): PatrolEvent => ({
  event_id: "e1", device_id: "d1", category: "app", state: "barking", status: "active",
  headline: "Suspicious app", what_happened: "An app can control your screen.", why: ["remote access"],
  what_to_do: "Remove the app in Settings.", indicator_host: null, indicator_digest: null, verified_block: false,
  adapter_label: "Apollo", occurred_at: "2026-10-08T04:00:00Z", resolved_at: null, ...over,
});

test("a gate in Action needed becomes a specific attention item (gate named + Higgins step)", () => {
  const items = buildHomeAttention({ gates: [gate({ id: "site", tone: "action", title: "Site Gate", currentHelp: "Website protection stopped.", primaryAction: { id: "restore_site", label: "Turn on Site Gate" }, capability: { automatic: { kind: "enforcement", state: "interrupted", limitation: "Turn Site Gate back on." } } })], events: [] });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "gate");
  assert.equal(items[0].title, "Site Gate needs attention");
  assert.equal(items[0].problem, "Website protection stopped.");
  assert.equal(items[0].higgins, "Turn Site Gate back on.");
  assert.equal(items[0].actionLabel, "Turn on Site Gate");
});

test("an active barking event becomes an attention item naming the gate and the fix", () => {
  const items = buildHomeAttention({ gates: [], events: [event({})] });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "event");
  assert.equal(items[0].gate, "App checking");
  assert.equal(items[0].problem, "An app can control your screen.");
  assert.equal(items[0].higgins, "Remove the app in Settings.");
  assert.match(items[0].route, /^\/patrol\//);
});

test("optional setup never creates an attention item (no false barking); growling events do appear", () => {
  // Gates in neutral tone (optional setup) must not raise an attention item on their own.
  const gates = [gate({ id: "text", tone: "neutral" }), gate({ id: "email", tone: "neutral" })];
  // Growling events (e.g. a suspected scam message, device setting change, insecure connection)
  // ARE user-facing concerns that belong on the Protection Details screen.
  const growlEvent = event({ event_id: "g1", state: "growling" });
  const resolvedEvent = event({ event_id: "r1", state: "resting", status: "resolved", resolved_at: "2026-10-08T04:05:00Z" });
  const items = buildHomeAttention({ gates, events: [growlEvent, resolvedEvent] });
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "event");
  assert.equal(items[0].title, "Suspicious app — has a warning sign");
});

test("barking events are ranked above growling and ears_up events", () => {
  const items = buildHomeAttention({ gates: [], events: [
    event({ event_id: "e1", state: "ears_up" }),
    event({ event_id: "e2", state: "growling" }),
    event({ event_id: "e3", state: "barking" }),
  ]});
  assert.equal(items.length, 3);
  assert.equal(items[0].event?.event_id, "e3"); // barking first
  assert.equal(items[1].event?.event_id, "e2"); // growling
  assert.equal(items[2].event?.event_id, "e1"); // ears_up last
});

test("a resolved barking event is no longer active, so it drops out of attention", () => {
  const items = buildHomeAttention({ gates: [], events: [event({ status: "resolved", resolved_at: "2026-10-08T04:05:00Z" })] });
  assert.equal(items.length, 0);
});

test("gate failures are listed before event decisions", () => {
  const items = buildHomeAttention({ gates: [gate({ id: "site", tone: "action" })], events: [event({})] });
  assert.equal(items[0].kind, "gate");
  assert.equal(items[1].kind, "event");
});
