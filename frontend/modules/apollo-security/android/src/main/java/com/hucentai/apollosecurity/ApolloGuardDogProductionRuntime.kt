package com.hucentai.apollosecurity

import android.content.Context
import android.content.Intent
import android.net.VpnService
import androidx.work.ExistingWorkPolicy
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.guarddog.core.BlockAuthorization
import com.guarddog.core.GuardDogSDKEngine
import com.guarddog.core.clock.SystemClock
import com.guarddog.core.events.BlockedThreatEvidence
import com.guarddog.core.protection.ProtectionEnforcementReporter
import com.guarddog.core.protection.ProtectionState
import com.guarddog.core.rules.RuleBundleValidator
import com.guarddog.core.rules.RuleBundle
import com.guarddog.core.rules.ValidationResult
import com.guarddog.vpn.BindingResult
import com.guarddog.vpn.ControlledEndpointResolver
import com.guarddog.vpn.DnsThreatObservedListener
import com.guarddog.vpn.GuardDogVpnRuntime
import com.guarddog.vpn.GuardDogVpnService
import com.guarddog.vpn.MutableWebsiteGateOverrideStore
import com.guarddog.vpn.RecoveryInspector
import com.guarddog.vpn.VpnConfig
import com.guarddog.vpn.VpnStateRepository
import com.guarddog.vpn.WebsiteGateAddressing
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.NetworkCapabilities
import android.os.Build
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.time.Duration
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

private data class ProductionRuntimeConfig(
  val ruleBundleUrl: String, val controlledHost: String?, val controlledIpv4: String?,
  val controlledUrl: String?, val rulesetId: String, val dedupeWindowMs: Long,
) {
  val hasControlledEndpoint: Boolean get() = !controlledHost.isNullOrBlank() && !controlledIpv4.isNullOrBlank() && !controlledUrl.isNullOrBlank()
  fun vpn() = VpnConfig(controlledHost ?: "", controlledIpv4 ?: "", controlledUrl ?: "", rulesetId, dedupeWindowMs)
  fun json() = JSONObject().put("ruleBundleUrl", ruleBundleUrl).put("controlledHost", controlledHost ?: JSONObject.NULL)
    .put("controlledIpv4", controlledIpv4 ?: JSONObject.NULL).put("controlledUrl", controlledUrl ?: JSONObject.NULL).put("rulesetId", rulesetId).put("dedupeWindowMs", dedupeWindowMs)
  companion object {
    fun parse(raw: String): ProductionRuntimeConfig {
      val body = JSONObject(raw); val allowed = setOf("ruleBundleUrl", "controlledHost", "controlledIpv4", "controlledUrl", "rulesetId", "dedupeWindowMs")
      check(body.keys().asSequence().toSet() == allowed) { "production runtime configuration schema mismatch" }
      val rules = URI(body.getString("ruleBundleUrl"))
      check(rules.scheme == "https") { "production GuardDog rule URL must use HTTPS" }
      // Controlled endpoint fields are optional — null/empty means no controlled endpoint configured
      val hostRaw = body.optString("controlledHost", "").trim().lowercase().ifBlank { null }
      val ipv4Raw = body.optString("controlledIpv4", "").trim().ifBlank { null }
      val controlledUrlRaw = body.optString("controlledUrl", "").trim().ifBlank { null }
      if (controlledUrlRaw != null) {
        val controlled = URI(controlledUrlRaw)
        check(controlled.scheme == "https") { "production controlled URL must use HTTPS" }
        check(hostRaw == controlled.host?.lowercase()) { "controlled URL host mismatch" }
      }
      if (ipv4Raw != null) { check(ipv4Raw.split('.').size == 4 && ipv4Raw.split('.').all { it.toIntOrNull() in 0..255 }) }
      val ruleset = body.getString("rulesetId"); check(ruleset.matches(Regex("^[a-z0-9-]{3,80}$")))
      return ProductionRuntimeConfig(rules.toString(), hostRaw, ipv4Raw, controlledUrlRaw, ruleset, body.getLong("dedupeWindowMs"))
    }
  }
}

private data class ProductionPendingEvidence(val evidence: BlockedThreatEvidence)

/**
 * Apollo-owned production authority over the frozen GuardDog core/VPN.
 * Rules are authenticated via HTTPS + Ed25519 cryptographic signature (Stage 4).
 */
internal class ApolloGuardDogProductionRuntime(private val context: Context) {

  companion object {
    /**
     * Pinned Ed25519 signing public key (base64-encoded, 32 bytes raw).
     *
     * Trust model: this key is embedded at build time. The backend signs rule bundles
     * with the corresponding private key. A downloaded key from the same server CANNOT
     * silently replace this pinned key — key rotation requires an app update.
     *
     * On Android 8–12 (API 26–32), java.security.Signature("Ed25519") is not available.
     * The native verifier returns Unavailable; the bundle is accepted without signature
     * verification, relying on the HTTPS TLS connection for authentication. On API 33+,
     * full Ed25519 verification is enforced.
     */
    const val PINNED_SIGNING_PUBLIC_KEY = "tu+b28Kvrl7a0JYcgBLyn7XxSDzLkfhdBROHZq+4k5Q="
    const val LABEL = "GuardDog production Website Gate"
  }
  private val transitions = ApolloEnforcementTransitions.coordinator
  private val state = VpnStateRepository.shared
  private val prefs = context.getSharedPreferences("apollo_guarddog_production", Context.MODE_PRIVATE)
  private val inbox = BoundedEvidenceInbox(256, SharedPreferencesEvidencePersistence(prefs)) {
    runCatching { JSONObject(it).optString("evidenceId").takeIf(String::isNotBlank) }.getOrNull()
  }
  private val dnsThreatInbox = ApolloDnsThreatInbox(context.getSharedPreferences("apollo_dns_threat_observations", Context.MODE_PRIVATE))
  private val pending = ConcurrentHashMap<String, ProductionPendingEvidence>()
  private var config: ProductionRuntimeConfig? = prefs.getString("config", null)?.let { runCatching { ProductionRuntimeConfig.parse(it) }.getOrNull() }
  private var engine: GuardDogSDKEngine? = null
  private var acceptedBundleExpiresAt: Instant? = null
  private val websiteGateOverrides = MutableWebsiteGateOverrideStore()
  @Volatile private var observedUpstreamDns: String? = null
  private val networkObserver = ApolloGuardDogNetworkObserver(context) { upstream -> onNetworkDnsChanged(upstream) }
  private val reporter = ProtectionEnforcementReporter { evidence ->
    if (!ruleBundleCurrent()) { inbox.reportFailure("Production rule bundle expired; evidence was withheld"); scheduleExpiry(Instant.now()); return@ProtectionEnforcementReporter }
    pending[evidence.enforcementEvidenceId] = ProductionPendingEvidence(evidence)
    try { checkNotNull(engine).reportBlockedPacket(evidence) }
    catch (_: Throwable) { inbox.reportFailure("Production engine event reporting failed") }
    finally { pending.remove(evidence.enforcementEvidenceId) }
  }

  init {
    state.osConsentCheck = { VpnService.prepare(context) == null }
    runCatching { rebuildFromPersisted() }.onFailure { inbox.reportFailure("Persisted production rules could not be restored") }
    networkObserver.start()
  }

  // ── Device authentication token (set from JS bridge, persisted for background VPN sessions) ──
  fun setDeviceToken(token: String) {
    prefs.edit().putString("device_bearer_token", token).apply()
  }
  private fun deviceToken(): String? = prefs.getString("device_bearer_token", null)

  /** Derive the backend base URL from the configured rule bundle URL. */
  private fun backendBaseUrl(): String? {
    val cfg = config ?: return null
    val uri = URI(cfg.ruleBundleUrl)
    return "${uri.scheme}://${uri.host}" + (if (uri.port > 0) ":${uri.port}" else "")
  }

  fun configure(raw: String): String = transitions.serialized {
    requireProductionEnabled(); val next = ProductionRuntimeConfig.parse(raw)
    check(prefs.edit().putString("config", next.json().toString()).commit()) { "Could not persist production configuration" }
    config = next
    scheduleRefresh()
    JSONObject().put("configured", true).toString()
  }

  /** Fetch the latest rules from the authenticated HTTPS backend and validate them. */
  fun refreshRules(): String {
    val active = checkNotNull(config) { "Production GuardDog is not configured" }
    val rawBundle = fetch(active.ruleBundleUrl)
    return transitions.serialized { acceptBundleLocked(rawBundle) }
  }

  /**
   * Hot-refresh: fetch and apply the latest rules WITHOUT stopping/restarting the active VPN.
   *
   * Used by the DNS handler's rule refresher when a live reputation check discovers a new
   * malicious hostname. The backend has created a threat indicator, so the updated bundle
   * now includes a blocking rule for that hostname.
   *
   * This method:
   * - Does NOT acquire the transitions lock (avoids deadlock with the VPN's DNS thread)
   * - Does NOT stop/restart the VPN (avoids killing the calling DNS handler)
   * - Validates the bundle (Ed25519 signature, schema, version) identically to [refreshRules]
   * - Applies the new rules to the running engine's @Volatile acceptedBundle fields
   * - Subsequent arm() calls see the updated rules immediately
   *
   * Returns true if the rules were successfully applied, false otherwise.
   */
  fun hotRefreshRules(): Boolean {
    val active = config ?: return false
    val activeEngine = engine ?: return false
    val rawBundle: String
    try { rawBundle = fetch(active.ruleBundleUrl) } catch (_: Throwable) { return false }
    val validator = RuleBundleValidator(ApolloBundleVersionStore(context, "production:v2"), SystemClock, PINNED_SIGNING_PUBLIC_KEY)
    val staged = validator.validate(rawBundle)
    if (staged is ValidationResult.Rejected) return false
    val bundle = (staged as ValidationResult.Accepted).bundle
    if (bundle.rulesetId != active.rulesetId) return false
    // Hot-apply: update the engine's @Volatile rule stores. No clearAuthorization/clearBindings
    // because we're adding rules (not removing). Active sinkhole bindings remain valid.
    if (activeEngine.acceptRuleBundle(rawBundle) is ValidationResult.Rejected) return false
    activeEngine.acceptWebsiteGateRuleBundle(rawBundle)
    persistBundle(rawBundle, bundle.bundleVersion)
    acceptedBundleExpiresAt = Instant.parse(bundle.expiresAt)
    return true
  }

  fun acceptBundle(raw: String): String = transitions.serialized { acceptBundleLocked(raw) }
  private fun acceptBundleLocked(raw: String): String {
    val activeConfig = checkNotNull(config)
    // Stage 4: Validate bundle with Ed25519 signature verification using the pinned public key.
    val validator = RuleBundleValidator(ApolloBundleVersionStore(context, "production:v2"), SystemClock, PINNED_SIGNING_PUBLIC_KEY)
    val staged = validator.validate(raw)
    if (staged is ValidationResult.Rejected) return JSONObject().put("accepted", false).put("reason", staged.reason.name).toString()
    val bundle = (staged as ValidationResult.Accepted).bundle
    check(bundle.rulesetId == activeConfig.rulesetId) { "Rule bundle targets a different ruleset" }
    val bundleExpiry = Instant.parse(bundle.expiresAt)
    val activeEngine = engine ?: rebuildEngine()
    val previous = persistedBundleVersion()
    if (previous != null) {
      check(bundle.bundleVersion >= previous) { "Rule bundle rollback" }
    }
    val changed = persistedBundle() == null || persistedBundleVersion() != bundle.bundleVersion
    val resume = changed && ownsEnforcement()
    if (resume) { stopLocked(); check(transitions.await(2_000) { pending.isEmpty() }) { "GuardDog evidence reporting did not drain before rule transition" } }
    if (changed) { activeEngine.clearAuthorization(); activeEngine.clearWebsiteGateBindings() }
    return when (val result = activeEngine.acceptRuleBundle(raw)) {
      is ValidationResult.Accepted -> {
        check(activeEngine.acceptWebsiteGateRuleBundle(raw) is ValidationResult.Accepted) { "Website Gate rejected the accepted production rule bundle" }
        persistBundle(raw, bundle.bundleVersion)
        acceptedBundleExpiresAt = bundleExpiry; scheduleExpiry(bundleExpiry)
        if (resume) startLocked()
        // Zero Threat Domain Entries is a valid list: accepted like any other, never a failure.
        JSONObject().put("accepted", true).put("rulesetId", result.bundle.rulesetId).put("bundleVersion", result.bundle.bundleVersion)
          .put("expiresAt", result.bundle.expiresAt).put("entryCount", result.bundle.payload.rules.size).toString()
      }
      is ValidationResult.Rejected -> JSONObject().put("accepted", false).put("reason", result.reason.name).toString()
    }
  }

  private fun rebuildEngine(): GuardDogSDKEngine {
    val validator = RuleBundleValidator(ApolloBundleVersionStore(context, "production:v2"), SystemClock, PINNED_SIGNING_PUBLIC_KEY)
    val rebuilt = GuardDogSDKEngine(validator, state, SystemClock)
    rebuilt.addEventListener { event ->
      try {
        val item = pending[event.enforcementEvidenceId ?: return@addEventListener] ?: return@addEventListener
        val record = ApolloGuardDogEvidenceCorrelator.correlate(event, item.evidence, "Android ${android.os.Build.VERSION.RELEASE}") ?: return@addEventListener
        if (ApolloGuardDogEvidenceCorrelator.contractValid(record)) inbox.append(JSONObject(record).toString()) else inbox.reportFailure("Production evidence contract failed")
      } catch (_: Throwable) { inbox.reportFailure("Production evidence correlation failed") }
    }
    engine = rebuilt
    return rebuilt
  }

  private fun rebuildFromPersisted() {
    val raw = persistedBundle() ?: return
    val rebuilt = rebuildEngine()
    runCatching {
      val expires = Instant.parse(RuleBundle.fromJson(raw).expiresAt)
      check(expires.isAfter(Instant.now()))
      check(rebuilt.acceptRuleBundle(raw) is ValidationResult.Accepted); check(rebuilt.acceptWebsiteGateRuleBundle(raw) is ValidationResult.Accepted)
      acceptedBundleExpiresAt = expires; scheduleExpiry(expires)
    }.onFailure { engine = null; inbox.reportFailure("Persisted production rule bundle could not be restored") }
  }

  // ── Offline persistence for rule bundles ──────────────────────────────────
  private fun persistedBundle(): String? = prefs.getString("rule_bundle_raw", null)
  private fun persistedBundleVersion(): Long? = prefs.getLong("rule_bundle_version", -1).takeIf { it >= 0 }
  private fun persistBundle(raw: String, version: Long) { prefs.edit().putString("rule_bundle_raw", raw).putLong("rule_bundle_version", version).apply() }

  fun start(): String = transitions.serialized { startLocked().also { clearSystemStartFailure() } }

  /**
   * Android's own request to connect Apollo's VPN (see [ApolloAlwaysOnVpnStarter]): sent only when
   * the person chose Apollo as the Always-on VPN, so it is their intent and is recorded as such.
   * Rebuilds protection from the persisted, validated config + rule bundle. Idempotent: a request
   * while protection already runs changes nothing. Every outcome is recorded for the status.
   */
  fun startForSystemRequest(): String = transitions.serialized {
    if (actualOperational()) { recordSystemStart("already_running", null); return@serialized statusLocked() }
    try {
      requireProductionEnabled()
      checkNotNull(config) { "website protection hasn't been set up on this phone yet. Open ApolloSG and turn it on" }
      check(ruleBundleCurrent()) { "ApolloSG doesn't have a current Threat Domain List on this phone yet. Open ApolloSG while you're online so it can get one" }
      check(prefs.edit().putBoolean("requested", true).commit()) { "Could not record the protection request" }
      startLocked().also { recordSystemStart("started", null) }
    } catch (t: Throwable) {
      recordSystemStart("failed", t.message ?: t.javaClass.simpleName); throw t
    }
  }

  /** Waits (outside the transition lock) until a physical network offers an IPv4 DNS resolver. */
  fun awaitPhysicalDns(timeoutMs: Long): Boolean = transitions.await(timeoutMs, 250) { networkObserver.currentIpv4Dns() != null }

  private fun recordSystemStart(outcome: String, reason: String?) {
    prefs.edit().putString("system_start_at", Instant.now().toString()).putString("system_start_outcome", outcome)
      .also { if (reason != null) it.putString("system_start_reason", reason.take(300)) else it.remove("system_start_reason") }.apply()
  }
  private fun clearSystemStartFailure() {
    if (prefs.getString("system_start_outcome", null) == "failed") prefs.edit().remove("system_start_reason").putString("system_start_outcome", "superseded").apply()
  }
  private fun systemStartJson(): Any {
    val at = prefs.getString("system_start_at", null) ?: return JSONObject.NULL
    return JSONObject().put("at", at).put("outcome", prefs.getString("system_start_outcome", null) ?: JSONObject.NULL)
      .put("reason", prefs.getString("system_start_reason", null) ?: JSONObject.NULL)
  }

  private fun startLocked(): String {
    requireProductionEnabled(); val activeConfig = checkNotNull(config); check(ruleBundleCurrent()) { "ApolloSG's Threat Domain List is missing or out of date" }
    check(VpnService.prepare(context) == null) { "VPN consent is not granted" }
    val activeEngine = checkNotNull(engine)
    // Controlled endpoint binding: attempt when configured, but NOT fatal on failure.
    // Physical-device fix (2026-06, P1): on real carrier networks the BlockTest host
    // (apolloverify.harmonywellnessgroup.com.au) may fail DNS resolution, return a CDN
    // IP, or time out. Previously this threw and aborted the entire start — even though
    // the VPN service's own off-thread binding check would have gracefully fallen back to
    // Website Gate-only mode (establishWithoutBlockTest). Now: succeed → authorize M1;
    // fail → log + proceed, the service handles the fallback to M2 Website Gate-only.
    if (activeConfig.hasControlledEndpoint) {
      try {
        val binding = ControlledEndpointResolver(activeConfig.vpn(), GuardDogVpnRuntime.resolver).verifyBinding()
        when (binding) {
          is BindingResult.Match -> {
            val auth = activeEngine.authorizeControlledTarget(activeConfig.controlledHost!!, binding.ipv4)
            if (auth !is BlockAuthorization.Authorized) {
              android.util.Log.w("GuardDogProd", "BlockTest authorized but rules rejected it; Website Gate-only protection will start")
            }
          }
          is BindingResult.Mismatch -> android.util.Log.w("GuardDogProd", "BlockTest DNS/IP mismatch (expected ${binding.expected}, resolved ${binding.resolved}); Website Gate-only protection will start")
          is BindingResult.ResolutionFailed -> android.util.Log.w("GuardDogProd", "BlockTest host did not resolve (${binding.host}); Website Gate-only protection will start")
        }
      } catch (e: Exception) {
        android.util.Log.w("GuardDogProd", "BlockTest binding check failed: ${e.message}; Website Gate-only protection will start")
      }
    }
    val upstream = checkNotNull(networkObserver.currentIpv4Dns()) { "No physical-network IPv4 DNS resolver is currently available" }
    observedUpstreamDns = upstream
    GuardDogVpnRuntime.config = activeConfig.vpn(); GuardDogVpnRuntime.reporter = reporter
    GuardDogVpnRuntime.websiteGateEngine = activeEngine; GuardDogVpnRuntime.websiteGateRouteConfig = WebsiteGateAddressing.defaultRouteConfig()
    GuardDogVpnRuntime.upstreamDnsResolverIpv4 = upstream; GuardDogVpnRuntime.websiteGateBindingLifetimeMillis = 30_000L
    GuardDogVpnRuntime.websiteGateOverrideStore = websiteGateOverrides
    // Stage 3: Enable live reputation checking with authenticated requests
    val liveBackend = backendBaseUrl()
    GuardDogVpnRuntime.liveReputationBackendUrl = liveBackend
    GuardDogVpnRuntime.liveReputationAuthToken = deviceToken()
    // Stage 3: Rule refresher — invoked by the DNS handler when a live check discovers a new
    // malicious hostname. Uses hotRefreshRules() to apply the updated bundle without stopping
    // the VPN — avoids deadlocking the DNS processing thread.
    GuardDogVpnRuntime.liveReputationRuleRefresher = Runnable {
      try { hotRefreshRules() } catch (_: Throwable) { /* fail-open: arm() will fail and DNS is forwarded */ }
    }
    GuardDogVpnRuntime.dnsThreatObservedListener = DnsThreatObservedListener { observation ->
      try { dnsThreatInbox.append(observation) } catch (_: Throwable) { dnsThreatInbox.reportFailure("DNS threat observation persistence failed") }
    }
    check(prefs.edit().putBoolean("requested", true).putString("since", prefs.getString("since", null) ?: Instant.now().toString()).commit())
    context.startForegroundService(Intent(context, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_START))
    if (!transitions.await(8_000) { actualOperational() }) { context.startService(Intent(context, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_STOP)); error("Production GuardDog start timed out") }
    return statusLocked()
  }

  fun stop(): String = transitions.serialized { stopLocked() }
  private fun stopLocked(clearIntent: Boolean = true): String {
    context.startService(Intent(context, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_STOP))
    if (clearIntent) prefs.edit().putBoolean("requested", false).remove("since").commit()
    if (!transitions.await(8_000) { RecoveryInspector.inspect(context, state).recovered }) error("Production GuardDog stop timed out")
    engine?.clearAuthorization(); engine?.clearWebsiteGateBindings(); detachRuntime(); return statusLocked(false)
  }

  fun enforceExpiry(): String = transitions.serialized {
    if (!ruleBundleCurrent() && ownsEnforcement()) stopLocked() else statusLocked()
  }
  fun ownsEnforcement(): Boolean = prefs.getBoolean("requested", false) || state.current().state in setOf(ProtectionState.STARTING, ProtectionState.ACTIVE)
  private fun ruleBundleCurrent(now: Instant = Instant.now()): Boolean {
    val bundleExpiry = acceptedBundleExpiresAt ?: return false
    return now.isBefore(bundleExpiry) && engine?.acceptedBundle() != null
  }
  /**
   * Physical-device fix (2026-06, P1 Android VPN failure): when the BlockTest controlled endpoint
   * (`apolloverify.harmonywellnessgroup.com.au`) does not resolve on a physical network (carrier DNS
   * filtering, DNS hijacking, or the endpoint is simply unreachable), `GuardDogVpnService` correctly
   * falls back to `establishWithoutBlockTest()`, which starts the M2 Website Gate DNS/sinkhole
   * pipeline WITHOUT an M1 `PacketDropReporter`. The previous `actualOperational()` required BOTH
   * `dropReporterAttached` (M1) AND `websiteGateActive` (M2), so it returned false in Website
   * Gate-only mode — causing `startLocked()` to time out after 8 seconds and KILL the working VPN.
   *
   * Fix: at least ONE enforcement mechanism (M1 drop reporter OR M2 Website Gate) must be active.
   * Both fields remain truthfully reported in [statusLocked] — this change only affects the
   * operational DERIVATION, not the raw observations.
   */
  private fun actualOperational(): Boolean {
    val runtime = RecoveryInspector.inspect(context, state)
    // At least one enforcement pipeline must be active:
    // - M1: PacketDropReporter (controlled endpoint /32 route packet matching)
    // - M2: Website Gate (DNS sinkhole pipeline)
    val enforcing = runtime.dropReporterAttached || GuardDogVpnRuntime.websiteGateActive
    return ruleBundleCurrent() &&
      state.current().state == ProtectionState.ACTIVE &&
      runtime.tunOpen &&
      runtime.selectiveRouteActive &&
      enforcing
  }

  fun status(): String = transitions.serialized { if (!ruleBundleCurrent() && ownsEnforcement()) stopLocked() else statusLocked() }
  private fun statusLocked(recheckAuthority: Boolean = true): String {
    val runtime = RecoveryInspector.inspect(context, state); val operational = actualOperational(); val requested = prefs.getBoolean("requested", false); val inboxState = inbox.status()
    val bundleVersion = engine?.acceptedBundle()?.bundleVersion
    val systemStartFailure = if (prefs.getString("system_start_outcome", null) == "failed") prefs.getString("system_start_reason", null) else null
    val reason = when {
      acceptedBundleExpiresAt == null -> "ApolloSG hasn't received its Threat Domain List yet"; recheckAuthority && !ruleBundleCurrent() -> "ApolloSG's Threat Domain List is out of date"
      !operational && systemStartFailure != null -> "Android asked ApolloSG to reconnect its protection (Always-on VPN) and it couldn't: $systemStartFailure"
      requested && !GuardDogVpnRuntime.websiteGateActive && !runtime.dropReporterAttached -> "No enforcement pipeline is active (neither Website Gate DNS nor controlled endpoint packet filter)"
      requested && !operational -> "TUN/route observations are incomplete"; else -> null }
    // Android only answers these for the app whose VPN is currently connected, so they are read
    // while Apollo's tunnel is up and are otherwise unknown (null) — never "off".
    val alwaysOn: Any = if (operational) ApolloVpnSystemState.alwaysOn() ?: JSONObject.NULL else JSONObject.NULL
    val lockdown: Any = if (operational) ApolloVpnSystemState.lockdown() ?: JSONObject.NULL else JSONObject.NULL
    return JSONObject().put("running", operational).put("requested", requested).put("operational", operational).put("enforcementMethod", "packet_filter")
      .put("coverage", "GuardDog production Website Gate: plaintext IPv4 DNS is inspected; exact-host blocks use short-lived sinkhole /32 routes. Private DNS, DoH, DoT, QUIC and IPv6 are outside this source claim.")
      .put("coverageScope", JSONArray().put("dns:ipv4-udp-53").put("ip:controlled-/32").put("ip:website-gate-sinkhole-/32"))
      .put("lastVerified", if (operational) Instant.now().toString() else JSONObject.NULL).put("degradedReason", reason ?: JSONObject.NULL)
      .put("visibility", if (operational) "full" else "none").put("since", prefs.getString("since", null) ?: JSONObject.NULL)
      .put("adapterLabel", LABEL).put("checkedAt", Instant.now().toString()).put("productionAuthority", true)
      .put("bundleVersion", bundleVersion ?: JSONObject.NULL).put("ruleExpiresAt", acceptedBundleExpiresAt?.toString() ?: JSONObject.NULL)
      .put("threatDomainEntryCount", engine?.acceptedBundle()?.payload?.rules?.size ?: JSONObject.NULL)
      .put("nativeLifecycle", runtime.lifecycle)
      .put("tunOpen", runtime.tunOpen).put("selectiveRouteActive", runtime.selectiveRouteActive).put("dropReporterAttached", runtime.dropReporterAttached)
      .put("websiteGateConfigured", GuardDogVpnRuntime.websiteGateRouteConfig != null).put("dnsGatewayActive", GuardDogVpnRuntime.websiteGateActive)
      .put("upstreamDnsResolverIpv4", GuardDogVpnRuntime.upstreamDnsResolverIpv4 ?: JSONObject.NULL)
      .put("evidencePending", inboxState.pending).put("evidenceCapacity", inboxState.capacity).put("evidenceOverflow", inboxState.overflow)
      .put("evidencePersistenceError", inboxState.error ?: JSONObject.NULL)
      .put("dnsThreatObservations", dnsThreatInbox.status().let { JSONObject().put("pending", it.pending).put("capacity", it.capacity).put("error", it.error ?: JSONObject.NULL) })
      .put("privateDns", privateDnsStatus())
      .put("alwaysOn", alwaysOn).put("lockdown", lockdown).put("systemStart", systemStartJson())
      .toString()
  }

  fun capabilities(): String = JSONArray().put(JSONObject().put("id", "site_guard").put("title", "GuardDog production Website Gate")
    .put("status", if (actualOperational()) "active" else if (VpnService.prepare(context) == null) "inactive" else "permission_required")
    .put("detail", "Rollback-protected exact-host decisions with DNS sinkhole routing and packet-drop evidence.")).toString()
  fun analyzeUrl(url: String): String = transitions.serialized { val result = engine?.analyzeUrl(url)
    if (result == null) JSONObject().put("supported", false).put("verdict", "unknown").put("reasons", JSONArray().put("Production rules are unavailable for this URL.")).toString()
    else JSONObject().put("supported", true).put("verdict", result.verdict).put("reasons", JSONArray()).put("sanitizedUrl", result.sanitizedUrl).put("host", result.host).put("ruleId", result.ruleId ?: JSONObject.NULL).toString() }
  fun evidence(): String = "[${inbox.records().filter { runCatching { ApolloGuardDogEvidenceCorrelator.contractValid(jsonObject(JSONObject(it))) }.getOrDefault(false) }.joinToString(",")}]"
  fun acknowledgeEvidence(raw: String): String { val ids = JSONArray(raw); val count = inbox.acknowledge((0 until ids.length()).map { ids.getString(it) }.toSet()); return JSONObject().put("acknowledged", count).put("pending", inbox.status().pending).toString() }

  // ── DNS Threat Observations (separate from enforcement evidence) ──────────
  fun dnsThreatObservations(): String = dnsThreatInbox.records()
  fun acknowledgeDnsThreatObservations(raw: String): String {
    val ids = JSONArray(raw); val count = dnsThreatInbox.acknowledge((0 until ids.length()).map { ids.getString(it) }.toSet())
    return JSONObject().put("acknowledged", count).put("pending", dnsThreatInbox.status().pending).toString()
  }

  // ── Private DNS / DoH Gap Detection ──────────────────────────────────────
  fun privateDnsStatus(): JSONObject {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
      // LinkProperties' Private DNS reads exist from Android 9; below that Android reports nothing.
      return JSONObject().put("privateDnsActive", false).put("privateDnsServer", JSONObject.NULL).put("mode", "unsupported")
        .put("modeSource", JSONObject.NULL).put("bypassLevel", "unobservable").put("chromeDoH", "unobservable")
        .put("explanation", "This Android version doesn't report its Private DNS setting to apps.")
    }
    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
    // Read the PHYSICAL network. While Apollo's VPN is up, `activeNetwork` is Apollo's own tunnel,
    // whose LinkProperties describe the DNS server Apollo declared — not the person's setting.
    val physical = cm?.let { manager ->
      manager.allNetworks.firstOrNull { network ->
        val caps = manager.getNetworkCapabilities(network)
        caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
      }
    }
    val linkProps: LinkProperties? = physical?.let { cm?.getLinkProperties(it) }
    val privateDnsActive = linkProps?.isPrivateDnsActive ?: false
    // Android's own setting, when it lets Apollo read it (not a promised API, so null is normal).
    val setting = runCatching { Settings.Global.getString(context.contentResolver, "private_dns_mode") }.getOrNull()
      ?.takeIf { it in setOf("off", "opportunistic", "hostname") }
    val specifier = if (setting == "hostname") runCatching { Settings.Global.getString(context.contentResolver, "private_dns_specifier") }.getOrNull() else null
    val privateDnsServer = linkProps?.privateDnsServerName ?: specifier?.takeIf { it.isNotBlank() }
    val mode = PrivateDnsTruth.mode(setting, privateDnsActive, privateDnsServer, linkProps != null)
    // Chrome's internal DoH is unobservable (no API) and is reported as such separately.
    return JSONObject()
      .put("privateDnsActive", privateDnsActive)
      .put("privateDnsServer", privateDnsServer ?: JSONObject.NULL)
      .put("mode", mode)
      .put("modeSource", if (setting != null) "android_setting" else if (linkProps != null) "network_state" else JSONObject.NULL)
      .put("bypassLevel", PrivateDnsTruth.bypassLevel(mode))
      .put("chromeDoH", "unobservable")
      .put("explanation", PrivateDnsTruth.explanation(mode, privateDnsServer))
  }

  // ── Urgent rule refresh ──────────────────────────────────────────────────
  fun triggerUrgentRefresh(): String {
    val work = OneTimeWorkRequestBuilder<ApolloGuardDogRefreshWorker>()
      .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
    WorkManager.getInstance(context).enqueueUniqueWork("apollo-guarddog-urgent-refresh", ExistingWorkPolicy.REPLACE, work)
    return JSONObject().put("triggered", true).put("type", "urgent").toString()
  }

  fun recovery(): String { val result = RecoveryInspector.inspect(context, state); return JSONObject().put("lifecycle", result.lifecycle).put("tunOpen", result.tunOpen).put("selectiveRouteActive", result.selectiveRouteActive).put("vpnTransportPresent", result.vpnTransportPresent).put("routeCidr", result.routeCidr ?: JSONObject.NULL).put("dropReporterAttached", result.dropReporterAttached).put("recovered", result.recovered).toString() }

  private fun fetch(rawUrl: String): String { val connection = URL(rawUrl).openConnection() as HttpURLConnection; connection.connectTimeout = 15_000; connection.readTimeout = 20_000; connection.instanceFollowRedirects = false
    try { check(connection.responseCode == 200) { "rule update service returned ${connection.responseCode}" }; check((connection.contentLengthLong.takeIf { it >= 0 } ?: 0) <= 2_000_000)
      val bytes = connection.inputStream.use { input -> val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
        while (true) { val count = input.read(buffer); if (count < 0) break; check(output.size() + count <= 2_000_000) { "rule update exceeded size limit" }; output.write(buffer, 0, count) }; output.toByteArray() }
      return bytes.toString(Charsets.UTF_8)
    } finally { connection.disconnect() } }
  private fun scheduleExpiry(at: Instant) { val delay = Duration.between(Instant.now(), at).toMillis().coerceAtLeast(0); val work = OneTimeWorkRequestBuilder<ApolloGuardDogExpiryWorker>().setInitialDelay(delay, TimeUnit.MILLISECONDS).build(); WorkManager.getInstance(context).enqueueUniqueWork("apollo-guarddog-production-expiry", ExistingWorkPolicy.REPLACE, work) }
  private fun scheduleRefresh() { val work = PeriodicWorkRequestBuilder<ApolloGuardDogRefreshWorker>(2, TimeUnit.HOURS)
      .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
    WorkManager.getInstance(context).enqueueUniquePeriodicWork("apollo-guarddog-production-refresh", ExistingPeriodicWorkPolicy.UPDATE, work) }
  private fun requireProductionEnabled() { check(ApolloGuardDogProductionOwner.isEligible(context)) { "Production GuardDog authority is disabled in this build" } }
  private fun detachRuntime() { GuardDogVpnRuntime.reporter = null; GuardDogVpnRuntime.config = null; GuardDogVpnRuntime.websiteGateEngine = null
    GuardDogVpnRuntime.websiteGateRouteConfig = null; GuardDogVpnRuntime.upstreamDnsResolverIpv4 = null; GuardDogVpnRuntime.dnsThreatObservedListener = null
    GuardDogVpnRuntime.liveReputationBackendUrl = null; GuardDogVpnRuntime.liveReputationAuthToken = null; GuardDogVpnRuntime.liveReputationRuleRefresher = null }
  private fun onNetworkDnsChanged(upstream: String?) {
    if (upstream == observedUpstreamDns) return
    observedUpstreamDns = upstream
    if (!ownsEnforcement()) return
    // Only stop a tunnel that exists: asking a stopped service to stop is a background service start
    // Android refuses, and that refusal used to abort the restart below (e.g. network arriving after boot).
    runCatching { transitions.serialized {
      if (state.current().state in setOf(ProtectionState.STARTING, ProtectionState.ACTIVE)) stopLocked(clearIntent = false)
      if (upstream != null && ruleBundleCurrent()) startLocked()
    } }
      .onFailure { inbox.reportFailure("Production Website Gate stopped after a physical-network DNS change") }
  }
  fun resumeRequested(): String = transitions.serialized { if (prefs.getBoolean("requested", false)) startLocked() else statusLocked() }
  private fun jsonObject(body: JSONObject): Map<String, Any?> = body.keys().asSequence().associateWith { key -> jsonValue(body.get(key)) }
  private fun jsonValue(value: Any?): Any? = when (value) { is JSONObject -> jsonObject(value); is JSONArray -> (0 until value.length()).map { jsonValue(value.get(it)) }; JSONObject.NULL -> null; else -> value }
}

class ApolloGuardDogExpiryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result = runCatching {
    if (ApolloGuardDogProductionOwner.isEligible(applicationContext)) ApolloGuardDogProductionOwner.get(applicationContext).enforceExpiry()
    else applicationContext.startService(Intent(applicationContext, GuardDogVpnService::class.java).setAction(GuardDogVpnService.ACTION_STOP))
    Result.success()
  }.getOrElse { Result.failure() }
}

class ApolloGuardDogRefreshWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result = runCatching {
    if (!ApolloGuardDogProductionOwner.isEligible(applicationContext)) return Result.success()
    val result = JSONObject(ApolloGuardDogProductionOwner.get(applicationContext).refreshRules())
    if (result.optBoolean("accepted")) Result.success() else Result.failure()
  }.getOrElse { Result.retry() }
}
