package ai.harma.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = HarmaTextPrimary,
    onPrimary = HarmaBlack,
    surface = HarmaSurface,
    onSurface = HarmaTextPrimary,
    background = HarmaBlack,
    onBackground = HarmaTextPrimary
)

@Composable
fun HarmaTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography,
        content = content
    )
}
