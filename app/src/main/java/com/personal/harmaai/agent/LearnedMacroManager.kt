package com.personal.harmaai.agent

import android.content.Context
import android.os.SystemClock
import android.util.Log
import com.personal.harmaai.accessibility.AgentAccessibilityService
import com.personal.harmaai.accessibility.ElementFingerprint
import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.data.HarmaDatabase
import com.personal.harmaai.data.LearnedMacroEntity
import com.personal.harmaai.data.StepEntity
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject

data class LearnedMacroStep(
    val toolName: String,
    val arguments: JSONObject,
    val fingerprint: ElementFingerprint? = null,
    val expectedPackage: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("toolName", toolName)
        .put("arguments", arguments)
        .put("expectedPackage", expectedPackage)
        .apply {
            if (fingerprint != null) {
                put("fingerprint", fingerprint.toJson())
            }
        }

    companion object {
        fun fromJson(json: JSONObject): LearnedMacroStep = LearnedMacroStep(
            toolName = json.optString("toolName"),
            arguments = json.optJSONObject("arguments") ?: JSONObject(),
            fingerprint = ElementFingerprint.fromJson(json.optJSONObject("fingerprint")),
            expectedPackage = json.optString("expectedPackage"),
        )
    }
}

sealed class MacroReplayResult {
    data class Replayed(
        val summary: String,
        val stepsExecuted: Int,
        val elapsedMs: Long,
    ) : MacroReplayResult()

    data class LayoutChanged(val reason: String) : MacroReplayResult()

    object NotFound : MacroReplayResult()
}

/**
 * Self-Learning UI Macro Cache:
 * Persists verified sequences of [ElementFingerprint] steps when the cloud LLM completes
 * a multi-step UI task, and replays them on-device (even offline) in <1s on subsequent requests.
 * Automatically falls back to the cloud LLM if an app update alters the UI layout.
 */
object LearnedMacroManager {
    private const val TAG = "LearnedMacroManager"
    private const val MAX_CONSECUTIVE_FAILURES = 2
    private const val MIN_TOKEN_SIMILARITY = 0.82

    private val NON_CACHEABLE_KEYWORDS = Regex(
        "(?i)\\b(password|otp|pin|cvv|pay|transfer|send|reply|whatsapp|call|dial|alarm|timer|delete|buy|order|purchase)\\b",
    )

    private val REPLAYABLE_TOOLS = setOf(
        "open_app",
        "tap",
        "type_text",
        "click_text",
        "click_id",
        "click_desc",
        "scroll",
        "scroll_to_find",
        "swipe",
        "press",
        "press_key",
        "back",
        "home",
        "recents",
        "open_settings",
        "open_settings_panel",
    )

    private val STOP_WORDS = setOf(
        "hey", "harma", "please", "can", "you", "could", "would", "the", "a", "an", "in", "on", "to", "for", "my",
    )

    fun normalizeCommand(rawCommand: String): String {
        return rawCommand
            .lowercase()
            .replace(Regex("^(?:hey\\s+harma|harma)[,\\s]*"), "")
            .replace(Regex("^(?:please|can\\s+you|could\\s+you|would\\s+you)\\s+"), "")
            .replace(Regex("[^a-z0-9\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    fun isCacheableCommand(rawCommand: String): Boolean {
        val norm = normalizeCommand(rawCommand)
        if (norm.length < 6) return false
        if (NON_CACHEABLE_KEYWORDS.containsMatchIn(norm)) return false
        return true
    }

    fun captureStepBeforeExecution(
        call: AgentToolCall,
        observationBefore: ScreenObservation?,
    ): LearnedMacroStep? {
        if (call.name !in REPLAYABLE_TOOLS) return null

        val cleanArgs = JSONObject(call.arguments.toString()).apply {
            remove("observation")
            remove("expected_outcome")
        }

        val targetIndex = if (call.name in setOf("tap", "type_text", "long_press", "scroll")) {
            call.arguments.optInt("index", -1)
        } else {
            -1
        }

        val fp = if (targetIndex >= 0 && observationBefore != null) {
            observationBefore.fingerprintAt(targetIndex)
        } else {
            null
        }

        return LearnedMacroStep(
            toolName = call.name,
            arguments = cleanArgs,
            fingerprint = fp,
            expectedPackage = observationBefore?.packageName.orEmpty(),
        )
    }

    fun serializeSteps(steps: List<LearnedMacroStep>): String {
        val arr = JSONArray()
        steps.forEach { arr.put(it.toJson()) }
        return arr.toString()
    }

    fun deserializeSteps(stepsJson: String): List<LearnedMacroStep> {
        if (stepsJson.isBlank()) return emptyList()
        return runCatching {
            val arr = JSONArray(stepsJson)
            buildList {
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    add(LearnedMacroStep.fromJson(obj))
                }
            }
        }.getOrDefault(emptyList())
    }

    suspend fun saveLearnedMacro(
        database: HarmaDatabase,
        rawCommand: String,
        steps: List<LearnedMacroStep>,
        finalSummary: String,
    ) {
        if (!isCacheableCommand(rawCommand)) return
        if (steps.isEmpty()) return
        // Require at least one UI interaction or multi-step sequence to be worth caching
        val hasUiStep = steps.any { it.fingerprint != null || it.toolName in setOf("tap", "click_text", "click_id", "click_desc", "type_text", "scroll_to_find") }
        if (!hasUiStep && steps.size < 2) return

        val normalized = normalizeCommand(rawCommand)
        val targetPkg = steps.firstNotNullOfOrNull { step ->
            step.arguments.optString("package").ifBlank { step.expectedPackage }.takeIf { it.isNotBlank() }
        }.orEmpty()

        val entity = LearnedMacroEntity(
            normalizedCommand = normalized,
            rawCommand = rawCommand.trim(),
            targetPackage = targetPkg,
            stepsJson = serializeSteps(steps),
            finalSummary = finalSummary,
            successCount = 1,
            failureCount = 0,
            updatedAt = System.currentTimeMillis(),
        )
        runCatching {
            database.learnedMacroDao().upsert(entity)
            Log.i(TAG, "Saved learned UI macro for '$normalized' (${steps.size} steps, pkg=$targetPkg)")
        }
    }

    suspend fun findMatchingMacro(
        database: HarmaDatabase,
        rawCommand: String,
    ): LearnedMacroEntity? {
        if (!isCacheableCommand(rawCommand)) return null
        val normalized = normalizeCommand(rawCommand)
        val dao = database.learnedMacroDao()

        dao.findByNormalizedCommand(normalized)?.let { exact ->
            if (exact.failureCount < MAX_CONSECUTIVE_FAILURES) return exact
        }

        val candidates = dao.getRecent(50)
        return candidates
            .filter { it.failureCount < MAX_CONSECUTIVE_FAILURES }
            .map { it to computeTokenSimilarity(normalized, it.normalizedCommand) }
            .filter { it.second >= MIN_TOKEN_SIMILARITY }
            .maxByOrNull { it.second }
            ?.first
    }

    internal fun computeTokenSimilarity(a: String, b: String): Double {
        if (a == b) return 1.0
        val tokensA = a.split(' ').map { it.trim() }.filter { it.isNotBlank() && it !in STOP_WORDS }.toSet()
        val tokensB = b.split(' ').map { it.trim() }.filter { it.isNotBlank() && it !in STOP_WORDS }.toSet()
        if (tokensA.isEmpty() || tokensB.isEmpty()) return 0.0
        val intersection = tokensA.intersect(tokensB).size.toDouble()
        val union = tokensA.union(tokensB).size.toDouble()
        return intersection / union
    }

    suspend fun tryReplayMacro(
        database: HarmaDatabase,
        executor: AgentToolExecutor,
        safetyGate: SafetyGate,
        command: String,
        taskId: String,
    ): MacroReplayResult {
        val macro = findMatchingMacro(database, command) ?: return MacroReplayResult.NotFound
        val steps = deserializeSteps(macro.stepsJson)
        if (steps.isEmpty()) return MacroReplayResult.NotFound

        val accessibility = AgentAccessibilityService.current()
            ?: return MacroReplayResult.LayoutChanged("Accessibility service is not connected for macro replay.")

        val startMs = SystemClock.uptimeMillis()
        Log.i(TAG, "[$taskId] Replaying learned UI macro '${macro.normalizedCommand}' (${steps.size} steps)")

        for ((idx, step) in steps.withIndex()) {
            val stepNum = idx + 1
            val currentObs = accessibility.captureObservation()
            safetyGate.blockedByProtectedScreen(currentObs)?.let { blockedReason ->
                return MacroReplayResult.LayoutChanged(blockedReason)
            }

            AgentRuntime.setRunningStep(
                number = stepNum,
                title = "Macro Replay: ${step.toolName}",
                detail = step.fingerprint?.text?.ifBlank { step.fingerprint.contentDescription } ?: step.arguments.toString(),
            )

            val stepSuccess: Boolean
            val stepMessage: String

            val fp = step.fingerprint
            if (fp != null && step.toolName == "tap") {
                val res = accessibility.tapByFingerprint(fp)
                stepSuccess = res.success
                stepMessage = res.message
            } else if (fp != null && step.toolName == "type_text") {
                val res = accessibility.typeTextByFingerprint(
                    fp = fp,
                    text = step.arguments.optString("text"),
                    submit = step.arguments.optBoolean("submit", false),
                )
                stepSuccess = res.success
                stepMessage = res.message
            } else {
                val toolRes = executor.execute(AgentToolCall(step.toolName, step.arguments), currentObs)
                stepSuccess = toolRes.success
                stepMessage = toolRes.message
            }

            AgentRuntime.completeLastStep(stepSuccess, stepMessage)
            database.stepDao().insert(
                StepEntity(
                    taskId = taskId,
                    stepNumber = stepNum,
                    category = "macro_replay",
                    toolName = step.toolName,
                    argumentsJson = step.arguments.toString(),
                    result = stepMessage,
                    success = stepSuccess,
                ),
            )

            if (!stepSuccess) {
                Log.w(TAG, "[$taskId] Learned macro step $stepNum (${step.toolName}) failed: $stepMessage. Falling back to LLM.")
                database.learnedMacroDao().recordReplayFailure(macro.normalizedCommand)
                if (macro.failureCount + 1 >= MAX_CONSECUTIVE_FAILURES) {
                    database.learnedMacroDao().deleteByNormalizedCommand(macro.normalizedCommand)
                }
                return MacroReplayResult.LayoutChanged(stepMessage)
            }

            // Settle UI briefly between replayed steps
            accessibility.awaitWindowSettled(quietPeriodMs = 120L, maxWaitMs = 450L)
            delay(60L)
        }

        val elapsedMs = SystemClock.uptimeMillis() - startMs
        database.learnedMacroDao().recordReplaySuccess(macro.normalizedCommand)
        return MacroReplayResult.Replayed(
            summary = "${macro.finalSummary} (Replayed on-device from learned UI macro cache in ${elapsedMs}ms)",
            stepsExecuted = steps.size,
            elapsedMs = elapsedMs,
        )
    }
}
