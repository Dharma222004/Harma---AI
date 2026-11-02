package com.personal.harmaai.agent

import android.content.Context
import com.personal.harmaai.accessibility.AgentAccessibilityService
import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.data.SettingsStore
import com.personal.harmaai.tools.ToolRegistry
import com.personal.harmaai.tools.ToolResult
import com.personal.harmaai.tools.ToolRisk
import com.personal.harmaai.tools.ToolSpec
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject

class AgentToolExecutor(
    context: Context,
    private val settings: SettingsStore,
    private val safetyGate: SafetyGate = SafetyGate(),
) {
    private val appContext = context.applicationContext
    private val directTools = ToolRegistry(appContext)
    private val allSpecs = directTools.specs + ACCESSIBILITY_SPECS
    private val specsByName = allSpecs.associateBy(ToolSpec::name)

    val specs: List<ToolSpec> get() = allSpecs

    suspend fun execute(
        call: AgentToolCall,
        observation: ScreenObservation?,
    ): ToolResult {
        val spec = specsByName[call.name]
            ?: return ToolResult.failure("Unknown tool '${call.name}'.")

        appPolicyFailure(call, observation)?.let { return ToolResult.failure(it) }

        if (call.name in PROTECTED_SCREEN_ACTIONS) {
            safetyGate.blockedByProtectedScreen(observation)?.let { blocked ->
                return ToolResult.failure(blocked)
            }
        }

        if (
            safetyGate.needsConfirmation(
                spec,
                call.arguments,
                observation,
                settings.confirmationsEnabled,
            )
        ) {
            val approved = AgentRuntime.requestConfirmation(
                toolName = call.name,
                description = safetyGate.confirmationDescription(spec),
                arguments = safeArguments(call),
            )
            if (!approved) return ToolResult.failure("The user rejected ${call.name}.")
        }

        if (directTools.find(call.name) != null) {
            val result = directTools.execute(call.name, call.arguments)
            if (call.name == "open_app" && result.success) {
                val expectedPkg = result.data.optString("expected_package")
                if (expectedPkg.isNotBlank()) {
                    AgentAccessibilityService.current()?.awaitForegroundPackage(expectedPkg)
                }
            }
            return result
        }

        val accessibility = AgentAccessibilityService.current()
        return when (call.name) {
            "get_screen" -> {
                if (accessibility == null) {
                    return ToolResult.failure("Accessibility service is not enabled. Please enable Harma AI in Android Accessibility settings.")
                }
                val screen = accessibility.captureObservation()
                if (screen.unavailable && screen.protectedContent) {
                    return ToolResult.success(
                        "Screen content is protected by system security (FLAG_SECURE, such as payment or UPI PIN screen). Harma AI will not read or enter credentials.",
                        JSONObject().put("protected", true).put("screen", screen.compactJson),
                    )
                }
                ToolResult.success("Current screen captured.", JSONObject().put("screen", screen.compactJson))
            }

            "tap" -> accessibilityResult(
                accessibility,
                accessibility?.tapNode(call.arguments.optInt("index", -1)),
            )

            "click_text" -> accessibilityResult(
                accessibility,
                accessibility?.clickByText(call.arguments.optString("text")),
            )

            "click_id" -> accessibilityResult(
                accessibility,
                accessibility?.clickById(call.arguments.optString("id")),
            )

            "click_desc" -> accessibilityResult(
                accessibility,
                accessibility?.clickByContentDescription(call.arguments.optString("desc")),
            )

            "scroll_to_find" -> accessibilityResult(
                accessibility,
                accessibility?.scrollToFind(call.arguments.optString("text")),
            )

            "wait_for" -> {
                val target = call.arguments.optString("text").ifBlank { call.arguments.optString("package") }
                val timeout = call.arguments.optLong("timeout", 5000L).coerceIn(1000L, 10000L)
                val inFg = accessibility?.awaitForegroundPackage(target, timeout) ?: false
                if (inFg) {
                    ToolResult.success("Waited and found '$target'.")
                } else {
                    ToolResult.failure("Timed out waiting for '$target'.")
                }
            }

            "tap_xy" -> accessibilityResult(
                accessibility,
                accessibility?.tapCoordinates(
                    call.arguments.optDouble("x", -1.0).toFloat(),
                    call.arguments.optDouble("y", -1.0).toFloat(),
                ),
            )

            "long_press" -> accessibilityResult(
                accessibility,
                accessibility?.longPress(
                    call.arguments.optDouble("x", -1.0).toFloat(),
                    call.arguments.optDouble("y", -1.0).toFloat(),
                    call.arguments.optLong("duration_ms", 800L),
                ),
            )

            "type_text" -> accessibilityResult(
                accessibility,
                accessibility?.setNodeText(
                    call.arguments.optInt("index", -1),
                    call.arguments.optString("text"),
                ),
            )

            "scroll" -> accessibilityResult(
                accessibility,
                accessibility?.scrollNode(
                    call.arguments.optInt("index", -1).takeIf { it >= 0 },
                    call.arguments.optString("direction", "down"),
                ),
            )

            "swipe" -> {
                if (accessibility == null) return ToolResult.failure("Accessibility service is not enabled.")
                val metrics = appContext.resources.displayMetrics
                val direction = call.arguments.optString("direction", "up").lowercase()
                val defaults = when (direction) {
                    "down" -> floatArrayOf(metrics.widthPixels * .5f, metrics.heightPixels * .3f, metrics.widthPixels * .5f, metrics.heightPixels * .78f)
                    "left" -> floatArrayOf(metrics.widthPixels * .8f, metrics.heightPixels * .5f, metrics.widthPixels * .2f, metrics.heightPixels * .5f)
                    "right" -> floatArrayOf(metrics.widthPixels * .2f, metrics.heightPixels * .5f, metrics.widthPixels * .8f, metrics.heightPixels * .5f)
                    else -> floatArrayOf(metrics.widthPixels * .5f, metrics.heightPixels * .78f, metrics.widthPixels * .5f, metrics.heightPixels * .3f)
                }
                val result = accessibility.swipe(
                    call.arguments.optDouble("x1", defaults[0].toDouble()).toFloat(),
                    call.arguments.optDouble("y1", defaults[1].toDouble()).toFloat(),
                    call.arguments.optDouble("x2", defaults[2].toDouble()).toFloat(),
                    call.arguments.optDouble("y2", defaults[3].toDouble()).toFloat(),
                    call.arguments.optLong("duration_ms", 450L),
                )
                ToolResult(result.success, result.message)
            }

            "press", "press_key" -> {
                val key = call.arguments.optString("key").ifBlank { call.arguments.optString("action") }
                when (key.lowercase()) {
                    "enter", "search" -> {
                        // Focus + ime search or coordinates
                        val ok = accessibility?.performGlobal("back") != null
                        ToolResult.success("Pressed $key.")
                    }
                    else -> accessibilityResult(
                        accessibility,
                        accessibility?.performGlobal(key),
                    )
                }
            }

            "wait" -> {
                val waitMs = call.arguments.optLong("milliseconds", 700L).coerceIn(100L, 10_000L)
                delay(waitMs)
                ToolResult.success("Waited ${waitMs}ms.")
            }

            "take_screenshot", "screenshot" -> {
                if (accessibility == null) return ToolResult.failure("Accessibility service is not enabled.")
                val screenshot = accessibility.captureScreenshot()
                if (screenshot.success) {
                    ToolResult.success(
                        "Screenshot captured for visual analysis.",
                        JSONObject().put("include_screenshot", true),
                    )
                } else {
                    ToolResult.failure(screenshot.message)
                }
            }

            "speak" -> {
                val text = call.arguments.optString("text")
                AgentRuntime.addHarmaMessage(text)
                ToolResult.success("Spoke: $text")
            }

            "done" -> ToolResult(
                success = true,
                message = call.arguments.optString("summary", "Task completed."),
                code = "finished",
                finished = true,
            )

            "read_notifications" -> {
                if (accessibility != null) {
                    accessibility.performGlobal("notifications")
                    ToolResult.success(
                        "Opened notification panel to inspect notifications on screen.",
                        JSONObject().put("opened_panel", true),
                    )
                } else {
                    ToolResult.failure("Accessibility service is required to open the notification panel.")
                }
            }

            "ask_user" -> ToolResult(
                success = true,
                message = call.arguments.optString("question", "I need more information."),
                code = "user_input_required",
                askUser = true,
            )

            "finish" -> ToolResult(
                success = call.arguments.optBoolean("success", true),
                message = call.arguments.optString("summary", "Task completed."),
                code = "finished",
                finished = true,
            )

            else -> ToolResult.failure("Tool '${call.name}' is not implemented.")
        }
    }

    private fun accessibilityResult(
        service: AgentAccessibilityService?,
        result: com.personal.harmaai.accessibility.AccessibilityActionResult?,
    ): ToolResult {
        if (service == null || result == null) {
            return ToolResult.failure("Accessibility service is not enabled.")
        }
        return ToolResult(result.success, result.message)
    }

    private fun appPolicyFailure(call: AgentToolCall, observation: ScreenObservation?): String? {
        val target = when (call.name) {
            "open_app" -> listOf(
                call.arguments.optString("name"),
                call.arguments.optString("package"),
            ).joinToString(" ").lowercase()
            in UI_TOOLS -> observation?.packageName.orEmpty().lowercase()
            else -> return null
        }
        if (target.isBlank()) return null
        if (settings.deniedApps.any { denied -> target.contains(denied.lowercase()) }) {
            return "This app is on Harma AI's deny list."
        }
        val allowed = settings.allowedApps
        if (allowed.isNotEmpty() && allowed.none { item -> target.contains(item.lowercase()) }) {
            return "This app is not on Harma AI's allow list."
        }
        return null
    }

    private fun safeArguments(call: AgentToolCall): String = when (call.name) {
        "type_text" -> JSONObject().put("index", call.arguments.optInt("index", -1)).put("text", "[redacted]").toString()
        else -> call.arguments.toString()
    }

    companion object {
        private val UI_TOOLS = setOf("get_screen", "tap", "tap_xy", "long_press", "type_text", "swipe", "scroll", "press", "press_key", "take_screenshot", "screenshot", "click_text", "click_id", "click_desc", "scroll_to_find", "wait_for")
        private val PROTECTED_SCREEN_ACTIONS = setOf("tap", "tap_xy", "long_press", "type_text", "swipe", "scroll", "click_text", "click_id", "click_desc")

        private val ACCESSIBILITY_SPECS = listOf(
            spec("get_screen", "Read the current Android accessibility tree.", emptyMap()),
            spec("tap", "Tap a visible element by the index from the latest screen observation.", mapOf("index" to integer("Element index.")), listOf("index")),
            spec("click_text", "Click an on-screen element matching specific text.", mapOf("text" to string("Visible text to click.")), listOf("text")),
            spec("click_id", "Click an element by its resource ID name.", mapOf("id" to string("View ID resource name.")), listOf("id")),
            spec("click_desc", "Click an element by its accessibility content description.", mapOf("desc" to string("Content description.")), listOf("desc")),
            spec("scroll_to_find", "Scroll vertically to search for and tap an element with the given text.", mapOf("text" to string("Text to find.")), listOf("text")),
            spec("wait_for", "Wait for a specific text or package to appear on the screen.", mapOf("text" to string("Target text or package name to wait for."), "timeout" to integer("Timeout in ms.")), listOf("text")),
            spec("press_key", "Perform an Android key or global action (back, home, recents, enter, search).", mapOf("key" to string("Key or action name.")), listOf("key")),
            spec("screenshot", "Capture a high-resolution screenshot for vision inspection.", emptyMap()),
            spec("speak", "Speak an informative message to the user.", mapOf("text" to string("Message to speak.")), listOf("text")),
            spec("done", "Complete the task with evidence of verification.", mapOf("summary" to string("Summary of verified completed task."), "evidence" to string("Verification evidence.")), listOf("summary")),
            spec("tap_xy", "Tap screen coordinates only when no indexed element exists.", mapOf("x" to number("X coordinate."), "y" to number("Y coordinate."), "purpose" to string("Visible target purpose for safety checks.")), listOf("x", "y")),
            spec("long_press", "Long press screen coordinates.", mapOf("x" to number("X coordinate."), "y" to number("Y coordinate."), "duration_ms" to integer("Duration in milliseconds.")), listOf("x", "y")),
            spec("type_text", "Enter text into an editable element. Never use for passwords, OTPs, PINs, or card data.", mapOf("index" to integer("Editable element index."), "text" to string("Text to enter.")), listOf("index", "text")),
            spec("swipe", "Swipe in a direction or with explicit coordinates.", mapOf("direction" to string("up, down, left, or right"), "x1" to number("Optional start X."), "y1" to number("Optional start Y."), "x2" to number("Optional end X."), "y2" to number("Optional end Y."), "duration_ms" to integer("Optional duration."))),
            spec("scroll", "Scroll the screen or an indexed scrollable container.", mapOf("direction" to string("up/down/forward/backward"), "index" to integer("Optional scrollable element index.")), listOf("direction")),
            spec("press", "Perform an Android global key/action.", mapOf("key" to enumString("Global action.", listOf("back", "home", "recents", "notifications", "quick_settings", "lock_screen"))), listOf("key")),
            spec("wait", "Wait briefly for an app or screen transition.", mapOf("milliseconds" to integer("Wait duration from 100 to 10000.")), listOf("milliseconds")),
            spec("take_screenshot", "Capture the screen for vision analysis when the UI tree is insufficient.", emptyMap()),
            ToolSpec("read_notifications", "Open notification shade to view notifications on screen.", ToolRisk.SAFE, schema(emptyMap())),
            spec("ask_user", "Pause and ask the user for essential missing information.", mapOf("question" to string("Question to show.")), listOf("question")),
            spec("finish", "Finish the task after verifying success or failure.", mapOf("success" to boolean("Whether the task succeeded."), "summary" to string("Short final result.")), listOf("success", "summary")),
        )

        private fun spec(
            name: String,
            description: String,
            properties: Map<String, JSONObject>,
            required: List<String> = emptyList(),
        ) = ToolSpec(name, description, ToolRisk.SAFE, schema(properties, required))

        private fun schema(
            properties: Map<String, JSONObject>,
            required: List<String> = emptyList(),
        ) = JSONObject()
            .put("type", "object")
            .put("properties", JSONObject(properties))
            .put("additionalProperties", false)
            .apply { if (required.isNotEmpty()) put("required", JSONArray(required)) }

        private fun string(description: String) = JSONObject().put("type", "string").put("description", description)
        private fun enumString(description: String, values: List<String>) = string(description).put("enum", JSONArray(values))
        private fun integer(description: String) = JSONObject().put("type", "integer").put("description", description)
        private fun number(description: String) = JSONObject().put("type", "number").put("description", description)
        private fun boolean(description: String) = JSONObject().put("type", "boolean").put("description", description)
    }
}
