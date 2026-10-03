package ai.harma.app.ui.screens

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import ai.harma.app.device.AccessibilityHelper
import ai.harma.app.ui.theme.*

@Composable
fun PermissionScreen(
    onBack: () -> Unit
) {
    val context = LocalContext.current
    var isMicGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        )
    }
    var isCameraGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    var isAccessibilityEnabled by remember {
        mutableStateOf(AccessibilityHelper.isAccessibilityEnabled(context))
    }

    val micLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        isMicGranted = granted
    }

    val cameraLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        isCameraGranted = granted
    }

    Scaffold(
        containerColor = HarmaBlack,
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                IconButton(onClick = onBack) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "Back",
                        tint = HarmaTextPrimary
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Permission Center",
                    style = MaterialTheme.typography.titleMedium,
                    color = HarmaTextPrimary
                )
            }
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            item {
                Text(
                    text = "Device Capabilities & Security",
                    style = MaterialTheme.typography.bodyMedium,
                    color = HarmaTextSecondary
                )
            }

            // Microphone Permission Card
            item {
                PermissionCard(
                    title = "Microphone",
                    description = "Required for wake-word detection (\"Hey Harma\") and voice command transcription.",
                    isGranted = isMicGranted,
                    actionText = if (isMicGranted) "Allowed" else "Grant Access",
                    onAction = {
                        micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                )
            }

            // Accessibility Service Card
            item {
                PermissionCard(
                    title = "Accessibility UI Control",
                    description = "Allows Harma to observe and interact with supported app interfaces (e.g. WhatsApp) to automate tasks.",
                    isGranted = isAccessibilityEnabled,
                    actionText = if (isAccessibilityEnabled) "Enabled" else "Open Settings",
                    onAction = {
                        AccessibilityHelper.openAccessibilitySettings(context)
                    }
                )
            }

            // Camera / Torch Card
            item {
                PermissionCard(
                    title = "Camera / Torch",
                    description = "Required to toggle and verify the device hardware flashlight.",
                    isGranted = isCameraGranted,
                    actionText = if (isCameraGranted) "Allowed" else "Grant Access",
                    onAction = {
                        cameraLauncher.launch(Manifest.permission.CAMERA)
                    }
                )
            }
        }
    }
}

@Composable
fun PermissionCard(
    title: String,
    description: String,
    isGranted: Boolean,
    actionText: String,
    onAction: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(HarmaCard)
            .border(1.dp, HarmaBorder, RoundedCornerShape(16.dp))
            .padding(18.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = HarmaTextPrimary
            )

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (isGranted) HarmaBorder else HarmaBlack)
                    .padding(horizontal = 8.dp, vertical = 4.dp)
            ) {
                Icon(
                    imageVector = if (isGranted) Icons.Default.Check else Icons.Default.Close,
                    contentDescription = null,
                    tint = if (isGranted) HarmaOnlineGreen else HarmaTextSecondary,
                    modifier = Modifier.size(14.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = if (isGranted) "Active" else "Inactive",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isGranted) HarmaOnlineGreen else HarmaTextSecondary
                )
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = description,
            style = MaterialTheme.typography.bodyMedium,
            color = HarmaTextSecondary
        )

        Spacer(modifier = Modifier.height(14.dp))

        OutlinedButton(
            onClick = onAction,
            enabled = !isGranted,
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = HarmaTextPrimary,
                disabledContentColor = HarmaTextSecondary
            ),
            border = androidx.compose.foundation.BorderStroke(1.dp, if (isGranted) HarmaBorder else HarmaTextPrimary)
        ) {
            Text(actionText)
        }
    }
}
