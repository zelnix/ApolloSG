// Whether a case should show "New": it arrived since tracking started and the person hasn't opened it yet.
import { useCallback, useEffect, useState } from "react";

import { isNewCase, type SeenCases } from "@/src/domain/newCases";
import type { PatrolEvent } from "@/src/domain/types";
import { readSeenCases, subscribeSeenCases } from "@/src/store/seenCases";

export function useNewCases(): (e: Pick<PatrolEvent, "event_id" | "occurred_at">) => boolean {
  const [seen, setSeen] = useState<SeenCases | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => void readSeenCases().then((s) => { if (live) setSeen(s); });
    load();
    const off = subscribeSeenCases(load);
    return () => { live = false; off(); };
  }, []);
  return useCallback((e) => isNewCase(e, seen), [seen]);
}
