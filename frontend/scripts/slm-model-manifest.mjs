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
    console.log(`  "${id}": ${JSON.stringify(entry)},`);
  });
