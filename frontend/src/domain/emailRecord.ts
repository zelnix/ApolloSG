// One email record for Home and the Threat Case alike: that it is an email, who sent it, its subject and when it
// arrived — read from what the case recorded (the copy kept on this phone first, then what ApolloSG recorded at
// intake), and "Not provided" wherever neither recorded it. Never "Not captured", and an email is never shown as a
// text message. Pure: no React, no storage, unit-tested in node.
import { headerFields } from "./evidencePresentation.ts";
import type { OriginalSource } from "../store/originalSource";
import type { PatrolEvent } from "./types";

/** What is shown where an email's sender, subject or received date was genuinely not recorded. */
export const NOT_PROVIDED = "Not provided";

export interface EmailRecord { sender: string | null; subject: string | null; received: string | null }

type EmailHints = Partial<Pick<PatrolEvent, "category" | "source_metadata" | "evidence_profile">>;

/** The case is about an email when anything it recorded says so: the kept original, the record, its evidence or the
 *  investigation's gate. One "email" settles it — a server record that filed the text as "text" never makes it an SMS. */
export function isEmailCase(event?: EmailHints | null, original?: Pick<OriginalSource, "kind"> | null, gates?: readonly string[] | null): boolean {
  return original?.kind === "email" || event?.category === "email" || event?.source_metadata?.type === "email"
    || event?.evidence_profile?.type === "email" || !!gates?.includes("email");
}

const clean = (v: string | null | undefined) => (v ?? "").replace(/\s+/g, " ").trim() || null;

/** Each part from the kept original when it holds it, else from the record; null where neither does. */
export function emailRecord(event?: Pick<PatrolEvent, "source_metadata"> | null, original?: Pick<OriginalSource, "fields" | "text"> | null): EmailRecord {
  const fields = original ? headerFields(original) : [];
  const field = (re: RegExp) => clean(fields.find((f) => re.test(f.label.trim()) && clean(f.value))?.value);
  const m = event?.source_metadata;
  return {
    sender: field(/^(from|sender)$/i) ?? clean(m?.sender),
    subject: field(/^subject$/i) ?? clean(m?.subject),
    received: field(/^(received|date)$/i) ?? clean(m?.received_at),
  };
}

/** The email's two summary lines, each always present. */
export function emailLines(record: EmailRecord): string[] {
  return [`From: ${record.sender ?? NOT_PROVIDED}`, `Subject: ${record.subject ?? NOT_PROVIDED}`];
}
