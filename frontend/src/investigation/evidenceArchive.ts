import { Directory, File, Paths } from "expo-file-system";
import * as Crypto from "expo-crypto";
import type { EvidenceArchive } from "./evidenceArchiveCore";

export function evidenceArchive(owner: string, caseId: string): EvidenceArchive {
  const directory = new Directory(Paths.document, "investigation-evidence", encodeURIComponent(owner), encodeURIComponent(caseId));
  const file = (digest: string) => new File(directory, digest);
  return {
    async digest(bytes) {
      const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, Uint8Array.from(bytes));
      return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    },
    async read(item) { const stored = file(item.sha256); return stored.exists ? stored.bytes() : null; },
    async write(item, bytes) {
      directory.create({ intermediates: true, idempotent: true });
      file(item.sha256).write(bytes);
    },
  };
}
export async function deleteArchivedEvidence(owner: string, caseId: string): Promise<void> {
  const directory = new Directory(Paths.document, "investigation-evidence", encodeURIComponent(owner), encodeURIComponent(caseId));
  if (directory.exists) directory.delete();
}
export async function deleteAllArchivedEvidence(): Promise<void> {
  const directory = new Directory(Paths.document, "investigation-evidence");
  if (directory.exists) directory.delete();
}
