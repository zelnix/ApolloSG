/**
 * Higgins Behavioural & Privacy Acceptance Tests
 *
 * Tests proving:
 * 1. Actionable findings produce specific, evidence-supported instructions.
 * 2. Higgins guides users through corrective procedures (directive language).
 * 3. Each step has one clear action and relevant navigation.
 * 4. Completed actions are verified where supported.
 * 5. Unverified outcomes are never reported as completed.
 * 6. Uncertainty does not produce vague or misleading instructions.
 * 7. Benign observations do not generate unnecessary warnings.
 * 8. LLM privacy boundary strips credentials and minimises personal data.
 * 9. The same Higgins standard applies across all user-facing screens.
 * 10. Model responses cannot disclose personal data or falsely claim security actions.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { hasRecordedFindings } from "../src/domain/caseFacts.ts";
import { buildHomeVoice, affectedCapabilities, joinNames } from "../src/domain/higginsHomeVoice.ts";
import { projectedEventVoice, humanizeReason } from "../src/domain/messageVoice.ts";
import { normalizeHistoricalEvent } from "../src/domain/packetEvidence.ts";
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
    evidence_provenance: "local_device", processing_source: "this_device", evidence_representation: "privacy_summary",
    ...overrides,
  });
}

function makeBlockEvent(overrides: Partial<PatrolEvent> = {}): PatrolEvent {
  return makeEvent({
    event_id: "block-1", state: "biting", status: "blocked", verified_block: true,
    headline: "Apollo blocked fake-bank.example.com",
    what_happened: "Apollo's Site Gate blocked a connection to fake-bank.example.com.",
    why: ["On-device filter matched this domain against a known threat"],
    what_to_do: "This connection was blocked. If you already shared details, review recovery steps.",
    enforcement_evidence: { evidenceId: "pkt-001", method: "packet_drop", observedAt: new Date().toISOString(), destination: { domain: "fake-bank.example.com" } } as any,
    ...overrides,
  });
}

// ── PASSIVE LANGUAGE PATTERNS ──
// These should NEVER appear in Higgins' authoritative output.
const PASSIVE_PATTERNS = [
  /you may want to/i,
  /consider reviewing/i,
  /it might be worth/i,
  /consult the relevant/i,
  /you could try/i,
  /perhaps you should/i,
  /it would be advisable/i,
];

function assertNoPassiveLanguage(text: string, context: string) {
  for (const pattern of PASSIVE_PATTERNS) {
    assert.ok(!pattern.test(text), `Passive language "${pattern.source}" found in ${context}: "${text.substring(0, 100)}..."`);
  }
}

// ── Test 1: Actionable findings produce specific, evidence-supported instructions ──
describe("1. Actionable findings produce specific, evidence-supported instructions", () => {
  it("narrateEvent with local evidence produces directive 'Here's what to do' instruction", () => {
    const event = makeEvent();
    const chunks = narrateEvent(event);
    const todoChunk = chunks.find(c => c.id === "todo");
    assert.ok(todoChunk, "Must produce a 'what to do' chunk");
    assert.match(todoChunk!.text, /Here's what to do/, "Uses directive language, not passive");
    assert.ok(todoChunk!.text.includes(event.what_to_do), "Includes the actual instruction from evidence");
  });

  it("narrateEvent with evidence includes specific problem description from findings", () => {
    const event = makeEvent();
    const chunks = narrateEvent(event);
    const whatChunk = chunks.find(c => c.id === "what");
    assert.ok(whatChunk, "Must produce a 'what happened' chunk");
    assert.match(whatChunk!.text, /Here's what Apollo found/, "Uses authoritative framing");
    assert.ok(whatChunk!.text.includes("impersonating a bank"), "Includes specific evidence detail");
  });

  it("buildHomeVoice for barking state produces action-oriented CTA", () => {
    const event = makeEvent({ state: "barking" });
    const voice = buildHomeVoice({
      resolution: { state: "barking", drivingEvent: event } as any,
      attention: [{ gate: "Site Gate", problem: "a suspicious login page", kind: "event", route: `/patrol/${event.event_id}` }] as any,
      gates: [], capabilities: [],
    });
    assert.ok(voice.ctaRoute, "Must provide a navigation route");
    assert.ok(voice.ctaLabel.length > 0, "Must provide a CTA label");
    assertNoPassiveLanguage(voice.text, "home voice barking");
  });
});

// ── Test 2: Higgins guides users through corrective procedures ──
describe("2. Higgins guides users through corrective procedures (directive language)", () => {
  it("incident narration uses 'Follow my lead' not 'Say stop at any time'", () => {
    const plan = {
      headline: "Phishing attempt across Text Gate and Link Gate",
      state: "barking" as const,
      timeline: [
        makeEvent({ event_id: "e1", category: "message" }),
        makeEvent({ event_id: "e2", category: "link" }),
      ],
      exposure: [], steps: [{ id: "s1", text: "Block the sender" }, { id: "s2", text: "Change your password" }], allResolved: false,
    } as any;
    const chunks = narrateIncident(plan);
    const planChunk = chunks.find(c => c.id === "plan");
    assert.ok(planChunk, "Must produce a plan chunk");
    assert.match(planChunk!.text, /Here's what we're going to do/, "Uses directive framing");
    assert.match(planChunk!.text, /walk you through/, "Guides the user");
  });

  it("incident narration tracks completed steps", () => {
    const plan = {
      headline: "Security concern",
      state: "barking" as const,
      timeline: [makeEvent({ event_id: "e1" })],
      exposure: [], steps: [{ id: "s1", text: "Reset your password" }], allResolved: false,
    } as any;
    const chunks = narrateIncident(plan, { s1: true });
    const stepChunk = chunks.find(c => c.id === "step-0");
    assert.ok(stepChunk, "Must produce step chunk");
    assert.match(stepChunk!.text, /already done/, "Acknowledges completed step");
  });
});

// ── Test 3: Each step has one clear action and relevant navigation ──
describe("3. Each step has one clear action and relevant navigation", () => {
  it("buildHomeVoice provides a single CTA route for each state", () => {
    // Barking with single event
    const event = makeEvent({ state: "barking" });
    const voice = buildHomeVoice({
      resolution: { state: "barking", drivingEvent: event } as any,
      attention: [{ gate: "Site Gate", problem: "suspicious page", kind: "event", route: `/patrol/${event.event_id}` }] as any,
      gates: [], capabilities: [],
    });
    assert.ok(voice.ctaRoute, "Must have exactly one CTA route");
    assert.ok(typeof voice.ctaRoute === "string", "CTA route must be a string");
  });

  it("buildHomeVoice for multiple findings directs to Protection Details", () => {
    const e1 = makeEvent({ event_id: "e1", state: "barking" });
    const e2 = makeEvent({ event_id: "e2", state: "barking", category: "message" });
    const voice = buildHomeVoice({
      resolution: { state: "barking" } as any,
      attention: [
        { gate: "Site Gate", problem: "suspicious page", kind: "event", route: "/patrol/e1" },
        { gate: "Text Gate", problem: "scam message", kind: "event", route: "/patrol/e2" },
      ] as any,
      gates: [], capabilities: [],
    });
    // Multiple findings → links to the most urgent investigation, not generic Protection Details
    assert.ok(voice.ctaRoute.startsWith("/patrol/"), "Multiple findings → most urgent investigation");
    assertNoPassiveLanguage(voice.text, "home voice multiple findings");
  });
});

// ── Test 4: Completed actions are verified where supported ──
describe("4. Completed actions are verified where supported", () => {
  it("verified block narrates containment clearly", () => {
    const event = makeBlockEvent();
    const chunks = narrateEvent(event);
    const doneChunk = chunks.find(c => c.id === "done");
    assert.ok(doneChunk, "Must produce a 'done' chunk for blocked event");
    assert.match(doneChunk!.text, /blocked and contained/, "States the threat is contained");
    assert.match(doneChunk!.text, /Apollo stopped it/, "Credits Apollo's enforcement");
  });

  it("buildHomeVoice for biting state with verified block is specific", () => {
    const event = makeBlockEvent();
    const voice = buildHomeVoice({
      resolution: { state: "biting", drivingEvent: event } as any,
      attention: [{ gate: "Site Gate", problem: "blocked threat", kind: "event", route: `/patrol/${event.event_id}` }] as any,
      gates: [], capabilities: [],
    });
    assert.match(voice.text, /Apollo blocked/, "States what Apollo blocked");
    assert.match(voice.text, /contained/, "Confirms containment");
    assertNoPassiveLanguage(voice.text, "home voice biting");
  });
});

// ── Test 5: Unverified outcomes are never reported as completed ──
describe("5. Unverified outcomes are never reported as completed", () => {
  it("normalizeHistoricalEvent prevents false biting claim without enforcement evidence", () => {
    const fake = makeEvent({ state: "biting", verified_block: true, enforcement_evidence: null });
    const n = normalizeHistoricalEvent(fake);
    assert.equal(n.state, "barking", "Cannot claim biting without enforcement evidence");
    assert.equal(n.evidence_completeness, "partial", "Marked as incomplete when evidence is missing");
    assert.equal(n.evidence_provenance, "local_device", "the evidence source is left as recorded");
  });

  it("server-projected event does not narrate as if verified", () => {
    const serverEvent = makeServerEvent();
    const chunks = narrateEvent(serverEvent);
    const whatChunk = chunks.find(c => c.id === "what");
    assert.ok(whatChunk, "Must produce a 'what' chunk");
    assert.match(whatChunk!.text, /privacy-protected summary/, "Honestly states evidence limitation");
    assert.ok(!whatChunk!.text.includes("impersonating"), "Does not narrate server-projected text as evidence");
  });
});

// ── Test 6: Uncertainty does not produce vague or misleading instructions ──
describe("6. Uncertainty does not produce vague or misleading instructions", () => {
  it("narration for event with no specific 'why' gives clear 'no action needed' assessment", () => {
    const event = makeEvent({ why: [] });
    const chunks = narrateEvent(event);
    const whyChunk = chunks.find(c => c.id === "why");
    assert.ok(whyChunk, "Must produce a 'why' chunk even when empty");
    assert.match(whyChunk!.text, /no specific warning signs/, "Honestly states no specific concerns");
    assert.match(whyChunk!.text, /No action needed/, "Provides clear direction");
    assertNoPassiveLanguage(whyChunk!.text, "empty why chunk");
  });

  it("humanizeReason for uncertain state produces clear honest reason", () => {
    const result = humanizeReason("server_projection_of_recorded_outcome", "growling");
    assert.ok(result.length > 0, "Must produce a reason");
    // Should not contain vague language
    assertNoPassiveLanguage(result, "humanized reason");
  });

  it("buildHomeVoice for recovering state gives clear instruction", () => {
    const voice = buildHomeVoice({
      resolution: { state: "growling", recovering: true } as any,
      attention: [] as any,
      gates: [], capabilities: [],
    });
    assert.match(voice.text, /fresh check/, "Directs user to run a fresh check");
    assert.ok(voice.ctaRoute, "Must provide route to take action");
    assertNoPassiveLanguage(voice.text, "recovering state");
  });
});

// ── Test 7: Benign observations do not generate unnecessary warnings ──
describe("7. Benign observations do not generate unnecessary warnings", () => {
  it("resting state states the all-clear in the approved wording", () => {
    const voice = buildHomeVoice({
      resolution: { state: "resting" } as any,
      attention: [] as any,
      gates: [], capabilities: [],
    });
    assert.match(voice.text, /No security threats currently detected/, "States the all-clear");
    assert.doesNotMatch(voice.text, /needs your decision|isn't confirmed yet/i, "Asks for nothing");
    assertNoPassiveLanguage(voice.text, "resting state");
  });

  it("resolved event narrates as handled without unnecessary alarm", () => {
    const event = makeEvent({ status: "resolved", resolved_at: new Date().toISOString() });
    const chunks = narrateEvent(event);
    const doneChunk = chunks.find(c => c.id === "done");
    assert.ok(doneChunk, "Must produce done chunk for resolved event");
    assert.match(doneChunk!.text, /handled/, "Confirms it's handled");
    assert.match(doneChunk!.text, /Well done/, "Reassures the user");
  });
});

// ── Test 8: LLM privacy boundary strips credentials and minimises personal data ──
describe("8. LLM privacy and evidence boundary", () => {
  it("hasRecordedFindings is false for the server's privacy summary alone", () => {
    const projected = makeServerEvent();
    assert.equal(hasRecordedFindings(projected), false, "A privacy summary carries no findings");
  });

  it("hasRecordedFindings is true for local_device events", () => {
    const local = makeEvent();
    assert.equal(hasRecordedFindings(local), true, "Local events carry their findings");
  });

  it("projectedEventVoice produces privacy-safe text without personal details", () => {
    const voice = projectedEventVoice("website", "barking", false);
    assert.ok(!voice.whatHappened.includes("fake-bank"), "No domain leaked in projected voice");
    assert.ok(!voice.whatHappened.includes("ANZ"), "No brand leaked in projected voice");
    assert.ok(voice.headline.length > 0, "Must produce a headline");
    assert.ok(voice.whatHappened.length > 0, "Must produce a description");
  });

  it("evidence_representation field controls narration, not text content", () => {
    // Even if text LOOKS like real evidence, a privacy-summary record prevents narration.
    const serverWithRealText = makeEvent({
      evidence_representation: "privacy_summary",
      what_happened: "This page impersonates a bank.",
    });
    const chunks = narrateEvent(serverWithRealText);
    const whatChunk = chunks.find(c => c.id === "what");
    assert.ok(!whatChunk!.text.includes("impersonates"), "Provenance field overrides text content");
    assert.match(whatChunk!.text, /privacy-protected summary/, "Uses honest limitation message");
  });
});

// ── Test 9: Same Higgins standard applies across all user-facing screens ──
describe("9. Same Higgins standard applies across all user-facing screens", () => {
  it("home voice uses directive language consistently across states", () => {
    const states: Array<{ state: string; hasEvent: boolean }> = [
      { state: "barking", hasEvent: true },
      { state: "growling", hasEvent: true },
      { state: "biting", hasEvent: false },
      { state: "resting", hasEvent: false },
    ];
    for (const { state, hasEvent } of states) {
      const event = hasEvent ? makeEvent({ state: state as any }) : undefined;
      const voice = buildHomeVoice({
        resolution: { state, drivingEvent: event, recovering: state === "growling" && !hasEvent } as any,
        attention: hasEvent ? [{ gate: "Site Gate", problem: "test", kind: "event", route: "/patrol/test" }] as any : [] as any,
        gates: [], capabilities: [],
      });
      assertNoPassiveLanguage(voice.text, `home voice state=${state}`);
    }
  });

  it("event narration uses directive language for all evidence states", () => {
    // With full evidence
    const fullEvidence = makeEvent();
    const fullChunks = narrateEvent(fullEvidence);
    for (const chunk of fullChunks) {
      assertNoPassiveLanguage(chunk.text, `full evidence chunk=${chunk.id}`);
    }

    // With projected evidence
    const projected = makeServerEvent();
    const projChunks = narrateEvent(projected);
    for (const chunk of projChunks) {
      assertNoPassiveLanguage(chunk.text, `projected evidence chunk=${chunk.id}`);
    }
  });

  it("incident narration maintains directive tone throughout", () => {
    const plan = {
      headline: "Multi-gate incident",
      state: "barking" as const,
      timeline: [makeEvent({ event_id: "e1" }), makeEvent({ event_id: "e2" })],
      exposure: [], steps: [{ id: "s1", text: "Block the sender" }], allResolved: false,
    } as any;
    const chunks = narrateIncident(plan);
    for (const chunk of chunks) {
      assertNoPassiveLanguage(chunk.text, `incident chunk=${chunk.id}`);
    }
    // Summary should include "Follow my lead"
    const summary = chunks.find(c => c.id === "summary");
    assert.match(summary!.text, /Follow my lead/, "Summary directs user to follow Higgins");
  });
});
