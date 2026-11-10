/** Privacy-safe startup stage telemetry: no case content, URLs or personal data. */
export type StartupStage = "on_device_ai" | "fonts" | "personal_data" | "device_protections" | "notifications" | "apollo_state" | "navigation";
const started = Date.now();
const active = new Map<StartupStage, number>();
export function startupStage(stage: StartupStage, status: "started" | "completed" | "failed" | "timed_out", detail?: string): void {
  const now = Date.now();
  if (status === "started") active.set(stage, now);
  const elapsed = now - (active.get(stage) ?? now);
  console.info("[ApolloSG startup]", stage, status, "stage_ms", elapsed, "boot_ms", now - started, detail ?? "");
  if (status !== "started") active.delete(stage);
}
