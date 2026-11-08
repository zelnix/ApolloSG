#!/usr/bin/env node
/**
 * Check a locally provisioned GGUF before using it in ApolloSG native tests.
 * The expected SHA-256 is supplied from a separately reviewed model manifest.
 * This script does not download files, execute models, or connect to servers.
 */
const { createReadStream, openSync, readSync, closeSync, statSync } = require("node:fs");
const { createHash } = require("node:crypto");
const { resolve } = require("node:path");

async function verifyGGUF(filePath, expectedSha256, options = {}) {
  if (typeof filePath !== "string" || !filePath.toLowerCase().endsWith(".gguf")) {
    throw new Error("expected_local_gguf");
  }
  if (typeof expectedSha256 !== "string" || !/^[a-f0-9]{64}$/i.test(expectedSha256)) {
    throw new Error("expected_sha256_required");
  }
  const file = resolve(filePath);
  const info = statSync(file);
  if (!info.isFile() || info.size < (options.minBytes ?? 1024)) {
    throw new Error("invalid_gguf_size");
  }
  const fd = openSync(file, "r");
  try {
    const magic = Buffer.alloc(4);
    if (readSync(fd, magic, 0, 4, 0) !== 4 || magic.toString("ascii") !== "GGUF") {
      throw new Error("invalid_gguf_header");
    }
  } finally {
    closeSync(fd);
  }

  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  const actual = hash.digest("hex");
  if (actual.toLowerCase() !== expectedSha256.toLowerCase()) {
    throw new Error("gguf_checksum_mismatch");
  }
  return { verified: true, sha256: actual, bytes: info.size };
}

if (require.main === module) {
  const [file, sha256] = process.argv.slice(2);
  verifyGGUF(file, sha256).then(
    (report) => {
      console.log(JSON.stringify(report));
    },
    (err) => {
      // Do not expose private filesystem locations.
      console.error(`SLM model verification failed: ${err.code || err.message}`);
      process.exitCode = 1;
    },
  );
}

module.exports = { verifyGGUF };
