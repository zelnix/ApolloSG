/**
 * Phone Identity — Higgins plain-English explanation of structured findings.
 *
 * Deterministic: no AI, no network call. Takes the identity result from the
 * backend and produces a headline, body paragraph, actionable advice,
 * and optional spoofing / scam / impersonation warnings.
 *
 * Follows the "Apollo investigates, Higgins explains" principle used throughout
 * the app: qualified language, never alarmist, always actionable.
 *
 * ── Explanation structure ──
 *   headline    One sentence: what Apollo found.
 *   body        2–4 sentences: what the evidence means, in Higgins's voice.
 *   whatToDo    1–2 sentences: what the person should do next.
 *   spoofing    Optional: caller-ID spoofing awareness (when entity is known
 *               but not Tier 1 verified).
 *   scamWarning Optional: IPQS / abuse intelligence (when scam_intel is present).
 *   impersonationWarning  Optional: when the number claims an identity that
 *               doesn't match the organisation's published numbers.
 */

import type { PhoneIdentityResult, IdentityEvidence, PrefixIntelligenceTier } from "@/src/api/phoneIdentity";

// ── Public types ─────────────────────────────────────────────────────────────

/** Explanation for a single prefix-intelligence tier. */
export interface TierExplanation {
  /** "geographic" | "number_block" | "caller" */
  tier: string;
  /** One-line finding for this tier. */
  headline: string;
  /** Supporting context. */
  detail: string | null;
  /** Qualification wording: "regional association" / "appears to be associated with" / "verified" */
  qualifier: string;
  /** Visual confidence signal. */
  confidence: "high" | "medium" | "low";
  /** Named business units or divisions (e.g. ["Kleenheat", "CSBP"]). */
  businessUnits: string[];
  /** How to reach them back. */
  callback: string | null;
  /** Extra context about calling back. */
  callbackNote: string | null;
  /** Physical location. */
  location: string | null;
}

export interface IdentityExplanation {
  /** One-line finding. */
  headline: string;
  /** 2–4 sentence Higgins paragraph. */
  body: string;
  /** Actionable next step. */
  whatToDo: string;
  /** Spoofing awareness (null when not applicable). */
  spoofing: string | null;
  /** Scam/abuse intel warning (null when clean). */
  scamWarning: string | null;
  /** Impersonation warning (null when not flagged). */
  impersonationWarning: string | null;
  /** Progressive intelligence tiers (geographic → block → caller). */
  tiers: TierExplanation[];
}

// ── Main entry point ─────────────────────────────────────────────────────────

export function explainIdentity(result: PhoneIdentityResult): IdentityExplanation {
  const {
    associated_entity: entity,
    association_confidence: confidence,
    evidence,
    scam_intel,
    known_impersonation,
    number_type,
    geographic,
    country,
    canonical,
    network,
    prefix_intelligence,
  } = result;

  return {
    headline: buildHeadline(entity, confidence, canonical),
    body: buildBody(entity, confidence, evidence, number_type, geographic, country, network, prefix_intelligence),
    whatToDo: buildWhatToDo(entity, confidence, known_impersonation, scam_intel),
    spoofing: buildSpoofing(entity, confidence),
    scamWarning: scam_intel ?? null,
    impersonationWarning: buildImpersonation(entity, known_impersonation),
    tiers: buildTierExplanations(prefix_intelligence ?? []),
  };
}

// ── Headline ─────────────────────────────────────────────────────────────────

function buildHeadline(
  entity: string | null,
  confidence: PhoneIdentityResult["association_confidence"],
  canonical: string,
): string {
  if (!entity) {
    return "No verified organisation claims this number — treat this call as likely a scam.";
  }

  switch (confidence) {
    case "verified":
      return `This is ${entity}'s published number.`;
    case "strong":
      return `This number is strongly associated with ${entity}.`;
    case "possible":
      return `This number may belong to ${entity}.`;
    case "conflicting":
      return "Different sources name different organisations for this number.";
    case "unknown":
      return "No verified organisation claims this number — treat this call as likely a scam.";
  }
}

// ── Body paragraph ───────────────────────────────────────────────────────────

function buildBody(
  entity: string | null,
  confidence: PhoneIdentityResult["association_confidence"],
  evidence: IdentityEvidence[],
  numberType: string | null,
  geographic: string | null,
  country: string | null,
  network: string | null,
  prefixIntelligence?: PrefixIntelligenceTier[],
): string {
  const parts: string[] = [];

  // What the number is
  const typeDesc = describeNumberType(numberType, geographic, country, network);
  if (typeDesc) {
    parts.push(typeDesc);
  }

  // Progressive intelligence context: if we have a number-block association
  // that provides context even when the caller tier is unknown, surface it.
  const blockTier = prefixIntelligence?.find((t) => t.tier === "number_block" && t.entity);
  if (blockTier && blockTier.entity && (!entity || entity.toLowerCase() === blockTier.entity.toLowerCase())) {
    if (!entity) {
      // No exact-number match, but block intelligence has a lead
      parts.push(
        `The number range appears to be associated with ${blockTier.entity}, although exact ownership wasn't confirmed.`,
      );
      if (blockTier.detail) {
        parts.push(blockTier.detail);
      }
    }
  }

  // What Apollo found
  switch (confidence) {
    case "verified": {
      const tier1 = evidence.find((e) => e.source_type === "tier_1_official");
      if (tier1) {
        parts.push(
          `Apollo confirmed this number on ${entity}'s own website${tier1.last_verified_at ? `, last verified ${formatDate(tier1.last_verified_at)}` : ""}.`,
        );
        parts.push("This is the strongest level of association Apollo can establish.");
      } else {
        parts.push(`Apollo found authoritative evidence that this number belongs to ${entity}.`);
      }
      break;
    }
    case "strong": {
      const sourceCount = evidence.length;
      const sourceTypes = uniqueSourceTypes(evidence);
      parts.push(
        `Apollo found ${sourceCount} independent ${plural(sourceCount, "source")} ${sourceTypes} associating this number with ${entity}.`,
      );
      parts.push("The evidence is strong, though the number wasn't confirmed on the organisation's own website.");
      break;
    }
    case "possible": {
      parts.push(
        `Apollo found some evidence suggesting this number may belong to ${entity}, but it hasn't been confirmed on official channels.`,
      );
      parts.push("The association is plausible but not certain.");
      break;
    }
    case "conflicting": {
      const entities = distinctEntities(evidence);
      if (entities.length >= 2) {
        parts.push(
          `Different sources associate this number with different organisations: ${entities.slice(0, 3).join(", ")}.`,
        );
      }
      parts.push("When sources disagree, the caller's claimed identity should be treated as unverified.");
      break;
    }
    case "unknown": {
      parts.push(
        "ApolloSG checked its Official Organisation Directory, knowledge base, and public web sources but found no verified organisation claiming this number.",
      );
      parts.push("An unregistered number is a common feature of scam and fraud calls — that alone is enough to treat this as concerning.");
      break;
    }
  }

  return parts.join(" ");
}

// ── What to do ───────────────────────────────────────────────────────────────

function buildWhatToDo(
  entity: string | null,
  confidence: PhoneIdentityResult["association_confidence"],
  knownImpersonation: boolean,
  scamIntel: string | null,
): string {
  // Impersonation is the most urgent signal
  if (knownImpersonation) {
    return `Do not share personal information. This number is not published by ${entity ?? "the claimed organisation"}. If you need to contact them, use the number on their official website.`;
  }

  // Scam intel present
  if (scamIntel) {
    return "Exercise caution. This number has been flagged in fraud or abuse reports. If you didn't initiate the call, consider not answering or hanging up.";
  }

  switch (confidence) {
    case "verified":
      return "You can be confident about who this number belongs to. As always, never share passwords or one-time codes over the phone.";
    case "strong":
      return `If you weren't expecting a call from ${entity ?? "this organisation"}, verify by calling them back on the number from their official website.`;
    case "possible":
      return "Verify the caller independently before sharing any sensitive information. Call the organisation back on a number you find yourself.";
    case "conflicting":
      return "Treat this caller's identity as unverified. If they claim to be from an organisation, hang up and call the organisation directly on a number from their official website.";
    case "unknown":
      return "Treat this call as likely a scam. Do not share personal information or act on any instructions. If the caller claims to represent an organisation, hang up and contact that organisation directly using a number from their official website.";
  }
}

// ── Spoofing awareness ───────────────────────────────────────────────────────

function buildSpoofing(
  entity: string | null,
  confidence: PhoneIdentityResult["association_confidence"],
): string | null {
  // No spoofing warning for unknown or verified — either we don't know, or it's confirmed
  if (!entity || confidence === "verified" || confidence === "unknown") {
    return null;
  }

  if (confidence === "conflicting") {
    return "Caller ID can be faked. When sources disagree about a number's owner, there is a higher chance the number is being spoofed.";
  }

  // strong or possible — the entity is named but not from their own website
  return "Caller ID can be spoofed. Even when a number is associated with an organisation, verify the caller independently before sharing sensitive information.";
}

// ── Impersonation warning ────────────────────────────────────────────────────

function buildImpersonation(
  entity: string | null,
  knownImpersonation: boolean,
): string | null {
  if (!knownImpersonation || !entity) return null;
  return `This number is not published by ${entity}. It may be spoofing a legitimate organisation's identity.`;
}

// ── Formatting helpers ───────────────────────────────────────────────────────

function describeNumberType(
  numberType: string | null,
  geographic: string | null,
  country: string | null,
  network: string | null,
): string {
  const parts: string[] = [];

  if (numberType) {
    const readable = NUMBER_TYPE_LABELS[numberType.toLowerCase()] ?? numberType;
    if (country) {
      parts.push(`This is ${aOrAn(readable)} ${readable} number from ${country}.`);
    } else {
      parts.push(`This is ${aOrAn(readable)} ${readable} number.`);
    }
  }

  if (geographic) {
    parts.push(`The area code maps to ${geographic}.`);
  }

  if (network) {
    parts.push(`The number is on the ${network} network.`);
  }

  return parts.join(" ");
}

const NUMBER_TYPE_LABELS: Record<string, string> = {
  mobile: "mobile",
  landline: "landline",
  "business line (shared cost)": "local-rate service",
  "local rate": "local-rate service",
  local_rate: "local-rate service",
  "toll free": "free-call",
  free_call: "free-call",
  "premium rate": "premium-rate",
  premium: "premium-rate",
  voip: "VOIP",
  unknown: "phone",
};

function aOrAn(word: string): string {
  return /^[aeiou]/i.test(word) ? "an" : "a";
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}

function uniqueSourceTypes(evidence: IdentityEvidence[]): string {
  const types = new Set(evidence.map((e) => SOURCE_TYPE_LABELS[e.source_type] ?? e.source_type));
  const list = [...types];
  if (list.length === 1) return `from ${list[0]}`;
  if (list.length === 2) return `from ${list[0]} and ${list[1]}`;
  return `from ${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  tier_1_official: "the organisation's own website",
  tier_2_government: "government records",
  tier_3_regulatory: "regulatory registers",
  tier_4_web: "public web sources",
  tier_5_community: "community directories",
  tier_6_apollo_kb: "ApolloSG's knowledge base",
};

function distinctEntities(evidence: IdentityEvidence[]): string[] {
  const seen = new Set<string>();
  const entities: string[] = [];
  for (const e of evidence) {
    const key = e.claim.toLowerCase().trim();
    if (!seen.has(key)) {
      seen.add(key);
      entities.push(e.claim);
    }
  }
  return entities;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}


// ── Tier explanations ────────────────────────────────────────────────────────

const TIER_LABELS: Record<string, string> = {
  geographic: "Area code",
  number_block: "Number range",
  caller: "Exact number",
};

function buildTierExplanations(tiers: PrefixIntelligenceTier[]): TierExplanation[] {
  return tiers.map((t) => ({
    tier: t.tier,
    headline: t.description,
    detail: t.detail,
    qualifier: humanQualifier(t.qualifier),
    confidence: t.confidence,
    businessUnits: t.business_units ?? [],
    callback: t.callback ?? null,
    callbackNote: t.callback_note ?? null,
    location: t.location ?? null,
  }));
}

/** Turn the backend qualifier into Higgins-appropriate wording. */
function humanQualifier(qualifier: string): string {
  switch (qualifier) {
    case "regional association":
      return "Regional association";
    case "possible association":
      return "Appears to be associated";
    case "strong association":
      return "Strongly associated";
    case "verified identity":
      return "Verified";
    case "conflicting information":
      return "Conflicting information";
    default:
      return "Unknown";
  }
}

export { TIER_LABELS };
