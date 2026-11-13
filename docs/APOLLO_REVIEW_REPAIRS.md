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
