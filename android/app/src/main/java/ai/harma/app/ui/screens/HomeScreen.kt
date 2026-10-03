package ai.harma.app.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.harma.app.data.model.VoiceState
import ai.harma.app.ui.theme.*

@Composable
fun HomeScreen(
    voiceState: VoiceState,
    connectionState: String,
    recentSteps: List<String>,
    onMicClick: () -> Unit,
    onQuickPromptClick: (String) -> Unit,
    onNavigateConversation: () -> Unit,
    onNavigatePermissions: () -> Unit,
    onNavigateSettings: () -> Unit
) {
    val infiniteTransition = rememberInfiniteTransition(label = "orb_pulse")
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 1.0f,
        targetValue = if (voiceState == VoiceState.LISTENING || voiceState == VoiceState.UNDERSTANDING || voiceState == VoiceState.EXECUTING) 1.15f else 1.03f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = if (voiceState == VoiceState.LISTENING) 700 else 1800,
                easing = FastOutSlowInEasing
            ),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulse_scale"
    )

    Scaffold(
        containerColor = HarmaBlack,
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp, vertical = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Connection status badge
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .clip(RoundedCornerShape(12.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(12.dp))
                        .padding(horizontal = 10.dp, vertical = 4.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(
                                if (connectionState == "ONLINE") HarmaOnlineGreen else HarmaTextSecondary
                            )
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = connectionState,
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                }

                // Action icons
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    IconButton(onClick = onNavigateConversation) {
                        Icon(Icons.Default.Chat, contentDescription = "Conversation", tint = HarmaTextSecondary)
                    }
                    IconButton(onClick = onNavigatePermissions) {
                        Icon(Icons.Default.Security, contentDescription = "Permissions", tint = HarmaTextSecondary)
                    }
                    IconButton(onClick = onNavigateSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "Settings", tint = HarmaTextSecondary)
                    }
                }
            }
        }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(24.dp))

            // Minimal Title
            Text(
                text = "HARMA",
                style = MaterialTheme.typography.displayLarge.copy(
                    fontWeight = FontWeight.ExtraLight,
                    letterSpacing = 4.sp
                ),
                color = HarmaTextPrimary
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "How can I help?",
                style = MaterialTheme.typography.titleMedium,
                color = HarmaTextSecondary
            )

            Spacer(modifier = Modifier.weight(1f))

            // Central Glowing Minimal Voice Orb
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(140.dp)
                    .scale(pulseScale)
                    .clip(CircleShape)
                    .background(HarmaCard)
                    .border(
                        width = if (voiceState == VoiceState.LISTENING) 2.dp else 1.dp,
                        color = if (voiceState == VoiceState.LISTENING) HarmaTextPrimary else HarmaBorderLight,
                        shape = CircleShape
                    )
                    .clickable { onMicClick() }
            ) {
                // Secondary inner circle
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(80.dp)
                        .clip(CircleShape)
                        .background(HarmaBorder)
                ) {
                    Icon(
                        imageVector = Icons.Default.Mic,
                        contentDescription = "Microphone",
                        tint = if (voiceState == VoiceState.LISTENING) HarmaOnlineGreen else HarmaTextPrimary,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(20.dp))

            // Voice State status indicator
            Text(
                text = voiceState.displayLabel,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                color = when (voiceState) {
                    VoiceState.LISTENING -> HarmaOnlineGreen
                    VoiceState.ERROR -> HarmaErrorRed
                    else -> HarmaTextPrimary
                },
                textAlign = TextAlign.Center
            )

            Text(
                text = "Tap or say \"Hey Harma\"",
                style = MaterialTheme.typography.bodyMedium,
                color = HarmaTextSecondary,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.weight(1f))

            // Quick suggestion chips
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                SuggestionChip(
                    text = "WhatsApp hi to Bhuvanesh",
                    modifier = Modifier.weight(1f),
                    onClick = { onQuickPromptClick("Open WhatsApp and send hi to Bhuvanesh") }
                )
                SuggestionChip(
                    text = "Turn on flashlight",
                    modifier = Modifier.weight(1f),
                    onClick = { onQuickPromptClick("Turn on the flashlight") }
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Recent execution activity card if available
            if (recentSteps.isNotEmpty()) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(14.dp))
                        .padding(14.dp)
                ) {
                    Text(
                        text = "ACTIVE EXECUTION",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    recentSteps.takeLast(2).forEach { step ->
                        Text(
                            text = "→ $step",
                            style = MaterialTheme.typography.bodyMedium,
                            color = HarmaTextPrimary
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
fun SuggestionChip(
    text: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(HarmaCard)
            .border(1.dp, HarmaBorder, RoundedCornerShape(12.dp))
            .clickable { onClick() }
            .padding(horizontal = 12.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = HarmaTextPrimary,
            textAlign = TextAlign.Center,
            maxLines = 1
        )
    }
}
