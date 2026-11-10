/** Shared, observable On-device AI download state across startup and Settings. */
export type OnDeviceAIDownloadState = {
  phase: "idle" | "downloading" | "verifying" | "registering" | "ready" | "failed";
  receivedBytes: number;
  totalBytes: number;
  error?: string;
};
let state: OnDeviceAIDownloadState = { phase: "idle", receivedBytes: 0, totalBytes: 0 };
const listeners = new Set<() => void>();
export const getOnDeviceAIDownloadState = () => state;
export const subscribeOnDeviceAIDownload = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export function updateOnDeviceAIDownload(patch: Partial<OnDeviceAIDownloadState>) {
  state = { ...state, ...patch };
  listeners.forEach(listener => listener());
}
