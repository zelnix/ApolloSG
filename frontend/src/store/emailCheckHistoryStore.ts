// Enhanced, on-device history for email checks. Stores richer metadata than the
// generic checkHistoryStore — subject, sender, account attribution, event linkage — so
// the "Your Recent Checks" section can display meaningful, filterable entries.
import type { ApolloState } from "@/src/domain/types";
import { storage } from "@/src/utils/storage";

export interface EmailCheckEntry {
  id: string;
  at: string;
  state: ApolloState;
  summary: string;
  subject?: string;
  sender?: string;
  account?: string;
  eventId?: string;
  scenario?: string;
}

const KEY = "apollo.email_checks.v1";
const CAP = 30;

async function read(): Promise<EmailCheckEntry[]> {
  const raw = await storage.getItem<string | null>(KEY, null);
  if (!raw) return [];
  try { return JSON.parse(raw) as EmailCheckEntry[]; } catch { return []; }
}

/** List email checks, optionally filtered by receiving account. */
export async function listEmailChecks(account?: string | null): Promise<EmailCheckEntry[]> {
  const all = await read();
  if (!account) return all;
  return all.filter((e) => e.account?.toLowerCase() === account.toLowerCase());
}

/** Record a completed email check. */
export async function recordEmailCheck(entry: EmailCheckEntry): Promise<void> {
  const prior = await read();
  const merged = [entry, ...prior.filter((e) => e.id !== entry.id)].slice(0, CAP);
  await storage.setItem(KEY, JSON.stringify(merged));
}

/** The person deleted these cases: their email check entries go with them. */
export async function forgetEmailChecks(eventIds: string[]): Promise<void> {
  const gone = new Set(eventIds);
  const prior = await read();
  const kept = prior.filter((e) => !e.eventId || !gone.has(e.eventId));
  if (kept.length !== prior.length) await storage.setItem(KEY, JSON.stringify(kept));
}
