// The DI tab: how the investigation reached its result, in the order it ran —
// Higgins Triage → TC Hawkeye → Magnum DI → Evidence Lock — and the outside research behind it, each source with the
// fact it supports or points against. Plain words only: rule-book codes, token counts, cost and Magnum DI's raw reply
// are in the Admin Portal, never here. Every step is built from what was recorded (the Triage record, the case's
// routing, the Magnum DI transactions and the result itself). A stage with no record says so — nothing is inferred.
// Pure: unit-tested in node.

import type { EvidenceFact, HigginsResponse, SourceReference } from "../investigation/types";
import { caseFindings } from "./caseBriefing.ts";
import { shortfallLine, triageShortfalls } from "./caseFacts.ts";
import type { DiTrace, DiTransaction } from "./diTransaction.ts";
import { investigatorName, outcomeLabel } from "./messageVoice.ts";
import { outcomeLabel as triageOutcomeLabel, plainTriageText, type TriageInvestigationRecord } from "./triage/contract.ts";

export type TraceStatus = "ran" | "settled" | "escalated" | "not_engaged" | "failed" | "simulated" | "pending" | "not_recorded";

export interface TraceStep {
  id: "triage" | "flyby" | "magnum" | "lock";
  name: string;
  status: TraceStatus;
  label: string;
  summary: string;
  details: string[];
}

export const TRACE_ORDER = "Higgins Triage → TC Hawkeye → Magnum DI → Evidence Lock";

const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

/** Whether a Magnum DI transaction finished with an answer. */
export function diSucceeded(record: DiTransaction): boolean {
  return !record.failureCode && (record.status ?? "success") === "success";
}

// ── TC Hawkeye's checks, in plain words ───────────────────────────────────────

const CHECK_LABEL: Record<string, string> = {
  general_question: "Your question", link: "The website", impersonation: "Who it claims to be from", phone: "The phone number",
  email: "The email address", company: "The business named", abn: "The ABN", acn: "The ACN", licence: "The licence number",
  person: "The person named", phrase: "Its wording, for copies elsewhere", claim: "A claim it makes", scam_alerts: "Current scam alerts",
  message_analysis: "The message as a whole", scam_pattern: "Known scam patterns",
};
const ROUTE_LABEL: Record<string, string> = {
  official_source: "official sources", apollo_kb: "ApolloSG's library", web_search: "a web search", google_search: "a web search",
  triage_rules: "Higgins Triage's rules",
};
const STATUS_LABEL: Record<string, string> = {
  resolved: "checked", checked: "checked", not_found: "no record found", unavailable: "couldn't be checked",
  needs_reasoning: "left for Magnum DI", not_needed: "not needed", open: "not checked",
};

export const checkLabel = (kind: string): string => CHECK_LABEL[kind] ?? `${kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}`;

/** "The website: checked with official sources". */
export function checkLine(c: { kind: string; status: string; route: string | null }): string {
  const how = c.route && ROUTE_LABEL[c.route] ? ` with ${ROUTE_LABEL[c.route]}` : "";
  return `${checkLabel(c.kind)}: ${STATUS_LABEL[c.status] ?? c.status.replace(/_/g, " ").toLowerCase()}${STATUS_LABEL[c.status] === "checked" ? how : ""}`;
}

function searchLine(flyby: NonNullable<DiTrace["flyby"]>): string | null {
  const calls = flyby.searchCalls ?? 0;
  if (!calls) return null;
  const saved = flyby.cacheHits ?? 0;
  return `TC Hawkeye ran ${plural(flyby.searchQueries || calls, "web search", "web searches")}${saved ? `, ${saved} answered from earlier results` : ""}.`;
}

// ── The steps ────────────────────────────────────────────────────────────────

/** On the server, Higgins Triage runs at the start of TC Hawkeye (it prepares what was sent and plans TC Hawkeye's
 *  checks), so a case with no Triage record of its own has its Triage in TC Hawkeye's record. */
function triageInFlyby(flyby: NonNullable<DiTrace["flyby"]>): TraceStep {
  const rulesMet = flyby.checks.some((c) => c.kind === "triage_rules");
  const planned = [...new Set(flyby.checks.filter((c) => c.kind !== "triage_rules").map((c) => checkLabel(c.kind).toLowerCase()))];
  return {
    id: "triage", name: "Higgins Triage", status: "ran", label: rulesMet ? "Warning signs found" : "Ran with TC Hawkeye",
    summary: `Higgins Triage prepared what was sent and planned ${plural(planned.length, "check")} for TC Hawkeye`
      + (rulesMet ? "; its rules found warning signs in it." : "."),
    details: planned.length ? [`Planned to check: ${planned.join(", ")}.`] : [],
  };
}

function triageStep(triage: TriageInvestigationRecord | null, hasCase: boolean, flyby: DiTrace["flyby"] | null): TraceStep {
  const name = "Higgins Triage";
  if (!triage && flyby) return triageInFlyby(flyby);
  if (!triage) return { id: "triage", name, status: "not_recorded", label: "No record", summary: "No Higgins Triage record is stored for this case.", details: [] };
  const met = triage.rules.filter((r) => r.result === "met");
  return {
    id: "triage", name, status: "ran", label: triageOutcomeLabel(triage),
    summary: `Checked ${triage.rulesChecked.length} of the ${plural(triage.rulesApplicable.length, "warning-sign rule")} that apply; `
      + `${met.length ? `${met.length} matched` : "none matched"}. `
      + (hasCase ? "It opened an investigation." : "It stopped here, so Magnum DI was not engaged."),
    details: [
      ...(triage.reason ? [plainTriageText(triage.reason)] : []),
      ...met.map((r) => `Warning sign: ${r.title}`),
      ...triageShortfalls(triage).map(shortfallLine),
    ],
  };
}

function flybyStep(trace: DiTrace | null, hasCase: boolean): TraceStep {
  const name = "TC Hawkeye";
  const flyby = trace?.flyby;
  if (!flyby) {
    return hasCase
      ? { id: "flyby", name, status: "not_recorded", label: "No record", summary: "No TC Hawkeye record is stored for this case.", details: [] }
      : { id: "flyby", name, status: "not_engaged", label: "Not engaged", summary: "TC Hawkeye was not engaged — Higgins Triage didn't open an investigation.", details: [] };
  }
  const reason = trace?.settledReason;
  const common = [
    ...flyby.checks.filter((c) => c.kind !== "triage_rules").map(checkLine),
    ...(flyby.pattern ? [`Matched a known scam pattern (${flyby.pattern.stage} match).`] : []),
    ...(searchLine(flyby) ? [searchLine(flyby) as string] : []),
    ...(flyby.gaps ?? []).map((g) => `Couldn't read: ${g.item} — ${g.what}`),
  ];
  if (flyby.resolved) {
    return {
      id: "flyby", name, status: "settled", label: `Settled · ${outcomeLabel(flyby.outcome) ?? "result recorded"}`,
      summary: reason?.by === "TC Hawkeye" ? reason.sentence : "TC Hawkeye settled this case with its automated checks.",
      details: ["This is an administrative determination from rule-based checks, not a deep investigation by Magnum DI.", ...common],
    };
  }
  return {
    id: "flyby", name, status: "escalated", label: "Escalated to Magnum DI",
    summary: reason?.by === "Magnum DI" ? reason.sentence : "TC Hawkeye couldn't settle this case, so it passed it to Magnum DI.",
    details: [...(flyby.issues ?? []).map((i) => `Left for Magnum DI: ${i.text}`), ...common],
  };
}

function magnumStep(trace: DiTrace | null, records: DiTransaction[], hasCase: boolean): TraceStep {
  const name = "Magnum DI";
  const magnum = trace?.magnum;
  if (records.length) {
    const last = records[records.length - 1];
    const attachments = records.reduce((n, r) => n + (r.request.attachmentCount ?? 0), 0);
    const details = [
      ...(magnum ? [`Given ${plural(magnum.itemsSent, "evidence item")}.`,
        magnum.webSearch ? `Web search on${magnum.searchQueries ? ` — ${plural(magnum.searchQueries, "search", "searches")}` : ""}.` : "Web search off."] : []),
      ...(attachments ? [`${plural(attachments, "picture or file", "pictures or files")} sent, each screened and with your personal information removed first.`] : []),
      ...(records.length > 1 ? [`Engaged ${records.length} times.`] : []),
    ];
    if (last.simulated) {
      return { id: "magnum", name, status: "simulated", label: "Simulated", details,
        summary: "Magnum DI ran exactly as in production; the preview stood in for the outside service Magnum DI calls." };
    }
    if (!diSucceeded(last)) {
      const why = (last.failureCode ?? last.status ?? "").replace(/_/g, " ");
      return { id: "magnum", name, status: "failed", label: "Didn't finish", details,
        summary: `Magnum DI was engaged but didn't finish${why ? ` (${why})` : ""}.` };
    }
    return {
      id: "magnum", name, status: "ran", label: "Investigated", details,
      summary: magnum
        ? `Magnum DI investigated ${plural(magnum.itemsSent, "evidence item")} ${magnum.webSearch ? "with" : "without"} web search.`
        : "Magnum DI investigated the case.",
    };
  }
  if (trace?.flyby?.resolved) return { id: "magnum", name, status: "not_engaged", label: "Not needed",
    summary: "Magnum DI was not engaged because TC Hawkeye's automated checks resolved all identified questions.",
    details: ["Deep investigation was not required — the rule-based checks were sufficient for this case."] };
  if (!hasCase) return { id: "magnum", name, status: "not_engaged", label: "Not needed",
    summary: "Magnum DI was not engaged because Higgins Triage did not open an investigation.",
    details: ["Triage rules did not indicate the need for a full investigation."] };
  if (trace?.flyby) return { id: "magnum", name, status: "pending", label: "No record yet", summary: "Escalated to Magnum DI. No Magnum DI record is stored for this case yet.", details: [] };
  return { id: "magnum", name, status: "not_recorded", label: "No record", summary: "No Magnum DI record is stored for this case.", details: [] };
}

/** What Higgins presented, as the case result records it — the same verdict and severity the Findings Brief shows. */
export interface PresentedResult { verdict: string | null; risk: string | null }

/** The result's facts by side, as its Evidence record holds them (else its findings, sides unrecorded). */
function factCount(response: HigginsResponse | null): { total: number; contrary: number } | null {
  if (!response) return null;
  if (Array.isArray(response.evidence)) return { total: response.evidence.length, contrary: response.evidence.filter((f) => f.stance === "contrary").length };
  const findings = caseFindings(response);
  return { total: findings.length, contrary: findings.filter((f) => f.stance === "contrary").length };
}

function lockStep(trace: DiTrace | null, triage: TriageInvestigationRecord | null, hasCase: boolean, presented: PresentedResult | null,
  response: HigginsResponse | null): TraceStep {
  const name = "Evidence Lock";
  const who = hasCase ? investigatorName(trace?.answeredBy) : triage ? "Higgins Triage" : "Apollo";
  if (!presented?.verdict && !response && !(trace?.answeredBy || trace?.outcome)) {
    return { id: "lock", name, status: "pending", label: "Not yet", summary: "There's no result to lock yet.", details: [] };
  }
  const facts = factCount(response);
  const verdict = presented?.verdict ? `${presented.verdict}${presented.risk ? ` · ${presented.risk}` : ""}` : null;
  const details = [
    ...(verdict ? [`Recorded verdict: ${verdict}`] : []),
    ...(facts ? [`Captured ${plural(facts.total, "fact")}${facts.contrary ? `, ${facts.contrary} pointing the other way` : ""}.`] : []),
  ];
  const higgins = trace?.higgins;
  if (higgins?.status === "PASS") {
    details.push(higgins.mode === "repaired"
      ? "Higgins' plain English was checked against the recorded result; the parts that didn't match are shown in Apollo's own wording."
      : "Higgins' plain English was checked against the recorded result and matched it.");
  } else if (higgins?.status === "FAIL") {
    details.push("Higgins' plain English didn't match the recorded result, so Apollo's own wording is shown.");
  } else if (hasCase) {
    details.push("No check of Higgins' plain English is recorded for this result.");
  } else if (triage?.outcome === "LIMITED_UNABLE_TO_DETERMINE") {
    details.push("Higgins advised treating it with caution — it is never shown as safe.");
  }
  return {
    id: "lock", name, status: higgins?.status === "FAIL" ? "failed" : "ran", label: "Preserved",
    summary: `The Evidence Lock preserves ${who}'s original decision as it was at the time. It records what was concluded — it does not independently verify that conclusion.`, details,
  };
}

export function buildDecisionTrace(input: {
  trace: DiTrace | null; records: DiTransaction[]; triage: TriageInvestigationRecord | null; hasCase: boolean;
  presented?: PresentedResult | null; response?: HigginsResponse | null;
}): TraceStep[] {
  const { trace, records, triage, hasCase, presented = null, response = null } = input;
  return [triageStep(triage, hasCase, trace?.flyby ?? null), flybyStep(trace, hasCase), magnumStep(trace, records, hasCase),
    lockStep(trace, triage, hasCase, presented, response)];
}

// ── Outside research ────────────────────────────────────────────────────────

export interface ResearchRow {
  id: string;
  title: string;
  /** The website it came from, when it has one. */
  site: string | null;
  url: string | null;
  /** "Official source" · "Independent source"… */
  standing: string;
  /** "Read directly" · "Found by a web search" · "Couldn't be read". */
  how: string;
  at: string | null;
  reused: boolean;
  supports: string[];
  against: string[];
  /** Facts it informs that bear on neither side, or whose side wasn't recorded. */
  other: string[];
}

const STANDING: Record<SourceReference["authority"], string> = {
  official: "Official source", independent: "Independent source", self_claimed: "The sender's own claim", unknown: "Standing unknown",
};
const HOW: Record<SourceReference["retrieval"], string> = { fetched: "Read directly", search_result: "Found by a web search", unavailable: "Couldn't be read" };

function siteOf(url: string): string | null {
  const m = /^https?:\/\/([^/?#]+)/i.exec(url.trim());
  return m ? m[1].replace(/^www\./i, "").toLowerCase() : null;
}

/** Every outside source the result rests on, with the facts it supports or points against, as the result recorded
 *  them. A source no fact cites is still listed: it was consulted. */
export function outsideResearch(sources: SourceReference[], response: HigginsResponse | null): ResearchRow[] {
  const facts: Pick<EvidenceFact, "text" | "sourceIds" | "stance">[] = !response ? []
    : Array.isArray(response.evidence) ? response.evidence
      : caseFindings(response).map((f) => ({ text: f.text, sourceIds: f.sourceIds, stance: f.stance === "contrary" ? "contrary" : f.stance === "supporting" ? "supporting" : "neutral" }));
  const seen = new Set<string>();
  const rows = sources.filter((s) => !seen.has(s.id) && seen.add(s.id)).map((s): ResearchRow => {
    const citing = facts.filter((f) => (f.sourceIds ?? []).includes(s.id));
    const texts = (stance: string) => [...new Set(citing.filter((f) => f.stance === stance).map((f) => f.text.trim()))];
    const site = s.url ? siteOf(s.url) : null;
    return {
      id: s.id, title: s.title?.trim() || site || "Untitled source", site, url: site ? s.url : null,
      standing: STANDING[s.authority] ?? STANDING.unknown, how: HOW[s.retrieval] ?? HOW.fetched, at: s.retrievedAt || null, reused: !!s.reused,
      supports: texts("supporting"), against: texts("contrary"), other: texts("neutral"),
    };
  });
  const weight = (r: ResearchRow) => (r.against.length || r.supports.length ? 0 : r.other.length ? 1 : 2);
  return rows.map((r, i) => ({ r, i })).sort((a, b) => weight(a.r) - weight(b.r) || a.i - b.i).map(({ r }) => r);
}
