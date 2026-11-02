package com.personal.harmaai.agent

import android.app.KeyguardManager
import android.content.Context
import android.os.SystemClock
import android.util.Base64
import com.personal.harmaai.accessibility.AgentAccessibilityService
import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.data.HarmaDatabase
import com.personal.harmaai.data.MemoryEntity
import com.personal.harmaai.data.SettingsStore
import com.personal.harmaai.data.StepEntity
import com.personal.harmaai.data.TaskEntity
import com.personal.harmaai.network.AgentConversation
import com.personal.harmaai.network.AgentLlmClient
import com.personal.harmaai.network.AgentMessage
import com.personal.harmaai.network.NvidiaAgentClient
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.permissions.PermissionNavigator
import com.personal.harmaai.tools.ToolResult
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import org.json.JSONObject
import java.io.File

class AgentOrchestrator(
    context: Context,
    private val settings: SettingsStore,
    private val database: HarmaDatabase,
    private val client: AgentLlmClient = NvidiaAgentClient(),
    private val executor: AgentToolExecutor = AgentToolExecutor(context, settings),
) {
    private val appContext = context.applicationContext
    private val keyguard = appContext.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
    private val safety = SafetyGate()
    private val localRouter = LocalCommandRouter(context)
    private val autonomousExecutor = AutonomousTaskExecutor(context, settings)

    suspend fun run(command: String, sessionId: String = "") {
        val effectiveCommand = AgentRuntime.continuationPrompt(command) ?: command
        val taskId = AgentRuntime.beginTask(command)
        val sId = sessionId.ifBlank { taskId }
        val persistedCommand = if (SECRET_PATTERN.containsMatchIn(command)) {
            "[Sensitive command redacted]"
        } else {
            command.take(MAX_PERSISTED_COMMAND_LENGTH)
        }
        database.taskDao().upsert(
            TaskEntity(id = taskId, command = persistedCommand, status = AgentStatus.RUNNING.name),
        )

        try {
            if (keyguard.isDeviceLocked) {
                finishFailure(
                    taskId,
                    "Phone is locked. Unlock it with Voice Match or your PIN, then repeat the command.",
                )
                HarmaPerf.onTaskFinished(sId, "Device locked")
                return
            }

            // Step 1: Autonomous Observe -> Plan -> Act -> Verify Execution for high-frequency deterministic tasks
            val autoResult = autonomousExecutor.tryExecute(effectiveCommand, taskId, sId)
            when (autoResult) {
                is AutonomousResult.Success -> {
                    finishSuccess(taskId, autoResult.message)
                    HarmaPerf.onTaskFinished(sId, autoResult.message)
                    return
                }
                is AutonomousResult.Failure -> {
                    finishFailure(taskId, "Task failed at Step ${autoResult.stepFailed}: ${autoResult.reason}")
                    HarmaPerf.onTaskFinished(sId, "Failed at step ${autoResult.stepFailed}")
                    return
                }
                is AutonomousResult.NotHandled -> {
                    // Fall through to local command router or LLM loop
                }
            }

            // Step 2 Fast Path: Try local command router next (for confirmation or direct tools)
            val routeResult = localRouter.tryRoute(effectiveCommand, sId)
            when (routeResult) {
                is RouterResult.Handled -> {
                    val res = routeResult.result
                    if (res.success) {
                        finishSuccess(taskId, res.message)
                    } else {
                        finishFailure(taskId, "Task failed: ${res.message}")
                    }
                    HarmaPerf.onTaskFinished(sId, routeResult.description)
                    return
                }
                is RouterResult.NeedsConfirmation -> {
                    val approved = AgentRuntime.requestConfirmation(
                        toolName = routeResult.toolName,
                        description = routeResult.userPrompt,
                        arguments = safeArguments(AgentToolCall(routeResult.toolName, routeResult.arguments)),
                    )
                    if (approved) {
                        val res = executor.execute(AgentToolCall(routeResult.toolName, routeResult.arguments), null)
                        if (res.success) finishSuccess(taskId, "Action completed with confirmation.")
                        else finishFailure(taskId, res.message)
                    } else {
                        finishFailure(taskId, "Action was rejected by user.")
                    }
                    HarmaPerf.onTaskFinished(sId, "Confirmation gate handled")
                    return
                }
                is RouterResult.NotHandled -> {
                    // Proceed to LLM loop
                }
            }

            if (settings.apiKey.isBlank()) {
                finishFailure(taskId, "Add an NVIDIA API key in Harma AI Settings first.")
                HarmaPerf.onTaskFinished(sId, "Missing NVIDIA API key")
                return
            }

            if (!checkOrAwaitAccessibility()) {
                finishFailure(taskId, "Harma AI paused: Turn on Harma AI in Accessibility settings to continue.")
                HarmaPerf.onTaskFinished(sId, "Accessibility missing")
                return
            }

            var observation = observe(sId)
            safety.blockedByProtectedScreen(observation)?.let { reason ->
                finishFailure(taskId, reason)
                HarmaPerf.onTaskFinished(sId, reason)
                return
            }
            val initialScreenshot = screenshotIfNeeded(observation, explicitlyRequested = false)
            val memory = relevantMemory()
            val history = mutableListOf<AgentMessage>(
                AgentConversation.initialMessage(
                    effectiveCommand,
                    observation,
                    initialScreenshot,
                    memory,
                ),
            )
            val successfulConsequentialActions = mutableSetOf<String>()
            var lastFailedFingerprint = ""
            var repeatedFailureCount = 0
            var lastActionScreenSignature = ""
            var loopDetectedCount = 0
            var fallbackNoticeShown = false
            var invalidCompletionCount = 0

            for (stepNumber in 1..settings.maxSteps) {
                currentCoroutineContext().ensureActive()
                if (keyguard.isDeviceLocked) {
                    finishFailure(
                        taskId,
                        "Phone is locked. Unlock it, then repeat the command.",
                    )
                    HarmaPerf.onTaskFinished(sId, "Phone locked during execution")
                    return
                }

                val decision = client.decide(
                    apiKey = settings.apiKey,
                    models = settings.modelChain(),
                    history = trimmedHistory(history),
                    tools = executor.specs,
                    sessionId = sId,
                )
                if (decision.fallbackFrom != null && !fallbackNoticeShown) {
                    AgentRuntime.addSystemMessage(
                        "${decision.fallbackFrom} was unavailable, so Harma AI used ${decision.modelUsed}.",
                    )
                    fallbackNoticeShown = true
                }
                history += decision.assistantMessage

                val providerCall = decision.toolCall
                if (providerCall == null) {
                    invalidCompletionCount += 1
                    if (invalidCompletionCount >= MAX_INVALID_COMPLETIONS) {
                        finishFailure(
                            taskId,
                            "The NVIDIA model stopped without using the finish tool, so Harma AI could not verify completion.",
                        )
                        HarmaPerf.onTaskFinished(sId, "Model stopped without finish tool")
                        return
                    }
                    history += AgentMessage.User(
                        buildString {
                            append("Do not end the task with plain text. ")
                            append("Inspect the latest evidence and call exactly one tool. ")
                            append("Use finish only after the requested result is verified.")
                            if (decision.text.isNotBlank()) {
                                append(" Your previous unverified response was: ")
                                append(decision.text.take(MAX_UNVERIFIED_TEXT_LENGTH))
                            }
                        },
                    )
                    continue
                }
                invalidCompletionCount = 0
                val call = providerCall.asAgentToolCall()

                // Step 7 Loop Detection: Detect repeated actions on unchanged screens
                val currentScreenSig = observation?.compactJson?.hashCode() ?: 0
                val currentActionSig = "${call.name}:${call.arguments}:$currentScreenSig"
                if (currentActionSig == lastActionScreenSignature) {
                    loopDetectedCount += 1
                    if (loopDetectedCount >= 2) {
                        finishFailure(taskId, "Harma AI detected a loop: The action had no effect on the current screen.")
                        HarmaPerf.onTaskFinished(sId, "Loop detected")
                        return
                    }
                } else {
                    lastActionScreenSignature = currentActionSig
                    loopDetectedCount = 0
                }

                if (call.name in SCREEN_TOOLS) {
                    if (!checkOrAwaitAccessibility()) {
                        finishFailure(taskId, "Harma AI paused: Turn on Harma AI in Accessibility settings to continue.")
                        return
                    }
                }

                AgentRuntime.setRunningStep(
                    number = stepNumber,
                    title = readableToolName(call.name),
                    detail = safeArguments(call),
                )

                val fingerprint = call.fingerprint()
                val toolStart = SystemClock.uptimeMillis()
                val rawResult = if (
                    call.name in CONSEQUENTIAL_TOOLS &&
                    fingerprint in successfulConsequentialActions
                ) {
                    ToolResult.success(
                        "This consequential action was already completed once and was not repeated.",
                    )
                } else {
                    executor.execute(call, observation)
                }
                val toolElapsed = SystemClock.uptimeMillis() - toolStart
                HarmaPerf.onToolExecution(sId, call.name, toolElapsed, rawResult.success)

                if (rawResult.success && call.name in CONSEQUENTIAL_TOOLS) {
                    successfulConsequentialActions += fingerprint
                }

                val modifiesScreen = call.name !in setOf("set_flashlight", "set_volume", "set_ringer_mode", "set_clipboard") &&
                    !(call.name == "open_app" && rawResult.success)

                if (modifiesScreen) {
                    val waitStart = SystemClock.uptimeMillis()
                    AgentAccessibilityService.current()?.awaitWindowSettled(
                        quietPeriodMs = settings.stepDelayMs.coerceAtMost(150L),
                        maxWaitMs = 500L,
                    ) ?: delay(settings.stepDelayMs)
                    HarmaPerf.onWaitAfterAction(sId, SystemClock.uptimeMillis() - waitStart, "window_settled")
                }

                observation = observe(sId)
                val result = verifyObservedResult(call, rawResult, observation)
                if (!result.success && fingerprint == lastFailedFingerprint) {
                    repeatedFailureCount += 1
                } else if (!result.success) {
                    lastFailedFingerprint = fingerprint
                    repeatedFailureCount = 1
                } else {
                    lastFailedFingerprint = ""
                    repeatedFailureCount = 0
                }
                val protectedReason = safety.blockedByProtectedScreen(observation)
                val screenshot = if (protectedReason == null) {
                    screenshotIfNeeded(
                        observation,
                        explicitlyRequested = call.name == "take_screenshot" ||
                            result.data.optBoolean("include_screenshot", false),
                    )
                } else {
                    ""
                }
                AgentRuntime.completeLastStep(result.success, result.message, screenshot)
                val screenshotPath = saveScreenshot(taskId, stepNumber, screenshot)
                database.stepDao().insert(
                    StepEntity(
                        taskId = taskId,
                        stepNumber = stepNumber,
                        category = "tool",
                        toolName = call.name,
                        argumentsJson = safeArguments(call),
                        result = result.message,
                        success = result.success,
                        screenshotPath = screenshotPath,
                    ),
                )

                if (protectedReason != null) {
                    finishFailure(taskId, protectedReason)
                    return
                }
                if (result.finished) {
                    if (result.success) {
                        if (isPrematureFinish(effectiveCommand, history)) {
                            history += AgentMessage.User(
                                "Navigating to the app is only Step 1. The requested goal ('$effectiveCommand') is not yet completed. Look at the current screen observation and execute the next action."
                            )
                            continue
                        }
                        finishSuccess(taskId, result.message)
                    } else {
                        finishFailure(taskId, result.message)
                    }
                    return
                }
                if (result.askUser) {
                    AgentRuntime.waitForUser(result.message)
                    database.taskDao().finish(
                        taskId,
                        AgentStatus.WAITING_FOR_USER.name,
                        result.message,
                        System.currentTimeMillis(),
                    )
                    return
                }

                history += AgentConversation.toolResultMessages(
                    call = providerCall,
                    result = result,
                    observation = observation,
                    screenshotBase64 = screenshot,
                )
                if (repeatedFailureCount >= 3) {
                    finishFailure(
                        taskId,
                        "Harma AI stopped after the same action failed three times: ${result.message}",
                    )
                    return
                }
            }

            finishFailure(taskId, "Harma AI reached the ${settings.maxSteps}-step safety limit.")
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            database.taskDao().finish(
                taskId,
                AgentStatus.STOPPED.name,
                "Stopped by the user.",
                System.currentTimeMillis(),
            )
            throw cancelled
        } catch (error: Exception) {
            finishFailure(taskId, "Harma AI could not complete the task: ${error.message ?: error.javaClass.simpleName}")
        }
    }

    private fun observe(sessionId: String = ""): ScreenObservation? =
        AgentAccessibilityService.current()?.captureObservation(sessionId = sessionId)

    private suspend fun screenshotIfNeeded(
        observation: ScreenObservation?,
        explicitlyRequested: Boolean,
    ): String {
        if (!settings.visionEnabled) return ""
        val shouldCapture = explicitlyRequested ||
            (observation != null && !observation.protectedContent && observation.usableNodeCount < 6)
        if (!shouldCapture) return ""
        return AgentAccessibilityService.current()
            ?.captureScreenshot()
            ?.takeIf { it.success }
            ?.jpegBase64
            .orEmpty()
    }

    private suspend fun relevantMemory(): String = database.memoryDao().getRelevant(12)
        .filterNot { SECRET_PATTERN.containsMatchIn("${it.memoryKey} ${it.value}") }
        .joinToString("\n") { "${it.memoryKey}: ${it.value}" }
        .take(1_500)

    private fun verifyObservedResult(
        call: AgentToolCall,
        result: ToolResult,
        observation: ScreenObservation?,
    ): ToolResult {
        if (!result.success || result.finished || result.askUser || observation == null) return result
        if (call.name != "open_app" || result.code != "dispatched") return result

        val expectedPackage = result.data.optString("expected_package").trim()
        if (expectedPackage.isBlank()) return result
        val observedPackage = observation.packageName.trim()
        val evidence = JSONObject(result.data.toString())
            .put("observed_package", observedPackage)
        return if (observedPackage == expectedPackage) {
            ToolResult.verified(
                "Opened ${call.arguments.optString("name").ifBlank { expectedPackage }} and verified the foreground app.",
                evidence,
                method = "accessibility_foreground_package",
            )
        } else {
            ToolResult.failure(
                "Android accepted the app launch, but the foreground package is '${observedPackage.ifBlank { "unknown" }}' instead of '$expectedPackage'.",
                evidence,
            )
        }
    }

    private fun isPrematureFinish(
        command: String,
        history: List<AgentMessage>,
    ): Boolean {
        val lower = command.lowercase()
        val actionKeywords = listOf(
            "search", "find", "play", "call", "send", "message", "write", "text", "photo", "picture", "buy", "order", "type"
        )
        val requiresDeepAction = actionKeywords.any { lower.contains(it) }
        if (!requiresDeepAction) return false

        val assistantCalls = history.filterIsInstance<AgentMessage.Assistant>().flatMap { it.toolCalls }
        val executedNames = assistantCalls.map { it.name }
        val interactionTools = setOf("tap", "tap_xy", "type_text", "take_photo", "make_call", "send_sms", "scroll")
        val hasInteracted = executedNames.any { it in interactionTools }
        return !hasInteracted && executedNames.contains("open_app")
    }

    private fun trimmedHistory(history: List<AgentMessage>): List<AgentMessage> {
        val selected = if (history.size <= MAX_HISTORY_MESSAGES) {
            history
        } else {
            var start = (history.size - (MAX_HISTORY_MESSAGES - 1)).coerceAtLeast(1)
            if (history[start] is AgentMessage.Tool && start > 1) start -= 1
            listOf(history.first()) + history.subList(start, history.size)
        }
        val latestImageIndex = selected.indexOfLast {
            it is AgentMessage.User && it.jpegBase64.isNotBlank()
        }
        return selected.mapIndexed { index, message ->
            if (message is AgentMessage.User && index != latestImageIndex) {
                message.copy(jpegBase64 = "")
            } else {
                message
            }
        }
    }

    private fun saveScreenshot(taskId: String, step: Int, base64: String): String? {
        if (base64.isBlank()) return null
        return runCatching {
            val directory = File(appContext.filesDir, "agent_screenshots").apply { mkdirs() }
            val file = File(directory, "$taskId-$step.jpg")
            file.writeBytes(Base64.decode(base64, Base64.DEFAULT))
            directory.listFiles()
                .orEmpty()
                .sortedByDescending(File::lastModified)
                .drop(MAX_RETAINED_SCREENSHOTS)
                .forEach(File::delete)
            file.absolutePath
        }.getOrNull()
    }

    private suspend fun finishSuccess(taskId: String, summary: String) {
        AgentRuntime.finish(summary)
        database.taskDao().finish(
            taskId,
            AgentStatus.COMPLETED.name,
            summary,
            System.currentTimeMillis(),
        )
        if (!SECRET_PATTERN.containsMatchIn(summary)) {
            runCatching {
                database.memoryDao().upsert(
                    MemoryEntity(
                        memoryKey = "recent_task_${System.currentTimeMillis()}",
                        value = summary.take(500),
                        importance = 1,
                    ),
                )
            }
        }
    }

    private suspend fun checkOrAwaitAccessibility(): Boolean {
        if (AgentAccessibilityService.isConnected()) return true

        AgentRuntime.addSystemMessage("Turn on Harma AI in Accessibility settings to continue.")
        AgentRuntime.setRunningStep(
            number = 0,
            title = "Waiting for Accessibility",
            detail = "Turn on Harma AI in Accessibility settings",
        )
        PermissionNavigator.openAccessibility(appContext)

        val waitStart = SystemClock.uptimeMillis()
        val maxWaitMs = 120_000L
        while (!AgentAccessibilityService.isConnected()) {
            delay(500L)
            currentCoroutineContext().ensureActive()
            if (SystemClock.uptimeMillis() - waitStart > maxWaitMs) {
                return false
            }
        }
        AgentRuntime.addSystemMessage("Accessibility connected. Resuming task...")
        delay(400L)
        return true
    }

    private suspend fun finishFailure(taskId: String, message: String) {
        AgentRuntime.fail(message)
        database.taskDao().finish(
            taskId,
            AgentStatus.FAILED.name,
            message,
            System.currentTimeMillis(),
        )
    }

    private fun readableToolName(name: String): String = when (name) {
        "set_flashlight" -> "Changing flashlight"
        "open_app" -> "Opening app"
        "tap" -> "Tapping screen element"
        "tap_xy" -> "Tapping screen"
        "type_text" -> "Entering text"
        "finish" -> "Verifying completion"
        else -> name.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }

    private fun safeArguments(call: AgentToolCall): String = when (call.name) {
        "type_text", "set_clipboard" -> JSONObject(call.arguments.toString()).apply {
            if (has("text")) put("text", "[redacted]")
        }.toString()
        else -> call.arguments.toString()
    }

    companion object {
        private val SCREEN_TOOLS = setOf(
            "get_screen",
            "tap",
            "tap_xy",
            "long_press",
            "type_text",
            "scroll",
            "take_screenshot",
        )
        private val CONSEQUENTIAL_TOOLS = setOf("make_call", "send_sms", "set_alarm", "set_timer")
        private val SECRET_PATTERN = Regex("(?i)password|otp|one.?time|pin|card|cvv|secret|token")
        private const val MAX_HISTORY_MESSAGES = 18
        private const val MAX_INVALID_COMPLETIONS = 3
        private const val MAX_UNVERIFIED_TEXT_LENGTH = 400
        private const val MAX_PERSISTED_COMMAND_LENGTH = 2_000
        private const val MAX_RETAINED_SCREENSHOTS = 40
    }
}
