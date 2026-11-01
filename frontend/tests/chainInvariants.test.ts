// Chain invariants (Evidence Lock → Higgins Luddish → every screen), proved as tests — they never run in the app.
//   1. Higgins Luddish can't change locked evidence or findings: the lock is frozen and fingerprinted, explaining it
//      changes nothing in it or in the result it came from, and a lock that was tampered with is never reworded.
//   2. Presentation can't silently change the verdict, severity, confidence or status: Home, Threats, the Findings
//      Brief, Evidence, History and DI all say what the case result (caseBriefing.caseResult) says, for every outcome,
//      every attention level, with a briefing that passed its Fidelity Check, one that failed it, and none.
//   3. No screen works a verdict or severity out for itself.
// Run: cd /app/frontend && node --test tests/chainInvariants.test.ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { investigationVerdict, resultVerdict, riskPill } from "../src/domain/briefVerdict.ts";
import { caseFindings, caseResult, eventBriefing, threatResult } from "../src/domain/caseBriefing.ts";
import { caseEvidence } from "../src/domain/caseEvidence.ts";
import { caseAuditTrail } from "../src/domain/caseAuditTrail.ts";
import { buildDecisionTrace } from "../src/domain/diTrace.ts";
import { eventBrief } from "../src/domain/homeHeroBrief.ts";
import { investigationPatch } from "../src/domain/investigationCaseUpdate.ts";
import { compose, lockFromInvestigation } from "../src/domain/luddish/index.ts";
import { lockedTexts, lockIntact } from "../src/domain/luddish/lock.ts";
import { threatCaseStatus } from "../src/domain/threatCase.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

const OUTCOMES = ["confirmed_threat", "likely_scam", "concerning", "unable_to_determine", "no_scam_indicators"] as const;
const ATTENTION = ["urgent", "action_needed", "review", "none"] as const;
const LABEL: Record<string, string> = {
  confirmed_threat: "Confirmed scam or threat", likely_scam: "Likely scam", concerning: "Concerning",
  unable_to_determine: "Unable to determine", no_scam_indicators: "No scam indicators found",
};
/** What the Home hero says for each verdict (homeHeroBrief). */
const HERO: Record<string, string> = {
  confirmed_threat: "detected as a confirmed scam or threat", likely_scam: "detected as a likely scam", concerning: "detected as concerning",
  unable_to_determine: "not confirmed safe", no_scam_indicators: "no scam signs found",
};
const SEVERITY: Record<string, string> = { urgent: "barking", action_needed: "barking", review: "growling", none: "resting" };

const placeholder = {
  event_id: "ev1", device_id: "d1", category: "message", state: "sniffing", status: "active", origin: "user",
  headline: "Apollo is investigating this", what_happened: "Higgins has started an investigation.", why: [], what_to_do: "Nothing to do right now.",
  indicator_host: null, indicator_digest: null, verified_block: false, adapter_label: "test", occurred_at: "2026-10-28T01:00:00Z",
  resolved_at: null, investigation_case_id: "case-1", evidence_provenance: "device_submission", processing_source: "apollosg_servers",
  evidence_representation: "privacy_protected_copy",
} as unknown as PatrolEvent;

const FINDINGS = [
  { id: "f1", text: "commbank-cancel.co carries CommBank's name, but it isn't CommBank's domain.", basis: "observation", confidence: "high", evidenceIds: ["EV-1"], sourceIds: [] },
  { id: "f2", text: "The message asks for your NetBank password.", basis: "observation", confidence: "medium", evidenceIds: ["EV-1"], sourceIds: [] },
];

type BriefingKind = "pass" | "fail" | "none";
function response(outcome: string, attention: string, briefing: BriefingKind) {
  const action = { id: "a1", kind: "instruction", label: "Don't open the link", instruction: "Do not open commbank-cancel.co.", capabilityId: null,
    executionDescriptorId: null, requiresUserGesture: false, sourceIds: [], desiredField: null, desiredValue: null };
  const b = briefing === "none" ? null : {
    version: 1, subject: null, headline: "Message using CommBank's name checked", summary: FINDINGS[0].text,
    findings: FINDINGS.map((f) => ({ id: f.id, subject: null, subjectType: null, organisation: null, check: "", result: "", finding: f.text,
      evidenceIds: f.evidenceIds, sourceIds: [], materiality: "material", confidence: f.confidence, basis: f.basis, stance: "supporting" })),
    supporting: ["f1", "f2"], contrary: [], unresolved: [],
    // A briefing that failed its Fidelity Check says something else — it must never be what any screen shows.
    status: briefing === "pass" ? LABEL[outcome] : "Confirmed scam or threat", statusCode: briefing === "pass" ? outcome : "confirmed_threat",
    attention: briefing === "pass" ? attention : "urgent", statusReason: "", userActionRequired: briefing === "fail",
    actionReason: briefing === "fail" ? "Act now." : null, recommendedAction: { label: "Don't open the link", instruction: "Do not open commbank-cancel.co." },
    fidelity: { status: briefing === "pass" ? "PASS" : "FAIL", failures: [] },
  };
  return {
    revision: 1, overview: "This looks like a CommBank impersonation attempt. The link isn't CommBank's.", explanationMarkdown: "",
    assessment: outcome === "no_scam_indicators" ? "no_concern_found_within_scope" : outcome === "unable_to_determine" ? "uncertain" : "concern_found",
    outcome, attention, attentionReason: attention === "urgent" || attention === "action_needed" ? "The link isn't CommBank's domain." : null,
    findings: FINDINGS, uncertainties: ["Apollo can't confirm who actually sent this."], scope: "TC FlyBy checked the submitted message.",
    sourceIds: [], remainingEvidenceIds: [], actions: outcome === "no_scam_indicators" ? [] : [action],
    recommendedActionId: outcome === "no_scam_indicators" ? null : "a1", question: null, completion: "complete", briefing: b,
  };
}
const investigation = (resp: ReturnType<typeof response>) => ({
  caseId: "case-1", gates: ["text"], status: "complete", createdAt: "2026-10-28T01:00:00Z", completedAt: "2026-10-28T01:00:30Z",
  committedAt: "2026-10-28T01:00:31Z", question: "", sources: [], turns: [], patrolEventId: "ev1", answeredBy: "tc_flyby",
  evidenceItems: [{ id: "EV-1", caseId: "case-1", clientItemId: "c1", displayId: "EV-1", origin: "user_submission", kind: "text", parentId: null,
    availability: "available", mediaType: null, byteLength: null, integrityHash: null, provenance: null,
    coverage: { status: "examined", unit: "characters", total: 120, examined: 120, materialGap: false }, simulation: null, transformations: [],
    label: "Submitted message text", expiresAt: "2026-10-28T02:00:00Z" }],
  response: resp,
}) as never;

const matrix = OUTCOMES.flatMap((o) => ATTENTION.flatMap((a) => (["pass", "fail", "none"] as BriefingKind[]).map((b) => [o, a, b] as const)));

// ── 1. Higgins Luddish can't change locked evidence or findings ─────────────────────────────────────────────────────

test("the Evidence Lock is frozen: nothing in it can be changed, added or removed", () => {
  const lock = lockFromInvestigation(response("likely_scam", "action_needed", "pass") as never, "TC FlyBy");
  assert.ok(lockIntact(lock));
  assert.throws(() => { (lock as { state: string }).state = "resting"; }, TypeError);
  assert.throws(() => { (lock.findings[0] as { text: string }).text = "Nothing to worry about."; }, TypeError);
  assert.throws(() => { (lock.findings[0] as { confidence: string }).confidence = "low"; }, TypeError);
  assert.throws(() => { (lock.findings as unknown as unknown[]).push({ text: "A new finding." }); }, TypeError);
  assert.throws(() => { (lock.findings as unknown as unknown[]).pop(); }, TypeError);
  assert.throws(() => { (lock as { uncertainties: string[] }).uncertainties = []; }, TypeError);
  assert.ok(lockIntact(lock));
});

test("explaining a result changes nothing in the lock or in the result it was locked from", () => {
  for (const [o, a, b] of matrix) {
    const resp = response(o, a, b);
    const before = JSON.stringify(resp);
    const lock = lockFromInvestigation(resp as never, "TC FlyBy");
    const fingerprint = lock.fingerprint;
    const ex = compose(lock);
    assert.ok(lockIntact(lock), `${o}/${a}/${b}`);
    assert.equal(lock.fingerprint, fingerprint);
    assert.equal(JSON.stringify(resp), before, `the result was changed by Luddish (${o}/${a}/${b})`);
    // Same state, same findings, each finding's basis and confidence exactly as recorded.
    assert.equal(ex.state, lock.state);
    assert.equal(ex.findings.length, resp.findings.length);
    assert.deepEqual(lock.findings.map((f) => f.confidence), resp.findings.map((f) => f.confidence));
    assert.deepEqual(lock.findings.map((f) => f.text), resp.findings.map((f) => f.text));
    // The technical detail is the locked wording, word for word.
    for (const f of resp.findings) assert.ok(ex.technical.some((t) => t.text === f.text), `technical detail lost "${f.text}"`);
  }
});

test("a lock whose content no longer matches its fingerprint is never reworded — Apollo's words only", () => {
  const lock = lockFromInvestigation(response("likely_scam", "action_needed", "pass") as never, "TC FlyBy");
  const tampered = Object.freeze({ ...lock, findings: Object.freeze([Object.freeze({ ...lock.findings[0], text: "It isn't CommBank's domain, utilise caution." })]) });
  assert.equal(lockIntact(tampered), false);
  const ex = compose(tampered);
  assert.equal(ex.findings[0].text, "It isn't CommBank's domain, utilise caution.");
  assert.equal(ex.findings[0].note, null);
});

test("the lock keeps where a finding's extra confidence came from: case evidence, this device, previous reports", () => {
  const note = (kind: string, text: string, findingIds: string[]) => ({ kind, match: "website", text, source: "x", agrees: true, subject: null,
    eventId: null, at: null, outcome: null, findingIds });
  const resp = { ...response("likely_scam", "action_needed", "pass"), history: [
    note("related_case", "An earlier case on this device involved the same link, commbank-cancel.co.", ["f1"]),
    note("previously_encountered", "This link, commbank-cancel.co, has been previously reported as malicious — High confidence.", ["f1"]),
    note("previously_encountered", "This number has mixed previous reports.", []),
  ] };
  const lock = lockFromInvestigation(resp as never, "TC FlyBy");
  assert.ok(lockIntact(lock));
  assert.deepEqual(lock.findings.map((f) => [...f.raisedBy]), [["this_device", "previous_reports"], []]);
  // History never becomes a finding, and the case's own basis stays as recorded (never "seen directly" because of it).
  assert.deepEqual(lock.findings.map((f) => f.text), FINDINGS.map((f) => f.text));
  assert.deepEqual(lock.findings.map((f) => f.basis), ["observed", "observed"]);
  assert.ok(!lockedTexts(lock).some((t) => /previous|earlier case/.test(t)));
  const ex = compose(lock);
  const detail = ex.technical.find((t) => t.text === FINDINGS[0].text)?.detail ?? "";
  assert.match(detail, /Confidence raised by this device's earlier cases and ApolloSG's previous reports \(not evidence\)$/);
  assert.doesNotMatch(ex.technical.find((t) => t.text === FINDINGS[1].text)?.detail ?? "", /raised/);
  // A lock with the provenance stripped is a different lock: it can't silently lose where the weight came from.
  const stripped = Object.freeze({ ...lock, findings: Object.freeze(lock.findings.map((f) => Object.freeze({ ...f, raisedBy: Object.freeze([]) }))) });
  assert.equal(lockIntact(stripped as never), false);
});

// ── 2. Presentation can't silently change the verdict, severity, confidence or status ──────────────────────────────

test("every screen says the case result's verdict and severity — for every outcome, attention and briefing", () => {
  for (const [o, a, b] of matrix) {
    const at = `${o}/${a}/${b}`;
    const resp = response(o, a, b);
    const inv = investigation(resp);
    const r = caseResult(resp as never);
    // The result itself: a briefing that failed its Fidelity Check never decides anything.
    assert.equal(r.verdict, LABEL[o], at);
    assert.equal(r.verdictCode, o, at);
    // An investigation that couldn't decide, with nothing concrete to act on, is not fully checked: no warning, no alert.
    const undecided = o === "unable_to_determine" && (a === "review" || a === "none");
    assert.equal(r.notFullyChecked, undecided, at);
    assert.equal(r.severity, undecided ? "resting" : SEVERITY[a], at);
    assert.equal(r.from, b === "pass" ? "briefing" : "response", at);

    // Findings Brief (Ask Higgins and a threat).
    const brief = investigationVerdict(resp as never);
    assert.equal(brief.label, r.verdict, at);
    assert.deepEqual(brief.risk ?? null, riskPill(r.severity), at);
    assert.deepEqual(resultVerdict(r), { label: r.verdict, tone: r.tone, risk: riskPill(r.severity) }, at);

    // The case on this device (Home, Threats, notifications read this copy).
    const event = investigationPatch(placeholder, inv)!;
    assert.equal(event.state, r.severity, at);
    assert.equal(event.case_briefing?.verdict, r.verdict, at);
    assert.equal(event.case_briefing?.severity, r.severity, at);
    assert.deepEqual(eventBriefing(resp as never)?.verdictCode, o, at);
    assert.deepEqual(threatResult(event, null), r, `the event's copy differs from the result (${at})`);
    assert.deepEqual(threatResult(event, resp as never), r, at);

    // Status: closed on its own only when nothing was found; "Needs you" only with the recorded reason.
    const status = threatCaseStatus(event);
    if (r.notFullyChecked) assert.equal(status, "not_fully_checked", at);
    else if (r.noConcern) assert.equal(status, r.severity === "resting" ? "no_threat" : "resolved", at);
    else assert.equal(status, event.case_briefing?.userActionRequired ? "attention" : "monitoring", at);
    // Closed on its own only when nothing was found or it is not fully checked; never "No threat" when undecided.
    assert.equal(!!event.resolved_at, r.noConcern || r.notFullyChecked, at);
    assert.equal(r.noConcern, o === "no_scam_indicators", at);

    // Home hero.
    assert.match(eventBrief(event).line1, new RegExp(`${HERO[o]}\\.$`), at);

    // Evidence: a result recorded without an Evidence record lists its findings word for word, with the confidence recorded.
    const ev = caseEvidence({ event, investigation: inv, trace: null, records: [], facts: [] });
    const found = caseFindings(resp as never);
    assert.deepEqual(ev.facts.map((f) => [f.text, f.confidence]).sort(), found.map((f) => [f.text, f.confidence]).sort(), at);

    // History: the verdict entry says the same verdict the Findings Brief shows.
    const trail = caseAuditTrail({ event, investigation: inv, trace: null, records: [], verdict: r.verdict });
    assert.ok(trail.some((e) => e.description === `Verdict: ${r.verdict}.`), at);

    // DI: what Higgins presented is the same verdict and risk.
    const steps = buildDecisionTrace({ trace: { triage: null, flyby: null, magnum: null, answeredBy: "tc_flyby", outcome: o, completion: "complete",
      settledReason: null, higgins: { status: "PASS", mode: "plain", attempts: 1 } }, records: [], triage: null, hasCase: true,
    presented: { verdict: brief.label, risk: brief.risk?.label ?? null } });
    const lock = steps.find((s) => s.id === "lock")!;
    assert.equal(lock.details[0], `Locked verdict: ${r.verdict}${riskPill(r.severity) ? ` · ${riskPill(r.severity)!.label}` : ""}`, at);
  }
});

// ── 3. No screen works a verdict or severity out for itself ─────────────────────────────────────────────────────────

const SURFACES = [
  "../app/patrol/[id].tsx", "../app/(tabs)/home.tsx", "../app/(tabs)/patrol.tsx", "../src/components/InvestigationView.tsx",
  "../src/components/report/FindingsBrief.tsx", "../src/components/report/CaseEvidenceTab.tsx", "../src/components/DiReport.tsx",
  "../src/domain/homeHeroBrief.ts", "../src/domain/caseEvidence.ts", "../src/domain/investigationCaseUpdate.ts",
];
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const RESULT_CODES = "urgent|action_needed|review|none|confirmed_threat|likely_scam|concerning|unable_to_determine|no_scam_indicators";

test("no screen reads the result's outcome or attention directly, or maps them to a severity of its own", () => {
  // (Higgins Triage's own record — "LIMITED_UNABLE_TO_DETERMINE" — and retry outcomes are records of their own.)
  const decides = new RegExp(`\\b(attention|outcome)\\s*[!=]==\\s*["'](${RESULT_CODES})["']`);
  for (const path of SURFACES) {
    const src = read(path);
    assert.doesNotMatch(src, decides, `${path} decides from the outcome or attention itself`);
    assert.doesNotMatch(src, /\b(stateFromOutcome|stateFromAssessment|investigationState|caseSeverity)\(/, `${path} works out a severity itself`);
  }
  // The screens show the threat's result through the one reader.
  assert.match(read("../app/patrol/[id].tsx"), /threatResult\(event, investigation\?\.response \?\? null\)/);
  assert.match(read("../src/components/InvestigationView.tsx"), /investigationVerdict\(/);
  assert.match(read("../src/domain/investigationCaseUpdate.ts"), /caseResult\(response\)/);
});

test("DI and History are handed the same verdict the Findings Brief shows", () => {
  const src = read("../app/patrol/[id].tsx");
  assert.match(src, /<HistoryContent [^>]*verdict=\{result \? verdict\.label : null\}/);
  assert.match(src, /presented=\{result \? \{ verdict: verdict\.label, risk: verdict\.risk\?\.label \?\? null \} : null\}/);
});
