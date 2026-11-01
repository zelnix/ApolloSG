// Preview simulation isolation — ONE build decision, all of it or none of it.
// Run: cd /app/frontend && node --test tests/previewIsolation.test.ts
//
// These tests read the source and the build configuration. The artifact itself is checked by
// scripts/verify-no-simulation.mjs, which exports a real bundle and greps it.
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { test } from "node:test";

// simulatedItems.ts loads real preview image assets, so only the data-only module is imported here;
// the rest is covered by the shared contract below and by the artifact check in CI.
import { SIMULATED_EMAILS } from "../src/simulation/simulatedInbox.ts";
// The production stand-in imports nothing but types, so it loads here exactly as it ships.
import { simulation as absent } from "../src/simulationAbsent.ts";

const ROOT = new URL("..", import.meta.url).pathname;
const read = (rel: string) => readFileSync(join(ROOT, rel), "utf8");
// The sandbox .env is not committed (it carries this workspace's URLs), so a CI checkout has none.
// Its checks apply where it exists; everywhere else there is nothing to check.
const SANDBOX_ENV = existsSync(join(ROOT, ".env")) ? read(".env") : null;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

const APP_SOURCES = [...walk(join(ROOT, "app")), ...walk(join(ROOT, "src"))]
  .filter((f) => !f.includes("/src/simulation/"));

/** Keys of an object literal `simulation: PreviewSimulation = { … }` in a module's source. */
function simulationKeys(code: string): string[] {
  const start = code.indexOf("simulation: PreviewSimulation = {");
  assert.ok(start > 0, "the module must declare one `simulation: PreviewSimulation` object");
  const body = code.slice(start, code.indexOf("\n};", start));
  return [...body.matchAll(/^\s{2}([A-Za-z]+):/gm)].map((m) => m[1]).sort();
}

test("application code reaches simulation through one entry only", () => {
  const offenders = APP_SOURCES.filter((f) => {
    if (f.endsWith("src/simulationAbsent.ts") || f.endsWith("src/simulationContract.ts")) return false; // types only, erased at compile time
    return /(?:from|require\()\s*["'][^"']*\/simulation\/[^"']+["']/.test(readFileSync(f, "utf8"));
  });
  assert.deepEqual(offenders, [], `These files import a file inside src/simulation/ instead of "@/src/simulation":\n${offenders.join("\n")}`);
});

test("nothing gates simulation at runtime — no __DEV__, no conditional require", () => {
  for (const file of APP_SOURCES) {
    for (const line of readFileSync(file, "utf8").split("\n")) {
      if (!/simulation/.test(line)) continue;
      assert.doesNotMatch(line, /__DEV__/, `${file}: __DEV__ must not gate simulation — isolation is a build decision`);
      assert.doesNotMatch(line, /require\(/, `${file}: a conditional require keeps simulation in the production dependency graph`);
    }
  }
});

test("the obsolete preview switches are gone from code and configuration", () => {
  const retired = ["EXPO_PUBLIC_PREVIEW_SAMPLES", "EXPO_PUBLIC_DEVICE_PREVIEW_HARNESS", "PREVIEW_SAMPLES_ENABLED", "IS_PREVIEW_HARNESS", "preview_harness"];
  const files = [...APP_SOURCES, ...walk(join(ROOT, "src/simulation"))];
  for (const file of files) {
    const code = readFileSync(file, "utf8");
    for (const name of retired) assert.ok(!code.includes(name), `${file} still references the retired switch ${name}`);
  }
  for (const name of retired) {
    if (SANDBOX_ENV !== null) assert.ok(!SANDBOX_ENV.includes(name), `.env still sets ${name}`);
    assert.ok(!read("eas.json").includes(name), `eas.json still sets ${name}`);
    assert.ok(!read("scripts/security-preflight.mjs").includes(name), `security-preflight still checks ${name}`);
  }
});

test("one build-level mechanism decides, and it is not __DEV__", () => {
  const babel = read("babel.config.js");
  const code = babel.split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
  assert.match(code, /EXPO_PUBLIC_PREVIEW_BUILD === "included"/, "babel.config.js must key off the single build variable");
  assert.match(code, /module-resolver/, "the production build must resolve the entry away from the simulation source");
  assert.match(code, /"\^@\/src\/simulation\$": "\.\/src\/simulationAbsent"/);
  assert.doesNotMatch(code, /__DEV__/, "__DEV__ is not a build-isolation mechanism");
  // Exactly two inputs: the build flag, and the backend the app talks to (a deployed app talks to the
  // production backend, so it can never qualify as the preview build whatever the flag says).
  const vars = [...code.matchAll(/EXPO_PUBLIC_[A-Z_]+/g)].map((m) => m[0]);
  assert.deepEqual([...new Set(vars)].sort(), ["EXPO_PUBLIC_BACKEND_URL", "EXPO_PUBLIC_PREVIEW_BUILD"]);
  // The preview is the build that includes it; every EAS profile excludes it.
  if (SANDBOX_ENV !== null) assert.match(SANDBOX_ENV, /EXPO_PUBLIC_PREVIEW_BUILD=included/);
  assert.match(read("eas.json"), /"EXPO_PUBLIC_PREVIEW_BUILD": "excluded"/);
  // The deploy pipeline copies the sandbox .env (PREVIEW_BUILD=included) into the EAS job and selects
  // its own profile, so the flag alone cannot be trusted: a store build must settle it structurally.
  assert.match(code, /EAS_BUILD/, "an EAS build must be production whatever the flag says");
  assert.match(code, /!STORE_BUILD && PREVIEW_BACKEND && process\.env\.EXPO_PUBLIC_PREVIEW_BUILD === "included"/);
  assert.match(code, /\\\.preview\\\.emergentagent\\\.com/, "only a preview backend can qualify");
});

test("the build's Babel plugin is a runtime dependency (the deploy install omits devDependencies)", () => {
  // The Emergent deploy builder installs without devDependencies. A plugin the production Babel branch
  // loads must therefore be in `dependencies`, or Metro's transformer never starts ("reading 'transformFile'").
  const pkg = JSON.parse(read("package.json"));
  assert.ok(pkg.dependencies["babel-plugin-module-resolver"], "babel-plugin-module-resolver must be in dependencies");
  assert.equal(pkg.devDependencies?.["babel-plugin-module-resolver"], undefined);
});

test("a deployed app cannot carry the simulation even though it shares the project's flag", () => {
  // Evaluate the real babel config with the deployment's inputs: flag "included", production backend.
  const load = (env: Record<string, string>) => {
    const saved = { ...process.env };
    Object.assign(process.env, env);
    delete process.env.EAS_BUILD; delete process.env.EAS_BUILD_PLATFORM;
    const requireCjs = createRequire(import.meta.url);
    const file = join(ROOT, "babel.config.js");
    delete requireCjs.cache[requireCjs.resolve(file)];
    const config = requireCjs(file)({ cache: { using: () => undefined } });
    process.env = saved;
    return config.plugins.length > 0 ? "production" : "preview";
  };
  assert.equal(load({ EXPO_PUBLIC_PREVIEW_BUILD: "included", EXPO_PUBLIC_BACKEND_URL: "https://threat-patrol-1.emergent.host" }), "production");
  assert.equal(load({ EXPO_PUBLIC_PREVIEW_BUILD: "included", EXPO_PUBLIC_BACKEND_URL: "https://case-source-preview--3ijise2t.preview.emergentagent.com.attacker.net" }), "production");
  assert.equal(load({ EXPO_PUBLIC_PREVIEW_BUILD: "excluded", EXPO_PUBLIC_BACKEND_URL: "https://case-source-preview--3ijise2t.preview.emergentagent.com" }), "production");
  assert.equal(load({ EXPO_PUBLIC_PREVIEW_BUILD: "included", EXPO_PUBLIC_BACKEND_URL: "https://case-source-preview--3ijise2t.preview.emergentagent.com" }), "preview");
});

test("there is no configuration where only part of the simulation system is present", () => {
  // One surface, the same members on both sides — the compiler enforces the type, this pins the keys.
  const keys = simulationKeys(read("src/simulation/index.ts"));
  assert.deepEqual(simulationKeys(read("src/simulationAbsent.ts")), keys);
  assert.deepEqual(Object.keys(absent).sort(), keys);

  // Everything the preview build offers is empty, false or null in a production build.
  assert.equal(absent.included, false);
  assert.equal(absent.tag, "", "not even the PREVIEW ONLY marking ships");
  assert.equal(absent.accountLabel, "");
  for (const key of ["texts", "calls", "apps", "files", "links", "deviceConcerns", "screenshots", "emails"] as const) {
    assert.deepEqual(absent[key], [], `${key} must be empty in a production build`);
  }
  assert.equal(absent.read("file:///anything"), null);
  assert.ok(!("exampleCase" in absent), "no hand-written case: every case comes from Apollo's own checks");
  assert.ok(!existsSync(join(ROOT, "src/simulation/exampleThreatCase.ts")));
  assert.equal(absent.Picker({ title: "", note: "", items: [], onSelect: () => {}, testID: "x" }), null);

  // …and the preview source really does carry samples.
  assert.ok(SIMULATED_EMAILS.length > 0, "the preview inbox must carry samples");
  const items = read("src/simulation/simulatedItems.ts");
  for (const name of ["SIMULATED_TEXTS", "SIMULATED_CALLS", "SIMULATED_APPS", "SIMULATED_FILES", "SIMULATED_LINKS", "SIMULATED_DEVICE_CONCERNS", "SIMULATED_SCREENSHOTS"]) {
    const declared = items.slice(items.indexOf(`export const ${name}`));
    assert.match(declared.slice(0, declared.indexOf("\nexport ")), /id: "/, `${name} must carry samples in a preview build`);
  }
});

test("simulation is never a fallback for a real capability", () => {
  // The image path accepts a registration from the preview entry; it must not import simulation itself.
  const privacy = read("src/domain/imagePrivacy.ts");
  assert.match(privacy, /export function registerSimulatedRead/);
  assert.doesNotMatch(privacy, /from\s+["'][^"']*simulat/i);
  assert.doesNotMatch(privacy, /require\(["'][^"']*simulat/i);
  // The device adapter selector offers no simulated host at all — it was removed, not switched off.
  assert.doesNotMatch(read("src/security/hostAdapter.web.ts"), /PreviewDeviceAdapter|fixtureEnabled/);
  assert.doesNotMatch(read("src/security/securityConfig.ts"), /devicePreviewHarness/);
  assert.equal(existsSync(join(ROOT, "tools/preview-device-harness")), false);
});

test("the production artifact is verified by a build check, not by trust", () => {
  const verify = read("scripts/verify-no-simulation.mjs");
  assert.match(verify, /"expo", "export"/, "the check must inspect a real exported artifact");
  assert.match(verify, /EXPO_PUBLIC_PREVIEW_BUILD/);
  assert.match(verify, /process\.exit\(1\)/);
  const workflow = readFileSync(join(ROOT, "../.github/workflows/native-dependencies.yml"), "utf8");
  assert.match(workflow, /verify-no-simulation\.mjs/, "CI must run the artifact check");
});
