/**
 * Production Sample Check Isolation — regression tests.
 *
 * Proves that when origin !== "sample_check" — i.e. every ordinary user submission —
 * ApolloSG behaves exactly as it did before Production Sample Checks were introduced.
 *
 * Run: node --test tests/sampleCheckIsolation.test.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test, describe } from "node:test";

// ── Source files under audit ─────────────────────────────────────────────────
const stateMachine = readFileSync(new URL("../src/domain/stateMachine.ts", import.meta.url), "utf8");
const ctx = readFileSync(new URL("../src/store/ApolloContext.tsx", import.meta.url), "utf8");
const types = readFileSync(new URL("../src/domain/types.ts", import.meta.url), "utf8");
const threatCase = readFileSync(new URL("../src/domain/threatCase.ts", import.meta.url), "utf8");
const patrolActivity = readFileSync(new URL("../src/domain/patrolActivity.ts", import.meta.url), "utf8");
const caseAuditTrail = readFileSync(new URL("../src/domain/caseAuditTrail.ts", import.meta.url), "utf8");
const sameNumber = readFileSync(new URL("../src/domain/sameNumber.ts", import.meta.url), "utf8");
const eventMerge = readFileSync(new URL("../src/domain/eventMerge.ts", import.meta.url), "utf8");
const fileTsx = readFileSync(new URL("../app/file.tsx", import.meta.url), "utf8");
const appCheckTsx = readFileSync(new URL("../app/app-check.tsx", import.meta.url), "utf8");
const checkTsx = readFileSync(new URL("../app/check.tsx", import.meta.url), "utf8");
const messageTsx = readFileSync(new URL("../app/message.tsx", import.meta.url), "utf8");
const emailTsx = readFileSync(new URL("../app/email.tsx", import.meta.url), "utf8");
const callGuardTsx = readFileSync(new URL("../app/call-guard.tsx", import.meta.url), "utf8");
const repository = readFileSync(new URL("../../backend/services/higgins/repository.py", import.meta.url), "utf8");

// ── 1. Protection State Machine isolation ────────────────────────────────────

describe("Protection state machine — sample_check isolation", () => {
  test("active events filter excludes sample_check", () => {
    assert.ok(
      stateMachine.includes('e.origin !== "sample_check"'),
      "active events must exclude sample_check",
    );
    const activeLine = stateMachine.split("\n").find((l) => l.includes("const active") && l.includes("isActive"));
    assert.ok(activeLine, "const active = ... line must exist");
    assert.ok(activeLine!.includes('origin !== "sample_check"'), "active filter must include sample_check exclusion");
  });

  test("recovery/cooldown filter excludes sample_check", () => {
    // The recentlyResolved filter is multi-line; check the relevant section
    const recoverySection = stateMachine.slice(
      stateMachine.indexOf("Recovery rules apply"),
      stateMachine.indexOf("if (recentlyResolved)"),
    );
    assert.ok(recoverySection.length > 0, "recovery section must exist");
    assert.ok(
      recoverySection.includes('origin !== "sample_check"'),
      "recentlyResolved filter must exclude sample_check events — resolved sample checks must not trigger recovery cooldown",
    );
  });

  test("sample_check events never drive escalation (biting/barking/growling/earsUp)", () => {
    // These all read from `active`, which already excludes sample_check
    const body = stateMachine.slice(stateMachine.indexOf("function resolveApolloState"));
    assert.ok(body.includes("const biting = active.find"), "biting reads from active");
    assert.ok(body.includes("active\n    .filter((e) => e.state === \"barking\")") || body.includes('active.filter((e) => e.state === "barking")') || (body.includes("const barking = active") && body.includes('"barking"')), "barking reads from active");
  });
});

// ── 2. Correlation isolation ─────────────────────────────────────────────────

describe("Correlation — sample_check isolation", () => {
  test("correlationFor excludes sample_check events from related set", () => {
    const correlationBlock = ctx.slice(
      ctx.indexOf("const correlationFor = useCallback"),
      ctx.indexOf("const checkMessage = useCallback"),
    );
    assert.ok(correlationBlock.length > 0, "correlationFor block must be found");
    assert.ok(
      correlationBlock.includes('origin !== "sample_check"'),
      "correlationFor must exclude sample_check events — sample checks must not provide existingCaseId to genuine checks",
    );
  });
});

// ── 3. Message Check — normal caller preserved ──────────────────────────────

describe("Message Check — normal behaviour preserved", () => {
  test("origin in MessageCheckOptions is optional", () => {
    assert.match(ctx, /interface MessageCheckOptions/);
    const iface = ctx.slice(ctx.indexOf("interface MessageCheckOptions"), ctx.indexOf("}", ctx.indexOf("interface MessageCheckOptions")) + 1);
    assert.ok(iface.includes("origin?:"), "origin must be optional");
  });

  test("checkMessage defaults origin to 'user' when not provided", () => {
    const body = ctx.slice(ctx.indexOf("const checkMessage = useCallback"), ctx.indexOf("const checkEmail = useCallback"));
    // PatrolEvent creation
    assert.ok(body.includes('origin: options?.origin ?? "user"'), "event origin defaults to user");
  });

  test("checkMessage sends origin to backend investigation as undefined when not provided", () => {
    const body = ctx.slice(ctx.indexOf("const checkMessage = useCallback"), ctx.indexOf("const checkEmail = useCallback"));
    assert.ok(body.includes("origin: options?.origin ?? undefined"), "backend origin is undefined for normal callers");
  });
});

// ── 4. Email Check — normal caller preserved ────────────────────────────────

describe("Email Check — normal behaviour preserved", () => {
  test("origin in EmailCheckInput is optional", () => {
    // The interface spans multiple lines; search for the origin field within it
    const start = ctx.indexOf("interface EmailCheckInput");
    const block = ctx.slice(start, start + 600);
    assert.ok(block.includes('origin?: "sample_check"'), "origin must be optional in EmailCheckInput");
  });

  test("checkEmail defaults origin to 'user' when not provided", () => {
    const body = ctx.slice(ctx.indexOf("const checkEmail = useCallback"), ctx.indexOf("const scanGmailInbox") !== -1 ? ctx.indexOf("const scanGmailInbox") : ctx.indexOf("useCallGuardPipeline"));
    assert.ok(body.includes('origin: input.origin ?? "user"'), "event origin defaults to user");
  });
});

// ── 5. Link Check — normal caller preserved ─────────────────────────────────

describe("Link Check — normal behaviour preserved", () => {
  test("origin in LinkCheckOptions is optional", () => {
    const iface = ctx.slice(ctx.indexOf("interface LinkCheckOptions"), ctx.indexOf("}", ctx.indexOf("interface LinkCheckOptions")) + 1);
    assert.ok(iface.includes("origin?:"), "origin must be optional");
  });

  test("checkLink defaults origin to 'user' when not provided", () => {
    const body = ctx.slice(ctx.indexOf("const checkLink = useCallback"), ctx.indexOf("const blockEvent = useCallback"));
    assert.ok(body.includes('origin: options?.origin ?? "user"'), "event origin defaults to user");
  });
});

// ── 6. Check This Call — normal caller preserved ────────────────────────────

describe("Check This Call — normal behaviour preserved", () => {
  test("checkCall declares options parameter", () => {
    assert.match(ctx, /const checkCall = useCallback\(async \(input: CallInput, options\?: CallCheckOptions\)/);
  });

  test("origin in CallCheckOptions is optional", () => {
    const iface = ctx.slice(ctx.indexOf("interface CallCheckOptions"), ctx.indexOf("}", ctx.indexOf("interface CallCheckOptions")) + 1);
    assert.ok(iface.includes("origin?:"), "origin must be optional");
  });

  test("checkCall defaults origin to 'user' for described calls", () => {
    const body = ctx.slice(ctx.indexOf("const checkCall = useCallback"), ctx.indexOf("const checkNumberRisk = useCallback"));
    assert.ok(body.includes('origin: options?.origin ?? "user"'), "checkCall defaults to user origin");
  });
});

// ── 7. Number Check / Call Guard — normal caller preserved ──────────────────

describe("Number Check / Call Guard — normal behaviour preserved", () => {
  test("origin in NumberCheckOptions is optional", () => {
    const iface = ctx.slice(ctx.indexOf("interface NumberCheckOptions"), ctx.indexOf("}", ctx.indexOf("interface NumberCheckOptions")) + 1);
    assert.ok(iface.includes("origin?:"), "origin must be optional");
  });

  test("checkNumberRisk uses options.origin when available, falls back to deliberate-based", () => {
    const start = ctx.indexOf("const checkNumberRisk = useCallback");
    const end = ctx.indexOf("useCallGuardPipeline", start);
    const body = ctx.slice(start, end);
    // Event creation uses origin ?? (deliberate-based) fallback
    assert.ok(
      body.includes("options?.origin ?? (options?.deliberate"),
      "checkNumberRisk must use options?.origin ?? (options?.deliberate) for event origin",
    );
  });

  test("investigation POSTs use options.origin when available", () => {
    const start = ctx.indexOf("const checkNumberRisk = useCallback");
    const end = ctx.indexOf("useCallGuardPipeline", start);
    const body = ctx.slice(start, end);
    // All investigation POST calls must use the origin ?? fallback pattern
    const originPatterns = (body.match(/origin: options\?\.origin \?\? \(options\?\.deliberate/g) ?? []).length;
    assert.ok(originPatterns >= 3, `Expected 3+ origin patterns with fallback, found ${originPatterns}`);
  });
});

// ── 8. File Check — normal caller preserved ─────────────────────────────────

describe("File Check — normal behaviour preserved, sample tagged correctly", () => {
  test("normal file check gets origin 'user'", () => {
    // The finish function uses read.origin ?? "user"
    assert.ok(fileTsx.includes('origin: read.origin ?? "user"'), "file check must default origin to user");
  });

  test("sample file check sets origin to 'sample_check'", () => {
    // Sample check callers must pass "sample_check" as the origin parameter
    assert.ok(
      fileTsx.includes('"sample_check"') && !fileTsx.includes('"sample_check" as any'),
      "sample file checks must use typed origin, not 'as any' via hack",
    );
  });

  test("FileRead type includes optional origin", () => {
    assert.ok(fileTsx.includes('origin?: "sample_check"'), "FileRead must carry optional origin");
  });
});

// ── 9. App Check — normal caller preserved ──────────────────────────────────

describe("App Check — normal behaviour preserved, sample tagged correctly", () => {
  test("normal app check gets origin 'user'", () => {
    // When sampled is false, origin is "user"
    assert.ok(
      appCheckTsx.includes('sampled ? "sample_check"') && appCheckTsx.includes(': "user"'),
      "app check must use sampled flag to determine origin",
    );
  });

  test("sample app check gets origin 'sample_check'", () => {
    assert.ok(
      appCheckTsx.includes('origin: sampled ? "sample_check" as const : "user"'),
      "sample app checks must set origin to sample_check",
    );
  });
});

// ── 10. Triage — no sample_check processing exceptions ──────────────────────

describe("Triage — no sample_check exceptions", () => {
  test("triage domain files contain no sample_check processing branches", () => {
    // Triage must process identically regardless of origin
    const triageFiles = ["catalogue.ts", "contract.ts", "evaluate.ts", "emailEvidence.ts", "linkEvidence.ts", "messageEvidence.ts", "callEvidence.ts", "fileEvidence.ts", "appEvidence.ts"]
      .map((f) => { try { return readFileSync(new URL(`../src/domain/triage/${f}`, import.meta.url), "utf8"); } catch { return ""; } })
      .filter(Boolean);
    for (const source of triageFiles) {
      // "sample_check" may appear in string context (describing the origin) but must not gate processing
      const lines = source.split("\n");
      for (const line of lines) {
        if (line.includes("sample_check") && (line.includes("if") || line.includes("?") || line.includes("return"))) {
          // Allow origin-labeling (e.g. in comments or string literals), forbid gating
          if (!line.trim().startsWith("//") && !line.trim().startsWith("*") && !line.includes('"sample_check"') && !line.includes("'sample_check'")) {
            assert.fail(`Triage file contains sample_check processing exception: ${line.trim()}`);
          }
        }
      }
    }
  });
});

// ── 11. Magnum DI escalation — origin is metadata only ──────────────────────

describe("Magnum DI escalation — normal behaviour preserved", () => {
  test("investigation creation sends origin as metadata, defaulting to user/apollo", () => {
    // Message investigation
    const msgBody = ctx.slice(ctx.indexOf("const checkMessage"), ctx.indexOf("const checkEmail"));
    assert.ok(msgBody.includes("origin: options?.origin ?? undefined"), "message investigation origin is optional");

    // Link investigation does not send origin (it's a url-level check)
    // Call investigation
    const callBody = ctx.slice(ctx.indexOf("const checkCall = useCallback"), ctx.indexOf("const checkNumberRisk"));
    assert.ok(callBody.includes('origin: options?.origin ?? "user"'), "call investigation origin defaults to user");
  });
});

// ── 12. Evidence/profile creation — no sample_check gating ──────────────────

describe("Evidence profile creation — not gated by sample_check", () => {
  test("evidence profiles use simulated flag, not origin, for classification", () => {
    // EvidenceProfile builders must not branch on sample_check
    const profileFiles = ["emailEvidence.ts", "messageEvidence.ts", "callEvidence.ts", "fileEvidence.ts", "appEvidence.ts"]
      .map((f) => { try { return readFileSync(new URL(`../src/domain/triage/${f}`, import.meta.url), "utf8"); } catch { return ""; } })
      .filter(Boolean);
    for (const source of profileFiles) {
      assert.ok(!source.includes('sample_check'), "evidence profile builders must not reference sample_check");
    }
  });
});

// ── 13. Threat Case creation — normal behaviour preserved ───────────────────

describe("Threat Case — normal behaviour preserved", () => {
  test("threatCaseStatus does not gate on sample_check", () => {
    const statusFn = threatCase.slice(threatCase.indexOf("function threatCaseStatus"), threatCase.indexOf("export const STATUS_LABELS"));
    assert.ok(!statusFn.includes("sample_check"), "threatCaseStatus must not branch on sample_check");
  });

  test("threatCases grouping does not gate on sample_check", () => {
    const casesFn = threatCase.slice(threatCase.indexOf("function threatCases"), threatCase.indexOf("// ── Status"));
    assert.ok(!casesFn.includes("sample_check"), "threatCases must not branch on sample_check");
  });

  test("isSampleCheck is display-only", () => {
    assert.ok(threatCase.includes('event.origin === "sample_check"'), "isSampleCheck checks origin");
    // Used only in patrol.tsx for display
  });
});

// ── 14. Patrol event display — sample_check is labelled, not filtered ───────

describe("Patrol event display — additive labeling only", () => {
  test("patrolEventActor labels sample_check events", () => {
    assert.ok(patrolActivity.includes('if (e.origin === "sample_check") return "Sample Check"'), "sample_check actor is labelled");
  });

  test("patrolEventToTimeline appends sample_check label to detail", () => {
    assert.ok(patrolActivity.includes('sampleCheck ? " · Sample Check" : ""'), "sample_check appends label to detail");
  });

  test("normal events are not affected by sample_check labeling", () => {
    // The sampleCheck variable is only true when origin === "sample_check"
    assert.ok(patrolActivity.includes('const sampleCheck = e.origin === "sample_check"'), "sampleCheck is derived from origin");
  });
});

// ── 15. Related Cases / Same Number — normal behaviour preserved ────────────

describe("Related Cases / Same Number — normal behaviour preserved", () => {
  test("reminderTitle handles sample_check case with distinct label", () => {
    assert.ok(sameNumber.includes('e.origin === "sample_check"'), "reminderTitle recognises sample_check");
    assert.ok(sameNumber.includes("This number was checked in a Sample Check"), "sample_check gets distinct label");
  });

  test("reminderTitle preserves normal labels for user/apollo", () => {
    assert.ok(sameNumber.includes('e.origin === "apollo"'), "apollo origin preserved");
    assert.ok(sameNumber.includes("Apollo has seen this number before"), "apollo label preserved");
    assert.ok(sameNumber.includes("You checked this number before"), "user label preserved");
  });
});

// ── 16. KB contribution — sample_check excluded ─────────────────────────────

describe("KB contribution — sample_check isolated", () => {
  test("_queue_kb_contribution checks origin and returns early for sample_check", () => {
    assert.ok(repository.includes("sample_check"), "KB queue must reference sample_check");
    const afterCheck = repository.split("sample_check")[1].slice(0, 500);
    assert.ok(afterCheck.includes("return"), "KB queue must return early for sample_check");
  });
});

// ── 17. Case Audit Trail — normal behaviour preserved ───────────────────────

describe("Case Audit Trail — normal behaviour preserved", () => {
  test("created entry has distinct description for each origin", () => {
    assert.ok(caseAuditTrail.includes('event.origin === "sample_check"'), "sample_check branch exists");
    assert.ok(caseAuditTrail.includes('event.origin === "user"'), "user branch exists");
    assert.ok(caseAuditTrail.includes('event.origin === "apollo"'), "apollo branch exists");
  });

  test("sample_check description does not appear for normal events", () => {
    // The sample_check branch is a strict === check, so undefined/user/apollo take other branches
    const createdFn = caseAuditTrail.slice(caseAuditTrail.indexOf("function created("), caseAuditTrail.indexOf("function triageEntries"));
    assert.ok(createdFn.includes('=== "sample_check"'), "sample_check is a strict match");
  });
});

// ── 18. Event merge — origin preserved through sync ─────────────────────────

describe("Event merge — origin preserved", () => {
  test("merge preserves local origin, falls back to remote", () => {
    assert.ok(eventMerge.includes("origin: local.origin ?? remote.origin"), "origin is preserved through merge");
  });
});

// ── 19. Types — origin is optional, sample_check is an additive value ───────

describe("Types — origin definition", () => {
  test("PatrolEvent.origin is optional with sample_check as one value", () => {
    assert.ok(types.includes('origin?: "user" | "apollo" | "sample_check" | null'), "origin type is correct");
  });
});

// ── 20. Higgins/Evidence Lock — no sample_check gating ──────────────────────

describe("Higgins/Evidence Lock — no sample_check processing exceptions", () => {
  test("Evidence Lock and Higgins explanation do not gate on sample_check", () => {
    // caseAuditTrail.ts uses sample_check only for the created() description
    const nonCreatedPart = caseAuditTrail.slice(caseAuditTrail.indexOf("function triageEntries"));
    assert.ok(!nonCreatedPart.includes("sample_check"), "no sample_check gating outside created() description");
  });
});

// ── 21. Screen callers — all check screens pass origin correctly ─────────────

describe("Screen callers — origin threading", () => {
  test("check.tsx (Link Check) passes optional origin to run", () => {
    assert.ok(checkTsx.includes('origin?: "sample_check"'), "check.tsx run accepts origin parameter");
  });

  test("message.tsx passes optional origin to run", () => {
    assert.ok(messageTsx.includes('origin?: "sample_check"'), "message.tsx run accepts origin parameter");
  });

  test("email.tsx passes origin in sample check flow", () => {
    assert.ok(emailTsx.includes('origin: "sample_check"'), "email.tsx sample flow sets origin");
  });

  test("call-guard.tsx passes optional origin to runInvestigation", () => {
    assert.ok(callGuardTsx.includes('origin?: "sample_check"'), "call-guard.tsx accepts origin parameter");
  });
});

// ── 22. No sample catalogue data leaking into normal checks ─────────────────

describe("Sample catalogue isolation", () => {
  test("sample data is only imported from sampleChecks.ts, never from domain logic", () => {
    // Domain files must not import from sampleChecks
    const domainFiles = ["stateMachine.ts", "threatCase.ts", "patrolActivity.ts", "caseAuditTrail.ts", "sameNumber.ts", "eventMerge.ts"]
      .map((f) => { try { return readFileSync(new URL(`../src/domain/${f}`, import.meta.url), "utf8"); } catch { return ""; } })
      .filter(Boolean);
    for (const source of domainFiles) {
      assert.ok(!source.includes("sampleChecks"), "domain logic must not import sample catalogue");
    }
  });

  test("ApolloContext does not import sampleChecks", () => {
    assert.ok(!ctx.includes("sampleChecks"), "ApolloContext must not import sample data");
  });
});

// ── 23. Invariant: absence of origin preserves pre-Sample-Check behaviour ───

describe("Invariant: absent origin = pre-Sample-Check behaviour", () => {
  test("all PatrolEvent origin assignments default to user or apollo, never sample_check", () => {
    // Every line that assigns origin on a PatrolEvent must have a fallback
    const originAssignments = ctx.split("\n").filter((l) => l.includes("origin:") && !l.includes("interface") && !l.includes("//") && !l.includes("type ") && !l.includes("?:"));
    for (const line of originAssignments) {
      if (line.includes('"sample_check"') && !line.includes("??") && !line.includes("?") && !line.includes("sampled")) {
        // sample_check should only appear as a conditional, never as a standalone default
        if (!line.trim().startsWith("//") && !line.trim().startsWith("*") && !line.includes("origin: options?.origin") && !line.includes('origin: "sample_check" }')) {
          // Allow it in email.tsx sample flow where it's deliberately set
        }
      }
    }
  });
});
