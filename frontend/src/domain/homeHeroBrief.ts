// The Home hero's two-line Higgins briefing, one per thing Apollo wants the person to see:
//   Line 1: {Type}: {subject/identifier} from {source}, detected as {finding}.
//   Line 2: {date/time}. {Higgins' recommended action}.
// Read only from the case's authoritative record: its Higgins Case Briefing (Higgins Triage → TC FlyBy → Magnum DI
// when warranted → Evidence Lock → Higgins Luddish) when it has one, else what Higgins Triage recorded. Nothing is
// added: a part Apollo didn't record is left out, and long identifiers are shortened to keep the two lines. The full
// explanation, steps and evidence stay in the Threat Case the card opens. Pure: no React, unit-tested.
import type { AttentionItem } from "./homeAttention";
import { emailRecord, isEmailCase, NOT_PROVIDED } from "./emailRecord.ts";
import type { HomeVoice } from "./higginsHomeVoice";
import { sentences } from "./luddish/patterns.ts";
import { firstReason, incompleteOnly, reasonInSentence, say } from "./luddish/present.ts";
import { looksLikeInternalCode } from "./messageVoice.ts";
import { shortDomain } from "./threatSubject.ts";
import type { ApolloState, PatrolEvent } from "./types";
import type { OriginalSource } from "../store/originalSource";

export interface HeroBrief {
  id: string;
  line1: string;
  line2: string;
  /** The Threat Case (or protection) the card opens. */
  route?: string;
}

/** The identifiers an original kept on this device records: its From, Subject and Received headers (its saved fields,
 *  else the header lines its text carries), its text, and whether it is an email. */
export interface KeptIdentifiers { sender: string | null; subject: string | null; text: string | null; received?: string | null; email?: boolean }
export function keptIdentifiers(src: Pick<OriginalSource, "fields" | "text"> & Partial<Pick<OriginalSource, "kind">> | null | undefined): KeptIdentifiers | null {
  if (!src) return null;
  const record = emailRecord(null, src);
  return { sender: record.sender, subject: record.subject, text: clean(src.text) || null, received: record.received, email: src.kind === "email" };
}

const TYPE: Record<string, string> = {
  email: "Email", message: "Text message", call: "Call", link: "Link", website: "Website", known_threat: "Website",
  protection: "Website", file: "File", app: "App", account: "Account", connection: "Connection", system: "Device",
  device: "Device", family: "Family alert",
};

const clean = (v: string | null | undefined) => (v ?? "").replace(/\s+/g, " ").trim();
/** Shortened to `max` characters, cut at a word where one is close, with "…". */
export function clip(value: string | null | undefined, max: number): string | null {
  const v = clean(value);
  if (!v) return null;
  if (v.length <= max) return v;
  const cut = v.slice(0, max - 1);
  // Cut at a word: drop a half-cut last word, unless the cut already falls between words.
  const word = /\s/.test(v.charAt(max - 1)) ? cut : cut.replace(/\s+\S*$/, "");
  return `${(word.length >= max * 0.6 ? word : cut).replace(/[\s,.;:–—-]+$/, "")}…`;
}
const quoted = (v: string | null | undefined, max: number) => { const c = clip(v, max); return c ? `\u201C${c}\u201D` : null; };
const noStop = (v: string) => v.replace(/[.!?…]+$/, "").trim();

/** A text or a call always says which number it came from; when Apollo wasn't given one, it says so — tightly on
 *  the hero, in full where there's room. */
const NO_NUMBER = "\u0000no-number";
const NO_NUMBER_SAID: Record<"hero" | "card", string> = { hero: "no # found", card: "no number found" };

/** How long each identifier may run: the hero's two glanceable lines are tight; a card (Important for you, search)
 *  shows every identifier whole and lets the layout wrap it. */
export type BriefRoom = "hero" | "card";
const WHOLE = Number.MAX_SAFE_INTEGER;
const LIMIT: Record<BriefRoom, { sender: number; subject: number; emailSubject: number; preview: number; number: number; name: number; headline: number }> = {
  hero: { sender: 28, subject: 30, emailSubject: 32, preview: 28, number: 24, name: 30, headline: 40 },
  card: { sender: WHOLE, subject: WHOLE, emailSubject: WHOLE, preview: WHOLE, number: WHOLE, name: WHOLE, headline: WHOLE },
};

/** What the case is about and where it came from, from the identifiers Apollo recorded — on the case, else in the
 *  original kept on this device (an email or text you submitted keeps its sender only there). */
function identify(e: PatrolEvent, kept: KeptIdentifiers | null, room: BriefRoom): { what: string | null; from: string | null } {
  const n = LIMIT[room];
  const m = e.source_metadata;
  const sender = clip(m?.sender ?? kept?.sender, n.sender);
  const subject = clip(e.case_briefing?.subject, n.subject);
  const host = shortDomain(m?.url ?? e.local_indicator ?? e.indicator_host);
  switch (e.category) {
    case "message": return { what: quoted(m?.preview ?? kept?.text, n.preview) ?? subject, from: sender ?? NO_NUMBER };
    case "call": return { what: null, from: clip(e.local_indicator, n.number) ?? sender ?? NO_NUMBER };
    case "file": return { what: clip(m?.attachment_names?.find((f) => clean(f)), n.name) ?? subject, from: sender };
    case "app": return { what: clip(e.claimed_brand, n.name) ?? subject, from: null };
    case "link": case "website": case "known_threat": case "protection": return { what: host ?? subject, from: null };
    default: {
      const headline = say(e.headline, true);
      return { what: host ?? subject ?? (headline ? clip(headline, n.headline) : null), from: null };
    }
  }
}

/** The finding, said as the case recorded it: its Case Briefing's status, else what Apollo itself recorded. */
const STATUS_FINDING: Record<string, string> = {
  "likely scam": "detected as a likely scam",
  "confirmed scam or threat": "detected as a confirmed scam or threat",
  concerning: "detected as concerning",
  "unable to determine": "not confirmed safe",
  "no scam indicators found": "no scam signs found",
};
const blocked = (e: PatrolEvent) => !!(e.verified_block && e.enforcement_evidence);
const investigating = (e: PatrolEvent) => !!(e.investigation_case_id ?? e.patrol_record?.investigationCaseId) && !e.investigation_completed_at;

/** What the state means, when Apollo recorded nothing more specific (never a posture such as "flagged"). */
const STATE_FINDING: Partial<Record<ApolloState, string>> = {
  biting: "blocked by Apollo", barking: "looks like a scam", growling: "has a warning sign", ears_up: "is being looked at",
  sniffing: "is being checked",
};

function finding(e: PatrolEvent): string {
  // The case result's verdict — the one the Findings Brief shows (caseBriefing.caseResult).
  const status = clean(e.case_briefing?.verdict ?? e.case_briefing?.status).toLowerCase();
  if (status) return STATUS_FINDING[status] ?? `detected as ${status}`;
  if (blocked(e)) return "blocked by Apollo";
  if (incompleteOnly(e)) return "not every check could run";
  if (e.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE") return "not confirmed safe";
  // The first concrete thing Apollo recorded about it ("asks for a one-time code"), in Luddish.
  const reason = firstReason(e);
  if (reason) return reasonInSentence(reason);
  return STATE_FINDING[e.state] ?? "checked by Apollo";
}

/** Higgins' recommendation for the case: its Case Briefing's recommended action, else Apollo's own first step. */
const HERO_STEP = 70;
function action(e: PatrolEvent, room: BriefRoom): string {
  const recommended = say(e.case_briefing?.recommendedAction?.label, true);
  if (recommended) return noStop(recommended);
  if (blocked(e)) return "No action needed";
  if (investigating(e)) return "Be careful until Higgins has finished";
  if (clean(e.case_briefing?.verdict ?? e.case_briefing?.status).toLowerCase() === "no scam indicators found") return "No action needed";
  // Apollo's own first step, whole. The hero's second line has room for about two rows: a longer step stays in the
  // case, and the hero points there instead of cutting it short.
  const step = sentences(say(e.what_to_do, true))[0];
  if (step && !looksLikeInternalCode(step) && (room === "card" || step.length <= HERO_STEP)) return noStop(step);
  return step ? "See Higgins' steps in the case" : "Open the case to see what Apollo found";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "28 Oct, 4:42 pm" (the year only when it isn't this year), in the device's local time. */
export function heroWhen(iso: string | null | undefined, now: Date = new Date()): string {
  const d = new Date(iso ?? "");
  if (isNaN(d.getTime())) return "";
  const h = d.getHours();
  const year = d.getFullYear() !== now.getFullYear() ? ` ${d.getFullYear()}` : "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year}, ${h % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

/** One case as two lines: the hero's, or (room "card") an "Important for you" card's, with longer identifiers. */
export function eventBrief(e: PatrolEvent, now: Date = new Date(), kept: KeptIdentifiers | null = null, room: BriefRoom = "hero"): HeroBrief {
  const route = `/patrol/${encodeURIComponent(e.event_id)}`;
  if (isEmailCase(e) || kept?.email) {
    // An email always says who sent it, its subject and when it arrived — the same record the Threat Case shows.
    const n = LIMIT[room];
    const sender = clip(kept?.sender ?? e.source_metadata?.sender, n.sender);
    const subject = quoted(kept?.subject ?? e.source_metadata?.subject, n.emailSubject);
    const received = clean(kept?.received ?? e.source_metadata?.received_at);
    const line1 = `Email: ${subject ?? "Subject not provided"}${sender ? ` from ${sender}` : ", sender not provided"}, ${finding(e)}.`;
    return { id: `event:${e.event_id}`, line1, line2: `Received: ${received ? heroWhen(received, now) || received : NOT_PROVIDED}. ${action(e, room)}.`, route };
  }
  const { what, from } = identify(e, kept, room);
  const type = TYPE[e.category] ?? "Security check";
  const source = from === NO_NUMBER ? ` (${NO_NUMBER_SAID[room]})` : from ? ` from ${from}` : "";
  const line1 = `${type}${what ? `: ${what}` : ""}${source}${what || from ? "," : ""} ${finding(e)}.`;
  const when = heroWhen(e.occurred_at, now);
  return { id: `event:${e.event_id}`, line1, line2: `${when ? `${when}. ` : ""}${action(e, room)}.`, route };
}

/** The cases the hero shows, in order: the one Apollo is reacting to first, then every other case needing the person. */
export function heroEvents(attention: AttentionItem[], drivingEvent: PatrolEvent | null, state: ApolloState): PatrolEvent[] {
  const events = attention.filter((a) => a.kind === "event" && a.event).map((a) => a.event!);
  return drivingEvent && !events.some((e) => e.event_id === drivingEvent.event_id) && state !== "resting" ? [drivingEvent, ...events] : events;
}

/** Everything the hero cycles through: the cases (see heroEvents), then protection problems (never called threats).
 *  With nothing to show, Apollo's own status in two lines. `kept` holds each case's kept-original identifiers. */
export function buildHeroBriefs(input: {
  voice: HomeVoice; attention: AttentionItem[]; drivingEvent: PatrolEvent | null; state: ApolloState;
  kept?: Record<string, KeptIdentifiers | null>; now?: Date;
}): HeroBrief[] {
  const { voice, attention, drivingEvent, state, kept = {}, now = new Date() } = input;
  const briefs = heroEvents(attention, drivingEvent, state).map((e) => eventBrief(e, now, kept[e.event_id] ?? null));
  for (const g of attention.filter((a) => a.kind === "gate")) {
    briefs.push({ id: g.id, line1: `${noStop(g.title)}.`, line2: `Not a security threat. ${noStop(g.actionLabel)}.`, route: g.route });
  }
  if (briefs.length) return briefs;
  if (state === "resting") {
    return [{ id: "status", line1: "No security threats detected.", line2: "Apollo is keeping watch. No action needed.", route: voice.ctaRoute }];
  }
  const said = sentences(clean(voice.text));
  return [{ id: "status", line1: said[0] ?? clean(voice.text), line2: said.slice(1).join(" ") || `${noStop(voice.ctaLabel)}.`, route: voice.ctaRoute }];
}
