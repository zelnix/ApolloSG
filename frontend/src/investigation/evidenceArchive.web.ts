import type { EvidenceArchive } from "./evidenceArchiveCore";

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("apollo-investigation-evidence", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("bytes");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction("bytes", mode);
      const request = action(tx.objectStore("bytes"));
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = tx.onerror = () => reject(tx.error ?? new Error("evidence_storage_failed"));
    });
  } finally { db.close(); }
}
const prefix = (owner: string, caseId: string) => JSON.stringify([owner, caseId]) + ":";
export function evidenceArchive(owner: string, caseId: string): EvidenceArchive {
  return {
    async digest(bytes) {
      const result = await crypto.subtle.digest("SHA-256", Uint8Array.from(bytes).buffer);
      return Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, "0")).join("");
    },
    async read(item) { return await transaction("readonly", store => store.get(prefix(owner, caseId) + item.sha256)) ?? null; },
    async write(item, bytes) { await transaction("readwrite", store => store.put(bytes, prefix(owner, caseId) + item.sha256)); },
  };
}
export async function deleteArchivedEvidence(owner: string, caseId: string): Promise<void> {
  const keys = await transaction("readonly", store => store.getAllKeys());
  for (const key of keys) if (String(key).startsWith(prefix(owner, caseId)))
    await transaction("readwrite", store => store.delete(key));
}
export async function deleteAllArchivedEvidence(): Promise<void> {
  await transaction("readwrite", store => store.clear());
}
