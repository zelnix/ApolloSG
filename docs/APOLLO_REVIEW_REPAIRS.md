# ApolloSG review repairs — 13 November 2026

Baseline: `slm` commit `9d64b06cea7a3d72846960dd18a4ce2851caad6f`.
This record describes local implementation and verification. It is not a claim
that an APK, an iOS build, a desktop runtime, or a deployment has been qualified.

## Preserved architecture

The workflow remains Apollo/user intake → required on-device Wright Triage →
TC Hawkeye → required on-device Higgins escalation assessment → optional
Magnum DI external investigation → required on-device Finding and Luddish
presentation → the existing fenced case acceptance. No second investigator,
verdict engine or cloud fallback was added.

Original evidence, extracted derivatives, external observations and model
interpretations retain their identities and provenance. Evidence Lock remains
an invariant of ingestion, validation and commit, not a separate investigator.
Protection state and packet-backed Biting rules were not relaxed.

## Repairs mapped to the review

| Finding | Implementation |
|---|---|
| F1 startup | Repaired literal escaped newlines in four Python files. Removed stale Safe Browsing imports and status probes. Active URL checks and revalidation use the existing quota-controlled Web Risk service. Historical Safe Browsing entries are not silently reverified against a different provider. |
| F2 Finding authority | The actual validator enforces established/provisional evidence floors; the coordinator supplies Hawkeye's retained floor. A clear Finding cannot pass with material coverage gaps. Partial examination stays partial. |
| F3 entry points and lifecycle | Cases without an explicit profile resolve metadata from their authenticated device registration. One app-owned SLM inbox executor survives navigation and recovers outstanding requests; SSE wakes it rather than owning a second executor. |
| F4 failures | The job runner handles unavailable on-device stages explicitly. An authenticated failed-request response retains bounded diagnostic codes on the existing device request, without turning failure into evidence. |
| F5 evidence pickup | A pickup contains an encrypted byte copy separate from working-copy expiry. The client transfers every manifest item to durable platform storage, verifies SHA-256 and readback, saves the source-linked manifest, then confirms the exact snapshot. Saved evidence views read verified local bytes first. Failed checks also retain their manifests. |
| F6 deletion | Continuation checkpoints, pickup chunks and DI processing payloads are included in deletion lifecycles. Case expiry removes processing payloads while the explicitly held pickup waits for the device. Late writes are fenced/reconciled. Account deletion keeps the identity available for retry if deletion fails. |
| F7 context/modalities | Later local stages can read source windows before bounded synthesis. If the complete synthesis still exceeds native capacity, the case stops explicitly. Binary originals are represented as inventory gaps, never fabricated text; their derived text and external examination remain separately identifiable. |
| F8 semantic integration | Wright's semantic interpretation now focuses existing verification checks. It does not satisfy checks, add verified facts, or overwrite evidence. Its synthesized intent and narrative are retained rather than replaced by generic wording. |
| F9 naming | Historical imports alias the exact canonical Hawkeye modules. Compatibility readers handle old and new persisted record names; current writes use Hawkeye names. |
| F10 Magnum continuation | Each external window and checkpoint checks the live job/epoch/fence. Failure status, diagnostic message, finish reason and returned text are retained. Grounding sources, simulation provenance and successful examination coverage propagate. Image labels travel with their bytes. |
| F11 consistency/CI | Regenerated the frontend triage catalogue from its backend source. Replaced unrelated general CI configuration with Apollo-specific isolated regression checks on `slm`, main and master. Removed test collection pollution that replaced real database modules globally. |
| F12 capabilities | The response reads the canonical case lifetime policy key and reports Web Risk configuration passively. |

Additional changes make authoritative local writes fail visibly, serialize
result/index/queue mutations, preserve case-sensitive evidence in dedupe keys,
and exclude simulated/partial results from the completed-result KB queue.
Downloads are pinned to the public Qwen repository revision
`9217f5db79a29953eb74d5343926648285ec7e67`; this does not claim that lightweight
admission is full-file checksum verification. Explicit installation can recover
from an invalid partial model package while preserving it for diagnosis.

## Evidence pickup contract

`GET /investigations/{caseId}/pickup` returns a snapshot ID, the evidence graph
and a manifest of evidence IDs, byte lengths and SHA-256 digests. The existing
authenticated API serves each manifest item through
`/investigations/{caseId}/pickup/{snapshotId}/evidence/{evidenceId}`.

Native byte archives use application document storage; web archives use IndexedDB.
Both are scoped to the device identity and case. The client verifies each
download, writes it, verifies readback and persists the manifest before sending
`saved.snapshotId` and `saved.evidenceDigests` to the existing confirm endpoint.
Missing or changed bytes, failed storage, a changed snapshot, or another device's
request cannot authorize release. Confirmation is idempotent after cleanup.
The final revoke compares the case revision atomically. Failed cleanup leaves
the pickup held, and both server and client keep retrying instead of recording
a successful purge. A cancelled external call retains its irreversible call
claim even when its late checkpoint payload is discarded.

Working case TTLs remain distinct from the owner's held pickup copy. Case/account
deletion and case wipe remove pickup chunks as well. Old pickups lacking a
complete manifest are not certified as complete; missing historic evidence
cannot be reconstructed or invented.

## Verification

Local checks use a disposable MongoDB 7 container, isolated database names,
ephemeral investigation encryption keys and no configured provider credentials.
Live AI calls are forbidden in bounded tests.

- Whole-backend Python compilation without execution (**455 files**) and real
  application import.
- Full application lifespan reached startup completion against isolated MongoDB.
- Combined backend regression selection: **270 passed, 2 pre-existing skips,
  9 subtests passed**, including ownership, checksum
  corruption, working-copy expiry, cancellation, cleanup, provider failure and
  simulation provenance, replay, legacy record compatibility and native failure
  diagnostics.
- Existing scoring, taxonomy, evidence-evaluation, Wright-window and business
  identity regressions are included in that backend count.
- Actual local HTTP server: **31 passed** for device authentication, enforcement
  evidence gates, case deletion and account deletion.
- Frontend SLM/native-binding mocks, triage catalogue/parity, window handling,
  evidence transfer corruption/storage failure, report evidence and protection truth.
- Complete frontend TypeScript checking and linting of changed TypeScript files
  (zero errors; 16 existing warnings remain).
- Expo web export completed. This is a bundle/build check, not web support for
  mandatory native inference.
- Chromium exercised the actual IndexedDB implementation: durable readback,
  SHA-256, device isolation, case deletion and all-data deletion passed. The
  local test build displayed the existing safe-start screen for its mismatched
  security configuration without uncaught JavaScript errors; no admission guard
  was bypassed to reach application navigation.
- CI YAML and its disposable encryption-key generation were checked locally;
  the public backend dependency selection resolved successfully in a pip dry run.

See `.github/workflows/ci.yml` for the repeatable bounded gate. The two historical
recovery tests already marked skipped concern the removed tool-ledger coordinator;
they do not establish current device or provider acceptance.

## Remaining qualification and limits

- Android and iOS inference quality, lifecycle, memory/thermal behavior and
  physical-device storage/build acceptance still require supported devices.
- Windows/macOS still need a real native SLM adapter and security qualification.
  Their unsupported admission remains fail-closed; mobile inference is not
  represented as desktop support.
- Arbitrarily large cases are not promised to fit a small local model. Every
  window must succeed and the complete synthesis must fit; overflow is explicit.
- Model admission intentionally retains the existing lightweight policy rather
  than silently reversing the prior product decision about full-file hashing.
- No release build, remote CI run or production deployment is claimed by these
  local checks. The existing EAS build requires its build-owner configuration.

## Integration with the saved evidence-classification PRD

The combined revision merges `main` at
`4c311ac9c71df051e952ed946863373b204a684f` with the repaired `slm` revision
`01139d2df5ac55d772df6448413539d638f8a5fc`. Main's evidence-authoritative S/N/L
waterfall, six-dimension raw score, minimal score-band reconciliation, recognised
domain exception, regression fixtures and report transparency are retained in
the canonical Hawkeye modules. Historical FlyBy imports remain aliases to those
same modules. No second classifier or rating engine is introduced.

The existing on-device Finding acceptance now preserves this contract too:

- A resolved local classification is supplied to the model as a labelled,
  source-linked deterministic projection, distinct from original source facts.
- Without a completed independent investigation, a local model cannot replace
  that resolved verdict. The required local stage still runs; an inconsistent
  answer stops instead of silently substituting a result.
- The accepted local response retains the server's raw/aligned rating, adjustment
  reason, deciding rule IDs and related report fields. None are authored by the
  model. An independently investigated response does not mislabel Hawkeye's old
  numeric rating as its own.
- Main's safeguard against concern verdicts supported only by low-confidence
  findings is restored. Mixed-confidence findings are evaluated correctly.

The four merge conflicts were resolved around the renamed Hawkeye modules and
routing expectations. Executable definitions in finding_rules, scoring, decide
and report were compared against main and match after normalising the module
rename and documentation. The PRD regression files are preserved.

Combined local validation: **356 backend tests passed, 2 existing skips,
9 subtests passed; 31 HTTP tests passed; 21 selected frontend test files passed**.
Complete frontend TypeScript checking, web export and backend startup passed.
These bounded checks do not reproduce or claim the earlier full 2,024-test run.

The additional synthetic calibration run passed 49 tests. All 32 locally
resolved reference cases matched their target finding tiers; 23 cases requiring
Magnum DI were skipped for verdict verification and remain unverified beyond
routing. These calibration checks are also included in the expanded CI gate.

The repair-only revision `01139d2` also completed the standalone Android native
build after fixing literal escaped newlines in the call-screening declaration.
The final combined revision requires its own APK build and deployment. Native
CI now follows every frontend change, including classification report changes.

## Signed EAS APK configuration admission

The signed EAS build of `1049d39` compiled, but release-artifact inspection found
no backend URL in its Hermes bundle. EAS reported an empty production environment,
and the inherited production profile omitted `EXPO_PUBLIC_BACKEND_URL`.
`api/client.ts` requires this value during module evaluation, so compilation
success did not establish application startup.

The production EAS profile now explicitly supplies the owner's production API
base, `https://threat-patrol-1.emergent.host`. Production preflight rejects a
missing or malformed HTTPS base before native dependency/build admission,
including the EAS pre-install hook. Its integration tests are part of CI.
This changes build configuration only; the client retains its required explicit
environment value and the classification merge is unchanged. The earlier signed
artifact is not an accepted release; its replacement must be inspected separately.

The expanded frontend gate passes 188 tests. The exact production EAS profile
passes pre-install admission, and a local Android export embeds the exact
production API base in Hermes bytecode. Negative admission checks reject an
unset or non-HTTPS base before EAS's dependency-check deferral.

## Required 64-bit Android distribution

`frontend/config/android-abis.json` is the shared build/artifact policy. Expo's
existing build-properties plugin writes `arm64-v8a` to native Gradle
configuration for APK and optional Play AAB builds. ARM32 (`armeabi-v7a`) and
32-bit x86 are excluded because the required llama.rn runtime cannot load on
those targets. The owner also excluded x86-64, selecting ARM64-only distribution.
Production preflight rejects a missing or changed architecture list. The existing
ARM64-scoped physical-device test workflow remains scoped to that approved subset.

Artifact admission inspects every packaged native library's directory and ELF
header, requires the appropriate SLM libraries for every target, and rejects
32-bit native code, unexpected targets, missing targets and duplicate libraries.
Both the standalone upload and signed EAS release-link publication run this check.

Android rejects installation when no packaged native ABI matches its supported
process architectures. Google Play uses native ABI targeting to filter availability
and downloads; an uploaded AAB must retain the same policy and pass Play's device
catalogue checks. Public direct APK URLs, including Expo install URLs, cannot
prevent an incompatible browser from downloading bytes. Store availability is a
distribution control, and is not claimed for those direct links. Previously
published universal APKs are not changed or revoked by a new build.

The owner selected Google Play for future public distribution and Expo for
internal testing, then requested APK delivery only for now. The optional
`android-play-bundle.yml` workflow is manual-only; it builds the existing
production AAB profile with the same ARM64-only target and verifies the downloaded
bundle when explicitly requested. It does not claim a Play upload or
publication. The automatic APK workflow remains internal distribution.

The first two-target APK (`0a0786a`) built successfully, but its CI verifier's
plain HTTP request was rejected by Expo's artifact edge with HTTP 403. The
downloaded APK was independently verified through Expo's browser flow (257.3 MB,
82 native libraries across ARM64/x86-64, unchanged EAS signing certificate).
The verifier now uses Playwright's browser download transport; archive validation
remains fail-closed. Verification-only changes and tests do not trigger native
recompilation. The final ARM64-only APK requires its own build and inspection.

SLM is now a fixed core capability. Backend request dispatch, result intake and
coordinator stages no longer read a handoff environment switch. The llama.rn
native plugin is unconditional, and its old native-build selector is removed
from EAS and workflows. Behavioral regressions cover all three required stages
with an obsolete off setting, while a web profile remains unavailable. The
historical pilot/native integration documents are updated to prevent a preview
from being configured with a misleading optional-mode workaround.

The owner paused builds. EAS APK generation and standalone native APK compilation
are manual-only; repository pushes run regression checks without producing APKs.
No further artifact build is authorised until the owner requests it.

The pause canceled one matching active Expo build through the existing project
credentials; no new artifact build was started by that operation. The temporary
cancellation workflow was removed after its successful run. Local core-capability
validation passed 412 backend tests (25 skips, 12 subtests), 190 frontend tests
and 13 artifact-admission tests. These are code checks, not a new APK qualification.

## Model setup failure reported on Galaxy Z Fold6

The latest existing GitHub standalone artifact was retrieved and inspected:
`d6627ac`, application `app.apollo.hwg`, version 1.1.0 / versionCode 1,
177,595,536 bytes, ARM64-only with the llama runtime libraries present. That
does not establish native inference acceptance on the owner's phone.

Source-level reproductions exposed setup defects: the 120-second UI deadline
included the model download and consent prompts; a late successful download
could leave the gate blocked; the network watcher repeatedly paused already
approved cellular downloads and abandoned the original promise when Expo paused
it; and startup errors lost the file/binding reason and actual failed stage.

Installation now has separate progress and no boot-verification deadline.
Native verification retains its bounded deadline and operation lock, including
cleanup before retry. A single transfer session follows native pause/resume
promises, requests consent on observed network changes, and stops monitoring
when finished. Model admission remains required; specific safe diagnostics
distinguish missing/invalid/unreadable files, binding import, registration and
native loading failures. No source content, paths or native exception messages
are exposed. The existing model admission policy and evidence pipeline are
unchanged.

Sixteen startup regressions cover long downloads, timeout/operation ownership,
pause/resume/denied consent and native/file failures. These tests reproduce the
identified defects, not the owner's physical-device failure. A subsequent
explicitly authorised APK build and device run are still required to verify
the corrected behavior on the Fold6. No build was started for these changes.

The owner subsequently authorised one APK build. The update uses the existing
GitHub internal-test pipeline and its signing identity, matching the inspected
installed GitHub APK. Its local Android versionCode advances from 1 to 2; EAS
production keeps its separate remote version source. A temporary caller invokes
the existing native workflow once. Automatic build-on-source-push remains paused.

The requested run started from `773b624`. Its temporary caller was then removed;
the native workflow remains available only for explicit manual/reusable calls.
This records a build request, not successful physical-device inference.
Before public release, confirm ARM32/x86 devices are unavailable in Play's
Device Catalog, and remove any retained 32-bit artifacts from active tracks.
Expo's project setting for unauthenticated internal-build access must also be
disabled by the project owner; marking a build internal does not make a public
install URL enforce device compatibility or authenticated tester access.

## Number investigation Findings and structured native answers

The owner's number-investigation screenshots showed a failed on-device Higgins
Escalation Assessment (`json_parse:no_json_object`) while a separate successful
phone lookup was hidden in DI. The shared investigation view now presents that
same lookup once in Findings, initially expanded, with its caller summary,
advice, sources and geographic/range/exact-number detail. It stays mounted
during investigation and tab changes. An unfinished case keeps its failure and
resubmit controls; a lookup never creates or replaces an authorised case Finding.

Unknown ownership alone no longer produces a "likely scam" claim or claims of
completed web checks. Unknown-caller advice uses independent official contacts,
does not recommend trusting callback caller ID, and does not imply landlines
are harder to spoof. Cached responses refresh advice without changing recorded
facts, source dates or freshness. Evidence Lock no longer treats a failed routing
outcome or engine name as proof that a final decision was preserved.

The native runtime now supplies llama.rn's JSON-object response format for
grammar-constrained decoding and disables the optional thinking channel. It
reads the SDK's answer content when provided and rejects interrupted, truncated,
context-full or output-limited generations. Existing semantic/citation checks,
case isolation and all mandatory SLM stages remain in place. The screenshots
establish the parsing failure, not the exact generated text; constrained decoding
and output-status handling still require a subsequent physical-device check.
No APK or Expo build is authorised or started by this change.

Validation: the updated frontend regression gate passes all 264 tests, and the
phone guidance plus evidence-verdict/Magnum floor suites pass all 30 backend
tests. The five existing explanation acceptance cases also pass. Full TypeScript
checking and lint on the touched frontend files pass. An additional, unchanged
caller-list source-wording test in `callProtectionSetup.test.ts` still fails its
pre-existing expectation that `ScreenedCallsList.tsx` contains "this is not your
phone"; neither that test nor that component was changed here. The installed
build 2 APK is unchanged, and the Fold6 has not run these source changes yet.

## Latest on-device response status in Settings

The next Fold6 screenshot showed the built-in response test failing with
`json_parse:no_json_object` while Settings still reported Active from an earlier
successful inference. Shared runtime activity now records the latest actual
adapter response status, including contract rejection and inference failure,
without retaining prompts, evidence or native exception text. An older success
timestamp remains historical; it cannot keep the current status Active after a
failure. A later validated response restores Active. Replacement/removal of the
shared runtime clears status, and late responses from the old adapter cannot
update it. Settings also hides a stale explicit test label after newer activity.

Core Android response diagnostics are no longer described as disabled merely
because the developer-only manual model-import controls are hidden. Settings
describes local AI as required and removes the unconditional installation claim.
No background probe, model reinstall, fallback, environment toggle or new build
is introduced. The JSON-constrained decoding fix in `2f83d822` still needs an
explicitly requested APK and physical-device verification.

Validation: all 270 frontend regression-gate tests and full TypeScript checking
pass. New activity regressions reproduce the screenshot's success → JSON parse
failure → recovery, invalid citations, replacement-runtime fencing and activity
notifications without background inference. Shared activity/status code and tests
pass lint. Settings retains 31 pre-existing lint errors (primarily its nested
render component definitions); a comparison with the previous source confirms
no new lint diagnostics were introduced. No APK build was run.

## Account-notification false positives and report consistency (14 November 2026)

A synthetic Google account-access notification reproduced a contradiction: automatic Gate checks recorded no matching rules while Findings repeated an older scam warning; Evidence and History were empty because no investigation case existed.

- Read generic “secure your account” advice separately from explicit sign-in or secret-disclosure requests. Recognise account-access notifications without trusting their sender or cancelling later harmful requests. Mirror the request reader change in the backend.
- Exclude standalone email addresses from message URL candidates while retaining explicit URLs, including deceptive URL user-info.
- Treat a different sender/link domain as an unverified relationship rather than an automatic impersonation assertion. Keep warnings for sensitive requests with supporting context.
- Require independent concern-level corroboration before a branded shared-service link establishes false identity or deception. Preserve the existing treatment of lookalike registrable domains and independently malicious destinations; no provider or application hostname is whitelisted.
- Project a Gate-only record with no matching rules into Findings and attention status consistently. Explain that no threat was identified by available checks, without calling the message genuine. Preserve precedence for committed investigations, enforcement and recorded malicious-link evidence.
- Load the device's existing original into Evidence using the event ID as well as an optional investigation ID. Use the existing case audit trail for Gate-only History; do not invent investigation stages or timestamps.
- Re-read eligible local email cases under the updated reader version from their retained originals. Keep prior check records, user closures, source bytes and investigated cases intact.

The reporting and domain fixes do not grant model hypotheses authority to change an established Finding. Sender relationships and legitimate explanations still require evidence-based verification; established evidence floors remain in force.

Regression coverage includes a synthetic account-access notice, third-party links, recipient addresses, appended password/code theft, preserved historical records, lookalike-domain scam cases and malicious shared-service destinations. Source changes require a later APK and backend deployment; automatic APK builds remain paused.

## Restore Wright semantic triage — 14 November 2026

The readiness-only change from commit `145196c9` was reversed at the user's request. The Google notification's DI record showed automatic Gate checks with no matches; the incorrect scam wording came from the Findings presentation. That reporting problem did not justify replacing Wright's existing semantic triage.

Wright again uses the mandatory on-device `wright_semantic` / `wrightSemantic` (`wright.semantic.v1`) contract. Its source-cited interpretation covers scam indicators, legitimate context, intent, coercion, exposure and uncertainty. Hawkeye may use it to focus verification; it does not satisfy checks, create verified facts, issue a final Finding, or bypass the existing evidence classification and verdict floors. The native runtime, JSON output checks, device ownership and evidence fences remain mandatory.

The reporting, retained-original Evidence view, recorded History, latest inference status and corroboration fixes from later commits are preserved. No production data or historical case records are migrated or rewritten. No APK build or deployment was initiated. Native app and backend must use the same Wright contract.

Validation of the restoration: 328 frontend regression tests pass; TypeScript passes. The configured backend regression gate passes 438 tests plus 12 subtests, with 25 existing skips. An exact source comparison confirms all non-documentation files changed by the readiness-only commit match their pre-change versions, and all later reporting/false-positive source fixes remain byte-for-byte unchanged.
