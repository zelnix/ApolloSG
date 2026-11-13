# ApolloSG SLM — core native runtime integration

Updated 13 November 2026. SLM is a required application capability. Historical
opt-in build and handoff selectors have been removed; no environment value can
disable the required native stages.

## Native implementation

- `llama.rn@0.12.9` remains pinned in `package.json` and the Yarn lockfile.
- The existing Expo configuration always includes its native plugin, with
  `forceCxx20: true`, `enableEntitlements: false` and `enableOpenCL: false`.
- Android release packaging targets ARM64 only, as defined by
  `frontend/config/android-abis.json`; other processor targets are rejected by
  native-artifact admission.
- The native bootstrap admits the configured device-local model before
  registering the one shared runtime. Model installation uses the existing
  pinned-source download/admission mechanism. Model weights are not in the APK.
- Model file, memory and actual runtime/output checks remain mandatory. The
  existing lightweight admission policy is not a full-file checksum guarantee.
- Web and Expo Go do not supply this native capability. They cannot complete
  the required native investigation stages or substitute another investigator.

## Investigation and evidence boundaries

Wright semantic triage, Higgins escalation assessment and Finding/presentation
use the shared native runtime through the authenticated case request/result
contracts. TC Hawkeye retains deterministic evidence classification and numeric
rating reconciliation. Magnum DI remains warranted independent investigation,
not an unavailable-SLM fallback.

Source facts, derived content, external observations and model interpretation
retain their provenance. Results are device/case/job/revision/epoch bound, and
accepted outputs must satisfy the existing evidence, coverage and verdict-floor
checks. A model cannot invent verification or change protection/enforcement
state through its explanation.

Missing, invalid or unavailable native output produces an explicit inability to
complete the investigation. There is no optional deterministic-only, simulated
or external-model continuation for a required native stage.

## Verification and qualification

The regression gate covers wire correlation, owner isolation, stale/cancelled
requests, evidence coverage, native failures and established-result authority.
Build checks inspect compiled native architectures and required SLM libraries.
See `APOLLO_REVIEW_REPAIRS.md` and `.github/workflows/ci.yml` for current results.

These checks do not establish physical-device inference quality, cold-load
latency, lifecycle recovery, memory/thermal behavior or durable-storage
acceptance. Those remain supported-device qualification work; removing an
on/off switch does not turn an unsupported preview into a native device.
