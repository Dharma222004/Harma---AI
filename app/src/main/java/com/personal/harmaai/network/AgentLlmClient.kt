package com.personal.harmaai.network

import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.agent.AgentToolCall
import com.personal.harmaai.tools.ToolResult
import com.personal.harmaai.tools.ToolSpec
import org.json.JSONObject

/**
 * Provider-neutral conversation state. Provider-specific JSON must stay inside the network
 * adapter so the orchestrator can switch models without changing its execution protocol.
 */
sealed interface AgentMessage {
    data class User(
        val text: String,
        val jpegBase64: String = "",
    ) : AgentMessage

    data class Assistant(
        val text: String = "",
        val toolCalls: List<AgentLlmToolCall> = emptyList(),
        /** Kept only so providers that require it can receive it on the next turn. */
        internal val reasoningContent: String = "",
    ) : AgentMessage {
        override fun toString(): String =
            "Assistant(text=$text, toolCalls=$toolCalls, reasoningContent=[redacted])"
    }

    data class Tool(
        val toolCallId: String,
        val toolName: String,
        val content: String,
    ) : AgentMessage
}

data class AgentLlmToolCall(
    val id: String,
    val name: String,
    val arguments: JSONObject,
) {
    fun asAgentToolCall(): AgentToolCall = AgentToolCall(name = name, arguments = arguments)
}

data class AgentDecision(
    val text: String,
    val toolCall: AgentLlmToolCall?,
    val assistantMessage: AgentMessage.Assistant,
    val modelUsed: String,
    val finishReason: String = "",
    val fallbackFrom: String? = null,
)

interface AgentLlmClient {
    suspend fun decide(
        apiKey: String,
        models: List<String>,
        history: List<AgentMessage>,
        tools: List<ToolSpec>,
        sessionId: String = "",
    ): AgentDecision
}

object AgentConversation {
    private fun formatObservation(observation: ScreenObservation?): String {
        if (observation == null) return "Accessibility service is not connected."
        return observation.compactText.ifBlank { observation.compactJson }
    }

    fun initialMessage(
        task: String,
        observation: ScreenObservation?,
        screenshotBase64: String = "",
        memory: String = "",
    ): AgentMessage.User = AgentMessage.User(
        text = buildString {
            append("User task: ").append(task)
            if (memory.isNotBlank()) append("\nRelevant local memory:\n").append(memory)
            append("\nCurrent phone observation:\n")
            append(formatObservation(observation))
        },
        jpegBase64 = screenshotBase64,
    )

    /**
     * OpenAI-compatible providers require a tool result whose tool_call_id exactly matches the
     * assistant call. A following user message carries an updated screenshot when vision is used.
     */
    fun toolResultMessages(
        call: AgentLlmToolCall,
        result: ToolResult,
        observation: ScreenObservation?,
        screenshotBase64: String = "",
    ): List<AgentMessage> {
        val payload = JSONObject()
            .put("success", result.success)
            .put("message", result.message)
            .put("code", result.code)
            .put("data", result.data)
            .put(
                "newScreen",
                formatObservation(observation),
            )

        return buildList {
            add(
                AgentMessage.Tool(
                    toolCallId = call.id,
                    toolName = call.name,
                    content = payload.toString(),
                ),
            )
            if (screenshotBase64.isNotBlank()) {
                add(
                    AgentMessage.User(
                        text = "Updated phone screenshot (with numbered [id] Set-of-Marks) after ${call.name}. Use it with the tool result and accessibility observation to verify the next action.",
                        jpegBase64 = screenshotBase64,
                    ),
                )
            }
        }
    }
}
