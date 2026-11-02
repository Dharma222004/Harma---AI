package com.personal.harmaai.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import android.util.SparseArray
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.service.HarmaAgentService
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.ArrayDeque
import kotlin.coroutines.resume
import kotlin.math.max

class AgentAccessibilityService : AccessibilityService() {
    private val indexedNodes = SparseArray<AccessibilityNodeInfo>()

    @Volatile
    private var lastWindowChangeAt = 0L

    @Volatile
    private var lastPackageName = ""

    private var previousSignatures = listOf<String>()
    private var previousPackage = ""

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        lastWindowChangeAt = SystemClock.uptimeMillis()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        event.packageName?.toString()?.let { lastPackageName = it }
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
        clearIndexedNodes()
        super.onDestroy()
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        clearIndexedNodes()
        return super.onUnbind(intent)
    }

    @Synchronized
    fun captureObservation(maxNodes: Int = DEFAULT_MAX_NODES, sessionId: String = ""): ScreenObservation {
        val obsStart = SystemClock.uptimeMillis()
        clearIndexedNodes()
        var root: AccessibilityNodeInfo? = rootInActiveWindow
        var attempts = 0
        while (root == null && attempts < 3) {
            attempts++
            try {
                Thread.sleep(50L)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                break
            }
            root = rootInActiveWindow
        }

        if (root == null) {
            val activeWindow = try {
                windows.firstOrNull { it.isActive }
                    ?: windows.firstOrNull { it.isFocused }
                    ?: windows.firstOrNull { it.root != null }
            } catch (_: Exception) {
                null
            }
            root = activeWindow?.root
        }

        if (root == null) {
            val isKnownSecureApp = lastPackageName in SECURE_APP_PACKAGES ||
                lastPackageName.contains("paytm", ignoreCase = true) ||
                lastPackageName.contains("paisa", ignoreCase = true) ||
                lastPackageName.contains("upi", ignoreCase = true)

            val reason = if (isKnownSecureApp) {
                "Screen content is protected by system security (FLAG_SECURE, such as payment or UPI PIN screen). Harma AI will not read or enter sensitive credentials."
            } else {
                "No active accessibility window. The screen may be locked, transition in progress, or protected."
            }

            val unavailableJson = JSONObject()
                .put("package", lastPackageName)
                .put("unavailable", true)
                .put("protected", isKnownSecureApp)
                .put("reason", reason)
                .toString()
            return ScreenObservation(
                packageName = lastPackageName,
                windowTitle = "",
                nodes = emptyList(),
                compactJson = unavailableJson,
                protectedContent = isKnownSecureApp,
                unavailable = true,
                capturedAtMillis = System.currentTimeMillis(),
            )
        }

        val snapshots = ArrayList<UiNodeSnapshot>(maxNodes.coerceAtMost(64))
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var protectedContent = false
        val observedPackageName = root.packageName?.toString().orEmpty()
        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels
        val screenHeight = displayMetrics.heightPixels

        val currentSignatures = mutableListOf<String>()

        while (queue.isNotEmpty() && snapshots.size < maxNodes) {
            val node = queue.removeFirst()
            try {
                if (!node.isVisibleToUser) continue

                for (childIndex in 0 until node.childCount) {
                    node.getChild(childIndex)?.let(queue::addLast)
                }

                val text = safeText(node).take(MAX_FIELD_LENGTH)
                val description = node.contentDescription?.toString()?.trim().orEmpty().take(MAX_FIELD_LENGTH)
                val rawId = node.viewIdResourceName.orEmpty()
                val shortId = rawId.substringAfterLast(":id/").take(32)
                val className = node.className?.toString().orEmpty()
                val editable = node.isEditable || className.contains("EditText", ignoreCase = true)
                val actionable = node.isClickable || node.isScrollable || editable || node.isCheckable

                if (text.isBlank() && description.isBlank() && shortId.isBlank() && !actionable) continue

                val bounds = Rect().also(node::getBoundsInScreen)
                if (bounds.width() <= 0 || bounds.height() <= 0 || bounds.right <= 0 || bounds.bottom <= 0 ||
                    bounds.left >= screenWidth || bounds.top >= screenHeight
                ) {
                    continue
                }

                val password = node.isPassword
                protectedContent = protectedContent || password

                val sig = "$text|$description|$shortId|${bounds.left},${bounds.top},${bounds.right},${bounds.bottom}|$actionable"
                if (currentSignatures.isNotEmpty() && currentSignatures.last() == sig) continue
                currentSignatures.add(sig)

                val index = snapshots.size
                indexedNodes.put(index, AccessibilityNodeInfo.obtain(node))
                snapshots += UiNodeSnapshot(
                    index = index,
                    className = className.takeLast(32),
                    text = if (password) "[PROTECTED]" else text,
                    contentDescription = description,
                    viewId = shortId,
                    bounds = "${bounds.left},${bounds.top},${bounds.right},${bounds.bottom}",
                    clickable = node.isClickable,
                    editable = editable,
                    scrollable = node.isScrollable,
                    focused = node.isFocused,
                    checked = node.isChecked,
                    password = password,
                )
            } finally {
                if (node !== root) node.recycle()
            }
        }
        root.recycle()

        val packageName = observedPackageName.ifBlank { lastPackageName }
        val windowTitle = windows.firstOrNull { it.isActive }?.title?.toString().orEmpty()

        val samePackage = packageName == previousPackage
        val matchingSigs = currentSignatures.count { it in previousSignatures }
        val similarity = if (currentSignatures.isNotEmpty()) matchingSigs.toFloat() / currentSignatures.size else 0f
        val isDiff = samePackage && similarity >= 0.85f && currentSignatures.size > 5

        val compactJson = if (isDiff) {
            val changedNodes = JSONArray()
            snapshots.filter { "${it.text}|${it.contentDescription}|${it.viewId}|${it.bounds}|${it.clickable || it.editable}" !in previousSignatures }
                .forEach { node ->
                    changedNodes.put(
                        JSONObject()
                            .put("i", node.index)
                            .putOpt("t", node.text.ifBlank { null })
                            .putOpt("d", node.contentDescription.ifBlank { null })
                            .putOpt("id", node.viewId.ifBlank { null })
                            .put("b", node.bounds)
                            .putOpt("click", if (node.clickable) true else null)
                            .putOpt("edit", if (node.editable) true else null),
                    )
                }
            JSONObject()
                .put("package", packageName)
                .put("diff", true)
                .put("changed", changedNodes)
                .toString()
        } else {
            val nodeArray = JSONArray()
            snapshots.forEach { node ->
                nodeArray.put(
                    JSONObject()
                        .put("i", node.index)
                        .putOpt("t", node.text.ifBlank { null })
                        .putOpt("d", node.contentDescription.ifBlank { null })
                        .putOpt("id", node.viewId.ifBlank { null })
                        .put("b", node.bounds)
                        .putOpt("click", if (node.clickable) true else null)
                        .putOpt("edit", if (node.editable) true else null)
                        .putOpt("scroll", if (node.scrollable) true else null)
                        .putOpt("password", if (node.password) true else null),
                )
            }
            JSONObject()
                .put("package", packageName)
                .putOpt("title", windowTitle.ifBlank { null })
                .put("protected", protectedContent)
                .put("nodes", nodeArray)
                .toString()
        }

        previousSignatures = currentSignatures
        previousPackage = packageName

        val obsDuration = SystemClock.uptimeMillis() - obsStart
        val charCount = compactJson.length
        val estTokens = charCount / 4
        if (sessionId.isNotBlank()) {
            HarmaPerf.onGetScreen(sessionId, obsDuration, snapshots.size, charCount, estTokens)
        }

        return ScreenObservation(
            packageName = packageName,
            windowTitle = windowTitle,
            nodes = snapshots,
            compactJson = compactJson,
            protectedContent = protectedContent,
            unavailable = false,
            capturedAtMillis = System.currentTimeMillis(),
        )
    }

    @Synchronized
    fun tapNode(index: Int): AccessibilityActionResult {
        var node = indexedNodes[index]
            ?: return failure("Element $index is not available. Refresh the screen first.")
        if (node.isPassword) return failure("Refusing to interact with a password field.")

        if (node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return success("Tapped element $index.")
        }

        var parent = node.parent
        repeat(MAX_PARENT_SEARCH) {
            if (parent == null) return@repeat
            val current = parent ?: return@repeat
            if (current.isClickable && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                current.recycle()
                return success("Tapped clickable parent of element $index.")
            }
            val next = current.parent
            current.recycle()
            parent = next
        }
        parent?.recycle()
        return failure("Element $index was not clickable.")
    }

    @Synchronized
    fun setNodeText(index: Int, text: String): AccessibilityActionResult {
        val node = indexedNodes[index]
            ?: return failure("Element $index is not available. Refresh the screen first.")
        if (node.isPassword) return failure("Refusing to type into a password field.")
        if (!node.isEditable && !node.className?.toString().orEmpty().contains("EditText")) {
            return failure("Element $index is not editable.")
        }

        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)) {
            success("Entered text in element $index.")
        } else {
            failure("Android rejected text entry for element $index.")
        }
    }

    @Synchronized
    fun scrollNode(index: Int?, direction: String): AccessibilityActionResult {
        var node = index?.let(indexedNodes::get) ?: rootInActiveWindow
            ?: return failure("No active window is available to scroll.")
        val shouldRecycle = index == null
        val action = if (direction.equals("up", true) || direction.equals("backward", true)) {
            AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        } else {
            AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        }

        repeat(MAX_PARENT_SEARCH + 1) {
            if (node.isScrollable && node.performAction(action)) {
                if (shouldRecycle) node.recycle()
                return success("Scrolled ${direction.lowercase()}.")
            }
            val parent = node.parent ?: return@repeat
            if (shouldRecycle || node !== indexedNodes[index ?: -1]) node.recycle()
            node = parent
        }
        if (shouldRecycle) node.recycle()
        return failure("No scrollable container was found.")
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

    suspend fun captureScreenshot(quality: Int = 70): ScreenshotCapture =
        suspendCancellableCoroutine { continuation ->
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
                                        ScreenshotCapture(false, message = "Unable to decode screenshot."),
                                    )
                                }
                                return
                            }
                            val copiedBitmap = hardwareBitmap.copy(Bitmap.Config.ARGB_8888, false)
                                ?: throw IllegalStateException("Unable to copy screenshot bitmap.")
                            val longestEdge = max(copiedBitmap.width, copiedBitmap.height)
                            val bitmap = if (longestEdge > MAX_SCREENSHOT_LONG_EDGE) {
                                val scale = MAX_SCREENSHOT_LONG_EDGE.toFloat() / longestEdge
                                Bitmap.createScaledBitmap(
                                    copiedBitmap,
                                    (copiedBitmap.width * scale).toInt().coerceAtLeast(1),
                                    (copiedBitmap.height * scale).toInt().coerceAtLeast(1),
                                    true,
                                ).also { copiedBitmap.recycle() }
                            } else {
                                copiedBitmap
                            }
                            val output = ByteArrayOutputStream()
                            bitmap.compress(Bitmap.CompressFormat.JPEG, quality.coerceIn(35, 90), output)
                            val base64 = Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
                            val encodedWidth = bitmap.width
                            val encodedHeight = bitmap.height
                            bitmap.recycle()
                            if (continuation.isActive) {
                                continuation.resume(
                                    ScreenshotCapture(
                                        success = true,
                                        jpegBase64 = base64,
                                        width = encodedWidth,
                                        height = encodedHeight,
                                        message = "Screenshot captured.",
                                    ),
                                )
                            }
                        } catch (error: Exception) {
                            if (continuation.isActive) {
                                continuation.resume(
                                    ScreenshotCapture(
                                        false,
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
                                    false,
                                    message = "Screenshot blocked or unavailable (code $errorCode).",
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
        quietPeriodMs: Long = 100L,
        maxWaitMs: Long = 500L,
    ) {
        val startedAt = SystemClock.uptimeMillis()
        while (SystemClock.uptimeMillis() - startedAt < maxWaitMs) {
            val quietFor = SystemClock.uptimeMillis() - lastWindowChangeAt
            if (quietFor >= quietPeriodMs) return
            delay(30L)
        }
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
                node.getChild(i)?.let { queue.add(it) }
            }
        }
        return null
    }

    suspend fun clickNodeWithFallback(node: AccessibilityNodeInfo, label: String = "element"): AccessibilityActionResult {
        if (node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return success("Clicked $label via ACTION_CLICK.")
        }
        var parent = node.parent
        repeat(MAX_PARENT_SEARCH) {
            if (parent == null) return@repeat
            val curr = parent ?: return@repeat
            if (curr.isClickable && curr.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
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

    suspend fun clickByText(text: String, exact: Boolean = false): AccessibilityActionResult {
        val root = getActiveRootNode() ?: return failure("No active window.")
        val target = text.trim()
        val match = findNode(root) { node ->
            val nodeText = node.text?.toString()?.trim().orEmpty()
            if (exact) nodeText.equals(target, ignoreCase = true)
            else nodeText.contains(target, ignoreCase = true)
        } ?: return failure("Element with text '$text' not found.")
        return clickNodeWithFallback(match, "text '$text'")
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
        val root = getActiveRootNode() ?: return failure("No active window.")
        val target = desc.trim()
        val match = findNode(root) { node ->
            val cd = node.contentDescription?.toString()?.trim().orEmpty()
            if (exact) cd.equals(target, ignoreCase = true)
            else cd.contains(target, ignoreCase = true)
        } ?: return failure("Element with content description '$desc' not found.")
        return clickNodeWithFallback(match, "content description '$desc'")
    }

    suspend fun tapAt(x: Float, y: Float): AccessibilityActionResult = tapCoordinates(x, y)

    fun typeText(index: Int, text: String): AccessibilityActionResult = setNodeText(index, text)

    fun pressBack(): AccessibilityActionResult = performGlobal("back")

    fun pressHome(): AccessibilityActionResult = performGlobal("home")

    suspend fun scrollToFind(targetText: String, maxScrolls: Int = 5): AccessibilityActionResult {
        val target = targetText.trim()
        repeat(maxScrolls) {
            val root = getActiveRootNode()
            if (root != null) {
                val match = findNode(root) {
                    it.text?.toString()?.contains(target, ignoreCase = true) == true ||
                    it.contentDescription?.toString()?.contains(target, ignoreCase = true) == true
                }
                if (match != null) {
                    return clickNodeWithFallback(match, "scrolled-to element '$targetText'")
                }
            }
            scrollNode(null, "down")
            delay(350L)
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
            dialogKeywords.any { kw -> text == kw || desc == kw || text.contains(kw) || desc.contains(kw) }
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
            "photo",
            "camera",
            "snap",
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

        val metrics = resources.displayMetrics
        val centerX = metrics.widthPixels / 2f
        val shutterY = metrics.heightPixels * 0.86f
        val tapRes = tapCoordinates(centerX, shutterY)
        Log.i(TAG, "Camera shutter fallback tap at ($centerX, $shutterY): ${tapRes.success}")
        return tapRes.success
    }

    suspend fun triggerDialerCall(): Boolean {
        val callKeywords = listOf("call", "dial", "voice call", "sim 1", "sim 2", "make call", "phone")
        val root = getActiveRootNode()
        if (root != null) {
            val callBtn = findNode(root) { node ->
                val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
                val text = node.text?.toString()?.lowercase().orEmpty()
                val id = node.viewIdResourceName?.lowercase().orEmpty()
                if (id.contains("search") || desc.contains("search") || text.contains("search")) return@findNode false
                if (id.contains("delete") || desc.contains("delete") || text.contains("backspace")) return@findNode false
                callKeywords.any { desc.contains(it) || text.contains(it) || id.contains(it) }
            }
            if (callBtn != null) {
                val res = clickNodeWithFallback(callBtn, "dialer call button")
                if (res.success) {
                    Log.i(TAG, "Dialer call button clicked via node: ${res.message}")
                    return true
                }
            }
        }

        val metrics = resources.displayMetrics
        val centerX = metrics.widthPixels / 2f
        val callY = metrics.heightPixels * 0.82f
        val tapRes = tapCoordinates(centerX, callY)
        Log.i(TAG, "Dialer call fallback tap at ($centerX, $callY): ${tapRes.success}")
        return tapRes.success
    }

    private fun safeText(node: AccessibilityNodeInfo): String {
        if (node.isPassword) return "[PROTECTED]"
        return node.text?.toString()?.trim().orEmpty()
    }

    @Synchronized
    private fun clearIndexedNodes() {
        for (index in 0 until indexedNodes.size()) {
            indexedNodes.valueAt(index)?.recycle()
        }
        indexedNodes.clear()
    }

    private fun success(message: String) = AccessibilityActionResult(true, message)

    private fun failure(message: String) = AccessibilityActionResult(false, message)

    companion object {
        private const val TAG = "AgentAccessibility"
        private const val DEFAULT_MAX_NODES = 48
        private const val MAX_FIELD_LENGTH = 80
        private const val MAX_PARENT_SEARCH = 6
        private const val MAX_SCREENSHOT_LONG_EDGE = 1280
        private const val TAP_DURATION_MS = 80L

        private val SECURE_APP_PACKAGES = setOf(
            "net.one97.paytm",
            "com.google.android.apps.nbu.paisa.user",
            "com.phonepe.app",
            "org.npci.upi.security.pinverification",
            "com.cred.android",
        )

        @Volatile
        private var instance: AgentAccessibilityService? = null

        fun current(): AgentAccessibilityService? = instance

        fun isConnected(): Boolean = instance != null
    }
}
