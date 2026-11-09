#!/usr/bin/env node
// Prints the MODEL_SOURCES entry (src/slm/models.ts) for a downloaded GGUF file:
//   node scripts/slm-model-manifest.mjs <model-id> <path-to-file.gguf> <https URL where you host it>
// The app refuses to load a file whose SHA-256 doesn't match, so run this on the exact file you upload.
import { createHash } from "node:crypto";
import { createReadStream, statSync } from "node:fs";

const [id, file, url] = process.argv.slice(2);
if (!id || !file || !url || !url.startsWith("https://")) {
  console.error("usage: node scripts/slm-model-manifest.mjs <model-id> <file.gguf> <https://…>");
  process.exit(1);
}
const hash = createHash("sha256");
createReadStream(file)
  .on("data", (chunk) => hash.update(chunk))
  .on("error", (e) => { console.error(e.message); process.exit(1); })
  .on("end", () => {
    const entry = { url, sha256: hash.digest("hex"), bytes: statSync(file).size };
    // Publisher-listed hashes (src/slm/models.ts upstreamSha256). The app refuses a hosted file that doesn't match.
    const PUBLISHER = { "qwen2.5-0.5b-instruct-q4km": "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db" };
    if (PUBLISHER[id] && PUBLISHER[id] !== entry.sha256) {
      console.error(`This file is not the publisher's ${id} file (expected SHA-256 ${PUBLISHER[id]}). Don't host it.`);
      process.exit(1);
    }
    console.log(`  "${id}": ${JSON.stringify(entry)},`);
  });
