import type { SLMActivitySnapshot } from "./sharedRuntime.ts";

/** Settings reports the latest local response; an older success is only history. */
export function slmActivityStatus(activity: SLMActivitySnapshot, options: {
  available: boolean; settingUp: boolean; testing: boolean;
}): string {
  if (options.settingUp) return "Setup in progress";
  if (!options.available) return "Unavailable on this platform";
  if (!activity.registered) return "Inactive — no runtime registered";
  if (options.testing) return "Testing local inference…";
  if (activity.latestInference?.status === "invalid_output") return "Needs attention — latest response failed validation";
  if (activity.latestInference?.status === "unavailable") return "Needs attention — latest local inference failed";
  if (activity.latestInference?.status === "completed") return "Active — latest local inference confirmed";
  return "Runtime registered — inference not yet confirmed";
}
