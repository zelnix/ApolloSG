package com.guarddog.expo

import android.app.Activity
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import com.guarddog.core.GuardDogSDKEngine
import com.guarddog.core.BlockAuthorization
import com.guarddog.core.clock.SystemClock
import com.guarddog.core.rules.AcceptedBundle
import com.guarddog.core.rules.BundleVersionStore
import com.guarddog.core.rules.InMemoryBundleVersionStore
import com.guarddog.core.rules.RuleBundleValidator
import com.guarddog.expo.dto.BridgeProtectionConfigRecord
import com.guarddog.expo.dto.BridgeWebsiteGateConfigRecord
import com.guarddog.expo.dto.BridgeWebsiteGateOverrideRecord
import com.guarddog.vpn.BindingResult
import com.guarddog.vpn.ControlledEndpointResolver
import com.guarddog.vpn.FreshConnectionProbe
import com.guarddog.vpn.GuardDogVpnRuntime
import com.guarddog.vpn.GuardDogVpnService
import com.guarddog.vpn.MutableWebsiteGateOverrideStore
import com.guarddog.vpn.RecoveryInspector
import com.guarddog.vpn.VpnLifecycleState
import com.guarddog.vpn.VpnStateRepository
import com.guarddog.vpn.WebsiteGateAddressing
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** Rollback store persisted across process restarts (core stays platform-agnostic). */
class SharedPreferencesBundleVersionStore(context: Context) : BundleVersionStore {
    private val prefs = context.getSharedPreferences("guarddog_bundle_versions", Context.MODE_PRIVATE)
    // Layout: "<rulesetId>" -> Long version (pre-existing key, so devices that already recorded v25 keep their state and are
    // migrated in place), "<rulesetId>.envelopeHash" -> identity of the accepted signed envelope (absent on legacy records).
    override fun highestAccepted(rulesetId: String): AcceptedBundle? =
        if (prefs.contains(rulesetId)) AcceptedBundle(prefs.getLong(rulesetId, 0), prefs.getString("$rulesetId.envelopeHash", null)) else null

    override fun recordAccepted(rulesetId: String, bundleVersion: Long, contentHash: String?) {
        val merged = InMemoryBundleVersionStore.merge(highestAccepted(rulesetId), AcceptedBundle(bundleVersion, contentHash))
        val editor = prefs.edit().putLong(rulesetId, merged.bundleVersion)
        if (merged.contentHash != null) editor.putString("$rulesetId.envelopeHash", merged.contentHash) else editor.remove("$rulesetId.envelopeHash")
        editor.apply()
    }
}

/**
 * Concrete Expo module class (discoverable by autolinking; no typealias shortcut).
 * Public surface is platform-neutral: requestPermission("vpn"), startProtection(), ...
 * All Android orchestration (consent intent, service, route) stays inside.
 */
class GuardDogExpoModule : Module() {
    private val state = VpnStateRepository.shared
    private lateinit var engine: GuardDogSDKEngine
    private var pendingConsent: Promise? = null
    // Gate Guard M2 Website Gate: the fast, in-memory runtime cache the native DNS pipeline
    // consults directly (see SinkholeBindingStore.arm). The durable, user-facing, auditable
    // record lives in JS/AsyncStorage (frontend/src/sdk/websiteGateOverrides.ts) and re-hydrates
    // this cache once per bridge session -- this object is never persisted natively.
    private val websiteGateOverrides = MutableWebsiteGateOverrideStore()

    private val context: Context get() = appContext.reactContext ?: throw CodedException("ERR_NO_CONTEXT", "React context unavailable", null)

    override fun definition() = ModuleDefinition {
        Name("GuardDogSecurity")
        Events(EVENT_SECURITY, EVENT_STATE)

        OnCreate {
            val validator = RuleBundleValidator(SharedPreferencesBundleVersionStore(context), SystemClock)
            engine = GuardDogSDKEngine(validator, state, SystemClock)
            engine.addEventListener { event ->
                GuardDogExpoAdapters.toRecord(event)?.let { sendEvent(EVENT_SECURITY, it.toBundle()) }
            }
            state.addListener { sendEvent(EVENT_STATE, GuardDogExpoAdapters.toRecord(it).toBundle()) }
            // Consent truthfulness fix (Phase 6A / M2.1 freeze, row 3.2): a physical device run showed
            // getProtectionState().consentGranted still reporting true after Android had genuinely
            // revoked VPN consent for this app -- VpnService.onRevoke() is only observed by a LIVE
            // service instance, so a revoke that happens while nothing is running (or between
            // process restarts) never clears the cached flag. Wire a live, on-demand OS check so
            // every status read re-derives consentGranted from VpnService.prepare(context) itself --
            // prepare() returning null IS Android's own authoritative "this app currently holds VPN
            // consent" answer, never merely assumed from our own cache. Falls back to the last-known
            // cached value only if the check throws (e.g. no foreground context at that instant).
            state.osConsentCheck = {
                try {
                    VpnService.prepare(context) == null
                } catch (e: Exception) {
                    state.consentGranted
                }
            }
            GuardDogVpnRuntime.reporter = engine
            // Gate Guard M2 Website Gate: the SAME engine instance -- GuardDogSDKEngine already holds
            // the M1 authorization table and the strictly parallel M2 WebsiteGateBinding table (Phase 3);
            // there is no second engine to construct or keep in sync.
            GuardDogVpnRuntime.websiteGateEngine = engine
            GuardDogVpnRuntime.websiteGateOverrideStore = websiteGateOverrides
        }

        Function("getCapabilities") { GuardDogExpoAdapters.androidCapabilities() }
        Function("getProtectionState") { GuardDogExpoAdapters.toRecord(state.current()) }

        Function("configure") { record: BridgeProtectionConfigRecord ->
            GuardDogVpnRuntime.config = GuardDogExpoAdapters.toVpnConfig(record)
        }

        Function("acceptRuleBundle") { rawJson: String -> GuardDogExpoAdapters.toRecord(engine.acceptRuleBundle(rawJson)) }

        Function("analyzeUrl") { url: String ->
            engine.analyzeUrl(url)?.let { mapOf("sanitizedUrl" to it.sanitizedUrl, "host" to it.host, "verdict" to it.verdict, "ruleId" to it.ruleId) }
        }

        // --- Gate Guard M2 Website Gate: additive bridge surface. None of the above M1 functions are touched. ---

        // The sinkhole pool / virtual DNS endpoint are ALWAYS the fixed native WebsiteGateAddressing
        // constants -- record only carries the upstream resolver + binding lifetime, never addresses
        // that could redirect Apollo's own DNS interception.
        Function("configureWebsiteGate") { record: BridgeWebsiteGateConfigRecord ->
            GuardDogVpnRuntime.websiteGateRouteConfig = WebsiteGateAddressing.defaultRouteConfig()
            GuardDogVpnRuntime.upstreamDnsResolverIpv4 = record.upstreamDnsResolverIpv4
            GuardDogVpnRuntime.websiteGateBindingLifetimeMillis = record.bindingLifetimeMs.toLong()
        }

        Function("acceptWebsiteGateRuleBundle") { rawJson: String -> GuardDogExpoAdapters.toRecord(engine.acceptWebsiteGateRuleBundle(rawJson)) }

        // Truthful, live status -- dnsGatewayActive reflects GuardDogVpnRuntime.websiteGateActive,
        // which only a live TUN session that actually built the DNS gateway pipeline can set true.
        Function("getWebsiteGateStatus") {
            GuardDogExpoAdapters.toWebsiteGateStatus(
                configured = GuardDogVpnRuntime.websiteGateRouteConfig != null,
                dnsGatewayActive = GuardDogVpnRuntime.websiteGateActive,
                acceptedBundle = engine.acceptedWebsiteGateBundle(),
                overrideCount = websiteGateOverrides.allowedHostsSnapshot().size,
            )
        }

        // Local, reversible, auditable ALLOW-only override (see WebsiteGateOverrideStore) -- can only
        // ever prevent a sinkhole arming the signed rule bundle would otherwise trigger; it can never
        // itself arm a binding or produce a THREAT_BLOCKED. Returns false if host fails canonicalization.
        Function("setWebsiteGateAllowOverride") { record: BridgeWebsiteGateOverrideRecord ->
            websiteGateOverrides.setAllowed(record.host, record.allowed)
        }

        Function("getWebsiteGateOverrides") { websiteGateOverrides.allowedHostsSnapshot().sorted() }

        Function("clearWebsiteGateOverrides") { websiteGateOverrides.clear() }

        AsyncFunction("requestPermission") { kind: String, promise: Promise ->
            if (kind != "vpn") { promise.resolve("unsupported"); return@AsyncFunction }
            val intent = VpnService.prepare(context)
            if (intent == null) { state.recordConsent(true); promise.resolve("granted"); return@AsyncFunction }
            val activity = appContext.currentActivity ?: throw CodedException("ERR_NO_ACTIVITY", "No foreground activity for consent", null)
            pendingConsent = promise
            state.transition(VpnLifecycleState.ConsentRequired)
            activity.startActivityForResult(intent, VPN_CONSENT_REQUEST)
        }

        OnActivityResult { _, payload ->
            if (payload.requestCode != VPN_CONSENT_REQUEST) return@OnActivityResult
            val granted = payload.resultCode == Activity.RESULT_OK
            state.recordConsent(granted)
            pendingConsent?.resolve(if (granted) "granted" else "denied")
            pendingConsent = null
        }

        AsyncFunction("startProtection") { promise: Promise ->
            val config = GuardDogVpnRuntime.config ?: throw CodedException("ERR_NOT_CONFIGURED", "configure() not called", null)
            if (!state.consentGranted || VpnService.prepare(context) != null) throw CodedException("ERR_CONSENT", "VPN consent not granted", null)
            if (engine.acceptedBundle() == null) throw CodedException("ERR_NO_BUNDLE", "no accepted signed rule bundle", null)
            // Physical-device fix (2026-06, P1): binding check is best-effort. On real carrier
            // networks the BlockTest host may fail DNS. The VPN service has its own off-thread
            // binding check and falls back to Website Gate-only mode gracefully.
            val binding = ControlledEndpointResolver(config, GuardDogVpnRuntime.resolver).verifyBinding()
            when (binding) {
                is BindingResult.Match -> {
                    when (val auth = engine.authorizeControlledTarget(config.controlledHost, binding.ipv4)) {
                        is BlockAuthorization.NotAuthorized -> android.util.Log.w("GuardDogBridge", "BlockTest rules rejected (${auth.reason}); proceeding with Website Gate-only")
                        is BlockAuthorization.Authorized -> Unit
                    }
                }
                is BindingResult.Mismatch -> android.util.Log.w("GuardDogBridge", "BlockTest DNS/IP mismatch; proceeding with Website Gate-only")
                is BindingResult.ResolutionFailed -> android.util.Log.w("GuardDogBridge", "BlockTest host did not resolve; proceeding with Website Gate-only")
            }
            context.startForegroundService(Intent(context, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_START))
            promise.resolve(GuardDogExpoAdapters.toRecord(state.current()))
        }

        AsyncFunction("stopProtection") { promise: Promise ->
            context.startService(Intent(context, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_STOP))
            engine.clearAuthorization()
            promise.resolve(GuardDogExpoAdapters.toRecord(state.current()))
        }

        Function("getEnforcementStats") {
            GuardDogVpnRuntime.dropReporter?.stats()?.let {
                mapOf("observedMatching" to it.observedMatching, "droppedMatching" to it.droppedMatching, "reportedBlocks" to it.reportedBlocks,
                    "dedupedRetries" to it.dedupedRetries, "unexpectedPackets" to it.unexpectedPackets,
                    "nonIpv4" to it.nonIpv4, "malformedIpv4" to it.malformedIpv4, "wrongDestinationIpv4" to it.wrongDestinationIpv4)
            }
        }

        // Recovery proof (AC-06): real runtime + OS-level snapshot; the HTTPS re-check is done by the caller.
        Function("getRecoveryStatus") {
            val r = RecoveryInspector.inspect(context, state)
            mapOf("lifecycle" to r.lifecycle, "tunOpen" to r.tunOpen, "selectiveRouteActive" to r.selectiveRouteActive,
                "vpnTransportPresent" to r.vpnTransportPresent, "routeCidr" to r.routeCidr, "dropReporterAttached" to r.dropReporterAttached,
                "recovered" to r.recovered)
        }

        // Harness-only, read-only OS consent check (never shows a dialog): true when VpnService.prepare() would return an intent, i.e. the
        // system holds no VPN consent for this app (revoked, never granted, or another VPN app owns it). Revoke proof evidence.
        Function("isVpnConsentRequired") { VpnService.prepare(context) != null }

        // Harness-only fresh-connection probe of the CONFIGURED controlled endpoint (no caller-supplied URL: nothing else is ever probed or
        // recorded). Opens a brand-new, unprotected socket each call so the probe is subject to our own /32 route; see FreshConnectionProbe.
        AsyncFunction("probeControlledEndpointFresh") { timeoutMs: Int, promise: Promise ->
            val config = GuardDogVpnRuntime.config ?: throw CodedException("ERR_NOT_CONFIGURED", "configure() not called", null)
            Thread {
                try {
                    promise.resolve(FreshConnectionProbe.run(config.controlledUrl, config.controlledIpv4, timeoutMs, GuardDogVpnRuntime.resolver).toMap())
                } catch (e: Exception) {
                    promise.reject(CodedException("E_FRESH_PROBE", e.message, e))
                }
            }.start()
        }

        // Build provenance for the device proof: SHA-256 of the installed base APK (compared against the CI artifact hash),
        // package/version and debuggable flag. Hashing runs off the main thread (APK is tens of MB).
        AsyncFunction("getBuildProvenance") { promise: Promise ->
            Thread {
                try {
                    val info = context.packageManager.getPackageInfo(context.packageName, 0)
                    val apk = java.io.File(context.applicationInfo.sourceDir)
                    val digest = java.security.MessageDigest.getInstance("SHA-256")
                    apk.inputStream().use { input ->
                        val buf = ByteArray(1 shl 16)
                        while (true) { val n = input.read(buf); if (n < 0) break; digest.update(buf, 0, n) }
                    }
                    val debuggable = (context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
                    promise.resolve(mapOf(
                        "apkSha256" to digest.digest().joinToString("") { "%02x".format(it) },
                        "apkSizeBytes" to apk.length(),
                        "splitApks" to (context.applicationInfo.splitSourceDirs?.size ?: 0),
                        "packageName" to context.packageName,
                        "versionName" to info.versionName,
                        "versionCode" to info.longVersionCode,
                        "debuggable" to debuggable,
                    ))
                } catch (e: Exception) {
                    promise.reject(CodedException("E_PROVENANCE", e.message, e))
                }
            }.start()
        }

        // Gate Guard M2.1 Phase 6: harness-only device provenance for the physical-device acceptance
        // report (docs/M2_PHASE6_ACCEPTANCE_TEMPLATE.md). Synchronous -- every field is an in-memory
        // android.os.Build constant, no I/O. `activeNativeStackId` is a native-sourced (not
        // JS-asserted) confirmation of which of the two independent Android stacks is actually
        // running: this module IS com.guarddog.* by construction (it cannot report the OTHER stack,
        // com.hucentai.apollosecurity, since that module's code never executes inside this process),
        // so its mere presence/response here is itself the "active stack" evidence the Phase 6
        // template asks for. Deliberately does NOT read Android's Private DNS setting: that value is
        // not exposed to third-party apps on modern Android without a privileged/system permission
        // this app does not hold -- see the template's own instruction to record it manually.
        Function("getPhase6DeviceProvenance") {
            mapOf(
                "manufacturer" to android.os.Build.MANUFACTURER,
                "model" to android.os.Build.MODEL,
                "osRelease" to android.os.Build.VERSION.RELEASE,
                "sdkInt" to android.os.Build.VERSION.SDK_INT,
                "securityPatch" to (android.os.Build.VERSION.SECURITY_PATCH ?: "unavailable"),
                "activeNativeStackId" to "com.guarddog.* (GuardDogSecurity native module)",
            )
        }

        // Gate Guard — DNS/DoH Capability Diagnostic Wizard (harness-only, additive; does not touch
        // any M1/M2/Phase6 acceptance code path). Exposes EXACTLY what Android's own public,
        // non-privileged API can prove about the device's current Private DNS runtime state --
        // and nothing more. LinkProperties.isPrivateDnsActive()/getPrivateDnsServerName() were
        // added in API 28 (Android 9); this app's minSdkVersion is 26, so devices below 28 report
        // UNSUPPORTED_OS_VERSION rather than a guessed value. Critically: privateDnsRuntimeMode ==
        // INACTIVE_OR_OFF is NEVER proof of "Off" -- Android's API cannot distinguish a deliberate
        // "Off" from "Automatic" whose opportunistic DoT probe is currently failing/unreachable.
        // The JS wizard (dnsCapabilityDiagnostic.ts) must preserve that ambiguity, never collapse it.
        //
        // Reviewer-caught fix: while Apollo's own VpnService is active, `ConnectivityManager.
        // activeNetwork` is Apollo's OWN virtual VPN network (Android routes default traffic through
        // it), whose LinkProperties reflect the DNS servers *this app's VpnService.Builder* declared
        // -- NOT the physical Wi-Fi/cellular network's real Private DNS state. Reading Private DNS
        // off `activeNetwork` while the VPN is up would silently inspect Apollo's own tunnel instead
        // of the real network being characterized. Android explicitly exposes
        // `NetworkCapabilities.NET_CAPABILITY_NOT_VPN` for exactly this disambiguation (see
        // https://developer.android.com/reference/android/net/NetworkCapabilities#NET_CAPABILITY_NOT_VPN);
        // find the underlying physical network by capability, not by "active", and read its
        // LinkProperties instead.
        Function("getDnsCapabilityDeviceSnapshot") {
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val physicalNetwork = connectivityManager.allNetworks.firstOrNull { net ->
                val caps = connectivityManager.getNetworkCapabilities(net)
                caps != null &&
                    caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                    caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) &&
                    (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))
            } ?: connectivityManager.activeNetwork // fallback: no VPN running yet (e.g. before Preflight starts protection)

            val privateDnsActive: Boolean
            val privateDnsServerName: String?
            val runtimeMode: String
            if (android.os.Build.VERSION.SDK_INT >= 28) {
                val linkProperties = physicalNetwork?.let { connectivityManager.getLinkProperties(it) }
                privateDnsActive = linkProperties?.isPrivateDnsActive ?: false
                privateDnsServerName = linkProperties?.privateDnsServerName
                runtimeMode = when {
                    privateDnsServerName != null -> "STRICT"
                    privateDnsActive -> "ACTIVE_NO_HOSTNAME"
                    else -> "INACTIVE_OR_OFF"
                }
            } else {
                privateDnsActive = false
                privateDnsServerName = null
                runtimeMode = "UNSUPPORTED_OS_VERSION"
            }
            val physicalCapabilities = physicalNetwork?.let { connectivityManager.getNetworkCapabilities(it) }
            val networkTransport = when {
                physicalCapabilities == null -> "unknown"
                physicalCapabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                physicalCapabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
                physicalCapabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                physicalCapabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn" // only reachable via the activeNetwork fallback above
                else -> "other"
            }
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            mapOf(
                "supportedAbis" to android.os.Build.SUPPORTED_ABIS.toList(),
                "primaryAbi" to (android.os.Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"),
                "activeNativeStackId" to "com.guarddog.* (GuardDogSecurity native module)",
                "privateDnsActive" to privateDnsActive,
                "privateDnsServerName" to privateDnsServerName,
                "privateDnsRuntimeMode" to runtimeMode,
                "networkTransport" to networkTransport,
                "notificationsEnabled" to notificationManager.areNotificationsEnabled(),
                "capturedAtMillis" to System.currentTimeMillis(),
            )
        }

        // DNS/DoH Diagnostic Wizard: native Settings navigation (physical-device review fix --
        // previously only a JS-side `Linking.sendIntent`/`Linking.openSettings()` guess with zero
        // visibility into whether anything actually opened, or what). Tries the direct Private DNS
        // settings screen first, falls back to the general Network & internet ("Wireless") settings
        // screen, then the top-level Settings app -- each candidate is verified resolvable via
        // PackageManager BEFORE attempting to launch it, so an OEM/skin that doesn't expose one
        // candidate cleanly falls through to the next rather than silently doing nothing or
        // crashing with ActivityNotFoundException. Returns exactly which screen was opened (or
        // FAILED) so the wizard can report this truthfully instead of assuming success.
        Function("openPrivateDnsSettings") {
            val candidates = listOf(
                "PRIVATE_DNS_SETTINGS" to "android.settings.PRIVATE_DNS_SETTINGS",
                "NETWORK_SETTINGS" to android.provider.Settings.ACTION_WIRELESS_SETTINGS,
                "GENERIC_SETTINGS" to android.provider.Settings.ACTION_SETTINGS,
            )
            var openedScreen = "FAILED"
            for ((label, action) in candidates) {
                try {
                    val intent = Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    if (intent.resolveActivity(context.packageManager) != null) {
                        context.startActivity(intent)
                        openedScreen = label
                        break
                    }
                } catch (e: Exception) {
                    // this candidate isn't launchable on this device/OEM -- fall through to the next, more-generic one.
                }
            }
            mapOf("openedScreen" to openedScreen)
        }

        // DNS/DoH wizard, tenth fix round (explicit user instruction: "automate everything the OS
        // can tell us; ask the tester only for information Android cannot expose"). Enumerates
        // every installed app that can handle a generic https:// ACTION_VIEW intent -- the
        // standard technique for listing installed browsers, since Android exposes no dedicated
        // "list browsers" API. Deduplicated by package (a browser can register multiple matching
        // activities); `isDefaultBrowser` compares against `packageManager.resolveActivity()`'s
        // own answer for the SAME probe intent, i.e. Android's own current default-app choice --
        // never guessed or hardcoded. A getPackageInfo() failure for any single candidate (e.g. it
        // was uninstalled between the query and this loop) is skipped, never crashes the whole call.
        Function("listHttpsCapableBrowsers") {
            val pm = context.packageManager
            val probeIntent = Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://www.example.com"))
            val defaultPackage = pm.resolveActivity(probeIntent, 0)?.activityInfo?.packageName
            val seenPackages = mutableSetOf<String>()
            val browsers = mutableListOf<Map<String, Any?>>()
            for (info in pm.queryIntentActivities(probeIntent, 0)) {
                val pkg = info.activityInfo.packageName
                if (!seenPackages.add(pkg)) continue
                try {
                    val pInfo = pm.getPackageInfo(pkg, 0)
                    browsers.add(mapOf(
                        "packageName" to pkg,
                        "appLabel" to (info.loadLabel(pm)?.toString() ?: pkg),
                        "versionName" to (pInfo.versionName ?: "unknown"),
                        "versionCode" to pInfo.longVersionCode,
                        "isDefaultBrowser" to (pkg == defaultPackage),
                    ))
                } catch (e: Exception) {
                    // uninstalled/unreadable between the query and here -- skip, never crash the whole list.
                }
            }
            browsers.sortedByDescending { it["isDefaultBrowser"] as Boolean }
        }

        // DNS/DoH wizard, tenth fix round: launches `url` EXPLICITLY into `packageName` (via
        // Intent.setPackage) rather than a generic ACTION_VIEW that lets Android's chooser (or a
        // stale last-used default) pick the app -- so the probe's machine-recorded browser
        // identity (from listHttpsCapableBrowsers above) is provably the SAME app that actually
        // opened the URL, never merely assumed. Verifies resolvability first via
        // resolveActivity(); never throws on failure -- returns a truthful opened:false + reason
        // instead, matching openPrivateDnsSettings's existing not-a-crash contract.
        Function("openUrlInBrowserPackage") { url: String, packageName: String ->
            try {
                val intent = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)).setPackage(packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                if (intent.resolveActivity(context.packageManager) == null) {
                    mapOf("opened" to false, "reason" to "Package $packageName cannot handle this URL on this device (resolveActivity returned null).")
                } else {
                    context.startActivity(intent)
                    mapOf("opened" to true, "reason" to null)
                }
            } catch (e: Exception) {
                mapOf("opened" to false, "reason" to (e.message ?: "unknown error launching $packageName"))
            }
        }

        // ----------------------------------------------------------------
        // Native Protection Detection — reports which OS/OEM scam
        // protection capabilities are present and their enabled state.
        //
        // This DETECTS capabilities. It does NOT read native verdicts
        // (no verified public API has been confirmed for Google,
        // Samsung, or carrier call/message classifications).
        // ----------------------------------------------------------------
        Function("getNativeProtectionCapabilities") {
            val pm = context.packageManager
            val telecom = context.getSystemService(Context.TELECOM_SERVICE) as android.telecom.TelecomManager

            // --- Call protection providers ---
            val callProtection = mutableListOf<Map<String, Any>>()

            // Google Phone / Dialer — has built-in call screening and spam detection
            val defaultDialer = try { telecom.defaultDialerPackage ?: "" } catch (_: Exception) { "" }
            val googlePhoneInstalled = try {
                pm.getPackageInfo("com.google.android.dialer", 0)
                true
            } catch (_: Exception) { false }
            val googlePhoneIsDefault = defaultDialer == "com.google.android.dialer"
            callProtection.add(mapOf(
                "provider" to "Google Phone",
                "packageName" to "com.google.android.dialer",
                "installed" to googlePhoneInstalled,
                "isDefaultHandler" to googlePhoneIsDefault,
                "feature" to "Caller ID & spam protection",
                "classificationAccessible" to false,  // No verified public API (rule 6)
                "note" to "Google does not share its scam-call classification with other apps, so Apollo cannot use it as evidence."
            ))

            // Samsung Smart Call (Hiya-powered)
            val samsungSmartCallInstalled = try {
                pm.getPackageInfo("com.samsung.android.smartcallprovider", 0)
                true
            } catch (_: Exception) {
                try {
                    pm.getPackageInfo("com.hiya.star", 0)
                    true
                } catch (_: Exception) { false }
            }
            val samsungDialerIsDefault = defaultDialer == "com.samsung.android.dialer"
            callProtection.add(mapOf(
                "provider" to "Samsung Smart Call",
                "packageName" to "com.samsung.android.smartcallprovider",
                "installed" to samsungSmartCallInstalled,
                "isDefaultHandler" to samsungDialerIsDefault,
                "feature" to "Caller ID & spam filtering",
                "classificationAccessible" to false,  // No verified Samsung API (rule 7)
                "note" to "Samsung does not share Smart Call's scam classification with other apps, so Apollo cannot use it as evidence."
            ))

            // Carrier visual voicemail / spam filter (T-Mobile Scam Shield, etc.)
            val carrierSpamApps = listOf(
                "com.tmobile.scamshield" to "T-Mobile Scam Shield",
                "com.att.callprotect" to "AT&T Call Protect",
                "com.verizon.callfilter" to "Verizon Call Filter",
            )
            for ((pkg, name) in carrierSpamApps) {
                val installed = try { pm.getPackageInfo(pkg, 0); true } catch (_: Exception) { false }
                if (installed) {
                    callProtection.add(mapOf(
                        "provider" to name,
                        "packageName" to pkg,
                        "installed" to true,
                        "isDefaultHandler" to false,
                        "feature" to "Carrier-level call filtering",
                        "classificationAccessible" to false,
                        "note" to "Your carrier does not share its call-filtering classification with other apps, so Apollo cannot use it as evidence."
                    ))
                }
            }

            // --- Message protection providers ---
            val messageProtection = mutableListOf<Map<String, Any>>()

            // Google Messages — has built-in spam/RCS classification
            val googleMessagesInstalled = try {
                pm.getPackageInfo("com.google.android.apps.messaging", 0)
                true
            } catch (_: Exception) { false }
            val defaultSms = try {
                android.provider.Telephony.Sms.getDefaultSmsPackage(context) ?: ""
            } catch (_: Exception) { "" }
            val googleMessagesIsDefault = defaultSms == "com.google.android.apps.messaging"
            messageProtection.add(mapOf(
                "provider" to "Google Messages",
                "packageName" to "com.google.android.apps.messaging",
                "installed" to googleMessagesInstalled,
                "isDefaultHandler" to googleMessagesIsDefault,
                "feature" to "Spam protection & verified SMS",
                "classificationAccessible" to false,
                "note" to "Google Messages does not share its spam classification with other apps, so Apollo cannot use it as evidence."
            ))

            // Samsung Messages
            val samsungMessagesInstalled = try {
                pm.getPackageInfo("com.samsung.android.messaging", 0)
                true
            } catch (_: Exception) { false }
            val samsungMessagesIsDefault = defaultSms == "com.samsung.android.messaging"
            messageProtection.add(mapOf(
                "provider" to "Samsung Messages",
                "packageName" to "com.samsung.android.messaging",
                "installed" to samsungMessagesInstalled,
                "isDefaultHandler" to samsungMessagesIsDefault,
                "feature" to "Spam filtering",
                "classificationAccessible" to false,
                "note" to "Samsung Messages does not share its spam classification with other apps, so Apollo cannot use it as evidence."
            ))

            mapOf(
                "callProtection" to callProtection,
                "messageProtection" to messageProtection,
                "defaultDialerPackage" to defaultDialer,
                "defaultSmsPackage" to defaultSms,
                "platform" to "android",
                "capturedAtMillis" to System.currentTimeMillis(),
            )
        }

        // ----------------------------------------------------------------
        // Device Posture Snapshot — reads all Android-accessible security
        // settings in one call. Each field is the OS's own answer; Apollo
        // reports what changed, never guesses why.
        // ----------------------------------------------------------------
        Function("getDevicePostureSnapshot") {
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val keyguardManager = context.getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager
            val pm = context.packageManager

            // Developer Options
            val developerOptionsEnabled = try {
                android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1
            } catch (_: Exception) { false }

            // USB Debugging
            val usbDebuggingEnabled = try {
                android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.ADB_ENABLED, 0) == 1
            } catch (_: Exception) { false }

            // Unknown Sources (API 26+: per-app canRequestPackageInstalls)
            val unknownSourcesEnabled = try {
                if (android.os.Build.VERSION.SDK_INT >= 26) {
                    pm.canRequestPackageInstalls()
                } else {
                    @Suppress("DEPRECATION")
                    android.provider.Settings.Secure.getInt(context.contentResolver, android.provider.Settings.Secure.INSTALL_NON_MARKET_APPS, 0) == 1
                }
            } catch (_: Exception) { false }

            // Screen Lock
            val screenLockSecure = keyguardManager.isDeviceSecure

            // Biometrics
            val biometricStatus = try {
                val bm = androidx.biometric.BiometricManager.from(context)
                when (bm.canAuthenticate(androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG or androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK)) {
                    androidx.biometric.BiometricManager.BIOMETRIC_SUCCESS -> "enrolled"
                    androidx.biometric.BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED -> "none_enrolled"
                    androidx.biometric.BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE -> "no_hardware"
                    else -> "unavailable"
                }
            } catch (_: Exception) { "unavailable" }

            // Notifications
            val notificationsEnabled = notificationManager.areNotificationsEnabled()

            // Accessibility services
            val accessibilityServices = try {
                val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as android.view.accessibility.AccessibilityManager
                am.getEnabledAccessibilityServiceList(android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
                    .mapNotNull { it.resolveInfo?.serviceInfo?.packageName }
                    .filter { it != context.packageName }
                    .distinct()
            } catch (_: Exception) { emptyList() }

            // Device admin apps
            val deviceAdmins = try {
                val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as android.app.admin.DevicePolicyManager
                dpm.activeAdmins?.map { it.packageName }?.filter { it != context.packageName }?.distinct() ?: emptyList()
            } catch (_: Exception) { emptyList<String>() }

            // Default SMS app
            val defaultSmsApp = try {
                if (android.os.Build.VERSION.SDK_INT >= 24) {
                    val roleManager = context.getSystemService(android.app.role.RoleManager::class.java)
                    // Can't query role holders without API 29 (Q) — use Telephony default
                    android.provider.Telephony.Sms.getDefaultSmsPackage(context) ?: "unknown"
                } else {
                    android.provider.Telephony.Sms.getDefaultSmsPackage(context) ?: "unknown"
                }
            } catch (_: Exception) { "unknown" }

            // Default phone/dialer app
            val defaultDialerApp = try {
                val telecom = context.getSystemService(Context.TELECOM_SERVICE) as android.telecom.TelecomManager
                telecom.defaultDialerPackage ?: "unknown"
            } catch (_: Exception) { "unknown" }

            // Notification listener packages
            val notificationListeners = try {
                val raw = android.provider.Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: ""
                raw.split(":").mapNotNull {
                    try { android.content.ComponentName.unflattenFromString(it)?.packageName } catch (_: Exception) { null }
                }.filter { it != context.packageName }.distinct()
            } catch (_: Exception) { emptyList<String>() }

            // Overlay permission apps (can draw over other apps)
            // Cannot enumerate all — we report whether our own app has it (as a reference). Full enumeration requires PackageManager queries.
            val canDrawOverlays = android.provider.Settings.canDrawOverlays(context)

            // VPN: is another VPN active (not ours)?
            val otherVpnActive = try {
                val activeNet = connectivityManager.activeNetwork
                val caps = activeNet?.let { connectivityManager.getNetworkCapabilities(it) }
                val vpnTransport = caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) ?: false
                val ourVpnRunning = state.current().lifecycle.name.let { it == "Running" || it == "Starting" }
                vpnTransport && !ourVpnRunning
            } catch (_: Exception) { false }

            // User-installed certificates
            val userCertificateCount = try {
                val ks = java.security.KeyStore.getInstance("AndroidCAStore")
                ks.load(null)
                val userCerts = ks.aliases().toList().count { alias ->
                    try { alias.startsWith("user:") } catch (_: Exception) { false }
                }
                userCerts
            } catch (_: Exception) { -1 }  // -1 = couldn't read

            // Root / Jailbreak indicators
            val rootIndicators = mutableListOf<String>()
            try {
                val suPaths = listOf("/system/bin/su", "/system/xbin/su", "/sbin/su", "/system/su", "/data/local/xbin/su", "/data/local/bin/su")
                for (path in suPaths) { if (java.io.File(path).exists()) { rootIndicators.add("su_binary:$path"); break } }
                if (android.os.Build.TAGS?.contains("test-keys") == true) rootIndicators.add("test_keys_build")
                // Check for common root management apps
                val rootApps = listOf("com.topjohnwu.magisk", "eu.chainfire.supersu", "com.koushikdutta.superuser", "com.thirdparty.superuser")
                for (pkg in rootApps) { try { pm.getPackageInfo(pkg, 0); rootIndicators.add("root_app:$pkg") } catch (_: Exception) { } }
            } catch (_: Exception) { }

            // OS Security patch level
            val securityPatch = android.os.Build.VERSION.SECURITY_PATCH ?: "unknown"

            // Play Protect: best-effort check via Google API availability
            val playProtectAvailable = try {
                val cls = Class.forName("com.google.android.gms.common.GoogleApiAvailability")
                val instance = cls.getMethod("getInstance").invoke(null)
                val result = cls.getMethod("isGooglePlayServicesAvailable", Context::class.java).invoke(instance, context) as Int
                result == 0  // ConnectionResult.SUCCESS
            } catch (_: Exception) { false }

            // Screen capture / media projection active (API 29+)
            val screenCaptureDetectable = android.os.Build.VERSION.SDK_INT >= 29

            mapOf(
                // Settings
                "developerOptionsEnabled" to developerOptionsEnabled,
                "usbDebuggingEnabled" to usbDebuggingEnabled,
                "unknownSourcesEnabled" to unknownSourcesEnabled,
                "screenLockSecure" to screenLockSecure,
                "biometricStatus" to biometricStatus,
                "notificationsEnabled" to notificationsEnabled,
                // Privileged access
                "accessibilityServices" to accessibilityServices,
                "deviceAdmins" to deviceAdmins,
                "notificationListeners" to notificationListeners,
                "canDrawOverlays" to canDrawOverlays,
                // Default app handlers
                "defaultSmsApp" to defaultSmsApp,
                "defaultDialerApp" to defaultDialerApp,
                // VPN & network
                "otherVpnActive" to otherVpnActive,
                // Certificates
                "userCertificateCount" to userCertificateCount,
                // Root / compromise
                "rootIndicators" to rootIndicators,
                // OS security
                "securityPatch" to securityPatch,
                "playProtectAvailable" to playProtectAvailable,
                "screenCaptureDetectable" to screenCaptureDetectable,
                // Metadata
                "capturedAtMillis" to System.currentTimeMillis(),
                "sdkInt" to android.os.Build.VERSION.SDK_INT,
            )
        }

    }

    companion object {
        const val EVENT_SECURITY = "onSecurityEvent"
        const val EVENT_STATE = "onProtectionStateChanged"
        private const val VPN_CONSENT_REQUEST = 0x6D31
    }
}

private fun expo.modules.kotlin.records.Record.toBundle(): android.os.Bundle {
    val bundle = android.os.Bundle()
    for (field in this::class.java.declaredFields) {
        field.isAccessible = true
        when (val v = field.get(this)) {
            null -> Unit
            is String -> bundle.putString(field.name, v)
            is Boolean -> bundle.putBoolean(field.name, v)
            is Double -> bundle.putDouble(field.name, v)
            is Long -> bundle.putLong(field.name, v)
            is Int -> bundle.putInt(field.name, v)
        }
    }
    return bundle
}
