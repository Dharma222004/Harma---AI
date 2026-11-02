package com.personal.harmaai.agent

import android.app.SearchManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.provider.Settings
import com.personal.harmaai.accessibility.AgentAccessibilityService
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.tools.AppListCache
import com.personal.harmaai.tools.DirectToolExecutor
import com.personal.harmaai.tools.ToolCall
import com.personal.harmaai.tools.ToolResult
import org.json.JSONObject
import java.util.regex.Pattern

sealed class RouterResult {
    data class Handled(val result: ToolResult, val description: String) : RouterResult()
    data class NeedsConfirmation(
        val toolName: String,
        val arguments: JSONObject,
        val userPrompt: String,
    ) : RouterResult()
    object NotHandled : RouterResult()
}

/**
 * Fast-path local command router that executes deterministic commands directly
 * without invoking any LLM, cutting execution latency to <1.5 seconds.
 */
class LocalCommandRouter(private val context: Context) {
    private val directTools = DirectToolExecutor(context)

    fun tryRoute(command: String, sessionId: String = ""): RouterResult {
        val start = SystemClock.uptimeMillis()
        val text = command.trim()
        val lower = text.lowercase()

        // 1. Flashlight / Torch
        if (matchesFlashlight(lower)) {
            val turnOn = !lower.contains("off") && !lower.contains("stop")
            val toolCall = ToolCall("set_flashlight", JSONObject().put("on", turnOn))
            val res = directTools.execute(toolCall)
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_flashlight", elapsed)
            return RouterResult.Handled(res, if (turnOn) "Flashlight turned on" else "Flashlight turned off")
        }

        // 2. Camera capture (take photo / click picture / open camera and take photo)
        if (matchesCameraCapture(lower)) {
            val res = directTools.execute(ToolCall("take_photo", JSONObject()))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "take_photo", elapsed)
            return RouterResult.Handled(res, "Taking photo")
        }

        // 3. Open App / Launch App
        val appName = extractOpenAppTarget(lower)
        if (appName != null) {
            val pkg = AppListCache.resolvePackage(appName, context)
            if (pkg != null) {
                val toolCall = ToolCall("open_app", JSONObject().put("name", appName).put("package", pkg))
                val res = directTools.execute(toolCall)
                val elapsed = SystemClock.uptimeMillis() - start
                HarmaPerf.onFastRouterCheck(sessionId, true, "open_app:$appName", elapsed)
                return RouterResult.Handled(res, "Opening $appName")
            }
        }

        // 3. Search on YouTube or Web
        val ytSearchQuery = extractYouTubeSearch(lower)
        if (ytSearchQuery != null) {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(ytSearchQuery)}")).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                setPackage("com.google.android.youtube")
            }
            val res = try {
                context.startActivity(intent)
                ToolResult.success("Searching for '$ytSearchQuery' on YouTube.")
            } catch (_: Exception) {
                // Fallback to web search if YouTube app not installed
                val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(ytSearchQuery)}")).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(webIntent)
                ToolResult.success("Searching for '$ytSearchQuery' on YouTube via browser.")
            }
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "search_youtube:$ytSearchQuery", elapsed)
            return RouterResult.Handled(res, "Searching YouTube for $ytSearchQuery")
        }

        // 4. Global Navigation (Home, Back, Recents, Notifications, Quick Settings, Lock Screen, Screenshot)
        val globalAction = extractGlobalAction(lower)
        if (globalAction != null) {
            val accessibility = AgentAccessibilityService.current()
            val res = if (accessibility != null) {
                val actionResult = accessibility.performGlobal(globalAction)
                ToolResult(actionResult.success, actionResult.message)
            } else {
                ToolResult.failure("Accessibility service is not active.")
            }
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "global:$globalAction", elapsed)
            return RouterResult.Handled(res, "Performed $globalAction")
        }

        // 5. Volume controls
        val volumePercent = extractVolumeTarget(lower)
        if (volumePercent != null) {
            val res = directTools.execute(ToolCall("set_volume", JSONObject().put("percent", volumePercent).put("stream", "media")))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_volume:$volumePercent", elapsed)
            return RouterResult.Handled(res, "Volume set to $volumePercent%")
        }

        // 6. Brightness controls
        val brightnessPercent = extractBrightnessTarget(lower)
        if (brightnessPercent != null) {
            val res = directTools.execute(ToolCall("set_brightness", JSONObject().put("percent", brightnessPercent)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_brightness:$brightnessPercent", elapsed)
            return RouterResult.Handled(res, "Brightness set to $brightnessPercent%")
        }

        // 7. Settings pages (Wi-Fi, Bluetooth, Settings)
        if (lower.contains("wifi") || lower.contains("wi-fi")) {
            val res = directTools.execute(ToolCall("open_wifi_settings", JSONObject()))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "open_wifi_settings", elapsed)
            return RouterResult.Handled(res, "Opening Wi-Fi settings")
        }
        if (lower.contains("bluetooth")) {
            val res = directTools.execute(ToolCall("open_bluetooth_settings", JSONObject()))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "open_bluetooth_settings", elapsed)
            return RouterResult.Handled(res, "Opening Bluetooth settings")
        }

        // 8. Timers & Alarms
        val timerSeconds = extractTimerSeconds(lower)
        if (timerSeconds != null) {
            val res = directTools.execute(ToolCall("set_timer", JSONObject().put("seconds", timerSeconds)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_timer:$timerSeconds", elapsed)
            return RouterResult.Handled(res, "Timer set for ${timerSeconds}s")
        }

        // 9. Call (Direct autonomous execution)
        val callTarget = extractCallTarget(text)
        if (callTarget != null) {
            val res = directTools.execute(ToolCall("make_call", JSONObject().put("contact_or_number", callTarget)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "make_call:$callTarget", elapsed)
            return RouterResult.Handled(res, "Calling $callTarget")
        }

        val elapsed = SystemClock.uptimeMillis() - start
        HarmaPerf.onFastRouterCheck(sessionId, false, "", elapsed)
        return RouterResult.NotHandled
    }

    companion object {
        fun matchesFlashlight(text: String): Boolean =
            text.contains("flashlight") || text.contains("torch")

        fun extractOpenAppTarget(text: String): String? {
            val patterns = listOf(
                Pattern.compile("^(?:open|launch|start|run)\\s+([a-z0-9\\s]+)$"),
                Pattern.compile("^(?:please\\s+)?(?:open|launch|start)\\s+([a-z0-9\\s]+)$"),
                Pattern.compile("^(?:switch\\s+to)\\s+([a-z0-9\\s]+)$"),
            )
            for (pattern in patterns) {
                val matcher = pattern.matcher(text)
                if (matcher.matches()) {
                    val candidate = matcher.group(1)?.trim().orEmpty()
                    if (candidate.isNotBlank() && !candidate.startsWith("flashlight") && !candidate.startsWith("torch") && !candidate.startsWith("settings")) {
                        return candidate
                    }
                }
            }
            return null
        }

        fun extractYouTubePlay(text: String): String? {
            val patterns = listOf(
                Pattern.compile("(?:open\\s+youtube\\s+and\\s+play)\\s+(.+)$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("(?:play|listen to)\\s+(.+?)(?:\\s+on\\s+youtube)?$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("youtube\\s+play\\s+(.+)$", Pattern.CASE_INSENSITIVE),
            )
            for (p in patterns) {
                val m = p.matcher(text)
                if (m.find()) {
                    val q = m.group(1)?.trim().orEmpty()
                    if (q.isNotBlank() && !q.equals("youtube", ignoreCase = true)) return q
                }
            }
            return null
        }

        fun extractWhatsAppTarget(text: String): Pair<String, String>? {
            val bdayPattern = Pattern.compile("(?:send|wish)\\s+(?:a\\s+)?birthday\\s+wishes?\\s+(?:to\\s+)?([a-zA-Z0-9\\s]+?)(?:\\s+on\\s+whatsapp)?$", Pattern.CASE_INSENSITIVE)
            val bm = bdayPattern.matcher(text)
            if (bm.find()) {
                val name = bm.group(1)?.trim().orEmpty()
                if (name.isNotBlank()) {
                    val msg = "Happy Birthday $name! Wishing you a wonderful day filled with happiness, health, and great joy! 🎉🎂"
                    return name to msg
                }
            }
            val msgPattern = Pattern.compile("(?:whatsapp|send\\s+whatsapp\\s+(?:message\\s+)?to)\\s+([a-zA-Z0-9\\s]+?)(?:\\s+(?:saying|that)\\s+(.+))?$", Pattern.CASE_INSENSITIVE)
            val mm = msgPattern.matcher(text)
            if (mm.find()) {
                val name = mm.group(1)?.trim().orEmpty()
                val customMsg = mm.group(2)?.trim() ?: "Hello from Harma AI!"
                if (name.isNotBlank()) {
                    return name to customMsg
                }
            }
            return null
        }

        fun extractYouTubeSearch(text: String): String? {
            val patterns = listOf(
                Pattern.compile("(?:search|find|play|look for)\\s+(.+?)\\s+(?:on|in)\\s+youtube"),
                Pattern.compile("youtube\\s+(?:search|play)\\s+(.+)"),
            )
            for (p in patterns) {
                val m = p.matcher(text)
                if (m.find()) {
                    return m.group(1)?.trim()
                }
            }
            return null
        }

        fun extractGlobalAction(text: String): String? = when {
            text in listOf("go home", "take me home", "home screen", "home") -> "home"
            text in listOf("go back", "back", "press back") -> "back"
            text in listOf("recent apps", "recents", "open recents", "app switcher") -> "recents"
            text in listOf("notifications", "open notifications", "show notifications") -> "notifications"
            text in listOf("quick settings", "open quick settings") -> "quick_settings"
            text in listOf("lock phone", "lock screen", "lock") -> "lock"
            text in listOf("take screenshot", "capture screen", "screenshot") -> "screenshot"
            else -> null
        }

        fun extractVolumeTarget(text: String): Int? {
            if (!text.contains("volume") && !text.contains("sound")) return null
            if (text.contains("mute") || text.contains("silent") || text.contains("zero")) return 0
            if (text.contains("max") || text.contains("full") || text.contains("100")) return 100
            val digits = text.filter { it.isDigit() }.toIntOrNull()
            if (digits != null && digits in 0..100) return digits
            if (text.contains("up") || text.contains("increase") || text.contains("raise")) return 80
            if (text.contains("down") || text.contains("lower") || text.contains("decrease")) return 30
            return null
        }

        fun extractBrightnessTarget(text: String): Int? {
            if (!text.contains("brightness")) return null
            if (text.contains("max") || text.contains("full") || text.contains("100")) return 100
            if (text.contains("min") || text.contains("lowest")) return 10
            val digits = text.filter { it.isDigit() }.toIntOrNull()
            if (digits != null && digits in 0..100) return digits
            if (text.contains("up") || text.contains("increase") || text.contains("higher")) return 80
            if (text.contains("down") || text.contains("lower") || text.contains("dim")) return 25
            return null
        }

        fun extractTimerSeconds(text: String): Int? {
            if (!text.contains("timer")) return null
            val minutePattern = Pattern.compile("(\\d+)\\s*(?:minute|min)")
            val secPattern = Pattern.compile("(\\d+)\\s*(?:second|sec)")
            val mm = minutePattern.matcher(text)
            if (mm.find()) {
                return (mm.group(1)?.toIntOrNull() ?: 1) * 60
            }
            val sm = secPattern.matcher(text)
            if (sm.find()) {
                return sm.group(1)?.toIntOrNull() ?: 30
            }
            return null
        }

        fun matchesCameraCapture(text: String): Boolean {
            return text.contains("take photo") ||
                text.contains("take a photo") ||
                text.contains("take one photo") ||
                text.contains("take picture") ||
                text.contains("take a picture") ||
                text.contains("click photo") ||
                text.contains("click a photo") ||
                text.contains("capture photo") ||
                text.contains("take selfie") ||
                text.contains("take a selfie") ||
                (text.contains("camera") && (text.contains("photo") || text.contains("picture") || text.contains("pic") || text.contains("capture") || text.contains("click") || text.contains("snap")))
        }

        fun extractCallTarget(text: String): String? {
            val pattern = Pattern.compile("^(?:please\\s+)?(?:call\\s+to|make\\s+a\\s+call\\s+to|call|dial|phone)\\s+([a-zA-Z0-9\\s+]+)$", Pattern.CASE_INSENSITIVE)
            val matcher = pattern.matcher(text)
            if (matcher.matches()) {
                return matcher.group(1)?.trim()
            }
            return null
        }
    }
}
