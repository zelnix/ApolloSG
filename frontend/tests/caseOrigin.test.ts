// Threat Case origin rule — regression tests. Every Threat Case begins on the device that detected it; server
// processing, Magnum DI, syncing, privacy projection and missing evidence never move a case's origin or change where
// its evidence came from (server processing is never an evidence source); checks that didn't finish show what was
// checked → what happened → why it failed → what couldn't be verified. Run: cd /app/frontend && node --test tests/caseOrigin.test.ts
import assert from "node:assert/strict";
import test from "node:test";

import {
  ORIGIN_LABEL, caseOrigin, caseShortfalls, completenessLabel, evidenceSourceLabel, hasRecordedFindings, privacyNote, processingLabels,
  shortfallLine, triageShortfalls,
} from "../src/domain/caseFacts.ts";
import { buildCaseSources, sourceHeading } from "../src/domain/caseSources.ts";
import { deviceCheckEvent } from "../src/domain/deviceCheckCase.ts";
import { mergeLocalAndRemoteEvents } from "../src/domain/eventMerge.ts";
import { EVIDENCE_SOURCES, evidenceModel } from "../src/domain/evidenceModel.ts";
import { buildEvidencePack } from "../src/domain/evidencePack.ts";
import { projectedEventVoice } from "../src/domain/messageVoice.ts";
import { normalizeHistoricalEvent } from "../src/domain/packetEvidence.ts";
import { patrolPayload } from "../src/domain/patrolPayload.ts";
import { enforceEgress } from "../src/domain/privacy.ts";
import { caseGroupKey } from "../src/domain/threatCase.ts";
import { gapPlainEnglish, type TriageInvestigationRecord } from "../src/domain/triage/contract.ts";
import type { ApolloState, PatrolEvent } from "../src/domain/types.ts";

/** Wording that would place a case, or its evidence, on some other device. */
const PROHIBITED = /another device|other device|device where it happened|originating device|not available on this device|not stored on this device|recorded on another device|browser session/i;

/** Every evidence model a case can have — plus the two values records stored before the separated model carried. */
const MODELS: Partial<PatrolEvent>[] = [
  { evidence_provenance: "local_device" },
  { evidence_provenance: "dns_observation" },
  { evidence_provenance: "native_protection", source_metadata: { type: "link", provider: "Samsung Message Guard" } },
  { evidence_provenance: "device_submission", processing_source: "apollosg_servers", evidence_representation: "privacy_protected_copy" },
  { evidence_provenance: "connected_mailbox", processing_source: "apollosg_servers", evidence_representation: "privacy_protected_copy", source_metadata: { type: "email", provider: "Gmail" } },
  { evidence_provenance: "local_device", processing_source: "this_device", evidence_representation: "privacy_summary" },
  { evidence_completeness: "partial" },
  {},
  { evidence_provenance: "server_projected" } as never,
  { evidence_provenance: "incomplete" } as never,
];
const label = (m: Partial<PatrolEvent>) => JSON.stringify(m);

function ev(partial: Partial<PatrolEvent> = {}): PatrolEvent {
  return {
    event_id: "e1", device_id: "phone-a", category: "message", state: "growling", status: "active",
    headline: "Message: parcel redelivery text", what_happened: "A text asked for a redelivery fee through a link.",
    why: ["The link isn't on the courier's own website."], what_to_do: "Don't tap the link.",
    indicator_host: "parcel-fee.top", indicator_digest: null, verified_block: false, adapter_label: "test",
    occurred_at: "2026-10-26T14:10:00.000Z", resolved_at: null, ...partial,
  } as PatrolEvent;
}

const rule = (ruleId: string, code: string, reason: string) => ({
  ruleId, title: ruleId, category: "link", applicable: true, checked: false, result: "coverage_gap" as const,
  evidence: reason ? [reason] : [], coverageGap: code, detail: "",
});

function triage(over: Partial<TriageInvestigationRecord> = {}): TriageInvestigationRecord {
  return {
    investigationId: "tri-1", catalogueVersion: 3, sourceType: "message", outcome: "NO_THREAT_IDENTIFIED", reason: "x",
    rulesApplicable: ["LINK-01", "LINK-10", "PWA-01"], rulesChecked: [], rulesMet: [], rules: [], coverageGaps: [],
    incompleteChecks: [], retries: [], correlation: {}, recheckUseful: false, geminiCalls: 0, evaluatedAt: "2026-10-26T14:10:05.000Z",
    ...over,
  };
}

/** Every person-facing string a Threat Case produces from one event. */
function caseText(event: PatrolEvent): string[] {
  const sources = buildCaseSources({ event, investigation: null });
  const facts = [event.headline, ...event.why];
  return [
    caseOrigin(event).label, evidenceSourceLabel(event), ...processingLabels(event), completenessLabel(event), privacyNote(event) ?? "",
    ...sources.flatMap((s) => [sourceHeading(s), s.returned]),
    ...narrateEvent(event).map((c) => c.text),
    buildEvidencePack({ event, facts, sources }),
  ];
}

const variants = (): PatrolEvent[] => MODELS.flatMap((model) => [
  ev(model),
  ev({ ...model, triage_investigation: triage() }),
  ev({ ...model, investigation_case_id: "case-1" }),
  ev({ ...model, investigation_case_id: "case-1", investigation_completed_at: "2026-10-26T14:12:00.000Z", investigation_answered_by: "tc_flyby_kb" }),
]);

test("every Threat Case's origin is the device that detected it", () => {
  for (const event of variants()) {
    assert.deepEqual(caseOrigin(event), { deviceId: "phone-a", label: ORIGIN_LABEL }, `origin for ${label(event)}`);
    for (const text of caseText(event)) assert.doesNotMatch(text, PROHIBITED, `${event.evidence_provenance}: ${text}`);
  }
});

test("server processing never changes the case's origin or its evidence source, and stays attached to the same case", () => {
  const local = ev({ evidence_provenance: "dns_observation", what_happened: "Apollo's DNS filter matched parcel-fee.top." });
  // What the server now holds for this case after TC Hawkeye / Magnum DI worked from a privacy-protected copy.
  const remote = ev({ ...projectedEventVoice("message", "growling", false), evidence_provenance: "device_submission", processing_source: "apollosg_servers",
    evidence_representation: "privacy_protected_copy", device_id: "phone-a", adapter_label: "Magnum DI investigation",
    what_happened: projectedEventVoice("message", "growling", false).whatHappened, investigation_case_id: "case-1" });
  const { events } = mergeLocalAndRemoteEvents([local], [remote]);
  assert.equal(events.length, 1, "one case");
  assert.equal(events[0].device_id, "phone-a");
  assert.equal(events[0].evidence_provenance, "dns_observation", "syncing never changes where the evidence came from");
  assert.equal(evidenceModel(events[0]).processing, "this_device", "nor where this device's check ran");
  assert.equal(events[0].evidence_representation, "full_record", "this device's own record is kept in full");
  assert.equal(events[0].what_happened, local.what_happened);
  assert.equal(events[0].investigation_case_id, "case-1", "the server's analysis is attached to this case");
  assert.deepEqual(processingLabels(events[0]), ["Apollo's DNS filter on this device", "ApolloSG's investigators"]);
  assert.equal(caseOrigin(events[0]).label, ORIGIN_LABEL);
  // A server record with no local copy (e.g. after a reinstall) is still this device's own case.
  const onlyServer = ev({ evidence_provenance: "local_device", processing_source: "this_device", evidence_representation: "privacy_summary" });
  assert.equal(caseOrigin(onlyServer).deviceId, onlyServer.device_id);
  assert.equal(evidenceSourceLabel(onlyServer), "Apollo's check on this device", "the summary keeps the device's own source");
  assert.match(privacyNote(onlyServer)!, /privacy-protected summary/);
  const analysed = ev({ evidence_provenance: "device_submission", processing_source: "apollosg_servers", evidence_representation: "privacy_protected_copy", triage_investigation: triage() });
  assert.doesNotMatch(privacyNote(analysed)!, PROHIBITED);
  assert.equal(evidenceSourceLabel(analysed), "Sent from this device for checking");
  assert.deepEqual(processingLabels(analysed), ["Higgins Triage on ApolloSG's servers"]);
});

test("no ApolloSG record answers \"Where did this evidence come from?\" with the server", () => {
  const SERVER = /server|server_projected|ApolloSG's servers/i;
  for (const event of variants()) {
    const read = normalizeHistoricalEvent(event);
    const merged = [
      ...mergeLocalAndRemoteEvents([read], []).events, ...mergeLocalAndRemoteEvents([], [read]).events,
      ...mergeLocalAndRemoteEvents([read], [read]).events,
    ];
    for (const e of [read, ...merged]) {
      const source = e.evidence_provenance as string | undefined;
      assert.ok(source === undefined || EVIDENCE_SOURCES.has(source), `${label(event)} → ${source}`);
      assert.doesNotMatch(evidenceSourceLabel(e), SERVER, `evidence label for ${label(event)}`);
      for (const s of buildCaseSources({ event: e, investigation: null })) assert.doesNotMatch(s.name, /ApolloSG's servers/, `source row for ${label(event)}`);
    }
    // What this device syncs names only its own evidence source, never a server.
    const out = enforceEgress("patrol_sync", patrolPayload({ ...read, state: "growling", verified_block: false }, "phone-a")) as Record<string, unknown>;
    assert.ok(out.evidence_provenance === null || ["local_device", "dns_observation", "native_protection"].includes(String(out.evidence_provenance)), `${label(event)} synced ${out.evidence_provenance}`);
  }
  assert.throws(() => enforceEgress("patrol_sync", { ...patrolPayload(ev({}), "phone-a"), evidence_provenance: "server_projected" }));
});

test("records stored before the separated model are read into it, and keep their origin", () => {
  const legacy = (over: Record<string, unknown>) => normalizeHistoricalEvent(ev({ evidence_provenance: "server_projected", ...over } as never));
  const mailboxTriage = legacy({ category: "email", adapter_label: "Higgins Triage (deterministic)", triage_investigation: triage() });
  assert.deepEqual([mailboxTriage.evidence_provenance, mailboxTriage.processing_source, mailboxTriage.evidence_representation],
    ["connected_mailbox", "apollosg_servers", "privacy_protected_copy"]);
  assert.equal(evidenceSourceLabel(mailboxTriage), "Your connected mailbox");
  const textTriage = legacy({ adapter_label: "Higgins Triage (deterministic)", triage_investigation: triage() });
  assert.equal(textTriage.evidence_provenance, "device_submission");
  const gmailCase = legacy({ adapter_label: "Magnum DI investigation", investigation_case_id: "case-1", source_metadata: { type: "email", provider: "Gmail" } });
  assert.equal(evidenceSourceLabel(gmailCase), "Gmail mailbox");
  const summary = legacy({ adapter_label: "ApolloSG on-device assessment" });
  assert.deepEqual([summary.evidence_provenance, summary.processing_source, summary.evidence_representation], [undefined, "this_device", "privacy_summary"]);
  assert.equal(evidenceSourceLabel(summary), "Not recorded", "a source that was never recorded is never filled in with the server");
  assert.ok(!hasRecordedFindings(summary));
  const downgraded = normalizeHistoricalEvent(ev({ evidence_provenance: "incomplete", what_happened: "This record does not establish an observed packet drop." } as never));
  assert.equal(downgraded.evidence_provenance, undefined);
  assert.equal(downgraded.evidence_completeness, "partial");
  assert.deepEqual(downgraded.evidence_gaps?.map((g) => g.check), ["block_proof"]);
  for (const e of [mailboxTriage, textTriage, gmailCase, summary, downgraded]) {
    assert.equal(caseOrigin(e).label, ORIGIN_LABEL);
    assert.ok(!["server_projected", "incomplete"].includes(String(e.evidence_provenance)));
  }
});

test("the generic incomplete-evidence row never stands in for a recorded reason", () => {
  const GENERIC = /Original evidence/;
  const rowsOf = (e: PatrolEvent) => buildCaseSources({ event: e, investigation: null }).filter((s) => !s.answered);
  const final = { check: "final_destination", status: "unresolved" as const, failure: "nonexistent_domain", detail: "", source: null, at: null };
  // Incomplete checks, a coverage gap, or the truth gate's recorded failure: each names exactly what is missing and why.
  const specific = [
    ev({ evidence_provenance: "incomplete", triage_investigation: triage({ incompleteChecks: [final] }) } as never),
    ev({ evidence_completeness: "partial", triage_investigation: triage({ rules: [rule("LINK-10", "INTELLIGENCE_PROVIDER_UNAVAILABLE", "domain registration age unavailable")],
      coverageGaps: [{ code: "INTELLIGENCE_PROVIDER_UNAVAILABLE", detail: "", recoverable: true, ruleIds: ["LINK-10"] }] }) }),
    normalizeHistoricalEvent(ev({ state: "biting", verified_block: true, enforcement_evidence: null })),
  ];
  for (const raw of specific) {
    const e = normalizeHistoricalEvent(raw);
    const rows = rowsOf(e);
    assert.ok(rows.length >= 1, "the specific reason is shown");
    assert.ok(rows.every((s) => !GENERIC.test(s.name)), `generic row shown beside a recorded reason: ${rows.map((s) => s.name)}`);
    assert.ok(rows.every((s) => !!s.unverified), "each row says what couldn't be verified");
    const pack = buildEvidencePack({ event: e, facts: [], sources: buildCaseSources({ event: e }) });
    assert.doesNotMatch(pack, /Not part of this case's record/);
  }
  const blocked = normalizeHistoricalEvent(ev({ state: "biting", verified_block: true, enforcement_evidence: null }));
  assert.deepEqual(caseShortfalls(blocked).map(shortfallLine), [
    "Proof of the block — couldn't be verified: The record doesn't contain a packet drop Apollo observed and matched to this event. Couldn't verify that the connection was actually blocked.",
  ]);
  // Only when nothing records why does the fixed row show — and it says no reason was recorded, never "unavailable".
  const unexplained = normalizeHistoricalEvent(ev({ evidence_provenance: "incomplete" } as never));
  const rows = rowsOf(unexplained);
  assert.deepEqual(rows.map((s) => [sourceHeading(s), s.returned]), [["Original evidence — not recorded with this case", "No reason was recorded."]]);
  assert.equal(completenessLabel(unexplained), "Part of this case's evidence wasn't recorded, and no reason was recorded for it");
});

test("incomplete checks show the actual check and their exact recorded failure", () => {
  const record = triage({
    incompleteChecks: [
      { check: "final_destination", status: "unresolved", failure: "nonexistent_domain", detail: "", source: "redirect", at: null },
      { check: "reputation", status: "unavailable", failure: "timeout", detail: "", source: "google_safe_browsing", at: null },
      { check: "sender_authentication", status: "unavailable", failure: "original_not_provided", detail: "", source: null, at: null },
      { check: "number_reputation", status: "unavailable", failure: null, detail: "carrier lookup returned 503", source: null, at: null },
    ],
    rules: [
      rule("LINK-01", "INTELLIGENCE_PROVIDER_UNAVAILABLE", "reputation lookup did not complete (timeout)"),
      rule("LINK-10", "INTELLIGENCE_PROVIDER_UNAVAILABLE", "domain registration age unavailable"),
      rule("PWA-01", "BROWSER_VISIBILITY_UNAVAILABLE", "PWA origin is not observable on this platform"),
    ],
    coverageGaps: [
      { code: "INTELLIGENCE_PROVIDER_UNAVAILABLE", detail: "reputation lookup did not complete (timeout)", recoverable: true, ruleIds: ["LINK-01", "LINK-10"] },
      { code: "BROWSER_VISIBILITY_UNAVAILABLE", detail: "PWA origin is not observable on this platform", recoverable: false, ruleIds: ["PWA-01"] },
    ],
  });
  const rows = triageShortfalls(record).map((r) => `${r.name} — ${r.status}: ${r.reason}`);
  assert.deepEqual(rows, [
    "Final destination — couldn't be verified: The website's address doesn't exist.",
    "Reputation check — didn't answer: The service timed out.",
    "Sender authentication — didn't answer: ApolloSG didn't receive the full email headers.",
    "Phone number reputation — didn't answer: Carrier lookup returned 503.",
    "Domain registration age — couldn't be checked: Domain registration age unavailable.",
    "Website the installed web app came from — couldn't be checked: PWA origin is not observable on this platform.",
  ]);
  const generic = new Set(["INTELLIGENCE_PROVIDER_UNAVAILABLE", "BROWSER_VISIBILITY_UNAVAILABLE"].map(gapPlainEnglish));
  const sources = buildCaseSources({ event: ev({ evidence_provenance: "local_device", triage_investigation: record }) });
  for (const s of sources) {
    assert.ok(!generic.has(s.returned), `generic gap wording replaced a recorded reason: ${s.returned}`);
    assert.doesNotMatch(s.name, /browser session/i);
  }
  assert.ok(sources.some((s) => s.name === "Final destination" && s.returned === "The website's address doesn't exist." && !s.answered
    && s.unverified === "where the link finally leads"));
  // Each row reads: what was checked → what happened → why it failed → what couldn't be verified.
  assert.deepEqual(triageShortfalls(record).map((r) => r.unverified), [
    "where the link finally leads", "whether it's listed as a known threat", "whether the email really came from the sender it shows",
    "whether the number has been reported for scams", "how long the website's address has existed", "which website the installed web app came from",
  ]);
  // A missing check narrows what was verified; it never becomes a concern.
  assert.equal(completenessLabel(ev({ triage_investigation: record })), "6 checks couldn't be completed — each is listed with its reason");
});

test("the Evidence Pack carries the five case facts and no device-location wording", () => {
  for (const event of variants()) {
    const pack = buildEvidencePack({ event, facts: [event.headline], sources: buildCaseSources({ event, investigation: null }) });
    assert.match(pack, /^Origin: Detected on this device$/m);
    assert.match(pack, /^Evidence: /m);
    assert.match(pack, /^Record: /m);
    assert.doesNotMatch(pack, PROHIBITED);
  }
  const withGaps = ev({ evidence_provenance: "local_device", triage_investigation: triage({
    incompleteChecks: [{ check: "final_destination", status: "unresolved", failure: "nonexistent_domain", detail: "", source: null, at: null }] }) });
  const pack = buildEvidencePack({ event: withGaps, facts: [], sources: buildCaseSources({ event: withGaps }) });
  assert.match(pack, /- Final destination — couldn't be verified: The website's address doesn't exist\. Couldn't verify where the link finally leads\./);
});

test("an independent detection on a second device is its own Threat Case, not a continuation of the first", () => {
  const first = ev({ event_id: "a-1", device_id: "phone-a", scent_id: "s-1", evidence_provenance: "local_device" });
  const second = ev({ event_id: "b-1", device_id: "phone-b", scent_id: "s-1", evidence_provenance: "local_device" });
  assert.notEqual(caseGroupKey(second), caseGroupKey(first));
  assert.equal(caseOrigin(second).deviceId, "phone-b");
  assert.equal(caseOrigin(first).deviceId, "phone-a");
  const checkA = deviceCheckEvent({ eventId: "c-a", deviceId: "phone-a", adapterLabel: "x", platformLabel: "android",
    briefing: { headline: "Looks good", findings: [], action: null, overall: "clear" } });
  const checkB = deviceCheckEvent({ eventId: "c-b", deviceId: "phone-b", adapterLabel: "x", platformLabel: "android",
    briefing: { headline: "Looks good", findings: [], action: null, overall: "clear" } });
  assert.notEqual(caseGroupKey(checkA), caseGroupKey(checkB));
  // Merging never folds one device's case into another's, and never rewrites a case's origin.
  const { events } = mergeLocalAndRemoteEvents([first], [{ ...first, device_id: "phone-b" }]);
  assert.equal(events[0].device_id, "phone-a");
});
