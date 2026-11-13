import type { ModelAdmission } from "./modelAdmission.ts";

export type NativeStartupFailure = Exclude<ModelAdmission, { available: true }>['reason']
  | "native_binding_unavailable" | "runtime_registration_failed";
type AdmittedModel = Extract<ModelAdmission, { available: true }>;

/** Model setup diagnostics contain no native exception text, paths or evidence. */
export function describeStartupFailure(code: NativeStartupFailure): string {
  const messages: Record<NativeStartupFailure, string> = {
    model_not_installed: "The required On-device AI model has not been installed.",
    model_unreadable: "ApolloSG could not read the downloaded On-device AI model.",
    invalid_model: "The downloaded On-device AI model is incomplete or invalid.",
    device_not_admitted: "This device does not meet the required memory capacity.",
    native_binding_unavailable: "This APK could not load its native On-device AI runtime.",
    runtime_registration_failed: "The On-device AI runtime could not be registered.",
  };
  return messages[code];
}

/** The existing startup path, factored so file admission and binding failures are distinguishable. */
export async function admitNativeStartup<Runtime>(
  verify: () => Promise<ModelAdmission>,
  loadFactory: () => Promise<(model: AdmittedModel) => Runtime | null>,
  onStage?: (stage: "model_integrity" | "runtime_registration") => void,
): Promise<{ available: true; runtime: Runtime } | { available: false; code: NativeStartupFailure }> {
  onStage?.("model_integrity");
  let model: ModelAdmission;
  try { model = await verify(); }
  catch { return { available: false, code: "model_unreadable" }; }
  if (!model.available) return { available: false, code: model.reason };
  onStage?.("runtime_registration");
  let create: (model: AdmittedModel) => Runtime | null;
  try { create = await loadFactory(); }
  catch { return { available: false, code: "native_binding_unavailable" }; }
  try {
    const runtime = create(model);
    return runtime ? { available: true, runtime } : { available: false, code: "runtime_registration_failed" };
  } catch { return { available: false, code: "runtime_registration_failed" }; }
}
