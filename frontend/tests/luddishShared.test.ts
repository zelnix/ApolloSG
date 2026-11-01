// The server's Higgins Luddish reads backend/content/luddish.json; it must be exactly what this app's Luddish gives.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { luddishShared } from "../scripts/luddishShared.ts";

test("backend/content/luddish.json is current (regenerate: node scripts/exportLuddish.ts)", () => {
  const onDisk = JSON.parse(readFileSync(new URL("../../backend/content/luddish.json", import.meta.url), "utf8"));
  assert.deepEqual(onDisk, JSON.parse(JSON.stringify(luddishShared())));
});
