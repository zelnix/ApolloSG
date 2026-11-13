/** Integrity handshake shared by platform-specific durable byte stores. */
export interface EvidenceManifestItem { evidenceId: string; byteLength: number; sha256: string; mediaType?: string; kind?: string }
export interface EvidenceArchive {
  read(item: EvidenceManifestItem): Promise<Uint8Array | null>;
  write(item: EvidenceManifestItem, bytes: Uint8Array): Promise<void>;
  digest(bytes: Uint8Array): Promise<string>;
}
export async function archiveEvidence(
  items: readonly EvidenceManifestItem[], archive: EvidenceArchive,
  download: (item: EvidenceManifestItem) => Promise<Uint8Array>,
): Promise<Record<string, string>> {
  const saved: Record<string, string> = {};
  for (const item of items) {
    if (!item.evidenceId || item.evidenceId in saved || !/^[a-f0-9]{64}$/.test(item.sha256) ||
        !Number.isSafeInteger(item.byteLength) || item.byteLength < 0) throw new Error("invalid_evidence_manifest");
    const matches = async (bytes: Uint8Array | null) => bytes !== null && bytes.length === item.byteLength &&
      await archive.digest(bytes) === item.sha256;
    let bytes = await archive.read(item);
    if (!await matches(bytes)) {
      bytes = await download(item);
      if (!await matches(bytes)) throw new Error("evidence_download_integrity_failed");
      await archive.write(item, bytes);
    }
    // The confirmation proves durable readback, not just successful download/write.
    if (!await matches(await archive.read(item))) throw new Error("evidence_storage_integrity_failed");
    saved[item.evidenceId] = item.sha256;
  }
  return saved;
}
