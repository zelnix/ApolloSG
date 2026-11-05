#!/usr/bin/env tsx
/**
 * Runner for the Higgins reporting regression fixtures.
 * Usage: npx tsx src/domain/luddish/__tests__/run_fixtures.ts
 */
import { runFixtures } from "./reporting.fixtures.ts";

const results = runFixtures();
let passed = 0;
let failed = 0;

for (const r of results) {
  if (r.passed) {
    console.log(`  ✅ ${r.fixture}`);
    passed++;
  } else {
    console.log(`  ❌ ${r.fixture}`);
    for (const f of r.failures) console.log(`     → ${f}`);
    failed++;
  }
}

console.log(`\n${passed + failed} fixtures, ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
