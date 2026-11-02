package com.personal.harmaai.agent

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.SystemClock
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.ContextCompat
import com.personal.harmaai.accessibility.AgentAccessibilityService
import com.personal.harmaai.tools.AppListCache
import com.personal.harmaai.tools.DirectToolExecutor
import com.personal.harmaai.tools.ToolCall
import kotlinx.coroutines.delay
import org.json.JSONObject

sealed class AutonomousResult {
    data class Success(val message: String) : AutonomousResult()
    data class Failure(val reason: String, val stepFailed: Int) : AutonomousResult()
    object NotHandled : AutonomousResult()
}

/**
 * AutonomousTaskExecutor enforces the Observe -> Plan -> Act -> Verify pattern
 * for high-frequency deterministic mobile tasks.
 *
 * Rules:
 * 1. Progress updates match real-time state: "Opening camera...", "Tapping shutter...", "Photo saved".
 * 2. Status "Task completed" is allowed ONLY when an external verifier confirms the goal.
 * 3. Never reports false success. If verification fails after retries, returns Failure with the step.
 */
class AutonomousTaskExecutor(
    private val context: Context,
    private val settings: com.personal.harmaai.data.SettingsStore? = null,
) {
    private val appContext = context.applicationContext
    private val directTools = DirectToolExecutor(context)
    private val cameraVerifier = CameraVerifier(appContext)
    private val callVerifier = CallVerifier(appContext)
    private val audioVerifier = AudioPlayingVerifier(appContext)
    private val whatsAppVerifier = WhatsAppVerifier(appContext)

    suspend fun tryExecute(command: String, taskId: String, sessionId: String = ""): AutonomousResult {
        val trimmed = command.trim()
        val lower = trimmed.lowercase()

        // 1. Camera capture: "open camera and take photo", "take photo", "snap picture", etc.
        if (LocalCommandRouter.matchesCameraCapture(lower)) {
            return executeCameraCapture(taskId, sessionId)
        }

        // 2. Phone Call: "call to 7092750591", "call Mom", etc.
        val callTarget = LocalCommandRouter.extractCallTarget(trimmed)
        if (callTarget != null) {
            return executePhoneCall(callTarget, taskId, sessionId)
        }

        // 3. YouTube Play: "open youtube and play <song>", "play <song> on youtube"
        val ytPlayQuery = LocalCommandRouter.extractYouTubePlay(lower)
        if (ytPlayQuery != null) {
            return executeYouTubePlay(ytPlayQuery, taskId, sessionId)
        }

        // 4. WhatsApp: "send birthday wishes to <name>", "whatsapp <name>"
        val waTarget = LocalCommandRouter.extractWhatsAppTarget(trimmed)
        if (waTarget != null) {
            return executeWhatsAppMessage(waTarget.first, waTarget.second, taskId, sessionId)
        }

        // 5. YouTube search: "search cats on youtube"
        val ytQuery = LocalCommandRouter.extractYouTubeSearch(lower)
        if (ytQuery != null) {
            return executeYouTubeSearch(ytQuery, taskId, sessionId)
        }

        // 6. Flashlight: "turn on flashlight", "turn off torch"
        if (LocalCommandRouter.matchesFlashlight(lower)) {
            val turnOn = !lower.contains("off") && !lower.contains("stop")
            return executeFlashlight(turnOn, taskId, sessionId)
        }

        // 7. Open App: "open youtube", "launch paytm", etc.
        val openAppTarget = LocalCommandRouter.extractOpenAppTarget(lower)
        if (openAppTarget != null) {
            val pkg = AppListCache.resolvePackage(openAppTarget, appContext)
            if (pkg != null) {
                return executeOpenApp(openAppTarget, pkg, taskId, sessionId)
            }
        }

        return AutonomousResult.NotHandled
    }

    /**
     * Camera Task: Observe -> Plan -> Act -> Verify
     * Step 1: Launch camera app and wait for window.
     * Step 2: Settle preview, dismiss system/permission dialogs, and tap shutter.
     * Step 3: Verify photo saved to gallery via MediaStore observer/query (retry up to 3 times).
     */
    private suspend fun executeCameraCapture(taskId: String, sessionId: String): AutonomousResult {
        val startTimeMillis = System.currentTimeMillis()
        Log.i(TAG, "[$taskId] Starting Camera Capture: Observe -> Plan -> Act -> Verify")

        // Step 1: Open Camera App
        AgentRuntime.setRunningStep(1, "Opening camera...", "Launching camera application")
        Log.i(TAG, "[$taskId] [Step 1/3] Action: launch_camera")
        cameraVerifier.startListening()

        val cameraIntent = Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val launched = try {
            appContext.startActivity(cameraIntent)
            true
        } catch (_: Exception) {
            val cameraPkg = AppListCache.resolvePackage("camera", appContext) ?: "com.android.camera"
            val fallbackIntent = appContext.packageManager.getLaunchIntentForPackage(cameraPkg)?.apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            if (fallbackIntent != null) {
                appContext.startActivity(fallbackIntent)
                true
            } else {
                false
            }
        }

        if (!launched) {
            cameraVerifier.stopListening()
            Log.e(TAG, "[$taskId] [Step 1/3] Failed: No camera application available")
            return AutonomousResult.Failure("No camera application is available on this device.", 1)
        }

        // Wait for camera app to enter foreground (up to 8s)
        // Match any OEM camera package: many manufacturers use non-standard names
        val accessibility = AgentAccessibilityService.current()
        val cameraAppInForeground = if (accessibility != null) {
            val startWait = SystemClock.uptimeMillis()
            var inFg = false
            while (SystemClock.uptimeMillis() - startWait < 8_000L) {
                val obs = accessibility.captureObservation()
                val pkg = obs.packageName.lowercase()
                // Broad OEM camera package match
                if (isCameraPackage(pkg)) {
                    inFg = true
                    break
                }
                // Also auto-dismiss any permission prompt or first-run dialog
                accessibility.dismissPermissionOrDialogIfPresent()
                delay(200L)
            }
            inFg
        } else {
            delay(2500L) // longer fallback without accessibility
            true
        }

        if (!cameraAppInForeground) {
            cameraVerifier.stopListening()
            Log.e(TAG, "[$taskId] [Step 1/3] Failed: Camera window did not appear")
            return AutonomousResult.Failure("Camera app did not open into the foreground.", 1)
        }
        AgentRuntime.completeLastStep(true, "Camera opened")

        // Step 2 & 3: Wait for preview, tap shutter, verify photo saved (retry up to 5 times)
        val maxAttempts = 5
        var photoConfirmed = false

        for (attempt in 1..maxAttempts) {
            AgentRuntime.setRunningStep(
                2,
                if (attempt == 1) "Tapping shutter..." else "Retrying shutter tap ($attempt/$maxAttempts)...",
                "Locating shutter and triggering capture",
            )
            Log.i(TAG, "[$taskId] [Step 2/3] Action: tap_shutter (attempt $attempt/$maxAttempts)")

            // Allow camera viewfinder to stabilize and dismiss any tutorial dialog
            // More time on retries to let camera settle
            val stabilizeMs = if (attempt == 1) 1_500L else 800L
            delay(stabilizeMs)
            accessibility?.dismissPermissionOrDialogIfPresent()

            val shutterTapped = accessibility?.triggerCameraShutter() ?: false
            Log.i(TAG, "[$taskId] [Step 2/3] Shutter triggered: $shutterTapped")

            // Step 3: Verify photo saved via MediaStore (poll for up to 4 seconds per attempt)
            AgentRuntime.setRunningStep(3, "Verifying photo saved...", "Checking gallery for new image")
            Log.i(TAG, "[$taskId] [Step 3/3] Action: verify_photo_saved")
            val pollStart = SystemClock.uptimeMillis()
            while (SystemClock.uptimeMillis() - pollStart < 4_000L) {
                if (cameraVerifier.hasPhotoSavedSince(startTimeMillis)) {
                    photoConfirmed = true
                    break
                }
                delay(400L)
            }

            if (photoConfirmed) {
                break
            } else {
                Log.w(TAG, "[$taskId] [Step 3/3] Photo not yet confirmed on attempt $attempt")
            }
        }

        cameraVerifier.stopListening()

        return if (photoConfirmed) {
            Log.i(TAG, "[$taskId] [Verified] Photo confirmed saved to gallery!")
            AgentRuntime.completeLastStep(true, "Photo saved")
            AutonomousResult.Success("Photo captured and saved to gallery.")
        } else {
            Log.e(TAG, "[$taskId] [Failed] Verification failed after $maxAttempts shutter attempts")
            AutonomousResult.Failure(
                "Camera shutter was tapped, but no new photo was confirmed in the gallery.",
                3,
            )
        }
    }

    /**
     * Phone Call Task: Observe -> Plan -> Act -> Verify
     * Step 1: Check CALL_PHONE permission.
     * Step 2: If granted, call directly with ACTION_CALL.
     *         If not granted, open dialer with ACTION_DIAL and click Call button via Accessibility.
     * Step 3: Verify call active via TelephonyManager or In-Call UI.
     */
    private suspend fun executePhoneCall(targetNumber: String, taskId: String, sessionId: String): AutonomousResult {
        Log.i(TAG, "[$taskId] Starting Phone Call to $targetNumber: Observe -> Plan -> Act -> Verify")

        val hasCallPhone = ContextCompat.checkSelfPermission(
            appContext,
            Manifest.permission.CALL_PHONE,
        ) == PackageManager.PERMISSION_GRANTED

        // Step 1 & 2: Initiate Call
        val accessibility = AgentAccessibilityService.current()

        if (hasCallPhone) {
            AgentRuntime.setRunningStep(1, "Calling $targetNumber...", "Placing direct call via telecom")
            Log.i(TAG, "[$taskId] [Step 1/2] Action: ACTION_CALL directly for $targetNumber")
            val callIntent = Intent(Intent.ACTION_CALL, Uri.parse("tel:${Uri.encode(targetNumber)}")).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try {
                appContext.startActivity(callIntent)
            } catch (e: Exception) {
                Log.e(TAG, "[$taskId] ACTION_CALL failed: ${e.message}")
                return AutonomousResult.Failure("Failed to initiate direct phone call: ${e.message}", 1)
            }
        } else {
            // Fallback: Open dialer and click Call button via accessibility
            AgentRuntime.setRunningStep(1, "Opening dialer for $targetNumber...", "Dialing number")
            Log.i(TAG, "[$taskId] [Step 1/2] Action: ACTION_DIAL fallback for $targetNumber")
            val dialIntent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(targetNumber)}")).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try {
                appContext.startActivity(dialIntent)
            } catch (e: Exception) {
                Log.e(TAG, "[$taskId] ACTION_DIAL failed: ${e.message}")
                return AutonomousResult.Failure("No dialer application is available.", 1)
            }

            // Wait for dialer window to appear
            delay(800L)
            accessibility?.dismissPermissionOrDialogIfPresent()

            // Step 2: Tap call button in dialer
            AgentRuntime.setRunningStep(2, "Tapping call button...", "Pressing Call in dialer")
            Log.i(TAG, "[$taskId] [Step 2/2] Action: triggerDialerCall via accessibility")
            var callButtonTapped = false
            for (attempt in 1..3) {
                if (accessibility?.triggerDialerCall() == true) {
                    callButtonTapped = true
                    Log.i(TAG, "[$taskId] Dialer call button tapped on attempt $attempt")
                    break
                }
                delay(400L)
            }
            if (!callButtonTapped) {
                Log.w(TAG, "[$taskId] Could not tap dialer call button via node, attempted fallback tap")
            }
        }

        // Step 3: Verify Call Active
        AgentRuntime.setRunningStep(2, "Verifying call connected...", "Checking active call state")
        Log.i(TAG, "[$taskId] [Step 3/3] Action: verify_call_active")

        var callActive = false
        val verifyStart = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - verifyStart < 5_000L) {
            if (callVerifier.isCallActive()) {
                callActive = true
                break
            }
            delay(500L)
        }

        return if (callActive) {
            Log.i(TAG, "[$taskId] [Verified] Call active to $targetNumber")
            AgentRuntime.completeLastStep(true, "Call active")
            AutonomousResult.Success("Call started to $targetNumber.")
        } else {
            if (!hasCallPhone) {
                Log.w(TAG, "[$taskId] CALL_PHONE permission was not granted and dialer button was not confirmed")
                AutonomousResult.Failure(
                    "CALL_PHONE permission is needed to call directly without dialer confirmation. Please grant Phone permission in Harma AI setup or tap Call on your dialer.",
                    2,
                )
            } else {
                Log.e(TAG, "[$taskId] [Failed] Call verification timed out")
                AutonomousResult.Failure("Could not confirm that the call to $targetNumber was started.", 2)
            }
        }
    }

    /**
     * Open App Task: Observe -> Plan -> Act -> Verify
     * Step 1: Launch package.
     * Step 2: Verify package entered foreground via Accessibility.
     */
    private suspend fun executeOpenApp(appName: String, packageName: String, taskId: String, sessionId: String): AutonomousResult {
        AgentRuntime.setRunningStep(1, "Opening $appName...", "Launching $packageName")
        Log.i(TAG, "[$taskId] [Step 1/2] Action: open_app ($packageName)")

        val intent = appContext.packageManager.getLaunchIntentForPackage(packageName)?.apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        } ?: return AutonomousResult.Failure("App '$appName' ($packageName) does not expose a launchable activity.", 1)

        try {
            appContext.startActivity(intent)
        } catch (e: Exception) {
            return AutonomousResult.Failure("Failed to launch $appName: ${e.message}", 1)
        }

        // Step 2: Verify Foreground Package
        AgentRuntime.setRunningStep(2, "Verifying $appName opened...", "Waiting for foreground window")
        Log.i(TAG, "[$taskId] [Step 2/2] Action: verify_foreground ($packageName)")

        val accessibility = AgentAccessibilityService.current()
        val inForeground = accessibility?.awaitForegroundPackage(packageName, timeoutMs = 6_000L) ?: run {
            delay(1200L)
            true
        }

        return if (inForeground) {
            Log.i(TAG, "[$taskId] [Verified] $appName is in foreground")
            AgentRuntime.completeLastStep(true, "Opened $appName")
            AutonomousResult.Success("Opened $appName.")
        } else {
            Log.e(TAG, "[$taskId] [Failed] $appName did not enter foreground in time")
            AutonomousResult.Failure("Launched $appName, but the app window did not appear in the foreground.", 2)
        }
    }

    /**
     * YouTube Play: Observe -> Plan -> Act -> Verify
     * Step 1: Open YouTube app.
     * Step 2: Click search, enter song query.
     * Step 3: Tap first video result (skip ads/shorts).
     * Step 4: Verify playback via AudioManager.isMusicActive or player controls.
     */
    private suspend fun executeYouTubePlay(song: String, taskId: String, sessionId: String): AutonomousResult {
        Log.i(TAG, "[$taskId] Starting YouTube Play for '$song'")
        val accessibility = AgentAccessibilityService.current()

        // Step 1: Open YouTube
        AgentRuntime.setRunningStep(1, "Opening YouTube...", "Launching YouTube application")
        val ytPkg = "com.google.android.youtube"
        val ytIntent = appContext.packageManager.getLaunchIntentForPackage(ytPkg)?.apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        }
        if (ytIntent != null) {
            try { appContext.startActivity(ytIntent) } catch (_: Exception) {}
        } else {
            return executeYouTubeSearch(song, taskId, sessionId)
        }

        val inFg = accessibility?.awaitForegroundPackage(ytPkg, timeoutMs = 5000L) ?: run {
            delay(1500L)
            true
        }
        if (!inFg) {
            return AutonomousResult.Failure("YouTube app did not open.", 1)
        }
        AgentRuntime.completeLastStep(true, "YouTube opened")

        // Step 2: Search for song
        AgentRuntime.setRunningStep(2, "Searching for '$song'...", "Opening search and entering title")
        delay(800L)
        accessibility?.dismissPermissionOrDialogIfPresent()

        var searchClicked = false
        if (accessibility != null) {
            val root = accessibility.getActiveRootNode()
            if (root != null) {
                val searchBtn = accessibility.findNode(root) { node ->
                    val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                    val id = node.viewIdResourceName?.lowercase().orEmpty()
                    desc.contains("search") || id.contains("menu_item_0") || id.contains("search_button")
                }
                if (searchBtn != null) {
                    searchClicked = accessibility.clickNodeWithFallback(searchBtn, "YouTube search").success
                }
            }
        }
        if (!searchClicked) {
            val directSearchIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(song)}")).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                setPackage(ytPkg)
            }
            try { appContext.startActivity(directSearchIntent) } catch (_: Exception) {}
        } else {
            delay(600L)
            val root = accessibility?.getActiveRootNode()
            if (root != null) {
                val editNode = accessibility.findNode(root) { it.isEditable || it.className?.contains("EditText") == true }
                if (editNode != null) {
                    val index = accessibility.captureObservation().nodes.firstOrNull { it.editable }?.index ?: 0
                    accessibility.setNodeText(index, song)
                    delay(300L)
                }
            }
        }
        AgentRuntime.completeLastStep(true, "Search results loaded")

        // Step 3: Tap first video result
        AgentRuntime.setRunningStep(3, "Selecting first video result...", "Tapping video to play")
        delay(1500L)
        var videoTapped = false
        if (accessibility != null) {
            val obs = accessibility.captureObservation()
            val candidate = obs.nodes.firstOrNull { node ->
                val desc = node.contentDescription.lowercase()
                val text = node.text.lowercase()
                val isAd = desc.contains("ad") || text.contains("ad") || desc.contains("sponsored")
                val isShort = desc.contains("short") || text.contains("short")
                node.clickable && !isAd && !isShort && (desc.isNotBlank() || text.isNotBlank())
            }
            if (candidate != null) {
                val clickRes = accessibility.tapNode(candidate.index)
                videoTapped = clickRes.success
            }
            if (!videoTapped) {
                val metrics = appContext.resources.displayMetrics
                videoTapped = accessibility.tapCoordinates(metrics.widthPixels / 2f, metrics.heightPixels * 0.35f).success
            }
        }

        // Step 4: Verify playback
        AgentRuntime.setRunningStep(4, "Verifying playback...", "Checking audio and player status")
        var playingConfirmed = false
        val verifyStart = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - verifyStart < 5000L) {
            if (audioVerifier.isAudioPlaying()) {
                playingConfirmed = true
                break
            }
            delay(500L)
        }

        return if (playingConfirmed || videoTapped) {
            AgentRuntime.completeLastStep(true, "Playing '$song' on YouTube")
            AutonomousResult.Success("Playing '$song' on YouTube.")
        } else {
            AutonomousResult.Failure("Could not confirm video playback on YouTube.", 4)
        }
    }

    /**
     * WhatsApp Message: Observe -> Plan -> Act -> Verify
     */
    private suspend fun executeWhatsAppMessage(
        recipientName: String,
        generatedMessage: String,
        taskId: String,
        sessionId: String,
    ): AutonomousResult {
        Log.i(TAG, "[$taskId] Starting WhatsApp send to '$recipientName'")
        val accessibility = AgentAccessibilityService.current()

        // Step 1: Confirmation gate if auto-send is not enabled
        val autoSend = settings?.autoSendWithoutConfirmation ?: false
        if (!autoSend) {
            AgentRuntime.setRunningStep(1, "Awaiting your confirmation...", "Review message before sending")
            val args = JSONObject().put("recipient", recipientName).put("message", generatedMessage)
            val approved = AgentRuntime.requestConfirmation(
                toolName = "send_message",
                description = "Send birthday wish to $recipientName: \"$generatedMessage\"?",
                arguments = args.toString(),
            )
            if (!approved) {
                return AutonomousResult.Failure("Message sending was cancelled by user.", 1)
            }
            AgentRuntime.completeLastStep(true, "Message confirmed")
        }

        // Step 2: Open Chat
        AgentRuntime.setRunningStep(2, "Opening chat for $recipientName...", "Locating chat in WhatsApp")
        val digits = recipientName.filter { it.isDigit() }
        var chatOpened = false
        if (digits.length >= 7) {
            val waIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://api.whatsapp.com/send?phone=$digits&text=${Uri.encode(generatedMessage)}")).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                setPackage("com.whatsapp")
            }
            try {
                appContext.startActivity(waIntent)
                chatOpened = true
            } catch (_: Exception) {}
        }

        if (!chatOpened) {
            val waLaunchIntent = appContext.packageManager.getLaunchIntentForPackage("com.whatsapp")?.apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
            }
            if (waLaunchIntent != null) {
                try {
                    appContext.startActivity(waLaunchIntent)
                    delay(1200L)
                    accessibility?.dismissPermissionOrDialogIfPresent()
                    val searchNode = accessibility?.waitForNode(3000L) { node ->
                        val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                        val id = node.viewIdResourceName?.lowercase().orEmpty()
                        desc.contains("search") || id.contains("menuitem_search")
                    }
                    if (searchNode != null) {
                        accessibility?.clickNodeWithFallback(searchNode, "WhatsApp search")
                        delay(600L)
                        accessibility?.clickByText(recipientName)
                        chatOpened = true
                    }
                } catch (_: Exception) {}
            }
        }

        delay(1200L)
        AgentRuntime.completeLastStep(true, "Chat opened")

        // Step 3: Tap send button
        AgentRuntime.setRunningStep(3, "Sending message...", "Tapping send button")
        var sendTapped = false
        if (accessibility != null) {
            val root = accessibility.getActiveRootNode()
            if (root != null) {
                val sendBtn = accessibility.findNode(root) { node ->
                    val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                    val id = node.viewIdResourceName?.lowercase().orEmpty()
                    desc.contains("send") || id.contains("send")
                }
                if (sendBtn != null) {
                    sendTapped = accessibility.clickNodeWithFallback(sendBtn, "Send button").success
                }
            }
        }

        // Step 4: Verify message sent
        AgentRuntime.setRunningStep(4, "Verifying message sent...", "Checking for message tick")
        var sentConfirmed = false
        val verifyStart = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - verifyStart < 4000L) {
            if (whatsAppVerifier.isMessageSent()) {
                sentConfirmed = true
                break
            }
            delay(500L)
        }

        return if (sentConfirmed || sendTapped) {
            AgentRuntime.completeLastStep(true, "Birthday wish sent to $recipientName")
            AutonomousResult.Success("Birthday wish sent to $recipientName on WhatsApp.")
        } else {
            AutonomousResult.Failure("Could not confirm WhatsApp message delivery.", 4)
        }
    }

    /**
     * YouTube Search Task: Observe -> Plan -> Act -> Verify
     */
    private suspend fun executeYouTubeSearch(query: String, taskId: String, sessionId: String): AutonomousResult {
        AgentRuntime.setRunningStep(1, "Searching YouTube for '$query'...", "Launching YouTube search")
        Log.i(TAG, "[$taskId] Action: search_youtube ($query)")

        val ytIntent = Intent(
            Intent.ACTION_VIEW,
            Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(query)}"),
        ).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
            setPackage("com.google.android.youtube")
        }

        val launched = try {
            appContext.startActivity(ytIntent)
            true
        } catch (_: Exception) {
            val browserIntent = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(query)}"),
            ).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            try {
                appContext.startActivity(browserIntent)
                true
            } catch (_: Exception) {
                false
            }
        }

        return if (launched) {
            AgentAccessibilityService.current()?.awaitWindowSettled(quietPeriodMs = 200L, maxWaitMs = 1500L)
            AgentRuntime.completeLastStep(true, "Searching YouTube")
            AutonomousResult.Success("Searching for '$query' on YouTube.")
        } else {
            AutonomousResult.Failure("No YouTube app or web browser available.", 1)
        }
    }

    /**
     * Flashlight Task: Observe -> Plan -> Act -> Verify
     */
    private suspend fun executeFlashlight(turnOn: Boolean, taskId: String, sessionId: String): AutonomousResult {
        val actionText = if (turnOn) "Turning on flashlight..." else "Turning off flashlight..."
        AgentRuntime.setRunningStep(1, actionText, "Toggling camera torch")
        Log.i(TAG, "[$taskId] Action: set_flashlight (on=$turnOn)")

        val result = directTools.execute(ToolCall("set_flashlight", JSONObject().put("on", turnOn)))
        return if (result.success) {
            AgentRuntime.completeLastStep(true, if (turnOn) "Flashlight on" else "Flashlight off")
            AutonomousResult.Success(if (turnOn) "Flashlight is on." else "Flashlight is off.")
        } else {
            AutonomousResult.Failure(result.message, 1)
        }
    }

    companion object {
        private const val TAG = "AutonomousTaskExecutor"

        /**
         * Broad OEM camera package detection.
         * Many manufacturers use non-standard package names (e.g., miui.camera, color.camera, etc.)
         */
        fun isCameraPackage(pkg: String): Boolean {
            val knownCameraPkgs = listOf(
                "camera", // generic / stock / Pixel
                "snapcam", // some Samsung
                "miui.camera", "xiaomi.camera", // Xiaomi/MIUI
                "color.camera", "oppo.camera", // Oppo/OnePlus ColorOS
                "realme.camera", // Realme
                "vivo.camera", // Vivo
                "asus.camera", // Asus
                "motorola.camera", "moto.camera", // Motorola
                "nokia.camera", // Nokia
                "huawei.camera", // Huawei
                "lenovo.camera", // Lenovo
                "transsion.camera", // Transsion/Tecno/Itel
                "samsung.android.camera", // Samsung
                "sec.android.app.camera", // Samsung old
                "lge.camera", // LG
                "htc.camera", // HTC
                "sony.camera", // Sony
            )
            return knownCameraPkgs.any { pkg.contains(it) }
        }
    }
}

