# Android CNG APK build-input investigation — 2026-09-24 (updated 2026-10-04)

- Reported log fragment: `Step #5 - 'eas-apk-build': script: line 199: expo: command not found`. Without the complete fatal worker log or build ID, this is not enough to establish that Expo command lookup is the fatal step: a previous build logged the identical preparer message and submitted normally (see the production app-bundle pre-install record below).
- No project-owned EAS/pre-install script invokes the bare Expo CLI. The regular `start`, `android`, `ios`, `web` and `lint` npm scripts previously used `expo` under the package manager's `node_modules/.bin` PATH.
- **Fix applied (2026-10-04):** Added `eas-build-post-install` lifecycle hook (`scripts/eas-post-install.mjs`) that symlinks `node_modules/.bin/expo` to `/usr/local/bin/expo` after dependency installation, before the EAS worker resolves config or runs prebuild. Also modernised local scripts (`start`, `android`, `ios`, `web`, `lint`) from bare `expo` to `npx expo`. Together these ensure the `expo` command is globally reachable when the platform-owned build script invokes it at line 199.
- **EAS_NO_VCS=1 fix (2026-10-04):** The ZIP-extracted build environment has no `.git` directory. EAS CLI defaults to GitClient, emits `Failed to get Git root path with 'git rev-parse --show-toplevel'`, and falls back to cwd. Expo documents `EAS_NO_VCS=1` to disable VCS entirely (uses NoVCSClient). Fix: the `postinstall` hook now creates a wrapper at `/usr/local/bin/eas` that exports `EAS_NO_VCS=1` and `EAS_PROJECT_ROOT` before delegating to the real binary. Additionally `EAS_NO_VCS=1` is set in the frontend `.env` file.
- **Build 90cec339 (app-bundle) — SUBMITTED, exit 0:** Previous `expo: command not found` was non-fatal; EAS CLI uploaded 8.8 MB, computed fingerprint, incremented versionCode 123→124. Build ID: `90cec339-f56a-4d12-97cd-dec74400a6fa`.
- **Subsequent retry — FAILED, exit 1:** `Network error: Service Unavailable` during EAS build request. This is a transient EAS infrastructure error (HTTP 503), not a code or configuration issue. The `git rev-parse` warnings are expected and non-fatal.
- CLI versions at time of investigation: Expo CLI 57.0.21, Node v24.19.0, Yarn 1.22.22. EAS CLI version is installed globally by the Emergent pipeline (not a project dependency).
- Source input corrected (earlier): keep the existing Yarn lockfile (including the `react-native-webrtc` and exact `expo-notifications` entries), remove the untracked npm `package-lock.json`, exclude future npm locks from EAS/Git input, and check CNG and lockfile invariants in CI. `android/` and `ios/` remain excluded from EAS input; the final tracked Gradle JAR is deleted locally and awaits the saved source commit. Existing ignored local `ios/` output is untouched.
- Verification: `yarn install --frozen-lockfile`, `device-test` EAS pre-install security preflight, post-install symlink (`expo` resolves globally after hook), eas wrapper (EAS_NO_VCS=1 injected), `expo config` (SDK 57, package `app.apollo.hwg`), TypeScript and security tests pass. A fresh EAS build is required to confirm the line-199 warning and git warnings are eliminated.

# Package 6 native source delivery — 2026-09-22

- iOS source resolves four app extensions under `app.apollo.hwg`: Content Blocker, Call Directory, Message Filter and Share Extension.
- Windows source includes an Apollo WFP ALE service, actual drop-event app/process attribution, bounded evidence, NSIS service hooks and Tauri bridge. MinGW x64 compile/link passed; temporary PE output was deleted.
- macOS source includes an `NEFilterDataProvider` system extension, source-app attribution/evidence, activation helper, entitlements, XcodeGen manifest and unsigned embedding recipe.
- Bounded validation: TypeScript, ESLint, Python lint, 379 Node tests, 61 provider-disabled pytest tests, Cargo check, 5 Rust tests, Package 6 preflight and staging/production preflights pass.
- Frozen GuardDog package roots remain unchanged. No signed build, installer, notarisation, deployment or physical-device acceptance was performed.
- Source manifest: 625 files, SHA-256 `facb85bf40e186fcb6bc61ef668a2b81b72e9250d21962914c38b66a25bff6f6`.
- Detailed record: `APOLLO_PACKAGE6_SOURCE_DELIVERY_RECORD.md`.

# Phase 2 source remediation — 2026-09-22

- Reviewed/starting SHA: `6fbd5b3bd5711a2ef0530da7c24a162ca2b57e79`.
- Production and app-bundle source now default to fail-closed `guarddog_production`; signed authority remains mandatory.
- Android package remains `app.apollo.hwg`; no frozen GuardDog package file changed.
- Bounded checks: TypeScript, ESLint, Python lint, 373 Node tests, 61 provider-disabled pytest tests, staging/production preflight and Cargo all pass.
- Backend health is 200 and the learning catalogue initialises exactly 35 published articles.
- No build, signing, deployment, scenario, Playwright, testing-agent or live-Gemini run was performed.
- Final source manifest SHA-256: `ed31a214ebccdaf80a9fae4e5dd4b9700e50d5ef58d8fc6f23eedd98a9749e67` across 606 source files.
- Final GitHub SHA remains pending Save to GitHub; this is a source-handoff requirement, not a source-test failure.
- Detailed closure: `APOLLO_PHASE2_SOURCE_REMEDIATION_RECORD.md`.

# Phase 2 baseline record — 2026-09-22

- Controlling Phase 2 source baseline was recorded before source edits as `d1ab4ff22f7476fefd3999e6c292c3ac92f2e30b` on local `main`.
- No Git remote/upstream is configured in this workspace; the exact current saved repository HEAD above is the available GitHub-derived baseline and is not reset to the older review anchor.
- M1–M4 remain accepted and closed. Phase 2 executes only P2.1–P2.6 and C19–C25/V27–V36.
- Full execution ledger: `docs/APOLLO_PHASE2_EXECUTION_RECORD.md`.

## Phase 2 RC1 source record — 2026-09-22

- Release identity: Apollo `1.1.0`; Android `versionCode 2`; iOS `buildNumber 2`; desktop `1.1.0`.
- Android package/application ID remains `app.apollo.hwg`.
- Bounded verification passed: TypeScript, ESLint, Python lint, 53 provider-disabled pytest checks, device-test security preflight, Cargo and all three Apollo-owned Android release Kotlin modules.
- The native compile closed missing `kotlinx-serialization-json` visibility in `apollo-security` and removed a stale `ApolloVpnGuardReceiver` reference after its work had already been replaced by the durable WorkManager schedule.
- No signed Android artifact is recorded: the build host is Linux ARM64 and React Native's bundled Hermes compiler has no matching host binary. A fake compiler and misleading installable artifact were explicitly rejected.
- GuardDog production-default cutover remains inactive and separate.
- Runtime closure: MongoDB/backend/Expo are RUNNING, backend health is 200 and the protected preview proxy is HTTP 200. The deployment scanner's sole remaining complaint is a missing `--tunnel` flag in an explicitly read-only Supervisor file that already supplies the protected proxy URL; source/env/security checks otherwise pass.

# GuardDog production-default authority track — source record (updated 2026-09-23)

- Production, app-bundle and guarddog-production now select only `guarddog_production`; staging acceptance remains isolated and production legacy activation is rejected natively.
- Apollo owns one native process runtime; the frozen Expo bridge remains excluded. Trust-generation transitions stop/recover/drain/clear/rebuild before resuming.
- Added pinned independent primary/recovery public-root configuration, strict signed trust manifests, ordinary-key validity/revocation, HMAC-bound rollback state, generation-scoped bundle stores, routine signed refresh and expiry stop work.
- Production now wires the accepted engine into the frozen Website Gate DNS gateway, sinkhole routes, physical-network IPv4 DNS forwarder, allow-only override store and genuine packet-drop reporter; boot/unlock/package-update/network-change reconciliation is source-wired.
- Acceptance test IDs/keys are rejected by production plugin, runtime and preflight.
- Added offline-only manifest/rule signing tools that refuse private key files inside the application repository.
- **External inputs still required for runtime activation:** owner public roots, signed trust/rule artifacts and HTTPS update URLs. Private keys remain offline and are never requested by the app/build/CI.
- **Source selection state:** production-default and fail-closed to GuardDog. Android package remains `app.apollo.hwg`. No signed artifact or physical-device cutover evidence is claimed.
- Verification remains bounded to source/static/compiler checks. A successful Android Kotlin compile is not a signed candidate and does not replace live-device authority, traffic, expiry, recovery or rollback evidence.

## Production app-bundle pre-install failure — fixed in source

- Failed EAS build: `4dee4d9b-99ba-48db-825d-1f63c22414db` (Android app bundle, versionCode 110).
- Fatal phase: `PRE_INSTALL_HOOK`, before native compilation. The deployment-created `app-bundle` profile inherited development-web values from `.env`: `EXPO_PUBLIC_APP_ENV=development` and `EXPO_PUBLIC_DEVICE_PREVIEW_HARNESS=enabled`. Apollo's security preflight correctly rejected shipping simulated preview-device input in a native build.
- Fix: `eas.json` now defines an explicit production-safe `app-bundle` profile; `.env.production` explicitly selects production/legacy/harness-off; `security-preflight.mjs` prevents every EAS native profile from inheriting base development-web defaults while preserving the fail-closed rejection of an explicitly unsafe profile.
- Source hygiene: `.easignore` excludes generated native/build caches. Local ignored Rust, Metro, desktop-dist and Ruff artifacts (about 3.6 GB) were removed before the next deployment archive.
- Verification: app-bundle, production, device-test and GuardDog acceptance pre-install matrices pass with their intended values; an explicit app-bundle + enabled preview harness still fails; security configuration tests 6/6; TypeScript and script lint clean; production Expo config resolves the expected native package and EAS project.
- The preparer log `expo: command not found` was non-fatal in this run: project linking and EAS submission continued successfully. The EAS worker's only fatal error was the intentional security-preflight rejection above.
- **Artifact status:** build `4dee4d9b-99ba-48db-825d-1f63c22414db` remains failed and contains no artifact. A new app-bundle build is required to validate the corrected source; no successful replacement build is claimed here.

# Apollo build record

## Android — 2026-09-22 seven-defect correction candidate

| Field | Value |
|---|---|
| Build id | `047bc183-37e9-447b-b0f8-48012f591550` |
| Result | **FINISHED** at `2026-09-22T03:08:19.721Z` |
| Build page | https://expo.dev/accounts/emergent-em-user-fb71a8d3-adc2-4275-b1ec-2692228557b8/projects/threat-patrol-1/builds/047bc183-37e9-447b-b0f8-48012f591550 |
| **APK download** | https://expo.dev/artifacts/eas/HNq2PiQUZ46vTsP-q2f8OTQ4O0CU4L_uNJY2RyCTRB8.apk |
| Exact saved Git source | `7fd6f9a61d292bdab17700152f7e47e457afc411` |
| Correction implementation commit | `4bb068292ad92118969dcc7802c2fb529502847f` |
| EAS fingerprint | `565f42d9b04dd39c836360eeccd12c4e442b800f` (`01a0c708-0e1b-7824-8b82-319c7b2396c8`) |
| App | `Apollo` 1.0.0 (versionCode 1), package `app.apollo.hwg`, Expo SDK 57 |
| Profile | `device-test`: internal APK, staging backend, legacy enforcement, preview harness explicitly `off` |
| Compatible backend | `https://case-source-preview--3ijise2t.preview.emergentagent.com` |
| Size | 147,567,093 bytes |
| SHA-256 | `c15804e04597e09628575cc58734bd97fc10c2cbe1f89dd4c1ddae239e102e97` |
| Local verification copy | `/app/Apollo-Android-047bc183.apk` |

Build `c46c1d78-d662-4cd6-a45d-292ffe175247` is **not a candidate**: it failed in EAS Pre-install because
the uploaded development `.env` enabled the browser preview harness. Commit `7fd6f9a...` explicitly sets
`EXPO_PUBLIC_DEVICE_PREVIEW_HARNESS=off` in all native EAS profiles; all three local profile preflights passed and
Deployment Agent returned PASS before the successful retry.

## Android — 2026-09-21 Package 1/2 closure candidate

| Field | Value |
|---|---|
| Build id | `18706c6e-cf91-418e-9536-94b1cf592f93` |
| Result | **FINISHED** at `2026-09-21T18:52:03.479Z` |
| Build page | https://expo.dev/accounts/emergent-em-user-fb71a8d3-adc2-4275-b1ec-2692228557b8/projects/threat-patrol-1/builds/18706c6e-cf91-418e-9536-94b1cf592f93 |
| **APK download** | https://expo.dev/artifacts/eas/e6U7nUAuNc-tULLCTfLftpltfy7wll9oithASkmvk7U.apk |
| EAS source fingerprint | `31a0394db69ca674b79ef91a3d0cf3c2b0e2e083` (`01a0c541-21a7-7d83-a8b9-5e0d153493a3`) |
| EAS informational git field | `58fb1a066eaabe06a96c143da8d4ce171e254d6c`; working-source identity is the EAS fingerprint above |
| App | `Apollo` 1.0.0 (versionCode 1), package `app.apollo.hwg`, Expo SDK 57 |
| Profile | `device-test`: internal APK, staging backend, legacy enforcement selection; GuardDog/Apollo native modules still compiled successfully |
| Compatible backend | `https://case-source-preview--3ijise2t.preview.emergentagent.com` (`/api/health` HTTP 200) |
| Size | 147,531,093 bytes |
| SHA-256 | `50e51aff03ee69ed859386b734365a205fe9040fc240c5af896e7a3342503e91` |
| Local verification copy | `/app/Apollo-Android-18706c6e.apk` |

Native build log reached and completed release Kotlin/CMake/Gradle tasks for Apollo Security, GuardDog dependencies,
`expo-share-intent` multi-item support and the application. This is compilation proof, not physical-device behavior proof.

> Saved-source mapping note (2026-09-22): human review was against commit
> `4c03315e5a4706812e67c4ed122822748993211a`. The subsequent Package 1/2 correction tree has source digest
> `01e4723d48cd34c3129701adebd2947249cb174f94d2ae21a699d30567ea0110` and is **not** part of build
> `18706c6e-cf91-418e-9536-94b1cf592f93`. The next build must record its newly saved Git SHA, EAS fingerprint and APK
> hash; do not substitute the older informational Git SHA or this working-tree digest for one another.

## Android — `device-test` profile (installable candidate)

| Field | Value |
|---|---|
| Build id | `e32f6068-b349-4de8-ab5d-8c950a6596bf` |
| Build page | https://expo.dev/accounts/emergent-em-user-fb71a8d3-adc2-4275-b1ec-2692228557b8/projects/threat-patrol-1/builds/e32f6068-b349-4de8-ab5d-8c950a6596bf |
| **APK download** | https://expo.dev/artifacts/eas/-R5J9ohNQ6k-MxXloAh_NuawortWikr6zDUyXPbaRlE.apk |
| Source commit | `fa9bf2f6955eee34e15f10c46d88448069be200d` (branch main; later commits are backend/desktop/docs and do not change the APK) |
| Profile | `device-test`: internal distribution, APK, `EXPO_PUBLIC_APP_ENV=staging`, `EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE=legacy` (GuardDog acceptance engine not selected) |
| App | `Apollo` 1.0.0 (versionCode 1), package `app.apollo.hwg`, Expo SDK 57 |
| Size / ABIs | 147,519,401 bytes; arm64-v8a, armeabi-v7a, x86, x86_64 |
| SHA-256 | `0755c7f37b19623f76d6dda23c2a8c11d0feec31449496631f49ca3291489103` |
| Signing | EAS cloud-generated keystore for project `47cd97c4-e5a6-41fa-9fde-257a5de031af` (internal testing; not a store key) |
| Backend | `EXPO_PUBLIC_BACKEND_URL` from `frontend/.env.production` (the stable reachable backend) |

### Artifact inspection (performed on the downloaded APK)
- JS bundle (`assets/index.android.bundle`, 5.10 MB): `PreviewDeviceAdapter`, `MOCKED DEVICE INPUT`, `MockSecurityAdapter`, `MockSecureCore`, `WebSecurityAdapter`, `EXPO_PUBLIC_SECURITY_MODE` — **all absent**; `getDeviceProfileFacts`, `open_settings.vpn`, fail-closed message — present.
- DEX: `ApolloSecurityModule`, `ApolloSmsListenerService`, `GuardDogVpnService` present. Manifest declares `POST_NOTIFICATIONS`.

### Install (Pixel 10)
Open the APK link on the phone (or `adb install apollo-device-test.apk`), allow "install unknown apps" for the browser once, install, open Apollo. First run shows onboarding; the Settings tab shows the real adapter label (`Android — Apollo DNS filter`) and no preview banner.

### Build history
| Build | Result | Cause / fix |
|---|---|---|
| `d54b2c70-6a1d-4f17-8255-f9cce2ed2b7f` | errored (Gradle, 9m38s) | `:apollo-security:compileReleaseKotlin` — `Unresolved reference 'activeSessionId'` ×3 in `ApolloGuardDogCandidateRuntime.kt` (frozen SDK e5d11be has no such field). Fixed in `fa9bf2f` by deriving the live TUN-session identity from `GuardDogVpnRuntime.activeSession`. Pre-existing packaging fixes in the same run: `app.json` slug → `threat-patrol-1` (EAS project mismatch), `gradle-wrapper.jar` tracked. |
| `e32f6068-b349-4de8-ab5d-8c950a6596bf` | **finished** (25m) | — |

Known build warnings (non-blocking): `expo-updates` not installed although the profile declares a channel (channels unused); `expo-doctor` warns about the tracked `android/` directory (bare workflow is intentional for the GuardDog modules).

## iOS / iPadOS — `device-test` profile
Attempted (`eas build --platform ios --profile device-test --non-interactive`): stops at **credential setup** — `EAS CLI couldn't find any credentials suitable for internal distribution`. Targets recognised: `app.apollo.hwg`, `app.apollo.hwg.contentblocker`, `app.apollo.hwg.share-extension`.
Genuinely missing owner inputs: Apple Developer team credentials (App Store Connect API key `.p8` + key id + issuer id, or an interactive Apple ID login) and the test devices' UDIDs (`eas device:create`) for ad-hoc internal distribution — or TestFlight instead. Nothing else blocks the iOS build.

## Windows / macOS
Tauri host in `/desktop`; no Windows/macOS runner in this workspace, so no installer produced yet (see `APOLLO_PLATFORM_DELIVERY_MATRIX.md`).
