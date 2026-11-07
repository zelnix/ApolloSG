#!/usr/bin/env node
/**
 * Build verification — inspect a real exported artifact and fail if ANY preview simulation reached it.
 *
 * Runtime flags, `__DEV__` and tree-shaking are not isolation, so this does not read the source: it
 * exports the bundle the way a release is built and greps the actual output.
 *
 *   node scripts/verify-no-simulation.mjs              # production artifact: must contain none of it
 *   node scripts/verify-no-simulation.mjs --preview    # preview artifact: must contain all of it
 *
 * Markers are fixture identifiers and sample strings that only exist inside src/simulation/. One hit
 * is a failure — a shipped build has to be free of all of them.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const preview = process.argv.includes("--preview");
// The export lands in the OS temp directory, never inside the project: a 20 MB artifact left in the
// repo is uploaded with the source on every deploy and can even be scanned as if it were app code.
const outDir = path.join(os.tmpdir(), preview ? "apollo-verify-export-preview" : "apollo-verify-export-production");

// Every marker is a string that a PREVIEW artifact provably contains (run with --preview), so its
// absence from a production artifact means something. Module paths and file names are not usable:
// a production export carries neither, so they would "pass" in both builds and prove nothing.
const MARKERS = [
  "commbank-cancel.co",
  "civic-plumbing-invoices.com",
  "SIMULATED_SCREENSHOT_TEXT",
  "SIMULATED_EMAILS",
  "SIMULATED_TEXTS",
  "PREVIEW ONLY",
  "preview-mock-threat-001",
  "sim-shot-sms-code",
  "Simulated inbox",
];

function exportBundle() {
  fs.rmSync(outDir, { recursive: true, force: true });
  const env = {
    ...process.env,
    // The production check reproduces an Emergent deployment: the project's flag says "included", but the
    // app talks to the production backend — the artifact must still contain none of the simulation.
    EXPO_PUBLIC_PREVIEW_BUILD: "included",
    EXPO_PUBLIC_BACKEND_URL: preview ? "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com" : "https://verify.emergent.host",
    NODE_ENV: "production",
  };
  console.log(`[verify-no-simulation] exporting web bundle (EXPO_PUBLIC_PREVIEW_BUILD=${env.EXPO_PUBLIC_PREVIEW_BUILD}, backend ${env.EXPO_PUBLIC_BACKEND_URL})…`);
  execFileSync("npx", ["expo", "export", "--platform", "web", "--output-dir", outDir, "--clear"], {
    cwd: root, env, stdio: "inherit",
  });
}

function bundleFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return bundleFiles(full);
    return /\.(js|hbc|map|json|html)$/.test(entry.name) ? [full] : [];
  });
}

exportBundle();
const files = bundleFiles(outDir);
if (files.length === 0) {
  console.error("[verify-no-simulation] the export produced no files — cannot verify.");
  process.exit(1);
}

const hits = new Map();
for (const file of files) {
  const text = fs.readFileSync(file, "utf8");
  for (const marker of MARKERS) {
    if (text.includes(marker)) {
      const list = hits.get(marker) ?? [];
      list.push(path.relative(outDir, file));
      hits.set(marker, list);
    }
  }
}

if (preview) {
  const missing = MARKERS.filter((m) => !hits.has(m));
  console.log(`[verify-no-simulation] preview artifact: ${MARKERS.length - missing.length}/${MARKERS.length} markers present across ${files.length} files.`);
  if (missing.length) {
    console.error("PREVIEW BUILD IS INCOMPLETE — the simulation these markers belong to did not reach the preview artifact:\n - " + missing.join("\n - "));
    process.exit(1);
  }
  console.log("[verify-no-simulation] OK — the preview build contains the simulation it is supposed to.");
  process.exit(0);
}

if (hits.size) {
  console.error(`PRODUCTION ARTIFACT CONTAINS PREVIEW SIMULATION (${hits.size} marker${hits.size === 1 ? "" : "s"}):`);
  for (const [marker, where] of hits) console.error(` - "${marker}" in ${[...new Set(where)].join(", ")}`);
  console.error("\nThe simulation source must not be in the dependency graph of a production build. Check babel.config.js and that every import uses \"@/src/simulation\".");
  process.exit(1);
}
console.log(`[verify-no-simulation] OK — ${files.length} artifact files scanned, zero simulation code, fixtures or identifiers.`);
