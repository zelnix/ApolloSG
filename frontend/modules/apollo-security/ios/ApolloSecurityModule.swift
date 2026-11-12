import CallKit
import Contacts
import ExpoModulesCore
import LocalAuthentication
import Network
import NetworkExtension
import SafariServices
import UIKit
import UserNotifications

/// ApolloSecurity — iOS (Swift) security module.
/// Site Guard = Safari Content Blocker extension (ApolloContentBlocker). The app
/// writes rules to the shared App Group and asks Safari to reload the blocker.
/// A block is "verified" only when the reload succeeds AND the extension is
/// enabled in Settings › Safari › Extensions. Nothing is inferred.
public class ApolloSecurityModule: Module {
  private let label = "iOS security module"
  /// Bumped whenever this module's observable behaviour changes. Mirrors ApolloDnsVpnService.MODULE_VERSION on Android.
  private let moduleVersion = "1.1.0"
  /// Last observed extension state + when it was observed. Never assumed; refreshed from SFContentBlockerManager.
  private var blockerEnabled: Bool? = nil
  private var blockerVerifiedAt: String? = nil
  private let transitionLock = NSLock()
  private var activeTransition: UUID? = nil

  /// Exactly what the Safari content blocker covers. Everything else is NOT covered and the UI says so.
  private let coverage = "Covers websites opened in Safari (and Safari View Controller inside other apps). Not covered: Chrome, Firefox and other browsers, in-app browsers that don't use Safari, and non-browser apps."
  private let coverageScope = ["browser:safari"]

  // Truth model: `requested` is the person's intent, persisted in the App Group so it survives relaunch.
  // `operational` is never stored — it is derived from the extension state each time it is reported.
  private var requestedKey: String { "apollo.siteguard.requested" }
  private var sinceKey: String { "apollo.siteguard.since" }
  private var requested: Bool {
    get { UserDefaults(suiteName: appGroup)?.bool(forKey: requestedKey) ?? false }
    set { UserDefaults(suiteName: appGroup)?.set(newValue, forKey: requestedKey) }
  }
  private var protectionSince: String? {
    get { UserDefaults(suiteName: appGroup)?.string(forKey: sinceKey) }
    set { UserDefaults(suiteName: appGroup)?.set(newValue, forKey: sinceKey) }
  }
  private var rulesWritten: Bool { listURL.map { FileManager.default.fileExists(atPath: $0.path) } ?? false }

  private var appBundleId: String { Bundle.main.bundleIdentifier ?? "" }
  private var blockerId: String { "\(appBundleId).contentblocker" }
  private var appGroup: String { "group.\(appBundleId).apollo" }
  private var listURL: URL? {
    FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?.appendingPathComponent("blockerList.json")
  }
  private var blockedKey: String { "apollo.siteguard.blocked" }
  private var messageEventsKey: String { "apollo.textguard.events.v1" }
  private var messageActivityKey: String { "apollo.textguard.lastObservedAt" }
  private var messageFilterObservedAt: String? { UserDefaults(suiteName: appGroup)?.string(forKey: messageActivityKey) }
  private var messageFilterRecentlyObserved: Bool {
    guard let value = messageFilterObservedAt, let date = ISO8601DateFormatter().date(from: value) else { return false }
    // B3: 30-day window is too stale to claim "currently filtering". Reduce to 72 hours: if the
    // extension hasn't processed a message in 3 days, report permission_required so the gate status
    // doesn't falsely claim active protection. The extension writes this timestamp on every process() call.
    return Date().timeIntervalSince(date) <= 72 * 60 * 60
  }

  // Call Guard — CXCallDirectoryExtension (ApolloCallDirectory), same App Group as Site Guard.
  // The extension only ever gets a STATIC list at reload time (Apple gives it no per-call callback,
  // unlike Android's CallScreeningService) — so `pendingLookups` can never be populated on iOS, and
  // `getEnforcementEvidence` must stay "[]" here too: Apple never reports back which entry, if any,
  // actually caused a block. See ApolloCallDirectory/CallDirectoryHandler.swift for what the
  // extension itself does with this list.
  private var callDirectoryId: String { "\(appBundleId).calldirectory" }
  private var callListURL: URL? {
    FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?.appendingPathComponent("callDirectory.json")
  }
  private func loadCallLists() -> [String: [String]] {
    guard let url = callListURL, let data = try? Data(contentsOf: url),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: [String]] else {
      return ["block": [], "allow": [], "autoRisky": []]
    }
    return ["block": obj["block"] ?? [], "allow": obj["allow"] ?? [], "autoRisky": obj["autoRisky"] ?? []]
  }
  private func saveCallLists(_ lists: [String: [String]]) -> Bool {
    let canonical = lists.mapValues { Array(Set($0.compactMap(canonicalPhoneNumber))).sorted() }
    guard let url = callListURL, let data = try? JSONSerialization.data(withJSONObject: canonical, options: [.sortedKeys]) else { return false }
    guard (try? data.write(to: url, options: .atomic)) != nil else { return false }
    let defaults = UserDefaults(suiteName: appGroup)
    defaults?.set((defaults?.integer(forKey: "apollo.callguard.listVersion") ?? 0) + 1, forKey: "apollo.callguard.listVersion")
    defaults?.set(now(), forKey: "apollo.callguard.preparedAt")
    return true
  }
  private func reloadCallDirectory(_ done: @escaping (Error?) -> Void) {
    let lock = NSLock(); var finished = false
    let finish: (Error?) -> Void = { error in lock.lock(); defer { lock.unlock() }; guard !finished else { return }; finished = true; done(error) }
    CXCallDirectoryManager.sharedInstance().reloadExtension(withIdentifier: callDirectoryId, completionHandler: finish)
    DispatchQueue.global().asyncAfter(deadline: .now() + 8) { finish(NSError(domain: "ApolloCallDirectory", code: 408, userInfo: [NSLocalizedDescriptionKey: "Call Directory reload timed out."])) }
  }

  public func definition() -> ModuleDefinition {
    Name("ApolloSecurity")
    Events("onProtectionStateChanged")

    AsyncFunction("getCapabilities") { (promise: Promise) in
      self.refreshBlockerState { enabled in
        let running = self.requested
        let site: (String, String) = enabled == true
          ? (running ? "active" : "inactive", running ? "Safari blocks verified threat domains via ApolloSG's content blocker." : "Turn protection on to activate the Safari content blocker.")
          : ("permission_required", "Enable ApolloSG in Settings › Safari › Extensions to block threat sites in Safari.")
        promise.resolve(self.json([
          ["id": "link_guard", "title": "Link Gate", "status": running ? "active" : "available", "detail": "Checks links you paste or share into ApolloSG."],
          ["id": "known_threats", "title": "Known Threat Lookup", "status": running ? "active" : "available", "detail": "Privacy-preserving reputation checks using the link only."],
          ["id": "site_guard", "title": "Site Gate", "status": site.0, "detail": site.1],
          ["id": "connection_guard", "title": "Connection Guard", "status": running ? "active" : "available", "detail": "Limited on iOS: Apple only reveals whether the current Wi‑Fi is open or secured."],
          ["id": "share_intake", "title": "Share to ApolloSG", "status": "active", "detail": "Share a link from any app to check it."],
        ]))
      }
    }

    AsyncFunction("getProtectionStatus") { (promise: Promise) in
      self.refreshBlockerState { _ in promise.resolve(self.statusJSON()) }
    }

    AsyncFunction("analyseURL") { (_ url: String) -> String in
      self.json(["supported": false, "verdict": "unknown", "reasons": ["Native URL analysis not implemented yet."]])
    }
    AsyncFunction("analyseDomain") { (_ domain: String) -> String in
      self.json(["supported": false, "verdict": "unknown", "reasons": ["Native domain analysis not implemented yet."]])
    }

    AsyncFunction("blockDestination") { (host: String, promise: Promise) in
      guard let canonicalHost = self.canonicalHost(host) else {
        promise.resolve(self.json(["verified": false, "method": "none", "detail": "That destination is not a valid host.", "adapterLabel": self.label, "blockedAt": NSNull(), "rulesState": "invalid", "reloadState": "not_requested", "activeState": "unobservable"]))
        return
      }
      var hosts = self.blockedHosts(); hosts.insert(canonicalHost)
      self.saveBlockedHosts(hosts)
      guard self.writeRules(hosts) else {
        promise.resolve(self.json(["verified": false, "method": "none", "detail": "Could not prepare the Safari rule list (App Group unavailable).", "adapterLabel": self.label, "blockedAt": NSNull(), "rulesState": "unavailable", "reloadState": "not_requested", "activeState": "unobservable"]))
        return
      }
      SFContentBlockerManager.reloadContentBlocker(withIdentifier: self.blockerId) { error in
        self.refreshBlockerState { enabled in
          promise.resolve(self.json([
            "verified": false,
            "method": "content_blocker",
            "detail": error == nil ? (enabled == true ? "Safari accepted Apollo's updated rule list. Safari does not report whether this destination is later matched." : "The rule list is prepared, but ApolloSG's Safari extension is not enabled.") : "The rule list is prepared, but Safari could not reload it.",
            "adapterLabel": self.label,
            "blockedAt": NSNull(),
            "rulesState": "prepared",
            "reloadState": error == nil ? "reload_requested" : "reload_failed",
            "activeState": enabled == true ? "enabled_match_unobservable" : "not_enabled",
          ]))
        }
      }
    }

    AsyncFunction("unblockDestination") { (host: String, promise: Promise) in
      var hosts = self.blockedHosts(); hosts.remove(host.lowercased())
      self.saveBlockedHosts(hosts); _ = self.writeRules(hosts)
      SFContentBlockerManager.reloadContentBlocker(withIdentifier: self.blockerId) { error in
        promise.resolve(self.json(["verified": false, "method": "content_blocker", "detail": error == nil ? "The Safari rule list was updated. Safari does not report individual matches." : "The rule was removed locally, but Safari could not reload the list.", "adapterLabel": self.label, "blockedAt": NSNull(), "rulesState": "prepared", "reloadState": error == nil ? "reload_requested" : "reload_failed", "activeState": "unobservable"]))
      }
    }

    AsyncFunction("getNetworkStatus") { (promise: Promise) in
      // iOS exposes very little: NEHotspotNetwork (needs the Access Wi‑Fi Information entitlement + location
      // permission) reports whether the current Wi‑Fi is secure. Anything Apple hides is reported as "unknown".
      let monitor = NWPathMonitor(); let queue = DispatchQueue(label: "apollo.path"); let lock = NSLock(); var completed = false
      let resolveOnce: ([String: Any]) -> Void = { value in lock.lock(); defer { lock.unlock() }; guard !completed else { return }; completed = true; monitor.cancel(); promise.resolve(self.json(value)) }
      monitor.pathUpdateHandler = { path in
        let type: String = path.status != .satisfied ? "none" : path.usesInterfaceType(.wifi) ? "wifi" : path.usesInterfaceType(.cellular) ? "cellular" : path.usesInterfaceType(.wiredEthernet) ? "ethernet" : "other"
        let vpn = path.availableInterfaces.contains { $0.type == .other && $0.name.hasPrefix("utun") }
        let finish: (String, String?) -> Void = { sec, ssid in
          resolveOnce(["connected": path.status == .satisfied, "type": type, "isInternetReachable": path.status == .satisfied,
                       "inspectable": self.requested, "wifiSecurity": sec, "captivePortal": NSNull(), "vpnActive": vpn, "ssid": ssid ?? NSNull(), "checkedAt": self.now()])
        }
        guard type == "wifi" else { finish("n/a", nil); return }
        if #available(iOS 14.0, *) {
          NEHotspotNetwork.fetchCurrent { net in
            guard let net = net else { finish("unknown", nil); return }
            if #available(iOS 15.0, *) {
              switch net.securityType { case .open: finish("open", net.ssid); case .WEP: finish("wep", net.ssid); case .personal: finish("wpa", net.ssid); case .enterprise: finish("enterprise", net.ssid); default: finish("unknown", net.ssid) }
            } else { finish(net.isSecure ? "wpa" : "open", net.ssid) }
          }
        } else { finish("unknown", nil) }
      }
      monitor.start(queue: queue)
      queue.asyncAfter(deadline: .now() + 5) { resolveOnce(["connected": false, "type": "unknown", "isInternetReachable": false, "inspectable": false, "wifiSecurity": "unknown", "captivePortal": NSNull(), "vpnActive": NSNull(), "ssid": NSNull(), "checkedAt": self.now(), "unavailableReason": "observation_timeout"]) }
    }

    AsyncFunction("getSecuritySignals") { () -> String in "[]" }

    // Gate 2 — Text Guard. The Message Filter extension sees only SMS/MMS from unknown senders;
    // iMessage, known contacts and other messaging apps remain outside Apple's extension scope.
    // A recent extension observation is positive evidence that it is active. Absence is not proof
    // that it is disabled, so Apollo reports permission_required until the extension runs.
    AsyncFunction("getMessagingCapabilities") { () -> String in
      // B3: Distinguish between confirmed current Message Filter activity (within 72h) and purely
      // historical observation. Only claim "supported" when the extension is actively filtering.
      let hasRecentObservation = self.messageFilterRecentlyObserved
      let hasHistoricalObservation = self.messageFilterObservedAt != nil && !hasRecentObservation
      let status: String = hasRecentObservation ? "supported" : "permission_required"
      return self.json([
        "smsFiltering": status,
        "linkInterception": "supported",
        "senderReputation": "unsupported",
        "shareExtension": "supported",
        "notificationIntegration": "unsupported",
        // Additional metadata for gate status reporting
        "messageFilterLastObserved": self.messageFilterObservedAt ?? NSNull(),
        "messageFilterHistoricalOnly": hasHistoricalObservation
      ])
    }
    AsyncFunction("getRecentMessageSecurityEvents") { () -> String in
      let rows = UserDefaults(suiteName: self.appGroup)?.array(forKey: self.messageEventsKey) ?? []
      return self.json(rows)
    }
    AsyncFunction("acknowledgeMessageSecurityEvents") { (ids: String) -> String in
      let requested = (try? JSONSerialization.jsonObject(with: Data(ids.utf8)) as? [String]) ?? []
      let defaults = UserDefaults(suiteName: self.appGroup)
      let rows = defaults?.array(forKey: self.messageEventsKey) as? [[String: Any]] ?? []
      let remaining = rows.filter { row in guard let id = row["id"] as? String else { return true }; return !requested.contains(id) }
      defaults?.set(remaining, forKey: self.messageEventsKey)
      return self.json(["acknowledged": rows.count - remaining.count])
    }
    AsyncFunction("openSmsListenerSettings") { () -> String in
      if let url = URL(string: UIApplication.openSettingsURLString) { DispatchQueue.main.async { UIApplication.shared.open(url) }; return self.json(["opened": true]) }
      return self.json(["opened": false])
    }
    // Text Guard local findings (Android-only; iOS uses Message Filter extension, no local analyzer).
    AsyncFunction("getTextGuardLocalFindings") { () -> String in "[]" }
    AsyncFunction("acknowledgeTextGuardLocalFindings") { (_: String) -> String in self.json(["acknowledged": 0]) }

    // Call Guard (CallSdk contract). `callScreening` reflects CXCallDirectoryManager's OWN reported
    // enabled status for ApolloCallDirectory — never assumed. `numberReputation` is always
    // "supported": the lookup is backend-proxied (POST /api/call/risk-check) and works regardless of
    // extension state. `callerIdentification` follows the SAME extension: when it is enabled,
    // numbers this phone found high-risk ring with the label "Suspected scam" (identification
    // entries), while the person's own block list is blocked.
    AsyncFunction("getCallProtectionCapabilities") { (promise: Promise) in
      CXCallDirectoryManager.sharedInstance().getEnabledStatusForExtension(withIdentifier: self.callDirectoryId) { status, _ in
        let enabled = status == .enabled
        promise.resolve(self.json([
          "callScreening": enabled ? "supported" : "permission_required",
          "callerIdentification": enabled ? "supported" : "permission_required",
          "numberReputation": "supported",
          "voicemailTranscript": "unsupported",
          "liveTranscript": "unsupported",
        ]))
      }
    }
    // Call Gate only: explicit, foreground contact access; never a background address-book scan.
    AsyncFunction("requestCallerContactsAccess") { (promise: Promise) in
      let store = CNContactStore()
      let status = CNContactStore.authorizationStatus(for: .contacts)
      if status == .authorized {
        promise.resolve(self.json(["granted": true]))
      } else if status == .notDetermined {
        store.requestAccess(for: .contacts) { granted, _ in
          promise.resolve(self.json(["granted": granted]))
        }
      } else {
        promise.resolve(self.json(["granted": false]))
      }
    }
    AsyncFunction("lookupCallerContact") { (number: String) -> String in
      guard CNContactStore.authorizationStatus(for: .contacts) == .authorized else {
        return self.json(["status": "permission_required"])
      }
      guard number.count >= 3 && number.count <= 32 && number.contains(where: { $0.isNumber }) else {
        return self.json(["status": "invalid"])
      }
      let store = CNContactStore()
      let keys: [CNKeyDescriptor] = [CNContactGivenNameKey as CNKeyDescriptor, CNContactFamilyNameKey as CNKeyDescriptor, CNContactPhoneNumbersKey as CNKeyDescriptor, CNContactThumbnailImageDataKey as CNKeyDescriptor]
      do {
        // Exact canonical digit match, with a conservative local-suffix fallback for country codes.
        // A suffix match is a saved-address-book association, not caller authentication.
        let target = number.filter { $0.isNumber }
        let contacts = try store.unifiedContacts(matching: CNContact.predicateForContacts(matching: CNPhoneNumber(stringValue: number)), keysToFetch: keys)
        guard let contact = contacts.first(where: { contact in
          contact.phoneNumbers.contains(where: { entry in
            let candidate = entry.value.stringValue.filter { $0.isNumber }
            return candidate == target || (candidate.count >= 9 && target.count >= 9 && candidate.suffix(9) == target.suffix(9))
          })
        }) else { return self.json(["status": "not_found"]) }
        let name = CNContactFormatter.string(from: contact, style: .fullName) ?? ""
        var result: [String: Any] = ["status": "matched", "name": name]
        if let photo = contact.thumbnailImageData, photo.count <= 262144 {
          result["photoUri"] = "data:image/jpeg;base64," + photo.base64EncodedString()
        }
        return self.json(result)
      } catch {
        return self.json(["status": "error"])
      }
    }
    AsyncFunction("getCallDirectoryStatus") { (promise: Promise) in
      CXCallDirectoryManager.sharedInstance().getEnabledStatusForExtension(withIdentifier: self.callDirectoryId) { status, error in
        if let error = error {
          promise.resolve(self.json(["status": "error", "enabled": false, "extensionAvailable": false, "detail": error.localizedDescription]))
          return
        }
        switch status {
        case .enabled:
          promise.resolve(self.json(["status": "ok", "enabled": true, "extensionAvailable": true]))
        case .disabled:
          promise.resolve(self.json(["status": "ok", "enabled": false, "extensionAvailable": true]))
        default:
          promise.resolve(self.json(["status": "error", "enabled": false, "extensionAvailable": false, "detail": "Call Directory state is unknown."]))
        }
      }
    }
    AsyncFunction("requestCallScreeningRole") { () -> String in
      // Apple has no API to deep-link directly to Phone › Call Blocking & Identification — only to
      // the app's own Settings page. The in-app copy tells the person exactly where to go from there.
      if let url = URL(string: UIApplication.openSettingsURLString) { DispatchQueue.main.async { UIApplication.shared.open(url) } }
      return self.json(["opened": true])
    }
    // Apple gives CXCallDirectoryProvider no per-call callback — there is no ringing event for iOS to
    // observe and queue, unlike Android's CallScreeningService. Always honestly empty.
    AsyncFunction("getPendingCallLookups") { () -> String in "[]" }
    AsyncFunction("getCallBlockAllowList") { () -> String in self.json(self.loadCallLists()) }
    AsyncFunction("addCallListEntry") { (json: String, promise: Promise) in
      guard let body = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String],
            let supplied = body["number"], let number = self.canonicalPhoneNumber(supplied) else { promise.resolve(self.json(["ok": false, "listState": "invalid_number", "reloadState": "not_requested"])); return }
      let key = body["kind"] == "allow" ? "allow" : "block"
      var lists = self.loadCallLists()
      lists[key] = Array(Set((lists[key] ?? []) + [number])).sorted()
      guard self.saveCallLists(lists) else { promise.resolve(self.json(["ok": false, "listState": "write_failed", "reloadState": "not_requested"])); return }
      self.reloadCallDirectory { error in promise.resolve(self.json(["ok": error == nil, "listState": "prepared", "reloadState": error == nil ? "reload_requested" : "reload_failed"])) }
    }
    AsyncFunction("removeCallListEntry") { (json: String, promise: Promise) in
      guard let body = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String],
            let supplied = body["number"], let number = self.canonicalPhoneNumber(supplied) else { promise.resolve(self.json(["ok": false, "listState": "invalid_number", "reloadState": "not_requested"])); return }
      let key = body["kind"] == "allow" ? "allow" : "block"
      var lists = self.loadCallLists()
      lists[key] = (lists[key] ?? []).filter { $0 != number }
      guard self.saveCallLists(lists) else { promise.resolve(self.json(["ok": false, "listState": "write_failed", "reloadState": "not_requested"])); return }
      self.reloadCallDirectory { error in promise.resolve(self.json(["ok": error == nil, "listState": "prepared", "reloadState": error == nil ? "reload_requested" : "reload_failed"])) }
    }
    AsyncFunction("markNumberRisky") { (json: String, promise: Promise) in
      guard let body = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: String],
            let supplied = body["number"], let number = self.canonicalPhoneNumber(supplied) else { promise.resolve(self.json(["ok": false, "listState": "invalid_number", "reloadState": "not_requested"])); return }
      var lists = self.loadCallLists()
      lists["autoRisky"] = Array(Set((lists["autoRisky"] ?? []) + [number])).sorted()
      guard self.saveCallLists(lists) else { promise.resolve(self.json(["ok": false, "listState": "write_failed", "reloadState": "not_requested"])); return }
      self.reloadCallDirectory { error in promise.resolve(self.json(["ok": error == nil, "listState": "prepared", "reloadState": error == nil ? "reload_requested" : "reload_failed"])) }
    }

    // Phase A — Apps & Device (AppDeviceSdk contract). iPhone exposes exactly two facts; the rest is honestly null.
    AsyncFunction("getAppDeviceCapabilities") { () -> String in self.json(DeviceSignalsTruth.capabilities()) }
    AsyncFunction("getInstalledAppAssessment") { (_ name: String) -> String in "null" }   // iOS has no app list / permission API
    AsyncFunction("getRecentInstallEvents") { () -> String in "[]" }
    AsyncFunction("getRecentAppSecurityEvents") { () -> String in "[]" }
    AsyncFunction("getDeviceSecuritySignals") { (promise: Promise) in
      let managed = UserDefaults.standard.dictionary(forKey: "com.apple.configuration.managed") != nil
      // A device passcode is required for deviceOwnerAuthentication; its availability proves a secure lock is set.
      let lockSecure = LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
      let probe = "/private/apollo_integrity_probe.txt"
      let wroteOutside = (try? "x".write(toFile: probe, atomically: true, encoding: .utf8)) != nil
      if wroteOutside { try? FileManager.default.removeItem(atPath: probe) }
      let jailbreak = DeviceSignalsTruth.jailbreakIndicators(fileExists: { FileManager.default.fileExists(atPath: $0) }, canWriteOutsideSandbox: wroteOutside)
      let scoped = ((CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any])?["__SCOPED__"] as? [String: Any])?.keys.map { $0 } ?? []
      let monitor = NWPathMonitor(); let queue = DispatchQueue(label: "apollo.device.path")
      monitor.pathUpdateHandler = { path in
        monitor.cancel()
        let names = path.availableInterfaces.map { $0.name }
        let vpn: Bool? = path.status == .satisfied ? DeviceSignalsTruth.vpnActive(interfaceNames: names, scopedProxyKeys: scoped) : nil
        promise.resolve(self.json(DeviceSignalsTruth.signals(vpnActive: vpn, managedConfigPresent: managed, screenLockSecure: lockSecure, jailbreakIndicators: jailbreak)))
      }
      monitor.start(queue: queue)
    }

    AsyncFunction("startProtection") { (promise: Promise) in
      guard let transition = self.beginTransition() else { promise.resolve(self.statusJSON(transitionFailure: "transition_in_progress")); return }
      self.requested = true
      if self.protectionSince == nil { self.protectionSince = self.now() }
      _ = self.writeRules(self.blockedHosts())
      // Report only after Safari has answered: reload result + real extension state.
      let timeout = DispatchWorkItem { if self.completeTransition(transition) { promise.resolve(self.statusJSON(transitionFailure: "transition_timeout")) } }
      DispatchQueue.global().asyncAfter(deadline: .now() + 10, execute: timeout)
      SFContentBlockerManager.reloadContentBlocker(withIdentifier: self.blockerId) { _ in
        self.refreshBlockerState { _ in
          guard self.completeTransition(transition) else { return }
          timeout.cancel(); let status = self.statusJSON(); self.sendEvent("onProtectionStateChanged", ["value": status]); promise.resolve(status)
        }
      }
    }
    AsyncFunction("stopProtection") { (promise: Promise) in
      guard let transition = self.beginTransition() else { promise.resolve(self.statusJSON(transitionFailure: "transition_in_progress")); return }
      self.requested = false
      self.protectionSince = nil
      // Turning protection off must also stop enforcing: write an empty rule list and reload.
      _ = self.writeRules([])
      let timeout = DispatchWorkItem { if self.completeTransition(transition) { promise.resolve(self.statusJSON(transitionFailure: "transition_timeout")) } }
      DispatchQueue.global().asyncAfter(deadline: .now() + 10, execute: timeout)
      SFContentBlockerManager.reloadContentBlocker(withIdentifier: self.blockerId) { _ in
        self.refreshBlockerState { _ in
          guard self.completeTransition(transition) else { return }
          timeout.cancel(); let status = self.statusJSON(); self.sendEvent("onProtectionStateChanged", ["value": status]); promise.resolve(status)
        }
      }
    }

    AsyncFunction("getProtectionPermissions") { (promise: Promise) in
      self.refreshBlockerState { enabled in
        // Notifications: a fresh UNUserNotificationCenter observation, separate from Apollo's recorded request history.
        UNUserNotificationCenter.current().getNotificationSettings { settings in
          let observedAt = self.now()
          let notifState: String
          switch settings.authorizationStatus {
          case .authorized, .provisional, .ephemeral: notifState = "granted"
          case .denied: notifState = "denied"
          default: notifState = "undetermined"
          }
          promise.resolve(self.json([
            self.perm("network_filter", "Safari content blocker", enabled == true ? "granted" : (enabled == false ? "denied" : "undetermined"), true,
                      "Enable ApolloSG under Settings › Safari › Extensions so Safari can block verified threat sites. Safari never shares what you browse with ApolloSG.", observedAt, enabled: enabled),
            self.perm("notifications", "Notifications", notifState, notifState != "denied", "Lets Apollo tell you when it barks.", observedAt, enabled: notifState == "granted"),
            self.perm("vpn_config", "Local VPN", "not_applicable", false, "ApolloSG on iOS uses a Safari content blocker, not a VPN.", observedAt, enabled: nil, unavailableReason: "not_implemented"),
            self.perm("accessibility", "Accessibility service", "not_applicable", false, "iOS exposes no accessibility-service permission to apps.", observedAt, enabled: nil, unavailableReason: "os_restricted"),
          ]))
        }
      }
    }

    AsyncFunction("requestProtectionPermission") { (id: String, promise: Promise) in
      self.recordRequest(id)
      let observedAt = self.now()
      if id == "network_filter", let url = URL(string: UIApplication.openSettingsURLString) {
        DispatchQueue.main.async { UIApplication.shared.open(url) }
        promise.resolve(self.json(self.perm(id, "Safari content blocker", "undetermined", true, "Opened Settings. Enable ApolloSG under Safari › Extensions, then return.", observedAt, enabled: nil)))
      } else if id == "notifications" {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
          promise.resolve(self.json(self.perm(id, "Notifications", granted ? "granted" : "denied", false, granted ? "Granted." : "Declined in the system prompt. It can be changed under Settings › ApolloSG › Notifications.", self.now(), enabled: granted)))
        }
      } else {
        promise.resolve(self.json(self.perm(id, id, "not_applicable", false, "ApolloSG does not request this permission on iOS.", observedAt, enabled: nil, unavailableReason: "not_implemented")))
      }
    }

    // Real device facts for investigation guidance. Form factor comes from the interface idiom, never from screen width.
    AsyncFunction("getDeviceProfileFacts") { () -> String in
      let idiom = UIDevice.current.userInterfaceIdiom
      let formFactor = idiom == .pad ? "tablet" : idiom == .phone ? "phone" : idiom == .mac ? "desktop" : "unknown"
      var systemInfo = utsname(); uname(&systemInfo)
      let machine = withUnsafePointer(to: &systemInfo.machine) { $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(validatingUTF8: $0) } } ?? UIDevice.current.model
      return self.json(["manufacturer": "Apple", "model": machine, "osVersion": self.platformVersion(), "formFactor": formFactor, "locale": Locale.current.identifier])
    }

    // Cross-Platform Architecture Directive: describes what THIS deployed mechanism — a Safari
    // Content Blocker (declarative WebKit rule matching) — actually does, never the theoretical
    // NEFilterDataProvider ceiling recorded as PLATFORM_CAPABILITY_BASELINES.ios in
    // PlatformCapabilityProfile.ts. Mirrors ApolloSecurityModule.kt's getPlatformCapabilityProfile
    // shape exactly; keep both in sync with PlatformCapabilityProfile.ts.
    AsyncFunction("getPlatformCapabilityProfile") { () -> String in
      self.json([
        "platform": "ios",
        "platformVersion": self.platformVersion(),
        "sdkVersion": self.moduleVersion,
        "capabilityVersion": "1", // keep in sync with CAPABILITY_PROFILE_VERSION in PlatformCapabilityProfile.ts
        // The content blocker filters URL loads inside Safari via a declarative rule list —
        // real, but scoped to one browser and pattern-based, not a network/VPN interception.
        "networkFiltering": "partial",
        // WebKit evaluates rules internally; the extension never sees a packet or a flow.
        "packetVisibility": "none",
        // No DNS-level visibility at all — matching is on URL patterns, not resolved queries.
        "dnsVisibility": "none",
        // Safari content blockers have no process concept.
        "processAttribution": "none",
        // Scoped to Safari only; there is no cross-app attribution to claim.
        "appAttribution": "none",
        // WebKit does not report back which domains matched a rule — no observation, only a
        // static block outcome. Reporting "none" here (not "partial") keeps this consistent
        // with getEnforcementEvidence() always returning [] below.
        "domainVisibility": "none",
        // Real: a matching rule genuinely stops the load, but only inside Safari.
        "localBlocking": "partial",
        // The compiled rule list runs inside Safari's own extension process, independent of
        // Apollo's app lifecycle — but only while the person is using Safari.
        "backgroundProtection": "partial",
        // The rule list is written to disk ahead of time; enforcing it needs no connectivity.
        "offlineProtection": "full",
        // Apple gives third-party apps zero feedback about content-blocker rule hits.
        "realTimeEvents": "none",
        "scope": self.coverageScope, // ["browser:safari"] — never claim broader reach than this
      ])
    }

    // Safari gives Apollo no per-hit evidence for content-blocker matches (see comment above on
    // domainVisibility/realTimeEvents), and CXCallDirectoryProvider gives no per-call feedback either
    // (see the Call Guard block above) — so unlike Android's DNS tunnel + CallScreeningService, there
    // is nothing to list here, ever. Must stay [] until iOS moves to mechanisms that report individual
    // verified actions. A manual "Block" tap must never appear here either — see blockDestination()
    // above, whose `verified` flag already reflects the same "no observed drop" truth for the app's own UI.
    AsyncFunction("getEnforcementEvidence") { () -> String in "[]" }

    AsyncFunction("getShareHandoff") { (handoffId: String) -> String in self.shareHandoff(handoffId) }
    AsyncFunction("acknowledgeShareHandoff") { (handoffId: String) -> String in self.acknowledgeShareHandoff(handoffId) }
    AsyncFunction("discardShareHandoff") { (handoffId: String) -> String in self.discardShareHandoff(handoffId) }

    // Live Caller ID — PIR server URL injection into shared UserDefaults.
    // Called silently at app startup from ApolloContext with the URL from app.json extra config.
    // The ApolloLiveCallerID extension reads this key to know where to send PIR queries.
    AsyncFunction("configurePirServerUrl") { (url: String) -> String in
      let defaults = UserDefaults(suiteName: self.appGroup)
      if url.isEmpty {
        defaults?.removeObject(forKey: "apollo.pir.server_url")
        return self.json(["configured": false])
      }
      guard URL(string: url) != nil else {
        return self.json(["configured": false, "error": "invalid_url"])
      }
      defaults?.set(url, forKey: "apollo.pir.server_url")
      defaults?.synchronize()
      return self.json(["configured": true, "url": url])
    }
  }

  // MARK: - Helpers

  private func refreshBlockerState(_ done: @escaping (Bool?) -> Void) {
    SFContentBlockerManager.getStateOfContentBlocker(withIdentifier: blockerId) { state, error in
      let enabled: Bool? = error == nil ? state?.isEnabled : nil
      self.blockerEnabled = enabled
      if enabled != nil { self.blockerVerifiedAt = self.now() }
      done(enabled)
    }
  }

  private func blockedHosts() -> Set<String> {
    Set(UserDefaults(suiteName: appGroup)?.stringArray(forKey: blockedKey) ?? [])
  }
  private func saveBlockedHosts(_ hosts: Set<String>) {
    UserDefaults(suiteName: appGroup)?.set(Array(hosts).sorted(), forKey: blockedKey)
  }

  /// Writes the Safari rule list built by SiteGuardTruth.rules (pure, unit-tested).
  private func writeRules(_ hosts: Set<String>) -> Bool {
    guard let url = listURL, let data = try? JSONSerialization.data(withJSONObject: SiteGuardTruth.rules(for: hosts)) else { return false }
    guard (try? data.write(to: url, options: .atomic)) != nil else { return false }
    let defaults = UserDefaults(suiteName: appGroup)
    defaults?.set((defaults?.integer(forKey: "apollo.siteguard.ruleVersion") ?? 0) + 1, forKey: "apollo.siteguard.ruleVersion")
    defaults?.set(now(), forKey: "apollo.siteguard.rulesPreparedAt")
    return true
  }

  /// requested = intent · operational = extension enabled (observed) AND rules written · degradedReason = the gap.
  /// Derivation lives in SiteGuardTruth so it is unit-tested; this only reads observed inputs and formats.
  private func statusJSON(transitionFailure: String? = nil) -> String {
    let wants = requested
    let d = SiteGuardTruth.derive(requested: wants, blockerEnabled: blockerEnabled, rulesWritten: rulesWritten)
    return json([
      "running": d.operational,
      "requested": wants,
      "operational": d.operational,
      "enforcementMethod": d.enforcementMethod,
      "coverage": d.operational ? coverage : "Nothing is being blocked in Safari right now. Link checks you run in ApolloSG still work.",
      "coverageScope": d.operational ? coverageScope : [],
      "lastVerified": blockerVerifiedAt ?? NSNull(),
      "degradedReason": d.degradedReason ?? NSNull(),
      "visibility": wants ? "limited" : "none",
      "since": wants ? (protectionSince ?? NSNull()) : NSNull(),
      "adapterLabel": label,
      "checkedAt": now(),
      "transitionFailure": transitionFailure ?? NSNull(),
      "ruleVersion": UserDefaults(suiteName: appGroup)?.integer(forKey: "apollo.siteguard.ruleVersion") ?? 0,
      "rulesPreparedAt": UserDefaults(suiteName: appGroup)?.string(forKey: "apollo.siteguard.rulesPreparedAt") ?? NSNull(),
    ])
  }

  private func now() -> String { ISO8601DateFormatter().string(from: Date()) }
  private func beginTransition() -> UUID? {
    transitionLock.lock(); defer { transitionLock.unlock() }
    guard activeTransition == nil else { return nil }
    let value = UUID(); activeTransition = value; return value
  }
  private func completeTransition(_ value: UUID) -> Bool {
    transitionLock.lock(); defer { transitionLock.unlock() }
    guard activeTransition == value else { return false }
    activeTransition = nil; return true
  }
  private func canonicalHost(_ value: String) -> String? {
    let host = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
    guard !host.isEmpty, host.count <= 253, host.range(of: #"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])$"#, options: .regularExpression) != nil else { return nil }
    return host
  }
  private func canonicalPhoneNumber(_ value: String) -> String? {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard trimmed.range(of: #"^\+[1-9][0-9]{7,14}$"#, options: .regularExpression) != nil else { return nil }
    return trimmed
  }

  private var shareHandoffRoot: URL? {
    FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?.appendingPathComponent("ApolloShareHandoffs", isDirectory: true)
  }
  private func shareHandoffDirectory(_ id: String) -> URL? {
    guard let uuid = UUID(uuidString: id), uuid.uuidString.lowercased() == id.lowercased(), !id.contains("/") else { return nil }
    return shareHandoffRoot?.appendingPathComponent(uuid.uuidString.lowercased(), isDirectory: true)
  }
  private func shareHandoff(_ id: String) -> String {
    cleanupShareHandoffs()
    guard let directory = shareHandoffDirectory(id) else { return json(["status": "invalid", "handoffId": id, "detail": "The share reference is invalid."]) }
    let manifest = directory.appendingPathComponent("manifest.complete.json")
    guard let data = try? Data(contentsOf: manifest), let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any], object["state"] as? String == "committed" else {
      return json(["status": "missing", "handoffId": id, "detail": "The protected shared items are not complete or are no longer available."])
    }
    if let value = object["expiresAt"] as? String, let expiry = ISO8601DateFormatter().date(from: value), expiry <= Date() {
      try? FileManager.default.removeItem(at: directory)
      return json(["status": "expired", "handoffId": id, "detail": "The protected shared items expired. Share them with ApolloSG again."])
    }
    guard let payload = object["payload"] as? [String: Any] else { return json(["status": "invalid", "handoffId": id, "detail": "The share manifest is invalid."]) }
    return json(["status": "ready", "handoffId": id, "payload": payload])
  }
  private func acknowledgeShareHandoff(_ id: String) -> String {
    guard let directory = shareHandoffDirectory(id), FileManager.default.fileExists(atPath: directory.appendingPathComponent("manifest.complete.json").path) else { return json(["acknowledged": false]) }
    let marker = directory.appendingPathComponent("imported")
    let stored = (try? Data(now().utf8).write(to: marker, options: .atomic)) != nil
    return json(["acknowledged": stored])
  }
  private func discardShareHandoff(_ id: String) -> String {
    guard let directory = shareHandoffDirectory(id) else { return json(["discarded": false]) }
    let existed = FileManager.default.fileExists(atPath: directory.path)
    if existed { try? FileManager.default.removeItem(at: directory) }
    return json(["discarded": existed])
  }
  private func cleanupShareHandoffs() {
    guard let root = shareHandoffRoot else { return }
    let directories = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
    for directory in directories {
      let data = try? Data(contentsOf: directory.appendingPathComponent("manifest.complete.json"))
      let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
      let expiry = (object?["expiresAt"] as? String).flatMap { ISO8601DateFormatter().date(from: $0) }
      let modified = try? directory.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
      if (expiry ?? modified ?? .distantPast) <= Date() { try? FileManager.default.removeItem(at: directory) }
    }
  }
  private func platformVersion() -> String { "iOS \(UIDevice.current.systemVersion)" }
  /// `requested`/`lastRequestedAt` = Apollo's recorded request history; `status`/`enabled` = fresh OS observation.
  private func perm(_ id: String, _ title: String, _ status: String, _ canAskAgain: Bool, _ why: String, _ observedAt: String, enabled: Bool?, unavailableReason: String? = nil) -> [String: Any] {
    let requestedAt = UserDefaults.standard.string(forKey: "apollo.perm_requested_at.\(id)")
    return ["id": id, "title": title, "status": status, "canAskAgain": canAskAgain, "why": why,
            "requested": requestedAt != nil, "lastRequestedAt": requestedAt ?? NSNull(), "enabled": enabled ?? NSNull(),
            "observedAt": observedAt, "unavailableReason": unavailableReason ?? NSNull()]
  }
  private func recordRequest(_ id: String) { UserDefaults.standard.set(now(), forKey: "apollo.perm_requested_at.\(id)") }
  private func json(_ value: Any) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: value), let s = String(data: data, encoding: .utf8) else { return "{}" }
    return s
  }
}
