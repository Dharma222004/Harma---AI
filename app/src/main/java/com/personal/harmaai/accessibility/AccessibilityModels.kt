package com.personal.harmaai.accessibility

import org.json.JSONObject

data class ElementFingerprint(
    val index: Int,
    val viewId: String,
    val className: String,
    val text: String,
    val contentDescription: String,
    val hintText: String = "",
    val bounds: String,
    val centerX: Int,
    val centerY: Int,
    val windowId: Int = -1,
    val windowType: String = "APP",
    val parentContext: String = "",
    val clickable: Boolean = false,
    val longClickable: Boolean = false,
    val editable: Boolean = false,
    val scrollable: Boolean = false,
    val checkable: Boolean = false,
) {
    val stableHash: String
        get() = "$windowType|$viewId|$className|${text.take(40)}|${contentDescription.take(40)}|$hintText|$bounds"

    fun toJson(): JSONObject = JSONObject()
        .put("index", index)
        .put("viewId", viewId)
        .put("className", className)
        .put("text", text)
        .put("contentDescription", contentDescription)
        .put("hintText", hintText)
        .put("bounds", bounds)
        .put("centerX", centerX)
        .put("centerY", centerY)
        .put("windowId", windowId)
        .put("windowType", windowType)
        .put("parentContext", parentContext)
        .put("clickable", clickable)
        .put("longClickable", longClickable)
        .put("editable", editable)
        .put("scrollable", scrollable)
        .put("checkable", checkable)

    companion object {
        fun fromJson(json: JSONObject?): ElementFingerprint? {
            if (json == null) return null
            val bounds = json.optString("bounds")
            val viewId = json.optString("viewId")
            val text = json.optString("text")
            val desc = json.optString("contentDescription")
            val className = json.optString("className")
            if (bounds.isBlank() && viewId.isBlank() && text.isBlank() && desc.isBlank() && className.isBlank()) {
                return null
            }
            return ElementFingerprint(
                index = json.optInt("index", -1),
                viewId = viewId,
                className = className,
                text = text,
                contentDescription = desc,
                hintText = json.optString("hintText"),
                bounds = bounds,
                centerX = json.optInt("centerX", 0),
                centerY = json.optInt("centerY", 0),
                windowId = json.optInt("windowId", -1),
                windowType = json.optString("windowType", "APP"),
                parentContext = json.optString("parentContext"),
                clickable = json.optBoolean("clickable", false),
                longClickable = json.optBoolean("longClickable", false),
                editable = json.optBoolean("editable", false),
                scrollable = json.optBoolean("scrollable", false),
                checkable = json.optBoolean("checkable", false),
            )
        }
    }
}

data class UiNodeSnapshot(
    val index: Int,
    val className: String,
    val text: String,
    val contentDescription: String,
    val viewId: String,
    val bounds: String,
    val clickable: Boolean,
    val editable: Boolean,
    val scrollable: Boolean,
    val focused: Boolean,
    val checked: Boolean,
    val password: Boolean,
    val hintText: String = "",
    val longClickable: Boolean = false,
    val checkable: Boolean = false,
    val enabled: Boolean = true,
    val windowId: Int = -1,
    val windowType: String = "APP",
    val parentContext: String = "",
) {
    fun toFingerprint(): ElementFingerprint {
        val parts = bounds.split(',').mapNotNull { it.trim().toIntOrNull() }
        val cx = if (parts.size == 4) (parts[0] + parts[2]) / 2 else 0
        val cy = if (parts.size == 4) (parts[1] + parts[3]) / 2 else 0
        return ElementFingerprint(
            index = index,
            viewId = viewId,
            className = className,
            text = text,
            contentDescription = contentDescription,
            hintText = hintText,
            bounds = bounds,
            centerX = cx,
            centerY = cy,
            windowId = windowId,
            windowType = windowType,
            parentContext = parentContext,
            clickable = clickable,
            longClickable = longClickable,
            editable = editable,
            scrollable = scrollable,
            checkable = checkable,
        )
    }
}

data class ScreenObservation(
    val packageName: String,
    val windowTitle: String,
    val nodes: List<UiNodeSnapshot>,
    val compactJson: String,
    val protectedContent: Boolean,
    val unavailable: Boolean,
    val capturedAtMillis: Long,
    val activityName: String = "",
    val keyboardVisible: Boolean = false,
    val scrollHints: List<String> = emptyList(),
    val compactText: String = "",
) {
    val usableNodeCount: Int get() = nodes.size

    fun nodeAt(index: Int): UiNodeSnapshot? = nodes.firstOrNull { it.index == index }

    fun fingerprintAt(index: Int): ElementFingerprint? = nodeAt(index)?.toFingerprint()
}

data class AccessibilityActionResult(
    val success: Boolean,
    val message: String,
)

data class ScreenshotCapture(
    val success: Boolean,
    val jpegBase64: String = "",
    val width: Int = 0,
    val height: Int = 0,
    val message: String,
    val flaggedSecure: Boolean = false,
    val blankCapture: Boolean = false,
)
