// Home "attention" model. Turns the REAL gate states and active Patrol events into a short list of
// specific, actionable issues — so Home can name exactly which gate is affected, what the problem is,
// what Higgins recommends, and the one action to take. No new text is invented: problem text comes
// from the gate's own currentHelp / the event's what_happened, and the recommendation from the gate
// limitation / the event's what_to_do. Pure and unit-tested.
import type { GatePresentation } from "./gates";
import type { EventCategory, PatrolEvent } from "./types";
import { briefed, needsYou } from "./caseBriefing.ts";
import { isActive } from "./stateMachine.ts";
import { incompleteOnly, presentEvent, say } from "./luddish/present.ts";

export interface AttentionItem {
  id: string;
  kind: "gate" | "event";
  /** Names the affected protection, e.g. "Internet monitoring". */
  gate: string;
  /** Short heading, e.g. "Internet monitoring needs attention". */
  title: string;
  /** The specific problem, from real gate/event data. */
  problem: string;
  /** Higgins' recommended next step, from real gate/event data. */
  higgins: string;
  actionLabel: string;
  route: string;
  /** Present for event items so the UI can offer Dismiss. */
  event?: PatrolEvent;
}

// Which gate a Patrol event belongs to (for naming the affected gate on Home).
const GATE_FOR_CATEGORY: Record<EventCategory, string> = {
  link: "Link checking", website: "Website protection", known_threat: "Website protection", protection: "Website protection",
  connection: "Internet monitoring", system: "Device monitoring", device: "Device monitoring", message: "Message screening",
  call: "Call screening", app: "App checking", account: "Account alerts", email: "Email monitoring", file: "File checking",
  family: "Family alert",
};
const gateForCategory = (c: EventCategory | string) => GATE_FOR_CATEGORY[c as EventCategory] ?? "a security check";

/** Short event description using real evidence — avoids generic "Email monitoring". */
function describeEventBrief(e: PatrolEvent): string {
  const cat = e.category;
  const indicator = e.indicator_host || "";
  const brand = e.claimed_brand || "";
  const sender = brand || indicator;
  if (cat === "email" && sender) return `Email from ${sender}`;
  if (cat === "call" && indicator) return `Call from ${indicator}`;
  if (cat === "message" && sender) return `Text from ${sender}`;
  if ((cat === "link" || cat === "website" || cat === "known_threat") && indicator)
    return `Site: ${indicator.length > 40 ? indicator.slice(0, 39) + "…" : indicator}`;
  const hl = (e.headline || "").trim();
  if (hl && hl.length <= 50) return hl;
  return gateForCategory(cat);
}

// Where the action for a gate issue should take the person.
const GATE_ROUTE: Record<string, string> = {
  site: "/gates", text: "/text-guard", call: "/call-guard", network: "/network", email: "/email",
  link: "/check", account: "/account", file: "/file", app: "/app-check", device: "/device",
};

/** Build the ordered list of things that genuinely need the person's attention right now.
 *  Order: verified gate failures first (protection actually stopped), then active events that need a
 *  decision (barking), then active concerns Apollo is still assessing (growling and ears_up — e.g.
 *  a suspected scam text, an insecure connection, a device setting change). Optional setup is
 *  deliberately NOT included — it is not an alarm. */
export function buildHomeAttention(input: { gates: GatePresentation[]; events: PatrolEvent[] }): AttentionItem[] {
  const items: AttentionItem[] = [];

  // Gate issues are protection-health concerns — they belong in the Protection Status card,
  // NOT mixed into the security findings list. We include them in the full attention list
  // only for backwards compatibility, but callers should use buildSecurityFindings() and
  // buildProtectionIssues() for proper separation.

  // 1) Gates in a verified "Action needed" state (protection-health issue).
  for (const g of input.gates) {
    if (g.tone !== "action") continue;
    const limitation = g.capability.automatic?.limitation;
    const higgins = limitation ?? (g.primaryAction ? `${g.primaryAction.label} to restore protection.` : "Open the protection to restore coverage.");
    items.push({
      id: `gate:${g.id}`,
      kind: "gate",
      gate: g.title,
      title: `${g.title} needs attention`,
      problem: g.currentHelp,
      higgins,
      actionLabel: g.primaryAction?.label ?? "Open protection",
      route: GATE_ROUTE[g.id] ?? "/gates",
    });
  }

  // 2) Active events — any state that Apollo is reacting to and the person should see.
  //    barking = needs a decision (highest), growling / ears_up = Apollo is unsure and worth a look.
  const activeAttention = input.events
    // A check that couldn't run is not a threat: it is never an attention item.
    .filter((e) => isActive(e) && !incompleteOnly(e) && (e.state === "barking" || e.state === "growling" || e.state === "ears_up"))
    .sort((a, b) => {
      const rank = (s: typeof a.state) => (s === "barking" ? 3 : s === "growling" ? 2 : s === "ears_up" ? 1 : 0);
      const r = rank(b.state) - rank(a.state);
      return r !== 0 ? r : Date.parse(b.occurred_at) - Date.parse(a.occurred_at);
    });
  for (const e of activeAttention) {
    const gate = gateForCategory(e.category);
    // A case with a Higgins Case Briefing is described by it — its headline names the organisation and what was
    // checked, its summary every material subject and what is still unresolved — never by generic Patrol text.
    const briefing = briefed(e);
    const shown = presentEvent(e);
    const problem = shown.summary || shown.title;
    const decision = needsYou(e);
    const higgins = (decision && briefing?.actionReason
      ? [say(briefing.actionReason), shown.whatToDo].filter(Boolean).join(" ")
      : shown.whatToDo)
      || "Review this finding. I'll explain what Apollo discovered and whether you need to take action.";
    // Build an evidence-specific title rather than generic "Email Gate looks suspicious".
    const specificLabel = briefing ? shown.title : describeEventBrief(e);
    // "needs your decision" only when the case owes the person one, with its concrete reason.
    const title = decision
      ? `${specificLabel} — needs your decision`
      : e.state === "growling" || e.state === "barking"
        ? `${specificLabel} — flagged by Apollo`
        : `${specificLabel} — worth a look`;
    items.push({
      id: `event:${e.event_id}`,
      kind: "event",
      gate,
      title,
      problem: problem || "Apollo flagged something that needs your attention.",
      higgins,
      actionLabel: "Open investigation",
      route: `/patrol/${encodeURIComponent(e.event_id)}`,
      event: e,
    });
  }

  return items;
}

/** Security findings only — active events with evidence-backed concerns.
 *  These belong on Home (prioritised) and in Threats → Investigations. */
export function buildSecurityFindings(input: { gates: GatePresentation[]; events: PatrolEvent[] }): AttentionItem[] {
  return buildHomeAttention(input).filter((a) => a.kind === "event");
}

/** Protection-health issues only — gate failures, disabled protections, setup needs.
 *  These belong in the Protection Status card and Protection screen, NOT in threat alerts. */
export function buildProtectionIssues(input: { gates: GatePresentation[]; events: PatrolEvent[] }): AttentionItem[] {
  return buildHomeAttention(input).filter((a) => a.kind === "gate");
}
