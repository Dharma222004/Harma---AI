package com.personal.harmaai.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.service.HarmaAgentService
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.ArrayDeque
import kotlin.coroutines.resume

class AgentAccessibilityService : AccessibilityService() {

    @Volatile
    private var lastWindowChangeAt = 0L

    @Volatile
    private var lastPackageName = ""

    @Volatile
    private var lastActivityName = ""

    @Volatile
    private var lastVolumeDownAt = 0L

    @Volatile
    private var latestObservation: ScreenObservation? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        lastWindowChangeAt = SystemClock.uptimeMillis()
    }

    override fun onKeyEvent(event: KeyEvent?): Boolean {
        if (event?.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && event.action == KeyEvent.ACTION_DOWN) {
            val status = com.personal.harmaai.agent.AgentRuntime.state.value.status
            if (status == com.personal.harmaai.agent.AgentStatus.RUNNING ||
                status == com.personal.harmaai.agent.AgentStatus.WAITING_FOR_CONFIRMATION
            ) {
                val now = SystemClock.uptimeMillis()
                if (now - lastVolumeDownAt <= 800L) {
                    lastVolumeDownAt = 0L
                    Log.i(TAG, "Emergency double Volume-Down detected! Stopping Harma AI task.")
                    HarmaAgentService.stopTask(this)
                    return true
                }
                lastVolumeDownAt = now
            }
        }
        return super.onKeyEvent(event)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        event.packageName?.toString()?.takeIf { it.isNotBlank() }?.let { pkg ->
            lastPackageName = pkg
        }
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            event.className?.toString()?.takeIf { it.isNotBlank() }?.let { cls ->
                lastActivityName = cls.substringAfterLast('.')
            }
        }
        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOWS_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED,
            AccessibilityEvent.TYPE_VIEW_SCROLLED,
            AccessibilityEvent.TYPE_VIEW_CLICKED,
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED,
            -> lastWindowChangeAt = SystemClock.uptimeMillis()
            else -> Unit
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (instance === this) instance = null
        latestObservation = null
        super.onDestroy()
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        latestObservation = null
        return super.onUnbind(intent)
    }

    @Synchronized
    fun captureObservation(maxNodes: Int = DEFAULT_MAX_NODES, sessionId: String = ""): ScreenObservation {
        val obsStart = SystemClock.uptimeMillis()
        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels
        val screenHeight = displayMetrics.heightPixels

        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        val fallbackRoot = try {
            rootInActiveWindow
        } catch (_: Exception) {
            null
        }

        val observation = ScreenParser.parse(
            windows = windowList,
            fallbackRoot = fallbackRoot,
            lastPackageName = lastPackageName,
            lastActivityName = lastActivityName,
            screenWidth = screenWidth,
            screenHeight = screenHeight,
            maxNodes = maxNodes,
        )
        latestObservation = observation

        val obsDuration = SystemClock.uptimeMillis() - obsStart
        val charCount = observation.compactJson.length
        val estTokens = charCount / 4
        if (sessionId.isNotBlank()) {
            HarmaPerf.onGetScreen(sessionId, obsDuration, observation.nodes.size, charCount, estTokens)
        }
        return observation
    }

    private fun resolveLiveForIndex(index: Int): Pair<ElementFingerprint, ElementResolver.ResolvedMatch?>? {
        val obs = latestObservation ?: captureObservation()
        val fp = obs.fingerprintAt(index) ?: return null
        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        val match = ElementResolver.resolveByFingerprint(windowList, rootInActiveWindow, fp)
        return fp to match
    }

    fun tapNode(index: Int): AccessibilityActionResult {
        val resolved = resolveLiveForIndex(index)
            ?: return failure("Element [$index] is not in the current snapshot. Re-observe the screen first.")
        val (fp, match) = resolved
        val node = match?.node
            ?: return failure("Element [$index] ('${fp.text.ifBlank { fp.contentDescription }}') moved or is no longer visible.")
        if (node.isPassword) return failure("Refusing to interact with a password field.")

        if (node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return success("Tapped element [$index] ('${fp.text.ifBlank { fp.contentDescription.ifBlank { fp.className } }}') via ACTION_CLICK.")
        }

        val screenArea = resources.displayMetrics.widthPixels * resources.displayMetrics.heightPixels
        var parent = node.parent
        repeat(MAX_PARENT_SEARCH) {
            val current = parent ?: return@repeat
            val parentBounds = Rect().also(current::getBoundsInScreen)
            val area = parentBounds.width() * parentBounds.height()
            // Avoid clicking huge container/list ancestors that cover >60% of the screen
            if (current.isClickable && area in 1..(screenArea * 6 / 10)) {
                if (current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    return success("Tapped clickable parent of element [$index].")
                }
            }
            parent = current.parent
        }
        return failure("Element [$index] did not accept ACTION_CLICK.")
    }

    suspend fun tapNodeWithFallback(index: Int): AccessibilityActionResult {
        val resolved = resolveLiveForIndex(index)
            ?: return failure("Element [$index] is not in the current snapshot. Re-observe the screen first.")
        val (fp, match) = resolved
        val direct = tapNode(index)
        if (direct.success) return direct

        val liveBounds = match?.bounds
        val cx = liveBounds?.centerX()?.toFloat() ?: fp.centerX.toFloat()
        val cy = liveBounds?.centerY()?.toFloat() ?: fp.centerY.toFloat()
        if (cx > 0f && cy > 0f) {
            val tapRes = tapCoordinates(cx, cy)
            if (tapRes.success) {
                return success("Tapped element [$index] at (${cx.toInt()}, ${cy.toInt()}) via gesture fallback.")
            }
        }
        return direct
    }

    fun resolveLiveByFingerprint(fp: ElementFingerprint): ElementResolver.ResolvedMatch? {
        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        return ElementResolver.resolveByFingerprint(windowList, rootInActiveWindow, fp)
    }

    suspend fun tapByFingerprint(fp: ElementFingerprint): AccessibilityActionResult {
        val match = resolveLiveByFingerprint(fp)
            ?: return failure("Learned UI element ('${fp.text.ifBlank { fp.contentDescription.ifBlank { fp.viewId } }}') was not found on the current screen.")
        val node = match.node
        if (node.isPassword) return failure("Refusing to interact with a password field.")

        if (node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return success("Tapped learned element ('${fp.text.ifBlank { fp.contentDescription.ifBlank { fp.viewId } }}') via ACTION_CLICK.")
        }

        val screenArea = resources.displayMetrics.widthPixels * resources.displayMetrics.heightPixels
        var parent = node.parent
        repeat(MAX_PARENT_SEARCH) {
            val current = parent ?: return@repeat
            val parentBounds = Rect().also(current::getBoundsInScreen)
            val area = parentBounds.width() * parentBounds.height()
            if (current.isClickable && area in 1..(screenArea * 6 / 10)) {
                if (current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    return success("Tapped clickable parent of learned element.")
                }
            }
            parent = current.parent
        }

        val cx = match.bounds.centerX().toFloat()
        val cy = match.bounds.centerY().toFloat()
        if (cx > 0f && cy > 0f) {
            val tapRes = tapCoordinates(cx, cy)
            if (tapRes.success) {
                return success("Tapped learned element at (${cx.toInt()}, ${cy.toInt()}) via gesture fallback.")
            }
        }
        return failure("Learned element did not accept tap.")
    }

    suspend fun typeTextByFingerprint(fp: ElementFingerprint, text: String, submit: Boolean = false): AccessibilityActionResult {
        val match = resolveLiveByFingerprint(fp)
        val node = match?.node?.takeIf {
            it.isEditable || it.className?.toString().orEmpty().contains("EditText", ignoreCase = true)
        } ?: return failure("Learned editable field ('${fp.hintText.ifBlank { fp.viewId }}') was not found on the current screen.")

        if (node.isPassword) return failure("Refusing to type into a password field.")
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val typed = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments) || runCatching {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            clipboard?.setPrimaryClip(ClipData.newPlainText("HarmaInput", text))
            node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        }.getOrDefault(false)

        if (!typed) {
            return failure("Android rejected text entry for learned editable field.")
        }
        if (submit) {
            kotlinx.coroutines.delay(150L)
            performImeEnter()
        }
        return success("Entered text into learned editable field.")
    }

    suspend fun longPressNode(index: Int, durationMs: Long = 800L): AccessibilityActionResult {
        val resolved = resolveLiveForIndex(index)
            ?: return failure("Element [$index] is not in the current snapshot. Re-observe the screen first.")
        val (fp, match) = resolved
        val node = match?.node
        if (node != null) {
            if (node.isPassword) return failure("Refusing to interact with a password field.")
            if (node.isLongClickable && node.performAction(AccessibilityNodeInfo.ACTION_LONG_CLICK)) {
                return success("Long-pressed element [$index] via ACTION_LONG_CLICK.")
            }
        }
        val cx = (match?.bounds?.centerX() ?: fp.centerX).toFloat()
        val cy = (match?.bounds?.centerY() ?: fp.centerY).toFloat()
        if (cx > 0f && cy > 0f) {
            return longPress(cx, cy, durationMs)
        }
        return failure("Could not long-press element [$index].")
    }

    fun setNodeText(index: Int, text: String): AccessibilityActionResult {
        var targetNode: AccessibilityNodeInfo? = null
        if (index >= 0) {
            val resolved = resolveLiveForIndex(index)
            val candidate = resolved?.second?.node
            if (candidate != null && (candidate.isEditable || candidate.className?.toString().orEmpty().contains("EditText", ignoreCase = true))) {
                targetNode = candidate
            }
        }
        if (targetNode == null) {
            val root = getActiveRootNode()
            if (root != null) {
                targetNode = findNode(root) {
                    (it.isEditable || it.className?.toString().orEmpty().contains("EditText", ignoreCase = true)) && it.isFocused
                } ?: findNode(root) {
                    it.isEditable || it.className?.toString().orEmpty().contains("EditText", ignoreCase = true)
                }
            }
        }

        val node = targetNode
            ?: return failure("Element [$index] is not editable and no editable input field was found on screen.")
        if (node.isPassword) return failure("Refusing to type into a password field.")

        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)) {
            return success("Entered text '$text' via ACTION_SET_TEXT.")
        }

        // Step 6 Fallback: Clipboard paste when ACTION_SET_TEXT is rejected by custom/WebView inputs
        val pasted = runCatching {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            clipboard?.setPrimaryClip(ClipData.newPlainText("HarmaInput", text))
            node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        }.getOrDefault(false)

        return if (pasted) {
            success("Entered text '$text' via clipboard paste fallback.")
        } else {
            failure("Android rejected text entry and paste for element [$index].")
        }
    }

    suspend fun performImeEnter(): AccessibilityActionResult {
        val root = getActiveRootNode()
        if (root != null) {
            val editableNode = findNode(root) {
                (it.isEditable || it.className?.toString().orEmpty().contains("EditText", ignoreCase = true)) && it.isFocused
            } ?: findNode(root) {
                it.isEditable || it.className?.toString().orEmpty().contains("EditText", ignoreCase = true)
            }
            if (editableNode != null) {
                val imeEnterId = AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id
                if (editableNode.performAction(imeEnterId)) {
                    return success("Submitted input via ACTION_IME_ENTER.")
                }
            }
            val submitBtn = findNode(root) { node ->
                val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                val text = node.text?.toString()?.lowercase().orEmpty()
                val id = node.viewIdResourceName?.lowercase().orEmpty()
                val isEdit = node.isEditable || node.className?.toString().orEmpty().contains("EditText", ignoreCase = true)
                !isEdit && node.isClickable && (
                    desc == "search" || desc == "send" || desc == "go" ||
                        text == "search" || text == "send" || text == "go" ||
                        id.endsWith("search_button") || id.endsWith("send")
                    )
            }
            if (submitBtn != null) {
                val clicked = clickNodeWithFallback(submitBtn, "submit/search button")
                if (clicked.success) return clicked
            }
        }

        // Only tap keyboard bottom-right corner if the IME keyboard window is actually open
        val imeOpen = latestObservation?.keyboardVisible == true || isImeWindowVisible()
        if (imeOpen) {
            val metrics = resources.displayMetrics
            val x = metrics.widthPixels * 0.91f
            val y = metrics.heightPixels * 0.92f
            val tapRes = tapCoordinates(x, y)
            if (tapRes.success) {
                return success("Pressed soft-keyboard Enter/Search key.")
            }
        }
        return failure("Could not trigger Enter/Search action (no IME Enter support or visible Search/Send button).")
    }

    private fun isImeWindowVisible(): Boolean = try {
        windows?.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD } == true
    } catch (_: Exception) {
        false
    }

    fun scrollNode(index: Int?, direction: String): AccessibilityActionResult {
        val resolvedNode = if (index != null && index >= 0) {
            resolveLiveForIndex(index)?.second?.node
        } else {
            null
        }
        var node = resolvedNode ?: getActiveRootNode()
            ?: return failure("No active window is available to scroll.")

        val action = if (direction.equals("up", true) || direction.equals("backward", true)) {
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        } else {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        }

        // First check if the target node or one of its ancestors is scrollable
        var curr: AccessibilityNodeInfo? = node
        repeat(MAX_PARENT_SEARCH + 1) {
            val candidate = curr ?: return@repeat
            if (candidate.isScrollable && candidate.performAction(action)) {
                return success("Scrolled ${direction.lowercase()}.")
            }
            curr = candidate.parent
        }

        // Otherwise search the tree for the primary scrollable container
        val scrollableInTree = findNode(node) { it.isScrollable }
        if (scrollableInTree != null && scrollableInTree.performAction(action)) {
            return success("Scrolled ${direction.lowercase()} on primary scrollable container.")
        }

        return failure("No scrollable container accepted scroll ${direction.lowercase()}.")
    }

    suspend fun tapCoordinates(x: Float, y: Float): AccessibilityActionResult =
        dispatchPath(
            path = Path().apply {
                moveTo(x, y)
                lineTo(x, y)
            },
            startTime = 0L,
            duration = TAP_DURATION_MS,
            successMessage = "Tapped coordinates (${x.toInt()}, ${y.toInt()}).",
        )

    suspend fun longPress(x: Float, y: Float, durationMs: Long = 800L): AccessibilityActionResult =
        dispatchPath(
            path = Path().apply {
                moveTo(x, y)
                lineTo(x, y)
            },
            startTime = 0L,
            duration = durationMs.coerceIn(500L, 2_500L),
            successMessage = "Long-pressed coordinates (${x.toInt()}, ${y.toInt()}).",
        )

    suspend fun swipe(
        x1: Float,
        y1: Float,
        x2: Float,
        y2: Float,
        durationMs: Long = 450L,
    ): AccessibilityActionResult = dispatchPath(
        path = Path().apply {
            moveTo(x1, y1)
            lineTo(x2, y2)
        },
        startTime = 0L,
        duration = durationMs.coerceIn(150L, 2_000L),
        successMessage = "Swiped from (${x1.toInt()}, ${y1.toInt()}) to (${x2.toInt()}, ${y2.toInt()}).",
    )

    fun performGlobal(action: String): AccessibilityActionResult {
        val actionId = when (action.lowercase()) {
            "back" -> GLOBAL_ACTION_BACK
            "home" -> GLOBAL_ACTION_HOME
            "recents" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            "quick_settings", "quicksettings" -> GLOBAL_ACTION_QUICK_SETTINGS
            "lock", "lock_screen" -> GLOBAL_ACTION_LOCK_SCREEN
            "screenshot", "take_screenshot" -> GLOBAL_ACTION_TAKE_SCREENSHOT
            else -> return failure("Unknown global action: $action")
        }
        return if (performGlobalAction(actionId)) {
            success("Performed global action ${action.lowercase()}.")
        } else {
            failure("Android rejected global action ${action.lowercase()}.")
        }
    }

    suspend fun captureScreenshot(quality: Int = 72): ScreenshotCapture =
        suspendCancellableCoroutine { continuation ->
            val nodesForOverlay = latestObservation?.nodes ?: emptyList()
            val metrics = resources.displayMetrics
            val screenW = metrics.widthPixels
            val screenH = metrics.heightPixels

            takeScreenshot(
                Display.DEFAULT_DISPLAY,
                mainExecutor,
                object : TakeScreenshotCallback {
                    override fun onSuccess(screenshot: ScreenshotResult) {
                        val hardwareBuffer = screenshot.hardwareBuffer
                        try {
                            val hardwareBitmap = Bitmap.wrapHardwareBuffer(
                                hardwareBuffer,
                                screenshot.colorSpace,
                            )
                            if (hardwareBitmap == null) {
                                if (continuation.isActive) {
                                    continuation.resume(
                                        ScreenshotCapture(
                                            success = false,
                                            message = "Unable to decode screenshot.",
                                            flaggedSecure = true,
                                        ),
                                    )
                                }
                                return
                            }
                            val copiedBitmap = hardwareBitmap.copy(Bitmap.Config.ARGB_8888, false)
                                ?: throw IllegalStateException("Unable to copy screenshot bitmap.")
                            hardwareBitmap.recycle()

                            val processed = VisionFallback.processAndAnnotate(
                                sourceBitmap = copiedBitmap,
                                nodes = nodesForOverlay,
                                screenWidth = screenW,
                                screenHeight = screenH,
                                quality = quality,
                            )
                            copiedBitmap.recycle()

                            if (continuation.isActive) {
                                continuation.resume(processed)
                            }
                        } catch (error: Exception) {
                            if (continuation.isActive) {
                                continuation.resume(
                                    ScreenshotCapture(
                                        success = false,
                                        message = "Screenshot failed: ${error.message}",
                                    ),
                                )
                            }
                        } finally {
                            hardwareBuffer.close()
                        }
                    }

                    override fun onFailure(errorCode: Int) {
                        if (continuation.isActive) {
                            continuation.resume(
                                ScreenshotCapture(
                                    success = false,
                                    message = "Screenshot blocked by FLAG_SECURE or unavailable (code $errorCode).",
                                    flaggedSecure = true,
                                ),
                            )
                        }
                    }
                },
            )
        }

    suspend fun awaitForegroundPackage(
        expectedPackage: String,
        timeoutMs: Long = 3_000L,
    ): Boolean {
        val target = expectedPackage.trim()
        if (target.isBlank()) return true

        val startTime = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - startTime < timeoutMs) {
            if (isPackageInForeground(target)) {
                return true
            }
            delay(50L)
        }
        return false
    }

    private fun isPackageInForeground(target: String): Boolean {
        if (lastPackageName.equals(target, ignoreCase = true) ||
            lastPackageName.contains(target, ignoreCase = true)
        ) {
            return true
        }
        val rootPkg = rootInActiveWindow?.packageName?.toString().orEmpty()
        if (rootPkg.equals(target, ignoreCase = true) || rootPkg.contains(target, ignoreCase = true)) {
            return true
        }
        try {
            val windowPkg = windows.firstOrNull { it.isActive || it.isFocused }?.root?.packageName?.toString().orEmpty()
            if (windowPkg.equals(target, ignoreCase = true) || windowPkg.contains(target, ignoreCase = true)) {
                return true
            }
        } catch (_: Exception) {}
        return false
    }

    suspend fun awaitWindowSettled(
        quietPeriodMs: Long = 200L,
        maxWaitMs: Long = 1_200L,
    ) {
        StabilityWaiter.awaitStable(
            lastEventTimestampProvider = { lastWindowChangeAt },
            actionStartTimeMs = SystemClock.uptimeMillis(),
            quietPeriodMs = quietPeriodMs,
            firstEventGraceMs = 280L,
            maxWaitMs = maxWaitMs,
        )
    }

    private suspend fun dispatchPath(
        path: Path,
        startTime: Long,
        duration: Long,
        successMessage: String,
    ): AccessibilityActionResult = suspendCancellableCoroutine { continuation ->
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, startTime, duration))
            .build()
        val accepted = dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    if (continuation.isActive) continuation.resume(success(successMessage))
                }

                override fun onCancelled(gestureDescription: GestureDescription?) {
                    if (continuation.isActive) continuation.resume(failure("Gesture was cancelled."))
                }
            },
            null,
        )
        if (!accepted && continuation.isActive) {
            continuation.resume(failure("Android rejected the gesture."))
        }
    }

    fun getActiveRootNode(): AccessibilityNodeInfo? {
        rootInActiveWindow?.let { return it }
        try {
            windows.firstOrNull { it.isFocused }?.root?.let { return it }
            windows.firstOrNull { it.isActive }?.root?.let { return it }
            windows.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }?.root?.let { return it }
        } catch (_: Exception) {}
        return null
    }

    fun findNode(root: AccessibilityNodeInfo, predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (predicate(node)) return node
            for (i in 0 until node.childCount) {
                try {
                    node.getChild(i)?.let { queue.add(it) }
                } catch (_: Exception) {}
            }
        }
        return null
    }

    suspend fun clickNodeWithFallback(node: AccessibilityNodeInfo, label: String = "element"): AccessibilityActionResult {
        if (node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return success("Clicked $label via ACTION_CLICK.")
        }
        val screenArea = resources.displayMetrics.widthPixels * resources.displayMetrics.heightPixels
        var parent = node.parent
        repeat(MAX_PARENT_SEARCH) {
            val curr = parent ?: return@repeat
            val parentBounds = Rect().also(curr::getBoundsInScreen)
            val area = parentBounds.width() * parentBounds.height()
            if (curr.isClickable && area in 1..(screenArea * 6 / 10) &&
                curr.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            ) {
                return success("Clicked parent of $label via ACTION_CLICK.")
            }
            parent = curr.parent
        }
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        if (!bounds.isEmpty && bounds.width() > 0 && bounds.height() > 0) {
            val res = tapCoordinates(bounds.exactCenterX(), bounds.exactCenterY())
            if (res.success) {
                return success("Tapped $label at (${bounds.centerX()}, ${bounds.centerY()}).")
            }
        }
        return failure("Could not click $label.")
    }

    suspend fun clickByText(text: String, exact: Boolean = false, excludeEditable: Boolean = false): AccessibilityActionResult {
        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        val match = ElementResolver.findBestNodeByTextOrDesc(
            windows = windowList,
            fallbackRoot = getActiveRootNode(),
            target = text,
            exact = exact,
            matchDescription = false,
            excludeEditable = excludeEditable,
        ) ?: return failure("Element with text '$text' not found.")
        return clickNodeWithFallback(match.node, "text '$text'")
    }

    suspend fun clickById(viewId: String): AccessibilityActionResult {
        val root = getActiveRootNode() ?: return failure("No active window.")
        val target = viewId.trim().lowercase()
        val match = findNode(root) { node ->
            node.viewIdResourceName?.lowercase()?.contains(target) == true
        } ?: return failure("Element with id '$viewId' not found.")
        return clickNodeWithFallback(match, "id '$viewId'")
    }

    suspend fun clickByContentDescription(desc: String, exact: Boolean = false): AccessibilityActionResult {
        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        val match = ElementResolver.findBestNodeByTextOrDesc(
            windows = windowList,
            fallbackRoot = getActiveRootNode(),
            target = desc,
            exact = exact,
            matchDescription = true,
            excludeEditable = false,
        ) ?: return failure("Element with content description '$desc' not found.")
        return clickNodeWithFallback(match.node, "content description '$desc'")
    }

    suspend fun tapAt(x: Float, y: Float): AccessibilityActionResult = tapCoordinates(x, y)

    fun typeText(index: Int, text: String): AccessibilityActionResult = setNodeText(index, text)

    fun pressBack(): AccessibilityActionResult = performGlobal("back")

    fun pressHome(): AccessibilityActionResult = performGlobal("home")

    suspend fun scrollToFind(targetText: String, maxScrolls: Int = 5): AccessibilityActionResult {
        val target = targetText.trim()
        val windowList = try {
            windows ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
        repeat(maxScrolls) {
            val match = ElementResolver.findBestNodeByTextOrDesc(
                windows = windowList,
                fallbackRoot = getActiveRootNode(),
                target = target,
                exact = false,
                matchDescription = false,
                excludeEditable = true,
            ) ?: ElementResolver.findBestNodeByTextOrDesc(
                windows = windowList,
                fallbackRoot = getActiveRootNode(),
                target = target,
                exact = false,
                matchDescription = true,
                excludeEditable = true,
            )
            if (match != null) {
                return clickNodeWithFallback(match.node, "scrolled-to element '$targetText'")
            }
            scrollNode(null, "down")
            awaitWindowSettled(quietPeriodMs = 180L, maxWaitMs = 700L)
        }
        return failure("Could not find '$targetText' after $maxScrolls scrolls.")
    }

    suspend fun waitForNode(timeoutMs: Long = 6000L, predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        val start = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - start < timeoutMs) {
            val root = getActiveRootNode()
            if (root != null) {
                val node = findNode(root, predicate)
                if (node != null) return node
            }
            delay(150L)
        }
        return null
    }

    suspend fun waitForPackage(targetPackage: String, timeoutMs: Long = 6000L): Boolean =
        awaitForegroundPackage(targetPackage, timeoutMs)

    suspend fun waitForTextOrPackage(target: String, timeoutMs: Long = 5000L): Boolean {
        val clean = target.trim()
        if (clean.isBlank()) return true
        val start = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - start < timeoutMs) {
            if (isPackageInForeground(clean)) return true
            val root = getActiveRootNode()
            if (root != null) {
                val matched = findNode(root) { node ->
                    node.text?.toString()?.contains(clean, ignoreCase = true) == true ||
                        node.contentDescription?.toString()?.contains(clean, ignoreCase = true) == true ||
                        node.viewIdResourceName?.contains(clean, ignoreCase = true) == true
                }
                if (matched != null) return true
            }
            delay(150L)
        }
        return false
    }

    suspend fun dismissPermissionOrDialogIfPresent(): Boolean {
        val root = getActiveRootNode() ?: return false
        val dialogKeywords = listOf(
            "while using the app",
            "only this time",
            "allow",
            "continue",
            "got it",
            "ok",
            "agree",
            "accept",
            "next",
            "dismiss",
        )
        val match = findNode(root) { node ->
            val text = node.text?.toString()?.lowercase().orEmpty()
            val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
            node.isClickable && dialogKeywords.any { kw -> text == kw || desc == kw }
        }
        if (match != null) {
            val res = clickNodeWithFallback(match, "dialog button")
            if (res.success) {
                Log.i(TAG, "Dismissed permission/system dialog: ${match.text ?: match.contentDescription}")
                delay(300L)
                return true
            }
        }
        return false
    }

    suspend fun triggerCameraShutter(): Boolean {
        val shutterKeywords = listOf(
            "shutter",
            "take photo",
            "take picture",
            "capture",
            "btn_shutter",
            "v9_shutter",
        )
        val root = getActiveRootNode()
        if (root != null) {
            val shutter = findNode(root) { node ->
                val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                val text = node.text?.toString()?.lowercase().orEmpty()
                val id = node.viewIdResourceName?.lowercase().orEmpty()
                if (id.contains("gallery") || desc.contains("gallery") || text.contains("gallery")) return@findNode false
                if (id.contains("switch") || desc.contains("switch") || text.contains("switch")) return@findNode false
                shutterKeywords.any { desc.contains(it) || text.contains(it) || id.contains(it) }
            }
            if (shutter != null) {
                val res = clickNodeWithFallback(shutter, "camera shutter")
                if (res.success) {
                    Log.i(TAG, "Camera shutter clicked via node: ${res.message}")
                    return true
                }
            }
        }
        return false
    }

    suspend fun triggerDialerCall(): Boolean {
        val callKeywords = listOf("call", "dial", "voice call", "sim 1", "sim 2", "make call")
        val root = getActiveRootNode()
        if (root != null) {
            val callBtn = findNode(root) { node ->
                val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                val text = node.text?.toString()?.lowercase().orEmpty()
                val id = node.viewIdResourceName?.lowercase().orEmpty()
                if (id.contains("search") || desc.contains("search") || text.contains("search")) return@findNode false
                if (id.contains("delete") || desc.contains("delete") || text.contains("backspace")) return@findNode false
                node.isClickable && callKeywords.any { desc.contains(it) || text.contains(it) || id.contains(it) }
            }
            if (callBtn != null) {
                val res = clickNodeWithFallback(callBtn, "dialer call button")
                if (res.success) {
                    Log.i(TAG, "Dialer call button clicked via node: ${res.message}")
                    return true
                }
            }
        }
        return false
    }

    private fun success(message: String) = AccessibilityActionResult(true, message)

    private fun failure(message: String) = AccessibilityActionResult(false, message)

    companion object {
        private const val TAG = "AgentAccessibility"
        private const val DEFAULT_MAX_NODES = 85
        private const val MAX_PARENT_SEARCH = 3
        private const val TAP_DURATION_MS = 80L

        @Volatile
        private var instance: AgentAccessibilityService? = null

        fun current(): AgentAccessibilityService? = instance

        fun isConnected(): Boolean = instance != null
    }
}
