// The sources Apollo actually consulted for one Threat Case, and exactly what each one returned.
//
// Every entry is built from recorded data only — the event's evidence source, its stored Triage record,
// its enforcement evidence, the saved Magnum DI investigation and its cited source references.
// A source that did not answer is reported as such; nothing is inferred and nothing is invented.
// ApolloSG's servers are never listed as a source: server processing is not where evidence comes from.

import type { DeviceInvestigation } from "../investigation/deviceStore";
import { caseShortfalls, hasRecordedFindings, unrecordedShortfall, type Shortfall } from "./caseFacts.ts";
import { evidenceModel } from "./evidenceModel.ts";
import { investigatorName, settledByFlyby } from "./messageVoice.ts";
import type { EmailEvidenceProfile } from "./triage/emailEvidence.ts";
import type { PatrolEvent } from "./types";

export interface CaseSource {
  id: string;
  /** What Apollo consulted, in plain English. */
  name: string;
  /** What that source returned — facts only, no interpretation. */
  returned: string;
  /** When it was consulted, when the record carries a time. */
  at: string | null;
  /** false when the source could not be read or did not answer. */
  answered: boolean;
  /** How it fell short when it didn't answer ("couldn't be verified"); "didn't answer" when absent. */
  status?: string;
  /** For a check that didn't finish: what ApolloSG therefore couldn't verify ("where the link finally leads"). */
  unverified?: string;
  /** Present for external references so the UI can open them. */
  url?: string;
}

/** The heading for one source: its name, and how it fell short when it did. */
export function sourceHeading(source: Pick<CaseSource, "name" | "answered" | "status">): string {
  return source.answered ? source.name : `${source.name} — ${source.status ?? "didn't answer"}`;
}

const MECHANISM_SOURCE: Record<string, string> = {
  dns_sinkhole: "Apollo's DNS filter",
  content_policy: "Apollo's content policy filter",
  firewall_rule: "Apollo's firewall rule",
  browser_interstitial: "Apollo's browser warning",
  app_block: "Apollo's app-level block",
  packet_drop: "Apollo's packet filter",
};

export function buildCaseSources(input: { event: PatrolEvent; investigation?: DeviceInvestigation | null }): CaseSource[] {
  const { event, investigation } = input;
  const sources: CaseSource[] = [];

  // 1. Where the evidence came from — its recorded source only.
  const model = evidenceModel(event);
  const provider = (event.source_metadata?.provider ?? "").trim();
  if (model.source === "local_device") {
    const count = (event.why ?? []).filter((w) => !!w.trim()).length;
    sources.push({
      id: "device",
      name: "This device",
      returned: !hasRecordedFindings(event)
        ? "Apollo checked it here. This record holds the kind of check and its result, not the content that was checked"
        : count > 0
          ? `Read directly on the device — ${count} recorded detail${count === 1 ? "" : "s"} about the finding`
          : "Read directly on the device — the finding, with no further detail recorded",
      at: event.occurred_at,
      answered: true,
    });
  } else if (model.source === "dns_observation" && event.indicator_host) {
    sources.push({
      id: "dns",
      name: "Apollo's known-threat list",
      returned: `A DNS lookup for ${event.indicator_host} matched a known-threat entry`,
      at: event.occurred_at,
      answered: true,
    });
  } else if (model.source === "native_protection") {
    const owner = provider || "Your device's built-in protection";
    const verdict = (event.source_metadata?.provider_classification ?? "").trim();
    sources.push({
      id: "native_protection",
      name: owner,
      returned: verdict
        ? `${owner} classified this as “${verdict}”. That is ${owner}'s finding — Apollo investigated it from there.`
        : `${owner} flagged this first. Apollo investigated it from there.`,
      at: event.occurred_at,
      answered: true,
    });
  } else if (model.source === "device_submission") {
    sources.push({ id: "device", name: "This device", returned: "Sent the item Apollo checked", at: event.occurred_at, answered: true });
  } else if (model.source === "connected_mailbox" && !provider) {
    sources.push({ id: "mailbox", name: "Your connected mailbox", returned: "Supplied the email Apollo checked", at: event.occurred_at, answered: true });
  }

  // 2. The mailbox or app the item was taken from, when intake recorded it.
  if (provider) {
    sources.push({
      id: "provider",
      name: `${provider} mailbox`,
      returned: "Supplied the message Apollo checked",
      at: event.source_metadata?.received_at ?? event.occurred_at,
      answered: true,
    });
  }

  // 2b. The evidence Higgins Triage received (email L1–L4) and, from an original, the server that recorded its
  //     sender authentication — credited to that server; ApolloSG reports it and never re-checks it.
  const profile = event.evidence_profile;
  if (profile) {
    const KIND: Record<string, string> = { email: "Email", link: "Link", message: "Message", call: "Call", file: "File", app: "App", image: "Image" };
    const label = `${KIND[profile.type] ?? ""} evidence`.trim();
    sources.push({ id: "evidence_profile", name: `${label.charAt(0).toUpperCase()}${label.slice(1)} received: ${profile.label}`, returned: profile.basis, at: profile.at, answered: true });
    const auth = profile.type === "email" ? (profile as EmailEvidenceProfile).auth : null;
    if (auth) {
      const server = auth.recordedBy === "unknown" ? "The receiving mail server" : auth.recordedBy;
      const results = (["spf", "dkim", "dmarc"] as const).map((m) => `${m.toUpperCase()} ${auth[m] ?? "not recorded"}`).join(", ");
      sources.push({
        id: "auth_results", name: `${server} (sender authentication)`,
        returned: `Recorded ${results}${auth.receiverConfirmed ? "" : " — ApolloSG couldn't match this server to the ones that delivered the email"}. ApolloSG reported these and didn't re-check them.`,
        at: profile.at, answered: true,
      });
    } else if (profile.type === "email" && profile.rank >= 3) {
      sources.push({ id: "auth_results", name: "The receiving mail server (sender authentication)", returned: "Recorded no SPF, DKIM or DMARC results in this email.", at: profile.at, answered: false });
    }
  }

  // 3. The deterministic Triage checks — outcome and counts, plus every source that didn't answer.
  const triage = event.triage_investigation;
  const caseId = event.investigation_case_id ?? event.patrol_record?.investigationCaseId;
  if (triage) {
    const next = !caseId ? "Magnum DI was not engaged."
      : settledByFlyby(investigation?.answeredBy) ? "TC Hawkeye settled it — Magnum DI was not engaged."
        : "Escalated to Magnum DI.";
    sources.push({
      id: "triage",
      name: `Apollo's Triage checks (rule catalogue v${triage.catalogueVersion})`,
      returned: `${triage.rulesChecked.length} of ${triage.rulesApplicable.length} applicable checks completed, ${triage.rulesMet.length} matched. ${next}`,
      at: triage.evaluatedAt,
      answered: true,
    });
  }
  // 3b. Every check that didn't finish: what was checked, what happened, why, and what couldn't be verified — the
  //     recorded reason, never generic wording. Only when nothing records why does the fixed "not recorded" row show.
  const shortfall = (row: Shortfall): CaseSource =>
    ({ id: row.id, name: row.name, returned: row.reason, at: row.at, answered: false, status: row.status, unverified: row.unverified });
  sources.push(...caseShortfalls(event).map(shortfall));
  const unrecorded = unrecordedShortfall(event);
  if (unrecorded) sources.push(shortfall(unrecorded));

  // 4. Apollo's own enforcement, when it genuinely acted.
  if (event.verified_block && event.enforcement_evidence) {
    const ev = event.enforcement_evidence;
    sources.push({
      id: "enforcement",
      name: MECHANISM_SOURCE[ev.mechanism] ?? `Apollo enforcement (${ev.mechanism.replace(/_/g, " ")})`,
      returned: `${ev.enforced_action.replace(/_/g, " ")} — ${ev.result.replace(/_/g, " ")}${ev.destination_domain ? ` for ${ev.destination_domain}` : ""}`,
      at: ev.observed_at,
      answered: true,
    });
  }

  // 5. The investigation itself, credited to whichever investigator answered it.
  if (caseId) {
    const findings = investigation?.response?.findings?.length ?? 0;
    sources.push({
      id: "magnum",
      name: investigation ? `${investigatorName(investigation.answeredBy)} investigation` : "Investigation",
      returned: investigation
        ? `${findings} finding${findings === 1 ? "" : "s"} returned`
        : event.investigation_completed_at ? "The result isn't part of this case's record" : "No result recorded yet",
      at: investigation?.completedAt ?? null,
      answered: !!investigation,
    });
  }

  // 6. Every external source the investigation cited, with what it gave back.
  for (const ref of investigation?.sources ?? []) {
    const citing = (investigation?.response?.findings ?? []).filter((f) => f.sourceIds.includes(ref.id));
    const returned = citing.length > 0
      ? citing.map((f) => f.text).join(" ")
      : ref.retrieval === "fetched" ? "Page retrieved; nothing from it was cited in the findings"
        : ref.retrieval === "search_result" ? "Appeared in search results only"
          : "Could not be retrieved";
    sources.push({
      id: `ref:${ref.id}`,
      name: ref.title || ref.url,
      returned,
      at: ref.retrievedAt || null,
      answered: ref.retrieval !== "unavailable",
      url: ref.url,
    });
  }

  // 7. References recorded on the event itself (official guidance Apollo linked to).
  for (const [i, ref] of (event.supporting_references ?? []).entries()) {
    sources.push({
      id: `support:${i}`,
      name: ref.label,
      returned: "Supporting reference recorded with this finding",
      at: null,
      answered: true,
      url: ref.url,
    });
  }

  return sources;
}
