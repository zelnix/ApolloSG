#!/usr/bin/env tsx
/**
 * Diagnostic runner — prints the full composed explanation for each failing fixture.
 */
import { lockEvidence } from "../lock.ts";
import { compose } from "../compose.ts";
import { FIXTURES } from "./reporting.fixtures.ts";

for (const fixture of FIXTURES) {
  const lock = lockEvidence(fixture.lock);
  const ex = compose(lock);
  const allParts = [
    `  BRIEF: ${ex.brief.text}`,
    ex.explanation ? `  EXPL:  ${ex.explanation.text}` : null,
    ...ex.findings.map((f, i) => `  FIND${i}: ${f.text}`),
    ...ex.meaning.map((m) => `  MEAN: ${m.text}`),
    ex.importance ? `  IMP:  ${ex.importance.text}` : null,
    ...ex.limitation.map((l) => `  LIM:  ${l.text}`),
    ...ex.action.map((a) => `  ACT:  ${a.text}`),
    ex.noAction ? `  NOACT: ${ex.noAction}` : null,
  ].filter(Boolean);

  console.log(`\n── ${fixture.name} ──`);
  console.log(`  State: ${ex.state}  Fidelity: ${ex.fidelity.status}  Readability: ${ex.readability.after}`);
  if (ex.fidelity.failures.length) console.log(`  Failures: ${ex.fidelity.failures.map((f) => `${f.code}@${f.ref}`).join(", ")}`);
  if (ex.fellBack.length) console.log(`  Fell back: ${ex.fellBack.map((f) => `${f.code}@${f.ref}`).join(", ")}`);
  for (const p of allParts) console.log(p);
}
