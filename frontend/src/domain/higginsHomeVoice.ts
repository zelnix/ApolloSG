// Higgins-led Home voice. Produces ONE short paragraph that interprets Apollo's current behaviour
// using REAL data — three independent conditions (threat status, protection coverage, user actions)
// are assessed separately and never conflated.
//
// OPERATING STANDARD: Higgins is an authoritative cybersecurity expert.
// INVESTIGATE → ASSESS → DIRECT → GUIDE → VERIFY.
// Every actionable finding produces a specific instruction, not a vague suggestion.
//
// Pure, unit-testable: no React, no navigation.

import type { AttentionItem } from "./homeAttention";
import type { GatePresentation } from "./gates";
import { briefed, firstFinding, needsYou } from "./caseBriefing.ts";
import { firstReason } from "./luddish/present.ts";
import { hasRecordedFindings } from "./caseFacts.ts";
import { sentences } from "./luddish/patterns.ts";
import { subjectDescriptor, threatSubject } from "./threatSubject.ts";
import { resolveHomeStatus, type HomeResolverInput } from "./homeStatusResolver.ts";
import type { StateResolution } from "./stateMachine";
import type { Capability, PatrolEvent } from "./types";
import { domainOnly } from "./urlPresentation.ts";

export interface HomeVoice {
  /** The short Higgins paragraph the Home card shows (and reads aloud). */
  text: string;
  /** The one primary action label — contextual (e.g. "View what Apollo found", "View Protection Details"). */
  ctaLabel: string;
  /** Route to open on tap. May be undefined for benign states (no CTA shown). */
  ctaRoute?: string;
  /** Spoken version — identical to text; kept separate so screens can extend if needed. */
  spoken: string;
  /** Protection status indicator — independent of threat state (PRD Section 6). */
  protectionStatus?: "watching" | "reduced" | "action_needed";
  /** Higgins' explanation of protection issues — shown separately from the threat assessment. */
  protectionGuidance?: string;
}

/** The ONE sentence from a finding that says what Apollo actually found — no instructions, no
 *  settings paths, no what-to-do. Returns null when the event carries no such sentence, so callers
 *  fall back to naming the check instead of inventing detail. Recorded findings only. */
export function findingSentence(event: PatrolEvent): string | null {
  if (!hasRecordedFindings(event)) return null;
  // Web addresses read as their website before anything is split or capped.
  const text = domainOnly((event.what_happened || "").trim());
  if (!text) return null;
  // Instructions belong in the case, never in the hero line.
  const factual = sentences(text).filter((sentence) => !/→|\bsettings\b|^open\b|^tap\b|\bgo to\b/i.test(sentence));
  const stated = factual.find((sentence) => /\b(found|detected|observed|spotted|flagged|blocked|stopped|is active)\b/i.test(sentence))
    ?? factual[0];
  if (!stated) return null;
  const cleaned = stated.replace(/^(in it,|here,|in this case,)\s*/i, "").trim();
  if (!cleaned) return null;
  // Whole: the sentence Apollo recorded is never cut short.
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/** A finding in its Higgins Case Briefing's own words: the headline, then its first finding (subject always named).
 *  Null when the event has no checked briefing. */
export function briefedLine(event: PatrolEvent | undefined): string | null {
  const b = briefed(event);
  return b ? `${b.headline}: ${firstFinding(b)}${needsYou(event!) ? " It needs your decision." : ""}` : null;
}

const sentence = (text: string) => (/[.!?…]$/.test(text) ? text : `${text}.`);
const capitalised = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const lowerFirst = (text: string) => (/^[A-Z][a-z]/.test(text) ? text[0].toLowerCase() + text.slice(1) : text);

/** "The text from AusPost: asks for a one-time code." — what was checked and the first concrete thing Apollo recorded
 *  about it; null when it recorded nothing specific. Never a posture ("Apollo flagged …"). */
function concreteLine(event: PatrolEvent | undefined, what: string): string | null {
  const reason = event ? firstReason(event) : null;
  return reason ? `${capitalised(what)}: ${sentence(lowerFirst(reason))}` : null;
}


/** Human label for every Capability id, used when assembling the dynamic affected-gate list. */
const CAPABILITY_LABEL: Record<Capability["id"], string> = {
  link_guard: "Link checking",
  site_guard: "Website protection",
  connection_guard: "Internet monitoring",
  known_threats: "Known Threat Lookup",
  share_intake: "Share to ApolloSG",
  message_guard: "Message screening",
  app_guard: "App checking",
};

/** Join a list of names in plain English: ["A", "B", "C"] → "A, B and C". */
export function joinNames(names: string[]): string {
  const unique = Array.from(new Set(names.filter(Boolean)));
  if (unique.length === 0) return "";
  if (unique.length === 1) return unique[0];
  if (unique.length === 2) return `${unique[0]} and ${unique[1]}`;
  return `${unique.slice(0, -1).join(", ")} and ${unique[unique.length - 1]}`;
}

/** Capability IDs that represent genuinely automatic protection (continuous background monitoring
 *  or enforcement). Manual-only checks (link, known_threats, share_intake, app) don't "run" in the
 *  background, so they should never appear as "Apollo can't confirm X is running." */
const AUTOMATIC_CAPABILITY_IDS = new Set<string>([
  "site_guard", "connection_guard", "message_guard",
]);

/** Capabilities where automatic protection has GENUINELY degraded — not merely optional setup,
 *  normal manual-check readiness, or unsupported platform features.
 *  - "available" = the check is ready when you need it (not a failure)
 *  - Manual-only capabilities never "run" continuously, so can't "fail to run"
 *  - "unsupported" = platform limitation (not a failure of something that was working) */
export function affectedCapabilities(capabilities: Capability[]): Capability[] {
  return capabilities.filter(
    (c) => c.status !== "active" && c.status !== "coming_later" && c.status !== "unsupported"
      && c.status !== "available"
      && AUTOMATIC_CAPABILITY_IDS.has(c.id),
  );
}

/** Describe what Apollo noticed, in a verb that matches the state. Used when assembling multi-issue
 *  paragraphs so "Apollo is barking because he spotted…" / "Apollo is growling because he's unsure…" */
function verbForState(state: StateResolution["state"]): string {
  switch (state) {
    case "barking":  return "spotted";
    case "biting":   return "stopped";
    case "growling": return "noticed";
    case "ears_up":  return "is looking at";
    default:         return "is checking";
  }
}

/** Build the short paragraph + CTA for the Home card.
 *  Uses the central Home Status Resolver to separate threat status, protection coverage,
 *  and user actions — then produces Higgins' interpretation as one natural paragraph.
 *
 *  Priority (highest first):
 *   1. Verified block (biting) → confirm what Apollo blocked, link to the investigation.
 *   2. One specific high-priority concern → name the concern, link to the investigation.
 *   3. Two current concerns → name both specifically.
 *   4. Three+ current concerns → name the most important, summarise to Threats.
 *   5. Visibility lost (protection unverified) → explain, link to Protection.
 *   6. Patrolling / Sniffing → calm status line.
 *
 *  NEVER: count-driven messaging ("N findings"), generic directions, or
 *  conflation of gate-health with security threats.
 */
export function buildHomeVoice(input: {
  resolution: StateResolution;
  attention: AttentionItem[];
  gates: GatePresentation[];
  capabilities: Capability[];
}): HomeVoice {
  const { resolution, attention, gates, capabilities } = input;
  const state = resolution.state;

  // Derive platformCanEnforce from capabilities (same logic as ApolloContext).
  const platformCanEnforce = capabilities.some((c) => c.id === "site_guard" && c.status !== "unsupported");

  // Run the three-pillar resolver to get the evidence-based status.
  const homeStatus = resolveHomeStatus({
    resolution,
    attention,
    gates,
    capabilities,
    findingCount: 0, // Not used for count-driven messaging
    platformCanEnforce,
  });

  // Separate security findings from protection issues — never conflate.
  const securityFindings = attention.filter((a) => a.kind === "event");
  const protectionIssues = attention.filter((a) => a.kind === "gate");

  // ── Resting: the resolver produces scenario-specific messaging ──
  if (state === "resting" || (resolution.platformLimited && homeStatus.behavior === "resting")) {
    // Use approved wording when no security threat
    const restingText = homeStatus.explanation ||
      "No security threats currently detected within Apollo's current protection capability.";
    return {
      text: restingText,
      ctaLabel: homeStatus.primaryAction?.label ?? "View protection",
      ctaRoute: homeStatus.primaryAction?.route ?? "/(tabs)/protection",
      spoken: restingText,
      protectionStatus: homeStatus.protectionStatus,
      protectionGuidance: homeStatus.protectionGuidance,
    };
  }

  if (state === "sniffing" || state === "ears_up") {
    const drivingEvent = resolution.drivingEvent;
    const verb = state === "ears_up" ? "has his ears up" : "is sniffing";
    if (drivingEvent) {
      const gateName = GATE_FOR_CATEGORY[drivingEvent.category] ?? "a security check";
      const rawSubject = domainOnly((drivingEvent.headline || drivingEvent.what_happened || "").trim());
      const subject = hasRecordedFindings(drivingEvent) ? rawSubject : "";
      const text = state === "ears_up"
        ? `ApolloSG ${verb} — something in ${gateName}${subject ? ` caught his attention: ${subject}` : " caught his attention"}. He's looking at it. I'll tell you exactly what to do once he's finished.`
        : `ApolloSG ${verb} — Magnum DI is investigating ${gateName}${subject ? `: ${subject}` : ""}. I'll tell you exactly what to do once he's finished.`;
      return {
        text,
        ctaLabel: "View what Apollo is checking",
        ctaRoute: `/patrol/${encodeURIComponent(drivingEvent.event_id)}`,
        spoken: text,
      };
    }
    return {
      text: state === "ears_up"
        ? "Apollo has noticed something — something in a recent check caught his attention. I'll show you what he's found."
        : "Apollo is sniffing — running his checks across your protections.",
      ctaLabel: "View what Apollo is checking",
      ctaRoute: "/(tabs)/patrol",
      spoken: state === "ears_up"
        ? "Apollo has noticed something — something caught his attention. I'll tell you what to do."
        : "Apollo is sniffing — running his checks across your protections.",
    };
  }

  const drivingEvent = resolution.drivingEvent;

  // 1) Biting — Apollo blocked something. Only when the driving event carries a verified_block flag.
  if (state === "biting" && drivingEvent?.verified_block) {
    const rawWhat = domainOnly((drivingEvent.what_happened || drivingEvent.headline || "").trim());
    const subject = threatSubject(drivingEvent);
    const what = hasRecordedFindings(drivingEvent) && rawWhat
      ? rawWhat
      : subject ? subjectDescriptor(subject) : "a threat";
    const gateName = GATE_FOR_CATEGORY[drivingEvent.category] ?? "a protection check";
    const text = `Apollo blocked ${what} through ${gateName}. The threat is contained. Open the investigation to see exactly what Apollo stopped and why.`;
    return {
      text,
      ctaLabel: "View what Apollo blocked",
      ctaRoute: `/patrol/${encodeURIComponent(drivingEvent.event_id)}`,
      spoken: `Apollo blocked ${what}. The threat is contained.`,
    };
  }

  // 2) Security findings — prioritise by severity, explain specifically, never count-driven.
  if (securityFindings.length > 0) {
    const primary = securityFindings[0]; // Already priority-sorted by buildHomeAttention
    const primaryProblem = domainOnly((primary.problem || "").trim());
    // A case with a Higgins Case Briefing is said in the briefing's own words, never wrapped in a template.
    const primaryBriefed = briefedLine(primary.event);

    if (securityFindings.length === 1) {
      // ONE short line: the specific thing Apollo reacted to, or the check it came from. The case
      // title and the what-to-do steps live in the case itself — the hero must stay glanceable.
      const stated = primaryBriefed ?? (primary.event ? findingSentence(primary.event) : null);
      const subject = primary.event ? threatSubject(primary.event) : null;
      const what = subject ? subjectDescriptor(subject) : `the ${primary.gate} check`;
      const text = stated
        ?? concreteLine(primary.event, what)
        ?? (state === "barking" ? `Apollo found signs of a scam in ${what}.` : `Apollo found a warning sign in ${what}.`);
      return {
        text,
        ctaLabel: "View what Apollo found",
        ctaRoute: primary.route,
        spoken: text,
      };
    }

    if (securityFindings.length === 2) {
      // Two specific concerns — name both, link to the most urgent.
      const second = securityFindings[1];
      const secondBrief = domainOnly((second.problem || second.title || "").trim());
      const secondBriefed = briefedLine(second.event);
      const text = primaryBriefed || secondBriefed
        ? `${primaryBriefed ?? sentence(primaryProblem || `Apollo found a concern in ${primary.gate}`)} Also: ${secondBriefed ?? sentence(secondBrief || second.gate)} I'll walk you through both, starting with the most urgent.`
        : primaryProblem
          ? `${sentence(capitalised(primaryProblem))} There's also a concern about ${secondBrief || second.gate}. I'll walk you through both, starting with the most urgent.`
          : `Apollo found concerns in ${primary.gate} and ${second.gate}. I'll walk you through both.`;
      return {
        text,
        ctaLabel: "View what Apollo found",
        ctaRoute: primary.route,
        spoken: text,
      };
    }

    // Three or more — name the most important, direct to Threats for the rest.
    const text = primaryBriefed
      ? `${primaryBriefed} There are other concerns too — I'll walk you through everything in Threats, starting with the most urgent.`
      : primaryProblem
        ? `${sentence(capitalised(primaryProblem))} There are other concerns too. Let's start with the most urgent — I'll walk you through everything in Threats.`
        : `Apollo found several security concerns. Let's start with the most urgent.`;
    return {
      text,
      ctaLabel: "View in Threats",
      ctaRoute: primary.route,
      spoken: text,
    };
  }

  // 3) Only gate/protection issues, no security findings — these are protection health, not threats.
  if (protectionIssues.length > 0) {
    const gateNames = Array.from(new Set(protectionIssues.map((g) => g.gate).filter(Boolean)));
    const names = joinNames(gateNames);
    const text = `${names} ${protectionIssues.length === 1 ? "needs" : "need"} attention to keep your protection running properly. This isn't a security threat — it's about maintaining Apollo's coverage.`;
    return {
      text,
      ctaLabel: "View protection",
      ctaRoute: "/(tabs)/protection",
      spoken: text,
      protectionStatus: "action_needed",
      protectionGuidance: `${names} ${protectionIssues.length === 1 ? "requires" : "require"} attention.`,
    };
  }

  // 3b) DNS threat observation.
  if (drivingEvent?.evidence_provenance === "dns_observation" && drivingEvent.indicator_host) {
    const domain = drivingEvent.indicator_host;
    const text = `Apollo detected a known threat — a DNS query for "${domain}" was intercepted and redirected before the browser could connect. This is a detection, not a confirmed block. Do not visit this website. If you received it in a message, treat that source as suspicious.`;
    return {
      text,
      ctaLabel: "View what Apollo detected",
      ctaRoute: `/patrol/${encodeURIComponent(drivingEvent.event_id)}`,
      spoken: `Apollo detected a known threat. A DNS query for ${domain} was intercepted.`,
    };
  }

  // 3c) A driving event exists but didn't surface as a dedicated attention item.
  if (drivingEvent) {
    const stated = findingSentence(drivingEvent);
    const subject = threatSubject(drivingEvent);
    const named = subject ? subjectDescriptor(subject) : "";
    const gateName = GATE_FOR_CATEGORY[drivingEvent.category] ?? "a security check";
    const text = stated
      ? stated
      : named
        ? `Apollo is reacting to ${named}.`
        : `Apollo is reacting to something in the ${gateName} check.`;
    return {
      text,
      ctaLabel: "View what Apollo found",
      ctaRoute: `/patrol/${encodeURIComponent(drivingEvent.event_id)}`,
      spoken: text,
    };
  }

  // 4) Visibility lost — use resolver's evidence-based messaging.
  if (resolution.visibilityLost) {
    return {
      text: homeStatus.explanation,
      ctaLabel: homeStatus.primaryAction?.label ?? "Check protection",
      ctaRoute: homeStatus.primaryAction?.route ?? "/(tabs)/protection",
      spoken: homeStatus.explanation,
    };
  }

  // 5) Recovering — no active event, waiting on a fresh verification check.
  if (resolution.recovering) {
    return {
      text: "ApolloSG is staying cautious after a recent alert. He needs a fresh check to confirm things are clear.",
      ctaLabel: "View protection",
      ctaRoute: "/(tabs)/protection",
      spoken: "ApolloSG is staying cautious after a recent alert.",
    };
  }

  // 6) Fallback — use resolver's evidence-based messaging.
  return {
    text: homeStatus.explanation,
    ctaLabel: homeStatus.primaryAction?.label ?? "View protection",
    ctaRoute: homeStatus.primaryAction?.route ?? "/(tabs)/protection",
    spoken: homeStatus.explanation,
  };
}

/** Mapping from a PatrolEvent category to a human gate name. Mirrors homeAttention. */
const GATE_FOR_CATEGORY: Record<string, string> = {
  link: "Link checking", website: "Website protection", known_threat: "Website protection", protection: "Website protection",
  connection: "Internet monitoring", system: "Device monitoring", device: "Device monitoring", message: "Message screening",
  call: "Call screening", app: "App checking", account: "Account alerts", email: "Email monitoring", file: "File checking",
  family: "Family alert",
};
