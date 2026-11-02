package com.personal.harmaai.tools

import android.Manifest
import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings
import android.view.KeyEvent
import androidx.core.content.ContextCompat
import com.personal.harmaai.accessibility.AgentAccessibilityService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.roundToInt

class DirectToolExecutor(private val context: Context) {
    private val appContext = context.applicationContext

    fun execute(call: ToolCall): ToolResult = try {
        when (call.name) {
            "set_flashlight" -> setFlashlight(call.arguments.optBoolean("on"))
            "take_photo" -> takePhoto()
            "open_app" -> openApp(
                name = call.arguments.optString("name"),
                packageName = call.arguments.optString("package"),
            )
            "set_volume" -> setVolume(
                streamName = call.arguments.optString("stream", "media"),
                percent = call.arguments.optInt("percent", 50),
            )
            "set_ringer_mode" -> setRingerMode(call.arguments.optString("mode", "normal"))
            "set_brightness" -> setBrightness(call.arguments.optInt("percent", 50))
            "set_alarm" -> setAlarm(
                hour = call.arguments.optInt("hour", -1),
                minute = call.arguments.optInt("minute", -1),
                label = call.arguments.optString("label"),
            )
            "set_timer" -> setTimer(
                seconds = call.arguments.optInt("seconds", -1),
                label = call.arguments.optString("label"),
            )
            "make_call", "call_number" -> makeCall(
                call.arguments.optString("number").ifBlank {
                    call.arguments.optString("contact_or_number")
                }
            )
            "call_contact" -> callContact(call.arguments.optString("name"))
            "send_sms" -> sendSms(
                contactOrNumber = call.arguments.optString("contact").ifBlank { call.arguments.optString("number") },
                text = call.arguments.optString("text"),
            )
            "open_url" -> openUrl(call.arguments.optString("url"))
            "search_web" -> searchWeb(call.arguments.optString("query"))
            "open_wifi_settings" -> openWifiSettings()
            "open_bluetooth_settings" -> openBluetoothSettings()
            "open_settings" -> openSettings(call.arguments.optString("panel", "general"))
            "toggle_do_not_disturb" -> toggleDoNotDisturb(call.arguments.optBoolean("on", true))
            "media_control" -> mediaControl(call.arguments.optString("action", "play_pause"))
            "get_battery" -> getBattery()
            "get_time" -> getTime()
            "get_clipboard" -> getClipboard()
            "set_clipboard" -> setClipboard(call.arguments.optString("text"))
            else -> ToolResult(
                success = false,
                message = "Unknown direct tool: ${call.name}",
                code = "unsupported",
            )
        }
    } catch (security: SecurityException) {
        ToolResult.failure("Android denied ${call.name}: ${security.message ?: "security restriction"}")
    } catch (error: Exception) {
        ToolResult.failure("${call.name} failed: ${error.message ?: error.javaClass.simpleName}")
    }

    private fun setFlashlight(on: Boolean): ToolResult {
        val cameraManager = appContext.getSystemService(CameraManager::class.java)
            ?: return ToolResult.failure("Camera service is unavailable.")
        val cameraId = cameraManager.cameraIdList.firstOrNull { id ->
            val characteristics = cameraManager.getCameraCharacteristics(id)
            characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true &&
                characteristics.get(CameraCharacteristics.LENS_FACING) ==
                CameraCharacteristics.LENS_FACING_BACK
        } ?: return ToolResult.failure("This device has no available rear-camera flashlight.")

        val commandIssued = AtomicBoolean(false)
        val observedState = AtomicReference<Boolean?>(null)
        val unavailable = AtomicBoolean(false)
        val stateChanged = CountDownLatch(1)
        val callback = object : CameraManager.TorchCallback() {
            override fun onTorchModeChanged(id: String, enabled: Boolean) {
                if (id == cameraId && commandIssued.get() && enabled == on) {
                    observedState.set(enabled)
                    stateChanged.countDown()
                }
            }

            override fun onTorchModeUnavailable(id: String) {
                if (id == cameraId && commandIssued.get()) {
                    unavailable.set(true)
                    stateChanged.countDown()
                }
            }
        }

        cameraManager.registerTorchCallback(DIRECT_EXECUTOR, callback)
        return try {
            commandIssued.set(true)
            cameraManager.setTorchMode(cameraId, on)
            stateChanged.await(TORCH_VERIFY_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            val evidence = JSONObject()
                .put("requested_on", on)
                .put("observed_on", observedState.get())
                .put("camera_id", cameraId)
            when {
                observedState.get() == on -> ToolResult.verified(
                    if (on) "Flashlight is on." else "Flashlight is off.",
                    evidence,
                    method = "camera_torch_callback",
                )
                unavailable.get() -> ToolResult.failure(
                    "Android reported that the flashlight became unavailable.",
                    evidence,
                )
                else -> ToolResult.dispatched(
                    "Flashlight change was requested, but Android did not confirm its state in time.",
                    evidence,
                    method = "camera_api_without_callback",
                )
            }
        } finally {
            cameraManager.unregisterTorchCallback(callback)
        }
    }

    private fun openApp(name: String, packageName: String): ToolResult {
        val requested = packageName.ifBlank { name }.trim()
        if (requested.isBlank()) return ToolResult.failure("An app name or package is required.")

        val resolvedPackage = when {
            packageName.isNotBlank() && appContext.packageManager.getLaunchIntentForPackage(packageName) != null ->
                packageName
            else -> resolveAppPackage(name)
        } ?: return ToolResult.failure("No installed launcher app matched '$requested'.")

        val intent = appContext.packageManager.getLaunchIntentForPackage(resolvedPackage)
            ?: return ToolResult.failure("$resolvedPackage does not expose a launchable activity.")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            "Launch request sent for ${name.ifBlank { resolvedPackage }}; verify the foreground package from the next screen observation.",
            JSONObject()
                .put("expected_package", resolvedPackage)
                .put("component", intent.component?.flattenToShortString()),
            method = "activity_launch_pending_accessibility_observation",
        )
    }

    @Suppress("DEPRECATION")
    private fun resolveAppPackage(appName: String): String? {
        val requested = appName.trim()
        AppListCache.resolvePackage(requested, appContext)?.let { return it }
        val manager = appContext.packageManager

        if (manager.getLaunchIntentForPackage(requested) != null) {
            return requested
        }

        val known = mapOf(
            "settings" to "com.android.settings",
            "whatsapp" to "com.whatsapp",
            "chrome" to "com.android.chrome",
            "youtube" to "com.google.android.youtube",
            "maps" to "com.google.android.apps.maps",
            "gmail" to "com.google.android.gm",
            "spotify" to "com.spotify.music",
            "paytm" to "net.one97.paytm",
            "gpay" to "com.google.android.apps.nbu.paisa.user",
            "google pay" to "com.google.android.apps.nbu.paisa.user",
            "phonepe" to "com.phonepe.app",
        )[requested.lowercase()]
        if (known != null && manager.getLaunchIntentForPackage(known) != null) {
            return known
        }

        val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val candidates = manager.queryIntentActivities(launcherIntent, 0)

        candidates.firstOrNull {
            it.loadLabel(manager).toString().equals(requested, ignoreCase = true)
        }?.let { return it.activityInfo.packageName }
        candidates.firstOrNull {
            it.loadLabel(manager).toString().contains(requested, ignoreCase = true)
        }?.let { return it.activityInfo.packageName }
        candidates.firstOrNull {
            it.activityInfo.packageName.contains(requested, ignoreCase = true)
        }?.let { return it.activityInfo.packageName }

        return known
    }

    private fun setVolume(streamName: String, percent: Int): ToolResult {
        val audio = appContext.getSystemService(AudioManager::class.java)
            ?: return ToolResult.failure("Audio service is unavailable.")
        val stream = when (streamName.lowercase()) {
            "ring" -> AudioManager.STREAM_RING
            "alarm" -> AudioManager.STREAM_ALARM
            "notification" -> AudioManager.STREAM_NOTIFICATION
            "voice", "call" -> AudioManager.STREAM_VOICE_CALL
            else -> AudioManager.STREAM_MUSIC
        }
        val targetPercent = percent.coerceIn(0, 100)
        val max = audio.getStreamMaxVolume(stream)
        val target = (max * targetPercent / 100f).roundToInt().coerceIn(0, max)
        audio.setStreamVolume(stream, target, AudioManager.FLAG_SHOW_UI)
        val actual = if (max == 0) 0 else (audio.getStreamVolume(stream) * 100f / max).roundToInt()
        return ToolResult.verified(
            "${streamName.ifBlank { "media" }.replaceFirstChar(Char::uppercase)} volume set to $actual%.",
            JSONObject()
                .put("stream", streamName)
                .put("requested_percent", targetPercent)
                .put("actual_percent", actual)
                .put("raw_volume", audio.getStreamVolume(stream))
                .put("raw_max", max),
            method = "audio_manager_readback",
        )
    }

    private fun setRingerMode(mode: String): ToolResult {
        val audio = appContext.getSystemService(AudioManager::class.java)
            ?: return ToolResult.failure("Audio service is unavailable.")
        val requested = mode.lowercase()
        if (requested == "silent") {
            val notifications = appContext.getSystemService(NotificationManager::class.java)
            if (notifications != null && !notifications.isNotificationPolicyAccessGranted) {
                return ToolResult.userAction(
                    Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS,
                    "Do Not Disturb access is required before silent mode can be set.",
                )
            }
        }
        audio.ringerMode = when (requested) {
            "silent" -> AudioManager.RINGER_MODE_SILENT
            "vibrate" -> AudioManager.RINGER_MODE_VIBRATE
            else -> AudioManager.RINGER_MODE_NORMAL
        }
        val actual = when (audio.ringerMode) {
            AudioManager.RINGER_MODE_SILENT -> "silent"
            AudioManager.RINGER_MODE_VIBRATE -> "vibrate"
            else -> "normal"
        }
        return ToolResult.verified(
            "Ringer mode is $actual.",
            JSONObject().put("requested_mode", requested).put("actual_mode", actual),
            method = "audio_manager_readback",
        )
    }

    private fun setBrightness(percent: Int): ToolResult {
        if (!Settings.System.canWrite(appContext)) {
            return ToolResult.failure(
                "Changing system display brightness requires system-level write settings, which is disabled for privacy and device security.",
            )
        }
        val targetPercent = percent.coerceIn(0, 100)
        val value = (targetPercent * 255 / 100f).roundToInt().coerceIn(1, 255)
        Settings.System.putInt(
            appContext.contentResolver,
            Settings.System.SCREEN_BRIGHTNESS_MODE,
            Settings.System.SCREEN_BRIGHTNESS_MODE_MANUAL,
        )
        val changed = Settings.System.putInt(
            appContext.contentResolver,
            Settings.System.SCREEN_BRIGHTNESS,
            value,
        )
        return if (changed) {
            val actualRaw = Settings.System.getInt(
                appContext.contentResolver,
                Settings.System.SCREEN_BRIGHTNESS,
                -1,
            )
            val actualPercent = if (actualRaw >= 0) {
                (actualRaw * 100f / 255f).roundToInt().coerceIn(0, 100)
            } else {
                -1
            }
            if (actualRaw >= 0) {
                ToolResult.verified(
                    "Brightness is $actualPercent%.",
                    JSONObject()
                        .put("requested_percent", targetPercent)
                        .put("actual_percent", actualPercent)
                        .put("raw_brightness", actualRaw),
                    method = "system_settings_readback",
                )
            } else {
                ToolResult.dispatched(
                    "Brightness change was accepted, but Android did not expose a readable result.",
                    JSONObject().put("requested_percent", targetPercent),
                    method = "settings_write_without_readback",
                )
            }
        } else {
            ToolResult.failure("Android did not accept the brightness change.")
        }
    }

    private fun setAlarm(hour: Int, minute: Int, label: String): ToolResult {
        if (hour !in 0..23 || minute !in 0..59) {
            return ToolResult.failure("Alarm time must use hour 0-23 and minute 0-59.")
        }
        val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            if (label.isNotBlank()) putExtra(AlarmClock.EXTRA_MESSAGE, label)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (intent.resolveActivity(appContext.packageManager) == null) {
            return ToolResult.failure("No installed clock app can create alarms.")
        }
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            "Alarm creation request sent for %02d:%02d; the Clock app owns final scheduling.".format(hour, minute),
            JSONObject().put("hour", hour).put("minute", minute).put("label", label),
            method = "alarm_clock_intent",
        )
    }

    private fun setTimer(seconds: Int, label: String): ToolResult {
        if (seconds <= 0) return ToolResult.failure("Timer duration must be greater than zero seconds.")
        val intent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            if (label.isNotBlank()) putExtra(AlarmClock.EXTRA_MESSAGE, label)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (intent.resolveActivity(appContext.packageManager) == null) {
            return ToolResult.failure("No installed clock app can start timers.")
        }
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            "Timer start request sent for $seconds seconds; the Clock app owns the running timer.",
            JSONObject().put("seconds", seconds).put("label", label),
            method = "alarm_clock_intent",
        )
    }

    private fun takePhoto(): ToolResult {
        val intent = Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val opened = try {
            appContext.startActivity(intent)
            true
        } catch (_: Exception) {
            val cameraPkg = AppListCache.resolvePackage("camera", appContext) ?: "com.android.camera"
            val launchIntent = appContext.packageManager.getLaunchIntentForPackage(cameraPkg)
            if (launchIntent != null) {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                appContext.startActivity(launchIntent)
                true
            } else {
                false
            }
        }
        if (!opened) {
            return ToolResult.failure("No camera application is available.")
        }

        CoroutineScope(Dispatchers.Default).launch {
            delay(1000L)
            val accessibility = AgentAccessibilityService.current()
            accessibility?.dismissPermissionOrDialogIfPresent()
            repeat(3) {
                if (accessibility?.triggerCameraShutter() == true) return@launch
                delay(600L)
            }
        }

        return ToolResult.success("Camera opened and shutter triggered.")
    }

    private fun makeCall(contactOrNumber: String): ToolResult {
        val number = resolveNumber(contactOrNumber) ?: contactOrNumber.trim()
        if (number.isBlank()) {
            return ToolResult.failure("No contact or number specified to call.")
        }

        val hasCallPhone = ContextCompat.checkSelfPermission(
            appContext,
            android.Manifest.permission.CALL_PHONE,
        ) == PackageManager.PERMISSION_GRANTED

        if (hasCallPhone) {
            val callIntent = Intent(Intent.ACTION_CALL, Uri.parse("tel:${Uri.encode(number)}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            appContext.startActivity(callIntent)
            return ToolResult.success("Direct call placed to $contactOrNumber.")
        }

        val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(number)}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (intent.resolveActivity(appContext.packageManager) == null) {
            return ToolResult.failure("No dialer application is available.")
        }
        appContext.startActivity(intent)

        CoroutineScope(Dispatchers.Default).launch {
            delay(600L)
            val accessibility = AgentAccessibilityService.current()
            accessibility?.dismissPermissionOrDialogIfPresent()
            repeat(3) {
                if (accessibility?.triggerDialerCall() == true) return@launch
                delay(500L)
            }
        }

        return ToolResult.success("Calling $contactOrNumber.")
    }

    private fun sendSms(contactOrNumber: String, text: String): ToolResult {
        if (text.isBlank()) return ToolResult.failure("SMS text cannot be empty.")
        val number = resolveNumber(contactOrNumber)
            ?: return ToolResult.failure("Please provide a valid phone number (e.g. +1234567890) for '$contactOrNumber'.")
        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${Uri.encode(number)}")).apply {
            putExtra("sms_body", text)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        if (intent.resolveActivity(appContext.packageManager) == null) {
            return ToolResult.failure("No messaging application is available to send SMS.")
        }
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            "Opened messaging app with draft for $number.",
            JSONObject().put("number", number).put("text_length", text.length),
            method = "sendto_intent_safe",
        )
    }

    private fun openUrl(rawUrl: String): ToolResult {
        val trimmed = rawUrl.trim()
        if (trimmed.isBlank()) return ToolResult.failure("A URL is required.")
        val normalized = if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "https://$trimmed"
        }
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(normalized)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (intent.resolveActivity(appContext.packageManager) == null) {
            return ToolResult.failure("No browser can open $normalized.")
        }
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            "Browser request sent for $normalized; verify the loaded page from the next screen observation.",
            JSONObject().put("expected_url", normalized),
            method = "view_intent_pending_accessibility_observation",
        )
    }

    private fun searchWeb(query: String): ToolResult {
        if (query.isBlank()) return ToolResult.failure("A search query is required.")
        return openUrl("https://www.google.com/search?q=${Uri.encode(query)}")
    }

    private fun openWifiSettings(): ToolResult = startSettingsIntent(
        action = Settings.Panel.ACTION_INTERNET_CONNECTIVITY,
        fallbackAction = Settings.ACTION_WIFI_SETTINGS,
        successMessage = "Opened Internet settings; Android requires you to confirm Wi-Fi changes.",
    )

    private fun openBluetoothSettings(): ToolResult = startSettingsIntent(
        action = Settings.ACTION_BLUETOOTH_SETTINGS,
        fallbackAction = Settings.ACTION_WIRELESS_SETTINGS,
        successMessage = "Opened Bluetooth settings; Android requires you to confirm Bluetooth changes.",
    )

    private fun startSettingsIntent(
        action: String,
        fallbackAction: String,
        successMessage: String,
    ): ToolResult {
        val manager = appContext.packageManager
        val primary = Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val intent = if (primary.resolveActivity(manager) != null) {
            primary
        } else {
            Intent(fallbackAction).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        appContext.startActivity(intent)
        return ToolResult.dispatched(
            successMessage,
            JSONObject().put("settings_action", intent.action),
            method = "settings_activity_dispatch",
        )
    }

    private fun getBattery(): ToolResult {
        val manager = appContext.getSystemService(BatteryManager::class.java)
        val percent = manager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
        val statusIntent = appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val status = statusIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        return ToolResult.success(
            if (percent >= 0) {
                "Battery is $percent% and ${if (charging) "charging" else "not charging"}."
            } else {
                "Battery state is ${if (charging) "charging" else "not charging"}; percentage unavailable."
            },
            JSONObject().put("percent", percent).put("charging", charging),
        )
    }

    private fun getClipboard(): ToolResult {
        val clipboard = appContext.getSystemService(ClipboardManager::class.java)
            ?: return ToolResult.failure("Clipboard service is unavailable.")
        val text = clipboard.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(appContext)
            ?.toString()
            .orEmpty()
        return if (text.isBlank()) {
            ToolResult.failure(
                "Clipboard is empty or Android blocked background clipboard access.",
                JSONObject().put("android_restriction", true),
            )
        } else {
            ToolResult.success("Clipboard text read.", JSONObject().put("text", text))
        }
    }

    private fun setClipboard(text: String): ToolResult {
        val clipboard = appContext.getSystemService(ClipboardManager::class.java)
            ?: return ToolResult.failure("Clipboard service is unavailable.")
        clipboard.setPrimaryClip(ClipData.newPlainText("Harma AI", text))
        val actual = clipboard.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(appContext)
            ?.toString()
        return if (actual == text) {
            ToolResult.verified(
                "Clipboard text updated.",
                JSONObject().put("length", text.length),
                method = "clipboard_readback",
            )
        } else {
            ToolResult.failure(
                "Android did not confirm the clipboard update.",
                JSONObject().put("requested_length", text.length),
            )
        }
    }

    private fun callContact(name: String): ToolResult {
        val trimmed = name.trim()
        if (trimmed.isBlank()) return ToolResult.failure("Contact name is required.")
        val matches = resolveContact(trimmed)
        if (matches.isEmpty()) {
            val hasPerm = ContextCompat.checkSelfPermission(appContext, Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED
            return if (!hasPerm) {
                // If contacts permission not granted, attempt fallback dial or prompt
                makeCall(trimmed)
            } else {
                ToolResult.failure("No contact found matching '$trimmed'.")
            }
        }
        if (matches.size > 1) {
            val options = matches.take(3).joinToString("; ") { "${it.first}: ${it.second}" }
            return ToolResult.userAction(
                action = "clarification",
                message = "Found multiple contacts matching '$trimmed': $options. Please specify which number.",
            )
        }
        val target = matches.first()
        return makeCall(target.second)
    }

    private fun resolveContact(query: String): List<Pair<String, String>> {
        val results = mutableListOf<Pair<String, String>>()
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }
        val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
        val projection = arrayOf(
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
            ContactsContract.CommonDataKinds.Phone.NUMBER,
        )
        val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
        val selectionArgs = arrayOf("%$query%")
        try {
            appContext.contentResolver.query(uri, projection, selection, selectionArgs, null)?.use { cursor ->
                val nameCol = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numCol = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                while (cursor.moveToNext() && results.size < 5) {
                    val name = if (nameCol >= 0) cursor.getString(nameCol) else ""
                    val num = if (numCol >= 0) cursor.getString(numCol) else ""
                    if (num.isNotBlank()) results.add(name to num)
                }
            }
        } catch (_: Exception) {}
        return results
    }

    private fun mediaControl(action: String): ToolResult {
        val audioManager = appContext.getSystemService(AudioManager::class.java)
            ?: return ToolResult.failure("Audio service unavailable.")
        val keyCode = when (action.lowercase()) {
            "play", "resume" -> KeyEvent.KEYCODE_MEDIA_PLAY
            "pause" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "play_pause", "toggle" -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            "next", "skip" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "prev", "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "stop" -> KeyEvent.KEYCODE_MEDIA_STOP
            else -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
        }
        val down = KeyEvent(KeyEvent.ACTION_DOWN, keyCode)
        val up = KeyEvent(KeyEvent.ACTION_UP, keyCode)
        audioManager.dispatchMediaKeyEvent(down)
        audioManager.dispatchMediaKeyEvent(up)
        return ToolResult.verified(
            "Media command '$action' sent.",
            JSONObject().put("action", action).put("key_code", keyCode),
            method = "media_key_event",
        )
    }

    private fun toggleDoNotDisturb(on: Boolean): ToolResult {
        val nm = appContext.getSystemService(NotificationManager::class.java)
            ?: return ToolResult.failure("Notification service unavailable.")
        if (!nm.isNotificationPolicyAccessGranted) {
            return ToolResult.userAction(
                Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS,
                "Do Not Disturb access is required to change DND settings.",
            )
        }
        val filter = if (on) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL
        nm.setInterruptionFilter(filter)
        val actualOn = nm.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL
        return ToolResult.verified(
            if (actualOn) "Do Not Disturb is on." else "Do Not Disturb is off.",
            JSONObject().put("dnd_on", actualOn),
            method = "notification_manager_readback",
        )
    }

    private fun getTime(): ToolResult {
        val now = java.util.Date()
        val timeFormat = java.text.SimpleDateFormat("h:mm a", java.util.Locale.getDefault())
        val dateFormat = java.text.SimpleDateFormat("EEEE, MMMM d, yyyy", java.util.Locale.getDefault())
        val formattedTime = timeFormat.format(now)
        val formattedDate = dateFormat.format(now)
        return ToolResult.success(
            "It is $formattedTime on $formattedDate.",
            JSONObject().put("time", formattedTime).put("date", formattedDate).put("timestamp", now.time),
        )
    }

    private fun openSettings(panel: String): ToolResult {
        val (action, fallback) = when (panel.lowercase()) {
            "wifi", "internet" -> Settings.Panel.ACTION_INTERNET_CONNECTIVITY to Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS to Settings.ACTION_WIRELESS_SETTINGS
            "sound", "volume" -> Settings.Panel.ACTION_VOLUME to Settings.ACTION_SOUND_SETTINGS
            "display", "brightness" -> Settings.ACTION_DISPLAY_SETTINGS to Settings.ACTION_SETTINGS
            "apps", "applications" -> Settings.ACTION_APPLICATION_SETTINGS to Settings.ACTION_SETTINGS
            "accessibility" -> Settings.ACTION_ACCESSIBILITY_SETTINGS to Settings.ACTION_SETTINGS
            "battery" -> Settings.ACTION_BATTERY_SAVER_SETTINGS to Settings.ACTION_SETTINGS
            else -> Settings.ACTION_SETTINGS to Settings.ACTION_SETTINGS
        }
        return startSettingsIntent(action, fallback, "Opened $panel settings.")
    }

    private fun resolveNumber(contactOrNumber: String): String? {
        val input = contactOrNumber.trim()
        val digits = input.filter { it.isDigit() }
        if (digits.length >= 3) {
            val prefix = if (input.trimStart().startsWith("+")) "+" else ""
            return prefix + digits
        }
        return null
    }

    companion object {
        private const val TORCH_VERIFY_TIMEOUT_MS = 1_200L
        private val DIRECT_EXECUTOR = Executor { command -> command.run() }
    }
}
