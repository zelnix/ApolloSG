package com.hucentai.apollosecurity

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.telecom.Call
import android.telecom.CallScreeningService
import android.telephony.PhoneNumberUtils
import android.telephony.TelephonyManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date
import java.time.Instant
import java.util.UUID

/**
 * ApolloCallScreeningService — Call Guard for Android.
 *
 * Truth model: this service NEVER listens to a call's audio and NEVER reads the system call log
 * beyond the one incoming number Android hands it. It only compares that number against three
 * on-device, person-controlled sets:
 *   - `block`     — numbers the person added themselves (deterministic, user_override).
 *   - `allow`     — numbers the person added themselves; always let these ring.
 *   - `autoRisky` — numbers THIS device previously looked up (via the backend's IPQualityScore
 *                   proxy — see services/phonerisk.py) and found to be high-risk. Per-device only;
 *                   nothing here is shared with other Apollo users in this build (see PRD).
 * A number in `block` or `autoRisky` causes a rejection REQUEST. Android supplies no separate
 * completion receipt here. The record is unverified and must never represent a packet drop.
 * Every other number rings completely
 * normally; Apollo never delays or silences a call based on a guess. Unknown numbers with no local
 * signal are queued (bounded, deduped) for the app to look up next time it's open — the 3rd-party
 * reputation lookup itself is too slow/unreliable to run inside this service's ~5 s response window.
 */
class ApolloCallScreeningService : CallScreeningService() {

  companion object {
    private const val PREFS = "apollo_callguard"
    private const val MODULE_VERSION = "apollo-security-1.0.0"
    private const val KEY_BLOCK = "block_numbers"
    private const val KEY_ALLOW = "allow_numbers"
    private const val KEY_AUTO_RISKY = "auto_risky_numbers"
    private const val KEY_PENDING = "pending_lookup_queue"
    private const val KEY_SEEN_PENDING = "seen_pending_numbers"
    private const val MAX_EVIDENCE = 50
    private const val MAX_PENDING = 20
    private const val MAX_SEEN_PENDING = 300

    private val evidenceLog = ArrayDeque<EnforcementEvidence>()
    fun recentEvidence(): List<EnforcementEvidence> = synchronized(evidenceLog) { evidenceLog.toList() }
    private fun recordEvidence(ev: EnforcementEvidence) = synchronized(evidenceLog) {
      evidenceLog.addLast(ev); while (evidenceLog.size > MAX_EVIDENCE) evidenceLog.removeFirst()
    }

    /** Digits and a leading '+' only — good enough for exact-match comparison without a full E.164 parse. */
    fun normalized(number: String?): String = (number ?: "").filter { it.isDigit() || it == '+' }

    /** E.164 canonicalization via Android's bundled PhoneNumberUtils + TelephonyManager country.
     * Returns empty string on failure — callers must guard against blank before storing, comparing, or queuing.
     * - Already-international numbers are structurally validated via formatNumberToE164.
     * - Local numbers require a resolvable device country; returns empty if country is unavailable.
     * - Uses networkCountryIso (preferred, nonblank) then simCountryIso (fallback, nonblank). */
    fun toE164(raw: String?, ctx: Context): String {
      val stripped = normalized(raw)
      if (stripped.length < 3) return ""  // too short for any valid phone number
      val tm = ctx.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
      // Resolve country: prefer network ISO when nonblank, fall back to SIM ISO when nonblank.
      val iso = tm?.networkCountryIso?.takeIf { it.isNotBlank() }
        ?: tm?.simCountryIso?.takeIf { it.isNotBlank() }
      if (stripped.startsWith("+")) {
        // Already international — still validate structurally via the platform.
        // formatNumberToE164 parses + numbers correctly regardless of the country hint.
        val hint = iso?.uppercase() ?: "US"
        return PhoneNumberUtils.formatNumberToE164(stripped, hint) ?: ""
      }
      // Local number: country context is required for canonicalization.
      if (iso.isNullOrBlank()) return ""
      return PhoneNumberUtils.formatNumberToE164(stripped, iso.uppercase()) ?: ""
    }

    fun isRoleHeld(ctx: Context): Boolean {
      val rm = ctx.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
      return try { rm.isRoleHeld(RoleManager.ROLE_CALL_SCREENING) } catch (_: Exception) { false }
    }
    fun isRoleAvailable(ctx: Context): Boolean {
      val rm = ctx.getSystemService(Context.ROLE_SERVICE) as? RoleManager ?: return false
      return try { rm.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING) } catch (_: Exception) { false }
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    fun loadSet(ctx: Context, key: String): Set<String> = prefs(ctx).getStringSet(key, emptySet()) ?: emptySet()
    fun addToSet(ctx: Context, key: String, number: String) {
      val e164 = toE164(number, ctx); if (e164.isBlank()) return
      val set = loadSet(ctx, key).toMutableSet(); set.add(e164)
      prefs(ctx).edit().putStringSet(key, set).apply()
    }
    fun removeFromSet(ctx: Context, key: String, number: String) {
      val e164 = toE164(number, ctx); if (e164.isBlank()) return
      val set = loadSet(ctx, key).toMutableSet(); set.remove(e164)
      prefs(ctx).edit().putStringSet(key, set).apply()
    }
    @Synchronized
    fun markRisky(ctx: Context, number: String) {
      addToSet(ctx, KEY_AUTO_RISKY, number)
      val e164 = toE164(number, ctx); if (e164.isBlank()) return
      writeMarks(ctx, RepeatCallerAlert.withHighRisk(readMarks(ctx), e164, System.currentTimeMillis()))
    }

    // ── Repeat Caller Alert ────────────────────────────────────────────────────────────────────
    // When Apollo found a number high-risk or worth checking — {e164: {level, at}}, kept for 30 days — so a call from
    // it in that time raises an alert. Block-list numbers alert on every call. See RepeatCallerAlert.
    private const val KEY_RISK_MARKS = "risk_marks"
    private const val ALERTS_CHANNEL = "apollo_alerts"
    private const val REPEAT_NOTIFICATION_BASE_ID = 7_300_000

    @Synchronized
    fun readMarks(ctx: Context): Map<String, RepeatCallerAlert.Mark> {
      val raw = prefs(ctx).getString(KEY_RISK_MARKS, null) ?: return emptyMap()
      val obj = try { JSONObject(raw) } catch (_: Exception) { return emptyMap() }
      val out = mutableMapOf<String, RepeatCallerAlert.Mark>()
      for (key in obj.keys()) {
        val m = obj.optJSONObject(key) ?: continue
        out[key] = RepeatCallerAlert.Mark(m.optString("level"), m.optLong("at", 0L))
      }
      return out
    }

    @Synchronized
    private fun writeMarks(ctx: Context, marks: Map<String, RepeatCallerAlert.Mark>) {
      val obj = JSONObject()
      RepeatCallerAlert.prune(marks, System.currentTimeMillis()).forEach { (n, m) -> obj.put(n, JSONObject().put("level", m.level).put("at", m.atMs)) }
      prefs(ctx).edit().putString(KEY_RISK_MARKS, obj.toString()).apply()
    }

    /** A number found worth checking (on), or found clean on a later check (off). */
    @Synchronized
    fun setWorthChecking(ctx: Context, number: String, on: Boolean) {
      val e164 = toE164(number, ctx); if (e164.isBlank()) return
      writeMarks(ctx, RepeatCallerAlert.withWorthChecking(readMarks(ctx), e164, on, e164 in loadSet(ctx, KEY_AUTO_RISKY), System.currentTimeMillis()))
    }

    /** The Repeat Caller Alert for this call, handed to Android now (with whether it will show), or null. */
    private fun repeatCallerAlert(ctx: Context, number: String, outcome: String, at: Long): Pair<RepeatCallerAlert.Alert, Boolean>? {
      if (outcome == "allowed_by_you") return null
      val mark = readMarks(ctx)[number]
      val reason = RepeatCallerAlert.reasonFor(
        onBlockList = outcome == "rejection_requested_block",
        onAutoRejectList = outcome == "rejection_requested_risky",
        mark = mark, nowMs = at,
      ) ?: return null
      val foundOn = mark?.let { DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(it.atMs)) }
      val alert = RepeatCallerAlert.alertFor(reason, number, foundOn)
      return alert to postRepeatCallerNotification(ctx, number, alert, at)
    }

    /** True only when Android will show it: ApolloSG's notifications and its alerts category are both on. */
    private fun postRepeatCallerNotification(ctx: Context, number: String, alert: RepeatCallerAlert.Alert, at: Long): Boolean {
      val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return false
      if (!NotificationManagerCompat.from(ctx).areNotificationsEnabled()) return false
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        val channel = nm.getNotificationChannel(ALERTS_CHANNEL)
          ?: NotificationChannel(ALERTS_CHANNEL, "Apollo alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "All ApolloSG scam protection alerts, warnings, and notifications."
          }.also { nm.createNotificationChannel(it) }
        if (channel.importance == NotificationManager.IMPORTANCE_NONE) return false
      }
      // Tapping opens Check a number on this number, which checks it again with the earlier result above today's.
      val open = Intent(Intent.ACTION_VIEW, Uri.parse("apollo://call-guard?number=${Uri.encode(number)}&repeat=$at"))
        .setPackage(ctx.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      val id = REPEAT_NOTIFICATION_BASE_ID + (at % 100_000).toInt()
      val tap = PendingIntent.getActivity(ctx, id, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
      // On a locked screen: that a repeat caller rang, without the number.
      val locked = NotificationCompat.Builder(ctx, ALERTS_CHANNEL).setSmallIcon(ctx.applicationInfo.icon)
        .setContentTitle("ApolloSG: a repeat caller").setContentText("Unlock to see the number.").build()
      val notification = NotificationCompat.Builder(ctx, ALERTS_CHANNEL)
        .setSmallIcon(ctx.applicationInfo.icon)
        .setContentTitle(alert.title)
        .setContentText(alert.body)
        .setStyle(NotificationCompat.BigTextStyle().bigText(alert.body))
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
        .setPublicVersion(locked)
        .setAutoCancel(true)
        .setContentIntent(tap)
        .build()
      nm.notify(id, notification)
      return true
    }

    fun blockAllowJson(ctx: Context): JSONObject = JSONObject()
      .put("block", JSONArray(loadSet(ctx, KEY_BLOCK).toList()))
      .put("allow", JSONArray(loadSet(ctx, KEY_ALLOW).toList()))
      .put("autoRisky", JSONArray(loadSet(ctx, KEY_AUTO_RISKY).toList()))

    // ── "Calls Apollo screened" ────────────────────────────────────────────────────────────────
    // A short, on-phone history built ONLY from the incoming numbers Android itself hands to
    // onScreenCall while Apollo holds the call-screening role. Never read from the system call log.
    // Bounded to MAX_SCREENED entries and SCREENED_RETENTION_MS; cleared by the app on request and by
    // "Delete My ApolloSG Data".
    private const val KEY_SCREENED = "screened_calls"
    private const val MAX_SCREENED = 50
    private const val SCREENED_RETENTION_MS = 30L * 24 * 60 * 60 * 1000

    /** Newest first: [{number (E.164), at (epoch ms), outcome}]. Entries past retention are dropped. */
    @Synchronized
    fun readScreenedCalls(ctx: Context): JSONArray {
      val p = prefs(ctx)
      val raw = p.getString(KEY_SCREENED, null) ?: return JSONArray()
      val all = try { JSONArray(raw) } catch (_: Exception) { return JSONArray() }
      val cutoff = System.currentTimeMillis() - SCREENED_RETENTION_MS
      val live = JSONArray()
      for (i in 0 until all.length()) {
        val entry = all.optJSONObject(i) ?: continue
        if (entry.optLong("at", 0L) >= cutoff && entry.optString("number").isNotBlank()) live.put(entry)
      }
      if (live.length() != all.length()) p.edit().putString(KEY_SCREENED, live.toString()).apply()
      return live
    }

    @Synchronized
    fun clearScreenedCalls(ctx: Context) { prefs(ctx).edit().remove(KEY_SCREENED).apply() }

    @Synchronized
    private fun recordScreenedCall(ctx: Context, number: String, outcome: String, verification: String) {
      if (number.isBlank()) return
      val at = System.currentTimeMillis()
      val entry = JSONObject().put("number", number).put("at", at).put("outcome", outcome)
      // A Repeat Caller Alert is raised here, after the screening answer, and noted on the entry with whether it showed.
      try {
        repeatCallerAlert(ctx, number, outcome, at)?.let { (alert, shown) ->
          entry.put("repeat", alert.reason.wire).put("alert", if (shown) "shown" else "not_shown").put("alertTitle", alert.title).put("alertBody", alert.body)
        }
      } catch (_: Exception) { }
      val existing = readScreenedCalls(ctx)
      val next = JSONArray().put(entry)
      for (i in 0 until minOf(existing.length(), MAX_SCREENED - 1)) next.put(existing.get(i))
      prefs(ctx).edit().putString(KEY_SCREENED, next.toString()).apply()
    }

    /** Before Android 10 the screening service was only bound for incoming calls; from 10 on, ask the call. */
    private fun isIncoming(details: Call.Details): Boolean {
      if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) return details.callDirection == Call.Details.DIRECTION_INCOMING
      return true
    }

    private const val MAX_RETRY_ATTEMPTS = 4

    /** Numbers seen ringing with no local signal — non-destructive read.
     * Auto-purges entries that have exceeded [MAX_RETRY_ATTEMPTS].
     * Caller must acknowledge individual numbers after successful processing via [acknowledgePendingLookups]
     * or mark them failed via [retryPendingLookup]. */
    fun readPendingLookups(ctx: Context): JSONArray {
      val p = prefs(ctx)
      val raw = p.getString(KEY_PENDING, null) ?: return JSONArray()
      val queue = try { JSONArray(raw) } catch (_: Exception) { return JSONArray() }
      val live = JSONArray()
      var purged = false
      for (i in 0 until queue.length()) {
        val entry = queue.optJSONObject(i) ?: continue
        if (entry.optInt("attempts", 0) >= MAX_RETRY_ATTEMPTS) { purged = true; continue }
        live.put(entry)
      }
      if (purged) {
        if (live.length() == 0) p.edit().remove(KEY_PENDING).apply()
        else p.edit().putString(KEY_PENDING, live.toString()).apply()
      }
      return live
    }

    /** Remove successfully processed numbers from the pending queue.
     * Acknowledged numbers are added to [KEY_SEEN_PENDING] so future calls from the same number
     * are not re-queued (until the seen set is trimmed by [MAX_SEEN_PENDING]). */
    fun acknowledgePendingLookups(ctx: Context, numbers: List<String>) {
      if (numbers.isEmpty()) return
      val p = prefs(ctx)
      val raw = p.getString(KEY_PENDING, null) ?: return
      val queue = try { JSONArray(raw) } catch (_: Exception) { return }
      val ackSet = numbers.toSet()
      val remaining = JSONArray()
      for (i in 0 until queue.length()) {
        val entry = queue.optJSONObject(i) ?: continue
        if (entry.optString("number") !in ackSet) remaining.put(entry)
      }
      // Mark acknowledged numbers as "seen" — prevents re-queuing on future calls from the same number.
      val seen = (p.getStringSet(KEY_SEEN_PENDING, emptySet()) ?: emptySet()).toMutableSet()
      seen.addAll(ackSet)
      val trimmedSeen = if (seen.size > MAX_SEEN_PENDING) seen.toList().takeLast(MAX_SEEN_PENDING).toSet() else seen
      val editor = p.edit()
      if (remaining.length() == 0) editor.remove(KEY_PENDING) else editor.putString(KEY_PENDING, remaining.toString())
      editor.putStringSet(KEY_SEEN_PENDING, trimmedSeen).apply()
    }

    /** Increment the retry counter for numbers that failed processing. Entries exceeding
     * [MAX_RETRY_ATTEMPTS] are purged on the next [readPendingLookups] call. */
    fun retryPendingLookup(ctx: Context, numbers: List<String>) {
      if (numbers.isEmpty()) return
      val p = prefs(ctx)
      val raw = p.getString(KEY_PENDING, null) ?: return
      val queue = try { JSONArray(raw) } catch (_: Exception) { return }
      val retrySet = numbers.toSet()
      val updated = JSONArray()
      for (i in 0 until queue.length()) {
        val entry = queue.optJSONObject(i) ?: continue
        if (entry.optString("number") in retrySet) {
          entry.put("attempts", entry.optInt("attempts", 0) + 1)
        }
        updated.put(entry)
      }
      p.edit().putString(KEY_PENDING, updated.toString()).apply()
    }

    private fun queuePendingLookup(ctx: Context, number: String) {
      if (number.isBlank()) return
      val p = prefs(ctx)
      // Dedup: check the pending queue itself, not KEY_SEEN_PENDING (which is written only on ack).
      val queue = try { JSONArray(p.getString(KEY_PENDING, null) ?: "[]") } catch (_: Exception) { JSONArray() }
      for (i in 0 until queue.length()) {
        if (queue.optJSONObject(i)?.optString("number") == number) return
      }
      // Also skip if this number was successfully processed recently.
      val seen = p.getStringSet(KEY_SEEN_PENDING, emptySet()) ?: emptySet()
      if (number in seen) return
      queue.put(JSONObject().put("number", number).put("seenAtMs", System.currentTimeMillis()).put("attempts", 0))
      val trimmed = if (queue.length() > MAX_PENDING) {
        val arr = JSONArray(); for (i in (queue.length() - MAX_PENDING) until queue.length()) arr.put(queue.get(i)); arr
      } else queue
      // Do NOT add to KEY_SEEN_PENDING here — that happens only on successful acknowledgement.
      p.edit().putString(KEY_PENDING, trimmed.toString()).apply()
    }
  }

  override fun onScreenCall(callDetails: Call.Details) {
    val ctx = applicationContext
    // What to add to "Calls Apollo screened" — decided alongside the response, written only afterwards.
    var screened: Pair<String, String>? = null
    // Carrier-provided number attestation, not proof of a business identity.
    val numberVerification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      try { when (callDetails.callerNumberVerificationStatus) {
        android.telecom.Connection.VERIFICATION_STATUS_PASSED -> "passed"
        android.telecom.Connection.VERIFICATION_STATUS_FAILED -> "failed"
        else -> "not_verified"
      } } catch (_: Exception) { "unavailable" }
    } else "unavailable"
    try {
      val number = toE164(callDetails.handle?.schemeSpecificPart, ctx)
      if (number.isBlank()) { respond(callDetails, disallow = false, reject = false); return }
      if (number in loadSet(ctx, KEY_ALLOW)) { respond(callDetails, disallow = false, reject = false); screened = number to "allowed_by_you"; return }

      val block = loadSet(ctx, KEY_BLOCK)
      val risky = loadSet(ctx, KEY_AUTO_RISKY)
      if (number in block || number in risky) {
        respond(callDetails, disallow = true, reject = true, skipNotification = true)
        screened = number to (if (number in block) "rejection_requested_block" else "rejection_requested_risky")
        // Record evidence honestly: a rejection REQUEST was issued but Android provides no completion
        // receipt confirming the call was actually blocked. The evidence is "rejection_requested",
        // not "verified" — the caller may still reach voicemail or the system may override the request.
        recordEvidence(EnforcementEvidence.verifiedCallBlock(
          evidenceId = UUID.randomUUID().toString(), observedAt = Instant.now().toString(), number = number,
          ruleSource = if (number in block) "user_override" else "cloud_intel",
          osVersion = "Android ${android.os.Build.VERSION.RELEASE}", sdkVersion = MODULE_VERSION,
        ).copy(result = "rejection_requested", enforcedAction = "reject_requested", destinationDomain = null, matchedRuleId = "call_local_rule"))
        return
      }
      // No local signal at all — let it ring normally, and queue for a background reputation lookup.
      // A5: For numbers with no local signal, we still allow the call to ring (no silencing by default).
      // Silencing unidentified callers is a device-level setting (Android: Settings → Phone → Caller ID
      // & spam → "Filter spam calls"; iOS: Settings → Phone → Silence Unknown Callers) that the person
      // controls independently. Apollo does not claim silencing as its own action and preserves the
      // missed-call record (setSkipCallLog=false) so the person can review and check the number later.
      respond(callDetails, disallow = false, reject = false)
      screened = number to "rang"
      queuePendingLookup(ctx, number)
    } catch (_: Exception) {
      // Never let a screening failure hang up a real call — always fall through to allow.
      respond(callDetails, disallow = false, reject = false)
    } finally {
      // History, and any Repeat Caller Alert, are written only after Android already has its answer, inside their own
      // guard, so they can never delay, change or fail the screening decision above.
      screened?.let { (number, outcome) ->
        try { if (isIncoming(callDetails)) recordScreenedCall(ctx, number, outcome, numberVerification) } catch (_: Exception) { }
      }
    }
  }

  private fun respond(details: Call.Details, disallow: Boolean, reject: Boolean, skipNotification: Boolean = false) {
    val response = CallResponse.Builder()
      .setDisallowCall(disallow)
      .setRejectCall(reject)
      .setSkipNotification(skipNotification)
      .setSkipCallLog(false)
      .build()
    respondToCall(details, response)
  }
}
