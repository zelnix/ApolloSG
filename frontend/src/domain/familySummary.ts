// What a threat's "Send to family" shares: the result, what happened, what to do and the website or number
// involved — each whole, never cut short. Never the original message, its full links or its pictures. Pure: no React,
// no native imports.

export interface Involved { label: "Website" | "Number"; value: string }

export interface FamilySummary {
  eventId: string;
  state: string;
  result: string;
  headline: string;
  whatHappened: string;
  whatToDo: string;
  involved: Involved | null;
  caseRef: string;
  occurredAt: string;
}

/** The website or number a threat involved: a call's number, else the website's address (never the full link). */
export function involvedIn(event: { category: string; local_indicator?: string | null; indicator_host?: string | null }): Involved | null {
  if (event.category === "call" && event.local_indicator) return { label: "Number", value: event.local_indicator };
  if (event.indicator_host) return { label: "Website", value: event.indicator_host };
  return null;
}

/** A website written so a messaging app can't turn it into a tappable link: example[.]com. */
export const untappable = (host: string) => host.replace(/\./g, "[.]");

/** The text the device's share menu sends (a message, WhatsApp or an email). */
export function summaryText(s: FamilySummary, when: string): string {
  return [
    "ApolloSG: a threat on my phone",
    `Result: ${s.result}`,
    `What happened: ${s.whatHappened || s.headline}`,
    s.whatToDo ? `What to do: ${s.whatToDo}` : null,
    s.involved ? `${s.involved.label} involved: ${s.involved.label === "Website" ? `${untappable(s.involved.value)} (written so it can't be tapped)` : s.involved.value}` : null,
    `Case ${s.caseRef} · ${when}`,
    "Only this summary is shared. The original message, its links and pictures stay on my phone.",
  ].filter(Boolean).join("\n");
}

/** What Apollo sends to linked family in the app: the summary whole (backend routers/family.ShareThreatIn has the
 *  same room a Patrol record has). */
export function summaryWire(s: FamilySummary) {
  return {
    event_id: s.eventId, state: s.state, result: s.result, headline: s.headline,
    what_happened: s.whatHappened, what_to_do: s.whatToDo,
    involved_label: s.involved?.label ?? null, involved: s.involved?.value ?? null,
    case_ref: s.caseRef, occurred_at: s.occurredAt,
  };
}
