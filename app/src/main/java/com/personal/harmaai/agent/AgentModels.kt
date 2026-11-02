package com.personal.harmaai.agent

import org.json.JSONObject
import java.util.UUID

enum class AgentStatus {
    IDLE,
    RUNNING,
    WAITING_FOR_CONFIRMATION,
    WAITING_FOR_USER,
    COMPLETED,
    FAILED,
    STOPPED,
}

enum class ChatAuthor {
    USER,
    HARMA,
    SYSTEM,
}

data class HarmaMessage(
    val id: String = UUID.randomUUID().toString(),
    val author: ChatAuthor,
    val text: String,
    val timestamp: Long = System.currentTimeMillis(),
    val isVoice: Boolean = false,
)

data class AgentStep(
    val id: String = UUID.randomUUID().toString(),
    val number: Int,
    val title: String,
    val detail: String,
    val success: Boolean? = null,
    val screenshotBase64: String = "",
    val timestamp: Long = System.currentTimeMillis(),
)

data class PendingConfirmation(
    val id: String = UUID.randomUUID().toString(),
    val toolName: String,
    val description: String,
    val arguments: String,
)

data class AgentUiState(
    val status: AgentStatus = AgentStatus.IDLE,
    val taskId: String = "",
    val currentTask: String = "",
    val currentStep: String = "Ready",
    val stepNumber: Int = 0,
    val messages: List<HarmaMessage> = listOf(
        HarmaMessage(
            author = ChatAuthor.HARMA,
            text = "I’m Harma AI. Give me a phone task and I’ll use direct Android tools or the current screen to complete it.",
        ),
    ),
    val steps: List<AgentStep> = emptyList(),
    val pendingConfirmation: PendingConfirmation? = null,
    val lastError: String = "",
    val isVoiceListening: Boolean = false,
    val voiceStateText: String = "",
    val liveWakeWordScore: Float = 0f,
    val wakeWordThreshold: Float = 0.5f,
    val liveRmsDb: Float = 0f,
)

data class AgentToolCall(
    val name: String,
    val arguments: JSONObject,
) {
    fun fingerprint(): String = "$name:${canonical(arguments)}"

    companion object {
        private fun canonical(value: Any?): String = when (value) {
            is JSONObject -> value.keys().asSequence().sorted().joinToString(",", "{", "}") { key ->
                "${JSONObject.quote(key)}:${canonical(value.opt(key))}"
            }
            is org.json.JSONArray -> (0 until value.length()).joinToString(",", "[", "]") {
                canonical(value.opt(it))
            }
            null, JSONObject.NULL -> "null"
            is String -> JSONObject.quote(value)
            else -> value.toString()
        }
    }
}
