# P1 Android Website Protection Fix — Root Cause & Resolution

## Date: 2026-06-04

## Root Cause Analysis

### Two cascading failures prevented VPN establishment on physical Android devices:

#### Root Cause 1: `actualOperational()` required BOTH M1 AND M2 enforcement
**File:** `ApolloGuardDogProductionRuntime.kt` line 346 (original)
**Original:** `runtime.dropReporterAttached && GuardDogVpnRuntime.websiteGateActive`
**Problem:** When the BlockTest endpoint (`apolloverify.harmonywellnessgroup.com.au`) fails DNS on a physical carrier network, the VPN service correctly falls back to Website Gate-only mode (`establishWithoutBlockTest()`). This mode creates the M2 DNS/sinkhole pipeline but does NOT create an M1 `PacketDropReporter` (M1 is controlled-endpoint-specific). The `actualOperational()` check required both, so it always returned `false` in Website Gate-only mode. The `startLocked()` method waited 8 seconds, timed out, then **killed the working VPN service**.

#### Root Cause 2: `startLocked()` threw on BlockTest binding failure
**File:** `ApolloGuardDogProductionRuntime.kt` lines 299-303 (original)
**Original:** `is BindingResult.Mismatch -> error("DNS/IP binding mismatch")`
**Problem:** Before even starting the VPN service, the bridge's pre-check would throw if the BlockTest endpoint didn't resolve or returned a different IP. This prevented the VPN service from ever receiving ACTION_START, even though the service itself has a graceful fallback path.

### Why this only affects physical devices:
The BlockTest endpoint `apolloverify.harmonywellnessgroup.com.au` at `52.25.179.131` may fail DNS on real carrier networks due to DNS filtering, ISP interference, CDN changes, or network restrictions. In development/emulator environments with stable DNS, the endpoint resolves correctly.

## Changes Made

### File 1: `ApolloGuardDogProductionRuntime.kt`
1. **`actualOperational()`** — Changed from requiring BOTH `dropReporterAttached` AND `websiteGateActive` to requiring at least ONE (`dropReporterAttached` OR `websiteGateActive`). Both fields still report truthfully in status; only the operational derivation changed.
2. **`startLocked()` binding check** — Made non-fatal. On Mismatch/ResolutionFailed, logs a warning and continues (the VPN service handles the fallback). Previously threw and aborted the entire start.
3. **`statusLocked()` reason** — Updated degraded reason text to correctly identify when neither M1 nor M2 is active.

### File 2: `GuardDogExpoModule.kt`
4. **`startProtection()` bridge** — Same fix as production runtime: binding failure no longer throws ERR_DNS_BINDING. Logs warning and proceeds.

## What Was NOT Changed
- `GuardDogVpnService.kt` — No changes needed. Its `establishWithoutBlockTest()` fallback already worked correctly.
- `RecoveryStatus.recovered` — Still checks `!dropReporterAttached` for cleanup verification (different purpose than operational status).
- Raw status fields (`dropReporterAttached`, `dnsGatewayActive`) — Still truthfully reported in all status endpoints.
- VPN tunnel establishment, DNS filtering, evidence integrity — All preserved.

## Physical Device Acceptance Steps
1. Build a new Android APK (Publish → Generate Android Build)
2. Install on the physical device where the issue was observed
3. Open ApolloSG, navigate to the Website Protection toggle
4. Tap "Turn on website protection"
5. **Expected:** VPN establishes, Android shows VPN icon in status bar, protection status shows "Active"
6. **Verify Always-on:** In Android Settings → Network → VPN → ApolloSG, enable "Always-on VPN". Reboot device. After boot, VPN should auto-establish.
7. **Verify DNS filtering:** Navigate to a known blocked domain in a browser — it should be sinkholed.

## Limitation
This fix CANNOT be validated on Expo Go or web preview. A native Android build (APK/AAB) is REQUIRED.
