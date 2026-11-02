package com.personal.harmaai.agent

import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.tools.ToolRisk
import com.personal.harmaai.tools.ToolSpec
import org.json.JSONObject

class SafetyGate {
    fun blockedByProtectedScreen(observation: ScreenObservation?): String? {
        if (observation == null) return null
        if (observation.protectedContent) {
            return "A password or protected field is visible. Harma AI paused so you can complete it manually."
        }
        val screenText = observation.nodes.joinToString(" ") {
            "${it.text} ${it.contentDescription} ${it.viewId}"
        }
        if (SECRET_PATTERN.containsMatchIn(screenText)) {
            return "A login, OTP, PIN, card, or authentication screen may be visible. Harma AI will not read or enter secrets."
        }
        return null
    }

    fun needsConfirmation(
        spec: ToolSpec,
        arguments: JSONObject,
        observation: ScreenObservation?,
        confirmationsEnabled: Boolean,
    ): Boolean {
        if (spec.risk == ToolRisk.HIGH_RISK) return true
        if (spec.name in ALWAYS_CONFIRM_TOOLS) return true
        if (confirmationsEnabled && spec.risk == ToolRisk.SENSITIVE) return true
        if (spec.name in setOf("tap", "tap_xy")) {
            val targetText = if (spec.name == "tap") {
                val index = arguments.optInt("index", -1)
                observation?.nodes?.firstOrNull { it.index == index }?.let {
                    "${it.text} ${it.contentDescription} ${it.viewId}"
                }.orEmpty()
            } else {
                arguments.optString("purpose")
            }
            return SENSITIVE_ACTION_PATTERN.containsMatchIn(targetText)
        }
        return false
    }

    fun confirmationDescription(spec: ToolSpec): String = when (spec.name) {
        "send_sms" -> "Send this SMS now?"
        "make_call" -> "Place this phone call now?"
        "tap", "tap_xy" -> "Harma AI is about to activate a sensitive on-screen action. Continue?"
        else -> "Allow Harma AI to perform the sensitive action '${spec.name}'?"
    }

    companion object {
        private val SECRET_PATTERN = Regex(
            "(?i)password|passcode|one.?time password|otp|verification code|security code|cvv|card number|upi pin|enter pin|biometric|fingerprint",
        )
        private val SENSITIVE_ACTION_PATTERN = Regex(
            "(?i)send|pay|transfer|delete|remove|purchase|buy|order|confirm|install|uninstall|submit payment|place call",
        )
        private val ALWAYS_CONFIRM_TOOLS = setOf("send_sms", "make_call")
    }
}
