package com.personal.harmaai.accessibility

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import java.util.ArrayDeque
import kotlin.math.hypot

/**
 * Stateless live-node resolver that re-resolves a snapshot `ElementFingerprint` against
 * the current live accessibility tree right before an action is executed.
 *
 * This eliminates stale-node bugs where RecyclerViews, LazyColumns, or animations recycle
 * or shift views during the 1.5–4s LLM network call.
 */
object ElementResolver {

    data class ResolvedMatch(
        val node: AccessibilityNodeInfo,
        val score: Int,
        val bounds: Rect,
    )

    fun resolveByFingerprint(
        windows: List<AccessibilityWindowInfo>,
        fallbackRoot: AccessibilityNodeInfo?,
        fingerprint: ElementFingerprint,
    ): ResolvedMatch? {
        val roots = collectRoots(windows, fallbackRoot)
        var bestMatch: ResolvedMatch? = null

        for ((winId, root) in roots) {
            val queue = ArrayDeque<AccessibilityNodeInfo>()
            queue.add(root)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                if (!node.isVisibleToUser) continue
                for (i in 0 until node.childCount) {
                    try {
                        node.getChild(i)?.let(queue::addLast)
                    } catch (_: Exception) {}
                }

                val bounds = Rect().also(node::getBoundsInScreen)
                if (bounds.width() <= 2 || bounds.height() <= 2) continue

                val score = scoreNodeAgainstFingerprint(node, winId, bounds, fingerprint)
                if (score >= MIN_FINGERPRINT_SCORE && (bestMatch == null || score > bestMatch.score)) {
                    bestMatch = ResolvedMatch(node, score, bounds)
                }
            }
        }
        return bestMatch
    }

    fun scoreNodeAgainstFingerprint(
        node: AccessibilityNodeInfo,
        windowId: Int,
        bounds: Rect,
        fp: ElementFingerprint,
    ): Int {
        var score = 0
        if (fp.windowId != -1 && windowId == fp.windowId) {
            score += 15
        }

        val shortId = node.viewIdResourceName.orEmpty().substringAfterLast(":id/").take(36)
        if (fp.viewId.isNotBlank() && shortId == fp.viewId) {
            score += 35
        } else if (fp.viewId.isNotBlank() && shortId.isNotBlank() && shortId != fp.viewId) {
            score -= 20
        }

        val shortClass = node.className?.toString().orEmpty().substringAfterLast('.').take(32)
        if (fp.className.isNotBlank() && shortClass == fp.className) {
            score += 15
        }

        val nodeText = node.text?.toString()?.trim().orEmpty()
        val nodeDesc = node.contentDescription?.toString()?.trim().orEmpty()
        val nodeHint = node.hintText?.toString()?.trim().orEmpty()

        if (fp.text.isNotBlank()) {
            when {
                nodeText.equals(fp.text, ignoreCase = true) -> score += 50
                nodeText.isNotBlank() && (fp.text.contains(nodeText, ignoreCase = true) || nodeText.contains(fp.text, ignoreCase = true)) -> score += 30
                nodeText.isBlank() && node.isClickable -> {
                    val merged = collectChildTextSnippet(node)
                    if (merged.equals(fp.text, ignoreCase = true)) score += 48
                    else if (merged.contains(fp.text, ignoreCase = true) || fp.text.contains(merged, ignoreCase = true)) score += 28
                }
                else -> score -= 25
            }
        }

        if (fp.contentDescription.isNotBlank()) {
            if (nodeDesc.equals(fp.contentDescription, ignoreCase = true)) score += 45
            else if (nodeDesc.contains(fp.contentDescription, ignoreCase = true)) score += 25
        }

        if (fp.hintText.isNotBlank() && nodeHint.equals(fp.hintText, ignoreCase = true)) {
            score += 25
        }

        val isEditable = node.isEditable || shortClass.contains("EditText", ignoreCase = true)
        if (fp.editable == isEditable) {
            score += if (fp.editable) 25 else 5
        } else {
            score -= 35
        }

        if (fp.clickable && node.isClickable) score += 15
        if (fp.scrollable && node.isScrollable) score += 15

        val dist = hypot(
            (bounds.centerX() - fp.centerX).toDouble(),
            (bounds.centerY() - fp.centerY).toDouble(),
        )
        when {
            dist <= 24.0 -> score += 30
            dist <= 90.0 -> score += 20
            dist <= 220.0 -> score += 8
            dist > 550.0 -> score -= 15
        }

        return score
    }

    /**
     * Disambiguated search for text/description/id queries:
     * - Prefers clickable/actionable elements over static headers.
     * - Optionally excludes editable EditText nodes (so searching for "Mom" after typing "Mom" in a search bar
     *   clicks the contact result row rather than re-tapping the search input box).
     */
    fun findBestNodeByTextOrDesc(
        windows: List<AccessibilityWindowInfo>,
        fallbackRoot: AccessibilityNodeInfo?,
        target: String,
        exact: Boolean = false,
        matchDescription: Boolean = false,
        excludeEditable: Boolean = false,
    ): ResolvedMatch? {
        val clean = target.trim()
        if (clean.isBlank()) return null
        val roots = collectRoots(windows, fallbackRoot)
        var best: ResolvedMatch? = null

        for ((_, root) in roots) {
            val queue = ArrayDeque<AccessibilityNodeInfo>()
            queue.add(root)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                if (!node.isVisibleToUser) continue
                for (i in 0 until node.childCount) {
                    try {
                        node.getChild(i)?.let(queue::addLast)
                    } catch (_: Exception) {}
                }

                val shortClass = node.className?.toString().orEmpty().substringAfterLast('.')
                val isEditable = node.isEditable || shortClass.contains("EditText", ignoreCase = true)
                if (excludeEditable && isEditable) continue

                val bounds = Rect().also(node::getBoundsInScreen)
                if (bounds.width() <= 2 || bounds.height() <= 2) continue

                val candidateText = if (matchDescription) {
                    node.contentDescription?.toString()?.trim().orEmpty()
                } else {
                    node.text?.toString()?.trim().orEmpty().ifBlank {
                        if (node.isClickable) collectChildTextSnippet(node) else ""
                    }
                }
                if (candidateText.isBlank()) continue

                val exactMatch = candidateText.equals(clean, ignoreCase = true)
                val partialMatch = !exact && candidateText.contains(clean, ignoreCase = true)
                if (!exactMatch && !partialMatch) continue

                var score = if (exactMatch) 60 else 35
                if (node.isClickable) score += 25
                else if (hasClickableAncestorWithin(node, 3)) score += 12
                if (!isEditable) score += 10
                if (node.isEnabled) score += 5

                if (best == null || score > best.score) {
                    best = ResolvedMatch(node, score, bounds)
                }
            }
        }
        return best
    }

    private fun hasClickableAncestorWithin(node: AccessibilityNodeInfo, maxDepth: Int): Boolean {
        var parent = node.parent
        var depth = 0
        while (parent != null && depth < maxDepth) {
            if (parent.isClickable) return true
            parent = parent.parent
            depth++
        }
        return false
    }

    private fun collectChildTextSnippet(node: AccessibilityNodeInfo, depth: Int = 0): String {
        if (depth > 2) return ""
        val parts = mutableListOf<String>()
        for (i in 0 until node.childCount) {
            val child = try {
                node.getChild(i)
            } catch (_: Exception) {
                null
            } ?: continue
            if (!child.isVisibleToUser) continue
            val t = child.text?.toString()?.trim().orEmpty()
            val d = child.contentDescription?.toString()?.trim().orEmpty()
            if (t.isNotBlank()) parts += t
            else if (d.isNotBlank()) parts += d
            val sub = collectChildTextSnippet(child, depth + 1)
            if (sub.isNotBlank()) parts += sub
        }
        return parts.distinct().joinToString(" • ")
    }

    private fun collectRoots(
        windows: List<AccessibilityWindowInfo>,
        fallbackRoot: AccessibilityNodeInfo?,
    ): List<Pair<Int, AccessibilityNodeInfo>> {
        val list = mutableListOf<Pair<Int, AccessibilityNodeInfo>>()
        for (w in windows.sortedByDescending { it.layer }) {
            if (w.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD) continue
            val root = try {
                w.root
            } catch (_: Exception) {
                null
            } ?: continue
            if (w.type == AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY &&
                root.packageName?.toString() == "com.personal.harmaai"
            ) {
                continue
            }
            list += w.id to root
        }
        if (list.isEmpty() && fallbackRoot != null) {
            list += fallbackRoot.windowId to fallbackRoot
        }
        return list
    }

    private const val MIN_FINGERPRINT_SCORE = 35
}
