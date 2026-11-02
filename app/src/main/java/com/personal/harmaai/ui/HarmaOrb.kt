package com.personal.harmaai.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.personal.harmaai.agent.AgentStatus
import com.personal.harmaai.ui.theme.HarmaAmber
import com.personal.harmaai.ui.theme.HarmaGreen
import com.personal.harmaai.ui.theme.HarmaPrimary
import com.personal.harmaai.ui.theme.HarmaPrimaryCyan
import com.personal.harmaai.ui.theme.HarmaRed
import kotlin.math.sin

@Composable
fun HarmaOrb(
    status: AgentStatus,
    isListening: Boolean,
    liveRmsDb: Float,
    size: Dp = 120.dp,
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "orb_pulse")

    // Idle breathing scale
    val breathingScale by infiniteTransition.animateFloat(
        initialValue = 0.92f,
        targetValue = 1.06f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "scale",
    )

    // Rotating gradient ring angle
    val rotationAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 3500, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "rotation",
    )

    // Audio reactive pulse
    val normalizedRms = remember(liveRmsDb) {
        val clamped = liveRmsDb.coerceIn(-2f, 10f)
        ((clamped + 2f) / 12f).coerceIn(0f, 1f)
    }

    val animatedRms = remember { Animatable(0f) }
    LaunchedEffect(normalizedRms) {
        animatedRms.animateTo(
            targetValue = normalizedRms,
            animationSpec = tween(120),
        )
    }

    val activeScale = if (isListening) {
        1.0f + (animatedRms.value * 0.35f)
    } else {
        breathingScale
    }

    val orbColor = when (status) {
        AgentStatus.COMPLETED -> HarmaGreen
        AgentStatus.FAILED, AgentStatus.STOPPED -> HarmaRed
        AgentStatus.WAITING_FOR_CONFIRMATION, AgentStatus.WAITING_FOR_USER -> HarmaAmber
        AgentStatus.RUNNING -> if (isListening) HarmaGreen else HarmaPrimaryCyan
        else -> HarmaPrimary
    }

    Box(
        modifier = modifier.size(size),
        contentAlignment = Alignment.Center,
    ) {
        // Rotating aura ring
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .rotate(rotationAngle)
                .scale(activeScale),
        ) {
            val center = Offset(this.size.width / 2f, this.size.height / 2f)
            val radius = this.size.minDimension / 2f * 0.85f

            val brush = Brush.sweepGradient(
                listOf(
                    orbColor.copy(alpha = 0.1f),
                    HarmaPrimaryCyan.copy(alpha = 0.6f),
                    HarmaPrimary.copy(alpha = 0.8f),
                    orbColor.copy(alpha = 0.2f),
                ),
            )

            drawCircle(
                brush = brush,
                radius = radius,
                center = center,
                style = Stroke(width = 4.dp.toPx()),
            )
        }

        // Inner glowing core
        Canvas(
            modifier = Modifier
                .size(size * 0.65f)
                .scale(activeScale),
        ) {
            val center = Offset(this.size.width / 2f, this.size.height / 2f)
            val coreRadius = this.size.minDimension / 2f

            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        orbColor.copy(alpha = 0.75f),
                        orbColor.copy(alpha = 0.25f),
                        Color.Transparent,
                    ),
                    center = center,
                    radius = coreRadius,
                ),
                radius = coreRadius,
                center = center,
            )
        }
    }
}

