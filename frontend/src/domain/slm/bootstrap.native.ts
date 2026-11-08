/** Native-only Luddish startup. Only a test-device GGUF already in app
 * private documents can enable the shared runtime. No auto-downloads.
 * The one instance services Ask Higgins and all investigation roles.
 */
import * as Device from "expo-device";
import { File, FileMode, Paths } from "expo-file-system";
import { CANDIDATE_FILE, verifyPrivateGGUF } from "./modelAdmission.ts";
import { createLuddishOnDevice } from "./llamaRnBinding.native.ts";
import { getSharedSLM, setSharedSLM } from "./sharedRuntime.ts";
import type { LocalLlamaRuntime } from "./llamaRnRuntime.ts";

let runtime: LocalLlamaRuntime | null = null;
let startup: Promise<boolean> | null = null;

export function startSharedLuddish(): Promise<boolean> {
  // Candidate model has not cleared product safety or physical-device QA.
  if (!__DEV__) return Promise.resolve(false);
  if (runtime) return Promise.resolve(true);
  if (startup) return startup;
  startup = (async () => {
    const file = new File(Paths.document, CANDIDATE_FILE);
    const admitted = await verifyPrivateGGUF({
      uri: file.uri, exists: file.exists, size: file.size,
      open: () => file.open(FileMode.ReadOnly),
    }, Device.totalMemory ?? null);
    if (!admitted.available) return false;
    const created = createLuddishOnDevice({
      modelUri: admitted.uri, modelId: admitted.modelId,
      deviceAdmitted: true,
    });
    if (!created) return false;
    runtime = created;
    setSharedSLM(created);
    return true;
  })().catch(() => false).finally(() => { startup = null; });
  return startup;
}

/** Explicit local test provisioning entry point. Requires an already-local
 * selected source URI. No external download or implicit import on boot.
 * Always rehashes the private copy before making a model available.
 */
export async function installPrivateLuddishForTest(sourceUri: string): Promise<boolean> {
  if (!__DEV__) return false;
  if (runtime || startup) return false;
  const source = new File(sourceUri);
  const dest = new File(Paths.document, CANDIDATE_FILE);
  if (!source.exists || !/^file:\/\/\//.test(sourceUri) ||
      source.uri === dest.uri || dest.exists) return false;
  try {
    source.copy(dest);
    const ok = await startSharedLuddish();
    if (!ok) { if (dest.exists) dest.delete(); }
    return ok;
  } catch {
    try { if (dest.exists) dest.delete(); } catch { /* no data leak */ }
    return false;
  }
}

export async function stopSharedLuddish(): Promise<void> {
  if (startup) await startup;
  const previous = runtime;
  runtime = null;
  if (previous && getSharedSLM() === previous) setSharedSLM(null);
  if (previous) await previous.release();
}
