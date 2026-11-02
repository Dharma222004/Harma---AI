package com.personal.harmaai.service

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import com.personal.harmaai.R

class FloatingStopOverlay(
    private val context: Context,
    private val onStop: () -> Unit,
) {
    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var root: View? = null
    private var statusText: TextView? = null

    fun show(initialText: String) {
        if (!Settings.canDrawOverlays(context) || root != null) return
        val density = context.resources.displayMetrics.density
        val layout = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding((12 * density).toInt(), (8 * density).toInt(), (8 * density).toInt(), (8 * density).toInt())
            setBackgroundColor(Color.argb(240, 11, 15, 26)) // Harma Dark
        }
        val logoView = ImageView(context).apply {
            setImageResource(R.drawable.harma_logo)
            layoutParams = LinearLayout.LayoutParams((28 * density).toInt(), (28 * density).toInt()).apply {
                marginEnd = (10 * density).toInt()
            }
        }
        statusText = TextView(context).apply {
            text = initialText
            setTextColor(Color.WHITE)
            textSize = 13f
            maxLines = 2
        }
        val stopButton = Button(context).apply {
            text = context.getString(R.string.stop)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(255, 82, 82))
            setOnClickListener { onStop() }
        }
        layout.addView(logoView)
        layout.addView(
            statusText,
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
        )
        layout.addView(stopButton)

        val params = WindowManager.LayoutParams(
            (320 * density).toInt(),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = (32 * density).toInt()
        }
        runCatching { windowManager.addView(layout, params) }
            .onSuccess { root = layout }
    }

    fun update(text: String) {
        statusText?.post { statusText?.text = text }
    }

    fun hide() {
        root?.let { view -> runCatching { windowManager.removeView(view) } }
        root = null
        statusText = null
    }
}
