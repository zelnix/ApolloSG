// Generated-equivalent wire types for the shared investigation case (backend/services/higgins/contracts.py, spec §4/§8).
export type Gate = "site" | "link" | "text" | "call" | "network" | "account" | "email" | "app" | "file" | "device";
export type CaseStatus = "queued" | "investigating" | "waiting_device" | "waiting_user" | "retry_wait" | "partial" | "complete" | "failed" | "cancelled" | "expired";
export type CoverageStatus = "not_started" | "partial" | "examined" | "unavailable" | "out_of_scope";
export type Assessment = "concern_found" | "no_concern_found_within_scope" | "uncertain";
/** Apollo's case Finding — the four Findings, plus legacy codes for backward compatibility. */
export type Outcome = "scam" | "not_scam" | "likely_scam" | "unable_to_determine"
  | "no_scam_indicators" | "concerning" | "confirmed_threat";
export type Attention = "none" | "review" | "action_needed" | "urgent";
export type Completion = "complete" | "partial" | "waiting_user";

export interface Coverage { status: CoverageStatus; unit: "bytes" | "characters" | "pages" | "items"; total: number | null; examined: number; examinedRanges: { start: number; end: number }[]; omittedRanges: { start: number; end: number; reason: string }[]; reason: string | null; materialGap: boolean }
export interface EvidenceProvenance { acquisitionMethod: string; sourceDescription: string; originalFilename: string | null }
export interface EvidenceItem { id: string; caseId: string; clientItemId: string; displayId: string; origin: "user_submission" | "device_observation" | "external_source" | "apollo_inference"; kind: string; parentId: string | null; availability: "available" | "unavailable" | "permission_required" | "purged" | "content_expired"; mediaType: string | null; byteLength: number | null; integrityHash: string | null; provenance: EvidenceProvenance | null; coverage: Coverage; simulation: { kind: "preview_device"; label: string; fixtureId: string } | null; transformations: { kind: string; description: string }[]; label: string; expiresAt: string; collectedAt?: string }
export interface SourceReference { id: string; url: string; title: string; retrievedAt: string; retrieval: "fetched" | "search_result" | "unavailable"; authority: "official" | "independent" | "self_claimed" | "unknown"; authorityBasis: string; reused?: boolean }
export interface Finding { id: string; text: string; basis: "observation" | "user_report" | "inference"; confidence: "low" | "medium" | "high"; evidenceIds: string[]; sourceIds: string[] }
export interface Question { id: string; text: string; reasonNeeded: string; answerType: "text" | "yes_no" | "choice"; choices: string[] }
export interface ActionProposal { id: string; kind: "instruction" | "open_settings" | "request_permission" | "recheck" | "open_verified_source"; label: string; instruction: string; capabilityId: string | null; executionDescriptorId: string | null; requiresUserGesture: boolean; sourceIds: string[]; desiredField: string | null; desiredValue: boolean | string | null }
export interface PlainItem { text: string; detail: string; explain: string; findingId: string | null }
export interface FidelityFailure { code: string; ref: string; detail: string }
/** Higgins' plain English of a validated result (backend services/higgins/explain), checked against it before it
 *  is shown. "literal" = it failed its Fidelity Check, so Apollo's own wording is shown instead. */
export interface PlainEnglish { version: 1; renderer: "apollo"; mode: "plain" | "repaired" | "literal"; result: string; severity: string; /** What it is: the case's subject in one fixed line. */ subject?: string; established: PlainItem[]; means: string[]; matters: string[]; todo: string[]; uncertain: string[]; how: string[]; fidelity: { status: "PASS" | "FAIL"; failures: FidelityFailure[] }; attempts: number; attemptFailures: FidelityFailure[][] }
/** One material finding: Subject → Check → Result, in the words shown (backend contracts.BriefingFinding). */
export interface BriefingFinding { id: string; subject: string | null; subjectType: string | null; organisation: string | null; /** The organisation is only named; the subject isn't its. */ organisationClaimed?: boolean; check: string; result: string; finding: string; evidenceIds: string[]; sourceIds: string[]; materiality: "material" | "context"; confidence: string; basis: string; stance: "supporting" | "contrary" | "context" }
/** The Higgins Case Briefing (backend services/higgins/explain/briefing.py): the one authoritative summary Home, Threats,
 *  the Overview and notifications all project. "Needs you" only when userActionRequired and a concrete actionReason. */
export interface CaseBriefing { version: 1; subject: { value: string; type: string; organisation: string | null; organisationClaimed?: boolean } | null; headline: string; summary: string; findings: BriefingFinding[]; supporting: string[]; contrary: string[]; unresolved: string[]; status: string; statusCode: string | null; attention: string; statusReason: string; userActionRequired: boolean; actionReason: string | null; recommendedAction: { label: string; instruction: string } | null; fidelity: { status: "PASS" | "FAIL"; failures: FidelityFailure[] } }
export interface HigginsResponse { revision: number; overview: string; explanationMarkdown: string; assessment: Assessment; outcome?: Outcome | null; attention: Attention; attentionReason: string | null; findings: Finding[]; uncertainties: string[]; scope: string; sourceIds: string[]; remainingEvidenceIds: string[]; actions: ActionProposal[]; recommendedActionId: string | null; question: Question | null; completion: Completion; plainEnglish?: PlainEnglish | null; briefing?: CaseBriefing | null; history?: HistoryNote[]; /** Null/absent: recorded before the Evidence record existed (never reconstructed). */ evidence?: EvidenceFact[] | null; /** TC Hawkeye's own Findings Rating (0-100, Apollo PRD v2.2 §2) and its six-dimension breakdown. Null for a general question / no Finding. */ findingsRating?: number | null; findingsRatingBreakdown?: FindingsRatingBreakdown | null; /** TC Hawkeye-only: a reputation check failed or timed out after retrying, so no Finding was reached. */ technicalFailure?: boolean | null; /** The Master Scam Taxonomy classification (Apollo PRD v2.2 Phase 2). Null for a "not a scam" result, a general question or no Finding. */ taxonomy?: TaxonomyClassification | null; /** The Higgins Findings Brief, the same Finding under its six required headers (Apollo PRD v2.2 Phase 5). Null for no Finding. */ findingsBrief?: FindingsBrief | null }
/** One check TC Hawkeye actually ran that a dimension's points draw on (backend's own Check record — never a client-side guess). */
export interface DimensionCheck { kind: string; subject: string; status: string }
/** One dimension of the Findings Rating (backend services.higgins.tc_flyby.scoring.DimensionScore). checks/evidence/missing
 *  are the real trace behind `points` — DI Scoring Transparency (Apollo PRD v2.3): missing evidence is listed as missing,
 *  never shown as if it were confirmed clean. */
export interface FindingsRatingDimension {
  key: string; label: string; points: number; max: number; why: string;
  /** The checks (link/phone/email/impersonation/etc.) this dimension's points actually drew on. */
  checks: DimensionCheck[];
  /** The real evidence text behind this dimension's points — never fabricated, never paraphrased. */
  evidence: string[];
  /** Checks this dimension could have used but that were unavailable — listed as unavailable, not as a clean result. */
  missing: string[];
}
/** One step of the exact arithmetic TC Hawkeye's scorer ran, in order (backend never recomputes this on request — the UI
 *  renders it verbatim). */
export interface ScoreCalculationStep { step: string; detail: string; value: number }
export interface FindingsRatingBreakdown {
  rating: number; finding: string; dimensions: FindingsRatingDimension[]; baseline: number; benignBaselineApplied: boolean;
  /** The specific, evidence-backed reason the benign floor fired (empty when it didn't) — never a generic phrase alone. */
  benignBaselineTrigger: string;
  legitimacyCredit: number; legitimacyReason: string; decisiveFloorApplied: boolean; decisiveMechanism: string | null;
  /** The ordered, human-readable trace of exactly how the 0-100 rating was calculated. */
  calculationTrace: ScoreCalculationStep[];
  /** Higgins' own plain-English account of the rating, composed only from the structured breakdown above. */
  narrative: string;
  /** Material TC Hawkeye couldn't read at all (PRD completeness) — distinct from "missing" per-dimension checks. */
  contentGaps: string[];
  /** Unified Evidence Classification PRD §5.1/§7.2 — the calculated six-dimension rating before any
   *  evidence-verdict alignment. Equal to `rating` whenever the evidence verdict and the calculated
   *  score already agreed. */
  rawRating: number;
  /** Why `rating` was nudged away from `rawRating` to match the evidence verdict's band — empty when it wasn't. */
  adjustmentReason: string;
  /** The S/N/L rule id(s) (e.g. ["S2"], ["N1","N2"]) that established the evidence verdict shown as `finding`. */
  verdictRuleIds: string[];
}
/** A master domain reference, without its variant code (backend services.higgins.tc_flyby.taxonomy). */
export interface TaxonomyDomainRef { domainCode: number; domainName: string }
/** The specific Operational Variant Code (001-1000) that settled the classification. */
export interface TaxonomyVariant extends TaxonomyDomainRef { variantCode: string; label: string }
/** The Master Scam Taxonomy classification for one case: one primary domain, zero or more secondary domains when the mechanism spans more than one (Apollo PRD v2.2 Phase 2). */
export interface TaxonomyClassification { primary: TaxonomyVariant; secondaryDomains: TaxonomyDomainRef[] }
/** A recommended action as it appears inside a Findings Brief — before the server hydrates it into a full ActionProposal. */
export interface BriefAction { kind: string; label: string; instruction: string; capabilityId: string | null; sourceIds: string[]; desiredField: string | null; desiredValue: boolean | string | null }
/** The Higgins Findings Brief (Apollo PRD v2.2 Phase 5): the same Finding, under its six required headers. */
export interface FindingsBrief { finding: string; findingsRating: number; whatApolloFound: string[]; whyThisMatters: string; whatWasVerified: { summary: string; limitations: string[] }; recommendedAction: { primary: BriefAction | null; additional: BriefAction[] }; taxonomy: TaxonomyClassification | null }
/** Who established a fact, in the order the investigation runs. */
export type EvidenceStage = "higgins_triage" | "tc_flyby" | "magnum_di";
/** One material fact the case established (backend services/higgins/case_evidence.py): listed once, with the stage that
 *  found it first and the later stages that established it too. stance is relative to the outcome. */
export interface EvidenceFact { id: string; text: string; stance: "supporting" | "contrary" | "neutral"; discoveredBy: EvidenceStage; corroboratedBy: EvidenceStage[]; weak: boolean; basis: "observation" | "user_report" | "inference"; confidence: "low" | "medium" | "high" | null; evidenceIds: string[]; sourceIds: string[]; findingIds: string[]; ruleId: string | null; establishedAt: string | null; simulated: boolean }
/** Related history beside a result (backend services/higgins/history.py): one of THIS device's own earlier cases, or a
 *  previous encounter in concerning material (never which device or how many). Context, never evidence: it never
 *  changes the verdict or a finding — only, when it agrees with a concern, the confidence of the findings it lists. */
export interface HistoryNote { kind: "previously_encountered" | "related_case"; match: "website" | "number" | "email" | "message" | "file" | "organisation" | "connected"; text: string; source: string; agrees: boolean; subject: string | null; eventId: string | null; at: string | null; outcome: string | null; findingIds: string[] }
export interface Inventory { total: number; examined: number; partial: number; unavailable: number; purged: number; contentExpired: number }
export interface InvestigationCase { schemaVersion: 1; id: string; revision: number; gates: Gate[]; status: CaseStatus; createdAt: string; updatedAt: string; expiresAt: string; evidenceExpiresAt: string | null; reportExpiresAt: string | null; retentionClass: string; reportByteSize: number; response: HigginsResponse | null; activeJobId: string | null; pendingDeviceRequestIds: string[]; inventory: Inventory; cleanupStatus: "not_due" | "pending" | "complete" | "failed"; answeredBy?: string | null; settledReason?: SettledReason | null; contentDeleteBy?: string | null; simulated?: boolean; origin?: CaseOrigin | null }
/** Who started an investigation, as recorded when it was opened. Absent when the record doesn't say — never inferred. */
export type CaseOrigin = "user" | "apollo" | "sample_check";
/** The rule that settled a result, as one plain sentence (backend services/rulebook.py; listed in the rule book). */
export interface SettledReason { ruleId: string; rule: string; by: "TC Hawkeye" | "Magnum DI"; sentence: string }
export interface Failure { code: string; message: string; retryable: boolean; retryAfterSeconds: number | null; resubmitAt?: string | null; missingEvidenceIds: string[] }
export interface Job { id: string; caseId: string; turnId: string; status: CaseStatus; startedAt: string | null; deadlineAt: string; retryAt: string | null; attempt: number; lastEventSequence: number; failure: Failure | null }
export type UnavailableReason = "not_implemented" | "os_restricted" | "hardware_absent" | "configuration_missing" | "entitlement_missing" | "privacy_prohibited" | "source_refused" | "adapter_failed";
export interface DeviceProfile { platform: "android" | "ios" | "windows" | "macos" | "web"; manufacturer: string | null; model: string | null; osVersion: string | null; formFactor: "phone" | "tablet" | "desktop" | "laptop" | "convertible" | "unknown"; locale: string; evidenceOrigin: "native" | "user_reported" | "browser"; capabilityIds: string[] }
export interface DeviceRequest { id: string; caseId: string; caseRevision: number; capabilityId: string; fields: string[]; reason: string; expiresAt: string }
export interface DeviceResult { requestId: string; caseRevision: number; capabilityId: string; status: "observed" | "unavailable" | "permission_required" | "denied" | "failed"; observedAt: string | null; values: Record<string, string | number | boolean | string[] | null>; simulation: { kind: "preview_device"; label: string; fixtureId: string } | null; unavailableReason: UnavailableReason | null }
export interface TurnCommit { turnId: string; caseId: string; inputRevision: number; committedRevision: number; question: string; answerToQuestionId: string | null; response: HigginsResponse; committedAt: string }
export interface Submission { clientItemId: string; kind: "text" | "url"; value: string; label?: string }
export interface CreateCase { gate: Gate | null; question: string; submissions: Submission[]; initialFindingRefs: string[]; initialFindings: string[]; deviceProfile: DeviceProfile | null; origin?: CaseOrigin; /** The check's own Threats record: the case updates it, never files a second one. */ patrolEventId?: string | null }

export type InvestigationEvent =
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "progress"; payload: { phase: "ingest" | "observe" | "research" | "assess" | "respond"; message: string } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "device_request"; payload: DeviceRequest }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "question"; payload: Question }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "response"; payload: { response: HigginsResponse; sources: SourceReference[] } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "retry_scheduled"; payload: { retryAt: string; failure: Failure } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "completed"; payload: { turnId: string; responseRevision: number; providerComplete: true; completion: Completion; caseStatus: CaseStatus; cleanupStatus: string } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "partial"; payload: { responseRevision: number | null; reason: Failure; canContinue: boolean } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "failed"; payload: Failure }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "cancelled"; payload: { cleanupStatus: string } }
  | { sequence: number; jobId: string; caseId: string; revision: number; at: string; type: "expired"; payload: { missingEvidenceIds: string[]; cleanupStatus: string } };
