import ExpoModulesCore
import CryptoKit
import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

struct SlmGenerateInput: Record {
  @Field var instructions: String = ""
  @Field var prompt: String = ""
  @Field var maxOutputTokens: Int = 256
  @Field var temperature: Double = 0.2
}

/// ApolloSG's on-device small language model: Apple's Foundation Models framework (iOS 26+, Apple Intelligence on).
///
/// Everything stays on the phone: no network call, no logging, nothing stored. One call per request, no retry, no
/// other model. A failure is reported as-is to the TypeScript caller, which keeps Apollo's fixed-rule result unchanged.
public class ApolloSlmModule: Module {
  private func now() -> String { ISO8601DateFormatter().string(from: Date()) }

  /// Apple publishes no version for its on-device model; it ships with the OS, so the iOS version identifies it.
  private func osVersion() -> String {
    let v = ProcessInfo.processInfo.operatingSystemVersion
    return "iOS \(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
  }

  private func status(_ availability: String, _ reason: String?, engine: String = "apple_foundation_models") -> [String: Any?] {
    ["availability": availability, "engine": engine, "reason": reason, "modelName": nil, "osVersion": osVersion(), "observedAt": now()]
  }

  private func readStatus() -> [String: Any?] {
    #if canImport(FoundationModels)
    if #available(iOS 26.0, *) {
      switch SystemLanguageModel.default.availability {
      case .available:
        return status("available", nil)
      case .unavailable(let reason):
        switch reason {
        case .deviceNotEligible: return status("unavailable", "device_not_eligible")
        case .appleIntelligenceNotEnabled: return status("unavailable", "apple_intelligence_off")
        case .modelNotReady: return status("downloading", "model_not_ready")
        @unknown default: return status("unavailable", "unknown")
        }
      }
    }
    #endif
    return status("unavailable", "os_too_old", engine: "none")
  }

  public func definition() -> ModuleDefinition {
    Name("ApolloSlm")

    AsyncFunction("getStatus") { () -> [String: Any?] in
      self.readStatus()
    }

    // iOS downloads and updates its model itself; this only reports where it stands.
    AsyncFunction("requestDownload") { () -> [String: Any?] in
      self.readStatus()
    }

    // SHA-256 of a downloaded fallback model, streamed so a 1 GB file never sits in memory. Nil if it can't be read.
    AsyncFunction("sha256File") { (path: String) -> String? in
      let url = path.hasPrefix("file://") ? URL(string: path) : URL(fileURLWithPath: path)
      guard let fileUrl = url, let handle = try? FileHandle(forReadingFrom: fileUrl) else { return nil }
      defer { try? handle.close() }
      var hasher = SHA256()
      // Each chunk is released before the next is read, so memory stays at about 1 MB however big the file is.
      var done = false
      while !done {
        autoreleasepool {
          let chunk = handle.readData(ofLength: 1 << 20)
          if chunk.isEmpty { done = true } else { hasher.update(data: chunk) }
        }
      }
      return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    AsyncFunction("generate") { (input: SlmGenerateInput) async throws -> [String: Any] in
      #if canImport(FoundationModels)
      if #available(iOS 26.0, *) {
        guard case .available = SystemLanguageModel.default.availability else {
          throw Exception(name: "SLM_UNAVAILABLE", description: "The on-device model isn't ready on this phone.")
        }
        let started = Date()
        do {
          let session = LanguageModelSession(instructions: input.instructions)
          let options = GenerationOptions(temperature: input.temperature,
                                          maximumResponseTokens: min(max(input.maxOutputTokens, 16), 512))
          let response = try await session.respond(to: input.prompt, options: options)
          return ["text": response.content, "engine": "apple_foundation_models", "modelName": NSNull(),
                  "osVersion": self.osVersion(), "elapsedMs": Int(Date().timeIntervalSince(started) * 1000)]
        } catch {
          throw Exception(name: "SLM_FAILED", description: String(describing: type(of: error)))
        }
      }
      #endif
      throw Exception(name: "SLM_UNAVAILABLE", description: "On-device AI needs iOS 26 with Apple Intelligence.")
    }
  }
}
