package ai.harma.app.ui.screens

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ai.harma.app.data.local.SecurePreferences
import ai.harma.app.data.model.AutonomyLevel
import ai.harma.app.ui.theme.*

@Composable
fun SettingsScreen(
    securePrefs: SecurePreferences,
    onUrlUpdated: (String) -> Unit,
    onBack: () -> Unit
) {
    var serverUrl by remember { mutableStateOf(securePrefs.baseUrl) }
    var currentAutonomy by remember { mutableStateOf(securePrefs.autonomyLevel) }
    var wakeWordEnabled by remember { mutableStateOf(securePrefs.isWakeWordEnabled) }

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
                    text = "Settings",
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
            verticalArrangement = Arrangement.spacedBy(20.dp)
        ) {
            // Harma Server URL
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(16.dp))
                        .padding(18.dp)
                ) {
                    Text(
                        text = "HARMA SERVER CONFIGURATION",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(10.dp))
                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        label = { Text("Server Base URL", color = HarmaTextSecondary) },
                        modifier = Modifier.fillMaxWidth(),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = HarmaTextPrimary,
                            unfocusedBorderColor = HarmaBorder,
                            focusedTextColor = HarmaTextPrimary,
                            unfocusedTextColor = HarmaTextPrimary
                        ),
                        singleLine = true
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        Button(
                            onClick = { onUrlUpdated(serverUrl) },
                            shape = RoundedCornerShape(10.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = HarmaTextPrimary,
                                contentColor = HarmaBlack
                            )
                        ) {
                            Text("Save & Connect")
                        }
                    }
                }
            }

            // Autonomy Policy Selection
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(16.dp))
                        .padding(18.dp)
                ) {
                    Text(
                        text = "AUTONOMY POLICY",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(12.dp))

                    AutonomyLevel.values().forEach { level ->
                        val isSelected = currentAutonomy == level
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (isSelected) HarmaBorder else HarmaBlack)
                                .border(1.dp, if (isSelected) HarmaBorderLight else HarmaBorder, RoundedCornerShape(10.dp))
                                .clickable {
                                    currentAutonomy = level
                                    securePrefs.autonomyLevel = level
                                }
                                .padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            RadioButton(
                                selected = isSelected,
                                onClick = {
                                    currentAutonomy = level
                                    securePrefs.autonomyLevel = level
                                },
                                colors = RadioButtonDefaults.colors(
                                    selectedColor = HarmaTextPrimary,
                                    unselectedColor = HarmaTextSecondary
                                )
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Column {
                                Text(
                                    text = level.title,
                                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                                    color = HarmaTextPrimary
                                )
                                Text(
                                    text = level.description,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = HarmaTextSecondary
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }

            // Voice & Wake Word
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(16.dp))
                        .padding(18.dp)
                ) {
                    Text(
                        text = "VOICE ENGINE",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column {
                            Text(
                                text = "Wake-Word Detection",
                                style = MaterialTheme.typography.bodyLarge,
                                color = HarmaTextPrimary
                            )
                            Text(
                                text = "Listens for \"Hey Harma\" or \"Harma\"",
                                style = MaterialTheme.typography.bodyMedium,
                                color = HarmaTextSecondary
                            )
                        }
                        Switch(
                            checked = wakeWordEnabled,
                            onCheckedChange = {
                                wakeWordEnabled = it
                                securePrefs.isWakeWordEnabled = it
                            },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = HarmaBlack,
                                checkedTrackColor = HarmaOnlineGreen,
                                uncheckedThumbColor = HarmaTextSecondary,
                                uncheckedTrackColor = HarmaBorder
                            )
                        )
                    }
                }
            }

            // Device Info
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(HarmaCard)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(16.dp))
                        .padding(18.dp)
                ) {
                    Text(
                        text = "DEVICE IDENTIFIER",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "ID: ${securePrefs.deviceId}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = HarmaTextPrimary
                    )
                    Text(
                        text = "Hardware: ${Build.MANUFACTURER} ${Build.MODEL}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = HarmaTextSecondary
                    )
                    Text(
                        text = "Android OS: ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
                        style = MaterialTheme.typography.bodyMedium,
                        color = HarmaTextSecondary
                    )
                }
            }

            item {
                Spacer(modifier = Modifier.height(20.dp))
            }
        }
    }
}
