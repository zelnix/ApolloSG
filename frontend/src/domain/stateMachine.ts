// Apollo six-state machine (sniffing is transient and never persisted as an event state).
// Escalation is immediate on evidence. Recovery to Patrolling is slow and strict:
// it requires (a) no active events, (b) a fresh verification after the most
// recent escalation was resolved, and (c) visibility not lost.

import type { ApolloState, PatrolEvent, Visibility } from "./types";
import { eventHasPacketProof } from './packetEvidence.ts';
import { areaLabel } from './messageVoice.ts';

export const STATE_RANK: Record<ApolloState, number> = { sniffing: 0, resting: 0, ears_up: 1, growling: 2, barking: 3, biting: 4 };

const capitalise = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** How recent a verification must be to permit returning to Patrolling. */
export const VERIFICATION_FRESHNESS_MS = 10 * 60 * 1000;
/** After an event resolves, Apollo stays alert until a fresh verification lands. */
export const RECOVERY_COOLDOWN_MS = 2 * 60 * 1000;

export interface StateInput {
  events: PatrolEvent[];
  visibility: Visibility;
  lastVerifiedAt: string | null;
  /** True when the platform genuinely supports enforcement (VPN/DNS filtering).
   *  When false and visibility is "none", it's a platform limitation, not visibility loss.
   *  Defaults to true when not specified (backward-compatible). */
  platformCanEnforce?: boolean;
  now?: number;
}

export interface StateResolution {
  state: ApolloState;
  /** Why Apollo is in this state, in plain language. */
  reason: string;
  /** Deep-link route the user should open to address the reason, if any. */
  reasonRoute?: string;
  /** True when Apollo has no active event but is waiting on fresh verification. */
  recovering: boolean;
  /** True when Patrolling cannot be shown truthfully because visibility is lost. */
  visibilityLost: boolean;
  /** True when the platform fundamentally cannot run enforcement (web preview, unsupported OS).
   *  Platform limitations are informational — never treated as failures or threats. */
  platformLimited: boolean;
  drivingEvent: PatrolEvent | null;
}

export function isActive(e: PatrolEvent): boolean {
  return e.status === "active" || (e.status === "blocked" && e.state === "biting" && !e.resolved_at);
}

export function resolveApolloState(input: StateInput): StateResolution {
  const now = input.now ?? Date.now();
  // ISOLATION: Sample Check events never affect the real protection state, threat counts or alerts.
  const active = input.events.filter((e) => isActive(e) && e.origin !== "sample_check");
  const verifiedAt = input.lastVerifiedAt ? Date.parse(input.lastVerifiedAt) : 0;
  const verificationFresh = verifiedAt > 0 && verifiedAt <= now && now - verifiedAt <= VERIFICATION_FRESHNESS_MS;
  const visibilityLost = input.visibility === 'none' || !verificationFresh;
  const platformCanEnforce = input.platformCanEnforce !== false; // default true for backward compat

  // ── Event-driven escalation always takes priority over visibility status ──

  // Biting only if a verified block exists. Never inferred.
  const biting = active.find((e) => e.state === "biting" && e.verified_block && eventHasPacketProof(e) &&
    Date.parse(e.occurred_at) <= now && now - Date.parse(e.occurred_at) < RECOVERY_COOLDOWN_MS);
  if (biting) {
    return { state: "biting", reason: "Apollo verified and blocked a threat.", recovering: false, visibilityLost: false, platformLimited: false, drivingEvent: biting };
  }

  // Barking — a confirmed threat requires the user's action. No time-based downgrade:
  // a genuinely unresolved threat stays barking until resolved, regardless of age.
  // Only active (unresolved) barking events with real evidence qualify.
  const barking = active
    .filter((e) => e.state === "barking")
    .sort(byNewest)[0];
  if (barking) {
    return { state: "barking", reason: `${capitalise(areaLabel(barking.category))} needs your decision.`, reasonRoute: `/patrol/${encodeURIComponent(barking.event_id)}`, recovering: false, visibilityLost, platformLimited: !platformCanEnforce, drivingEvent: barking };
  }

  const growling = active.filter((e) => e.state === "growling").sort(byNewest)[0];
  if (growling) {
    return { state: "growling", reason: `${capitalise(areaLabel(growling.category))} looks suspicious and isn't confirmed yet.`, reasonRoute: `/patrol/${encodeURIComponent(growling.event_id)}`, recovering: false, visibilityLost, platformLimited: !platformCanEnforce, drivingEvent: growling };
  }
  const earsUp = active.filter((e) => e.state === "ears_up").sort(byNewest)[0];
  if (earsUp) {
    return { state: "ears_up", reason: `${capitalise(areaLabel(earsUp.category))} is worth a careful look.`, reasonRoute: `/patrol/${encodeURIComponent(earsUp.event_id)}`, recovering: false, visibilityLost, platformLimited: !platformCanEnforce, drivingEvent: earsUp };
  }

  // ── No active events driving escalation — check visibility, then recovery ──

  // Platform limitation: the device simply cannot run enforcement (web preview, unsupported OS).
  // This is NOT visibility loss — it's a platform characteristic. Apollo should rest, not growl.
  if (visibilityLost && !platformCanEnforce) {
    return {
      state: "resting",
      reason: "Apollo is watching the areas this device allows. Some features are not supported on this device.",
      recovering: false,
      visibilityLost: false,
      platformLimited: true,
      drivingEvent: null,
    };
  }

  // Genuine visibility loss: the platform CAN enforce but protection cannot be verified right now.
  // This is a PROTECTION STATUS issue, not a security threat — Apollo stays resting.
  // The visibilityLost flag allows downstream messaging to explain reduced protection.
  if (visibilityLost) return {
    state: "resting",
    reason: input.visibility === 'none' ? 'Protection is unavailable or unverified.' : 'Protection observation has expired.',
    reasonRoute: '/(tabs)/protection',
    recovering: false, visibilityLost: true, platformLimited: false, drivingEvent: null,
  };

  // No active events. Recovery rules apply.
  const recentlyResolved = input.events
    .filter((e) => e.resolved_at && e.state !== "resting")
    .sort((a, b) => Date.parse(b.resolved_at!) - Date.parse(a.resolved_at!))[0];

  if (recentlyResolved) {
    const resolvedAt = Date.parse(recentlyResolved.resolved_at!);
    const withinCooldown = now - resolvedAt < RECOVERY_COOLDOWN_MS;
    const verifiedAfterResolve = verifiedAt > resolvedAt;
    if (withinCooldown || !verifiedAfterResolve) {
      // Recovery period: the threat is resolved, so Apollo rests. The recovering flag
      // allows Higgins to mention the recent resolution without changing threat state.
      return {
        state: "resting",
        reason: "A recent event was resolved. Apollo is waiting for a fresh check before returning to patrol.",
        recovering: true,
        visibilityLost: false,
        platformLimited: false,
        drivingEvent: recentlyResolved,
      };
    }
  }

  if (!verificationFresh) {
    // Stale verification is a protection-health condition, not a security threat.
    return { state: "resting", reason: "Apollo has not verified protection recently. A fresh check is needed.", recovering: true, visibilityLost: false, platformLimited: false, drivingEvent: null };
  }
  return {
    state: "resting",
    reason: input.visibility === "limited" ? "Protection observed within its limited coverage. Earlier incidents remain in Patrol." : "Protection was freshly observed. Earlier incidents remain in Patrol.",
    recovering: false,
    visibilityLost: false,
    platformLimited: false,
    drivingEvent: null,
  };
}

function byNewest(a: PatrolEvent, b: PatrolEvent) {
  return Date.parse(b.occurred_at) - Date.parse(a.occurred_at);
}

/** Guard for transitions requested by user or adapter. Returns the allowed next state or null. */
export function canTransition(event: PatrolEvent, next: ApolloState, opts: { verifiedBlock?: boolean } = {}): boolean {
  if (next === "biting") return opts.verifiedBlock === true; // never infer biting
  if (STATE_RANK[next] > STATE_RANK[event.state]) return true; // escalation is always allowed
  if (event.state === "biting" && next !== "resting") return false; // biting only resolves fully
  return true;
}
