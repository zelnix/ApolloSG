/**
 * Pure, testable event merge — reconciles local events with server records.
 *
 * This is the SINGLE function that determines the outcome of local + remote synchronisation.
 * It is imported by ApolloContext (production) and by regression tests (verification).
 *
 * Rules:
 * 1. Local content wins whenever this device holds its own full record: a DNS block, native protection or incomplete
 *    record is never replaced by the server's privacy-protected copy or summary.
 * 1b. Syncing never changes what supplied the evidence or where it was processed: the source and processing this
 *    device recorded are kept; the server's copy only fills in what this device didn't record.
 * 2. Server metadata is absorbed (patrol_record, investigation_case_id, etc.).
 * 3. Resolved/trusted events are never reopened unless the server carries genuinely new evidence
 *    (new enforcement_evidence.evidence_id not previously seen on this event).
 * 4. A server record with no local version (e.g. after a reinstall) is taken as-is. It is still this device's
 *    own case: records are per device, and server processing never changes where a case began.
 */
import type { PatrolEvent, SourceMetadata } from "./types";
import { evidenceModel } from "./evidenceModel.ts";
import { STATE_RANK } from "./stateMachine.ts";

const missingValue = (v: unknown) => v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length);
/** This device's recorded identifiers, with any it lacks filled in from the server's record. Never overwritten. */
export function enrichMetadata(local: SourceMetadata | null | undefined, remote: SourceMetadata | null | undefined): SourceMetadata | null | undefined {
  if (!local) return remote ?? local;
  if (!remote) return local;
  const out: Record<string, unknown> = { ...local };
  for (const [k, v] of Object.entries(remote)) if (missingValue(out[k]) && !missingValue(v)) out[k] = v;
  return out as unknown as SourceMetadata;
}

export interface MergeResult {
  events: PatrolEvent[];
  /** Event IDs that were superseded (local placeholder replaced by projected version). */
  superseded: string[];
}

export function mergeLocalAndRemoteEvents(
  localEvents: PatrolEvent[],
  remoteEvents: PatrolEvent[],
): MergeResult {
  const remoteById = new Map(remoteEvents.map((e) => [e.event_id, e]));
  const remoteBySubmission = new Map<string, string>();
  for (const re of remoteEvents) {
    if (re.client_submission_id) remoteBySubmission.set(re.client_submission_id, re.event_id);
  }
  const localById = new Map(localEvents.map((e) => [e.event_id, e]));

  const merged: PatrolEvent[] = [];
  const mergedIds = new Set<string>();
  const superseded: string[] = [];
  // One check, one record. A server twin — filed under its own id for a check this device recorded,
  // and naming that record as its client_submission_id — is the same check: it is folded into that
  // record (its investigation link and answer are kept) instead of being shown a second time.
  const twins = new Map<string, PatrolEvent>();

  // 1. Iterate remote events. For each, blend with local or take as-is.
  for (const remote of remoteEvents) {
    const twinOf = remote.client_submission_id && remote.client_submission_id !== remote.event_id ? remote.client_submission_id : null;
    if (twinOf && (localById.has(twinOf) || remoteById.has(twinOf))) {
      twins.set(twinOf, remote);
      superseded.push(remote.event_id);
      continue;
    }
    const local = localById.get(remote.event_id);
    if (local) {
      // Recorded on this device: local content WINS. Absorb only server metadata.
      const localModel = evidenceModel(local);
      const remoteModel = evidenceModel(remote);
      const localIsDetailed = localModel.representation === "full_record";

      // Lifecycle guard: local resolution is preserved unless genuinely new evidence exists.
      const localResolved = local.status === "resolved" || local.status === "trusted" || !!local.resolved_at;
      // Reopening requires genuinely new evidence observed AFTER the resolution time.
      // Two pathways:
      //
      // Pathway 1 — Enforcement: Different evidence_id with observed_at > resolved_at
      // (a fresh native block was observed for this event).
      //
      // Pathway 2 — Detection: The server sets detection_updated_at > resolved_at
      // (genuinely new detection evidence — new scan, new indicator, new threat intelligence —
      // without requiring a native block).
      //
      // Without either, the local resolution is preserved.
      const localEvidenceId = local.enforcement_evidence?.evidence_id;
      const remoteEvidenceId = remote.enforcement_evidence?.evidence_id;
      const remoteObservedAt = remote.enforcement_evidence?.observed_at;
      const localResolvedAt = local.resolved_at;
      const isDifferentEvidence = !!remoteEvidenceId && remoteEvidenceId !== localEvidenceId;
      const isObservedAfterHandling = !!remoteObservedAt && !!localResolvedAt
        && Date.parse(remoteObservedAt) > Date.parse(localResolvedAt);
      const hasNewEnforcementEvidence = isDifferentEvidence && isObservedAfterHandling;

      // Pathway 2: detection-only reopening
      const detectionUpdated = remote.detection_updated_at;
      const isDetectionAfterHandling = !!detectionUpdated && !!localResolvedAt
        && Date.parse(detectionUpdated) > Date.parse(localResolvedAt);
      const hasNewDetectionEvidence = isDetectionAfterHandling;

      const hasNewEvidence = hasNewEnforcementEvidence || hasNewDetectionEvidence;
      const preserveResolution = localResolved && !hasNewEvidence;
      // A user reopen newer than the server's resolution keeps the case open.
      const userReopened = !localResolved && !!local.reopened_at && !!remote.resolved_at
        && Date.parse(local.reopened_at) > Date.parse(remote.resolved_at);

      merged.push({
        ...local,
        // Preserve detailed local findings — never overwrite with privacy-projected server text.
        headline: localIsDetailed ? local.headline : remote.headline,
        what_happened: localIsDetailed ? local.what_happened : remote.what_happened,
        why: localIsDetailed ? local.why : remote.why,
        what_to_do: localIsDetailed ? local.what_to_do : remote.what_to_do,
        // Keep local-only fields. The record's identifiers (sender, subject, received date, text) are this device's
        // own where it recorded them; the server's copy fills in only what this device didn't record.
        source_metadata: enrichMetadata(local.source_metadata, remote.source_metadata),
        local_indicator: local.local_indicator ?? remote.local_indicator,
        origin: local.origin ?? remote.origin,
        claimed_brand: local.claimed_brand ?? remote.claimed_brand,
        scenario: local.scenario ?? remote.scenario,
        // Where the evidence came from and where it was processed never change in a sync.
        evidence_provenance: localModel.source ?? remoteModel.source ?? undefined,
        processing_source: localModel.processing ?? remoteModel.processing ?? undefined,
        // What the record holds follows the content kept: this device's own, else the server's copy.
        evidence_representation: (localIsDetailed ? localModel.representation : remoteModel.representation) ?? undefined,
        evidence_completeness: (localIsDetailed ? localModel.completeness : remoteModel.completeness) ?? undefined,
        evidence_gaps: localIsDetailed ? local.evidence_gaps : remote.evidence_gaps,
        // The case's origin never moves: the device that detected it.
        device_id: local.device_id,
        // Absorb server lifecycle metadata.
        patrol_record: remote.patrol_record ?? local.patrol_record,
        investigation_case_id: remote.investigation_case_id ?? local.investigation_case_id,
        // Either side can be the one that knows the investigation answered.
        investigation_completed_at: local.investigation_completed_at ?? remote.investigation_completed_at,
        client_submission_id: remote.client_submission_id ?? local.client_submission_id,
        // Lifecycle: preserve local resolution unless genuinely new evidence.
        status: preserveResolution || userReopened ? local.status : remote.status,
        // "sniffing" holds no assessment yet: any assessed state from the server replaces it.
        state: preserveResolution ? local.state
          : local.state === "sniffing" && remote.state !== "sniffing" ? remote.state
            : (STATE_RANK[remote.state] > STATE_RANK[local.state] ? remote.state : local.state),
        resolved_at: preserveResolution ? local.resolved_at : userReopened ? null : (hasNewEvidence ? null : (remote.resolved_at ?? local.resolved_at)),
        verified_block: remote.verified_block || local.verified_block,
        enforcement_evidence: remote.enforcement_evidence ?? local.enforcement_evidence,
        supporting_references: (local.supporting_references?.length ? local.supporting_references : remote.supporting_references),
      });
    } else {
      // No local version (e.g. after a reinstall): take the server's record as-is.
      merged.push(remote);
    }
    mergedIds.add(remote.event_id);
  }

  // 2. Add local-only events (not on server yet, or superseded placeholders).
  for (const local of localEvents) {
    if (mergedIds.has(local.event_id)) continue;
    // A twin of another record this device holds (it names that record as its client_submission_id)
    // is the same check: fold it in rather than show it again.
    const localTwinOf = local.client_submission_id && local.client_submission_id !== local.event_id
      && (localById.has(local.client_submission_id) || remoteById.has(local.client_submission_id)) ? local.client_submission_id : null;
    if (localTwinOf) {
      if (!twins.has(localTwinOf)) twins.set(localTwinOf, local);
      superseded.push(local.event_id);
      continue;
    }
    // Drop local placeholder superseded by projected version.
    if (local.client_submission_id && remoteBySubmission.has(local.client_submission_id) && local.event_id !== remoteBySubmission.get(local.client_submission_id)) {
      superseded.push(local.event_id);
      continue;
    }
    merged.push(local);
    mergedIds.add(local.event_id);
  }

  // 3. Fold each twin into the record it duplicates: keep what only the twin knows.
  for (const [recordId, twin] of twins) {
    const i = merged.findIndex((e) => e.event_id === recordId);
    if (i < 0) continue;
    const record = merged[i];
    merged[i] = {
      ...record,
      investigation_case_id: record.investigation_case_id ?? twin.investigation_case_id,
      investigation_completed_at: record.investigation_completed_at ?? twin.investigation_completed_at,
      patrol_record: record.patrol_record ?? twin.patrol_record,
    };
  }

  // Sort newest first.
  merged.sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));

  return { events: merged, superseded };
}
