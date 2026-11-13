import { domainOnly, packetFields, evidenceToken } from './packetEvidence.ts';
import { DEVICE_EVIDENCE_SOURCES } from './evidenceModel.ts';
import { projectedEventVoice } from './messageVoice.ts';
import type { ApolloState } from './types';
// Data egress policy, enforced in code. Every outbound payload passes through
// `enforceEgress` which rejects anything outside the allow-list.
// User-submitted content may leave the device only for the disclosed, one-off assessment the user
// requested. It must not be copied into Patrol payloads, logs, analytics, or background monitoring.

export type EgressEndpoint = "intel_check" | "patrol_sync" | "trust_sync" | "ask_apollo" | "higgins_chat" | "higgins_context" | "capability_snapshot" | "device_register" | "push_register" | "push_preferences" | "device_posture" | "family" | "device_settings" | "message_check" | "link_investigation" | "feedback" | "gmail_scan" | "gmail_monitor" | "app_check" | "account_check" | "breach_check" | "account_monitor" | "voice" | "call_risk_check" | "number_details" | "number_identify" | "call_investigate" | "investigation" | "vision_investigate" | "message_investigation" | "call_investigation" | "number_risk_investigation" | "device_activity" | "triage_telemetry" | "email_evidence" | "official_contacts" | "patrol_saved" | "patrol_delete" | "slm_advisory";

const ALLOWED_KEYS: Record<EgressEndpoint, Set<string>> = {
  // Opt-in, advisory-only local SLM handoff: structured model output only, never raw case material.
  slm_advisory: new Set(["jobId", "caseRevision", "role", "caseId", "requestId", "execution", "modelId", "answer", "status", "reason"]),
  family: new Set(["device_id", "url", "email", "name", "owner_name", "code", "reply", "phone", "protected_device_id", "scent_id", "headline", "state", "events", "steps", "done", "note", "resolved", "kind", "text", "from_name", "enabled", "preview_only", "guardian_name", "duration_s", "submission_id", "relationshipId", "sharerDeviceId", "captureScope", "microphoneRequested", "clientRequestId", "decision", "helperDeviceId", "expectedRevision", "generation", "nativeState", "failureCode",
    // "Send to family" on a threat: its short summary only — never the original message, its links or pictures.
    "event_id", "result", "what_happened", "what_to_do", "involved_label", "involved", "case_ref", "occurred_at"]),
  intel_check: new Set(["indicator_type", "value", "values", "device_id", "expand"]),
  // Shared investigation case (spec §8): opaque IDs, the person's question/message, explicitly submitted items and a device profile — never credentials.
  investigation: new Set(["gate", "question", "submissions", "initialFindingRefs", "initialFindings", "deviceProfile", "origin", "patrolEventId", "expectedRevision", "turnId", "message", "answerToQuestionId", "evidenceIds", "clientItemId", "parentId", "kind", "text", "url", "label", "deviceResult", "requestId", "caseRevision", "capabilityId", "status", "observedAt", "values", "simulation", "unavailableReason", "target", "device", "deviceResultIds", "responseRevision", "section", "filename", "mediaType", "declaredBytes", "expectedField", "expectedValue", "confirmed", "submissionId", "sourceKey", "revisionDigest", "sender", "capturedAt", "expiresAt", "contentComplete", "originalCharacters", "deviceExtractedText", "sanitizationDecision", "redactedRegions", "sanitizationTransformations",
    // Which parts of a finished check this phone saved and checked (booleans and header labels — never their content).
    "saved"]),
  // The Threats records this phone saved with their text: their ids only.
  patrol_saved: new Set(["eventIds"]),
  // Cases the person deleted on this phone, so the server deletes its copies too: their ids only.
  patrol_delete: new Set(["eventIds", "caseIds"]),
  // Higgins' voice: only the sentence already shown on screen, so it can be read aloud.
  voice: new Set(["device_id", "text", "scope_id"]),
  feedback: new Set(["device_id", "event_id", "kind", "state", "host", "sources", "note"]),
  patrol_sync: new Set([
    "event_id", "device_id", "category", "state", "status", "headline", "what_happened", "why", "what_to_do", "case_id",
    "indicator_host", "indicator_digest", "verified_block", "adapter_label", "occurred_at", "resolved_at", "background", "claimed_brand", "scenario", "scent_id", "enforcement_evidence", "supporting_references", "recovery_kinds",
    // Which of the device's own sources supplied the evidence: a fixed label only (validated below).
    "evidence_provenance",
  ]),
  trust_sync: new Set(["device_id", "indicator_type", "indicator_digest", "indicator_host", "event_id", "trust_id"]),
  ask_apollo: new Set(["device_id", "message", "context", "handoff_id", "conversation_id", "turn_id"]),
  // `deviceSnapshot` is the live reading of this device's own Apollo state (protection
  // statuses, permission states, settings values, counts and headlines Apollo wrote).
  // It carries no message content, screenshots, files, links or secrets.
  higgins_chat: new Set(["turnId", "message", "conversationId", "previousTurnIds", "selectedPatrolRecordId", "deviceSnapshot"]),
  higgins_context: new Set(["category", "summary", "provenance", "observedAt"]),
  capability_snapshot: new Set(["platform", "adapter", "online", "gates", "capabilities", "protection", "id", "state", "reason", "requested", "operational", "enforcementMethod", "degradedReason"]),
  // Plus what the device is (make, model, system, region-setting country, install date) for the admin Devices list, and on
  // Android whether it is one of Google's test phones (Play pre-launch testing), so those never count as real users.
  device_register: new Set(["platform", "adapter_mode", "app_version", "tz_offset_minutes", "locale", "manufacturer", "model", "os_name", "os_version", "country", "installed_at", "test_lab"]),
  // Official Organisation Directory: the websites (host only), numbers and addresses a check holds, and the organisation
  // the material names. Nothing else from the material; the server keeps nothing.
  official_contacts: new Set(["claimed_org", "sites", "phones", "emails"]),
  // A feature used on the device: which one, and for a Learn article or scam alert its slug or link (kept only as a digest).
  device_activity: new Set(["kind", "item"]),
  push_register: new Set(["platform", "device_token"]),
  // Gate 2: message text + URLs leave the device only when the user taps "Check message" (shown as "Shared with Apollo for analysis").
  // `client_submission_id` is the id of the patrol record THIS device filed for this check (a
  // locally generated UUID, no personal content). It lets the investigation name that record, so one
  // check stays one case instead of being filed twice.
  // `email_evidence`: Higgins Triage's minimal structured findings about the email evidence (level, recorded
  // authentication results, domains, counts, fingerprints) — never the original .eml, its headers or names.
  message_check: new Set(["device_id", "sender", "text", "urls", "local_state", "scenario", "signals", "claimed_brand", "second_opinion", "client_submission_id", "gate", "email_evidence"]),
  // Better email evidence for an existing case (e.g. the original .eml after a screenshot): findings only.
  email_evidence: new Set(["findings"]),
  link_investigation: new Set(["device_id", "url", "local_state", "local_findings", "claimed_brand", "client_submission_id"]),
  // Gmail read-only connect (Gate 1 add-on): only device_id — the scan itself is triggered here,
  // but the actual message fetch happens entirely on the backend against Google's API using the
  // stored OAuth token; no email content is ever part of this request body.
  gmail_scan: new Set(["device_id"]),
  gmail_monitor: new Set(["device_id", "enabled"]),
  // Gate 7: only the app's name/developer/source/purpose/permission *labels* and SDK-reported hosts — never an app inventory.
  app_check: new Set(["device_id", "name", "developer", "source", "purpose", "permissions", "hosts", "local_state", "scenario", "second_opinion"]),
  // Gate 8: alert text leaves the device only when the user taps "Check this alert"; the breach lookup sends the identifier the user typed, nothing else.
  account_check: new Set(["device_id", "kind", "provider", "sender", "text", "urls", "local_state", "scenario", "second_opinion"]),
  breach_check: new Set(["device_id", "identifier"]),
  // Account Gate exposure monitoring: only the owner's own email addresses, forwarded once per scan.
  account_monitor: new Set(["device_id", "emails"]),
  // Quiet hours window (local minutes + UTC offset) so the server can hold growling pushes at night.
  device_settings: new Set(["quiet_hours"]),
  // Notification categories — booleans only; no device id, no content.
  push_preferences: new Set(["sniffing_growling", "scam_alerts", "learn_with_higgins"]),
  // Device Posture Monitor — observed setting states and the changes between checks. Values are the
  // OS's own answers ("on"/"off"/"unknown"), never app names, numbers, message text or identifiers.
  device_posture: new Set(["snapshot", "changes"]),
  // Call Guard (Gate 4 add-on): only the number itself (+ optional 2-letter country for local
  // numbers) leaves the device, only when the person taps "Check this number" or a call rings with
  // no local block/allow/risk signal — see backend/services/phonerisk.py (IPQualityScore, proxied).
  call_risk_check: new Set(["device_id", "number", "country"]),
  // Number Details on a call's top card: the number and a country hint only — read from built-in numbering-plan data,
  // no lookup service, nothing stored (backend/services/number_details.py).
  number_details: new Set(["number", "country"]),
  // Phone Number Identity: the number and a country hint only — used to identify who the number belongs to
  // from Apollo's own sources (Official Org Directory, KB, web search). No paid reverse-lookup APIs.
  number_identify: new Set(["number", "country"]),
  // Triage outcome telemetry ("Limited by cause"): outcome and cause codes only — never a link, number or content.
  triage_telemetry: new Set(["source_type", "outcome", "causes", "gap_codes", "incomplete", "catalogue_version", "lookup_check", "lookup_attempts", "lookup_outcome"]),
  call_investigate: new Set(["device_id", "number", "country", "caller_asks", "caller_claim", "transcript"]),
  // Vision Gate: privacy-screened image + OCR text → visual investigation routing.
  // Only device_id, extracted_text from on-device OCR, and sanitisation receipt metadata leave the device.
  vision_investigate: new Set(["device_id", "extracted_text"]),
  // Tier 2 escalation after a deterministic Possible Threat. Same content the person already submitted
  // to the gate — the message/call details and Apollo's own deterministic findings. Nothing else.
  message_investigation: new Set(["device_id", "text", "sender", "urls", "local_state", "scenario", "signals", "claimed_brand", "client_submission_id", "gate"]),
  call_investigation: new Set(["gate", "question", "submissions", "initial_findings", "origin"]),
  number_risk_investigation: new Set(["gate", "question", "submissions", "initial_findings", "origin"]),
};

/** Keys that must never appear in any outbound payload, regardless of endpoint. */
const FORBIDDEN_KEYS = new Set(["local_indicator", "contacts", "messages", "sms", "email_body", "page_content", "clipboard", "location", "imei", "serial", "phone_number", "advertising_id"]);

import { CREDENTIAL_PATTERNS, PHONE_PATTERN } from "./privacyPolicy.ts";

// Lazy-load personal data redaction to avoid hard dependency on native modules in test environments.
let _redactPersonalDataInText: (text: string) => string = (text) => text;
let _learnFromMessage: ((text: string) => Promise<void>) | null = null;
try {
  const store = require("../store/personalDataStore");
  _redactPersonalDataInText = store.redactPersonalDataInText;
} catch {
  // Native modules unavailable (test environment) — personal data redaction disabled
}
try {
  const learning = require("../store/personalDataLearning");
  _learnFromMessage = learning.learnFromMessage;
} catch {
  // Native modules unavailable (test environment)
}

/** Private investigation evidence may retain relevant identifiers; durable Patrol does not.
 *  Redaction patterns are imported from the canonical privacyPolicy — no separate rules here. */
export function redactInvestigationSecrets(value: string): string {
  let result = value;
  // Apply all canonical credential patterns from the single source of truth.
  for (const { pattern } of CREDENTIAL_PATTERNS) {
    const re = new RegExp(
      pattern.source,
      pattern.flags + (pattern.flags.includes("g") ? "" : "g"),
    );
    result = result.replace(re, "[credential redacted]");
  }
  return result;
}

export function redactUserSecrets(value: string): string {
  // 1. Always redact credentials
  let result = redactInvestigationSecrets(value);
  // 2. Redact only the user's own personal data (matched against My Personal Data profile)
  result = _redactPersonalDataInText(result);
  // 3. Always redact IP addresses (never user evidence, always infrastructure)
  result = result
    .replace(/\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g, "[ip address]")
    .replace(/\b(?:[A-F0-9]{1,4}:){2,7}[A-F0-9]{1,4}\b/gi, "[ip address]");
  return result;
}

export class EgressViolation extends Error {
  readonly code = "EGRESS_SCHEMA_REJECTED";
  constructor(endpoint: EgressEndpoint, key: string) {
    super("ApolloSG couldn't safely prepare this request. Retry this step.");
    this.name = "EgressViolation";
    Object.defineProperties(this, { endpoint: { value: endpoint, enumerable: false }, field: { value: key, enumerable: false } });
  }
}

/** The only keys an email evidence finding may carry (see src/domain/triage/emailEvidence.ts emailFindings). */
const EMAIL_FINDING_KEYS = new Set(["type", "level", "via", "capabilities", "auth", "from_domain", "reply_to_domains", "return_path_domain", "message_id_domain",
  "dkim_domains", "received_hops", "header_count", "attachments", "signals", "original_sha256", "original_bytes", "observed_at"]);
function validateEmailFindings(endpoint: EgressEndpoint, value: unknown) {
  if (value == null) return;
  if (typeof value !== "object" || Array.isArray(value)) throw new EgressViolation(endpoint, "email_evidence");
  for (const key of Object.keys(value)) if (!EMAIL_FINDING_KEYS.has(key)) throw new EgressViolation(endpoint, `email_evidence.${key}`);
}

export function enforceEgress<T extends Record<string, unknown>>(endpoint: EgressEndpoint, payload: T): T {
  const allowed = ALLOWED_KEYS[endpoint];
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(payload)) {
    if (FORBIDDEN_KEYS.has(key) || !allowed.has(key)) throw new EgressViolation(endpoint, key);
    out[key] = payload[key];
  }
  if (endpoint === 'message_check') validateEmailFindings(endpoint, out.email_evidence);
  if (endpoint === 'email_evidence') validateEmailFindings(endpoint, out.findings);
  if (endpoint === 'message_check' || endpoint === 'account_check') {
    if (typeof out.text !== 'string' || typeof out.sender !== 'string') throw new EgressViolation(endpoint, 'submission types');
    // Non-blocking: learn personal data from submitted message text (email signatures, etc.)
    if (_learnFromMessage && typeof out.text === 'string' && out.text.length > 30) {
      void _learnFromMessage(out.text).catch(() => undefined);
    }
    out.text = redactInvestigationSecrets(out.text);
    out.urls = Array.isArray(out.urls) ? out.urls.map(u => purposeLimitedUrl(String(u))) : [];
  }
  if (endpoint === 'message_investigation') {
    if (typeof out.text !== 'string') throw new EgressViolation(endpoint, 'text');
    out.text = redactInvestigationSecrets(out.text);
  }
  if (endpoint === 'link_investigation') {
    out.url = purposeLimitedUrl(String(out.url ?? ''));
    if (!Array.isArray(out.local_findings) || out.local_findings.length > 12 || out.local_findings.some((value) => typeof value !== 'string' || value.length > 160)) {
      throw new EgressViolation(endpoint, 'local_findings');
    }
  }
  // Investigation endpoint: apply consistent credential redaction to all text fields
  // the person submits. Scammer identifiers (phone, URL, email, sender) are retained.
  if (endpoint === 'investigation') {
    if (typeof out.question === 'string') out.question = redactInvestigationSecrets(out.question);
    if (typeof out.text === 'string') out.text = redactInvestigationSecrets(out.text);
    if (typeof out.message === 'string') out.message = redactInvestigationSecrets(out.message);
    if (typeof out.deviceExtractedText === 'string') out.deviceExtractedText = redactInvestigationSecrets(out.deviceExtractedText);
    if (typeof out.url === 'string') out.url = purposeLimitedUrl(out.url);
  }
  if (endpoint === 'intel_check') {
    if (typeof out.value === 'string') out.value = out.indicator_type === 'domain' ? new URL(minimalIndicator(out.value)).hostname : minimalIndicator(out.value);
    if (Array.isArray(out.values)) out.values = out.values.map(v => minimalIndicator(String(v)));
  }
  if (endpoint === 'official_contacts') {
    for (const key of ['sites', 'phones', 'emails'] as const) {
      if (out[key] !== undefined && (!Array.isArray(out[key]) || (out[key] as unknown[]).some((v) => typeof v !== 'string' || v.length > 320))) {
        throw new EgressViolation(endpoint, key);
      }
    }
    // A website goes as its host only — never its path or query.
    if (Array.isArray(out.sites)) out.sites = (out.sites as string[]).map((v) => v.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '').split(/[/?#]/)[0].split('@').pop()!.toLowerCase());
  }
  if (endpoint === 'patrol_sync') {
    // Minimal case-link payload (only case_id) — no event content to validate.
    if (out.case_id != null && out.category === undefined) {
      if (typeof out.case_id !== 'string' || !evidenceToken(out.case_id)) throw new EgressViolation(endpoint, 'case_id');
    } else {
    // Full event sync — validate all fields and project to privacy-safe values.
    const ev = out.enforcement_evidence as Record<string, unknown> | null | undefined;
    if (ev) validateEvidence(ev, out);
    if (out.category === 'call' && (ev || out.verified_block || out.state === 'biting' || out.indicator_host)) throw new EgressViolation(endpoint, 'call packet claim');
    if (out.indicator_host != null && !domainOnly(out.indicator_host)) throw new EgressViolation(endpoint, 'indicator_host');
    // Only a device's own evidence source label may be synced — never content, never a server.
    if (out.evidence_provenance != null && !DEVICE_EVIDENCE_SOURCES.has(String(out.evidence_provenance))) throw new EgressViolation(endpoint, 'evidence_provenance');
    if (out.supporting_references === undefined) out.supporting_references = [];
    if (!Array.isArray(out.supporting_references) || out.supporting_references.length > 6 || out.supporting_references.some((ref) => {
      if (!ref || typeof ref !== 'object') return true;
      const item = ref as Record<string, unknown>;
      return typeof item.label !== 'string' || item.label.length > 100 || typeof item.url !== 'string' ||
        !item.url.startsWith('https://') || /[?#@]/.test(item.url) || item.url.length > 500;
    })) throw new EgressViolation(endpoint, 'supporting_references');
    const category = String(out.category);
    if (!['link', 'website', 'connection', 'known_threat', 'protection', 'system', 'message', 'call', 'app', 'device', 'account', 'email'].includes(category)) throw new EgressViolation(endpoint, 'category');
    for (const key of ['event_id', 'device_id', 'scent_id']) if (out[key] != null && !evidenceToken(out[key])) throw new EgressViolation(endpoint, key);
    // Project all user-facing text to privacy-safe values BEFORE validation.
    // Raw pre-projection values (headline, what_happened, what_to_do, why) may contain
    // URLs or phone numbers from the investigation subject — that is expected and safe
    // because these fields are always overwritten with controlled projections below.
    out.headline = ev ? 'Apollo observed a blocked connection' : `Apollo recorded a ${category} check`;
    out.what_happened = ev ? 'An observed packet was intentionally blocked by the on-device filter.' : 'A local assessment was recorded. Details stay on the device.';
    out.why = [ev ? 'Packet-backed enforcement evidence is attached.' : 'Only a minimal security summary is shared.'];
    out.what_to_do = 'Review the original alert on your device. A past check does not establish current safety.';
    // Plain-English, code-free, privacy-preserving projection shown on any device/surface (standing
    // message requirement): no raw category/state codes ever reach the user, no detail leaves the device.
    const voice = projectedEventVoice(category, String(out.state) as ApolloState, !!ev);
    out.headline = voice.headline;
    out.what_happened = voice.whatHappened;
    out.why = [voice.why];
    out.what_to_do = voice.whatToDo;
    out.claimed_brand = null;
    out.scenario = typeof out.scenario === 'string' && /^[A-Z]{1,3}\d{1,3}[a-z]?$/.test(out.scenario) ? out.scenario : null;
    out.adapter_label = 'ApolloSG on-device assessment';
    // Validate the PROJECTED output — these are now controlled string literals.
    for (const key of ['headline', 'what_happened', 'what_to_do', 'adapter_label']) {
      if (typeof out[key] !== 'string' || /https?:\/\/|[+@]|\b\d[\d ()-]{6,}\d/.test(out[key] as string)) throw new EgressViolation(endpoint, key);
    }
    if (!Array.isArray(out.why) || out.why.some(w => typeof w !== 'string' || w.length > 160)) throw new EgressViolation(endpoint, 'why');
    }
  }
  if (endpoint === 'family' && Array.isArray(out.events)) {
    out.headline = 'Shared ApolloSG security incident';
    out.events = out.events.map((v: Record<string, unknown>) => ({ event_id: v.event_id, category: v.category,
      state: v.state, headline: 'Security check — review with the protected person', occurred_at: v.occurred_at, status: v.status }));
    if (Array.isArray(out.steps)) out.steps = out.steps.map((v: Record<string, unknown>) => ({ id: v.id, text: 'Review this recovery step on the protected phone together.' }));
  }
  if (endpoint === 'ask_apollo') {
    if (typeof out.message !== 'string' || out.message.length > 262144) throw new EgressViolation(endpoint, 'message');
    out.message = redactInvestigationSecrets(out.message);
    if (out.handoff_id != null && (typeof out.handoff_id !== 'string' || !/^[A-Za-z0-9-]{8,64}$/.test(out.handoff_id))) throw new EgressViolation(endpoint, 'handoff_id');
    if (out.conversation_id == null) out.conversation_id = 'general';
    if (typeof out.conversation_id !== 'string' || !/^[A-Za-z0-9-]{1,64}$/.test(out.conversation_id)) throw new EgressViolation(endpoint, 'conversation_id');
    if (out.context != null) out.context = validateAskContext(out.context);
  }
  return out as T;
}

const ASK_CONTEXT_KEYS = new Set(['gate', 'issue_summary', 'assessment_state', 'findings', 'uncertainty', 'confirmed_protective_actions', 'user_reported_actions', 'available_actions']);
const ASK_FINDING_KEYS = new Set(['summary', 'provenance', 'status']);
const ASK_ACTION_KEYS = new Set(['label', 'instruction']);
const ASK_GATES = new Set(['site', 'link', 'text', 'call', 'network', 'account', 'email', 'app', 'file', 'device', 'incident']);
const ASK_STATES = new Set(['sniffing', 'resting', 'ears_up', 'growling', 'barking', 'biting', 'unknown']);
function validateAskContext(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new EgressViolation('ask_apollo', 'context');
  const raw = value as Record<string, unknown>;
  if (Object.keys(raw).some((key) => !ASK_CONTEXT_KEYS.has(key)) || !ASK_GATES.has(String(raw.gate)) || !ASK_STATES.has(String(raw.assessment_state))) throw new EgressViolation('ask_apollo', 'context');
  const cleanLine = (line: unknown, max = 180) => {
    if (typeof line !== 'string' || !line.trim() || line.length > max) throw new EgressViolation('ask_apollo', 'context');
    return redactUserSecrets(line.trim());
  };
  const lines = (key: string, limit: number) => {
    const items = raw[key] ?? [];
    if (!Array.isArray(items) || items.length > limit) throw new EgressViolation('ask_apollo', `context.${key}`);
    return items.map((line) => cleanLine(line));
  };
  const findings = raw.findings ?? [];
  if (!Array.isArray(findings) || findings.length > 8) throw new EgressViolation('ask_apollo', 'context.findings');
  const actions = raw.available_actions ?? [];
  if (!Array.isArray(actions) || actions.length > 4) throw new EgressViolation('ask_apollo', 'context.available_actions');
  return {
    gate: raw.gate,
    issue_summary: cleanLine(raw.issue_summary, 240),
    assessment_state: raw.assessment_state,
    findings: findings.map((value) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new EgressViolation('ask_apollo', 'context.findings');
      const finding = value as Record<string, unknown>;
      if (Object.keys(finding).some((key) => !ASK_FINDING_KEYS.has(key)) || !['observed', 'inferred', 'user_reported'].includes(String(finding.provenance)) || !['confirmed', 'warning', 'uncertain'].includes(String(finding.status))) throw new EgressViolation('ask_apollo', 'context.findings');
      return { summary: cleanLine(finding.summary), provenance: finding.provenance, status: finding.status };
    }),
    uncertainty: lines('uncertainty', 6),
    confirmed_protective_actions: lines('confirmed_protective_actions', 4),
    user_reported_actions: lines('user_reported_actions', 6),
    available_actions: actions.map((value) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new EgressViolation('ask_apollo', 'context.available_actions');
      const action = value as Record<string, unknown>;
      if (Object.keys(action).some((key) => !ASK_ACTION_KEYS.has(key))) throw new EgressViolation('ask_apollo', 'context.available_actions');
      return { label: cleanLine(action.label, 80), instruction: cleanLine(action.instruction, 240) };
    }),
  };
}

const EVIDENCE_KEYS = new Set(['evidence_id', 'event_id', 'device_id', 'platform', 'os_version', 'sdk_version', 'observed_at', 'mechanism', 'direction', 'protocol', 'destination_ip', 'destination_domain', 'destination_port', 'app_id', 'process_name', 'attribution_confidence', 'matched_rule_id', 'threat_id', 'requested_action', 'enforced_action', 'result', 'rule_source', 'confidence', 'correlation_id']);
function validateEvidence(ev: Record<string, unknown>, event: Record<string, unknown>) {
  for (const key of Object.keys(ev)) if (!EVIDENCE_KEYS.has(key)) throw new EgressViolation('patrol_sync', `enforcement_evidence.${key}`);
  for (const key of ['os_version', 'sdk_version', 'destination_ip', 'app_id', 'process_name', 'threat_id', 'correlation_id']) if (ev[key] != null) throw new EgressViolation('patrol_sync', `enforcement_evidence.${key}`);
  if (!packetFields(ev as any) || (ev.event_id != null && (ev.event_id !== event.event_id || !evidenceToken(ev.event_id))) ||
    (ev.device_id != null && ev.device_id !== event.device_id) || Date.parse(String(ev.observed_at)) !== Date.parse(String(event.occurred_at))) throw new EgressViolation('patrol_sync', 'enforcement_evidence');
}

/** Reduce a URL to the indicator we are willing to send for reputation checks.
 * Preserves the path so page-specific threats (e.g. phishing landing pages vs. clean homepages)
 * get distinct reputation. Strips credentials, fragments and secret-looking query parameters. */
export function minimalIndicator(normalizedUrl: string): string {
  const u = new URL(normalizedUrl.includes('://') ? normalizedUrl : `https://${normalizedUrl}`);
  if (!['http:', 'https:'].includes(u.protocol)) throw new EgressViolation('intel_check', 'scheme');
  u.username = "";
  u.password = "";
  u.hash = "";
  // Strip query parameters that may carry secrets (tokens, session IDs, etc.)
  const secret = /token|code|otp|auth|session|password|pass|secret|key|signature|sig/i;
  for (const key of [...u.searchParams.keys()]) if (secret.test(key)) u.searchParams.delete(key);
  // Path is intentionally preserved: stripping it to "/" would make origin-only checks
  // indistinguishable from exact-link checks, hiding page-specific threats.
  return u.toString();
}

/** Preserve the submitted path/context while stripping credentials, fragments and secret query values. */
export function purposeLimitedUrl(normalizedUrl: string): string {
  const u = new URL(normalizedUrl.includes('://') ? normalizedUrl : `https://${normalizedUrl}`);
  if (!['http:', 'https:'].includes(u.protocol)) throw new EgressViolation('message_check', 'scheme');
  u.username = '';
  u.password = '';
  u.hash = '';
  const secret = /token|code|otp|auth|session|password|pass|secret|key|signature|sig/i;
  for (const key of [...u.searchParams.keys()]) if (secret.test(key)) u.searchParams.set(key, '[redacted]');
  return u.toString();
}

export const PRIVACY_POLICY_SUMMARY = [
  "Links you check are analysed on your device first.",
  "When you tap Check, the submitted text, sender and links are processed for that assessment. Credentials, fragments and secret query values are removed before sending.",
  "Submitted screenshots are processed only for the requested assessment and ApolloSG closes request-scoped upload copies after success or failure.",
  "Background notification access, mailbox connections and ongoing monitoring require separate opt-in. Automatic notification checks remain local unless you enable a supported connection.",
  "Patrol keeps the assessment summary and safe supporting references, not full messages, screenshots, files or sensitive tokens.",
  "Ask Higgins conversation content and generated speech are encrypted temporarily, for no more than 15 minutes. Clear temporary history invalidates them; provider-side retention follows your Higgins account policy.",
  "ApolloSG uses an anonymous device ID. No account, no email. A phone number is shared only if you choose to add one so family can call you.",
  "Ask Higgins sends only your question and, if you choose, a short event summary.",
  "Hear Higgins reads the displayed explanation in temporary protected audio sections. It uses the owner's Higgins account, not a different AI provider.",
];
