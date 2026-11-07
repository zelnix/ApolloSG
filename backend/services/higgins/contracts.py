"""Authoritative wire contracts for the shared investigation case (spec §4, §8).

Strict models: unknown fields are rejected. camelCase on the wire, snake_case in code.
IDs are opaque server-issued UUIDs; timestamps are UTC ISO 8601.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

Gate = Literal["site", "link", "text", "call", "network", "account", "email", "app", "file", "device", "vision"]
CaseStatus = Literal["queued", "investigating", "waiting_device", "waiting_user", "retry_wait", "partial", "complete", "failed", "cancelled", "expired"]
Origin = Literal["user_submission", "device_observation", "external_source", "apollo_inference"]
CoverageStatus = Literal["not_started", "partial", "examined", "unavailable", "out_of_scope"]
Assessment = Literal["concern_found", "no_concern_found_within_scope", "uncertain"]
# Apollo's case Finding (services/higgins/outcomes.py), shared by TC Hawkeye and Magnum DI.
# Current findings: scam, not_scam, likely_scam, unlikely_scam
# Legacy codes (confirmed_threat, no_scam_indicators, concerning, unable_to_determine) accepted for
# backward compatibility with records stored before the Findings Rating (unable_to_determine now
# normalizes to unlikely_scam — see outcomes.LEGACY_MAP).
Outcome = Literal["scam", "not_scam", "likely_scam", "unlikely_scam",
                  "no_scam_indicators", "concerning", "confirmed_threat", "unable_to_determine"]
Attention = Literal["none", "review", "action_needed", "urgent"]
Completion = Literal["complete", "partial", "waiting_user"]
FailureCode = Literal["invalid_input", "unauthenticated", "not_found", "conflict", "provider_configuration", "rate_limited",
                      "provider_unavailable", "transport_interrupted", "incomplete_output", "unsupported_format", "evidence_expired",
                      "budget_exhausted", "device_unavailable", "permission_denied", "response_invalid", "cleanup_failed",
                      "evidence_too_large", "budget_limit"]
EvidenceKind = Literal["text", "url", "image", "document", "audio", "attachment", "observation", "source_snapshot"]
Platform = Literal["android", "ios", "windows", "macos", "web"]
UUID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,79}$"


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class Range(Wire):
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class OmittedRange(Range):
    reason: str


class Coverage(Wire):
    status: CoverageStatus = "not_started"
    unit: Literal["bytes", "characters", "pages", "items"] = "characters"
    total: Optional[int] = None
    examined: int = 0
    examined_ranges: list[Range] = Field(default_factory=list)
    omitted_ranges: list[OmittedRange] = Field(default_factory=list)
    reason: Optional[str] = None
    material_gap: bool = False
    # Set ONLY at ingestion, for a limitation that reading more of what was retained can never resolve (truncation,
    # parser failure, an unsupported format, ...). `material_gap` above is recomputed on every read as "not yet fully
    # read"; this field is the durable signal that survives those recomputations, so a genuine ingestion-time gap is
    # never mistaken as resolved just because the (already limited) retained content was read in full.
    permanent_gap: bool = False


class Simulation(Wire):
    kind: Literal["preview_device"] = "preview_device"
    label: str
    fixture_id: str


class Transformation(Wire):
    kind: Literal["secret_redaction", "ocr", "decode", "chunk", "normalise", "privacy_note", "privacy_screening", "image_resize"]
    description: str
    source_start: Optional[int] = None
    source_end: Optional[int] = None


class EvidenceProvenance(Wire):
    acquisition_method: Literal["user_upload", "user_text", "device_observation", "external_fetch", "vision_screening", "ocr_extraction", "derived"] = "user_text"
    source_description: str = ""
    original_filename: Optional[str] = None


class EvidenceItem(Wire):
    id: str
    case_id: str
    client_item_id: str
    display_id: str = ""  # Human-readable: "E-001", "E-002"
    origin: Origin
    kind: EvidenceKind
    parent_id: Optional[str] = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    collected_at: datetime
    observed_at: Optional[datetime] = None
    expires_at: datetime
    availability: Literal["available", "unavailable", "permission_required", "purged", "content_expired"] = "available"
    media_type: Optional[str] = None
    byte_length: Optional[int] = None
    integrity_hash: Optional[str] = None  # SHA-256 of the investigated evidence bytes
    provenance: Optional[EvidenceProvenance] = None
    coverage: Coverage = Field(default_factory=Coverage)
    simulation: Optional[Simulation] = None
    transformations: list[Transformation] = Field(default_factory=list)
    label: str = ""  # short non-secret display label (filename kind, host, "observation: x")


class SourceReference(Wire):
    id: str
    url: str
    title: str
    retrieved_at: datetime
    retrieval: Literal["fetched", "search_result", "unavailable"]
    authority: Literal["official", "independent", "self_claimed", "unknown"] = "unknown"
    authority_basis: str = ""
    published_at: Optional[datetime] = None
    evidence_ids: list[str] = Field(default_factory=list)
    # An earlier lookup Apollo reused while still current (services/reusable_intel.py): retrieved_at is when Apollo
    # last checked it, and the person is shown that.
    reused: bool = False


class Finding(Wire):
    id: str
    text: str
    basis: Literal["observation", "user_report", "inference"]
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    supersedes_finding_ids: list[str] = Field(default_factory=list)
    # ── Structured evidence metadata (optional, populated by evidence evaluation) ──
    subject_attribution: Optional[str] = None        # who/what this finding is about
    relevance: Optional[Literal["primary", "supporting", "excluded"]] = None
    exclusion_reason: Optional[str] = None
    correlation_group: Optional[str] = None          # group ID for correlated findings
    legitimate_hypothesis: Optional[str] = None      # why this might be legitimate
    malicious_hypothesis: Optional[str] = None       # why this might be malicious
    hypothesis_balance: Optional[Literal["legitimate", "malicious", "ambiguous", "verified_threat"]] = None


class Question(Wire):
    id: str
    text: str
    reason_needed: str
    answer_type: Literal["text", "yes_no", "choice"] = "text"
    choices: list[str] = Field(default_factory=list)


ActionKind = Literal["instruction", "open_settings", "request_permission", "recheck", "open_verified_source"]


class ActionProposal(Wire):
    id: str
    kind: ActionKind
    label: str
    instruction: str
    capability_id: Optional[str] = None
    execution_descriptor_id: Optional[str] = None
    requires_user_gesture: bool = True
    source_ids: list[str] = Field(default_factory=list)
    # Structured intent for open_settings/request_permission actions, supplied by Higgins — the client binds a
    # SettingsPlan to exactly this field/value and NEVER infers a direction from the label/instruction wording.
    # Both are null when there is no single observable target (the plan is then left unresolvable by design).
    desired_field: Optional[str] = None
    desired_value: Union[bool, str, None] = None


class PlainItem(Wire):
    """One finding, in plain English: its words, who established it and how firmly, and any jargon explained."""
    text: str
    detail: str = ""
    explain: str = ""  # explanatory only, never case evidence (e.g. what a domain is)
    finding_id: Optional[str] = None


class FidelityFailure(Wire):
    code: str
    ref: str = ""
    detail: str = ""


class FidelityResult(Wire):
    status: Literal["PASS", "FAIL"]
    failures: list[FidelityFailure] = Field(default_factory=list)


class PlainEnglish(Wire):
    """Higgins' plain-English explanation of a validated result (services/higgins/explain). A presentation layer
    only: the structured result it explains stays authoritative, and wins wherever the two differ.
    mode: "plain" passed the Fidelity Check first time; "repaired" passed once its failed parts were put back in
    Apollo's own wording; "literal" failed again, so the person sees Apollo's own wording only."""
    version: Literal[1] = 1
    renderer: Literal["apollo"] = "apollo"
    mode: Literal["plain", "repaired", "literal"]
    result: str
    severity: str
    # What it is: the case's subject in one fixed line ("What it is: the Stoko email address hello@stoko.com.").
    subject: str = ""
    established: list[PlainItem] = Field(default_factory=list)
    means: list[str] = Field(default_factory=list)
    matters: list[str] = Field(default_factory=list)
    todo: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    how: list[str] = Field(default_factory=list)
    fidelity: FidelityResult
    attempts: int = 1
    attempt_failures: list[list[FidelityFailure]] = Field(default_factory=list)


class BriefingSubject(Wire):
    value: str
    type: str
    organisation: Optional[str] = None
    # True when the organisation is only named and the subject isn't its (a lookalike), so it is never called its owner.
    organisation_claimed: bool = False


class BriefingFinding(Wire):
    """One material finding: Subject → Check → Result, in the words shown (the subject always named)."""
    id: str
    subject: Optional[str] = None
    subject_type: Optional[str] = None
    organisation: Optional[str] = None
    organisation_claimed: bool = False
    check: str
    result: str
    finding: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    materiality: Literal["material", "context"]
    confidence: str
    basis: str
    stance: Literal["supporting", "contrary", "context"]


class CaseBriefing(Wire):
    """The Higgins Case Briefing (services/higgins/explain/briefing.py): the one authoritative summary every surface
    projects — Home, Threats, the Overview and notifications. "Needs you" only when user_action_required is true and
    there is a concrete action_reason."""
    version: Literal[1] = 1
    subject: Optional[BriefingSubject] = None
    headline: str
    summary: str
    findings: list[BriefingFinding] = Field(default_factory=list)
    supporting: list[str] = Field(default_factory=list)
    contrary: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    status: str
    status_code: Optional[str] = None
    attention: str
    status_reason: str
    user_action_required: bool
    action_reason: Optional[str] = None
    recommended_action: Optional[dict[str, str]] = None
    fidelity: FidelityResult


class HistoryNote(Wire):
    """Related history beside a result (services/higgins/history.py): one of this device's own earlier cases, or a
    previous encounter in concerning material. Context, never evidence: it never changes the outcome, attention or
    findings — only, when it agrees with a concern, the confidence of the findings it lists."""
    kind: Literal["previously_encountered", "related_case"]
    match: Literal["website", "number", "email", "message", "file", "organisation", "connected"]
    text: str
    source: str
    agrees: bool
    subject: Optional[str] = None
    event_id: Optional[str] = None
    at: Optional[str] = None
    outcome: Optional[str] = None
    finding_ids: list[str] = Field(default_factory=list)


Stage = Literal["higgins_triage", "tc_flyby", "magnum_di"]


class EvidenceFact(Wire):
    """One material fact the investigation established (services/higgins/case_evidence.py), recorded at commit from
    the case's own records: the stage that first established it and the later stages that established it too.
    stance: supporting / contrary ("points the other way") relative to the outcome, or neutral. A lookup that found
    nothing or didn't answer is never evidence either way, so it is never a fact."""
    id: str
    text: str
    stance: Literal["supporting", "contrary", "neutral"]
    discovered_by: Stage
    corroborated_by: list[Stage] = Field(default_factory=list)
    weak: bool = False
    basis: Literal["observation", "user_report", "inference"] = "observation"
    confidence: Optional[Literal["low", "medium", "high"]] = None
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    # The result's findings this fact stands for (their related history is shown beside it).
    finding_ids: list[str] = Field(default_factory=list)
    rule_id: Optional[str] = None
    established_at: Optional[datetime] = None
    simulated: bool = False


class HigginsResponse(Wire):
    revision: int
    overview: str
    explanation_markdown: str
    assessment: Assessment
    outcome: Optional[Outcome] = None
    attention: Attention
    attention_reason: Optional[str] = None
    findings: list[Finding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    scope: str = ""
    source_ids: list[str] = Field(default_factory=list)
    remaining_evidence_ids: list[str] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    recommended_action_id: Optional[str] = None
    question: Optional[Question] = None
    completion: Completion
    plain_english: Optional[PlainEnglish] = None
    briefing: Optional[CaseBriefing] = None
    history: list[HistoryNote] = Field(default_factory=list)
    # None: recorded before the Evidence record existed (never reconstructed). [] : recorded, nothing established.
    evidence: Optional[list[EvidenceFact]] = None
    # The Findings Rating (0-100, Apollo PRD v2.2 §2) and its six-dimension explanation
    # (services.higgins.tc_flyby.scoring.ScoreBreakdown.wire()). None for a general question / no Finding.
    findings_rating: Optional[int] = Field(default=None, ge=0, le=100)
    findings_rating_breakdown: Optional[dict] = None
    # A reputation-check provider (e.g. IPQualityScore) failed or timed out after retrying and nothing
    # else resolved what it would have covered (PRD v2.2 §2.5, services.higgins.tc_flyby.decide.technical_issue).
    # True only for that "investigation unable to progress" case — never set alongside a Findings Rating.
    technical_failure: Optional[bool] = None


class Inventory(Wire):
    total: int = 0
    examined: int = 0
    partial: int = 0
    unavailable: int = 0
    purged: int = 0
    content_expired: int = 0


class SettledReason(Wire):
    """The rule that settled a result, as one plain sentence (services/rulebook.py)."""
    rule_id: str
    rule: str
    by: Literal["TC Hawkeye", "Magnum DI"]
    sentence: str


class InvestigationCase(Wire):
    schema_version: Literal[1] = 1
    id: str
    revision: int
    gates: list[Gate]
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    evidence_expires_at: Optional[datetime] = None  # 24h from first evidence acquisition
    retention_class: str = ""
    response: Optional[HigginsResponse] = None
    active_job_id: Optional[str] = None
    pending_device_request_ids: list[str] = Field(default_factory=list)
    inventory: Inventory = Field(default_factory=Inventory)
    cleanup_status: Literal["not_due", "pending", "complete", "failed"] = "not_due"
    # Who settled the latest result: "magnum_di", or TC Hawkeye by route ("tc_flyby_official", "tc_flyby_kb", "tc_flyby_search").
    answered_by: Optional[str] = None
    # The rule that settled it, as one plain sentence (services/rulebook.py). None when the record doesn't say.
    settled_reason: Optional[SettledReason] = None
    # The latest moment the server keeps what was submitted: 24 hours after the investigation finished (None while it runs).
    content_delete_by: Optional[datetime] = None
    # An outside source behind the result was simulated (the preview's stand-in for Magnum DI's call or TC Hawkeye's search).
    # Everything else ran exactly as in production; this only tags it.
    simulated: bool = False
    # Who started the investigation, as recorded when the case was opened: the person ("user") or Apollo ("apollo").
    # None when the record doesn't say — never inferred.
    origin: Optional[Literal["user", "apollo"]] = None


class RetryAttempt(Wire):
    """One recovery attempt in the investigation's retry history."""
    attempt: int
    kind: Literal["provider_retry", "job_resume", "stream_reconnect", "manual_retry"]
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    timestamp: Optional[str] = None
    duration_ms: Optional[int] = None
    outcome: Literal["retrying", "recovered", "exhausted", "failed", "cancelled"]


class DiagnosticDetail(Wire):
    """Original service/component diagnostic info — sanitised for display."""
    component: Optional[str] = None          # magnum_di, provider_adapter, gemini, investigation_storage, transport
    service: Optional[str] = None            # Gemini, Google AI Studio, etc.
    operation: Optional[str] = None          # investigation, evidence_retrieval, response_generation, validation, storage
    original_error_code: Optional[str] = None
    http_status: Optional[int] = None
    original_message: Optional[str] = None   # provider response, safely redacted
    provider_response: Optional[str] = None  # the provider's actual reply, verbatim but redacted/truncated
    provider_model: Optional[str] = None     # model that produced the reply
    provider_finish_reason: Optional[str] = None
    exception_type: Optional[str] = None
    timestamp: Optional[str] = None          # ISO 8601
    duration_ms: Optional[int] = None
    request_id: Optional[str] = None         # provider correlation reference
    case_id: Optional[str] = None
    job_id: Optional[str] = None
    final_status: Optional[str] = None       # retrying, recovered, exhausted, failed, cancelled


class Failure(Wire):
    code: FailureCode
    message: str
    retryable: bool = False
    retry_after_seconds: Optional[int] = None
    # Set when both Gemini attempts were used: the person may resubmit from this moment.
    resubmit_at: Optional[datetime] = None
    missing_evidence_ids: list[str] = Field(default_factory=list)
    diagnostics: Optional[DiagnosticDetail] = None
    retry_history: list[RetryAttempt] = Field(default_factory=list)


class Job(Wire):
    id: str
    case_id: str
    turn_id: str
    status: CaseStatus
    started_at: Optional[datetime] = None
    deadline_at: datetime
    retry_at: Optional[datetime] = None
    attempt: int = 0
    last_event_sequence: int = 0
    failure: Optional[Failure] = None


class DeviceProfile(Wire):
    platform: Platform
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    form_factor: Literal["phone", "tablet", "desktop", "laptop", "convertible", "unknown"] = "unknown"
    locale: str = "en-AU"
    evidence_origin: Literal["native", "user_reported", "browser"] = "browser"
    capability_ids: list[str] = Field(default_factory=list)


class DeviceRequest(Wire):
    id: str
    case_id: str
    case_revision: int
    capability_id: str
    fields: list[str]
    reason: str
    expires_at: datetime


DeviceValue = Union[str, int, float, bool, list[str], None]


UnavailableReason = Literal["not_implemented", "os_restricted", "hardware_absent", "configuration_missing", "entitlement_missing", "privacy_prohibited", "source_refused", "adapter_failed"]


class UserActionContract(Wire):
    action_id: str
    label: str
    context: dict[str, str] = Field(default_factory=dict)


class PatrolSummaryContract(Wire):
    state: Literal["resting", "ears_up", "growling", "barking", "biting"]
    title: str
    summary: str
    occurred_at: datetime
    source: Literal["background", "user_started", "higgins", "family"]


class PatrolOutputContract(Wire):
    summary: PatrolSummaryContract
    repeat_count: int = Field(ge=1)
    result: str
    result_basis: str
    primary_action: Optional[UserActionContract] = None
    secondary_actions: list[UserActionContract] = Field(default_factory=list)
    why_this_rating: list[str] = Field(default_factory=list)


class DeviceResult(Wire):
    request_id: str
    case_revision: int
    capability_id: str
    status: Literal["observed", "unavailable", "permission_required", "denied", "failed"]
    observed_at: Optional[datetime] = None
    values: dict[str, DeviceValue] = Field(default_factory=dict)
    simulation: Optional[Simulation] = None
    # An observed result has no unavailable reason; an unavailable/failed result states its actual reason.
    unavailable_reason: Optional[UnavailableReason] = None

    @model_validator(mode="after")
    def unavailable_has_reason(self):
        if self.status in {"unavailable", "failed"} and not self.unavailable_reason:
            raise ValueError("unavailable and failed device results require unavailableReason")
        if self.status in {"observed", "permission_required", "denied"} and self.unavailable_reason is not None:
            raise ValueError("available and permission results must not carry unavailableReason")
        return self


class ExpectedObservation(Wire):
    capability_id: str
    field: str
    expected_value: Union[bool, str]


class SettingsPlan(Wire):
    id: str
    case_id: str
    target: str
    device: DeviceProfile
    match: Literal["exact", "platform_only", "unresolved"]
    mode: Literal["permission_request", "settings_link", "instructions"]
    instructions: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    execution_descriptor_id: Optional[str] = None
    expected_observation: Optional[ExpectedObservation] = None


class RecheckResult(Wire):
    plan_id: str
    checked_at: datetime
    outcome: Literal["correct", "not_yet_correct", "cannot_observe", "failed"]
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str


class Usage(Wire):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ProviderResult(Wire):
    # "apollo" for TC Hawkeye (runs locally without an external API).
    # "gemini", "anthropic", or "openai" for Magnum DI, set directly from AIResult.provider.
    provider: str = "gemini"
    model: str
    api_version: str = "v1beta"
    finish_reason: str
    provider_complete: bool
    usage: Usage = Field(default_factory=Usage)
    source_ids: list[str] = Field(default_factory=list)
    # True when the preview simulator answered instead of Gemini — recorded, never hidden.
    simulated: bool = False
    # Who settled this turn: "magnum_di", or TC Hawkeye by route ("tc_flyby_official", "tc_flyby_kb", "tc_flyby_search").
    answered_by: str = "magnum_di"


class TurnCommit(Wire):
    turn_id: str
    case_id: str
    input_revision: int
    committed_revision: int
    question: str
    answer_to_question_id: Optional[str] = None
    response: HigginsResponse
    provider: ProviderResult
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    committed_at: datetime


# ------------------------------------------------------------------ requests
class Submission(Wire):
    client_item_id: str = Field(pattern=UUID_PATTERN)
    kind: Literal["text", "url"]
    value: str = Field(min_length=1)
    label: str = Field(default="", max_length=80)


class CreateCase(Wire):
    gate: Optional[Gate] = None  # None = general Higgins question not tied to one Gate
    question: str = Field(default="", max_length=4000)  # blank = open the case, attach evidence first, then submit the first turn
    submissions: list[Submission] = Field(default_factory=list)
    initial_finding_refs: list[str] = Field(default_factory=list)
    initial_findings: list[str] = Field(default_factory=list)  # Apollo observations (apollo_inference origin), full text
    device_profile: Optional[DeviceProfile] = None
    # Who started it, as the phone records it: the person submitted it ("user") or Apollo detected it ("apollo").
    origin: Optional[Literal["user", "apollo"]] = None
    # The check's own Threats record on the phone: the case's result updates that record, never files a twin.
    patrol_event_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,80}$")


class TextSubmission(Wire):
    expected_revision: int
    client_item_id: str = Field(pattern=UUID_PATTERN)
    parent_id: Optional[str] = None
    kind: Literal["text"]
    text: str = Field(min_length=1)
    label: str = Field(default="", max_length=80)


class UrlSubmission(Wire):
    expected_revision: int
    client_item_id: str = Field(pattern=UUID_PATTERN)
    parent_id: Optional[str] = None
    kind: Literal["url"]
    url: str = Field(min_length=4)
    label: str = Field(default="", max_length=80)


class ObservationSubmission(Wire):
    expected_revision: int
    client_item_id: str = Field(pattern=UUID_PATTERN)
    parent_id: Optional[str] = None
    kind: Literal["observation"]
    device_result: DeviceResult


EvidenceSubmission = Union[TextSubmission, UrlSubmission, ObservationSubmission]


class UploadMetadata(Wire):
    expected_revision: int
    client_item_id: str = Field(pattern=UUID_PATTERN)
    parent_id: Optional[str] = None
    kind: Literal["image", "document", "audio", "attachment"]
    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=3, max_length=120)
    # What the device did to the image before upload (e.g. "credential regions redacted"). Informational only —
    # submitting an image to an investigation authorises its analysis.
    sanitization_decision: Optional[str] = None
    redacted_regions: Optional[int] = None
    sanitization_transformations: list[str] = Field(default_factory=list)
    # The text the phone's on-device text recognition read from the image (credentials already removed there).
    # Higgins Triage uses it as the image's extracted content; the image itself is stored unchanged.
    device_extracted_text: Optional[str] = Field(default=None, max_length=20000)


class CreateUpload(UploadMetadata):
    declared_bytes: int = Field(ge=1)


class SubmitTurn(Wire):
    expected_revision: int
    turn_id: str = Field(pattern=UUID_PATTERN)
    message: str = Field(min_length=1)
    answer_to_question_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)


class ExpectedRevision(Wire):
    expected_revision: int


class SettingsPlanRequest(Wire):
    expected_revision: int
    target: str = Field(min_length=1, max_length=200)
    device: DeviceProfile
    capability_id: Optional[str] = None  # supported action descriptor the plan is bound to (must be advertised by the device)
    expected_field: str = "enabled"
    expected_value: Union[bool, str, None] = None  # intended target value (e.g. False for "disable"); None = cannot be observed


class RecheckRequest(Wire):
    device_result_ids: list[str]


# ------------------------------------------------------------------ model-facing (IDs assigned by coordinator)
class ModelFinding(Wire):
    text: str
    basis: Literal["observation", "user_report", "inference"]
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    supersedes_finding_ids: list[str] = Field(default_factory=list)


class ModelAction(Wire):
    kind: ActionKind
    label: str
    instruction: str
    capability_id: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    desired_field: Optional[str] = None
    desired_value: Union[bool, str, None] = None


class ModelQuestion(Wire):
    text: str
    reason_needed: str
    answer_type: Literal["text", "yes_no", "choice"] = "text"
    choices: list[str] = Field(default_factory=list)


class ModelResponse(Wire):
    overview: str = Field(min_length=1)
    explanation_markdown: str = Field(min_length=1)
    assessment: Assessment
    outcome: Optional[Outcome] = None
    attention: Attention
    attention_reason: Optional[str] = None
    findings: list[ModelFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    scope: str = ""
    source_ids: list[str] = Field(default_factory=list)
    remaining_evidence_ids: list[str] = Field(default_factory=list)
    actions: list[ModelAction] = Field(default_factory=list)
    recommended_action_index: Optional[int] = None
    question: Optional[ModelQuestion] = None
    completion: Completion
    # TC Hawkeye's own Findings Rating (0-100, Apollo PRD v2.2 §2) and six-dimension explanation
    # (services.higgins.tc_flyby.scoring) — attached to the dict report.compose() builds before it's
    # validated through this same model. The Gemini-facing schema allows but never asks for these;
    # Magnum DI's model output leaves them null.
    findings_rating: Optional[int] = Field(default=None, ge=0, le=100)
    findings_rating_breakdown: Optional[dict] = None
    # TC Hawkeye-only: a reputation-check provider failed/timed out after retrying with nothing else
    # resolving what it would have covered (PRD v2.2 §2.5) — "investigation unable to progress", never a
    # Finding. The Gemini-facing schema allows but never asks for this; Magnum DI's model output leaves it null.
    technical_failure: Optional[bool] = None


MODEL_RESPONSE_SCHEMA = ModelResponse.model_json_schema(by_alias=True)


def failure_body(code: FailureCode, message: str, *, retryable: bool = False, retry_after: Optional[int] = None,
                 missing: Optional[list[str]] = None) -> dict:
    return {"error": Failure(code=code, message=message, retryable=retryable, retry_after_seconds=retry_after,
                             missing_evidence_ids=missing or []).wire()}
