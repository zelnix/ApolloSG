/** Read the verified device copy first, then the authenticated working copy. */
import { API_BASE, ApiError } from "@/src/api/client";
import { getDeviceIdentity, getDeviceToken } from "@/src/auth/deviceIdentity";
import { getEvidenceManifest } from "./deviceStore";
import { evidenceArchive } from "./evidenceArchive";

export async function fetchEvidenceContent(caseId: string, evidenceId: string): Promise<Response> {
  const identity = await getDeviceIdentity();
  const saved = await getEvidenceManifest(caseId);
  const item = saved?.items.find(value => value.evidenceId === evidenceId);
  if (identity && item) {
    const archive = evidenceArchive(identity.deviceId, caseId);
    const bytes = await archive.read(item);
    if (bytes && bytes.length === item.byteLength && await archive.digest(bytes) === item.sha256)
      return new Response(Uint8Array.from(bytes).buffer, { headers: { "Content-Type": item.mediaType || "application/octet-stream" } });
  }
  const token = await getDeviceToken();
  if (!token) throw new ApiError(401, "ApolloSG hasn't registered this device yet.");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    return await fetch(`${API_BASE}/investigations/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/content`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    });
  } finally { clearTimeout(timeout); }
}
