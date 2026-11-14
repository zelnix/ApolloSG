import { ACTIVE_MODEL, REFERENCE_MODEL } from "./modelProfiles.ts";

/** Removes only the superseded app-private package, after the active runtime has loaded.
 * Never deletes an imported original, evidence, settings, or the active package.
 */
export async function prepareAndRetireReferenceModel(
  loadedModelId: string,
  prepare: () => Promise<void>,
  removePrivatePackage: (filename: string) => void,
): Promise<{ removedLegacy: boolean; cleanupFailed: boolean }> {
  await prepare(); // Failure preserves the old package and propagates to startup.
  if (ACTIVE_MODEL.modelId === REFERENCE_MODEL.modelId || loadedModelId !== ACTIVE_MODEL.modelId || ACTIVE_MODEL.filename === REFERENCE_MODEL.filename)
    return { removedLegacy: false, cleanupFailed: false };
  try {
    removePrivatePackage(REFERENCE_MODEL.filename);
    return { removedLegacy: true, cleanupFailed: false };
  } catch {
    return { removedLegacy: false, cleanupFailed: true };
  }
}
