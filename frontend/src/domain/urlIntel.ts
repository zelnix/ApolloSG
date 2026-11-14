// URL reputation for links found inside a message or email.
//
// This is the DETECTION path only: the same `/intel/check` call a manual Check-a-Link makes, run
// over each link the material contains. It never opens an investigation case and never spends a
// Gemini call — Magnum DI is launched separately, and only when Triage escalates.

import { apiPost } from "@/src/api/client";
import { parseIntelResult } from "@/src/domain/intelContract";
import { lookupWithRetry, type LookupFailure, type LookupOutcome } from "@/src/domain/reputationLookup";
import type { DomainInfo, IntelResult } from "@/src/domain/types";
import { fromSources, type IncompleteCheck } from "@/src/domain/triage/completeness";

export interface MessageUrlResult {
  url: string;
  host: string;
  verdict: "clean" | "malicious" | "unknown";
  threat_types: string[];
  coverage: string;
  redirect_chain?: string[];
  final_url?: string | null;
  domain_info?: DomainInfo | null;
  /** Set when the lookup established nothing: how it failed, after the controlled retry. */
  failure?: LookupFailure | null;
  /** Checks inside an answer that didn't complete (a source that didn't answer, an unverified final destination). */
  incomplete?: IncompleteCheck[];
}

export function hostOfUrl(url: string): string {
  return url.replace(/^https?:\/\//i, "").split("/")[0].toLowerCase();
}

/** Per-attempt budget: the server bounds its own work well inside this, and the lookup is retried. */
const INTEL_TIMEOUT_MS = 30000;

const LOOKUP_FAILURE_MESSAGE: Record<LookupFailure, string> = {
  timeout: "The reputation service took too long to answer.",
  offline: "ApolloSG couldn't reach the reputation service.",
  server_error: "The reputation service is having trouble right now.",
  rate_limited: "The reputation service is busy right now.",
  malformed: "The reputation service sent an answer ApolloSG couldn't read.",
  provider_unavailable: "No reputation source could check this link.",
  auth_failure: "ApolloSG's reputation check wasn't authorised for this device.",
  forbidden: "This device isn't allowed to use the reputation check.",
  rejected: "The reputation service couldn't accept this link for checking.",
  not_configured: "The reputation service isn't set up here.",
  no_data: "The reputation service had no information about this.",
  quota_exhausted: "The reputation service has used up its checks for now.",
};

export function lookupFailureMessage(failure: LookupFailure, error?: unknown): string {
  return error instanceof Error && error.message ? error.message : LOOKUP_FAILURE_MESSAGE[failure];
}

/** One reputation lookup with the controlled retry. A malformed answer, or one where no source could check
 *  anything (coverage "none"), counts as unavailable — never as a clean result. */
export function lookupUrlIntel(value: string, deviceId: string | null): Promise<LookupOutcome<IntelResult | null>> {
  return lookupWithRetry("reputation_lookup", value, async () => {
    const raw = await apiPost<unknown>("/intel/check", "intel_check", { indicator_type: "url", value, device_id: deviceId ?? undefined, expand: true }, { timeoutMs: INTEL_TIMEOUT_MS });
    return parseIntelResult(raw);
  }, { unavailable: (intel) => (!intel ? "malformed" : intel.coverage === "none" ? "provider_unavailable" : null) });
}

/** Reputation for up to `limit` links. A link the service could not answer for is still returned,
 *  with coverage "unavailable" — never silently dropped and never assumed clean. */
export async function fetchMessageUrlIntel(
  urls: string[],
  deviceId: string | null,
  limit = 5,
): Promise<MessageUrlResult[]> {
  const results: MessageUrlResult[] = [];
  for (const rawUrl of [...new Set(urls)].slice(0, limit)) {
    const { value: parsed, failure } = await lookupUrlIntel(rawUrl, deviceId);
    results.push({
      url: rawUrl,
      host: hostOfUrl(rawUrl),
      verdict: failure ? "unknown" : parsed?.verdict === "malicious" ? "malicious" : parsed?.verdict === "clean" ? "clean" : "unknown",
      threat_types: failure ? [] : parsed?.threat_types ?? [],
      // Real coverage from the reputation service. A failed lookup is "unavailable" — it must never be
      // recorded as a completed check.
      coverage: failure || !parsed ? "unavailable" : parsed.coverage,
      redirect_chain: parsed?.redirect_chain ?? undefined,
      final_url: parsed?.final_url ?? null,
      domain_info: parsed?.domain_info ?? null,
      failure,
      incomplete: failure || !parsed || parsed.coverage === "none" ? [] : fromSources(parsed.sources, rawUrl),
    });
  }
  return results;
}

/** The deterministic link finding Triage reads. Null when the material carries no links. */
/** The threat-producing Link Gate rules the links met: a malicious listing is LINK-01 (authoritative reputation). */
export function linkTriageRulesMet(urls: MessageUrlResult[]): string[] {
  return urls.some((u) => u.verdict === "malicious") ? ["LINK-01"] : [];
}

export function linkTriageOutcome(urls: MessageUrlResult[]): "POSSIBLE_THREAT_IDENTIFIED" | "LIMITED_UNABLE_TO_DETERMINE" | "NO_THREAT_IDENTIFIED" | null {
  if (urls.some((u) => u.verdict === "malicious")) return "POSSIBLE_THREAT_IDENTIFIED";
  if (urls.some((u) => u.coverage === "unavailable")) return "LIMITED_UNABLE_TO_DETERMINE";
  return urls.length ? "NO_THREAT_IDENTIFIED" : null;
}
