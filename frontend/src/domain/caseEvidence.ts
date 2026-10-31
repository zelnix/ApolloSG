// The Threat Case Evidence tab: the material facts the case established, strongest first — never the item you
// submitted again, and never the verdict. Built from the case's own records only:
//   • a result's Evidence record (backend services/higgins/case_evidence.py): each fact once, with the stage that found
//     it first and the later stages that established it too ("Found by X · Confirmed by Y, Z");
//   • a result recorded before that record existed: its findings, in the result's own words, with no "Found by" line —
//     who found what wasn't recorded, so it is never guessed;
//   • a case no investigation has answered: what Higgins Triage or Apollo recorded about the item;
//   • a block this device recorded: a device observation, listed like any other fact.
// A fact that points the other way is listed with the rest and marked, never dropped. Pure: unit-tested in node.
import type { DeviceInvestigation } from "../investigation/deviceStore";
import type { EvidenceFact, EvidenceItem, EvidenceStage, HigginsResponse, SourceReference } from "../investigation/types";
import { caseFindings } from "./caseBriefing.ts";
import { raisedBy, type RaisedFrom } from "./caseHistory.ts";
import type { DiTrace, DiTransaction } from "./diTransaction.ts";
import { settledByFlyby } from "./messageVoice.ts";
import type { PatrolEvent } from "./types";

export type FactStance = "supporting" | "contrary" | "neutral";
/** Who established a fact: an investigation stage, or Apollo itself on this device (a block it recorded). */
export type Finder = EvidenceStage | "this_device";
export const FINDER_LABEL: Record<Finder, string> = {
  higgins_triage: "Higgins Triage", tc_flyby: "TC FlyBy", magnum_di: "Magnum DI", this_device: "Apollo on this device",
};
export type Confidence = "low" | "medium" | "high";

/** One material fact, as its card shows it. */
export interface FactPiece {
  id: string;
  text: string;
  stance: FactStance;
  /** Null when the record doesn't say who found it (a result recorded before the Evidence record): no "Found by" line. */
  foundBy: Finder | null;
  confirmedBy: Finder[];
  confidence: Confidence | null;
  /** A weak signal: recorded, never a concern on its own. */
  weak: boolean;
  /** Seen directly — in the evidence, or by this device. */
  observed: boolean;
  /** How it was found, in plain words. */
  basis: string | null;
  /** What it rests on, by name ("the email you submitted", "TC FlyBy's checks"). */
  basedOn: string[];
  at: string | null;
  simulated: boolean;
  /** Related history that raised its confidence, in its own words (context, never evidence). */
  raisedBy: { from: RaisedFrom; text: string }[];
  sources: { title: string; url: string; authority: string }[];
  /** Extra recorded detail (a block's mechanism). */
  details: { label: string; value: string }[];
  /** A device observation (this device's own record) rather than an investigation's finding. */
  device: boolean;
}

export interface TrailStage {
  id: "triage" | "flyby" | "magnum";
  name: string;
  /** "Completed", "Escalated to Magnum DI", "Didn't finish", "In progress"… as recorded. */
  status: string;
  tone: "done" | "escalated" | "failed" | "pending";
  at: string | null;
}

export interface CaseEvidence {
  facts: FactPiece[];
  trail: TrailStage[];
  /** A message case whose investigation never received the message (opened before checks sent it along). */
  messageNotSaved: boolean;
}

const clean = (v: string | null | undefined) => (v ?? "").replace(/\s+/g, " ").trim();
const normal = (v: string) => clean(v).toLowerCase().replace(/[’‘]/g, "'").replace(/[^a-z0-9'$%@.]+/g, " ").trim();

/** "Found by TC FlyBy · Confirmed by Magnum DI" — null when who found it wasn't recorded. */
export function provenanceLine(p: Pick<FactPiece, "foundBy" | "confirmedBy">): string | null {
  if (!p.foundBy) return null;
  const confirmed = p.confirmedBy.filter((f) => f !== p.foundBy).map((f) => FINDER_LABEL[f]);
  return `Found by ${FINDER_LABEL[p.foundBy]}${confirmed.length ? ` · Confirmed by ${confirmed.join(", ")}` : ""}`;
}

const CONFIDENCE_WEIGHT: Record<Confidence, number> = { high: 3, medium: 2, low: 1 };

/** How strongly a fact bears on the case: how firmly it was recorded, how many stages established it and whether it was
 *  seen directly. A weak signal, or a fact that bears on neither side, comes after the rest. Order only: never shown. */
export function factStrength(p: Pick<FactPiece, "confidence" | "confirmedBy" | "observed" | "weak" | "stance">): number {
  return (p.confidence ? CONFIDENCE_WEIGHT[p.confidence] : 1.5) + 0.75 * p.confirmedBy.length + (p.observed ? 0.25 : 0)
    - (p.weak ? 1.5 : 0) - (p.stance === "neutral" ? 1 : 0);
}

/** Strongest first; equally strong facts keep the order they were established in. */
export function orderFacts(facts: FactPiece[]): FactPiece[] {
  return facts.map((f, i) => ({ f, i })).sort((a, b) => factStrength(b.f) - factStrength(a.f) || a.i - b.i).map(({ f }) => f);
}

// ── What a fact rests on, by name ───────────────────────────────────────────

const BASIS_WORDS: Record<string, string> = {
  observation: "Seen in the evidence", inference: "Worked out from the evidence", user_report: "What you told Apollo",
};
const SUBMITTED_NOUN: Record<string, string> = { email: "email", call: "call details", file: "file", app: "app details", link: "link", website: "link" };
const INTERNAL_ITEM: Record<string, string> = {
  "tc-flyby-di-checks": "TC FlyBy's checks", "tc-flyby-di-brief": "TC FlyBy's brief to Magnum DI", "apollo-triage-intelligence": "Higgins Triage's lookups",
};

function itemName(item: EvidenceItem, byId: Map<string, EvidenceItem>, category: string): string | null {
  const noun = SUBMITTED_NOUN[category] ?? "message";
  if (INTERNAL_ITEM[item.clientItemId]) return INTERNAL_ITEM[item.clientItemId];
  if (item.origin === "device_observation") return "a reading from this device";
  if (item.origin === "apollo_inference") return /fly-?by/i.test(item.label) ? "TC FlyBy's checks" : clean(item.label) || null;
  const parent = item.parentId ? byId.get(item.parentId) : undefined;
  if (parent) return item.kind === "url" ? `a link in the ${noun} you submitted` : `part of the ${noun} you submitted`;
  if (item.kind === "url") return "the link you submitted";
  if (item.kind === "image") return "the picture you submitted";
  return `the ${noun} you submitted`;
}

function namesOf(ids: string[], byId: Map<string, EvidenceItem>, category: string): string[] {
  return [...new Set(ids.map((id) => byId.get(id)).filter((i): i is EvidenceItem => !!i)
    .map((i) => itemName(i, byId, category)).filter((n): n is string => !!n))];
}

function sourcesOf(ids: string[], refs: Map<string, SourceReference>): FactPiece["sources"] {
  return ids.map((id) => refs.get(id)).filter((r): r is SourceReference => !!r)
    .map((r) => ({ title: clean(r.title) || r.url, url: r.url, authority: r.authority }));
}

// ── The facts ────────────────────────────────────────────────────────────────

/** The result's Evidence record, as recorded. */
function recordedFacts(response: HigginsResponse, record: EvidenceFact[], ctx: Ctx): FactPiece[] {
  return record.filter((f) => clean(f.text)).map((f) => ({
    id: f.id, text: clean(f.text), stance: f.stance, foundBy: f.discoveredBy, confirmedBy: f.corroboratedBy ?? [],
    confidence: f.confidence, weak: !!f.weak, observed: f.basis === "observation",
    basis: BASIS_WORDS[f.basis] ?? null, basedOn: namesOf(f.evidenceIds ?? [], ctx.byId, ctx.category),
    at: f.establishedAt ?? ctx.at, simulated: !!f.simulated,
    raisedBy: (f.findingIds ?? []).flatMap((id) => raisedBy(response, id)),
    sources: sourcesOf(f.sourceIds ?? [], ctx.refs), details: [], device: false,
  }));
}

/** A result recorded before the Evidence record: its findings in its own words, each once; who found them unsaid. */
function earlierFindings(response: HigginsResponse, ctx: Ctx): FactPiece[] {
  const seen = new Set<string>();
  return caseFindings(response).filter((f) => {
    const key = normal(f.text);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((f) => ({
    id: f.id, text: f.text, stance: f.stance === "contrary" ? "contrary" as const : f.stance === "supporting" ? "supporting" as const : "neutral" as const,
    foundBy: null, confirmedBy: [], confidence: (f.confidence as Confidence | null) ?? null, weak: false, observed: f.basis === "observation",
    basis: BASIS_WORDS[f.basis] ?? null, basedOn: namesOf(f.evidenceIds, ctx.byId, ctx.category), at: ctx.at, simulated: false,
    raisedBy: raisedBy(response, f.id), sources: sourcesOf(f.sourceIds, ctx.refs), details: [], device: false,
  }));
}

/** No investigation has answered: what Higgins Triage (a check) or Apollo (its own detection) recorded about the item.
 *  The case's headline names the case, so it isn't one of its facts. */
function recordedOnThePhone(event: PatrolEvent, facts: string[]): FactPiece[] {
  const headline = normal(event.headline ?? "");
  const by: Finder = event.triage_investigation || event.origin === "user" ? "higgins_triage" : "this_device";
  const seen = new Set<string>();
  return facts.map(clean).filter((line) => {
    const key = normal(line);
    if (!key || key === headline || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((text, i) => ({
    id: `recorded:${i}`, text, stance: "supporting" as const, foundBy: by, confirmedBy: [], confidence: null, weak: false, observed: true,
    basis: by === "this_device" ? "Recorded by Apollo on this device" : "Seen in what was checked", basedOn: [], at: event.occurred_at,
    simulated: !!(event.evidence_profile?.simulated || event.investigation_simulated), raisedBy: [], sources: [], details: [], device: false,
  }));
}

/** A block this device recorded: an observation like any other fact, as firm as its own record. */
function blockFact(e: PatrolEvent): FactPiece | null {
  const ev = e.enforcement_evidence;
  if (!ev) return null;
  const proved = !!e.verified_block;
  const action = clean(ev.enforced_action.replace(/_/g, " "));
  return {
    id: "block", text: `Apollo ${action || "acted"}${ev.destination_domain ? ` on ${ev.destination_domain}` : ""} — ${clean(ev.result.replace(/_/g, " "))}.`,
    stance: "supporting", foundBy: "this_device", confirmedBy: [], confidence: proved ? "high" : "low", weak: false, observed: proved,
    basis: proved ? "This device observed the blocked connection and matched it to this case."
      : "The record doesn't contain a packet drop Apollo observed and matched to this event.",
    basedOn: [], at: ev.observed_at, simulated: false, raisedBy: [], sources: [],
    details: [{ label: "Mechanism", value: clean(ev.mechanism.replace(/_/g, " ")) }], device: true,
  };
}

interface Ctx { byId: Map<string, EvidenceItem>; refs: Map<string, SourceReference>; category: string; at: string | null }

// ── Evidence trail ───────────────────────────────────────────────────────────

/** Only the stages that actually happened, each with what it recorded. */
export function evidenceTrail(input: { event: PatrolEvent; trace: DiTrace | null; records: DiTransaction[] }): TrailStage[] {
  const { event, trace, records } = input;
  const out: TrailStage[] = [];
  const triage = trace?.triage ?? event.triage_investigation ?? null;
  const flyby = trace?.flyby ?? null;
  const hasCase = !!(event.investigation_case_id ?? event.patrol_record?.investigationCaseId);
  if (triage || flyby) out.push({ id: "triage", name: "Higgins Triage", status: "Completed", tone: "done", at: triage?.evaluatedAt ?? flyby?.ranAt ?? null });
  if (flyby) {
    out.push({ id: "flyby", name: "TC FlyBy", status: flyby.resolved ? "Completed" : "Escalated to Magnum DI", tone: flyby.resolved ? "done" : "escalated", at: flyby.ranAt });
  } else if (hasCase && event.investigation_completed_at && settledByFlyby(event.investigation_answered_by)) {
    out.push({ id: "flyby", name: "TC FlyBy", status: "Completed", tone: "done", at: event.investigation_completed_at });
  }
  if (records.length) {
    const last = records[records.length - 1];
    const failed = !!last.failureCode || (last.status ?? "success") !== "success";
    out.push({ id: "magnum", name: "Magnum DI", status: failed ? "Didn't finish" : last.simulated ? "Completed (simulated)" : "Completed",
      tone: failed ? "failed" : "done", at: trace?.magnum?.at ?? last.occurredAt ?? null });
  } else if (trace?.magnum) {
    out.push({ id: "magnum", name: "Magnum DI", status: "Completed", tone: "done", at: trace.magnum.at });
  } else if (!flyby && hasCase && event.investigation_completed_at && event.investigation_answered_by && !settledByFlyby(event.investigation_answered_by)) {
    out.push({ id: "magnum", name: "Magnum DI", status: "Completed", tone: "done", at: event.investigation_completed_at });
  }
  if (hasCase && !event.investigation_completed_at && !out.some((s) => s.id !== "triage")) {
    out.push({ id: "flyby", name: "TC FlyBy", status: "In progress", tone: "pending", at: null });
  }
  return out;
}

// ── The whole tab ────────────────────────────────────────────────────────────

export function caseEvidence(input: {
  event: PatrolEvent; investigation: DeviceInvestigation | null; trace: DiTrace | null; records: DiTransaction[];
  /** What Higgins Triage / Apollo recorded about the item (its met rules' evidence and recorded signals). */
  facts: string[];
}): CaseEvidence {
  const { event, investigation, trace, records, facts } = input;
  const response = investigation?.response ?? null;
  const ctx: Ctx = {
    byId: new Map((investigation?.evidenceItems ?? []).map((i) => [i.id, i])),
    refs: new Map((investigation?.sources ?? []).map((r) => [r.id, r])),
    category: event.category, at: investigation?.committedAt ?? investigation?.completedAt ?? null,
  };
  const found = !response ? recordedOnThePhone(event, facts)
    : Array.isArray(response.evidence) ? recordedFacts(response, response.evidence, ctx) : earlierFindings(response, ctx);
  const block = blockFact(event);
  const messageNotSaved = event.category === "message" && !!investigation
    && !(investigation.evidenceItems ?? []).some((i) => i.origin === "user_submission");
  return { facts: orderFacts(block ? [...found, block] : found), trail: evidenceTrail({ event, trace, records }), messageNotSaved };
}
