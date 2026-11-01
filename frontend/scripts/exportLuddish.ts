// @ts-nocheck — a Node dev script (run with node's type stripping), not app code.
// Writes backend/content/luddish.json from the app's Higgins Luddish (see scripts/luddishShared.ts).
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { luddishShared } from "./luddishShared.ts";

const out = fileURLToPath(new URL("../../backend/content/luddish.json", import.meta.url));
writeFileSync(out, `${JSON.stringify(luddishShared(), null, 2)}\n`);
console.log(`wrote ${out}`);
