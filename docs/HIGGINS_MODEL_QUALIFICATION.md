# Higgins generation and model qualification

Remote baseline resolved before edits: `5b95236bccb9610238cca694fee41ffe2316c93c`.
No branch reset or subsequent commits were discarded. No APK or deployment is part
of this work. No fine-tuning was initiated.

## Package comparison (metadata, not measured quality)

| Field | Reference | Proposed |
|---|---|---|
| Publisher | Qwen/Qwen2.5-0.5B-Instruct-GGUF | unsloth/Qwen3-1.7B-GGUF |
| Revision | 9217f5db79a29953eb74d5343926648285ec7e67 | d7f544eead698dbd1f15126ef60b45a1e1933222 |
| Filename | qwen2.5-0.5b-instruct-q4_k_m.gguf | Qwen3-1.7B-Q4_K_M.gguf |
| Bytes | 491400032 | 1107409472 |
| SHA-256 | 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db | b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897 |
| Context | existing 4096-token reference | qualify 8192 tokens; 4096 needs separate evaluation |
| Selection | available reference | Active by explicit owner request; qualification pending |

Metadata was read from Hugging Face model APIs with `blobs=true`. Candidate base
model is Qwen/Qwen3-1.7B, revision 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e.
Package URLs are constructed from the pinned source, revision and filename.
The proposed file exceeds one GiB. Profile-specific admission supports its actual
size and filename. Startup retains the established lightweight file/header policy;
recorded upstream SHA-256 is provenance metadata, not a claim of on-device hashing.

Installed llama.rn is 0.12.9. Its embedded source includes `cpp/models/qwen3.cpp`
and Qwen3 architecture registration in `cpp/llama-arch.cpp`. Its exposed SDK has
`getFormattedChat`, `tokenize`, `stopCompletion`, constrained JSON response formats
and `enable_thinking`. This is source-level compatibility evidence, NOT a verified
model load. Non-thinking formatting and completion both disable thinking. CPU
execution remains the reference; acceleration is not enabled by this change.

Initial output budgets: chat/Wright 384, window analysis/escalation 512, final
findings 1024 tokens. Sampling evaluation profiles record temperature 0.7,
top-p 0.8, top-k 20, min-p 0 for non-thinking and a lower-temperature comparison.
They are evaluation candidates, not evidence that lower temperature is better.
The runtime starts from the non-thinking profile; the constructor accepts the structured comparison profile for identical-case evaluation. Neither profile is quality-qualified.

## Context and timing

Ordinary chat retrieves structured context using `/higgins/chat/context`; it no
longer displays local diagnostic/product responder answers or silently falls back
to a backend conversational reply. Investigation intent still uses the existing
authenticated investigation path. Backend retrieval never calls Gemini. History
is filtered to the current conversation and one-hour retention, at most eight
messages. Quotations are checked verbatim; citations must be supplied passage IDs.
Missing/stale knowledge must be acknowledged. Case findings remain protected by
fidelity checks. Model failures are errors, not successful canned answers.

Product guidance and sourced KB excerpts retain IDs, titles, source URLs and date/
freshness metadata. At most six passages are retrieved. The local product cache
contains versioned static product guidance only, never device or case data.

Native admission tokenises the formatted chat template, instructions, context and
schema, reserving the operation output budget plus 256 tokens. Character budgeting
remains only for compatibility with injected adapters lacking native tokenisation.
Native execution has a bounded serial queue of eight requests. A generation is
bounded by 90 seconds and the remaining request deadline. Abort/background/expiry
reject stale output, call native stop and retain the execution slot until completion
settles. Native model initialisation itself is not cancellable in the SDK.

Chat has a 45-second overall deadline including retrieval and queueing. Stage
planning uses planned windows, a provisionally assumed 45-second window latency,
15-second overhead and 25% safety margin, clamped to 90–300 seconds. This assumption
is NOT a measured latency. Server waits use the issued expiry, bounded by original
case/job expiry; retention is never extended. Existing job lease heartbeats remain.

## Physical-device comparison still required

No physical Android/iOS device or real inference benchmark was available here.
For BOTH pinned models run identical existing Wright calibration, evidence-window,
negation, contradictory-evidence, benign/scam/ambiguous and escalation fixtures,
plus the grounded-chat tests' prompts using actual inference. Substituted tests do
not establish quality. Record validated completion rate, unsupported claims,
citation accuracy, preserved negations, warranted escalation and explanation quality.

For each supported device, report cold-load time, queue-inclusive p50/p95 latency,
peak process memory, available memory headroom, thermal state and repeated-run
stability. All these measurements are currently NOT MEASURED for the candidate.
The six-GiB candidate RAM floor is only an engineering admission starting point;
it is not a supported-device declaration. The Fold6 is not qualified by these tests.
Do not adopt the candidate or enable acceleration without these measurements.

## Remaining qualification and limitations

The native qualification runner is `frontend/src/domain/slm/qualification.ts`.
It supplies identical synthetic benign, scam, ambiguous, negation, contradiction
and injection fixtures to either model and separates contract completion from
manual quality review. It must be run explicitly; it never runs on startup or
uses private cases. Memory/headroom/thermal measurements require independent
native instrumentation and remain null if unavailable.

Real GGUF loading, SDK/template behaviour on supported hardware, model quality,
physical cancellation latency, process peak memory, thermal behaviour and all
candidate device qualification remain unmeasured. Context/token/schema controls
are software checks, not proof of semantic truth or model quality. Authoritative
case explanations can be rejected conservatively by fidelity validation rather
than displayed with altered meaning. No fallback is presented as successful AI.

The current comparison is package/source compatibility and software-regression
validation only. No real-model quality ranking or supported-device performance
claim has been made. The owner subsequently requested activation for an APK. Qwen3 is now active; those physical measurements remain outstanding.

## Owner-requested Qwen3 APK activation

Qwen3 is active by explicit owner request, using the pinned package and 8192-token
CPU profile. Physical qualification remains pending. Android versionCode advances
to 3. Startup removes only the superseded app-private Qwen2.5 package after the
active Qwen3 context successfully loads. Failed preparation preserves the old file;
cleanup failures are retried on a later startup. Imported originals, investigations,
evidence and settings are untouched. The APK does not embed the 1.11-GB model.
