import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { archiveEvidence, type EvidenceArchive } from "../src/investigation/evidenceArchiveCore.ts";

const bytes = new TextEncoder().encode("original evidence");
const sha256 = createHash("sha256").update(bytes).digest("hex");
const item = { evidenceId: "E1", byteLength: bytes.length, sha256 };
function store(): EvidenceArchive {
  let saved: Uint8Array | null = null;
  return { read: async () => saved, write: async (_item, data) => { saved = Uint8Array.from(data); },
    digest: async data => createHash("sha256").update(data).digest("hex") };
}
test("only durable checksum-verified evidence can be confirmed; retry reuses it", async () => {
  const archive = store(); let downloads = 0;
  const load = async () => { downloads++; return bytes; };
  assert.deepEqual(await archiveEvidence([item], archive, load), { E1: sha256 });
  assert.deepEqual(await archiveEvidence([item], archive, load), { E1: sha256 });
  assert.equal(downloads, 1);
});
test("changed download cannot reach storage or a confirmation", async () => {
  const archive = store();
  await assert.rejects(archiveEvidence([item], archive, async () => new Uint8Array(bytes.length)), /download_integrity/);
  assert.equal(await archive.read(item), null);
});
test("storage loss is detected by readback even when write resolves", async () => {
  const archive = store(); archive.write = async () => {};
  await assert.rejects(archiveEvidence([item], archive, async () => bytes), /storage_integrity/);
});
test("duplicate manifest identifiers cannot certify two different sources", async () => {
  await assert.rejects(archiveEvidence([item, item], store(), async () => bytes), /invalid_evidence_manifest/);
});
