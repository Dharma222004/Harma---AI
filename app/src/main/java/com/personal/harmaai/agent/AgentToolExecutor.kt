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
    private val allSpecs = (directTools.specs + ACCESSIBILITY_SPECS).map(::withReasoningFields)
    private val specsByName = allSpecs.associateBy(ToolSpec::name)

    val specs: List<ToolSpec> get() = allSpecs

    suspend fun execute(
        call: AgentToolCall,
        observation: ScreenObservation?,
    ): ToolResult {
        val normalizedName = if (call.name == "open_settings_panel") "open_settings" else call.name
        val spec = specsByName[call.name] ?: specsByName[normalizedName]
            ?: return ToolResult.failure("Unknown tool '${call.name}'.")

        appPolicyFailure(call, observation)?.let { return ToolResult.failure(it) }

        if (normalizedName in PROTECTED_SCREEN_ACTIONS) {
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
                toolName = normalizedName,
                description = safetyGate.confirmationDescription(spec),
                arguments = safeArguments(call),
            )
            if (!approved) return ToolResult.failure("The user rejected $normalizedName.")
        }

        if (directTools.find(normalizedName) != null) {
            val result = directTools.execute(normalizedName, call.arguments)
            if (normalizedName == "open_app" && result.success) {
                val expectedPkg = result.data.optString("expected_package")
                if (expectedPkg.isNotBlank()) {
                    AgentAccessibilityService.current()?.awaitForegroundPackage(expectedPkg)
                }
            }
            return result
        }

        val accessibility = AgentAccessibilityService.current()
        return when (normalizedName) {
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
                accessibility?.tapNodeWithFallback(call.arguments.optInt("index", -1)),
            )

            "click_text" -> accessibilityResult(
                accessibility,
                accessibility?.clickByText(
                    text = call.arguments.optString("text"),
                    exact = call.arguments.optBoolean("exact", false),
                    excludeEditable = call.arguments.optBoolean("exclude_editable", false),
                ),
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
                val found = accessibility?.waitForTextOrPackage(target, timeout) ?: false
                if (found) {
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

            "long_press" -> {
                val index = call.arguments.optInt("index", -1)
                val durationMs = call.arguments.optLong("duration_ms", 800L)
                if (index >= 0) {
                    accessibilityResult(
                        accessibility,
                        accessibility?.longPressNode(index, durationMs),
                    )
                } else {
                    accessibilityResult(
                        accessibility,
                        accessibility?.longPress(
                            call.arguments.optDouble("x", -1.0).toFloat(),
                            call.arguments.optDouble("y", -1.0).toFloat(),
                            durationMs,
                        ),
                    )
                }
            }

            "type_text" -> {
                val res = accessibility?.setNodeText(
                    call.arguments.optInt("index", -1),
                    call.arguments.optString("text"),
                )
                if (res != null && res.success && call.arguments.optBoolean("submit", false)) {
                    delay(150L)
                    accessibility.performImeEnter()
                }
                accessibilityResult(accessibility, res)
            }

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

            "press", "press_key", "back", "home", "recents" -> {
                val key = when (normalizedName) {
                    "back", "home", "recents" -> normalizedName
                    else -> call.arguments.optString("key").ifBlank { call.arguments.optString("action") }
                }
                when (key.lowercase()) {
                    "enter", "search", "send", "go", "submit" -> accessibilityResult(
                        accessibility,
                        accessibility?.performImeEnter(),
                    )
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
                        "Screenshot captured with Set-of-Marks overlay for visual analysis.",
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
                val readResult = com.personal.harmaai.notifications.HarmaNotificationListenerService.readRecentMessages(
                    context = appContext,
                    limit = 10,
                )
                if (readResult.notifications.isNotEmpty()) {
                    ToolResult.success(
                        readResult.summary,
                        com.personal.harmaai.notifications.HarmaNotificationListenerService.recentJson(10),
                    )
                } else if (accessibility != null) {
                    accessibility.performGlobal("notifications")
                    ToolResult.success(
                        "Opened notification panel to inspect notifications on screen.",
                        JSONObject().put("opened_panel", true),
                    )
                } else {
                    ToolResult.failure(readResult.summary)
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
        private val UI_TOOLS = setOf(
            "get_screen", "tap", "tap_xy", "long_press", "type_text", "swipe", "scroll",
            "press", "press_key", "back", "home", "recents", "take_screenshot", "screenshot",
            "click_text", "click_id", "click_desc", "scroll_to_find", "wait_for",
        )
        private val PROTECTED_SCREEN_ACTIONS = setOf(
            "tap", "tap_xy", "long_press", "type_text", "swipe", "scroll",
            "click_text", "click_id", "click_desc",
        )

        private fun withReasoningFields(spec: ToolSpec): ToolSpec {
            val params = JSONObject(spec.parameters.toString())
            val props = params.optJSONObject("properties") ?: JSONObject()
            if (!props.has("observation")) {
                props.put("observation", string("Brief summary of current screen state and previous step verification."))
            }
            if (!props.has("expected_outcome")) {
                props.put("expected_outcome", string("Expected visible screen or system change after this action."))
            }
            params.put("properties", props)
            return spec.copy(parameters = params)
        }

        private val ACCESSIBILITY_SPECS = listOf(
            spec("get_screen", "Read the current Android multi-window accessibility snapshot.", emptyMap()),
            spec("tap", "Tap a visible element by its numeric [index] from the current screen snapshot.", mapOf("index" to integer("Element index from the current snapshot.")), listOf("index")),
            spec("long_press", "Long-press a visible element by its numeric [index] from the current snapshot.", mapOf("index" to integer("Element index from the current snapshot."), "duration_ms" to integer("Duration in milliseconds.")), listOf("index")),
            spec("type_text", "Enter text into an editable element by [index] (uses ACTION_SET_TEXT with clipboard paste fallback). Set submit=true to trigger IME Enter.", mapOf("index" to integer("Editable element index."), "text" to string("Text to enter."), "submit" to boolean("Whether to submit via IME Enter after typing.")), listOf("index", "text")),
            spec("click_text", "Click an on-screen element matching visible text (disambiguates clickable rows from static headers).", mapOf("text" to string("Visible text to click."), "exclude_editable" to boolean("Exclude editable search boxes when clicking a search result.")), listOf("text")),
            spec("click_id", "Click an element by its resource ID name.", mapOf("id" to string("View ID resource name.")), listOf("id")),
            spec("click_desc", "Click an element by its accessibility content description.", mapOf("desc" to string("Content description.")), listOf("desc")),
            spec("scroll", "Scroll the screen or an indexed scrollable container.", mapOf("direction" to string("up/down/forward/backward"), "index" to integer("Optional scrollable element index.")), listOf("direction")),
            spec("scroll_to_find", "Scroll vertically to search for and tap an element with the given text.", mapOf("text" to string("Text to find.")), listOf("text")),
            spec("swipe", "Swipe in a direction (up, down, left, right).", mapOf("direction" to string("up, down, left, or right"), "duration_ms" to integer("Optional duration."))),
            spec("press_key", "Perform an Android key or global action (back, home, recents, enter, search).", mapOf("key" to string("Key or action name.")), listOf("key")),
            spec("back", "Navigate back (GLOBAL_ACTION_BACK).", emptyMap()),
            spec("home", "Go to the home screen (GLOBAL_ACTION_HOME).", emptyMap()),
            spec("recents", "Open recent apps (GLOBAL_ACTION_RECENTS).", emptyMap()),
            spec("open_settings_panel", "Open an Android Settings panel (wifi, bluetooth, sound, display, apps, accessibility, battery).", mapOf("panel" to string("Panel name.")), listOf("panel")),
            spec("wait_for", "Wait for specific text or package name to appear on screen.", mapOf("text" to string("Target text or package name to wait for."), "timeout" to integer("Timeout in ms.")), listOf("text")),
            spec("wait", "Wait briefly for an app or screen transition.", mapOf("milliseconds" to integer("Wait duration from 100 to 10000.")), listOf("milliseconds")),
            spec("take_screenshot", "Capture the screen with numbered Set-of-Marks (SoM) badges when the UI tree is insufficient (WebView, Flutter, canvas).", emptyMap()),
            spec("screenshot", "Alias for take_screenshot with Set-of-Marks overlay.", emptyMap()),
            spec("speak", "Speak an informative message to the user.", mapOf("text" to string("Message to speak.")), listOf("text")),
            ToolSpec("read_notifications", "Open notification shade to view notifications on screen.", ToolRisk.SAFE, schema(emptyMap())),
            spec("ask_user", "Pause and ask the user for essential missing information.", mapOf("question" to string("Question to show.")), listOf("question")),
            spec("done", "Complete the task with evidence of verification.", mapOf("summary" to string("Summary of verified completed task."), "evidence" to string("Verification evidence.")), listOf("summary")),
            spec("finish", "Finish the task after verifying success or failure on screen.", mapOf("success" to boolean("Whether the task succeeded."), "summary" to string("Short final verified result.")), listOf("success", "summary")),
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
        private fun integer(description: String) = JSONObject().put("type", "integer").put("description", description)
        private fun boolean(description: String) = JSONObject().put("type", "boolean").put("description", description)
    }
}
