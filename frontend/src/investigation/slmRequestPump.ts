/** One application-owned executor for the existing server-issued SLM inbox.
 * Navigation does not own inference. SSE and inbox delivery share one request ID.
 */
import { AppState } from "react-native";
import { apiGet } from "@/src/api/client";
import { getDeviceToken } from "@/src/auth/deviceIdentity";
import { getSharedSLM } from "@/src/domain/slm/sharedRuntime";
import { submitIssuedAdvisory, type Issued } from "@/src/domain/slm/slmTransport";

let running = false;
let wake: (() => void) | null = null;
export function wakeSLMRequestPump(): void { wake?.(); }
export function startSLMRequestPump(): () => void {
  if (running) return () => undefined;
  running = true;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let busy = false;
  const attempts = new Map<string, { count: number; expiresAt: number }>();
  const poll = async () => {
    if (busy || stopped) return;
    busy = true;
    try {
      const runtime = getSharedSLM();
      if (stopped || !runtime || AppState.currentState !== "active" || !await getDeviceToken()) return;
      const { items } = await apiGet<{ items: Issued[] }>("/investigations/slm/pending");
      for (const issued of items) {
        if (stopped || Date.parse(issued.expiresAt) <= Date.now()) break;
        for (const [key, value] of attempts) if (value.expiresAt <= Date.now()) attempts.delete(key);
        const previous = attempts.get(issued.request.requestId);
        if ((previous?.count ?? 0) >= 2) continue;
        attempts.set(issued.request.requestId, { count: (previous?.count ?? 0) + 1, expiresAt: Date.parse(issued.expiresAt) });
        await submitIssuedAdvisory(issued.request.caseId, issued, runtime);
      }
    } catch { /* Same outstanding request remains recoverable; no replacement case or model. */ }
    finally { busy = false; if (!stopped) timer = setTimeout(() => { void poll(); }, 1000); }
  };
  wake = () => { if (timer) clearTimeout(timer); void poll(); };
  void poll();
  return () => { stopped = true; running = false; wake = null; if (timer) clearTimeout(timer); };
}
