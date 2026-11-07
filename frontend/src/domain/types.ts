// Shared Apollo domain types. Used by the state machine, risk engine, Patrol,
// capability model and privacy policy. Platform-agnostic: no React, no native.

// Six-state model. `sniffing` is transient (analysing), `ears_up` is a low-confidence pattern match,
// `biting` is the internal key for a confirmed protective block.
export type ApolloState = "sniffing" | "resting" | "ears_up" | "growling" | "barking" | "biting";

/** Semantically exact wording for each state. Never paraphrase these in the UI. */
/** User-facing state names. The internal key stays `resting`; on the lookout it reads as "Patrolling". */
/** Ordered low → high for comparisons in UI code (mirrors stateMachine STATE_RANK). */
export const STATE_RANK_ORDER: ApolloState[] = ["sniffing", "resting", "ears_up", "growling", "barking", "biting"];

export const STATE_NAME: Record<ApolloState, string> = { sniffing: "Checking", resting: "Patrolling", ears_up: "Sniffing", growling: "Growling", barking: "Barking", biting: "Biting" };

export const STATE_LABEL: Record<ApolloState, string> = {
  sniffing: "Apollo is sniffing",
  resting: "Apollo is Patrolling",
  ears_up: "Apollo is sniffing something",
  growling: "Apollo is growling",
  barking: "Apollo is barking",
  biting: "Apollo is biting",
};

export const STATE_MEANING: Record<ApolloState, string> = {
  sniffing: "The current checks are still running; no assessment is final yet.",
  resting: "No concern was identified within the checks that completed.",
  ears_up: "Apollo noticed something and is looking at it more closely.",
  growling: "A possible concern needs caution or further investigation.",
  barking: "A significant concern requires your attention.",
  biting: "An actual protective block was confirmed by device evidence.",
};

export type Visibility = "full" | "limited" | "none";

export type RiskLevel = "clean" | "uncertain" | "suspicious" | "malicious";

export interface RiskSignal {
  code: string;
  weight: number;
  plain: string; // plain-language explanation shown to the user
}

export interface LocalAnalysis {
  input: string;
  normalizedUrl: string | null;
  host: string | null;
  valid: boolean;
  score: number; // 0–100
  level: RiskLevel;
  signals: RiskSignal[];
}

export type IntelVerdict = "clean" | "malicious" | "unknown";
export type IntelCoverage = "full" | "partial" | "none";

export interface IntelSource {
  name: string;
  status: "match" | "clear" | "unavailable" | "not_configured";
  detail: string;
  threat_types: string[];
  /** What kind of check this source is — the person-facing wording follows completeness by check, never the provider. */
  check?: "reputation" | "final_destination";
  /** Why it didn't complete, when it didn't (timeout, quota_exhausted, nonexistent_domain, …). */
  failure?: string | null;
  /** The list's own page, so the person can see who flagged it (the entry's own page when the list has one). */
  url?: string | null;
}

/** RDAP domain lookup — best-effort, keyless registrar/registration-date context. Never gates the
 * verdict; `available: false` (or an absent object) just means no registration info could be shown. */
export interface DomainInfo {
  domain: string;
  registrar: string | null;
  registered_at: string | null;
  registrant_organization: string | null;
  rdap_server: string | null;
  age_days: number | null;
  newly_registered: boolean;
  available: boolean;
  error: string | null;
}

export interface IntelResult {
  redirect_chain?: string[];
  final_url?: string | null;
  verdict: IntelVerdict;
  threat_types: string[];
  sources: IntelSource[];
  indicator_digest: string;
  checked_at: string;
  cached: boolean;
  coverage: IntelCoverage;
  domain_info?: DomainInfo | null;
  /** Official Organisation Directory: an organisation's own website, or one using its name that isn't. Never changes the verdict. */
  official?: import("./officialContacts").OfficialVerdict | null;
}

export type EventCategory = "link" | "website" | "connection" | "known_threat" | "protection" | "system" | "message" | "call" | "app" | "device" | "account" | "email" | "file" | "family";
export type EventStatus = "active" | "trusted" | "blocked" | "resolved";
export type PatrolDisplayState = "safe" | "monitoring" | "warning" | "danger" | "blocked" | "resolved" | "unknown";

/** Record classification — separates threats from protection health */
export type RecordClass = "security_threat" | "threat_stopped" | "protection_issue" | "reduced_protection" | "diagnostic_result" | "informational" | "resolved" | "unverifiable_legacy";

export interface HigginsBriefing {
  investigated: string;
  established: string;
  evidence_points: string[];
  meaning: string;
  action: string | null;
  record_class: RecordClass;
  generated_at: string | null;
  version: string;
}

export interface PatrolRecord {
  recordId: string; logicalIssueKey: string; revision: number; supersedes: string | null; sourceEventId: string; sourceType: string;
  category: string; headline: string; summary: string; rawState: string; effectiveState: PatrolDisplayState; effectiveReason: string;
  observedBlockReference: string | null; assessmentReference: string | null; investigationCaseId: string | null;
  scenarioContext: { scenario?: string | null; claimedBrand?: string | null; indicatorHost?: string | null } | null;
  freshness: { observedAt: string; projectedAt: string; status: string }; outageContext: Record<string, unknown> | null;
  resolution: { status: string; resolvedAt: string | null } | null; duplicateOf: string | null; duplicateReason: string | null;
  occurredAt: string; updatedAt: string; event: PatrolEvent;
  /** Retrofit: approved record classification */
  recordClass?: RecordClass | null;
  /** Retrofit: Higgins briefing for this record */
  higginsBriefing?: HigginsBriefing | null;
  /** Retrofit: reassessment metadata — tracks migration provenance */
  reassessment?: Reassessment | null;
}

/** Retrofit reassessment metadata — how a legacy record was re-classified. */
export interface Reassessment {
  original_class: RecordClass | null;
  new_class: RecordClass;
  reassessed_at: string;
  reason: string;
  version: string;
}

/** What supplied a case's evidence. Never a server: processing is not an evidence source.
 *  - "local_device": Apollo's own check on this device.
 *  - "dns_observation": Apollo's DNS filter on this device.
 *  - "native_protection": the device's built-in protection (named in `source_metadata.provider`).
 *  - "device_submission": this device sent the item for checking (a check, a captured notification, Ask Higgins).
 *  - "connected_mailbox": the mailbox this device connected (named in `source_metadata.provider`). */
export type EvidenceSource = "local_device" | "dns_observation" | "native_protection" | "device_submission" | "connected_mailbox";
/** Where Apollo's checks on a record ran. */
export type ProcessingSource = "this_device" | "apollosg_servers";
/** "partial": part of the evidence the checks needed is missing. Missing evidence is never evidence of a threat. */
export type EvidenceCompleteness = "complete" | "partial";
/** The privacy state of what a record holds: this device's full record, the privacy-protected copy ApolloSG's servers
 *  worked from, or only the privacy-protected summary (the kind of check and its result). */
export type EvidenceRepresentation = "full_record" | "privacy_protected_copy" | "privacy_summary";

export interface PatrolEvent {
  event_id: string;
  /** The case's origin: the device that detected it. Server processing, Magnum DI, syncing, privacy projection and
   *  missing evidence never change it. A detection on a second device is that device's own case. */
  device_id: string;
  category: EventCategory;
  state: ApolloState;
  status: EventStatus;
  headline: string;
  what_happened: string;
  why: string[];
  what_to_do: string;
  indicator_host: string | null;
  indicator_digest: string | null;
  /** Full indicator (e.g. the link) — kept ON DEVICE ONLY, never synced. */
  local_indicator?: string | null;
  /** Safe public references supporting the local assessment. Raw submitted links are excluded. */
  supporting_references?: { label: string; url: string }[];
  verified_block: boolean;
  /** Where the evidence came from — the answer to "Where did this evidence come from?" and nothing else. Set when the
   *  evidence is recorded and never changed by processing, syncing, privacy transformation or storage. It is not the
   *  case's origin (`device_id`), not what processed it (`processing_source`), not how complete it is
   *  (`evidence_completeness`) and not its privacy state (`evidence_representation`). Server processing is never an
   *  evidence source. Records stored before this model may hold "server_projected" or "incomplete";
   *  src/domain/evidenceModel.ts reads those into the separated fields. */
  evidence_provenance?: EvidenceSource;
  /** Where Apollo's checks on this record ran. Never moves the case's origin. */
  processing_source?: ProcessingSource;
  /** Whether part of the evidence its checks needed is missing; each gap carries its recorded reason. */
  evidence_completeness?: EvidenceCompleteness;
  /** Recorded gaps outside the Triage record (e.g. a block claim the packet truth gate couldn't verify). */
  evidence_gaps?: import("./triage/completeness").IncompleteCheck[] | null;
  /** The privacy state of what this record holds. */
  evidence_representation?: EvidenceRepresentation;
  adapter_label: string;
  occurred_at: string;
  resolved_at: string | null;
  /** Set when the user reopened a case they had marked contained/handled (wins over an older server resolution). */
  reopened_at?: string | null;
  /** The resolution time a reopen cleared — kept so History still records that the case was closed. */
  previously_resolved_at?: string | null;
  /** Set by the server when genuinely new detection evidence arrives for a previously resolved event.
   *  Used by the merge to distinguish fresh detection from stale server state. The client never sets this. */
  detection_updated_at?: string | null;
  /** Set by the native Site Guard when the block happened with the app closed → backend pushes an alert to this device. */
  background?: boolean;
  /** Gate 2 (messages): extracted security signals only — never the conversation. */
  claimed_brand?: string | null;
  scenario?: string | null;
  /** Threat Scent id linking related events (message → link → login → call). */
  scent_id?: string | null;
  /** Stable case identity for repeat checks on the same subject. Events sharing a case_key are ONE
   *  case in Threats (latest shown), while each event remains its own entry in patrol history.
   *  Used by device checks so a recheck after a fix doesn't open a second case. */
  case_key?: string | null;
  /** Whether "Trust This" may be offered. Only growling-level uncertain items. */
  trust_allowed?: boolean;
  /** Cross-Platform Architecture Directive: raw enforcement evidence backing verified_block, if any.
   * The backend independently re-derives verified_block from this — it is never trusted as-is. */
  enforcement_evidence?: PatrolEnforcementEvidence | null;
  /** Structured user-reported recovery actions. New records use this instead of parsing display text. */
  recovery_kinds?: string[];
  /** Owner-validated server association for continuing this event after remount or device refresh. */
  investigation_case_id?: string | null;
  /** When Magnum DI's answer for `investigation_case_id` was committed to this device. Device-local:
   *  the device holds the result, so only it can say the investigation has finished. While this is
   *  absent the case is genuinely still being investigated. */
  investigation_completed_at?: string | null;
  /** Who settled that investigation: "magnum_di" or a TC Hawkeye route ("tc_flyby_official", "tc_flyby_kb",
   *  "tc_flyby_search"). Device-local, copied from the committed result; absent when not recorded. */
  investigation_answered_by?: string | null;
  /** The outcome the case's investigation recorded (no_scam_indicators … unable_to_determine), never guessed. */
  investigation_outcome?: string | null;
  /** An outside source behind that investigation was simulated in the preview (copied from the committed result).
   *  Device-local. Everything else ran exactly as in production; this only tags the case. */
  investigation_simulated?: boolean;
  /** Who started this case, recorded when it was filed: the person submitted it ("user"), Apollo detected it
   *  ("apollo"), or it was a Sample Check exercising the production pipeline ("sample_check").
   *  Device-local. Absent on records filed before it was recorded — never inferred. */
  origin?: "user" | "apollo" | "sample_check" | null;
  /** Server-owned correlation: links a background-intake submission to its projected Patrol event.
   * Set by the investigation projector; the frontend sets it on local placeholder events for
   * reconciliation. When the server supplies a value, it is authoritative and supersedes the local
   * placeholder (see remote merge effect in ApolloContext). */
  client_submission_id?: string | null;
  /** Server-owned immutable Patrol projection. Consumer history must prefer this when present. */
  patrol_record?: PatrolRecord;
  /** Source metadata — actual recorded identifiers from intake, NOT Gemini-inferred.
   *  Used by the Original Item Summary to show what was investigated. */
  source_metadata?: SourceMetadata | null;
  /** The completed deterministic Triage Investigation for this item: rules applicable, rules
   *  checked, results, evidence, coverage gaps, retries, correlation and the final outcome.
   *  Present for every outcome — No Threat, Possible Threat and Limited alike. */
  triage_investigation?: import("./triage/contract").TriageInvestigationRecord | null;
  /** Earlier Triage records for this same item, oldest first — kept when new evidence (e.g. the original email)
   *  re-ran Triage, so the case never loses how it was assessed before. Device-local. */
  triage_history?: import("./triage/contract").TriageInvestigationRecord[] | null;
  /** Higgins Triage's classification of the evidence it received (email: L1–L4; link: as given → followed), what it
   *  could examine, the signals it raised and every level the case has had. Device-local: never part of the Patrol sync payload. */
  evidence_profile?: import("./triage/evidenceProfile").EvidenceProfile | null;
  /** Telephone/mobile numbers found in this case's ORIGINAL EVIDENCE and exactly what the reputation
   *  service returned for each. Device-local: numbers are never part of the Patrol sync payload
   *  (see patrolPayload). */
  evidence_phones?: import("./phoneNumbers").EvidencePhoneResult[] | null;
  /** The case's Higgins Case Briefing, projected for Home, Threats and notifications (src/domain/caseBriefing.ts).
   *  Device-local: it names the subject, so it is never part of the Patrol sync payload (see patrolPayload). */
  case_briefing?: import("./caseBriefing").EventBriefing | null;
}

/** Recorded identifiers from the original submitted item. Every field is actual
 *  intake data — never reconstructed by Gemini. */
export interface SourceMetadata {
  type: "email" | "text" | "screenshot" | "link" | "call" | "app" | "file" | "account" | "device" | "network";
  // Email fields
  sender?: string | null;
  subject?: string | null;
  received_at?: string | null;
  reply_to?: string | null;
  attachment_count?: number | null;
  attachment_names?: string[] | null;
  auth_passed?: boolean | null;
  link_count?: number | null;
  provider?: string | null;
  /** The actual mailbox account email address (e.g. "user@gmail.com"), available when the
   *  case was created by a connected-mailbox monitor scan. */
  account?: string | null;
  // Text/SMS fields
  preview?: string | null;
  content_complete?: boolean | null;
  // Native protection attribution — the OS/OEM provider's OWN classification of this call or
  // message. Recorded verbatim so a Samsung/Google/carrier finding is never read as Apollo's.
  provider_classification?: string | null;
  provider_confidence?: string | null;
  // Screenshot/image fields
  image_count?: number | null;
  user_question?: string | null;
  // Link fields
  url?: string | null;
  // General
  submitted_at?: string | null;
}

/**
 * Backend-facing (snake_case, flat) mirror of src/security/PlatformCapabilityProfile.ts
 * EnforcementEvidence — see toPatrolEnforcementEvidence() in enforcementEvidenceSync.ts for the
 * camelCase→snake_case, nested→flat conversion at the SDK/domain boundary.
 */
export interface PatrolEnforcementEvidence {
  evidence_id: string;
  event_id: string | null;
  device_id: string | null;
  platform: string;
  os_version: string | null;
  sdk_version: string | null;
  observed_at: string;
  mechanism: string;
  direction: string;
  protocol: string;
  destination_ip: string | null;
  destination_domain: string | null;
  destination_port: number | null;
  app_id: string | null;
  process_name: string | null;
  attribution_confidence: string;
  matched_rule_id: string | null;
  threat_id: string | null;
  requested_action: string;
  enforced_action: string;
  result: string;
  rule_source: string;
  confidence: string;
  correlation_id: string | null;
}

export type CapabilityStatus = "available" | "active" | "permission_required" | "unsupported" | "coming_later" | "inactive";

export interface Capability {
  id: "link_guard" | "site_guard" | "connection_guard" | "known_threats" | "share_intake" | "message_guard" | "app_guard";
  title: string;
  status: CapabilityStatus;
  detail: string; // truthful, plain-language reason for the status
}

export interface Decision {
  state: ApolloState;
  headline: string;
  what_happened: string;
  why: string[];
  what_to_do: string;
  action_required: boolean;
  trust_allowed: boolean;
  block_offered: boolean;
  confidence: "low" | "medium" | "high";
  /** Gate 3: organisation the destination claims/looks like (Brand & Impersonation engine). */
  claimed_brand?: string | null;
}

// ── DNS Threat Observation (separate from enforcement evidence) ──────────

/**
 * A genuine DNS-level threat observation — produced when a DNS query for a hostname
 * matching an active BLOCK rule is intercepted and answered with a sinkhole address.
 *
 * This is a DETECTION, not enforcement. The observation MUST NOT claim a block occurred.
 * It says: "Apollo observed a DNS query for a known-dangerous hostname and redirected
 * the answer to a sinkhole."
 */
export interface DnsThreatObservation {
  observationId: string;
  hostname: string;
  ruleId: string | null;
  rulesetId: string | null;
  observedAt: string;
  decision: "block";
  sinkholeIpv4: string | null;
  coverageScope: string;
  evidenceType: "dns_observation";
}

/**
 * How Private DNS is set, as far as Android tells Apollo (read from the physical network, never
 * Apollo's own tunnel). `not_in_use` = Off, or Automatic on a network that doesn't support it —
 * Android can't tell those apart when its own setting isn't readable, so it is never shown as "off".
 */
export type PrivateDnsMode = "off" | "automatic" | "hostname" | "not_in_use" | "unknown" | "unsupported";

/**
 * Private DNS / DoH gap detection status. Identifies when Apollo's website protection
 * is reduced because DNS queries bypass the virtual DNS gateway.
 */
export interface PrivateDnsStatus {
  /** True if Android's Private DNS is active (DoT to an encrypted provider). */
  privateDnsActive: boolean;
  /** The configured Private DNS server name (e.g. "dns.google"), or null for "Automatic". */
  privateDnsServer: string | null;
  /** How Private DNS is set. Absent from builds that predate the mode read. */
  mode?: PrivateDnsMode;
  /** Where `mode` came from: Android's own setting, or only the network's current Private DNS state. */
  modeSource?: "android_setting" | "network_state" | null;
  /** "confirmed" = a provider hostname sends lookups past Apollo, "none" = Apollo sees them, "unobservable" = cannot determine. */
  bypassLevel: "confirmed" | "none" | "unobservable";
  /** Chrome DoH is always "unobservable" — no Android API exposes Chrome's internal DNS config. */
  chromeDoH: "unobservable";
  /** Plain-English explanation for Higgins / protection details. */
  explanation: string;
}
