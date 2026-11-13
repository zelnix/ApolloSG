// Saving what ApolloSG's server kept for this phone, then telling the server it may delete its copy
// (backend services/device_pickup.py; owner's rules, 2026-11-01). In order: the finished result is committed, the
// original (its text, link and headers) is saved — enriching any copy already kept, never replacing it — both are
// read back from this phone's own storage, and only a complete copy is confirmed. Until then the server keeps its
// copy, however long this phone is offline. Runs for every case this phone knows (ApolloContext) and whenever a
// followed investigation answers (caseStore).
import * as api from "./client";
import { commitInvestigation, getInvestigation, recordServerCopyRemoved, saveEvidenceManifest, type DeviceInvestigation } from "./deviceStore";
import type { InvestigationCase } from "./types";
import { isEmailCase } from "@/src/domain/emailRecord";
import { missingParts, originalFromPickup, pickupIdentifiers, savedReport } from "@/src/domain/pickupCheck";
import { serverLeavesBy } from "@/src/domain/serverCopyNote";
import type { PatrolEvent } from "@/src/domain/types";
import { getOriginalSource, saveOriginalSource } from "@/src/store/originalSource";
import { storage } from "@/src/utils/storage";
import { getDeviceIdentity } from "@/src/auth/deviceIdentity";
import { archiveEvidence } from "./evidenceArchiveCore";
import { evidenceArchive } from "./evidenceArchive";

const DONE_KEY = "apollo.pickup.done.v1";
const DONE_MAX = 1000;
/** Cases this phone has finished with: confirmed, or the server keeps nothing for it. */
export async function pickupsDone(): Promise<string[]> {
  try { const parsed = JSON.parse((await storage.getItem<string | null>(DONE_KEY, null)) ?? "[]"); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}
export async function rememberPickups(caseIds: string[]): Promise<void> {
  const next = [...new Set([...(await pickupsDone()), ...caseIds])].slice(-DONE_MAX);
  await storage.setItem(DONE_KEY, JSON.stringify(next));
}

/** confirmed: the server was told and released its copy · nothing_held: it keeps nothing for this phone ·
 *  waiting: still being checked · incomplete: this phone's copy isn't complete yet, so nothing was confirmed. */
export type PickupOutcome = "confirmed" | "nothing_held" | "waiting" | "incomplete";

/** A finished answer this phone keeps as its saved result (a question still waiting, or a failed check, isn't one). */
export function needsResult(c: Pick<InvestigationCase, "response" | "status">): boolean {
  return !!c.response && !c.response.question && c.status !== "failed";
}

function snapshotOf(held: api.HeldCopy, question: string, ownerId: string): DeviceInvestigation {
  const c = held.case;
  return {
    ownerId, evidenceSnapshotId: held.snapshotId,
    caseId: c.id, gates: c.gates ?? [], status: c.status, createdAt: c.createdAt, completedAt: c.updatedAt,
    question: question || held.turns[0]?.question || "",
    response: c.response!, sources: held.sources, turns: held.turns, evidenceItems: held.evidence,
    patrolEventId: null, committedAt: new Date().toISOString(), answeredBy: c.answeredBy ?? null, settledReason: c.settledReason ?? null,
    ...(c.simulated ? { simulated: true } : {}),
    serverCopy: { removedAt: null, leavesBy: serverLeavesBy(c) },
    origin: c.origin ?? null,
  };
}

export async function pickUpCase(caseId: string, opts: { event?: PatrolEvent | null; question?: string } = {}): Promise<PickupOutcome> {
  const identity = await getDeviceIdentity();
  if (!identity) return "incomplete";
  const held = await api.getPickup(caseId);
  if (!held.held) {
    if (held.working) return "waiting";
    if (held.removedAt) await recordServerCopyRemoved(caseId, held.removedAt);
    // Nothing kept for this phone (a check cleaned before this rule): the server still says when its copy went.
    return "nothing_held";
  }
  // 1. The finished result.
  const wantResult = needsResult(held.case);
  const existing = await getInvestigation(caseId);
  if (wantResult && (existing?.response?.revision !== held.case.response!.revision || existing?.evidenceSnapshotId !== held.snapshotId)) {
    await commitInvestigation(snapshotOf(held, opts.question ?? "", identity.deviceId));
  }
  // 2. The original: what the server kept, with this phone's own record of the case filling any gap.
  const event = opts.event ?? null;
  const source = pickupIdentifiers(held.source, event?.source_metadata);
  const input = originalFromPickup(held.originals, source, { email: isEmailCase(event, null, held.case.gates), capturedAt: event?.occurred_at ?? held.case.createdAt });
  if (input) await saveOriginalSource([event?.event_id, caseId], input);
  // 3. Read both back from this phone's storage; confirm only a complete copy.
  const resultSaved = wantResult && (await getInvestigation(caseId))?.response?.revision === held.case.response!.revision;
  const report = savedReport(await getOriginalSource(caseId), held.originals, resultSaved);
  if (missingParts(report, { originals: held.originals, source: held.source ?? {} }, wantResult).length) return "incomplete";
  if (!held.snapshotId || !Array.isArray(held.evidenceContent)) return "incomplete";
  report.evidenceDigests = await archiveEvidence(held.evidenceContent, evidenceArchive(identity.deviceId, caseId),
    item => api.downloadPickupEvidence(caseId, held.snapshotId, item.evidenceId));
  await saveEvidenceManifest(caseId, { ownerId: identity.deviceId, snapshotId: held.snapshotId,
    items: held.evidenceContent, evidence: held.evidence });
  report.snapshotId = held.snapshotId;
  if ((await getDeviceIdentity())?.deviceId !== identity.deviceId) return "incomplete";
  const { purged, removedAt } = await api.confirmCommit(caseId, report);
  if (!purged) return "incomplete";
  if (removedAt) await recordServerCopyRemoved(caseId, removedAt);
  return "confirmed";
}
