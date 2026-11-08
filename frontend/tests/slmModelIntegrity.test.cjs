const assert = require("node:assert/strict");
const test = require("node:test");
const { createHash } = require("node:crypto");
const { mkdtempSync, writeFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const { verifyGGUF } = require("../scripts/slm-verify-gguf.cjs");

async function withFixture(fn) {
  const dir = mkdtempSync(join(tmpdir(), "apollo-slm-model-test-"));
  const path = join(dir, "candidate.gguf");
  const good = Buffer.concat([Buffer.from("GGUF"), Buffer.alloc(1024)]);
  const sha = createHash("sha256").update(good).digest("hex");
  writeFileSync(path, good);
  try { await fn({ path, sha, good }); }
  finally { rmSync(dir, { recursive: true, force: true }); }
}

test("approves a local GGUF only when its digest matches", async () => {
  await withFixture(async ({ path, sha, good }) => {
    const result = await verifyGGUF(path, sha);
    assert.equal(result.verified, true);
    assert.equal(result.sha256, sha);
    assert.equal(result.bytes, good.length);
  });
});

test("rejects corrupted or unapproved weights", async () => {
  await withFixture(async ({ path }) => {
    await assert.rejects(verifyGGUF(path, "0".repeat(64)), /gguf_checksum_mismatch/);
  });
});

test("rejects non-GGUF files even when the digest matches", async () => {
  await withFixture(async ({ path, good }) => {
    const tampered = Buffer.from(good);
    tampered.write("FAIL", 0, "ascii");
    writeFileSync(path, tampered);
    const sha = createHash("sha256").update(tampered).digest("hex");
    await assert.rejects(verifyGGUF(path, sha), /invalid_gguf_header/);
  });
});

test("requires explicit expected hash and local GGUF path", async () => {
  await withFixture(async ({ path }) => {
    await assert.rejects(verifyGGUF(path, ""), /expected_sha256_required/);
    await assert.rejects(verifyGGUF("https://example.com/model.gguf", "a".repeat(64)), /ENOENT|expected_local_gguf/);
    await assert.rejects(verifyGGUF(path.replace(".gguf", ".bin"), "a".repeat(64)), /expected_local_gguf/);
  });
});
