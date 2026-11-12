package com.hucentai.apollosecurity

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.provider.Settings
import com.guarddog.core.protection.ProtectionState
import com.guarddog.vpn.VpnStateRepository
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

/**
 * ApolloSecurity — Android (Kotlin) security module.
 * GuardDog production is the sole enforcement engine. Legacy DNS-only and candidate
 * acceptance paths have been removed.
 */
class ApolloSecurityModule : Module() {
  private val ctx: Context get() = appContext.reactContext ?: throw IllegalStateException("No context")
  private val prefs get() = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
  private fun guardDogProduction(): ApolloGuardDogProductionRuntime = ApolloGuardDogProductionOwner.get(ctx)

  // Pending VPN-consent / call-screening-role requests. The AsyncFunctions store their Promise here
  // and OnActivityResult resolves it once the user actually responds to the system dialog.
  private var vpnConsentPromise: Promise? = null
  private var callRolePromise: Promise? = null

  companion object {
    private const val PREFS = "apollo_siteguard"
    private const val VPN_REQUEST_CODE = 0xA901
    private const val CALL_ROLE_REQUEST_CODE = 0xA902
  }

  override fun definition() = ModuleDefinition {
    Name("ApolloSecurity")
    Function("getGuardDogProductionCapabilities") { guardDogProduction().capabilities() }
    Function("getGuardDogProductionStatus") { guardDogProduction().status() }
    Function("configureGuardDogProduction") { json: String -> guardDogProduction().configure(json) }
    Function("setGuardDogDeviceToken") { token: String -> guardDogProduction().setDeviceToken(token) }
    Function("acceptGuardDogProductionRuleBundle") { json: String -> guardDogProduction().acceptBundle(json) }
    AsyncFunction("refreshGuardDogProductionRules") { guardDogProduction().refreshRules() }
    AsyncFunction("startGuardDogProduction") { guardDogProduction().start() }
    AsyncFunction("stopGuardDogProduction") { guardDogProduction().stop() }
    Function("analyzeGuardDogProductionUrl") { url: String -> guardDogProduction().analyzeUrl(url) }
    Function("getGuardDogProductionEvidence") { guardDogProduction().evidence() }
    Function("acknowledgeGuardDogProductionEvidence") { ids: String -> guardDogProduction().acknowledgeEvidence(ids) }
    Function("getGuardDogProductionRecovery") { guardDogProduction().recovery() }

    // ── DNS Threat Observations (separate pipeline from enforcement evidence) ──
    Function("getGuardDogDnsThreatObservations") { guardDogProduction().dnsThreatObservations() }
    Function("acknowledgeGuardDogDnsThreatObservations") { ids: String -> guardDogProduction().acknowledgeDnsThreatObservations(ids) }

    // ── Private DNS / DoH gap detection ──────────────────────────────────────
    Function("getGuardDogPrivateDnsStatus") { guardDogProduction().privateDnsStatus().toString() }

    // ── Urgent rule refresh (from Link Gate intelligence trigger) ─────────────
    Function("triggerGuardDogUrgentRefresh") { guardDogProduction().triggerUrgentRefresh() }

    // ── Production-dedicated OS observation methods ─────────────────────────
    // These provide the same OS-level facts as the legacy bridge functions but
    // derive VPN state from the GuardDog production runtime, never from
    // The production JS adapter calls only these.

    AsyncFunction("getGuardDogProductionNetworkStatus") {
      val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
      val caps = cm.getNetworkCapabilities(cm.activeNetwork)
      val type = when {
        caps == null -> "none"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
        else -> "other"
      }
      var wifiSecurity = if (type == "wifi") "unknown" else "n/a"
      if (type == "wifi" && android.os.Build.VERSION.SDK_INT >= 31) {
        val info = caps?.transportInfo as? android.net.wifi.WifiInfo
        wifiSecurity = when (info?.currentSecurityType) {
          android.net.wifi.WifiInfo.SECURITY_TYPE_OPEN, android.net.wifi.WifiInfo.SECURITY_TYPE_OWE -> "open"
          android.net.wifi.WifiInfo.SECURITY_TYPE_WEP -> "wep"
          android.net.wifi.WifiInfo.SECURITY_TYPE_PSK -> "wpa"
          android.net.wifi.WifiInfo.SECURITY_TYPE_SAE -> "wpa3"
          android.net.wifi.WifiInfo.SECURITY_TYPE_EAP, android.net.wifi.WifiInfo.SECURITY_TYPE_EAP_WPA3_ENTERPRISE -> "enterprise"
          null -> "unknown"
          else -> "unknown"
        }
      }
      val captive = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_CAPTIVE_PORTAL)
      val rawSsid = if (type == "wifi" && android.os.Build.VERSION.SDK_INT >= 31) (caps?.transportInfo as? android.net.wifi.WifiInfo)?.ssid else null
      val ssid = rawSsid?.trim('"')?.takeIf { it.isNotBlank() && it != "<unknown ssid>" }
      val networkObservable = caps != null
      // VPN state from GuardDog production runtime — never from the legacy DNS service.
      val productionState = VpnStateRepository.shared.current().state
      val vpnRunning = productionState == ProtectionState.ACTIVE
      JSONObject().put("connected", caps != null).put("type", type)
        .put("isInternetReachable", caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) ?: JSONObject.NULL)
        .put("inspectable", networkObservable).put("wifiSecurity", wifiSecurity)
        .put("captivePortal", captive ?: JSONObject.NULL).put("vpnActive", vpnRunning).put("ssid", ssid ?: JSONObject.NULL).put("checkedAt", now()).toString()
    }

    AsyncFunction("getGuardDogProductionProtectionPermissions") {
      val observedAt = now()
      val vpn = if (VpnService.prepare(ctx) == null) "granted" else "undetermined"
      val notificationsEnabled = androidx.core.app.NotificationManagerCompat.from(ctx).areNotificationsEnabled()
      val postGranted = if (android.os.Build.VERSION.SDK_INT >= 33)
        ctx.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED else true
      val notificationsState = when {
        notificationsEnabled && postGranted -> "granted"
        requestedAt("notifications") != null -> "denied"
        else -> "undetermined"
      }
      val listener = ApolloSmsListenerService.isEnabled(ctx)
      JSONArray().apply {
        put(perm("vpn_config", "Local VPN (selective packet filter)", vpn, true, "Lets Apollo enforce verified protection rules by selectively filtering network packets on this device. Only traffic matching validated threat rules is affected.", observedAt, enabled = vpn == "granted"))
        put(perm("notifications", "Notifications", notificationsState, notificationsState != "denied" || android.os.Build.VERSION.SDK_INT < 33, "Lets Apollo tell you when it barks.", observedAt, enabled = notificationsEnabled && postGranted))
        put(perm("network_filter", "Notification access (Text Gate)", if (listener) "granted" else "undetermined", true, "Lets Apollo read message notifications you allow so Text Gate can warn you. Apollo never reads SMS directly.", observedAt, enabled = listener))
        put(perm("accessibility", "Accessibility service", "not_applicable", false, "ApolloSG does not use an accessibility service.", observedAt, enabled = null, unavailableReason = "not_implemented"))
      }.toString()
    }

    AsyncFunction("requestGuardDogProductionProtectionPermission") { id: String, promise: Promise ->
      recordRequest(id)
      val observedAt = now()
      when (id) {
        "vpn_config" -> {
          val intent = VpnService.prepare(ctx)
          if (intent == null) {
            promise.resolve(perm("vpn_config", "Local VPN (selective packet filter)", "granted", true, "Granted.", observedAt, enabled = true).put("requestState", "already_granted").toString())
          } else {
            val activity = appContext.currentActivity
            if (activity == null) {
              promise.resolve(perm("vpn_config", "Local VPN (selective packet filter)", "undetermined", true, "Android could not open VPN consent (no active screen).", observedAt, enabled = false).put("requestState", "launch_failed").toString())
            } else {
              try {
                // Launch the system VPN-consent dialog FOR RESULT and wait for the user's response —
                // OnActivityResult resolves this promise with the real granted/denied outcome. (No
                // FLAG_ACTIVITY_NEW_TASK: that would break result delivery back to this activity.)
                vpnConsentPromise?.resolve(perm("vpn_config", "Local VPN (selective packet filter)", "undetermined", true, "Superseded by a newer request.", observedAt, enabled = false).put("requestState", "cancelled").toString())
                vpnConsentPromise = promise
                activity.startActivityForResult(intent, VPN_REQUEST_CODE)
              } catch (_: Exception) {
                vpnConsentPromise = null
                promise.resolve(perm("vpn_config", "Local VPN (selective packet filter)", "undetermined", true, "Android could not open VPN consent.", observedAt, enabled = false).put("requestState", "launch_failed").toString())
              }
            }
          }
        }
        "notifications" -> {
          val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
          try {
            appContext.currentActivity?.startActivity(intent) ?: ctx.startActivity(intent)
            promise.resolve(perm("notifications", "Notifications", "undetermined", true, "Notification settings opened. Apollo will check when you return.", observedAt, enabled = null).put("requestState", "system_ui_opened").toString())
          } catch (_: Exception) {
            promise.resolve(perm("notifications", "Notifications", "undetermined", true, "Android could not open notification settings.", observedAt, enabled = null).put("requestState", "launch_failed").toString())
          }
        }
        "network_filter" -> {
          val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
          try {
            appContext.currentActivity?.startActivity(intent) ?: ctx.startActivity(intent)
            promise.resolve(perm("network_filter", "Notification access (Text Gate)", "undetermined", true, "Notification access settings opened. Apollo will check when you return.", observedAt, enabled = null).put("requestState", "system_ui_opened").toString())
          } catch (_: Exception) {
            promise.resolve(perm("network_filter", "Notification access (Text Gate)", "undetermined", true, "Android could not open notification access settings.", observedAt, enabled = null).put("requestState", "launch_failed").toString())
          }
        }
        else -> promise.resolve(perm(id, id, "not_applicable", false, "ApolloSG does not request this permission on Android.", observedAt, enabled = null, unavailableReason = "not_implemented").put("requestState", "unsupported").toString())
      }
    }

    // Resolve the pending VPN-consent / call-screening-role request when the user responds.
    OnActivityResult { _, payload ->
      if (payload.requestCode == VPN_REQUEST_CODE) {
        val pending = vpnConsentPromise
        vpnConsentPromise = null
        if (pending != null) {
          val observedAt = now()
          val granted = VpnService.prepare(ctx) == null
          pending.resolve(perm("vpn_config", "Local VPN (selective packet filter)", if (granted) "granted" else "undetermined", true, if (granted) "VPN consent granted." else "VPN consent was declined.", observedAt, enabled = granted).put("requestState", if (granted) "granted" else "denied").toString())
        }
      } else if (payload.requestCode == CALL_ROLE_REQUEST_CODE) {
        val pending = callRolePromise
        callRolePromise = null
        if (pending != null) {
          val held = ApolloCallScreeningService.isRoleHeld(ctx)
          pending.resolve(JSONObject().put("opened", true).put("held", held).toString())
        }
      }
    }


    // Real device facts for investigation guidance (manufacturer/model/OS/form factor). No inference from screen width.
    AsyncFunction("getDeviceProfileFacts") {
      val cfg = ctx.resources.configuration
      val pm = ctx.packageManager
      val formFactor = when {
        pm.hasSystemFeature("android.hardware.type.pc") -> "desktop"
        pm.hasSystemFeature("android.software.leanback") -> "unknown"
        cfg.smallestScreenWidthDp >= 600 -> "tablet"
        else -> "phone"
      }
      JSONObject()
        .put("manufacturer", android.os.Build.MANUFACTURER)
        .put("model", android.os.Build.MODEL)
        .put("osVersion", platformVersion())
        .put("formFactor", formFactor)
        .put("locale", java.util.Locale.getDefault().toLanguageTag())
        .toString()
    }

    // Google's test phones (Firebase Test Lab, used by Play's pre-launch reports) set this system setting to "true".
    AsyncFunction("isGoogleTestLab") {
      Settings.System.getString(ctx.contentResolver, "firebase.test.lab") == "true"
    }

    // Phase A — Apps & Device (AppDeviceSdk contract). Real signals within package-visibility limits; see AppDeviceSignals.
    AsyncFunction("getAppDeviceCapabilities") { AppDeviceSignals(ctx).capabilitiesJson() }
    AsyncFunction("getInstalledAppAssessment") { nameOrPackage: String -> AppDeviceSignals(ctx).appAssessmentJson(nameOrPackage) }
    AsyncFunction("listInstalledApps") { AppDeviceSignals(ctx).installedLaunchableAppsJson() }
    // ── Call Gate / Text Gate on-demand pickers (sensitive runtime permissions) ──────────────
    // READ_CALL_LOG / READ_SMS are Google Play restricted permissions and are NOT declared by default
    // (plugins/withRestrictedPhonePermissions.js). When this build does not declare one, every call
    // below reports it as not declared and never reaches the system dialog or the provider.
    // When declared, the person grants it explicitly; JS polls hasRuntimePermission after requesting.
    AsyncFunction("hasRuntimePermission") { name: String ->
      val perm = runtimePermission(name)
      val declared = perm != null && isDeclared(perm)
      JSONObject()
        .put("granted", declared && perm != null && androidx.core.content.ContextCompat.checkSelfPermission(ctx, perm) == android.content.pm.PackageManager.PERMISSION_GRANTED)
        .put("declared", declared)
        .toString()
    }
    AsyncFunction("requestRuntimePermission") { name: String ->
      val perm = runtimePermission(name)
      val activity = appContext.currentActivity
      if (perm == null) JSONObject().put("requested", false).put("reason", "unsupported").toString()
      else if (!isDeclared(perm)) JSONObject().put("requested", false).put("reason", "not_declared").toString()
      else if (androidx.core.content.ContextCompat.checkSelfPermission(ctx, perm) == android.content.pm.PackageManager.PERMISSION_GRANTED) JSONObject().put("requested", false).put("granted", true).toString()
      else if (activity == null) JSONObject().put("requested", false).put("reason", "no_activity").toString()
      else { try { activity.requestPermissions(arrayOf(perm), 0xA910) } catch (_: Exception) {}; JSONObject().put("requested", true).toString() }
    }
    // Opt-in, local-only contact lookup. Caller ID is not authenticated by a saved contact.
    // Return only the matched contact's display name and photo URI; never upload the address book.
    AsyncFunction("lookupCallerContact") { number: String ->
      val permission = android.Manifest.permission.READ_CONTACTS
      if (!isDeclared(permission) || androidx.core.content.ContextCompat.checkSelfPermission(ctx, permission) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
        JSONObject().put("status", "permission_required").toString()
      } else if (number.length !in 3..32 || !number.any { it.isDigit() }) {
        JSONObject().put("status", "invalid").toString()
      } else {
        try {
          val uri = android.net.Uri.withAppendedPath(android.provider.ContactsContract.PhoneLookup.CONTENT_FILTER_URI, android.net.Uri.encode(number))
          val fields = arrayOf(android.provider.ContactsContract.PhoneLookup.DISPLAY_NAME, android.provider.ContactsContract.PhoneLookup.PHOTO_URI)
          ctx.contentResolver.query(uri, fields, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
              JSONObject().put("status", "matched")
                .put("name", cursor.getString(0) ?: "")
                .put("photoUri", cursor.getString(1) ?: JSONObject.NULL)
                .toString()
            } else JSONObject().put("status", "not_found").toString()
          } ?: JSONObject().put("status", "not_found").toString()
        } catch (_: Exception) {
          JSONObject().put("status", "error").toString()
        }
      }
    }
    AsyncFunction("listRecentCalls") { if (isDeclared(android.Manifest.permission.READ_CALL_LOG)) PhonePickers.recentCallsJson(ctx) else "[]" }
    AsyncFunction("listRecentSms") { if (isDeclared(android.Manifest.permission.READ_SMS)) PhonePickers.recentSmsJson(ctx) else "[]" }
    // "Calls Apollo screened" — only numbers Android handed to ApolloCallScreeningService. No permission needed.
    AsyncFunction("getScreenedCalls") { ApolloCallScreeningService.readScreenedCalls(ctx).toString() }
    AsyncFunction("clearScreenedCalls") { ApolloCallScreeningService.clearScreenedCalls(ctx); JSONObject().put("cleared", true).toString() }
    AsyncFunction("getRecentInstallEvents") { "[]" }        // no PACKAGE_ADDED receiver by design (would need broad visibility)
    AsyncFunction("getDeviceSecuritySignals") { AppDeviceSignals(ctx).deviceSignalsJson() }
    AsyncFunction("getRecentAppSecurityEvents") { "[]" }

    // Gate 2 — Text Guard. Two mechanisms:
    // 1. NotificationListenerService (ApolloSmsListenerService) — opt-in notification access
    //    for live message monitoring. Does NOT use READ_SMS.
    // 2. PhonePickers.recentSmsJson() — uses READ_SMS when the user explicitly grants it
    //    via the on-demand picker (Call Gate / Text Gate). This is a user-initiated action,
    //    not a background read.
    // `senderReputation` stays honestly unsupported (no number reputation source is wired).
    // Link checks and Share-to-Apollo already work regardless.
    AsyncFunction("getMessagingCapabilities") {
      val enabled = ApolloSmsListenerService.isEnabled(ctx)
      JSONObject()
        .put("smsFiltering", if (enabled) "supported" else "permission_required")
        .put("linkInterception", "supported")
        .put("senderReputation", "unsupported")
        .put("shareExtension", "supported")
        .put("notificationIntegration", if (enabled) "supported" else "permission_required")
        .toString()
    }
    // Protected inbox semantics: reading is non-destructive; acknowledge only exact IDs after durable submission.
    AsyncFunction("getRecentMessageSecurityEvents") { ApolloSmsListenerService.readQueue(ctx).toString() }
    AsyncFunction("acknowledgeMessageSecurityEvents") { idsJson: String ->
      val ids = JSONArray(idsJson); val values = mutableSetOf<String>()
      for (index in 0 until ids.length()) values.add(ids.optString(index))
      JSONObject().put("acknowledged", ApolloSmsListenerService.acknowledge(ctx, values)).toString()
    }
    AsyncFunction("configureTextBackgroundHandoff") { configJson: String ->
      val config = JSONObject(configJson)
      JSONObject().put("configured", ApolloSmsListenerService.configureHandoff(ctx, config.getString("backendUrl"), config.getString("deviceToken"))).toString()
    }
    AsyncFunction("openSmsListenerSettings") {
      val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      appContext.currentActivity?.startActivity(intent) ?: ctx.startActivity(intent)
      JSONObject().put("opened", true).toString()
    }
    // Text Guard local findings (ApolloLocalMessageAnalyzer results, encrypted, survive content expiry).
    AsyncFunction("getTextGuardLocalFindings") { ApolloSmsListenerService.readLocalFindings(ctx).toString() }
    AsyncFunction("acknowledgeTextGuardLocalFindings") { idsJson: String ->
      val ids = try { val arr = org.json.JSONArray(idsJson); (0 until arr.length()).map { arr.getString(it) }.toSet() } catch (_: Exception) { emptySet() }
      JSONObject().put("acknowledged", ApolloSmsListenerService.acknowledgeLocalFindings(ctx, ids)).toString()
    }

    // Call Guard (CallSdk contract). Real Android signal: RoleManager.ROLE_CALL_SCREENING held by
    // ApolloCallScreeningService — never a live call is read here, only role/list state.
    // `numberReputation` is always "supported": the actual lookup is backend-proxied
    // (POST /api/call/risk-check via services/phonerisk.py) and works regardless of native readiness;
    // /call/risk-check itself reports source="not_configured" honestly if no IPQS key is set.
    AsyncFunction("getCallProtectionCapabilities") {
      val held = ApolloCallScreeningService.isRoleHeld(ctx)
      JSONObject()
        .put("callScreening", if (held) "supported" else "permission_required")
        .put("callerIdentification", "unsupported")
        .put("numberReputation", "supported")
        .put("voicemailTranscript", "unsupported")
        .put("liveTranscript", "unsupported")
        .toString()
    }
    AsyncFunction("requestCallScreeningRole") { promise: Promise ->
      val rm = ctx.getSystemService(Context.ROLE_SERVICE) as? android.app.role.RoleManager
      val activity = appContext.currentActivity
      if (rm == null || !ApolloCallScreeningService.isRoleAvailable(ctx) || ApolloCallScreeningService.isRoleHeld(ctx) || activity == null) {
        promise.resolve(JSONObject().put("opened", false).put("held", ApolloCallScreeningService.isRoleHeld(ctx)).toString())
      } else {
        try {
          // Launch the call-screening role dialog FOR RESULT (no FLAG_ACTIVITY_NEW_TASK — that
          // prevents the dialog showing and breaks result delivery). Resolved in OnActivityResult.
          val intent = rm.createRequestRoleIntent(android.app.role.RoleManager.ROLE_CALL_SCREENING)
          callRolePromise?.resolve(JSONObject().put("opened", false).put("held", ApolloCallScreeningService.isRoleHeld(ctx)).toString())
          callRolePromise = promise
          activity.startActivityForResult(intent, CALL_ROLE_REQUEST_CODE)
        } catch (_: Exception) {
          callRolePromise = null
          promise.resolve(JSONObject().put("opened", false).put("held", ApolloCallScreeningService.isRoleHeld(ctx)).toString())
        }
      }
    }
    // Mailbox semantics — non-destructive read. Acknowledge individually after successful processing.
    AsyncFunction("getPendingCallLookups") { ApolloCallScreeningService.readPendingLookups(ctx).toString() }
    AsyncFunction("acknowledgeCallLookups") { json: String ->
      val arr = JSONArray(json)
      val numbers = (0 until arr.length()).map { arr.getString(it) }
      ApolloCallScreeningService.acknowledgePendingLookups(ctx, numbers)
      JSONObject().put("acknowledged", numbers.size).toString()
    }
    AsyncFunction("retryCallLookups") { json: String ->
      val arr = JSONArray(json)
      val numbers = (0 until arr.length()).map { arr.getString(it) }
      ApolloCallScreeningService.retryPendingLookup(ctx, numbers)
      JSONObject().put("retried", numbers.size).toString()
    }
    AsyncFunction("getCallBlockAllowList") { ApolloCallScreeningService.blockAllowJson(ctx).toString() }
    AsyncFunction("addCallListEntry") { json: String ->
      val body = JSONObject(json)
      val key = if (body.optString("kind") == "allow") "allow_numbers" else "block_numbers"
      ApolloCallScreeningService.addToSet(ctx, key, body.optString("number"))
      JSONObject().put("ok", true).toString()
    }
    AsyncFunction("removeCallListEntry") { json: String ->
      val body = JSONObject(json)
      val key = if (body.optString("kind") == "allow") "allow_numbers" else "block_numbers"
      ApolloCallScreeningService.removeFromSet(ctx, key, body.optString("number"))
      JSONObject().put("ok", true).toString()
    }
    AsyncFunction("markNumberRisky") { json: String ->
      ApolloCallScreeningService.markRisky(ctx, JSONObject(json).optString("number"))
      JSONObject().put("ok", true).toString()
    }
    // Repeat Caller Alert: a number found worth checking (on), or found clean on a later check (off).
    AsyncFunction("setNumberWorthChecking") { json: String ->
      val body = JSONObject(json)
      ApolloCallScreeningService.setWorthChecking(ctx, body.optString("number"), body.optBoolean("on", true))
      JSONObject().put("ok", true).toString()
    }

    // Live Caller ID — PIR server URL (iOS-only feature; Android stub for cross-platform parity).
    AsyncFunction("configurePirServerUrl") { _: String ->
      JSONObject().put("configured", false).put("reason", "android_not_applicable").toString()
    }
  }

  private fun platformVersion(): String = "Android ${android.os.Build.VERSION.RELEASE}"

  private fun evidenceJson(ev: EnforcementEvidence): JSONObject = JSONObject()
    .put("evidenceId", ev.evidenceId)
    .put("eventId", ev.eventId ?: JSONObject.NULL)
    .put("deviceId", ev.deviceId ?: JSONObject.NULL)
    .put("platform", ev.platform)
    .put("osVersion", ev.osVersion ?: JSONObject.NULL)
    .put("sdkVersion", ev.sdkVersion ?: JSONObject.NULL)
    .put("observedAt", ev.observedAt)
    .put("mechanism", ev.mechanism)
    .put("direction", ev.direction)
    .put("protocol", ev.protocol)
    .put("destination", JSONObject().put("ip", ev.destinationIp ?: JSONObject.NULL).put("domain", ev.destinationDomain ?: JSONObject.NULL).put("port", ev.destinationPort ?: JSONObject.NULL))
    .put("attribution", JSONObject().put("appId", ev.appId ?: JSONObject.NULL).put("processName", ev.processName ?: JSONObject.NULL).put("confidence", ev.attributionConfidence))
    .put("matchedRuleId", ev.matchedRuleId ?: JSONObject.NULL)
    .put("threatId", ev.threatId ?: JSONObject.NULL)
    .put("requestedAction", ev.requestedAction)
    .put("enforcedAction", ev.enforcedAction)
    .put("result", ev.result)
    .put("ruleSource", ev.ruleSource)
    .put("confidence", ev.confidence)
    .put("sourceMetadata", JSONObject())
    .put("correlationId", ev.correlationId ?: JSONObject.NULL)

  private fun perm(id: String, title: String, status: String, canAskAgain: Boolean, why: String, observedAt: String = now(), enabled: Boolean? = null, unavailableReason: String? = null): JSONObject {
    val requestedAt = requestedAt(id)
    return JSONObject().put("id", id).put("title", title).put("status", status).put("canAskAgain", canAskAgain).put("why", why)
      .put("requested", requestedAt != null).put("lastRequestedAt", requestedAt ?: JSONObject.NULL)
      .put("enabled", enabled ?: JSONObject.NULL).put("observedAt", observedAt).put("unavailableReason", unavailableReason ?: JSONObject.NULL)
  }

  private fun requestedAt(id: String): String? = prefs.getString("perm_requested_at_$id", null)
  private fun recordRequest(id: String) { prefs.edit().putString("perm_requested_at_$id", now()).apply() }

  private fun now(): String = Instant.now().toString()

  /** True only when this build's merged manifest actually requests [permission]. */
  private fun isDeclared(permission: String): Boolean = try {
    @Suppress("DEPRECATION")
    val info = ctx.packageManager.getPackageInfo(ctx.packageName, android.content.pm.PackageManager.GET_PERMISSIONS)
    info.requestedPermissions?.contains(permission) == true
  } catch (_: Exception) { false }

  /** Maps the JS picker permission key to the Android manifest permission (null = unsupported). */
  private fun runtimePermission(name: String): String? = when (name) {
    "call_log" -> android.Manifest.permission.READ_CALL_LOG
    "sms" -> android.Manifest.permission.READ_SMS
    "contacts" -> android.Manifest.permission.READ_CONTACTS
    else -> null
  }
}
