// The SPECIFIC thing Apollo is reacting to — read only from identifiers Apollo actually recorded
// (intake source metadata, the local indicator, the observed host, the declared brand).
//
// Nothing here is inferred, guessed or generated: if the event carries no recorded identifier, the
// helpers return null and callers keep their existing generic wording. Pure + unit-tested.

import type { ApolloState, PatrolEvent } from "./types";

export type SubjectKind =
  | "website"
  | "email_sender"
  | "message_sender"
  | "caller"
  | "app"
  | "file";

export interface ThreatSubject {
  kind: SubjectKind;
  /** The bare identifier, e.g. "paypal-secure.top", "+61 412 345 678", "WeatherPro". */
  name: string;
}

function named(value: string): string {
  return value.trim();
}

/** Reduce a link to the domain a person can recognise: no scheme, no "www.", no path or query.
 *  Input that isn't a link is returned trimmed (and clipped) so callers can pass either. */
export function shortDomain(raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim();
  if (!value) return null;
  const withoutScheme = value.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, "");
  const host = withoutScheme.split(/[/?#]/)[0].replace(/^www\./i, "").replace(/:\d+$/, "");
  if (!host) return null;
  // Only treat it as a host when it looks like one; otherwise keep the original text.
  if (/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(host)) return named(host.toLowerCase());
  return named(value);
}

/** The specific subject of this event, or null when Apollo recorded no identifier for it. */
export function threatSubject(event: PatrolEvent): ThreatSubject | null {
  const meta = event.source_metadata;
  const brand = (event.claimed_brand ?? "").trim();

  switch (event.category) {
    case "email": {
      const sender = (meta?.sender ?? "").trim() || brand;
      if (sender) return { kind: "email_sender", name: named(sender) };
      break;
    }
    case "message": {
      const sender = (meta?.sender ?? "").trim() || brand;
      if (sender) return { kind: "message_sender", name: named(sender) };
      break;
    }
    case "call": {
      const caller = (event.local_indicator ?? "").trim() || (meta?.sender ?? "").trim();
      if (caller) return { kind: "caller", name: named(caller) };
      break;
    }
    case "file": {
      const file = (meta?.attachment_names ?? []).find((n) => !!n && n.trim().length > 0);
      if (file) return { kind: "file", name: named(file) };
      break;
    }
    case "app": {
      if (brand) return { kind: "app", name: named(brand) };
      break;
    }
    default:
      break;
  }

  // Any category can carry a recorded destination — a link, a sinkholed host, a blocked domain.
  const host = shortDomain(meta?.url ?? event.local_indicator ?? event.indicator_host);
  if (host) return { kind: "website", name: host };
  if (brand) return { kind: "message_sender", name: named(brand) };
  return null;
}

/** How the subject reads inside a sentence: "paypal-secure.top", "the email from billing@x.co". */
export function subjectDescriptor(subject: ThreatSubject): string {
  switch (subject.kind) {
    case "website": return subject.name;
    case "email_sender": return `the email from ${subject.name}`;
    case "message_sender": return `the text from ${subject.name}`;
    case "caller": return `the call from ${subject.name}`;
    case "app": return subject.name;
    case "file": return `the file ${subject.name}`;
  }
}

/** Apollo's state headline, naming the actual subject when one was recorded.
 *  e.g. "Apollo is growling at paypal-secure.top". Falls back to the plain state line. */
export function stateHeadline(state: ApolloState, event: PatrolEvent | null | undefined): string {
  const subject = event ? threatSubject(event) : null;
  const what = subject ? subjectDescriptor(subject) : null;
  switch (state) {
    case "biting":   return what ? `Apollo is biting ${what}` : "Apollo is biting";
    case "barking":  return what ? `Apollo is barking at ${what}` : "Apollo is barking";
    case "growling": return what ? `Apollo is growling at ${what}` : "Apollo is growling";
    case "ears_up":  return what ? `Apollo is sniffing ${what}` : "Apollo is sniffing something";
    case "sniffing": return what ? `Apollo is checking ${what}` : "Apollo is sniffing";
    default:         return "Apollo is Patrolling";
  }
}

/** Row label for lists: names the subject with the kind of thing it is, e.g. "From: billing@acme.co",
 *  "Caller: +61 412 345 678", "paypal-secure.top". null when Apollo recorded no identifier. */
export function subjectRowLabel(event: PatrolEvent): string | null {
  const subject = threatSubject(event);
  if (!subject) return null;
  switch (subject.kind) {
    case "website": return subject.name;
    case "email_sender":
    case "message_sender": return `From: ${subject.name}`;
    case "caller": return `Caller: ${subject.name}`;
    case "app": return `App: ${subject.name}`;
    case "file": return `File: ${subject.name}`;
  }
}

/** Short subject label for cards and notification titles — no sentence wrapper. */
export function subjectLabel(event: PatrolEvent): string | null {
  const subject = threatSubject(event);
  return subject ? subject.name : null;
}
