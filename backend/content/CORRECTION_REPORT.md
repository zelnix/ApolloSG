# ApolloSG — Targeted Code Corrections Report

Scope: the three issues raised in the ApolloSG PRD v2.3 code review (calibration fixture mutation,
Magnum DI calibration-coverage reporting, Verification Playbook evidence integrity), fixed by editing
shared logic only — no case-specific branches, no score/threshold changes, no new testing framework,
no duplication of the real investigation pipeline. Verified with the existing `pytest` suite (no
`testing_agent` run, per instruction).

## 1. Calibration fixture mutation — fixed

**File:** `backend/tests/test_calibration_reference_library.py` — `_apply_ground_truth()`.

**Root cause:** `fact_kwargs.pop("place", None)` mutated the *same* dict object stored on the
module-level `CASES` list (built once at import time, by `reference_cases.gt()`). `_run()` — and
therefore `_apply_ground_truth()` — is called on the same case more than once in a normal test run:
once inside the module-scoped `calibration_results` fixture (used by `TestEveryCaseSettlesAtTcHawkeye`
and `TestScoreCalibrationReport`), and once more, independently, by
`TestFindingTierAccuracy.test_case_reaches_the_target_finding_tier`. The first call permanently
stripped `"place"` from the shared dict; every later call for that case ran with an incomplete
ground truth, with the actual result depending on which test ran first.

**Proven impact (before the fix, on this session's checkout):**
```
run1 (fresh ground_truth):  scam 75
run2 (place already popped by run1): CRASH — StopIteration in report.py:750
  `place = next(f["place"] for f in facts if f.get("place"))`
```
Case 002 (a confirmed-scam case) doesn't just score differently on repeat — `report.compose()`
raises, because `impersonation_result()` requires at least one ground-truth fact to carry `"place"`.
This is a real, order-dependent defect, not a cosmetic one.

**Fix:** read `fact_kwargs.get("place")` and build a new `fact_args` dict excluding `"place"`, instead
of mutating the original. Nothing else in the function changed.

**Verified:** ran case 002 through `_run()` three times in one process — byte-identical results each
time, and the fixture's own `ground_truth` dict still carries `"place"` afterwards.

## 2. Magnum DI calibration coverage — clarified

**File:** `backend/tests/test_calibration_reference_library.py`.

**Root cause:** the report only ever distinguished "settled by TC Hawkeye" vs. "not settled" (escalated).
An escalated case being *correctly routed* to Magnum DI was the only fact available — but nothing in
the report said so explicitly, so a reader could mistake "escalated" for "investigated and confirmed."
No Finding from Magnum DI is actually produced by this suite (that requires a live case/job and a real
provider call through `services.higgins.coordinator.run_turn` — a different, heavier pipeline this
suite does not stand up, by design).

**Fix (reporting only, no pipeline change):** every case result and the written
`content/calibration_results.json` now carry four explicit, non-overlapping buckets:
- `tcHawkeyeResolved` — settled deterministically; tier-checked by `TestFindingTierAccuracy`.
- `correctlyRequiresMagnumDi` — TC Hawkeye's routing decision was correct (PRD-intended), nothing more.
- `magnumDiFindingsVerifiedEndToEnd` — escalated cases whose actual Magnum DI Finding was produced and
  checked against target. Always `0` in this suite, with a note explaining why.
- `unverifiedBeyondRouting` — the same escalated cases, explicitly flagged as *not* end-to-end verified.

Added assertions (`TestEveryCaseSettlesAtTcHawkeye`, `TestScoreCalibrationReport`) that the four buckets
partition the 55 cases exactly, and that no escalated case is ever marked as Magnum-DI-verified by this
suite — so a future accidental "upgrade" of the escalation report into a false verification claim would
itself fail a test, rather than silently passing.

**Verified:** `tcHawkeyeResolved.count` (32) + `correctlyRequiresMagnumDi.count` (23) = 55;
`magnumDiFindingsVerifiedEndToEnd.count` = 0; `unverifiedBeyondRouting.count` = 23 — matches the 23
case IDs already reported as escalated before this change (005, 007, 012, 013, 015, 027, 028, 062,
063, 066, 070, 072, 073, 076, 077, 078, 079, 082, 086–090). No routing or scoring behaviour changed.

## 3. Verification Playbook evidence integrity — fixed

**File:** `backend/services/higgins/tc_flyby/playbook_runner.py`.

**Root cause:** every step resolver returned `"completed"` whenever it found anything, whether the
finding came from an external authoritative source (RDAP, Google Safe Browsing, ABR/ASIC check-digit,
Apollo's org-contact directory — real registry/reputation lookups in `official.py`) or from Apollo's
own internal detection (a matched KB scam pattern, extracted claim/urgency text, a consequential
request, an OTP-style ask). Both were labelled identically, so a completed pattern match could be read
as if an independent party had verified it.

**Fix:** four resolvers that read genuinely external facts (`company_registry`, `link_reputation`,
`contact_crossref`, `licence_check`, `person_crossref`) now return `"verified"` on a hit. Four
resolvers that read Apollo's own detection output (`scam_pattern_match`, `claims_and_urgency`,
`consequential_request`, `otp_request_check`) now return `"inferred"` on a hit — explicitly flagged in
each one's docstring as *not* an external party confirming anything. `"inconclusive"`, `"unavailable"`
and `"not_applicable"` are unchanged. Every step result also now carries a new `evidenceSource` field
(`external_verification` | `internal_detection` | `none`) so the provenance is explicit without having
to infer it from the status word. The escalation logic in `run_playbook()` (`unavailable_or_inconclusive`
count) was not touched — it never referenced `"completed"`, so this rename cannot change which cases
escalate.

**Verified:** no test file in `backend/tests/` references the playbook step status vocabulary or the
`playbooks` field directly (confirmed by search), and `final["playbooks"]` is typed as a loose
`list[dict]` in both `contracts.py` and `response_schema.py` (no enum constraint on `status`) — so this
is a pure clarity fix with zero schema or behavioural impact.

## 4. Full regression run

`pytest tests/` (1977 tests, the entire backend suite) was run in full after these changes, chunked to
fit execution limits (4 chunks by file name + a standalone re-run of the one flaky file below):

| Chunk | Result |
|---|---|
| 1 (44 files) | 501 passed, 25 skipped |
| 2 (44 files) | 419 passed, 1 skipped |
| 3 (42 files) | 429 passed, 1 xpassed |
| 4 (42 files) | 585 passed, 13 skipped, **3 failed** (below) |

`tests/test_calibration_reference_library.py` itself: **35 passed, 23 skipped, 0 failed** — identical
pass/skip counts to before this session's changes; only the fixture's internal mechanics and the
written report's shape changed, not any routing or score outcome.

**3 failures found, all confirmed pre-existing and unrelated** (reproduced identically with `git
stash` applied against this session's two changed files — i.e. present before and after):
- `test_rulebook.py::test_the_rule_book_was_reviewed_after_the_last_rule_change` — `decide.py`'s
  content hash no longer matches `content/rulebook.lock.json`'s stamp from an earlier session; this
  session made no change to `decide.py`. Needs `python scripts/rulebook_stamp.py` run by whoever last
  touched `decide.py`'s rules — out of this correction's scope.
- `test_reusable_intel.py::test_the_kb_retrieval_benchmark_reproduces_its_baseline` (×2, main +
  holdout) — same drift already flagged in `content/CALIBRATION_REPORT.md` from the previous session
  (two new KB patterns were added then; the baseline needs re-recording with
  `scripts/kb_benchmark.py --record`). Unaffected by this session's three fixes.
- `test_tombstone_sweep.py::test_thousands_of_deleted_cases_cost_nothing_when_their_content_is_gone` —
  order-dependent (passes inside the full chunked run, fails when run standalone); stale shared
  test-database state, also already flagged previously. Unrelated to triage/decide/playbooks.

No new failures were introduced. No decisive-mechanism, scoring, threshold or Finding-tier behaviour
changed — confirmed by the calibration suite's own 32/32 tier-match count being unchanged, and by the
`correctlyRequiresMagnumDi` case-ID list matching the previous session's 23 escalated IDs exactly.

## Remaining limitations

- Magnum DI's actual Findings for the 23 escalated reference cases remain unverified end-to-end by any
  automated test — that would require standing up the full case/job pipeline with a live or simulated
  provider call, which is intentionally out of this suite's scope (and out of this correction's scope,
  per instruction not to duplicate the investigation pipeline). The report now says this plainly
  instead of implying otherwise.
- The three pre-existing failures above (rulebook stamp drift, KB benchmark baseline drift, flaky
  tombstone test) are untouched, as they are unrelated to the three scoped corrections.
