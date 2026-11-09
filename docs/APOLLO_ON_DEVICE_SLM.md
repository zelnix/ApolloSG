# On-device small language model (SLM)

**Status:** source added on branch `slm-claude`. Not yet built or run on a device.

## What it is

ApolloSG can now use the small language model that is built into the phone:

| Platform | Model | Runtime | Requirement |
|---|---|---|---|
| Android | Gemini Nano | ML Kit GenAI Prompt API (AICore) | An AICore-supported device (e.g. recent Pixel / Galaxy). The OS downloads the model. |
| iOS | Apple on-device foundation model | `FoundationModels` framework | iOS 26+, Apple Intelligence on, eligible iPhone. |

Most phones have neither, so ApolloSG also offers a **downloadable fallback model** (below). The app itself bundles no
model weights. Nothing the model reads or writes leaves the phone. It is **off by default**. The person turns it on
in **Settings → App → On-device AI**, and that row shows which model is ready.

Order: the phone's built-in model if it's ready → the fallback model if one was downloaded → none (nothing extra shown).

## Fallback model for phones without a built-in one

Runtime: llama.cpp through `llama.rn` 0.12.9 (latest stable; 0.13 is still release candidates), CPU only,
2,048-token context, released after 60 s idle. Settings → App → **On-device AI models** lists:

| Model | Approx. download | Offered when total memory ≥ | Licence | Upstream file to host |
|---|---|---|---|---|
| Qwen 2.5 0.5B Instruct, Q4_K_M | ~491 MB | 3 GB | Apache-2.0 | `Qwen/Qwen2.5-0.5B-Instruct-GGUF` / `qwen2.5-0.5b-instruct-q4_k_m.gguf` |
| Llama 3.2 1B Instruct, Q4_K_M | ~810 MB | 4 GB | Llama 3.2 Community License ("Built with Llama") | `bartowski/Llama-3.2-1B-Instruct-GGUF` / `Llama-3.2-1B-Instruct-Q4_K_M.gguf` |
| Qwen 2.5 1.5B Instruct, Q4_K_M | ~1.1 GB | 6 GB | Apache-2.0 | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` / `qwen2.5-1.5b-instruct-q4_k_m.gguf` |

Sizes are approximate. Qwen 0.5B's size and publisher SHA-256 (`74a4da8c…7a9db`) come from the `slm` branch's
`docs/SLM_MODEL_BENCHMARK.md`; the app refuses a hosted Qwen 0.5B file whose hash isn't the publisher's, and the manifest
script refuses to print an entry for one. The other two have no publisher hash recorded yet.

- Downloaded only when the person taps it, only on Wi-Fi, only with enough memory and storage (500 MB left free).
- Files come from **ApolloSG's own storage**, not Hugging Face links, so they can't change underneath the app.
- The file's SHA-256 (streamed natively) must match the pinned value before it is ever loaded; a mismatch deletes it.
- One model is kept at a time; it can be deleted from the same screen.
- **Compare models** runs fixed, made-up test messages through the model in use and keeps each model's score on the
  phone: how many real requests it finds, how many of its finds are right, how many explanations pass the checks,
  and the median time per call.

### Licences

- **Llama 3.2** (§1.b of its licence): anyone distributing the model must provide a copy of the agreement, prominently
  display "Built with Llama", and keep the attribution notice. ApolloSG distributes it when a phone downloads it, so the
  app shows "Built with Llama" on the Llama card and in About, and the licence and notice under "Read the licence".
- **Qwen 2.5 0.5B / 1.5B**: Apache License 2.0, shown under "Read the licence".
- Texts: `frontend/src/slm/licences.ts` (generated from Meta's GitHub and apache.org on 2026-11-08), and
  `docs/slm-model-files/` for hosting beside the model files.

### To make the models downloadable

1. Download each GGUF named above, upload it to ApolloSG's storage (HTTPS), with the matching files from
   `docs/slm-model-files/` beside it (Llama: licence and notice; Qwen: Apache 2.0).
2. Run `node frontend/scripts/slm-model-manifest.mjs <model-id> <file.gguf> <https URL>` on the exact uploaded file.
3. Paste the printed line into `MODEL_SOURCES` in `frontend/src/slm/models.ts`. Until then each model shows
   "Not available to download yet".

## Relationship to the `slm` branch

The owner's `slm` branch is a separate SLM effort (developer-only llama.rn runtime, Ask Higgins re-wording, and
advisory hand-off to the server investigation). The owner decided on 2026-11-09 to keep the two **separate**:
`slm-claude` is not merged into `slm` or the reverse. Owner decisions recorded the same day:

1. Downloading a model when the person taps Download is allowed.
2. Sending model output to the server is acceptable (this applies to `slm`'s hand-off; `slm-claude` sends nothing,
   and its privacy text says so — if the two are ever combined, that text must change first).

If both ever reach `main`: they each add their own llama.rn runtime and both edit `app.config.js`, `package.json`,
`yarn.lock` and `privacy.ts`, so only one runtime can stay and those files will conflict.

## Which model version

ApolloSG doesn't pin a model version: the OS chooses and updates it, so it is recorded instead.

- **Android:** the Gemini Nano version AICore reports (`GenerativeModel.getBaseModelName()`), plus the Android
  version. Library: `com.google.mlkit:genai-prompt:1.0.0-beta4`.
- **iOS:** Apple publishes no version for its on-device model. It ships with the OS, so the iOS version identifies it.

It is shown in Settings → App → On-device AI ("Ready — Gemini Nano (…) · Android …") and in the card's footnote.
Each call is also kept in a local record on the phone (last 50: time, purpose, model, OS version, duration,
outcome such as `ok` or `rejected_reassurance`). The record never holds message text, prompts or answers, and is
not sent anywhere. Settings shows a one-line summary of it.

## What it does (advisory only)

1. **Plain-language explanation** of a result that Apollo has already settled (Message check result, under
   "On this phone"). The re-wording is checked before it is shown. It is rejected if it reassures ("safe",
   "genuine"…) without a negation, adds a link or a number that isn't in the result, or dismisses the advice. When
   it is rejected, nothing extra is shown: Apollo's fixed wording is already complete. Last, it must pass the app's own
   Luddish fidelity check (`domain/luddish/fidelity.ts differences()`) against Apollo's verdict and advice: same point,
   every negation, number and quote kept, no added reassurance or alarm.
2. **Pre-screen pointers**: requests to act (send money, share a code or details, install something, remote access,
   call or reply), a claimed organisation, and urgency. Each pointer must quote the message word for word. A quote
   that isn't in the text, or that a negation governs ("we will never ask you to…"), is dropped. Only pointers the
   fixed rules didn't already name are shown. When one of them is a request to act, the note offers to hand the
   message to Higgins.

## What it never does

- It never sets or changes a state, verdict, Gate result or Higgins action. `advisoryFor()` takes no state and
  returns none (`changedResult: false`). Gate checks stay fixed catalogue rules (OPERATING_RULES, Gate checks 4),
  Higgins Triage stays no-network/no-AI, and Biting still needs a verified packet.
- It is not an investigation model. Magnum DI and TC Hawkeye run on the server through the single AI gateway
  (`backend/services/higgins/provider.py`) and need JSON, vision and web search. A phone model can't be called from
  there, so it is not listed in ApolloSG Settings → AI Provider & Model.
- No retry and no other model. A failure, timeout (12 s) or unavailable model shows nothing extra.

## Where the code is

- `frontend/modules/apollo-slm/`: Expo module. `android/…/ApolloSlmModule.kt` (ML Kit GenAI) and
  `ios/ApolloSlmModule.swift` (FoundationModels, weak-linked, `#available(iOS 26)`). `index.ts` returns
  "unavailable" when the module isn't in the build (web, Expo Go).
- `frontend/src/slm/core.ts`: the rules (input redaction, prompts, verbatim-quote and negation checks, explanation
  checks). Pure; tested by `yarn test:slm` (`tests/onDeviceSlm.test.ts`).
- `frontend/src/slm/onDeviceSlm.ts`: the setting, status, one call with a timeout.
- `frontend/src/slm/models.ts`, `fallbackModel.ts`: the fallback catalogue, fit rules, download/verify/run.
- `frontend/src/slm/benchmark.ts`, `benchmarkRunner.ts`, `frontend/app/settings/on-device-ai.tsx`: model comparison
  and the models screen. Tested by `tests/slmModels.test.ts`.
- `frontend/src/components/OnDeviceAiNote.tsx`: the "On this phone" card. It renders through the new `footer` slot
  of `CheckResultScreen` / `InvestigationCheckScreen`, below the result.

## Before release

- **Android test build (CI):** `.github/workflows/slm-claude-android.yml` runs on pushes to `slm-claude` that touch
  this work, and on demand. It prebuilds, checks `apollo-slm` and `llama.rn` are linked, compiles debug and standalone
  APKs, checks the llama.cpp native library is packaged, and keeps both APKs for 7 days (Actions → the run →
  Artifacts). The standalone APK runs without Metro and is debug-signed, for test phones only. A green build proves
  the native code compiles, not that a model runs.

- Run an EAS Android build. `1.0.0-beta4` comes from Google's Prompt API guide; Google Maven itself couldn't be
  reached from the authoring environment, so the build is the first real check.
- Build on iOS with an Xcode version whose SDK includes FoundationModels (iOS 26 SDK).
- Host the three fallback files and fill `MODEL_SOURCES` (see above).
- iOS memory entitlements are off (`llama.rn` plugin `enableEntitlements: false`). Turn them on only after adding the
  increased-memory capability to the App ID; the fallback models are sized to run without it.
- Check the web build still bundles (`llama.rn` is loaded lazily, only when a downloaded model runs).
- Confirm the owner's earlier "Gemini only" instruction (`docs/GEMINI_ONLY_MIGRATION_STATUS.md`) no longer applies to
  on-device models. The owner approved non-Google on-device models on 2026-11-08.
- On-device acceptance: one AICore phone, one non-AICore phone, one Apple Intelligence iPhone, one older iPhone,
  and two or three mid-range Android phones (3–6 GB memory) for the fallback models: run Compare models on each.
  Check the Settings status line, the note's appearance, and that the result above it is identical with the
  setting on and off.
- Privacy disclosure: done (privacy inventory, AI disclosure, processing flows, onboarding summary). Have it
  reviewed with the rest of the privacy policy.
