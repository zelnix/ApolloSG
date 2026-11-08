package app.apollo.slm

import android.os.Build
import android.os.SystemClock
import com.google.mlkit.genai.common.FeatureStatus
import com.google.mlkit.genai.prompt.Generation
import com.google.mlkit.genai.prompt.GenerativeModel
import com.google.mlkit.genai.prompt.TextPart
import com.google.mlkit.genai.prompt.generateContentRequest
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.functions.Coroutine
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

class SlmGenerateInput : Record {
  @Field var instructions: String = ""
  @Field var prompt: String = ""
  @Field var maxOutputTokens: Int = 256
  @Field var temperature: Double = 0.2
}

class SlmUnavailableException : CodedException("SLM_UNAVAILABLE", "The on-device model isn't ready on this phone.", null)
class SlmFailedException(kind: String) : CodedException("SLM_FAILED", kind, null)

/**
 * ApolloSG's on-device small language model: Gemini Nano through ML Kit GenAI, run by Android AICore.
 *
 * Everything stays on the phone: this module makes no network call of its own, logs nothing, and never stores the
 * prompt or the answer. One call per request, no retry, no other model. A failure is reported as-is to the TypeScript
 * caller, which keeps Apollo's fixed-rule result unchanged.
 */
class ApolloSlmModule : Module() {
  private val downloads = CoroutineScope(SupervisorJob() + Dispatchers.Default)
  private var model: GenerativeModel? = null

  private fun client(): GenerativeModel = model ?: Generation.getClient().also { model = it }

  private fun osVersion(): String = "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})"

  /** The Gemini Nano version AICore runs on this phone (e.g. a nano-v2/v3 name), or null if it can't be read. */
  private suspend fun baseModelName(): String? = try {
    client().getBaseModelName().takeIf { it.isNotBlank() }
  } catch (e: Exception) {
    null
  }

  private fun status(availability: String, reason: String?, engine: String = "gemini_nano_mlkit", modelName: String? = null): Map<String, Any?> =
    mapOf(
      "availability" to availability, "engine" to engine, "reason" to reason,
      "modelName" to modelName, "osVersion" to osVersion(), "observedAt" to Instant.now().toString(),
    )

  private suspend fun readStatus(): Map<String, Any?> = try {
    when (client().checkStatus()) {
      FeatureStatus.AVAILABLE -> status("available", null, modelName = baseModelName())
      FeatureStatus.DOWNLOADABLE -> status("downloadable", "model_not_downloaded")
      FeatureStatus.DOWNLOADING -> status("downloading", "model_downloading")
      else -> status("unavailable", "device_not_eligible")
    }
  } catch (e: Exception) {
    // AICore missing or refused the request: report it, never guess.
    status("unavailable", "aicore_error", engine = "none")
  }

  override fun definition() = ModuleDefinition {
    Name("ApolloSlm")

    AsyncFunction("getStatus") Coroutine { -> readStatus() }

    AsyncFunction("requestDownload") Coroutine { ->
      val current = readStatus()
      if (current["availability"] == "downloadable") {
        // The OS fetches the model; progress is read back through getStatus.
        downloads.launch { runCatching { client().download().collect { } } }
        status("downloading", "model_downloading")
      } else {
        current
      }
    }

    AsyncFunction("generate") Coroutine { input: SlmGenerateInput ->
      if (client().checkStatus() != FeatureStatus.AVAILABLE) throw SlmUnavailableException()
      val started = SystemClock.elapsedRealtime()
      val text = try {
        // The Prompt API takes one text input, so the fixed instructions lead it.
        val request = generateContentRequest(TextPart(input.instructions + "\n\n" + input.prompt)) {
          temperature = input.temperature.toFloat()
          maxOutputTokens = input.maxOutputTokens.coerceIn(16, 512)
          candidateCount = 1
        }
        client().generateContent(request).candidates.firstOrNull()?.text.orEmpty()
      } catch (e: Exception) {
        throw SlmFailedException(e.javaClass.simpleName)
      }
      mapOf(
        "text" to text, "engine" to "gemini_nano_mlkit", "modelName" to baseModelName(), "osVersion" to osVersion(),
        "elapsedMs" to (SystemClock.elapsedRealtime() - started),
      )
    }

    OnDestroy {
      downloads.cancel()
      runCatching { model?.close() }
      model = null
    }
  }
}
