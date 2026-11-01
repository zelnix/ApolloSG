// The Threat Case History tab: a strict audit trail of what happened to the case and when, oldest first — the case
// created, Higgins Triage, TC FlyBy, the escalation, Magnum DI, evidence added, the Evidence Lock, the verdict, and
// what the person did with it. Every entry is a recorded event with its recorded time: a stage that didn't run has no
// entry, an event whose time wasn't recorded says so, and earlier results stay on the trail. Nothing from another case
// or another device appears here; sources and related cases belong to the Evidence tab and the Findings Brief.
// Pure: unit-tested in node.
import type { DeviceInvestigation } from "../investigation/deviceStore";
import type { DiTrace, DiTransaction } from "./diTransaction.ts";
import { investigatorName, outcomeLabel as caseOutcomeLabel, settledByFlyby } from "./messageVoice.ts";
import { categoryLabel } from "./threatCase.ts";
import { subjectDescriptor, threatSubject } from "./threatSubject.ts";
import { outcomeLabel as triageOutcomeLabel, type TriageInvestigationRecord } from "./triage/contract.ts";
import { upgrades } from "./triage/evidenceProfile.ts";
import type { PatrolEvent } from "./types";

/** How an entry is marked on the trail. */
export type AuditTone = "start" | "check" | "escalated" | "done" | "warning" | "closed";

export interface AuditEntry {
  id: string;
  /** When it happened, as recorded. Null: the record holds no time for it. */
  at: string | null;
  title: string;
  description: string;
  tone: AuditTone;
  /** Still under way (an investigation that hasn't answered). */
  pending?: boolean;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const words = (code: string) => code.replace(/_/g, " ");

const MECHANISM: Record<string, string> = {
  dns_sinkhole: "A DNS-level block was applied", content_policy: "A content filter was applied", firewall_rule: "A firewall rule was enforced",
  browser_interstitial: "A browser warning was shown", app_block: "An app-level block was applied", packet_drop: "The connection's packets were dropped",
};
const RECOVERY: Record<string, string> = {
  password_changed: "Password changed", account_locked: "Account locked", card_frozen: "Card frozen", reported_to_bank: "Reported to bank",
  blocked_sender: "Sender blocked", reported_to_authority: "Reported to authority",
};
const ITEM_NOUN: Record<string, string> = { text: "Text", url: "A link", image: "A picture", document: "A file", file: "A file", attachment: "A file" };

function created(event: PatrolEvent): AuditEntry {
  const subject = threatSubject(event);
  const what = subject ? subjectDescriptor(subject) : `this ${categoryLabel(event.category, event.patrol_record?.recordClass).toLowerCase()} item`;
  const description = event.origin === "sample_check" ? `Sample Check: Apollo checked ${what} through its production pipeline.`
    : event.origin === "user" ? `You submitted ${what} for checking.`
    : event.origin === "apollo" ? `Apollo detected ${what}.` : `${categoryLabel(event.category, event.patrol_record?.recordClass)} recorded: ${what}.`;
  return { id: "created", at: event.occurred_at, title: "Case created", description, tone: "start" };
}

function triageEntries(event: PatrolEvent): AuditEntry[] {
  const records = [...(event.triage_history ?? []), ...(event.triage_investigation ? [event.triage_investigation] : [])] as TriageInvestigationRecord[];
  const out = records.map((t, i): AuditEntry => ({
    id: `triage-${i}`, at: t.evaluatedAt || null, title: "Higgins Triage completed", tone: "check",
    description: `Result: ${triageOutcomeLabel(t)}.${i < records.length - 1 ? " This earlier result is kept on record." : ""}`,
  }));
  if (!out.length && event.patrol_record?.higginsBriefing) {
    const b = event.patrol_record;
    out.push({ id: "auto-checks", at: b.freshness?.observedAt ?? b.higginsBriefing?.generated_at ?? null, title: "Apollo's automatic checks completed",
      description: "Apollo finished his automatic checks on this item.", tone: "check" });
  }
  return out;
}

function evidenceAdded(event: PatrolEvent, investigation: DeviceInvestigation | null): AuditEntry[] {
  const out: AuditEntry[] = upgrades(event.evidence_profile).map(({ from, to }, i) => ({
    id: `upgrade-${i}`, at: to.at, title: "Evidence added", tone: "check",
    description: `${to.label} (was ${from.label}). Higgins Triage checked the case again with it.`,
  }));
  // Material the person added to the investigation after it opened: submitted later than the first item, as recorded.
  const items = (investigation?.evidenceItems ?? []).filter((i) => i.origin === "user_submission" && !i.parentId && i.collectedAt);
  const first = Math.min(...items.map((i) => Date.parse(i.collectedAt as string)));
  items.filter((i) => Date.parse(i.collectedAt as string) - first > 60_000).forEach((i, n) => out.push({
    id: `added-${n}`, at: i.collectedAt ?? null, title: "Evidence added", tone: "check",
    description: `${ITEM_NOUN[i.kind] ?? "An item"} was added to the investigation.`,
  }));
  return out;
}

function investigationEntries(event: PatrolEvent, investigation: DeviceInvestigation | null, trace: DiTrace | null, records: DiTransaction[]): AuditEntry[] {
  const out: AuditEntry[] = [{ id: "opened", at: investigation?.createdAt ?? null, title: "Investigation opened", tone: "start",
    description: "ApolloSG opened an investigation for a closer look." }];
  const flyby = trace?.flyby;
  const answeredBy = investigation?.answeredBy ?? event.investigation_answered_by ?? null;
  if (flyby) {
    if (flyby.resolved) {
      out.push({ id: "flyby", at: flyby.ranAt, title: "TC FlyBy settled the case", tone: "done",
        description: `Result: ${caseOutcomeLabel(flyby.outcome) ?? "recorded"}. Magnum DI wasn't needed.` });
    } else {
      out.push({ id: "flyby", at: flyby.ranAt, title: "TC FlyBy completed its checks", tone: "check", description: "Its checks alone couldn't settle the case." });
      const issues = (flyby.issues ?? []).map((i) => i.text.trim()).filter(Boolean);
      out.push({ id: "escalated", at: flyby.ranAt, title: "Escalated to Magnum DI", tone: "escalated",
        description: issues.length ? `Left for Magnum DI: ${issues.join(" ")}` : "TC FlyBy passed the case to Magnum DI." });
    }
  } else if (event.investigation_completed_at && settledByFlyby(answeredBy)) {
    out.push({ id: "flyby", at: event.investigation_completed_at, title: "TC FlyBy settled the case", tone: "done", description: "Magnum DI wasn't needed." });
  }
  records.forEach((r, i) => {
    const failed = !!r.failureCode || (r.status ?? "success") !== "success";
    out.push({
      id: `magnum-${i}`, at: r.occurredAt ?? trace?.magnum?.at ?? null, tone: failed ? "warning" : "done",
      title: failed ? "Magnum DI didn't finish" : "Magnum DI completed its investigation",
      description: failed ? `It stopped before answering${r.failureCode || r.status ? ` (${words(r.failureCode ?? r.status ?? "")})` : ""}.`
        : `${trace?.magnum ? `It examined ${plural(trace.magnum.itemsSent, "evidence item")}.` : "It investigated the case."}${r.simulated ? " The preview stood in for the outside service Magnum DI calls." : ""}`,
    });
  });
  if (!records.length && trace?.magnum) {
    out.push({ id: "magnum", at: trace.magnum.at, title: "Magnum DI completed its investigation", tone: "done",
      description: `It examined ${plural(trace.magnum.itemsSent, "evidence item")}.` });
  } else if (!records.length && !flyby && event.investigation_completed_at && answeredBy && !settledByFlyby(answeredBy)) {
    out.push({ id: "magnum", at: event.investigation_completed_at, title: "Magnum DI completed its investigation", tone: "done", description: "It investigated the case." });
  }
  return out;
}

function lockEntry(investigation: DeviceInvestigation, trace: DiTrace | null, event: PatrolEvent): AuditEntry {
  const response = investigation.response;
  const facts = Array.isArray(response.evidence) ? response.evidence : null;
  const who = investigatorName(investigation.answeredBy ?? event.investigation_answered_by);
  const contrary = facts?.filter((f) => f.stance === "contrary").length ?? 0;
  const higgins = trace?.higgins;
  return {
    id: "lock", at: investigation.completedAt || investigation.committedAt || null, title: "Evidence locked", tone: "done",
    description: `${who}'s result was locked${facts ? ` with ${plural(facts.length, "fact")}${contrary ? `, ${contrary} pointing the other way` : ""}` : ""}, before Higgins explained it.`
      + (higgins?.status === "PASS" ? " Higgins' plain English matched the locked result."
        : higgins?.status === "FAIL" ? " Higgins' plain English didn't match it, so Apollo's own wording is shown." : ""),
  };
}

/** Every recorded event of the case, oldest first. Events at the same time keep the order the case runs in; an event
 *  with no recorded time comes after the rest. */
export function caseAuditTrail(input: {
  event: PatrolEvent; investigation: DeviceInvestigation | null; trace: DiTrace | null; records: DiTransaction[];
  /** The verdict the Findings Brief shows, when the case has one. */
  verdict: string | null;
}): AuditEntry[] {
  const { event, investigation, trace, records, verdict } = input;
  const caseId = event.investigation_case_id ?? event.patrol_record?.investigationCaseId ?? null;
  const triage = triageEntries(event);
  const entries: AuditEntry[] = [created(event), ...triage, ...evidenceAdded(event, investigation)];
  if (caseId) entries.push(...investigationEntries(event, investigation, trace, records));

  // Follow-up questions answered from the finished investigation's record.
  (investigation?.turns ?? []).slice(1).forEach((t, i) => entries.push({
    id: `followup-${i}`, at: t.committedAt, title: "Follow-up answered", tone: "check",
    description: `You asked: "${t.question}"`,
  }));

  const lock = caseId && investigation?.response ? lockEntry(investigation, trace, event) : null;
  if (lock) entries.push(lock);
  if (verdict?.trim()) {
    const at = lock ? lock.at : event.triage_investigation?.evaluatedAt ?? triage[triage.length - 1]?.at ?? event.occurred_at;
    entries.push({ id: "verdict", at, title: "Verdict recorded", description: `Verdict: ${verdict.trim()}.`, tone: "done" });
  }

  const block = event.verified_block ? event.enforcement_evidence : null;
  if (block) {
    entries.push({ id: "protection", at: block.observed_at, title: "Protection applied", tone: "done",
      description: `${MECHANISM[block.mechanism] ?? words(block.mechanism)}${block.destination_domain ? ` for ${block.destination_domain}` : ""}.` });
  }
  if (event.recovery_kinds?.length) {
    entries.push({ id: "recovery", at: null, title: "Recovery steps recorded", tone: "done",
      description: event.recovery_kinds.map((k) => RECOVERY[k] ?? words(k)).join(", ") });
  }
  // Every close and reopen, earlier ones included.
  const closes = [...new Set([event.previously_resolved_at, event.resolved_at].filter((t): t is string => !!t))];
  closes.forEach((at, i) => entries.push({ id: `closed-${i}`, at, title: "Case closed", tone: "closed",
    description: event.patrol_record?.resolution?.status && at === event.resolved_at ? `Status: ${words(event.patrol_record.resolution.status)}.` : "This case was closed." }));
  if (event.reopened_at) {
    entries.push({ id: "reopened", at: event.reopened_at, title: "Reopened by you", tone: "warning", description: "You reopened this case, so Apollo is tracking it again." });
  }
  if (caseId && !event.investigation_completed_at && !investigation?.response) {
    entries.push({ id: "pending", at: null, title: "Investigation in progress", tone: "check", pending: true, description: "Higgins hasn't finished investigating yet." });
  }

  const time = (e: AuditEntry) => (e.at && !Number.isNaN(Date.parse(e.at)) ? Date.parse(e.at) : Number.POSITIVE_INFINITY);
  return entries.map((e, i) => ({ e, i })).sort((a, b) => (time(a.e) - time(b.e)) || a.i - b.i).map(({ e }) => e);
}
