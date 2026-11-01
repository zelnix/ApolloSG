// Adapters: existing on-device analysers → the shared Triage evidence shape.
// Nothing here decides an outcome; it only normalises evidence for the engine.

import type { LocalAnalysis } from "@/src/domain/types";
import type { MessageAnalysis } from "@/src/domain/messageAnalysis.ts";
import type { CallAnalysis, CallInput } from "@/src/domain/callAnalysis.ts";
import type { TriageEvidence } from "./engine.ts";
import type { TriageOutcome } from "./contract.ts";
import { fromSources, incompleteCheck, type IncompleteCheck, type SourceLike } from "./completeness.ts";
import type { EmailAnalysis } from "@/src/domain/emailAnalysis.ts";
import { registrableDomain } from "../brand.ts";
import type { EmailEvidenceProfile } from "./emailEvidence.ts";

export interface CorrelationInput {
  related?: { category: string; event_id: string; occurred_at?: string }[];
  mechanics?: string[];
  supporting_evidence?: boolean;
  case_key?: string | null;
}

export interface UrlIntel {
  verdict?: "clean" | "malicious" | "unknown";
  threat_types?: string[];
  redirect_chain?: string[] | null;
  final_url?: string | null;
  domain_info?: { newly_registered?: boolean; available?: boolean } | null;
  /** "none" = no reputation source could check anything — unavailable, never a pass. */
  coverage?: string;
  unavailable?: boolean;
  /** Each source's answer; one that didn't answer is recorded as an incomplete check, never as completed. */
  sources?: SourceLike[];
}

const CREDENTIAL_SIGNALS = new Set(["credential_lure", "credentials_in_url", "brand_lookalike", "brand_in_path"]);

/** Browser/session/DNS/TLS internals are not observable from an Expo app — the engine records
 *  these as Coverage Gaps instead of pretending the check ran. */
export const DEVICE_VISIBILITY = { browser: false, websocket: false, tls: false, push: false, pwa: false } as const;

export function linkTriageEvidence(args: {
  local: LocalAnalysis;
  intel: UrlIntel | null;
  intelError?: string | null;
  /** How the reputation lookup failed after its controlled retry (timeout, auth_failure, …). */
  intelFailure?: string | null;
  displayedHost?: string | null;
  actualHost?: string | null;
  credentialInteraction?: boolean;
  correlation?: CorrelationInput;
  sourceType?: "link" | "site" | "qr";
  qrPayload?: string | null;
}): TriageEvidence {
  const { local, intel, intelError } = args;
  const signals = local.signals.map((s) => s.code);
  // A failed lookup — or an answer where no source could check anything — is unavailable, never a pass.
  const reputation = intel && !intelError && !args.intelFailure && intel.verdict && intel.coverage !== "none"
    ? { status: "ok", verdict: intel.verdict, source: "Apollo threat intelligence", threat_types: intel.threat_types ?? [] }
    : { status: "unavailable", verdict: "unknown", ...(args.intelFailure ? { failure: args.intelFailure } : {}) };
  const hops = (intel?.redirect_chain?.length ?? 0) > 1 ? (intel?.redirect_chain?.length ?? 0) - 1 : 0;
  // Checks that didn't complete inside an answer that did (a source that didn't answer, an unverified final
  // destination). When nothing answered at all, the reputation gap above already says so.
  const incomplete = reputation.status === "ok" ? fromSources(intel?.sources) : [];
  const destination = incomplete.find((c) => c.check === "final_destination");
  return {
    source_type: args.sourceType ?? "link",
    host: local.host,
    local_level: local.level,
    local_signals: signals,
    indicator_match: signals.includes("known_test_threat"),
    credentials_in_url: signals.includes("credentials_in_url"),
    credential_interaction: args.credentialInteraction ?? signals.some((code) => CREDENTIAL_SIGNALS.has(code)),
    brand_mismatch: signals.includes("brand_lookalike") || signals.includes("brand_in_path"),
    displayed_host: args.displayedHost ?? null,
    actual_host: args.actualHost ?? null,
    reputation,
    redirect: hops
      ? destination
        ? { status: "incomplete", hops, final_url: null, final_verdict: "unknown", failure: destination.failure ?? "redirect_failure" }
        : { status: "ok", hops, final_url: intel?.final_url ?? null, final_verdict: intel?.verdict ?? "unknown" }
      : {},
    incomplete_checks: incomplete,
    domain_age: intel?.domain_info
      ? { status: "ok", newly_registered: !!intel.domain_info.newly_registered }
      : (intelError ? { status: "unavailable" } : {}),
    qr_payload: args.qrPayload ?? null,
    qr_is_url: !!args.qrPayload,
    scheme: "https",
    visibility: DEVICE_VISIBILITY,
    correlation: args.correlation ?? {},
    // Structural-only suspicion that no deception rule explains is Limited, never Possible Threat.
    unresolved_concern: local.level === "suspicious" && !signals.some((code) => CREDENTIAL_SIGNALS.has(code)),
    unresolved_concern_detail: "Several structural URL indicators, but no deterministic deception evidence.",
  };
}

export function messageTriageEvidence(args: {
  // An email carries the same signals a text does (EmailAnalysis exposes the same `signals`), so
  // both gates feed the one message adapter.
  analysis: Pick<MessageAnalysis, "signals" | "verdict" | "why">;
  linkOutcome?: TriageOutcome | null;
  /** The threat-producing Link Gate rules the message's links met (MSG-12 routes them; the case cites these). */
  linkRulesMet?: string[];
  phoneReputation?: { status: string; verdict?: string; fraud_score?: number; failure?: string | null } | null;
  /** Checks the message needed that didn't complete: its numbers' and links' reputation lookups. */
  incompleteChecks?: IncompleteCheck[];
  correlation?: CorrelationInput;
}): TriageEvidence {
  const s = args.analysis.signals;
  return {
    source_type: "message",
    signals: {
      code_request: s.codeRequest,
      login_request: s.loginRequest,
      identity_request: s.identityRequest,
      safe_account: /safe account|secure account|protected account/i.test(args.analysis.verdict),
      gift_cards: s.giftCards,
      remote_access: s.remoteAccess,
      install_request: s.remoteAccess,
      extortion: s.extortion,
      advance_fee: s.advanceFee,
      fake_payment: s.fakePayment,
      family_claim: s.familyClaim,
      new_number: s.newNumber,
      money_request: s.moneyRequest,
      payment_request: s.paymentRequest,
      guaranteed_returns: s.guaranteedReturns,
      job_offer: s.jobOffer,
      romance_escalation: s.romanceEscalation,
      platform_switch: s.platformSwitch,
      urgency: s.urgency,
      threat: s.threat,
      unknown_sender: s.unknownSender,
      claimed_brand: s.claimedBrand,
      brand_kind: s.brandKind,
      crypto: s.crypto,
      instant_payment: /\bpay ?id\b|\bosko\b/i.test(args.analysis.verdict) || /\bpay ?id\b|\bosko\b/i.test(args.analysis.why.join(" ")),
      payment_change: false,
      forwarding_code: false,
      forwarding_intent: false,
      callback_request: s.callbackRequest,
      alleged_charge: s.allegedCharge,
      lookalike_name: s.lookalikeName,
      lookalike_chars: s.lookalikeChars.length > 0,
      reply_request: !!s.replyRequest,
      time_pressure: !!s.timePressure,
      government_rebate: !!s.governmentRebate,
    },
    brand_mismatch: !!s.claimedBrand && args.linkOutcome === "POSSIBLE_THREAT_IDENTIFIED",
    link_outcome: args.linkOutcome ?? null,
    link_rules_met: args.linkRulesMet ?? [],
    phone_reputation: args.phoneReputation ?? {},
    incomplete_checks: args.incompleteChecks ?? [],
    visibility: DEVICE_VISIBILITY,
    correlation: args.correlation ?? {},
  };
}

/** An email: the message rules over its content, plus the header evidence its level made available — the
 *  authentication results the receiving server recorded (never re-checked by ApolloSG) and the Reply-To.
 *  Below L3 the authentication check is recorded as incomplete, so the result can never read as complete. */
export function emailTriageEvidence(args: Parameters<typeof messageTriageEvidence>[0] & {
  profile: Pick<EmailEvidenceProfile, "level" | "rank" | "auth" | "facts">;
  analysis: Pick<EmailAnalysis, "signals" | "verdict" | "why" | "senderMismatch" | "replyMismatch" | "bankChange" | "parsed"> & Partial<Pick<EmailAnalysis, "claimedBrand">>;
}): TriageEvidence {
  const base = messageTriageEvidence(args);
  // An email's claimed organisation is who it speaks as (emailAnalysis.claimedSpeaker), never a brand it only mentions.
  if ("claimedBrand" in args.analysis) {
    const speaker = args.analysis.claimedBrand ?? null;
    base.signals = { ...(base.signals as Record<string, unknown>), claimed_brand: speaker, brand_kind: speaker ? (base.signals as Record<string, unknown>).brand_kind : null };
    base.brand_mismatch = !!speaker && base.link_outcome === "POSSIBLE_THREAT_IDENTIFIED";
  }
  const s = base.signals as Record<string, unknown>;
  const { profile, analysis } = args;
  const auth = profile.auth;
  const headers = profile.rank >= 3;
  const results = auth ? Object.fromEntries((["spf", "dkim", "dmarc"] as const).filter((m) => auth[m]).map((m) => [m, auth[m]])) : {};
  const incomplete = [...(base.incomplete_checks as IncompleteCheck[])];
  if (!Object.keys(results).length) {
    incomplete.push(incompleteCheck("sender_authentication", headers ? "not_recorded" : "original_not_provided", { source: headers ? auth?.recordedBy ?? null : null }));
  }
  // With full headers Reply-To is known either way; below that only when the copy showed it.
  const replyKnown = headers || !!analysis.parsed.replyTo;
  return {
    ...base,
    source_type: "email",
    evidence_level: profile.level,
    evidence_rank: profile.rank,
    auth_results: results,
    auth_recorded_by: auth?.recordedBy ?? null,
    auth_receiver_confirmed: auth?.receiverConfirmed ?? false,
    sender_domain: profile.facts.fromDomain,
    sender_domain_mismatch: analysis.senderMismatch,
    reply_to_mismatch: replyKnown ? (headers ? profile.facts.replyToDomains.some((d) => !!profile.facts.fromDomain && registrableDomain(d) !== registrableDomain(profile.facts.fromDomain)) : analysis.replyMismatch) : null,
    consequential_action: ["login_request", "code_request", "identity_request", "payment_request", "money_request", "gift_cards", "remote_access", "callback_request"].some((k) => !!s[k]) || analysis.bankChange,
    credential_request: !!(s.login_request || s.code_request),
    payment_change: analysis.bankChange,
    incomplete_checks: incomplete,
  };
}

export function callTriageEvidence(args: {
  input: CallInput;
  analysis: CallAnalysis;
  reputation?: { status: string; verdict?: string; fraud_score?: number } | null;
  correlation?: CorrelationInput;
}): TriageEvidence {
  const transcript = (args.input.transcript ?? "").toLowerCase();
  return {
    source_type: "call",
    asks: args.analysis.requestedActions,
    claim: args.input.claim,
    safe_account: /safe account|secure account|protected account/.test(transcript),
    threat: /suspend|lock|arrest|warrant|fine|penalty|legal action/.test(transcript),
    dont_hangup: args.analysis.requestedActions.includes("dont_hangup"),
    phone_reputation: args.reputation ?? {},
    visibility: DEVICE_VISIBILITY,
    correlation: args.correlation ?? {},
  };
}

/** Caller-number reputation check (no call content) — reputation evidence only. */
export function numberRiskTriageEvidence(args: {
  decision: string;
  fraudScore?: number | null;
  recentAbuse?: boolean | null;
  voip?: boolean | null;
  unavailable?: boolean;
  /** How the live lookup failed, when it did (timeout, quota_exhausted, …). */
  failure?: string | null;
  /** "stale" = the live lookup failed and this is the last known score from `checkedAt`. */
  freshness?: "fresh" | "cached" | "stale" | null;
  checkedAt?: string | null;
  correlation?: CorrelationInput;
}): TriageEvidence {
  const unavailable = args.unavailable || args.decision === "unknown";
  const reputation = unavailable
    ? { status: "unavailable", verdict: "unknown", ...(args.failure ? { failure: args.failure } : {}) }
    : { status: "ok", verdict: args.decision === "avoid" ? "malicious" : "clean", fraud_score: args.fraudScore ?? null };
  const incomplete = unavailable
    ? [incompleteCheck("number_reputation", args.failure, { source: "ipqs" })]
    : args.freshness === "stale"
      ? [incompleteCheck("number_reputation", args.failure, { status: "stale", source: "ipqs", at: args.checkedAt ?? null })]
      : [];
  return {
    source_type: "call",
    asks: args.decision === "avoid" ? ["callback"] : [],
    claim: "unknown",
    phone_reputation: reputation,
    incomplete_checks: incomplete,
    visibility: DEVICE_VISIBILITY,
    correlation: args.correlation ?? {},
    // A reputation signal with no observed scam behaviour is explicitly not a threat on its own.
    unresolved_concern: args.decision === "review",
    unresolved_concern_detail: "Moderate caller-reputation signals with no observed scam behaviour.",
  };
}
