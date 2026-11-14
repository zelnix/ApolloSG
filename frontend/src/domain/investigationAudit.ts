import { HIGGINS_NAME } from "./higginsIdentity.ts";
import type { DiTrace, DiTransaction } from "./diTransaction.ts";
import type { TriageInvestigationRecord } from "./triage/contract.ts";
import { plainServiceText } from "./checkServicePresentation.ts";

export interface SlmStage {
  caseId: string; caseRevision?: number; requestId: string; role: string; operation?: string;
  observedAt?: string; requestedAt?: string | null; startedAt?: string; returnedAt?: string; acceptedAt?: string; failedAt?: string;
  status: "requested" | "running" | "returned" | "accepted" | "failed";
  output?: unknown; failure?: string; modelId?: string;
}
export interface InvestigationAudit { ownerId: string; caseId: string; deleted?: boolean; stages: SlmStage[]; trace?: DiTrace | null; records?: DiTransaction[] }
interface KV { getItem(key: string, fallback: string): Promise<string | null>; setItem(key: string, value: string): Promise<boolean> }
export interface AuditToken { ownerId: string; caseId: string; epoch: string; generation: number }

/** Injected storage/identity keeps ownership, deletion and late-write behavior testable without native modules. */
export function createInvestigationAudit(kv: KV, owner: () => Promise<string | null>) {
  let queue = Promise.resolve();
  let generation = 0;
  const listeners = new Set<() => void>();
  const serial = <T>(fn: () => Promise<T>): Promise<T> => { const work = queue.then(fn, fn); queue = work.then(() => undefined, () => undefined); return work; };
  const prefix = (id: string) => `apollo.investigation.audit.${id}.`;
  const read = async (key: string) => { try { return JSON.parse(await kv.getItem(key, "null") ?? "null"); } catch { return null; } };
  const write = async (key: string, value: unknown) => { if (!await kv.setItem(key, JSON.stringify(value))) throw new Error("Audit storage unavailable"); };
  const key = (t: AuditToken) => prefix(t.ownerId) + t.caseId;
  const valid = async (t: AuditToken) => t.generation === generation && await owner() === t.ownerId && (await kv.getItem(prefix(t.ownerId) + "epoch", "0") ?? "0") === t.epoch;
  const open = async (caseId: string): Promise<AuditToken | null> => {
    const openedGeneration = generation;
    const ownerId = await owner(); if (!ownerId || !caseId) return null;
    return { ownerId, caseId, generation: openedGeneration, epoch: await kv.getItem(prefix(ownerId) + "epoch", "0") ?? "0" };
  };
  const get = async (caseId: string): Promise<InvestigationAudit | null> => {
    const t = await open(caseId); if (!t) return null;
    const data = await read(key(t));
    return await valid(t) && data?.ownerId === t.ownerId && data.caseId === caseId && !data.deleted ? data : null;
  };
  const update = (t: AuditToken, fn: (data: InvestigationAudit) => InvestigationAudit) => serial(async () => {
    if (!await valid(t)) return;
    const previous = await read(key(t)); if (previous?.deleted) return;
    const data = previous ?? { ownerId: t.ownerId, caseId: t.caseId, stages: [] };
    if (data.ownerId !== t.ownerId || data.caseId !== t.caseId) return;
    const indexKey = prefix(t.ownerId) + "index";
    const index: string[] = await read(indexKey) ?? [];
    if (!index.includes(t.caseId)) await write(indexKey, [...index, t.caseId]);
    if (!await valid(t)) return;
    await write(key(t), fn(data)); listeners.forEach((fn) => fn());
  });
  return {
    open, get,
    async isCurrent(t: AuditToken) { return await valid(t) && !(await read(key(t)))?.deleted; },
    subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    stage(t: AuditToken, stage: SlmStage) {
      if (stage.caseId !== t.caseId) return Promise.resolve();
      return update(t, (data) => {
        const i = data.stages.findIndex((s) => s.requestId === stage.requestId && s.caseRevision === stage.caseRevision);
        const stages = [...data.stages]; if (i < 0) stages.push(stage); else stages[i] = { ...stages[i], ...stage };
        return { ...data, stages };
      });
    },
    snapshot(t: AuditToken, trace: DiTrace | null, records: DiTransaction[]) { return update(t, (data) => ({ ...data, trace, records })); },
    async remove(caseId: string) { const t = await open(caseId); if (!t) return; await serial(async () => {
      await write(key(t), { ownerId: t.ownerId, caseId, deleted: true, stages: [] }); listeners.forEach((fn) => fn());
    }); },
    async clear() { generation += 1; const id = await owner(); if (!id) return; await serial(async () => {
      const p = prefix(id); await kv.setItem(p + "epoch", String(Date.now()) + Math.random());
      const index: string[] = await read(p + "index") ?? [];
      for (const caseId of index) await write(p + caseId, { ownerId: id, caseId, deleted: true, stages: [] });
      listeners.forEach((fn) => fn());
    }); },
  };
}

export const SLM_ROLES: Record<string, string> = { wright_triage: "Wright triage", higgins_triage: "Higgins triage", tc_hawkeye: "TC Hawkeye reasoning", magnum_di: "Magnum DI reasoning", higgins_escalation_assessment: "Higgins escalation assessment", case_finding: "Finding preparation", luddish: "Explanation using Luddish", ask_higgins: "Ask Higgins" };
export function mergeSlmStages(remote: SlmStage[], local: SlmStage[]): SlmStage[] {
  const all = new Map<string, SlmStage>();
  for (const stage of [...remote, ...local]) {
    const key = `${stage.caseId}:${stage.requestId}`;
    const previous = all.get(key);
    const merged = { ...previous, ...stage };
    // Native output and server receipt can arrive in either order.
    merged.status = merged.acceptedAt ? "accepted" : merged.failedAt ? "failed" : merged.returnedAt ? "returned" : merged.startedAt ? "running" : "requested";
    all.set(key, merged);
  }
  return [...all.values()].sort((a, b) => (a.requestedAt ?? a.observedAt ?? "").localeCompare(b.requestedAt ?? b.observedAt ?? ""));
}
export function slmHistory(stages: SlmStage[]) {
  return stages.flatMap((s) => [
    [s.requestedAt, "requested", "A request was issued; this alone does not establish native execution."],
    [s.observedAt, "received on this device", "The device received this case’s request for Higgins."],
    [s.startedAt, "engaged", "Native inference was invoked for this stage."],
    [s.returnedAt, "returned output", "The stage returned output; this is not independent verification."],
    [s.acceptedAt, "output received by coordinator", "The handoff receipt was accepted; final Finding approval is separate."],
    [s.failedAt, "failed", s.failure ?? "No failure cause was recorded."],
  ].filter(([at]) => !!at).map(([at, action, body]) => ({ title: `${HIGGINS_NAME} — ${SLM_ROLES[s.role] ?? s.role} ${action}`, body: body!, at: at!, iconType: action === "failed" ? "failed" as const : "working" as const, entryKind: "process" as const })));
}

/** Actual engine records shared by case History and DI, including cases without a patrol event. */
export function engineHistory(trace: DiTrace | null, records: DiTransaction[], retainedTriage: TriageInvestigationRecord[] = []) {
  const entries: { title: string; body: string; at: string; iconType: "complete" | "failed"; entryKind: "process" }[] = [];
  const add = (title: string, body: string, at: string | null, failed = false) => entries.push({ title, body, at: at ?? "", iconType: failed ? "failed" : "complete", entryKind: "process" });
  if (trace?.flyby) add("TC Hawkeye checks recorded", trace.flyby.resolved ? "TC Hawkeye recorded a resolved result." : "TC Hawkeye's checks did not settle the case.", trace.flyby.ranAt);
  const seenTriage = new Set<string>();
  for (const triage of [...retainedTriage, ...(trace?.triage ? [trace.triage] : [])]) {
    const key = `${triage.investigationId}:${triage.evaluatedAt}`;
    if (seenTriage.has(key)) continue;
    seenTriage.add(key);
    add("Triage assessment recorded", plainServiceText(triage.reason), triage.evaluatedAt);
  }
  for (const record of records) {
    const failed = !!record.failureCode || (record.status ?? "success") !== "success";
    add(failed ? "Magnum DI did not finish" : "Magnum DI response recorded", record.failureCode ?? "The recorded transaction is available in DI.", record.occurredAt, failed);
  }
  if (!records.length && trace?.magnum) add("Magnum DI stage recorded", "The investigation recorded a Magnum DI stage.", trace.magnum.at);
  return entries;
}
