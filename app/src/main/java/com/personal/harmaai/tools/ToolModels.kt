package com.personal.harmaai.tools

import org.json.JSONObject

enum class ToolRisk {
    SAFE,
    SENSITIVE,
    HIGH_RISK,
}

data class ToolCall(
    val name: String,
    val arguments: JSONObject = JSONObject(),
)

data class ToolResult(
    val success: Boolean,
    val message: String,
    val data: JSONObject = JSONObject(),
    val code: String = if (success) "success" else "failure",
    val finished: Boolean = false,
    val askUser: Boolean = false,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("success", success)
        .put("code", code)
        .put("message", message)
        .put("data", data)
        .put("finished", finished)
        .put("ask_user", askUser)

    companion object {
        fun success(message: String, data: JSONObject = JSONObject()) =
            ToolResult(true, message, data, "success")

        /**
         * A state-changing operation whose result was read back from Android or hardware.
         * The evidence travels with the tool response so the agent can distinguish verified
         * state from an intent/API request that merely returned without throwing.
         */
        fun verified(
            message: String,
            data: JSONObject = JSONObject(),
            method: String,
        ) = ToolResult(
            success = true,
            message = message,
            data = withEvidence(data, state = "verified", method = method),
            code = "verified",
        )

        /**
         * The request was accepted locally, but a later screen/device observation must verify
         * the user's goal. This intentionally avoids wording a dispatch as completed work.
         */
        fun dispatched(
            message: String,
            data: JSONObject = JSONObject(),
            method: String = "android_dispatch",
        ) = ToolResult(
            success = true,
            message = message,
            data = withEvidence(data, state = "dispatched", method = method),
            code = "dispatched",
        )

        fun failure(message: String, data: JSONObject = JSONObject()) =
            ToolResult(false, message, data, "failure")

        fun permission(permission: String, message: String): ToolResult = ToolResult(
            success = false,
            message = message,
            data = JSONObject().put("permission", permission),
            code = "permission_required",
        )

        fun userAction(action: String, message: String): ToolResult = ToolResult(
            success = false,
            message = message,
            data = JSONObject().put("settings_action", action),
            code = "user_action_required",
            askUser = true,
        )

        private fun withEvidence(
            data: JSONObject,
            state: String,
            method: String,
        ): JSONObject = JSONObject(data.toString())
            .put("execution_state", state)
            .put("verification_method", method)
    }
}

data class ToolSpec(
    val name: String,
    val description: String,
    val risk: ToolRisk,
    val parameters: JSONObject,
) {
    /** OpenAI-compatible tool object used by NVIDIA NIM chat-completions. */
    fun toOpenAiTool(): JSONObject = JSONObject()
        .put("type", "function")
        .put(
            "function",
            JSONObject()
                .put("name", name)
                .put("description", description)
                .put("parameters", parameters),
        )

    /** Provider-neutral function body, also accepted by Gemini function declarations. */
    fun toFunctionDeclaration(): JSONObject = JSONObject()
        .put("name", name)
        .put("description", description)
        .put("parameters", parameters)

    @Deprecated("Use toFunctionDeclaration or toOpenAiTool")
    fun toGeminiDeclaration(): JSONObject = JSONObject()
        .put("name", name)
        .put("description", description)
        .put("parameters", parameters)
}
