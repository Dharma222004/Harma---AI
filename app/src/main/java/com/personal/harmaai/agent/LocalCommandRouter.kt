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

        val alarm = extractAlarmTime(lower)
        if (alarm != null) {
            val (hour, minute, label) = alarm
            val args = JSONObject().put("hour", hour).put("minute", minute).apply {
                if (label.isNotBlank()) put("label", label)
            }
            val res = directTools.execute(ToolCall("set_alarm", args))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_alarm:$hour:$minute", elapsed)
            return RouterResult.Handled(res, "Alarm set for %02d:%02d".format(hour, minute))
        }

        // 9. Ringer Mode & Do Not Disturb
        val dndOn = extractDndToggle(lower)
        if (dndOn != null) {
            val res = directTools.execute(ToolCall("toggle_do_not_disturb", JSONObject().put("on", dndOn)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "toggle_dnd:$dndOn", elapsed)
            return RouterResult.Handled(res, if (dndOn) "Do Not Disturb enabled" else "Do Not Disturb disabled")
        }

        val ringerMode = extractRingerMode(lower)
        if (ringerMode != null) {
            val res = directTools.execute(ToolCall("set_ringer_mode", JSONObject().put("mode", ringerMode)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "set_ringer_mode:$ringerMode", elapsed)
            return RouterResult.Handled(res, "Ringer mode set to $ringerMode")
        }

        // 10. Media Controls
        val mediaAction = extractMediaAction(lower)
        if (mediaAction != null) {
            val res = directTools.execute(ToolCall("media_control", JSONObject().put("action", mediaAction)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "media_control:$mediaAction", elapsed)
            return RouterResult.Handled(res, "Media $mediaAction")
        }

        // 11. Battery & Time Queries
        if (matchesBatteryQuery(lower)) {
            val res = directTools.execute(ToolCall("get_battery", JSONObject()))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "get_battery", elapsed)
            return RouterResult.Handled(res, "Checked battery status")
        }

        if (matchesTimeQuery(lower)) {
            val res = directTools.execute(ToolCall("get_time", JSONObject()))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "get_time", elapsed)
            return RouterResult.Handled(res, "Checked current time")
        }

        // 12. Web Search
        val webQuery = extractWebSearch(lower)
        if (webQuery != null) {
            val res = directTools.execute(ToolCall("search_web", JSONObject().put("query", webQuery)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "search_web:$webQuery", elapsed)
            return RouterResult.Handled(res, "Searching web for $webQuery")
        }

        // 13. Call (Direct autonomous execution)
        val callTarget = extractCallTarget(text)
        if (callTarget != null) {
            val res = directTools.execute(ToolCall("make_call", JSONObject().put("contact_or_number", callTarget)))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "make_call:$callTarget", elapsed)
            return RouterResult.Handled(res, "Calling $callTarget")
        }

        // 14. Read recent messages / notifications hands-free (zero screen tapping)
        val readMsgFilter = extractReadMessagesQuery(text)
        if (readMsgFilter != null) {
            val (senderFilter, appFilter) = readMsgFilter
            val args = JSONObject()
                .put("sender", senderFilter)
                .put("app", appFilter)
                .put("limit", 5)
            val res = directTools.execute(ToolCall("read_recent_messages", args))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "read_recent_messages", elapsed)
            return RouterResult.Handled(res, "Reading recent messages")
        }

        // 15. Instant Background Reply via Notification RemoteInput (zero screen tapping)
        val replyTarget = extractNotificationReply(text)
        if (replyTarget != null) {
            val (senderQuery, replyText) = replyTarget
            val args = JSONObject()
                .put("sender", senderQuery)
                .put("text", replyText)
            val res = directTools.execute(ToolCall("reply_notification", args))
            val elapsed = SystemClock.uptimeMillis() - start
            HarmaPerf.onFastRouterCheck(sessionId, true, "reply_notification:$senderQuery", elapsed)
            return RouterResult.Handled(
                res,
                if (senderQuery.isBlank()) "Replying to latest message" else "Replying to $senderQuery",
            )
        }

        val elapsed = SystemClock.uptimeMillis() - start
        HarmaPerf.onFastRouterCheck(sessionId, false, "", elapsed)
        return RouterResult.NotHandled
    }

    companion object {
        private val COMPOUND_CONNECTORS = listOf(
            " and ", " then ", " to ", " for ", " search ", " play ", " send ",
            " call ", " message ", " text ", " type ", " find ", " check ",
            " turn ", " set ", " take ", " click ", " tap ", " with ", " saying ",
        )

        fun matchesFlashlight(text: String): Boolean =
            text.contains("flashlight") || text.contains("torch")

        fun extractOpenAppTarget(text: String): String? {
            val normalized = text.lowercase().trim()
            val patterns = listOf(
                Pattern.compile("^(?:please\\s+)?(?:open|launch|start|run)\\s+([a-z0-9\\s]+)$"),
                Pattern.compile("^(?:please\\s+)?(?:go\\s+to|switch\\s+to)\\s+([a-z0-9\\s]+)$"),
            )
            for (pattern in patterns) {
                val matcher = pattern.matcher(normalized)
                if (matcher.matches()) {
                    val candidate = matcher.group(1)?.trim().orEmpty()
                    val paddedCandidate = " $candidate "
                    if (candidate.isNotBlank() &&
                        COMPOUND_CONNECTORS.none { paddedCandidate.contains(it) } &&
                        !candidate.startsWith("flashlight") &&
                        !candidate.startsWith("torch")
                    ) {
                        return candidate
                    }
                }
            }
            return null
        }

        fun extractYouTubePlay(text: String): String? {
            val patterns = listOf(
                Pattern.compile("(?:open\\s+youtube\\s+and\\s+play)\\s+(.+)$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("(?:play|listen to)\\s+(.+?)\\s+on\\s+youtube$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("^(?:play|listen to)\\s+(.+)$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("youtube\\s+play\\s+(.+)$", Pattern.CASE_INSENSITIVE),
            )
            for (p in patterns) {
                val m = p.matcher(text.trim())
                if (m.find()) {
                    val q = m.group(1)?.trim().orEmpty()
                    val lowerQ = q.lowercase()
                    if (q.isNotBlank() &&
                        !lowerQ.equals("youtube", ignoreCase = true) &&
                        lowerQ !in setOf("music", "song", "audio", "video", "pause", "resume", "stop") &&
                        !lowerQ.endsWith(" on spotify")
                    ) {
                        return q
                    }
                }
            }
            return null
        }

        fun extractWhatsAppTarget(text: String): Pair<String, String>? {
            val trimmed = text.trim()
            val bdayPattern = Pattern.compile(
                "(?:send|wish)\\s+(?:a\\s+)?birthday\\s+wishes?\\s+(?:to\\s+)?([a-zA-Z0-9\\s]+?)(?:\\s+on\\s+whatsapp)?$",
                Pattern.CASE_INSENSITIVE,
            )
            val bm = bdayPattern.matcher(trimmed)
            if (bm.find()) {
                val name = bm.group(1)?.trim().orEmpty()
                if (name.isNotBlank()) {
                    val msg = "Happy Birthday $name! Wishing you a wonderful day filled with happiness, health, and great joy! 🎉🎂"
                    return name to msg
                }
            }

            val patterns = listOf(
                Pattern.compile(
                    "(?:open\\s+whatsapp\\s+and\\s+(?:send\\s+(?:a\\s+)?(?:whatsapp\\s+)?(?:message\\s+)?to|message|text))\\s+([a-zA-Z0-9+\\s]+?)(?:\\s+(?:saying|that|:|-)\\s*(.+))?$",
                    Pattern.CASE_INSENSITIVE,
                ),
                Pattern.compile(
                    "(?:send\\s+(?:a\\s+)?(?:whatsapp\\s+)?(?:message\\s+)?to|message)\\s+([a-zA-Z0-9+\\s]+?)\\s+on\\s+whatsapp(?:\\s+(?:saying|that|:|-)\\s*(.+))?$",
                    Pattern.CASE_INSENSITIVE,
                ),
                Pattern.compile(
                    "(?:whatsapp|send\\s+(?:a\\s+)?whatsapp\\s+(?:message\\s+)?to)\\s+([a-zA-Z0-9+\\s]+?)(?:\\s+(?:saying|that|:|-)\\s*(.+))?$",
                    Pattern.CASE_INSENSITIVE,
                ),
                Pattern.compile(
                    "send\\s+[\"']?(.+?)[\"']?\\s+to\\s+([a-zA-Z0-9+\\s]+?)\\s+on\\s+whatsapp$",
                    Pattern.CASE_INSENSITIVE,
                ),
            )
            for ((idx, pattern) in patterns.withIndex()) {
                val m = pattern.matcher(trimmed)
                if (m.find()) {
                    if (idx == 3) {
                        val customMsg = m.group(1)?.trim().orEmpty()
                        val name = m.group(2)?.trim().orEmpty()
                        if (name.isNotBlank() && customMsg.isNotBlank()) {
                            return name to customMsg
                        }
                    } else {
                        val name = m.group(1)?.trim().orEmpty()
                        val customMsg = m.group(2)?.trim()?.takeIf { it.isNotBlank() } ?: "Hello"
                        if (name.isNotBlank()) {
                            return name to customMsg
                        }
                    }
                }
            }
            return null
        }

        fun extractYouTubeSearch(text: String): String? {
            val patterns = listOf(
                Pattern.compile("(?:search|find|look for)\\s+(.+?)\\s+(?:on|in)\\s+youtube", Pattern.CASE_INSENSITIVE),
                Pattern.compile("youtube\\s+search\\s+(?:for\\s+)?(.+)", Pattern.CASE_INSENSITIVE),
                Pattern.compile("open\\s+youtube\\s+and\\s+search\\s+(?:for\\s+)?(.+)", Pattern.CASE_INSENSITIVE),
            )
            for (p in patterns) {
                val m = p.matcher(text.trim())
                if (m.find()) {
                    return m.group(1)?.trim()
                }
            }
            return null
        }

        fun extractWebSearch(text: String): String? {
            val patterns = listOf(
                Pattern.compile("^(?:search\\s+google\\s+for|google\\s+search\\s+for|google\\s+search|search\\s+(?:the\\s+)?web\\s+for)\\s+(.+)$", Pattern.CASE_INSENSITIVE),
                Pattern.compile("^search\\s+(?:for\\s+)?(.+?)\\s+on\\s+(?:google|web|chrome)$", Pattern.CASE_INSENSITIVE),
            )
            for (p in patterns) {
                val m = p.matcher(text.trim())
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
            val hourPattern = Pattern.compile("(\\d+)\\s*(?:hour|hr)")
            val minutePattern = Pattern.compile("(\\d+)\\s*(?:minute|min)")
            val secPattern = Pattern.compile("(\\d+)\\s*(?:second|sec)")
            var totalSeconds = 0
            val hm = hourPattern.matcher(text)
            if (hm.find()) totalSeconds += (hm.group(1)?.toIntOrNull() ?: 0) * 3600
            val mm = minutePattern.matcher(text)
            if (mm.find()) totalSeconds += (mm.group(1)?.toIntOrNull() ?: 0) * 60
            val sm = secPattern.matcher(text)
            if (sm.find()) totalSeconds += (sm.group(1)?.toIntOrNull() ?: 0)
            return totalSeconds.takeIf { it > 0 }
        }

        fun extractAlarmTime(text: String): Triple<Int, Int, String>? {
            if (!text.lowercase().contains("alarm") && !text.lowercase().contains("wake me")) return null
            val pattern = Pattern.compile(
                "(?:at|for)\\s+(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm|a\\.m\\.|p\\.m\\.)?(?:\\s+(?:called|labeled|named)\\s+(.+))?$",
                Pattern.CASE_INSENSITIVE,
            )
            val matcher = pattern.matcher(text.trim())
            if (!matcher.find()) return null
            var hour = matcher.group(1)?.toIntOrNull() ?: return null
            val minute = matcher.group(2)?.toIntOrNull() ?: 0
            val ampm = matcher.group(3)?.lowercase()?.replace(".", "").orEmpty()
            val label = matcher.group(4)?.trim().orEmpty()
            if (ampm == "pm" && hour in 1..11) hour += 12
            if (ampm == "am" && hour == 12) hour = 0
            if (hour !in 0..23 || minute !in 0..59) return null
            return Triple(hour, minute, label)
        }

        fun extractRingerMode(text: String): String? {
            val lower = text.lowercase().trim()
            if (lower.contains("volume")) return null
            return when {
                lower in listOf("silent mode", "put phone on silent", "put phone on silent mode", "set phone to silent", "set ringer to silent", "silence phone", "mute phone") -> "silent"
                lower in listOf("vibrate mode", "put phone on vibrate", "put phone on vibrate mode", "set phone to vibrate", "set ringer to vibrate") -> "vibrate"
                lower in listOf("normal mode", "ringer mode normal", "set phone to normal", "set ringer to normal", "unmute phone", "sound mode") -> "normal"
                else -> null
            }
        }

        fun extractDndToggle(text: String): Boolean? {
            if (!text.contains("do not disturb") && !text.contains("dnd")) return null
            return !text.contains("off") && !text.contains("disable") && !text.contains("stop")
        }

        fun extractMediaAction(text: String): String? = when (text.trim()) {
            "pause", "pause music", "pause song", "pause video", "pause playback" -> "pause"
            "resume", "resume music", "resume playback", "continue playing" -> "play"
            "next song", "next track", "skip song", "skip track" -> "next"
            "previous song", "previous track", "prev song" -> "prev"
            "stop music", "stop playback" -> "stop"
            else -> null
        }

        fun matchesBatteryQuery(text: String): Boolean =
            text in listOf("battery", "battery level", "battery status", "battery percentage", "what is my battery", "check battery", "how much battery is left")

        fun matchesTimeQuery(text: String): Boolean =
            text in listOf("what time is it", "current time", "tell me the time", "what is the time", "what is today's date", "today's date")

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
            val matcher = pattern.matcher(text.trim())
            if (matcher.matches()) {
                return matcher.group(1)?.trim()
            }
            return null
        }

        /**
         * Parses commands like:
         * - "read my new messages" / "read my messages" / "check my messages" / "read notifications"
         * - "read my whatsapp messages" / "any new telegram messages"
         * - "read messages from Rahul" / "what did Mom message me"
         * Returns Pair(senderFilter, appFilter) or null if not a read-messages command.
         */
        fun extractReadMessagesQuery(text: String): Pair<String, String>? {
            val trimmed = text.trim()
            val lower = trimmed.lowercase()

            val fromSenderPattern = Pattern.compile(
                "^(?:please\\s+)?(?:read|check|show|tell\\s+me)\\s+(?:my\\s+)?(?:new\\s+|latest\\s+|recent\\s+)?(?:whatsapp\\s+|telegram\\s+|instagram\\s+)?messages?\\s+from\\s+([a-zA-Z0-9\\s]+)$",
                Pattern.CASE_INSENSITIVE,
            )
            val mSender = fromSenderPattern.matcher(trimmed)
            if (mSender.matches()) {
                val sender = mSender.group(1)?.trim().orEmpty()
                val app = when {
                    lower.contains("whatsapp") -> "whatsapp"
                    lower.contains("telegram") -> "telegram"
                    lower.contains("instagram") -> "instagram"
                    else -> ""
                }
                return sender to app
            }

            val whatDidPattern = Pattern.compile(
                "^what\\s+did\\s+([a-zA-Z0-9\\s]+?)\\s+(?:message|text|send)(?:\\s+me)?$",
                Pattern.CASE_INSENSITIVE,
            )
            val mWhat = whatDidPattern.matcher(trimmed)
            if (mWhat.matches()) {
                return mWhat.group(1)?.trim().orEmpty() to ""
            }

            val generalPattern = Pattern.compile(
                "^(?:please\\s+)?(?:read|check|hear|tell\\s+me|any)\\s+(?:my\\s+|all\\s+)?(?:new\\s+|latest\\s+|recent\\s+|unread\\s+)?(?:(whatsapp|telegram|instagram|sms|text)\\s+)?(?:messages?|notifications?)$",
                Pattern.CASE_INSENSITIVE,
            )
            val mGen = generalPattern.matcher(trimmed)
            if (mGen.matches()) {
                val app = mGen.group(1)?.trim()?.lowercase().orEmpty()
                return "" to if (app == "sms" || app == "text") "messages" else app
            }

            return null
        }

        /**
         * Parses commands like:
         * - "reply to Rahul saying I'll be there in 5 minutes"
         * - "reply to that message saying I'm on my way"
         * - "reply to Mom that I will call later"
         * - "reply saying okay got it"
         * Returns Pair(senderQuery, replyText) or null.
         */
        fun extractNotificationReply(text: String): Pair<String, String>? {
            val trimmed = text.trim()
            val patterns = listOf(
                Pattern.compile(
                    "^(?:please\\s+)?reply\\s+to\\s+(.+?)\\s+(?:saying|that|:|-)\\s+(.+)$",
                    Pattern.CASE_INSENSITIVE,
                ),
                Pattern.compile(
                    "^(?:please\\s+)?reply\\s+(?:to\\s+(?:that|the|last|latest)\\s+message\\s+)?(?:saying|that|:|with)\\s+(.+)$",
                    Pattern.CASE_INSENSITIVE,
                ),
            )

            val m0 = patterns[0].matcher(trimmed)
            if (m0.matches()) {
                val rawTarget = m0.group(1)?.trim().orEmpty()
                val replyBody = m0.group(2)?.trim().orEmpty()
                if (replyBody.isNotBlank()) {
                    val genericTargets = setOf(
                        "that message", "the message", "last message", "latest message",
                        "recent message", "it", "them", "that", "this",
                    )
                    val normalizedSender = if (rawTarget.lowercase() in genericTargets) "" else rawTarget
                    return normalizedSender to replyBody
                }
            }

            val m1 = patterns[1].matcher(trimmed)
            if (m1.matches()) {
                val replyBody = m1.group(1)?.trim().orEmpty()
                if (replyBody.isNotBlank()) {
                    return "" to replyBody
                }
            }

            return null
        }
    }
}
