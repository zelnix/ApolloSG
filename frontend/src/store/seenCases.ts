// Which cases the person has opened on this phone, for the "New" badge (domain/newCases.ts). Tracking starts the first
// time this is read; the record stays until the person deletes all their data.
import { withSeen, type SeenCases } from "@/src/domain/newCases";
import { storage } from "@/src/utils/storage";

const KEY = "apollo.seenCases.v1";
const listeners = new Set<() => void>();
let current: Promise<SeenCases> | null = null;

const save = (s: SeenCases) => storage.setItem(KEY, JSON.stringify(s));

export function readSeenCases(): Promise<SeenCases> {
  current ??= storage.getItem<string | null>(KEY, null)
    .then(async (raw) => {
      const found = raw ? (JSON.parse(raw) as SeenCases) : null;
      if (found?.startedAt) return found;
      const started: SeenCases = { startedAt: new Date().toISOString(), ids: [] };
      await save(started);
      return started;
    })
    .catch(() => ({ startedAt: new Date().toISOString(), ids: [] }));
  return current;
}

export function subscribeSeenCases(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; }

/** The person opened this case: it is no longer New. */
export async function markCaseSeen(eventId: string): Promise<void> {
  const before = await readSeenCases();
  const next = withSeen(before, eventId);
  if (next === before) return;
  current = Promise.resolve(next);
  await save(next).catch(() => undefined);
  listeners.forEach((l) => l());
}
