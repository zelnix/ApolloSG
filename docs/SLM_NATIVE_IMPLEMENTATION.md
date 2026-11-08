# ApolloSG SLM branch — native runtime integration (work in progress)

## Scope and current status

Branch: `slm`. The shared interface lives in `frontend/src/domain/slm/index.ts`;
`llamaRnRuntime.ts` implements the execution boundary against the documented
`llama.rn` native `initLlama()` / `completion()` / `release()` API.

**Not enabled in the application. No physical-device tests have been run.**
`llama.rn@0.12.9` is pinned with a Yarn-generated lockfile on `slm`.
No model weights, model downloader or native device builds have been added.
The native plugin is staged behind the non-production `APOLLO_SLM_NATIVE=on`
build-time switch, and remains off pending native device acceptance.
The native binding admission gate is in `frontend/src/domain/slm/nativeBridge.ts`.
The real SDK adapter is `frontend/src/domain/slm/llamaRnBinding.native.ts`.
Neither is yet wired into production case processing.

## Native integration gate

1. **Completed:** Pinned stable `llama.rn@0.12.9` with repository Yarn v1.
   `frontend/package.json` and `frontend/yarn.lock` were generated together
   and committed to the `slm` branch by the branch-only lock workflow.
   Native binaries have not yet been built or tested.
2. The `llama.rn` Expo config plugin has been staged in the existing authoritative
   `frontend/app.config.js`, disabled unless `APOLLO_SLM_NATIVE=on` in a
   non-production build. Existing config plugins and device permissions are intact.
   CPU-only mode initially (no GPU/OpenCL permissions).
3. Build a generated **native development client** for Android and iOS.
   Expo Go and browser builds cannot verify this native runtime.
4. Obtain a licensed, vetted quantised **text-only** GGUF model. Verify
   provenance, exact SHA-256, commercial-use licence, memory footprint,
   supported languages, and whether its chat template works with llama.rn.
   Make the model available as an explicitly selected, device-local
   `file://...`. Do not download arbitrary user-supplied remote models.
5. Wire the native binding explicitly from a native-only mobile entry point:
   `createLuddishOnDevice({modelUri: localModelUri, modelId: verifiedModelId, deviceAdmitted: true})`;
   then `await runSLM(caseScopedRequest, runtime)`.
   Device admission checks must establish sufficient free disk, memory and
   actual model compatibility before loading. Release when unused.
6. Test supported Android/iOS physical devices: native linking, cold load,
   output quality, device-memory pressure, long inputs, background/foreground,
   cancellation and peak battery/thermal behaviour. If unavailable, retain
   the current deterministic investigation pipeline; never simulate an SLM.
7. Hook SLM advisory outputs into Higgins Triage, TC Hawkeye, Magnum DI and
   Luddish through the existing investigation contracts **only after**
   comparing accuracy and false positives against current baselines.
   Neither SLM nor Gemini may change Evidence Lock or final verdict scoring.

## Safety and isolation

- Input text is untrusted; prompts must not be treated as authority.
- The SLM is advisory: no generated score, verdict or unsupported citation.
- Evidence IDs in generated findings must be among the current request's
  explicitly supplied IDs; no cross-device case lookups, memory or cache.
- The model is on-device only and no fallback is configured in this adapter.
- On unavailable or invalid local inference, the existing deterministic
  pipeline continues with its honest limitations.
- Gemini remains a **warranted Magnum DI extension only**, not a fallback.
- Existing Luddish fidelity and Evidence Lock protections remain mandatory.
- Avoid logging prompts, model completions, case identifiers or private evidence.

## Verification

Run existing frontend tests alongside:

```sh
cd frontend
node --test tests/slm.test.ts tests/slmRuntime.test.ts tests/slmNativeBridge.test.ts
```

These tests mock the native binding and **do not constitute a native build or
physical-device proof**. Validate in the repository's configured Node version.

## Outstanding work

Approved GGUF model; activate opt-in Expo plugin;
Android/iOS build and measurements; real app lifecycle wiring; stage-specific
integration; warranted Gemini extension; full regression/acceptance testing.

## Package compatibility check (2026-11-08)

Expo SDK 57 uses React Native 0.86.3 / New Architecture. `llama.rn`
provides an Expo config plugin, and its v0.13.0-rc.9 prerelease exists.
`llama.rn@0.12.9` is pinned in `frontend/package.json` and the generated
Yarn lockfile on `slm`. The branch-only GitHub Actions package-lock run
succeeded. Version 0.13.0 is still a prerelease. Actual native installation
and build compatibility remain **unproven**. Do not activate the build flag
until Android and iOS native acceptance has succeeded.
