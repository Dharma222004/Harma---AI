package com.personal.harmaai.accessibility

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
)

data class ScreenObservation(
    val packageName: String,
    val windowTitle: String,
    val nodes: List<UiNodeSnapshot>,
    val compactJson: String,
    val protectedContent: Boolean,
    val unavailable: Boolean,
    val capturedAtMillis: Long,
) {
    val usableNodeCount: Int get() = nodes.size
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
)
