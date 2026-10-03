package ai.harma.app.device

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.lang.ref.WeakReference

/**
 * Harma Accessibility Service
 * Provides native UI observation, semantic node inspection, and interaction
 * without relying on brittle fixed coordinates.
 */
class HarmaAccessibilityService : AccessibilityService() {

    companion object {
        private var instanceRef: WeakReference<HarmaAccessibilityService>? = null

        val instance: HarmaAccessibilityService?
            get() = instanceRef?.get()

        val isRunning: Boolean
            get() = instanceRef?.get() != null
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instanceRef = WeakReference(this)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Event stream can be monitored if needed
    }

    override fun onInterrupt() {
        // Service interrupted by OS
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instanceRef?.get() == this) {
            instanceRef = null
        }
    }

    /**
     * Finds nodes matching text content
     */
    fun findNodesByText(text: String, exact: Boolean = false): List<AccessibilityNodeInfo> {
        val root = rootInActiveWindow ?: return emptyList()
        val found = root.findAccessibilityNodeInfosByText(text) ?: return emptyList()
        return if (exact) {
            found.filter { it.text?.toString().equals(text, ignoreCase = true) }
        } else {
            found
        }
    }

    /**
     * Finds nodes matching view ID or resource name
     */
    fun findNodesByViewId(viewId: String): List<AccessibilityNodeInfo> {
        val root = rootInActiveWindow ?: return emptyList()
        return root.findAccessibilityNodeInfosByViewId(viewId) ?: emptyList()
    }

    /**
     * Finds first clickable node matching a predicate
     */
    fun findFirstClickableMatching(predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        return dfsFind(root, predicate)
    }

    private fun dfsFind(node: AccessibilityNodeInfo, predicate: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        if (predicate(node)) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val result = dfsFind(child, predicate)
            if (result != null) return result
        }
        return null
    }

    /**
     * Recursively collect all visible text nodes in current window
     */
    fun getVisibleTexts(): List<String> {
        val root = rootInActiveWindow ?: return emptyList()
        val list = mutableListOf<String>()
        fun collect(node: AccessibilityNodeInfo) {
            val text = node.text?.toString()?.trim()
            if (!text.isNullOrBlank()) list.add(text)
            val desc = node.contentDescription?.toString()?.trim()
            if (!desc.isNullOrBlank() && desc != text) list.add(desc)
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                collect(child)
            }
        }
        collect(root)
        return list
    }

    /**
     * Clicks a target node, walking up to clickable parent if needed
     */
    fun clickNode(node: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        while (current != null) {
            if (current.isClickable) {
                return current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            }
            current = current.parent
        }
        // Fallback: force click on given node
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    /**
     * Injects text into an editable node
     */
    fun inputText(node: AccessibilityNodeInfo, text: String): Boolean {
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
    }

    fun performBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)
    fun performHome(): Boolean = performGlobalAction(GLOBAL_ACTION_HOME)
    fun performRecents(): Boolean = performGlobalAction(GLOBAL_ACTION_RECENTS)
}
