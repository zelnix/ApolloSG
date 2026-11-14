// Thin API client. Every outbound body passes through the egress policy.

import { Platform } from "react-native";

import { markBackendFailure, markBackendOk } from "@/src/api/backendHealth";
import { getDeviceToken, resetDeviceIdentity } from "@/src/auth/deviceIdentity";
import { enforceEgress, type EgressEndpoint } from "@/src/domain/privacy";
import { classifyHttpFailure, FAILURE_MESSAGE, type FailureKind } from "@/src/domain/serviceHealth";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
if (!BASE) throw new Error("EXPO_PUBLIC_BACKEND_URL is not set");
export const API_BASE = `${BASE}/api`;

export class ApiError extends Error {
  /** `kind` is set for transport-level failures (no coherent HTTP answer); undefined for real HTTP status errors. */
  constructor(readonly status: number, message: string, readonly kind?: FailureKind) { super(message); this.name = "ApiError"; }
}

// Failure contract (Hardening Gate step 3): every call ends — in an answer, or in a classified failure. A hung
// service must never leave a check spinning; the caller degrades to "unavailable", never to "safe".
export const DEFAULT_TIMEOUT_MS = 20000;
/** Endpoints that legitimately take longer (vision/LLM second opinions, TTS, redirect expansion). */
const LONG_TIMEOUT_MS = 135000; // interim alignment while analysis routes migrate to asynchronous jobs
const ASK_STREAM_TIMEOUT_MS = 135000; // compatibility transport: server's absolute work budget + transport margin
const LONG_PATHS = ["/voice/speak", "/app/analyse", "/account/analyse", "/account/monitor/scan", "/intel/check", "/ask/", "/gmail/scan", "/vision/investigate"];
export function timeoutFor(path: string): number { return LONG_PATHS.some((p) => path.startsWith(p)) ? LONG_TIMEOUT_MS : DEFAULT_TIMEOUT_MS; }

/** Bearer credential for every call. Fails closed: with no identity the request is not sent. */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getDeviceToken();
  if (!token) throw new ApiError(401, "ApolloSG hasn't registered this device yet.");
  return { Authorization: `Bearer ${token}` };
}

async function fetchWithBudget(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ctl = new AbortController();
  let timedOut = false;
  let rejectTimeout: ((reason?: unknown) => void) | null = null;
  const timeout = new Promise<never>((_resolve, reject) => { rejectTimeout = reject; });
  const t = setTimeout(() => {
    timedOut = true;
    ctl.abort();
    rejectTimeout?.(new Error("request timeout"));
  }, timeoutMs);
  try {
    // Some React Native Web fetch implementations do not settle after AbortController.abort(). The explicit
    // race guarantees every user check reaches a truthful fallback instead of spinning forever.
    return await Promise.race([fetch(url, { ...init, signal: ctl.signal }), timeout]);
  } catch {
    const kind: FailureKind = timedOut || ctl.signal.aborted ? "timeout" : "offline";
    markBackendFailure(kind);
    throw new ApiError(0, FAILURE_MESSAGE[kind], kind);
  } finally { clearTimeout(t); }
}

async function request<T>(path: string, init?: RequestInit, acceptUnavailable = false, timeoutMs?: number): Promise<T> {
  const auth = await authHeaders();
  const res = await fetchWithBudget(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...auth, ...(init?.headers ?? {}) } }, timeoutMs ?? timeoutFor(path));
  if (!res.ok && !(acceptUnavailable && res.status === 503)) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep statusText */ }
    const cls = classifyHttpFailure(res.status);
    // A 5xx means the service answered but is failing → degraded. Any 4xx (incl. 401/403) is a coherent answer → reachable.
    if (cls === "service_degraded") markBackendFailure("server_error"); else markBackendOk();
    // 401 → credential is dead → explicit identity reset. 403 → authenticated but NOT allowed → never touches identity.
    if (cls === "identity_reset") await resetDeviceIdentity(typeof detail === "string" ? detail : "Device credential rejected.");
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 503) markBackendFailure("server_error"); else markBackendOk();
  if (res.status === 204) return undefined as T;
  try { return (await res.json()) as T; }
  catch { markBackendFailure("malformed"); throw new ApiError(502, FAILURE_MESSAGE.malformed, "malformed"); }
}

export function apiGet<T>(path: string, timeoutMs?: number) { return request<T>(path, undefined, false, timeoutMs); }
/** Preserve a bounded 503 readiness body instead of treating it as a healthy response. */
export function apiGetReadiness<T>(path: string) { return request<T>(path, undefined, true); }
/** No payload is ever sent to the server-owned synthetic check. */
export function apiPostEmpty<T>(path: string, idempotencyKey: string) {
  return request<T>(path, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
export function apiDelete<T>(path: string) { return request<T>(path, { method: "DELETE" }); }
/** `timeoutMs` overrides the path's budget for one call (e.g. a reputation lookup that will be retried). */
export function apiPost<T>(path: string, endpoint: EgressEndpoint, body: Record<string, unknown>, options?: { timeoutMs?: number }) {
  return request<T>(path, { method: "POST", body: JSON.stringify(enforceEgress(endpoint, body)) }, false, options?.timeoutMs);
}
/** Multipart upload (voice notes). Text fields go through the egress allow-list like any JSON body; the file is appended
 *  in the runtime's own shape (web needs a real Blob, native needs { uri, name, type }). Content-Type is left to the runtime. */
export async function apiUpload<T>(path: string, endpoint: EgressEndpoint, fields: Record<string, string>, file: { uri: string; name: string; type: string } | null) {
  const form = new FormData();
  for (const [k, v] of Object.entries(enforceEgress(endpoint, fields))) form.append(k, String(v));
  if (file && file.uri) {
    if (Platform.OS === "web") form.append("file", await (await fetch(file.uri)).blob(), file.name);
    else form.append("file", file as unknown as Blob);
  }
  const auth = await authHeaders();
  const res = await fetchWithBudget(`${API_BASE}${path}`, { method: "POST", body: form, headers: auth }, LONG_TIMEOUT_MS);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep statusText */ }
    if (res.status >= 500) markBackendFailure("server_error"); else markBackendOk();
    if (res.status === 401) await resetDeviceIdentity(typeof detail === "string" ? detail : "Device credential rejected.");
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  markBackendOk();
  return (await res.json()) as T;
}
export function apiPatch<T>(path: string, body: Record<string, unknown>) {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
export function apiPut<T>(path: string, endpoint: EgressEndpoint, body: Record<string, unknown>) {
  return request<T>(path, { method: "PUT", body: JSON.stringify(enforceEgress(endpoint, body)) });
}

/** SSE streaming over XHR — works on native and web without ReadableStream. */
export function streamPost(path: string, endpoint: EgressEndpoint, body: Record<string, unknown>, onDelta: (t: string) => void, onDone: (err?: string) => void) {
  const xhr = new XMLHttpRequest();
  let seen = 0;
  let finished = false;
  const finish = (err?: string) => { if (!finished) { finished = true; onDone(err); } };
  xhr.open("POST", `${API_BASE}${path}`);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.setRequestHeader("Accept", "text/event-stream");
  void getDeviceToken().then((token) => {
    if (!token) { finish("ApolloSG hasn't registered this device yet."); return; }
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.send(JSON.stringify(enforceEgress(endpoint, body)));
  }).catch((error: unknown) => finish(error instanceof Error ? error.message : "ApolloSG could not prepare this request."));
  const consume = () => {
    const text = xhr.responseText ?? "";
    const chunk = text.slice(seen);
    const lastBreak = chunk.lastIndexOf("\n\n");
    if (lastBreak < 0) return;
    seen += lastBreak + 2;
    for (const line of chunk.slice(0, lastBreak).split("\n")) {
      if (!line.startsWith("data: ")) continue;
      try {
        const evt = JSON.parse(line.slice(6)) as { delta?: string; done?: boolean; error?: string; failure_kind?: string; provider_complete?: boolean; finish_reason?: string };
        if (finished) continue;
        if (evt.delta) onDelta(evt.delta);
        if (evt.error) finish(evt.error);
        if (evt.done) finish(evt.provider_complete === true && evt.finish_reason === 'STOP' ? undefined : 'Magnum DI did not confirm a complete provider answer. Retry this question.');
      } catch { /* partial line */ }
    }
  };
  xhr.onprogress = consume;
  xhr.onload = () => {
    consume();
    if (xhr.status >= 500) markBackendFailure("server_error"); else markBackendOk();
    // 401 → identity reset; 403 → forbidden, identity untouched.
    if (xhr.status === 401) { void resetDeviceIdentity("Device credential rejected."); finish("ApolloSG needs to re-register this device. Try again in a moment."); }
    else if (xhr.status === 403) finish("This device isn't allowed to do that.");
    else if (xhr.status >= 400) finish("I couldn't answer right now.");
    else if (!finished) finish("The connection ended before Magnum DI completed this answer. Retry this question.");
  };
  xhr.onerror = () => { markBackendFailure("offline"); finish(FAILURE_MESSAGE.offline); };
  xhr.ontimeout = () => { markBackendFailure("timeout"); finish(FAILURE_MESSAGE.timeout); };
  xhr.timeout = path.startsWith("/ask/") ? ASK_STREAM_TIMEOUT_MS : LONG_TIMEOUT_MS;
  return () => { finished = true; xhr.abort(); };
}
