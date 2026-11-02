package com.personal.harmaai.ui.theme

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// Futuristic clean dark palette as requested
val HarmaBlack = Color(0xFF0B0F1A)
val HarmaSurface = Color(0xFF121A2B)
val HarmaCard = Color(0xFF182238)
val HarmaBorder = Color(0xFF26334D)

// Primary gradient: #6C5CE7 -> #00D2FF
val HarmaPrimary = Color(0xFF6C5CE7)
val HarmaPrimaryCyan = Color(0xFF00D2FF)
val HarmaPrimaryGradient = Brush.horizontalGradient(
    colors = listOf(HarmaPrimary, HarmaPrimaryCyan)
)
val HarmaPrimaryGradientVertical = Brush.verticalGradient(
    colors = listOf(HarmaPrimary, HarmaPrimaryCyan)
)

// Accent / Status colors
val HarmaGreen = Color(0xFF00E676)
val HarmaAmber = Color(0xFFFFB300)
val HarmaRed = Color(0xFFFF5252)

// Typography colors
val HarmaText = Color(0xFFE8ECF8)
val HarmaMuted = Color(0xFF8F9BB8)

private val HarmaColors = darkColorScheme(
    primary = HarmaPrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF2D2460),
    onPrimaryContainer = Color(0xFFDCD5FF),
    secondary = HarmaPrimaryCyan,
    onSecondary = Color(0xFF002933),
    secondaryContainer = Color(0xFF004D5F),
    onSecondaryContainer = Color(0xFFB5F2FF),
    tertiary = HarmaGreen,
    onTertiary = Color(0xFF00220F),
    background = HarmaBlack,
    onBackground = HarmaText,
    surface = HarmaSurface,
    onSurface = HarmaText,
    surfaceVariant = HarmaCard,
    onSurfaceVariant = HarmaMuted,
    outline = HarmaBorder,
    error = HarmaRed,
)

@Composable
fun HarmaTheme(content: @Composable () -> Unit) {
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = HarmaBlack.toArgb()
            window.navigationBarColor = HarmaBlack.toArgb()
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = false
                isAppearanceLightNavigationBars = false
            }
        }
    }
    MaterialTheme(colorScheme = HarmaColors, content = content)
}
