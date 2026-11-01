// The identifiers an original kept on this device records (its From, Subject and text), for one case's card.
// Read on the phone only: a submitted email's sender and subject are never synced.
import { useEffect, useState } from "react";

import { keptIdentifiers, type KeptIdentifiers } from "@/src/domain/homeHeroBrief";
import type { PatrolEvent } from "@/src/domain/types";
import { getCaseOriginal, subscribeOriginalSource } from "@/src/store/originalSource";

export function useKeptIdentifiers(event: Pick<PatrolEvent, "event_id" | "investigation_case_id">): KeptIdentifiers | null {
  const [kept, setKept] = useState<KeptIdentifiers | null>(null);
  const { event_id: eventId, investigation_case_id: caseId } = event;
  useEffect(() => {
    let active = true;
    const load = () => void (async () => {
      const src = await getCaseOriginal([eventId, caseId]);
      if (active) setKept(keptIdentifiers(src));
    })();
    load();
    const unsubscribe = subscribeOriginalSource(load);
    return () => { active = false; unsubscribe(); };
  }, [eventId, caseId]);
  return kept;
}
