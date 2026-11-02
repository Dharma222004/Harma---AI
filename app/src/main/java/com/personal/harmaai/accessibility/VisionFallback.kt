package com.personal.harmaai.accessibility

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.Base64
import java.io.ByteArrayOutputStream
import kotlin.math.max

/**
 * Set-of-Marks (SoM) vision fallback processor for API 30+ screenshots:
 * 1. Detects blank/black screenshots (e.g. FLAG_SECURE or display off) by sampling pixel luminance.
 * 2. Overlays numbered Set-of-Marks (`[0]`, `[1]`, ...) badges and bounding boxes matching
 *    the current `ScreenObservation` nodes so the multimodal LLM selects a mark ID instead of guessing coordinates.
 */
object VisionFallback {
    private const val MAX_LONG_EDGE = 1280

    fun processAndAnnotate(
        sourceBitmap: Bitmap,
        nodes: List<UiNodeSnapshot>,
        screenWidth: Int,
        screenHeight: Int,
        quality: Int = 72,
    ): ScreenshotCapture {
        if (isBitmapBlankOrBlack(sourceBitmap)) {
            return ScreenshotCapture(
                success = false,
                width = sourceBitmap.width,
                height = sourceBitmap.height,
                message = "Screenshot appears completely blank or protected by FLAG_SECURE.",
                flaggedSecure = true,
                blankCapture = true,
            )
        }

        val longestEdge = max(sourceBitmap.width, sourceBitmap.height)
        val scale = if (longestEdge > MAX_LONG_EDGE) MAX_LONG_EDGE.toFloat() / longestEdge else 1f
        val targetW = (sourceBitmap.width * scale).toInt().coerceAtLeast(1)
        val targetH = (sourceBitmap.height * scale).toInt().coerceAtLeast(1)

        val annotated = Bitmap.createBitmap(targetW, targetH, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(annotated)
        val srcRect = android.graphics.Rect(0, 0, sourceBitmap.width, sourceBitmap.height)
        val dstRect = RectF(0f, 0f, targetW.toFloat(), targetH.toFloat())
        canvas.drawBitmap(sourceBitmap, srcRect, dstRect, null)

        val scaleX = if (screenWidth > 0) targetW.toFloat() / screenWidth.toFloat() else scale
        val scaleY = if (screenHeight > 0) targetH.toFloat() / screenHeight.toFloat() else scale

        val boxPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2.5f
            color = Color.rgb(0, 229, 255)
        }
        val badgeBgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.argb(230, 255, 23, 68)
        }
        val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 22f
            isFakeBoldText = true
        }

        for (node in nodes) {
            if (!node.clickable && !node.editable && !node.checkable && !node.scrollable) continue
            val parts = node.bounds.split(',').mapNotNull { it.trim().toIntOrNull() }
            if (parts.size != 4) continue
            val left = (parts[0] * scaleX).coerceIn(0f, targetW.toFloat())
            val top = (parts[1] * scaleY).coerceIn(0f, targetH.toFloat())
            val right = (parts[2] * scaleX).coerceIn(0f, targetW.toFloat())
            val bottom = (parts[3] * scaleY).coerceIn(0f, targetH.toFloat())
            if (right - left < 6f || bottom - top < 6f) continue

            canvas.drawRect(left, top, right, bottom, boxPaint)

            val label = "${node.index}"
            val textWidth = textPaint.measureText(label)
            val badgeW = textWidth + 12f
            val badgeH = 26f
            val badgeLeft = left.coerceIn(0f, (targetW - badgeW).coerceAtLeast(0f))
            val badgeTop = (top - badgeH).coerceAtLeast(0f)
            val badgeRect = RectF(badgeLeft, badgeTop, badgeLeft + badgeW, badgeTop + badgeH)
            canvas.drawRoundRect(badgeRect, 6f, 6f, badgeBgPaint)
            canvas.drawText(label, badgeLeft + 6f, badgeTop + badgeH - 6f, textPaint)
        }

        val output = ByteArrayOutputStream()
        annotated.compress(Bitmap.CompressFormat.JPEG, quality.coerceIn(40, 90), output)
        val base64 = Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
        annotated.recycle()

        return ScreenshotCapture(
            success = true,
            jpegBase64 = base64,
            width = targetW,
            height = targetH,
            message = "Screenshot captured with Set-of-Marks overlay.",
            flaggedSecure = false,
            blankCapture = false,
        )
    }

    fun isBitmapBlankOrBlack(bitmap: Bitmap): Boolean {
        val w = bitmap.width
        val h = bitmap.height
        if (w <= 0 || h <= 0) return true
        var nonDarkSamples = 0
        var totalSamples = 0
        val stepX = (w / 10).coerceAtLeast(1)
        val stepY = (h / 10).coerceAtLeast(1)
        var y = stepY / 2
        while (y < h) {
            var x = stepX / 2
            while (x < w) {
                totalSamples++
                val pixel = bitmap.getPixel(x, y)
                val r = Color.red(pixel)
                val g = Color.green(pixel)
                val b = Color.blue(pixel)
                if (r > 12 || g > 12 || b > 12) {
                    nonDarkSamples++
                    if (nonDarkSamples >= 3) return false
                }
                x += stepX
            }
            y += stepY
        }
        return totalSamples > 0 && nonDarkSamples < 3
    }
}
