#!/usr/bin/env node
// Build-time security and installed-native-dependency preflight. Production native
// requirements follow securityConfig.ts. Wired to the EAS "eas-build-pre-install" hook in
// package.json and runnable locally: `node scripts/security-preflight.mjs`.
//
// Environment resolution (first match wins): process.env → .env.<APP_ENV or NODE_ENV> → .env

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import nativeGuard from "./native-dependency-guard.cjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const ANDROID_PACKAGE = "app.apollo.hwg";
const IOS_BUNDLE_IDENTIFIER = "app.apollo.hwg";
const RETIRED_SECURITY_NAME = ["Secure", "Core"].join("");
const RETIRED_SELECTORS = [
  ["EXPO", "PUBLIC", RETIRED_SECURITY_NAME.toUpperCase(), "MODE"].join("_"),
  ["Mock", RETIRED_SECURITY_NAME].join(""),
  ["HuCentAI", RETIRED_SECURITY_NAME].join(""),
];
const RETIRED_RUNTIME_MOCK = ["Mock", "Security", "Adapter"].join("");
const RETIRED_SECURITY_MODE = ["EXPO", "PUBLIC", "SECURITY", "MODE"].join("_");
// Production requires real rule authority, not controlled threat-test endpoints.
// Controlled host/IP/URL are acceptance-test inputs and must not gate production APKs.
const PRODUCTION_KEYS = [
  "EXPO_PUBLIC_GUARDDOG_RULE_BUNDLE_URL", "EXPO_PUBLIC_GUARDDOG_RULESET_ID"];
const KEYS = ["EXPO_PUBLIC_APP_ENV", "EXPO_PUBLIC_PREVIEW_BUILD", "EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE", ...PRODUCTION_KEYS];

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "node_modules" ? [] : walk(p);
    return /\.(ts|tsx|js|mjs|cjs|py|json|md|rs|swift|cpp|h|plist|ps1|nsh|yml|sh)$/.test(e.name) && !/\.d\.ts$/.test(e.name) ? [p] : [];
  });
}

function readDotenv(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*"?([^"#]*)"?\s*(#.*)?$/);
    if (m) out[m[1]] = m[2].trim();
  }
  return out;
}

const profile = process.env.EAS_BUILD_PROFILE;
const profileDefaults = profile ? {
  EXPO_PUBLIC_APP_ENV: profile === "staging" ? "staging" : "production",
  EXPO_PUBLIC_PREVIEW_BUILD: "excluded",
  EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE: "guarddog_production",
} : {};
const guessedEnv = process.env.EXPO_PUBLIC_APP_ENV || profileDefaults.EXPO_PUBLIC_APP_ENV || (process.env.NODE_ENV === "production" ? "production" : "development");
const baseFile = readDotenv(path.join(root, ".env"));
const environmentFile = readDotenv(path.join(root, `.env.${guessedEnv}`));
// Native EAS profiles never inherit development-web defaults from `.env`. Explicit profile env wins, then the
// matching environment file, then fail-safe native defaults. Local web development still reads `.env` normally.
const cfg = Object.fromEntries(KEYS.map((k) => [k, process.env[k] ?? environmentFile[k] ?? (profile ? profileDefaults[k] : baseFile[k])]));
if (!cfg.EXPO_PUBLIC_APP_ENV && profile) cfg.EXPO_PUBLIC_APP_ENV = guessedEnv;

const errors = [];
// In the EAS build environment the Emergent pipeline generates app.json from
// app.config.js and then deletes app.config.js.  Fall back to app.json so this
// pre-install hook works in both local and EAS contexts.
let resolvedAppConfig;
const appConfigPath = path.join(root, "app.config.js");
const appJsonPath = path.join(root, "app.json");
if (fs.existsSync(appConfigPath)) {
  const appConfigModule = require(appConfigPath);
  resolvedAppConfig = appConfigModule.expo || appConfigModule;
} else if (fs.existsSync(appJsonPath)) {
  const appJson = JSON.parse(fs.readFileSync(appJsonPath, "utf8"));
  resolvedAppConfig = appJson.expo || appJson;
} else {
  errors.push("Neither app.config.js nor app.json found — cannot validate app identity.");
  resolvedAppConfig = {};
}
if (resolvedAppConfig.android?.package !== ANDROID_PACKAGE) errors.push(`Android package must be ${ANDROID_PACKAGE}.`);
if (resolvedAppConfig.ios?.bundleIdentifier !== IOS_BUNDLE_IDENTIFIER) errors.push(`iOS bundle identifier must be ${IOS_BUNDLE_IDENTIFIER}.`);
// CNG has no android/ until prebuild. The authoritative package is app.config.js; if a
// generated project is present, additionally reject any mismatch in its concrete Gradle output.
const gradlePath = path.join(root, "android/app/build.gradle");
if (fs.existsSync(gradlePath)) {
  const nativeGradle = fs.readFileSync(gradlePath, "utf8");
  if (!nativeGradle.includes(`namespace '${ANDROID_PACKAGE}'`) || !nativeGradle.includes(`applicationId '${ANDROID_PACKAGE}'`)) {
    errors.push(`Native Android namespace and applicationId must both be ${ANDROID_PACKAGE}.`);
  }
}
if (!["development", "staging", "production"].includes(cfg.EXPO_PUBLIC_APP_ENV)) errors.push(`EXPO_PUBLIC_APP_ENV is missing or invalid (got "${cfg.EXPO_PUBLIC_APP_ENV}").`);
// ONE build decision governs preview simulation (babel.config.js). A shipped build must never carry it.
const previewBuild = cfg.EXPO_PUBLIC_PREVIEW_BUILD;
if (previewBuild !== undefined && previewBuild !== "" && previewBuild !== "excluded" && previewBuild !== "included") {
  errors.push(`EXPO_PUBLIC_PREVIEW_BUILD="${previewBuild}" is invalid. Use "included" for the preview build only.`);
}
if (previewBuild === "included" && profile) errors.push("EXPO_PUBLIC_PREVIEW_BUILD=included would bundle the preview simulation source; it can never be part of an EAS build profile.");
const engine = cfg.EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE ?? (cfg.EXPO_PUBLIC_APP_ENV === "production" ? "guarddog_production" : "legacy");
if (engine !== "guarddog_production") errors.push(`EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE="${engine}" is invalid. Only "guarddog_production" is supported.`);
if (cfg.EXPO_PUBLIC_APP_ENV === "production" && engine !== "guarddog_production") errors.push("Production must use GuardDog production runtime.");
if (engine === "guarddog_production" && cfg.EXPO_PUBLIC_APP_ENV !== "production") errors.push("GuardDog production authority requires a production app environment.");
if (engine === "guarddog_production") {
  for (const key of PRODUCTION_KEYS) if (!cfg[key]) errors.push(`${key} is required for GuardDog production authority.`);
}
const packageConfig = require(path.join(root, "package.json"));
const autolinking = resolvedAppConfig.autolinking ?? packageConfig.expo?.autolinking ?? {};
if (!(autolinking.android?.exclude ?? []).includes("guarddog-expo-module") || !(autolinking.ios?.exclude ?? []).includes("guarddog-expo-module")) {
  errors.push("The frozen GuardDog Expo bridge must remain excluded on Android and iOS; Apollo owns the only production bridge.");
}
// Runtime-mock exclusion: no mock adapter/selector may exist in application source, and simulation source may only be
// reached through the single `@/src/simulation` entry (which a production build rewrites to src/simulationAbsent.ts).
const workspace = path.resolve(root, "..");
const appSources = [
  ...["src", "app", "modules", "plugins", "tests", "scripts"].flatMap((dir) => walk(path.join(root, dir))),
  ...walk(path.join(workspace, "tests")),
  ...walk(path.join(workspace, "desktop")),
  ...[path.join(workspace, "design_guidelines.json")].filter((file) => fs.existsSync(file)),
];
for (const file of appSources) {
  const text = fs.readFileSync(file, "utf8");
  const rel = path.relative(root, file);
  const assertionOnly = rel.startsWith("tests/") || rel.startsWith("scripts/") || rel.startsWith("../tests/");
  // Only `@/src/simulation` may be imported. Reaching into a file inside the folder would survive the
  // production alias and pull simulation source into the artifact. src/simulationAbsent.ts re-exports
  // its TYPES from there (erased at compile time), and src/simulationContract.ts defines the shared
  // type surface using only `import type` (also erased). Both are exempt.
  const reachesIntoSimulation = /(?:from|require\()\s*["'][^"']*\/simulation\/[^"']+["']/.test(text);
  const typeOnlyExemptions = ["src/simulationAbsent.ts", "src/simulationContract.ts"];
  if (!assertionOnly && reachesIntoSimulation && !rel.startsWith("src/simulation/") && !typeOnlyExemptions.includes(rel)) {
    errors.push(`${rel} reaches into src/simulation/ directly; application code must import "@/src/simulation" only.`);
  }
  if (text.includes(RETIRED_SECURITY_MODE) || text.includes(RETIRED_RUNTIME_MOCK) || RETIRED_SELECTORS.some((selector) => text.includes(selector)) || text.toLowerCase().includes(RETIRED_SECURITY_NAME.toLowerCase())) errors.push(`${rel} references a retired security boundary.`);
}

console.log(`[security-preflight] profile=${profile ?? "local"} env=${cfg.EXPO_PUBLIC_APP_ENV} engine=${engine} preview-simulation=${previewBuild || "excluded"} app-sources-scanned=${appSources.length}`);
if (errors.length) {
  console.error("SECURITY CONFIGURATION ERROR:\n - " + errors.join("\n - "));
  process.exit(1);
}
console.log("[security-preflight] OK");

// EAS invokes this lifecycle BEFORE dependency installation: there is no truthful tree
// to inspect yet. Managed Android/iOS prebuild enforces the guard AFTER installation via
// withNativeDependencyGuard. Manual/CI security:preflight never takes this deferral.
if (process.env.npm_lifecycle_event === "eas-build-pre-install") {
  console.log("[native-dependency-guard] DEFERRED: EAS pre-install; mandatory Android/iOS prebuild check runs after dependency installation.");
} else {
  const report = nativeGuard.auditNativeDependencies(root);
  console.log(nativeGuard.formatReport(report));
  if (report.status !== "pass") process.exit(report.status === "error" ? 2 : 1);
}
