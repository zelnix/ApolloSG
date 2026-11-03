import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path: string) => readFileSync(join(root, path), "utf8");

test("P2.1 exposes the exact root tab order in native and standard navigation", () => {
  const source = read("app/(tabs)/_layout.tsx");
  // Tab order: Home → Threats → Ask Higgins → Alerts → Settings
  for (const sequence of [
    ['name="home"', 'name="patrol"', 'name="ask"', 'name="scams"', 'name="settings"'],
    ['name="home" options', 'name="patrol" options', 'name="ask" options', 'name="scams" options', 'name="settings" options'],
  ]) {
    let cursor = -1;
    for (const token of sequence) { const next = source.indexOf(token, cursor + 1); assert.ok(next > cursor, `${token} must appear in order`); cursor = next; }
  }
  // Check It was removed — guard and protection remain as hidden tabs
  assert.doesNotMatch(source, /name="check-it"/, "check-it should be removed");
  assert.match(source, /name="guard" options=\{\{ href: null \}\}/);
  assert.ok(existsSync(join(root, "app/gates.tsx")));
  assert.ok(existsSync(join(root, "app/(tabs)/protection.tsx")));
});

test("P2.1 Settings is a bottom tab and screen headers no longer carry a Settings icon", () => {
  assert.ok(existsSync(join(root, "app/(tabs)/settings.tsx")));
  assert.doesNotMatch(read("src/components/RootScreenHeader.tsx"), /icons\/settings|router\.push\("\/settings"\)/);
  assert.doesNotMatch(read("app/(tabs)/home.tsx"), /home-settings/);
  // Higgins (ask.tsx) is a full chat screen with its own messaging header, not the shared root header.
  assert.match(read("app/(tabs)/ask.tsx"), /testID="higgins-header"/);
});

test("V27 retired security boundary is absent from current app, source, tests and build scripts", () => {
  const retired = ["secure", "core"].join("");
  const files = ["src/security/securityBoot.ts", "scripts/security-preflight.mjs", "app/support.tsx", "tests/securityBoot.test.ts", "tests/securityConfig.test.ts"];
  for (const file of files) assert.equal(read(file).toLowerCase().includes(retired), false, file);
  assert.equal(existsSync(join(root, `src/security/${retired}`)), false);
});
