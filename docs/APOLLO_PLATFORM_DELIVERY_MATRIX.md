# Apollo platform delivery matrix (spec §1A / §16) — updated 2026-09-22, Phase 2 RC1

Android CPU policy update, 13 November 2026: the required SLM supports only
`arm64-v8a` and `x86_64`. ARM32 and 32-bit x86 are excluded from current APK/AAB
builds. Public distribution targets Google Play; Expo APKs are internal tests.
See `frontend/config/android-abis.json` and `APOLLO_REVIEW_REPAIRS.md` for the
current build checks. Earlier artifact/build observations below are historical.

## Phase 2 RC1

| Target | Current evidence | External boundary |
|---|---|---|
| Android | 1.1.0 / versionCode 2; application ID `app.apollo.hwg`; native dependency preflight pass; `guarddog-core`, `guarddog-vpn`, `apollo-security` release Kotlin pass on SDK 36 | Signed APK/AAB not emitted because this build host is Linux ARM64 and has no compatible bundled Hermes compiler |
| iOS | Shared Expo/TypeScript 1.1.0 source and buildNumber 2 compile cleanly | Native Apple compilation remains outside this Linux host |
| Windows/macOS desktop | Tauri/Rust 1.1.0 `cargo check` pass | Platform installers are not emitted by this Linux ARM64 source-check environment |
| Backend | Python lint pass; 53 provider-disabled Phase 2/baseline regression checks pass | Live Gemini and scenario campaigns intentionally not run |

No platform result above is inferred from another platform, and no unavailable artifact is claimed.

## GuardDog Android production-default source status

- `production`, `app-bundle`, and the explicit `guarddog-production` profile select `guarddog_production` only; production does not fall back to legacy or acceptance.
- Primary/recovery signed trust, rollback state, ordinary-key revocation/expiry, update/expiry workers and one Apollo-owned bridge/runtime are source-wired.
- The production owner now configures the frozen M2 Website Gate DNS gateway, sinkhole pool, physical-network DNS forwarder, allow-only override store and packet-drop reporter before the VPN starts.
- No C15 native artifact was produced. Existing APKs remain historical legacy/acceptance evidence and cannot validate this source track.
- Runtime activation is blocked only on owner public roots, signed trust/rule artifacts, HTTPS update locations and the separately permitted native build/device authority/rollback observations.
- Coverage is truthful and bounded: plaintext IPv4 UDP/53 plus fixed sinkhole/controlled /32 routes. Private DNS, DoH, DoT, QUIC and IPv6 are not claimed.

## Current correction-candidate impact

- **Existing Android APK:** remains the last installable feedback artifact. It predates the current frontend/native corrections and must not be cited as evidence for strict operation ownership, report management or the AES-GCM protected Text notification inbox.
- **Next Android candidate:** required to deliver those frontend/native changes. It is intentionally consolidated for the next candidate rather than rebuilt during this repair pass.
- **Backend-only changes:** maintenance recovery, PDF continuation, mailbox Higgins coordination, saved-report deletion and lifecycle cleanup are server changes and do not require an APK rebuild.
- **Desktop:** generated Windows PowerShell now avoids the reserved `$host` variable; its Rust unit passed and the Tauri crate passed `cargo check`. No Windows/macOS installer was produced.
- **iOS:** implementation/configuration work remains unblocked; signed delivery is blocked only by the Apple team/device prerequisites already recorded below.

Status vocabulary: `implemented` (code present and wired), `partial` (some operations real, rest reported `not_implemented`),
`not_implemented` (open work, never relabelled "unsupported"), `os_restricted` (cited vendor constraint). Build status is the
actual artifact outcome, not a claim. Owner scenario acceptance is **deferred — owner evaluation** for every row.

## Hosts and packaging

| Target | Device classes | Min OS / CPU (from SDK/build config) | Host | Build profile / command | Artifact produced in this session | Exact remaining blocker |
|---|---|---|---|---|---|---|
| Android | phones, tablets (sw600dp reported as tablet) | Android 8.0+ (`minSdkVersion` 26); arm64-v8a, x86_64 (64-bit only) | Expo app + `modules/apollo-security` (Kotlin, GuardDog production Website Gate, notification listener, call screening) | `eas.json` → `production`/`app-bundle`/`guarddog-production`, all fail-closed to `guarddog_production` | No current signed production-default artifact is claimed; historical APKs predate this source | Owner supplies public roots/signed artifacts/HTTPS locations; build owner emits signed candidate; device owner records VPN consent, lifecycle, DNS/sinkhole drop, expiry/revocation/rollback and reboot/network-change outcomes. |
| iOS / iPadOS | iPhone, iPad (idiom-based form factor) | iOS 15.1+ (Expo SDK 57 default); arm64 | Expo app + Swift module (Safari content blocker, notifications, device facts) | `eas.json` → `device-test` (`ios.simulator=false`, internal distribution); `eas build --platform ios --profile device-test` | **Attempted** from this workspace: EAS stopped at credential setup (`EAS CLI couldn't find any credentials suitable for internal distribution`). Config is otherwise valid (targets `app.apollo.hwg`, `.contentblocker`, `.share-extension` recognised). | **Genuinely missing owner inputs (nothing else blocks it):** (1) Apple Developer Program team access — App Store Connect API key (`.p8`, key id, issuer id) or Apple ID login in an interactive `eas credentials`/`eas build` run; (2) UDIDs of the iPhone/iPad test devices for the ad-hoc internal-distribution profile (`eas device:create`), or choose TestFlight instead of ad-hoc; (3) provisioning profiles for all three targets are generated by EAS once (1)–(2) exist. Email/push credentials and desktop filtering are NOT prerequisites. |
| Windows | PCs, laptops, tablets, 2-in-1 | Windows 10 1809+ (WebView2); x64 source path | `desktop/` Tauri v2 shell + Rust typed commands + WFP ALE service | `cd desktop && yarn build:windows` (NSIS source path) | **Not produced here** — no Windows runner in sandbox | Run on Windows, sign the service/installer, then verify service lifecycle and real WFP flow drops on a physical host. |
| macOS | desktops, laptops | macOS 12+; arm64/x64 source path | Tauri shell + `NEFilterDataProvider` system extension + activation/configuration helper | `cd desktop && yarn build:macos` (unsigned `.app` source candidate) | **Not produced here** | Build on macOS with granted Network/System Extension entitlements; sign nested components and containing app, notarize, then verify approval/filter lifecycle on a physical Mac. |

## Ten Gates × platform (implementation status; scenario status = deferred — owner evaluation for all)

| Gate | Android | iOS/iPadOS | Windows (desktop host) | macOS (desktop host) | Notes / consent |
|---|---|---|---|---|---|
| Site | implemented (DNS VpnService filter; VPN consent) | implemented (Safari content blocker; Settings › Safari › Extensions) | implemented in source (WFP ALE service; administrator/service approval); runtime evidence awaits signed host build | implemented in source (`NEFilterDataProvider`; System Extension + filter approval); runtime evidence awaits signed host build | Desktop flow/authorization drops are surfaced as Barking, not packet-backed Biting; Biting remains restricted to correlated packet-drop evidence. |
| Link | implemented | implemented | implemented (shared case + server checks) | implemented | — |
| Text | implemented (opt-in notification-listener; screenshot original now carried onto the case) | implemented (paste/screenshot; no message access — `os_restricted`, Apple exposes none to apps) | implemented (paste/screenshot) | implemented | — |
| Call | implemented (CallScreeningService role) | partial (CallKit directory; no per-call callback — `os_restricted`) | user-submitted concern only; no telephony (`hardware_absent`) | same | Device without telephony still investigates a submitted call concern. |
| Network | implemented (transport/security/SSID with location consent) | partial (limited Wi‑Fi info — `os_restricted`) | partial (real interface/VPN enumeration; SSID/security `not_implemented`) | partial (same) | — |
| Account | implemented | implemented | implemented | implemented | Server-side research; no credentials collected. |
| Email | implemented (Gmail read-only OAuth) | implemented | implemented | implemented | — |
| File | implemented (picker/share intake, bounded inspection, secret preflight for images) | implemented | partial (open/drop via dialog plugin; share target `not_implemented`) | partial | Cloud origin never treated as proof of safety. |
| App | implemented (package-visibility limits; typed native observation now on the case) | partial (no app inventory — `os_restricted`) | `not_implemented` (installed-app inventory) | `not_implemented` | — |
| Device | implemented (real permission state + request history, manufacturer/model/OS, Settings intents, return recheck) | implemented (notification state, content-blocker state, app Settings + path, return recheck) | implemented host facts for OS/locale/manufacturer/model/chassis form factor plus fixed `ms-settings:` targets | implemented host facts for OS/locale/model/form factor plus fixed `x-apple.systempreferences:` targets | Settings plan → exact descriptor → return → fresh recheck implemented in `src/settings/*`; signed-host observation remains external acceptance. |

## Shared behaviour on every host
Gemini investigation (owner key, server-side), grounded research, case persistence/recovery, actionable guidance, speech playback and
honest capability reporting (`unavailableReason`) are shared. No host ships a runtime mock (see `APOLLO_RUNTIME_SIMULATION_AUDIT.md`).
