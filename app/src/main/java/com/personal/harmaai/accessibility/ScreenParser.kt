package com.personal.harmaai.accessibility

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * Multi-window, stateless screen perception engine.
 *
 * Key guarantees:
 * 1. Traverses ALL relevant interactive windows (dialogs/popups, active application, system panels,
 *    and detects IME soft keyboard visibility).
 * 2. Merges non-actionable child text/contentDescription labels into their clickable parent
 *    container so composite rows/cards/buttons are represented as a single clearly-labeled node.
 * 3. Drops invisible, zero-size, off-screen, and purely decorative wrapper nodes.
 * 4. Produces both structured JSON (`compactJson`) and token-efficient Set-of-Marks lines (`compactText`)
 *    like: `[12] EditText "Search" editable bounds=(40,120,980,240)`.
 * 5. Never retains live `AccessibilityNodeInfo` objects across steps.
 */
object ScreenParser {
    private const val DEFAULT_MAX_NODES = 85
    private const val MAX_FIELD_LENGTH = 100
    private const val MAX_CHILD_MERGE_DEPTH = 3

    private val SECURE_APP_PACKAGES = setOf(
        "net.one97.paytm",
        "com.google.android.apps.nbu.paisa.user",
        "com.phonepe.app",
        "org.npci.upi.security.pinverification",
        "com.cred.android",
    )

    fun parse(
        windows: List<AccessibilityWindowInfo>,
        fallbackRoot: AccessibilityNodeInfo?,
        lastPackageName: String,
        lastActivityName: String,
        screenWidth: Int,
        screenHeight: Int,
        maxNodes: Int = DEFAULT_MAX_NODES,
    ): ScreenObservation {
        var keyboardVisible = false
        val rootEntries = mutableListOf<WindowRootEntry>()

        for (window in windows.sortedByDescending { it.layer }) {
            val type = window.type
            if (type == AccessibilityWindowInfo.TYPE_INPUT_METHOD) {
                val imeBounds = Rect()
                window.getBoundsInScreen(imeBounds)
                if (imeBounds.height() > screenHeight / 8) {
                    keyboardVisible = true
                }
                // Still allow reading key action labels if needed, or skip full key grid to save tokens
                continue
            }
            val root = try {
                window.root
            } catch (_: Exception) {
                null
            } ?: continue

            val windowTypeLabel = when (type) {
                AccessibilityWindowInfo.TYPE_APPLICATION -> if (window.isActive || window.isFocused) "APP" else "APP_BG"
                AccessibilityWindowInfo.TYPE_SYSTEM -> "SYSTEM"
                AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY -> "OVERLAY"
                else -> "DIALOG"
            }
            // Skip our own floating stop overlay window
            val pkg = root.packageName?.toString().orEmpty()
            if (windowTypeLabel == "OVERLAY" && pkg == "com.personal.harmaai") {
                continue
            }
            rootEntries += WindowRootEntry(
                root = root,
                windowId = window.id,
                windowType = windowTypeLabel,
                windowTitle = window.title?.toString()?.trim().orEmpty(),
                isActive = window.isActive || window.isFocused,
            )
        }

        if (rootEntries.isEmpty() && fallbackRoot != null) {
            rootEntries += WindowRootEntry(
                root = fallbackRoot,
                windowId = fallbackRoot.windowId,
                windowType = "APP",
                windowTitle = "",
                isActive = true,
            )
        }

        if (rootEntries.isEmpty()) {
            val isKnownSecureApp = isSecurePackage(lastPackageName)
            val reason = if (isKnownSecureApp) {
                "Screen content is protected by system security (FLAG_SECURE, such as payment or UPI PIN screen). Harma AI will not read or enter sensitive credentials."
            } else {
                "No active accessibility window. The screen may be locked, transition in progress, or protected."
            }
            val unavailableJson = JSONObject()
                .put("package", lastPackageName)
                .put("activity", lastActivityName)
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
                activityName = lastActivityName,
                keyboardVisible = keyboardVisible,
                compactText = "SCREEN_UNAVAILABLE ($lastPackageName): $reason",
            )
        }

        val primaryEntry = rootEntries.firstOrNull { it.isActive && it.windowType == "APP" }
            ?: rootEntries.first()
        val observedPackage = primaryEntry.root.packageName?.toString().orEmpty().ifBlank { lastPackageName }
        val primaryTitle = rootEntries.firstOrNull { it.windowTitle.isNotBlank() }?.windowTitle.orEmpty()

        val snapshots = ArrayList<UiNodeSnapshot>(maxNodes)
        val scrollHints = mutableListOf<String>()
        val seenSignatures = HashSet<String>()
        var protectedContent = isSecurePackage(observedPackage)

        for (entry in rootEntries) {
            if (snapshots.size >= maxNodes) break
            traverseNode(
                node = entry.root,
                parentContext = "",
                windowId = entry.windowId,
                windowType = entry.windowType,
                screenWidth = screenWidth,
                screenHeight = screenHeight,
                maxNodes = maxNodes,
                snapshots = snapshots,
                scrollHints = scrollHints,
                seenSignatures = seenSignatures,
                onPasswordDetected = { protectedContent = true },
            )
        }

        val compactLines = formatCompactLines(
            packageName = observedPackage,
            activityName = lastActivityName,
            windowTitle = primaryTitle,
            keyboardVisible = keyboardVisible,
            protectedContent = protectedContent,
            scrollHints = scrollHints,
            nodes = snapshots,
        )

        val nodeArray = JSONArray()
        snapshots.forEach { node ->
            nodeArray.put(
                JSONObject()
                    .put("i", node.index)
                    .putOpt("t", node.text.ifBlank { null })
                    .putOpt("d", node.contentDescription.ifBlank { null })
                    .putOpt("h", node.hintText.ifBlank { null })
                    .putOpt("id", node.viewId.ifBlank { null })
                    .putOpt("cls", node.className.ifBlank { null })
                    .put("b", node.bounds)
                    .putOpt("click", if (node.clickable) true else null)
                    .putOpt("longClick", if (node.longClickable) true else null)
                    .putOpt("edit", if (node.editable) true else null)
                    .putOpt("scroll", if (node.scrollable) true else null)
                    .putOpt("check", if (node.checkable) node.checked else null)
                    .putOpt("focus", if (node.focused) true else null)
                    .putOpt("win", if (node.windowType != "APP") node.windowType else null)
                    .putOpt("password", if (node.password) true else null),
            )
        }

        val compactJson = JSONObject()
            .put("package", observedPackage)
            .putOpt("activity", lastActivityName.ifBlank { null })
            .putOpt("title", primaryTitle.ifBlank { null })
            .put("keyboard_open", keyboardVisible)
            .put("protected", protectedContent)
            .putOpt("scroll_hints", if (scrollHints.isNotEmpty()) JSONArray(scrollHints) else null)
            .put("nodes", nodeArray)
            .put("compact_view", compactLines)
            .toString()

        return ScreenObservation(
            packageName = observedPackage,
            windowTitle = primaryTitle,
            nodes = snapshots,
            compactJson = compactJson,
            protectedContent = protectedContent,
            unavailable = false,
            capturedAtMillis = System.currentTimeMillis(),
            activityName = lastActivityName,
            keyboardVisible = keyboardVisible,
            scrollHints = scrollHints,
            compactText = compactLines,
        )
    }

    private fun traverseNode(
        node: AccessibilityNodeInfo,
        parentContext: String,
        windowId: Int,
        windowType: String,
        screenWidth: Int,
        screenHeight: Int,
        maxNodes: Int,
        snapshots: MutableList<UiNodeSnapshot>,
        scrollHints: MutableList<String>,
        seenSignatures: MutableSet<String>,
        onPasswordDetected: () -> Unit,
    ) {
        if (snapshots.size >= maxNodes) return
        if (!node.isVisibleToUser) return

        val bounds = Rect().also(node::getBoundsInScreen)
        val validBounds = bounds.width() > 2 && bounds.height() > 2 &&
            bounds.right > 0 && bounds.bottom > 0 &&
            bounds.left < screenWidth && bounds.top < screenHeight

        val rawClass = node.className?.toString().orEmpty()
        val shortClass = rawClass.substringAfterLast('.').take(32)
        val rawId = node.viewIdResourceName.orEmpty()
        val shortId = rawId.substringAfterLast(":id/").take(36)
        val password = node.isPassword
        if (password) onPasswordDetected()

        val directText = if (password) "[PROTECTED]" else node.text?.toString()?.trim().orEmpty().take(MAX_FIELD_LENGTH)
        val directDesc = node.contentDescription?.toString()?.trim().orEmpty().take(MAX_FIELD_LENGTH)
        val hintText = node.hintText?.toString()?.trim().orEmpty().take(MAX_FIELD_LENGTH)

        val editable = node.isEditable || shortClass.contains("EditText", ignoreCase = true)
        val clickable = node.isClickable
        val longClickable = node.isLongClickable
        val scrollable = node.isScrollable
        val checkable = node.isCheckable
        val actionable = clickable || longClickable || editable || scrollable || checkable

        if (scrollable && validBounds && scrollHints.size < 4) {
            val label = shortId.ifBlank { shortClass.ifBlank { "container" } }
            scrollHints += "Scrollable $label at (${bounds.left},${bounds.top}-${bounds.right},${bounds.bottom})"
        }

        // Merge text-only children into a clickable/checkable container if the container itself has no text
        val mergedChildText = if ((clickable || checkable) && !editable && directText.isBlank() && directDesc.isBlank()) {
            collectNonActionableChildText(node, depth = 0).take(MAX_FIELD_LENGTH)
        } else {
            ""
        }
        val effectiveText = directText.ifBlank { mergedChildText }

        val shouldEmit = validBounds && (
            actionable ||
                effectiveText.isNotBlank() ||
                directDesc.isNotBlank() ||
                hintText.isNotBlank()
            ) && !(
            // Drop purely decorative containers that have no label and are only scrollable layout wrappers when they have children
            !clickable && !editable && !checkable && effectiveText.isBlank() && directDesc.isBlank() && hintText.isBlank() && node.childCount > 0 && !scrollable
            )

        var nextParentContext = parentContext
        if (shouldEmit) {
            val boundsStr = "${bounds.left},${bounds.top},${bounds.right},${bounds.bottom}"
            val sig = "$windowType|$shortId|$effectiveText|$directDesc|$boundsStr|$clickable|$editable"
            if (seenSignatures.add(sig)) {
                val index = snapshots.size
                snapshots += UiNodeSnapshot(
                    index = index,
                    className = shortClass,
                    text = effectiveText,
                    contentDescription = directDesc,
                    viewId = shortId,
                    bounds = boundsStr,
                    clickable = clickable,
                    editable = editable,
                    scrollable = scrollable,
                    focused = node.isFocused || node.isAccessibilityFocused,
                    checked = node.isChecked,
                    password = password,
                    hintText = hintText,
                    longClickable = longClickable,
                    checkable = checkable,
                    enabled = node.isEnabled,
                    windowId = windowId,
                    windowType = windowType,
                    parentContext = parentContext,
                )
                if (effectiveText.isNotBlank() || shortId.isNotBlank()) {
                    nextParentContext = effectiveText.ifBlank { shortId }.take(28)
                }
            }
        }

        // If we merged all non-actionable child labels into a clickable leaf row and none of its direct children are independently actionable,
        // skip emitting redundant duplicate text children while still recursing into any independently clickable/editable child controls (e.g. a switch or icon button inside a row).
        val skipNonActionableChildren = mergedChildText.isNotBlank() && clickable

        for (i in 0 until node.childCount) {
            if (snapshots.size >= maxNodes) break
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue

            if (skipNonActionableChildren && !hasIndependentlyActionableSubtree(child, 0)) {
                continue
            }

            traverseNode(
                node = child,
                parentContext = nextParentContext,
                windowId = windowId,
                windowType = windowType,
                screenWidth = screenWidth,
                screenHeight = screenHeight,
                maxNodes = maxNodes,
                snapshots = snapshots,
                scrollHints = scrollHints,
                seenSignatures = seenSignatures,
                onPasswordDetected = onPasswordDetected,
            )
        }
    }

    private fun collectNonActionableChildText(node: AccessibilityNodeInfo, depth: Int): String {
        if (depth > MAX_CHILD_MERGE_DEPTH) return ""
        val parts = mutableListOf<String>()
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            if (!child.isVisibleToUser) continue
            if (child.isClickable || child.isEditable || child.isCheckable) continue
            val t = child.text?.toString()?.trim().orEmpty()
            val d = child.contentDescription?.toString()?.trim().orEmpty()
            if (t.isNotBlank()) parts += t
            else if (d.isNotBlank()) parts += d
            val nested = collectNonActionableChildText(child, depth + 1)
            if (nested.isNotBlank()) parts += nested
        }
        return parts.distinct().joinToString(" • ")
    }

    private fun hasIndependentlyActionableSubtree(node: AccessibilityNodeInfo, depth: Int): Boolean {
        if (depth > MAX_CHILD_MERGE_DEPTH) return false
        if (node.isClickable || node.isEditable || node.isCheckable || node.isScrollable) return true
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            if (hasIndependentlyActionableSubtree(child, depth + 1)) return true
        }
        return false
    }

    fun formatCompactLines(
        packageName: String,
        activityName: String,
        windowTitle: String,
        keyboardVisible: Boolean,
        protectedContent: Boolean,
        scrollHints: List<String>,
        nodes: List<UiNodeSnapshot>,
    ): String = buildString {
        append("PACKAGE: ").append(packageName.ifBlank { "unknown" })
        if (activityName.isNotBlank()) append(" | ACTIVITY: ").append(activityName)
        if (windowTitle.isNotBlank()) append(" | TITLE: \"").append(windowTitle).append('"')
        append(" | KEYBOARD: ").append(if (keyboardVisible) "OPEN" else "CLOSED")
        if (protectedContent) append(" | PROTECTED_SCREEN: TRUE")
        if (scrollHints.isNotEmpty()) {
            append("\nSCROLL_HINTS: ").append(scrollHints.joinToString("; "))
        }
        append("\nELEMENTS (").append(nodes.size).append("):")
        for (n in nodes) {
            append("\n[").append(n.index).append("] ")
            if (n.windowType != "APP") append('{').append(n.windowType).append("} ")
            append(n.className.ifBlank { "View" })
            if (n.text.isNotBlank()) append(" \"").append(n.text.replace('\n', ' ')).append('"')
            if (n.contentDescription.isNotBlank() && n.contentDescription != n.text) {
                append(" desc=\"").append(n.contentDescription.replace('\n', ' ')).append('"')
            }
            if (n.hintText.isNotBlank() && n.hintText != n.text) {
                append(" hint=\"").append(n.hintText.replace('\n', ' ')).append('"')
            }
            if (n.viewId.isNotBlank()) append(" id=").append(n.viewId)
            val flags = buildList {
                if (n.clickable) add("clickable")
                if (n.longClickable) add("longClickable")
                if (n.editable) add("editable")
                if (n.scrollable) add("scrollable")
                if (n.checkable) add(if (n.checked) "checked" else "unchecked")
                if (n.focused) add("focused")
                if (!n.enabled) add("disabled")
            }
            if (flags.isNotEmpty()) append(' ').append(flags.joinToString(","))
            append(" bounds=(").append(n.bounds).append(')')
        }
    }

    fun isSecurePackage(pkg: String): Boolean {
        val lower = pkg.lowercase()
        return lower in SECURE_APP_PACKAGES ||
            lower.contains("paytm") ||
            lower.contains("paisa") ||
            lower.contains("upi") ||
            lower.contains("phonepe")
    }

    private data class WindowRootEntry(
        val root: AccessibilityNodeInfo,
        val windowId: Int,
        val windowType: String,
        val windowTitle: String,
        val isActive: Boolean,
    )
}
