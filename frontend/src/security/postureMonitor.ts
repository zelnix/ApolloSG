/**
 * Posture Monitor — periodic device posture surveillance.
 *
 * Runs on app foreground (and on each resume from background).
 * Compares current posture snapshot against the last known state.
 * Fires local alerts for any security-relevant changes and reports
 * them to the backend for push notification delivery when the app is closed.
 */

import { AppState, type AppStateStatus } from "react-native";

import { storage } from "@/src/utils/storage";
import type { NetworkStatus, ProtectionStatus } from "./SecurityPlatformAdapter";
import { collectPostureSnapshot, diffPosture, postureChangeAlerts, type PostureSnapshot, type PostureChange } from "./devicePosture";
export type { PostureSnapshot, PostureChange } from "./devicePosture";
import { scheduleLocalAlert } from "@/src/push/notifications";
import { apiPost } from "@/src/api/client";

const STORAGE_KEY = "apollo.posture.lastSnapshot";
const MIN_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes between checks

let _lastCheckAt = 0;
let _appStateSubscription: ReturnType<typeof AppState.addEventListener> | null = null;
let _protectionRef: ProtectionStatus | null = null;
let _networkRef: NetworkStatus | null = null;
let _onChangeCallbacks: Array<(changes: PostureChange[], snapshot: PostureSnapshot) => void> = [];

// ────────────────────────────────────────────────────────────────────
// Public API
// ────────────────────────────────────────────────────────────────────

/** Update the protection and network refs used by the monitor. Call from ApolloContext whenever these change. */
export function updatePostureInputs(protection: ProtectionStatus | null, network: NetworkStatus | null): void {
  _protectionRef = protection;
  _networkRef = network;
}

/** Register a callback for posture changes. Returns unsubscribe function. */
export function onPostureChange(cb: (changes: PostureChange[], snapshot: PostureSnapshot) => void): () => void {
  _onChangeCallbacks.push(cb);
  return () => { _onChangeCallbacks = _onChangeCallbacks.filter((c) => c !== cb); };
}

/** Start monitoring. Call once from app bootstrap. */
export function startPostureMonitor(): void {
  if (_appStateSubscription) return; // already started

  _appStateSubscription = AppState.addEventListener("change", handleAppStateChange);

  // Run initial check after a brief delay to let the app settle
  setTimeout(() => { void runPostureCheck(); }, 3000);
}

/** Stop monitoring (cleanup). */
export function stopPostureMonitor(): void {
  _appStateSubscription?.remove();
  _appStateSubscription = null;
}

/** Force an immediate posture check. Returns the snapshot and any changes. */
export async function runPostureCheck(): Promise<{ snapshot: PostureSnapshot; changes: PostureChange[] }> {
  _lastCheckAt = Date.now();

  const current = await collectPostureSnapshot(_protectionRef, _networkRef);
  const previous = await loadPreviousSnapshot();
  const changes = previous ? diffPosture(previous, current) : [];

  // Save current as the new baseline
  await saveSnapshot(current);

  // Fire local alerts for changes
  if (changes.length > 0) {
    const alerts = postureChangeAlerts(changes);
    for (const alert of alerts) {
      try { await scheduleLocalAlert(alert); } catch { /* non-fatal */ }
    }

    // Report to backend
    try {
      await apiPost("/devices/posture", "device_posture", {
        snapshot: {
          checks: current.checks.map((c) => ({ id: c.id, value: c.value, severity: c.severity, observable: c.observable })),
          capturedAt: current.capturedAt,
          platform: current.platform,
        },
        changes: changes.map((c) => ({ id: c.id, label: c.label, previousValue: c.previousValue, currentValue: c.currentValue, severity: c.severity, detail: c.detail })),
      });
    } catch { /* offline: local alerts still fire */ }

    // Notify in-app listeners
    for (const cb of _onChangeCallbacks) {
      try { cb(changes, current); } catch { /* non-fatal */ }
    }
  }

  return { snapshot: current, changes };
}

/** Get the last posture snapshot without running a new check. */
export async function getLastPostureSnapshot(): Promise<PostureSnapshot | null> {
  return loadPreviousSnapshot();
}

// ────────────────────────────────────────────────────────────────────
// Internal
// ────────────────────────────────────────────────────────────────────

function handleAppStateChange(state: AppStateStatus): void {
  if (state === "active" && Date.now() - _lastCheckAt > MIN_INTERVAL_MS) {
    void runPostureCheck();
  }
}

async function loadPreviousSnapshot(): Promise<PostureSnapshot | null> {
  try {
    const raw = await storage.getItem<string | null>(STORAGE_KEY, null);
    if (!raw || typeof raw !== "string") return null;
    return JSON.parse(raw) as PostureSnapshot;
  } catch {
    return null;
  }
}

async function saveSnapshot(snapshot: PostureSnapshot): Promise<void> {
  try {
    await storage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  } catch { /* non-fatal */ }
}
