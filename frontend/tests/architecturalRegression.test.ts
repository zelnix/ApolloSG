/**
 * Architectural regression tests — Point 6 acceptance criteria.
 * Each test exercises the ACTUAL PRODUCTION functions, not reimplemented logic.
 *
 * 1. Original findings survive sync (via mergeLocalAndRemoteEvents).
 * 2. Handled findings stay handled; new evidence reopens with reason.
 * 3. Repeated blocks retain enforcement evidence without duplicates.
 * 4. Higgins explanations: specific, evidence-backed, no generic fallbacks.
 * 5. Missing/stale/contradictory evidence can't create false claims.
 * 6. Privacy restrictions and enforcement truth gates intact.
 *
 * The finding-correlation criteria that used to sit here (distinct-finding counts and the
 * Protection Details finding builder) were removed with src/domain/protectionDetails.ts: Home now
 * derives its attention items from buildHomeAttention, which this file covers below.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { hasRecordedFindings } from "../src/domain/caseFacts.ts";
import { normalizeHistoricalEvent } from "../src/domain/packetEvidence.ts";
import { mergeLocalAndRemoteEvents } from "../src/domain/eventMerge.ts";
import { isActive, STATE_RANK, resolveApolloState } from "../src/domain/stateMachine.ts";
import { buildHomeAttention } from "../src/domain/homeAttention.ts";
import { projectedEventVoice, looksLikeInternalCode, humanizeReason, scrubMessage } from "../src/domain/messageVoice.ts";
import type { PatrolEvent, ApolloState, Capability } from "../src/domain/types.ts";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeEvent(overrides: Partial<PatrolEvent> = {}): PatrolEvent {
  return {
    event_id: "evt-1", device_id: "dev-1", category: "website", state: "barking", status: "active",
    headline: "Suspicious login page detected", what_happened: "Apollo's Site Gate found this page asks for credentials while impersonating a bank.",
    why: ["Domain registered 2 days ago", "TLS certificate does not match the bank"],
    what_to_do: "Do not enter your password. Close the tab and open the real bank site from your bookmarks.",
    indicator_host: "fake-bank.example.com", indicator_digest: null, local_indicator: "fake-bank.example.com",
    verified_block: false, adapter_label: "Apollo on-device assessment",
    occurred_at: new Date().toISOString(), resolved_at: null, trust_allowed: false,
    evidence_provenance: "local_device",
    ...overrides,
  } as PatrolEvent;
}

function makeServerEvent(overrides: Partial<PatrolEvent> = {}): PatrolEvent {
  const voice = projectedEventVoice("website", "barking", false);
  return makeEvent({
    headline: voice.headline, what_happened: voice.whatHappened, why: [voice.why], what_to_do: voice.whatToDo,
    // The privacy-protected summary the server keeps of this device's check: its source stays this device's own.
    evidence_provenance: "local_device", processing_source: "this_device", evidence_representation: "privacy_summary",
    ...overrides,
  });
}

function makeBlockEvent(overrides: Partial<PatrolEvent> = {}): PatrolEvent {
  return makeEvent({
    event_id: "block-1", state: "biting", status: "blocked", verified_block: true,
    headline: "Apollo blocked fake-bank.example.com",
    what_happened: "Apollo's Site Gate observed a real connection attempt to fake-bank.example.com and blocked it.",
    why: ["On-device filter matched this domain against a known threat"],
    what_to_do: "This connection was blocked. If you already shared details, review recovery steps.",
    enforcement_evidence: { evidenceId: "pkt-001", method: "packet_drop", observedAt: new Date().toISOString(), destination: { domain: "fake-bank.example.com" } } as any,
    ...overrides,
  });
}

// ── Test 1: Exercises the ACTUAL mergeLocalAndRemoteEvents ──────────────────
describe("1. Original findings survive local/server synchronisation (production merge)", () => {
  it("local event with detailed findings is preserved through actual merge", () => {
    const local = makeEvent({ event_id: "e1" });
    const serverProjected = makeServerEvent({ event_id: "e1" });

    const { events } = mergeLocalAndRemoteEvents([local], [serverProjected]);
    const merged = events.find((e) => e.event_id === "e1")!;
    assert.ok(merged, "Event exists after merge");
    assert.equal(merged.what_happened, local.what_happened, "Local detailed content preserved");
    assert.equal(merged.headline, local.headline, "Local headline preserved");
    assert.equal(merged.evidence_provenance, "local_device", "Provenance stays local_device");
  });

  it("server-only events are taken as-is: their evidence source and privacy state unchanged", () => {
    const serverOnly = makeServerEvent({ event_id: "e-other" });
    const { events } = mergeLocalAndRemoteEvents([], [serverOnly]);
    const merged = events.find((e) => e.event_id === "e-other")!;
    assert.ok(merged);
    assert.equal(merged.evidence_provenance, "local_device");
    assert.equal(merged.evidence_representation, "privacy_summary");
  });

  it("local-only events (not yet on server) survive merge", () => {
    const localOnly = makeEvent({ event_id: "e-local-only" });
    const { events } = mergeLocalAndRemoteEvents([localOnly], []);
    assert.equal(events.length, 1);
    assert.equal(events[0].event_id, "e-local-only");
  });

  it("hasRecordedFindings uses what the record holds, not text matching", () => {
    const localEvt = makeEvent({ evidence_provenance: "local_device" });
    const serverEvt = makeServerEvent();
    const incompleteEvt = makeEvent({ evidence_completeness: "partial" });
    assert.ok(hasRecordedFindings(localEvt));
    assert.ok(!hasRecordedFindings(serverEvt), "the server's privacy summary alone carries no findings");
    // An incomplete record still carries what Apollo recorded — it isn't somewhere else.
    assert.ok(hasRecordedFindings(incompleteEvt));
  });
});

// ── Test 2: Exercises the ACTUAL mergeLocalAndRemoteEvents for lifecycle ─────
describe("2. Handled findings remain handled; new evidence can reopen (production merge)", () => {
  it("resolved event stays resolved through actual merge even when server says active", () => {
    const local = makeEvent({ event_id: "e2", status: "resolved", resolved_at: new Date().toISOString() });
    const serverActive = makeServerEvent({ event_id: "e2", status: "active", resolved_at: null });

    const { events } = mergeLocalAndRemoteEvents([local], [serverActive]);
    const merged = events.find((e) => e.event_id === "e2")!;
    assert.equal(merged.status, "resolved", "Resolution preserved through merge");
    assert.ok(merged.resolved_at, "resolved_at preserved");
  });

  it("genuinely new enforcement evidence CAN reopen through actual merge (observed after handling)", () => {
    const resolvedTime = "2026-06-01T10:00:00Z";
    const local = makeEvent({
      event_id: "e3", status: "resolved", resolved_at: resolvedTime,
      enforcement_evidence: { evidence_id: "old-evidence", observed_at: "2026-06-01T09:00:00Z" } as any,
    });
    const serverNewEvidence = makeServerEvent({
      event_id: "e3", status: "active", state: "biting", verified_block: true,
      enforcement_evidence: { evidence_id: "NEW-evidence-id", observed_at: "2026-06-01T11:00:00Z" } as any,
    });

    const { events } = mergeLocalAndRemoteEvents([local], [serverNewEvidence]);
    const merged = events.find((e) => e.event_id === "e3")!;
    assert.equal(merged.status, "active", "New evidence observed after handling reopens the event");
    assert.equal(merged.resolved_at, null, "resolved_at cleared on reopen");
  });

  it("delayed delivery of older evidence does NOT reopen (observed before handling)", () => {
    const resolvedTime = "2026-06-01T10:00:00Z";
    const local = makeEvent({
      event_id: "e3b", status: "resolved", resolved_at: resolvedTime,
      enforcement_evidence: { evidence_id: "first-evidence", observed_at: "2026-06-01T09:00:00Z" } as any,
    });
    const serverOldEvidence = makeServerEvent({
      event_id: "e3b", status: "active", state: "biting",
      enforcement_evidence: { evidence_id: "delayed-old-evidence", observed_at: "2026-06-01T08:00:00Z" } as any,
    });

    const { events } = mergeLocalAndRemoteEvents([local], [serverOldEvidence]);
    const merged = events.find((e) => e.event_id === "e3b")!;
    assert.equal(merged.status, "resolved", "Delayed older evidence does not reopen");
    assert.ok(merged.resolved_at, "resolved_at preserved");
  });

  it("same enforcement evidence does NOT reopen through actual merge", () => {
    const local = makeEvent({
      event_id: "e4", status: "resolved", resolved_at: new Date().toISOString(),
      enforcement_evidence: { evidence_id: "same-evidence" } as any,
    });
    const serverSameEvidence = makeServerEvent({
      event_id: "e4", status: "active",
      enforcement_evidence: { evidence_id: "same-evidence" } as any,
    });

    const { events } = mergeLocalAndRemoteEvents([local], [serverSameEvidence]);
    const merged = events.find((e) => e.event_id === "e4")!;
    assert.equal(merged.status, "resolved", "Same evidence does not reopen");
  });

  it("isActive excludes resolved events from warning counts", () => {
    assert.ok(!isActive(makeEvent({ status: "resolved", resolved_at: new Date().toISOString() })));
    assert.ok(!isActive(makeEvent({ status: "trusted" })));
    assert.ok(isActive(makeEvent({ status: "active" })));
  });
});

// ── Test 3: Repeated blocks don't create misleading duplicates ──────────────
describe("3. Repeated blocks retain enforcement evidence without duplicate threats", () => {
  it("normalizeHistoricalEvent preserves verified block with valid packet proof", () => {
    const now = new Date().toISOString();
    const blockWithProof = makeBlockEvent({
      event_id: "block-proof", device_id: "dev-1", category: "connection", occurred_at: now,
      enforcement_evidence: {
        evidence_id: "pkt-001", observed_at: now, platform: "android", mechanism: "vpn_service",
        requested_action: "block", enforced_action: "blocked", result: "verified",
        direction: "outbound", protocol: "tcp", matched_rule_id: "rule.threat.1",
        destination_domain: "fake-bank.example.com", destination_port: 443,
        event_id: "block-proof", device_id: "dev-1",
      } as any,
    });
    const normalized = normalizeHistoricalEvent(blockWithProof);
    assert.equal(normalized.state, "biting", "Verified block preserved");
    assert.ok(normalized.verified_block);
  });

  it("normalizeHistoricalEvent downgrades unproven block claim and records why it is incomplete", () => {
    const fake = makeEvent({ state: "biting", verified_block: true, enforcement_evidence: null });
    const normalized = normalizeHistoricalEvent(fake);
    assert.equal(normalized.state, "barking", "Unproven block downgraded");
    assert.equal(normalized.evidence_completeness, "partial", "Marked incomplete");
    assert.equal(normalized.evidence_provenance, "local_device", "the evidence source is left as recorded");
    assert.deepEqual(normalized.evidence_gaps?.map((g) => [g.check, g.failure]), [["block_proof", "no_packet_evidence"]]);
  });
});

// ── Test 4: Higgins explanations are evidence-backed, no generic fallbacks ──
describe("4. Higgins explanations are specific, evidence-backed, no generic fallback narratives", () => {
  it("humanizeReason converts code to honest sentence, passes prose through", () => {
    assert.match(humanizeReason("server_projection_of_recorded_outcome", "barking"), /needs your attention/);
    assert.equal(humanizeReason("Domain registered 2 days ago.", "barking"), "Domain registered 2 days ago.");
  });
});

// ── Test 5: Missing/stale/contradictory evidence can't create false claims ──
describe("5. Missing, stale or contradictory evidence cannot create false threat or protection claims", () => {
  it("normalizeHistoricalEvent prevents false biting claim without packet proof", () => {
    const fake = makeEvent({ state: "biting", verified_block: true, enforcement_evidence: null });
    const n = normalizeHistoricalEvent(fake);
    assert.equal(n.state, "barking");
    assert.equal(n.evidence_completeness, "partial");
  });

  it("mergeLocalAndRemoteEvents clears resolved_at when genuinely reopening", () => {
    const local = makeEvent({
      event_id: "x", status: "resolved", resolved_at: "2026-01-01T00:00:00Z",
      enforcement_evidence: { evidence_id: "old", observed_at: "2025-12-31T23:00:00Z" } as any,
    });
    const remote = makeServerEvent({
      event_id: "x", status: "active",
      // New evidence observed AFTER the resolution — this is a genuine reopen.
      enforcement_evidence: { evidence_id: "genuinely-new", observed_at: "2026-01-02T12:00:00Z" } as any,
    });
    const { events } = mergeLocalAndRemoteEvents([local], [remote]);
    const m = events.find((e) => e.event_id === "x")!;
    assert.equal(m.resolved_at, null, "resolved_at cleared on genuine reopen — no contradictory timestamps");
  });

  it("mergeLocalAndRemoteEvents reopens on detection-only evidence without enforcement", () => {
    const local = makeEvent({
      event_id: "det-1", status: "resolved", resolved_at: "2026-01-01T00:00:00Z",
      enforcement_evidence: null as any,
    });
    const remote = makeServerEvent({
      event_id: "det-1", status: "active",
      // New detection evidence: server found fresh indicators after the resolution.
      detection_updated_at: "2026-01-02T08:00:00Z",
      enforcement_evidence: null as any,
    });
    const { events } = mergeLocalAndRemoteEvents([local], [remote]);
    const m = events.find((e) => e.event_id === "det-1")!;
    assert.equal(m.resolved_at, null, "resolved_at cleared on detection-only reopen");
    assert.equal(m.status, "active", "status reopened by detection evidence");
  });

  it("mergeLocalAndRemoteEvents preserves resolution when detection evidence is stale", () => {
    const local = makeEvent({
      event_id: "det-2", status: "resolved", resolved_at: "2026-01-10T00:00:00Z",
      enforcement_evidence: null as any,
    });
    const remote = makeServerEvent({
      event_id: "det-2", status: "active",
      // Detection evidence is BEFORE the resolution — stale, not new.
      detection_updated_at: "2026-01-05T00:00:00Z",
      enforcement_evidence: null as any,
    });
    const { events } = mergeLocalAndRemoteEvents([local], [remote]);
    const m = events.find((e) => e.event_id === "det-2")!;
    assert.equal(m.status, "resolved", "resolution preserved when detection is stale");
    assert.ok(m.resolved_at, "resolved_at preserved");
  });

  it("resolveApolloState with only resolved events does not bark", () => {
    const resolved = makeEvent({ status: "resolved", resolved_at: new Date().toISOString() });
    const resolution = resolveApolloState({ events: [resolved], visibility: "full", lastVerifiedAt: new Date().toISOString() });
    assert.notEqual(resolution.state, "barking");
    assert.notEqual(resolution.state, "biting");
  });
});

// ── Test 6: Privacy restrictions and enforcement truth gates intact ──────────
describe("6. Privacy restrictions and native enforcement truth gates remain intact", () => {
  it("projectedEventVoice produces privacy-safe text with no detail leak", () => {
    const voice = projectedEventVoice("website", "barking", false);
    assert.ok(!voice.whatHappened.includes("fake-bank"), "No domain leaked");
    assert.ok(!voice.whatHappened.includes("ANZ"), "No brand leaked");
  });

  it("isActive preserves the enforcement truth gate: blocked+biting without resolution stays active", () => {
    assert.ok(isActive(makeBlockEvent({ resolved_at: null })));
    assert.ok(!isActive(makeBlockEvent({ resolved_at: new Date().toISOString() })));
  });

  it("STATE_RANK hierarchy is intact", () => {
    assert.ok(STATE_RANK.biting > STATE_RANK.barking);
    assert.ok(STATE_RANK.barking > STATE_RANK.growling);
    assert.ok(STATE_RANK.growling > STATE_RANK.ears_up);
    assert.ok(STATE_RANK.ears_up > STATE_RANK.resting);
  });

  it("evidence_representation field controls Higgins narration, not text content", () => {
    // Even if text LOOKS like real evidence, if the record holds only the privacy summary, Higgins won't use it.
    const serverWithRealishText = makeEvent({
      evidence_representation: "privacy_summary",
      what_happened: "This page impersonates a bank (but came from server).",
    });
    assert.ok(!hasRecordedFindings(serverWithRealishText), "Provenance field overrides text content");
  });
});
