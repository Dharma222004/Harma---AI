package com.personal.harmaai.agent

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.util.UUID

object AgentRuntime {
    private val mutableState = MutableStateFlow(AgentUiState())
    val state: StateFlow<AgentUiState> = mutableState.asStateFlow()

    @Volatile
    private var confirmationDeferred: CompletableDeferred<Boolean>? = null

    /**
     * Carries an answer back into a task that paused through ask_user. This is intentionally
     * in-memory: after process death Harma AI must ask the owner to restate the task rather than
     * silently reconstructing a potentially sensitive workflow.
     */
    fun continuationPrompt(answer: String): String? {
        val current = mutableState.value
        if (current.status != AgentStatus.WAITING_FOR_USER) return null
        val question = current.messages.lastOrNull { it.author == ChatAuthor.HARMA }?.text.orEmpty()
        if (current.currentTask.isBlank() || question.isBlank()) return null
        return buildString {
            append("Continue the paused phone task.\nOriginal task: ")
            append(current.currentTask.take(1_000))
            append("\nQuestion previously asked: ")
            append(question.take(600))
            append("\nUser answer: ")
            append(answer.take(1_000))
            append("\nRe-observe the current phone state before taking the next action.")
        }
    }

    fun beginTask(command: String): String {
        confirmationDeferred?.cancel()
        confirmationDeferred = null
        val taskId = UUID.randomUUID().toString()
        mutableState.update { current ->
            current.copy(
                status = AgentStatus.RUNNING,
                taskId = taskId,
                currentTask = command,
                currentStep = "Understanding your request",
                stepNumber = 0,
                steps = emptyList(),
                pendingConfirmation = null,
                lastError = "",
                messages = current.messages + HarmaMessage(author = ChatAuthor.USER, text = command),
            )
        }
        return taskId
    }

    fun setRunningStep(number: Int, title: String, detail: String = "") {
        mutableState.update {
            it.copy(
                status = AgentStatus.RUNNING,
                stepNumber = number,
                currentStep = title,
                steps = it.steps + AgentStep(number = number, title = title, detail = detail),
            )
        }
    }

    fun completeLastStep(success: Boolean, result: String, screenshotBase64: String = "") {
        mutableState.update { state ->
            val updated = state.steps.toMutableList()
            if (updated.isNotEmpty()) {
                val last = updated.last()
                updated[updated.lastIndex] = last.copy(
                    detail = listOf(last.detail, result).filter { it.isNotBlank() }.joinToString("\n"),
                    success = success,
                    screenshotBase64 = screenshotBase64,
                )
            }
            state.copy(steps = updated)
        }
    }

    fun addSystemMessage(message: String) {
        mutableState.update {
            it.copy(messages = it.messages + HarmaMessage(author = ChatAuthor.SYSTEM, text = message))
        }
    }

    fun addVoiceUserMessage(text: String) {
        mutableState.update {
            it.copy(messages = it.messages + HarmaMessage(author = ChatAuthor.USER, text = text, isVoice = true))
        }
    }

    fun setVoiceListening(listening: Boolean, statusText: String = "") {
        mutableState.update {
            it.copy(isVoiceListening = listening, voiceStateText = statusText)
        }
    }

    fun setLiveWakeWordScore(score: Float, threshold: Float) {
        mutableState.update {
            it.copy(liveWakeWordScore = score, wakeWordThreshold = threshold)
        }
    }

    fun setLiveRms(rms: Float) {
        mutableState.update {
            it.copy(liveRmsDb = rms)
        }
    }

    fun addHarmaMessage(message: String) {
        mutableState.update {
            it.copy(messages = it.messages + HarmaMessage(author = ChatAuthor.HARMA, text = message))
        }
    }

    suspend fun requestConfirmation(
        toolName: String,
        description: String,
        arguments: String,
    ): Boolean {
        val pending = PendingConfirmation(
            toolName = toolName,
            description = description,
            arguments = arguments,
        )
        val deferred = CompletableDeferred<Boolean>()
        confirmationDeferred = deferred
        mutableState.update {
            it.copy(
                status = AgentStatus.WAITING_FOR_CONFIRMATION,
                currentStep = "Waiting for your confirmation",
                pendingConfirmation = pending,
            )
        }
        return try {
            deferred.await()
        } finally {
            confirmationDeferred = null
            mutableState.update {
                it.copy(
                    status = if (it.status == AgentStatus.STOPPED) AgentStatus.STOPPED else AgentStatus.RUNNING,
                    pendingConfirmation = null,
                )
            }
        }
    }

    fun respondToConfirmation(approved: Boolean) {
        confirmationDeferred?.complete(approved)
    }

    fun waitForUser(question: String) {
        addHarmaMessage(question)
        mutableState.update {
            it.copy(
                status = AgentStatus.WAITING_FOR_USER,
                currentStep = "Waiting for your answer",
            )
        }
    }

    fun finish(summary: String) {
        addHarmaMessage(summary)
        mutableState.update {
            it.copy(
                status = AgentStatus.COMPLETED,
                currentStep = "Completed",
                pendingConfirmation = null,
            )
        }
    }

    fun fail(message: String) {
        addHarmaMessage(message)
        mutableState.update {
            it.copy(
                status = AgentStatus.FAILED,
                currentStep = "Failed",
                lastError = message,
                pendingConfirmation = null,
            )
        }
    }

    fun stop(message: String = "Stopped by you.") {
        confirmationDeferred?.complete(false)
        confirmationDeferred = null
        addHarmaMessage(message)
        mutableState.update {
            it.copy(
                status = AgentStatus.STOPPED,
                currentStep = "Stopped",
                pendingConfirmation = null,
            )
        }
    }
}
