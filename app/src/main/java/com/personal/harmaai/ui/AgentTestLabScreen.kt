package com.personal.harmaai.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Alarm
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.FlashlightOn
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.personal.harmaai.agent.AutonomousResult
import com.personal.harmaai.agent.AutonomousTaskExecutor
import com.personal.harmaai.data.SettingsStore
import com.personal.harmaai.tools.DirectToolExecutor
import com.personal.harmaai.tools.ToolCall
import com.personal.harmaai.ui.theme.HarmaAmber
import com.personal.harmaai.ui.theme.HarmaCard
import com.personal.harmaai.ui.theme.HarmaGreen
import com.personal.harmaai.ui.theme.HarmaMuted
import com.personal.harmaai.ui.theme.HarmaRed
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

enum class TestStatus {
    IDLE,
    RUNNING,
    PASS,
    FAIL,
}

data class LabTestItem(
    val id: String,
    val title: String,
    val command: String,
    val description: String,
    val icon: ImageVector,
    var status: TestStatus = TestStatus.IDLE,
    var details: String = "",
    var durationMs: Long = 0L,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentTestLabScreen(
    settings: SettingsStore,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()

    val testItems = remember {
        mutableStateListOf(
            LabTestItem(
                id = "flashlight",
                title = "Flashlight Toggle",
                command = "turn on flashlight",
                description = "Tests CameraManager torch mode + TorchCallback state verification",
                icon = Icons.Default.FlashlightOn,
            ),
            LabTestItem(
                id = "camera",
                title = "Camera Capture",
                command = "open camera and take one photo",
                description = "Opens camera, taps shutter via Accessibility, verifies new MediaStore image",
                icon = Icons.Default.CameraAlt,
            ),
            LabTestItem(
                id = "call",
                title = "Phone Call",
                command = "call to 7092750591",
                description = "Initiates call via ACTION_CALL, verifies TelephonyManager active state",
                icon = Icons.Default.Phone,
            ),
            LabTestItem(
                id = "youtube",
                title = "YouTube Play",
                command = "open youtube and play believer",
                description = "Searches song on YouTube, taps first video, verifies playback / audio",
                icon = Icons.Default.PlayArrow,
            ),
            LabTestItem(
                id = "whatsapp",
                title = "WhatsApp Birthday Wish",
                command = "send birthday wishes to Rahul",
                description = "Generates message, opens chat, taps Send, verifies sent tick",
                icon = Icons.Default.Send,
            ),
            LabTestItem(
                id = "volume",
                title = "Volume Control",
                command = "set volume to 60%",
                description = "Sets media volume and reads back actual volume from AudioManager",
                icon = Icons.Default.VolumeUp,
            ),
            LabTestItem(
                id = "alarm",
                title = "Set Alarm",
                command = "set alarm for 7:30 AM",
                description = "Dispatches AlarmClock.ACTION_SET_ALARM with SKIP_UI=true",
                icon = Icons.Default.Alarm,
            ),
            LabTestItem(
                id = "settings",
                title = "Settings Panel",
                command = "open wifi settings",
                description = "Opens Internet connectivity panel without crashing",
                icon = Icons.Default.Wifi,
            ),
            LabTestItem(
                id = "voice",
                title = "Voice Round Trip",
                command = "STT -> Agent -> TTS",
                description = "Tests speech synthesis and TTS playback with audio focus",
                icon = Icons.Default.Mic,
            ),
        )
    }

    var isRunningAll by remember { mutableStateOf(false) }

    fun runSingleTest(item: LabTestItem) {
        val index = testItems.indexOfFirst { it.id == item.id }
        if (index < 0) return
        testItems[index] = testItems[index].copy(status = TestStatus.RUNNING, details = "Executing...")

        coroutineScope.launch {
            val start = System.currentTimeMillis()
            val executor = AutonomousTaskExecutor(context, settings)
            val directTools = DirectToolExecutor(context)

            try {
                when (item.id) {
                    "flashlight" -> {
                        val res = directTools.execute(ToolCall("set_flashlight", JSONObject().put("on", true)))
                        delay(800L)
                        directTools.execute(ToolCall("set_flashlight", JSONObject().put("on", false)))
                        val duration = System.currentTimeMillis() - start
                        testItems[index] = testItems[index].copy(
                            status = if (res.success) TestStatus.PASS else TestStatus.FAIL,
                            details = if (res.success) "PASS: Flashlight turned on and verified by TorchCallback, then turned off (${duration}ms)" else "FAIL: ${res.message}",
                            durationMs = duration,
                        )
                    }

                    "camera" -> {
                        val res = executor.tryExecute("open camera and take one photo", "lab-camera")
                        val duration = System.currentTimeMillis() - start
                        when (res) {
                            is AutonomousResult.Success -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.PASS,
                                    details = "PASS: Camera opened, shutter triggered, image verified in MediaStore (${duration}ms)",
                                    durationMs = duration,
                                )
                            }
                            is AutonomousResult.Failure -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.FAIL,
                                    details = "FAIL: Step ${res.stepFailed}: ${res.reason}",
                                    durationMs = duration,
                                )
                            }
                            else -> {
                                testItems[index] = testItems[index].copy(status = TestStatus.FAIL, details = "FAIL: Not handled")
                            }
                        }
                    }

                    "call" -> {
                        val res = executor.tryExecute("call to 7092750591", "lab-call")
                        val duration = System.currentTimeMillis() - start
                        when (res) {
                            is AutonomousResult.Success -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.PASS,
                                    details = "PASS: Direct call placed and confirmed active (${duration}ms)",
                                    durationMs = duration,
                                )
                            }
                            is AutonomousResult.Failure -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.FAIL,
                                    details = "FAIL: Step ${res.stepFailed}: ${res.reason}",
                                    durationMs = duration,
                                )
                            }
                            else -> {
                                testItems[index] = testItems[index].copy(status = TestStatus.FAIL, details = "FAIL: Not handled")
                            }
                        }
                    }

                    "youtube" -> {
                        val res = executor.tryExecute("open youtube and play believer", "lab-yt")
                        val duration = System.currentTimeMillis() - start
                        when (res) {
                            is AutonomousResult.Success -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.PASS,
                                    details = "PASS: YouTube opened, search executed, video playback confirmed (${duration}ms)",
                                    durationMs = duration,
                                )
                            }
                            is AutonomousResult.Failure -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.FAIL,
                                    details = "FAIL: Step ${res.stepFailed}: ${res.reason}",
                                    durationMs = duration,
                                )
                            }
                            else -> {
                                testItems[index] = testItems[index].copy(status = TestStatus.FAIL, details = "FAIL: Not handled")
                            }
                        }
                    }

                    "whatsapp" -> {
                        val res = executor.tryExecute("send birthday wishes to Rahul", "lab-wa")
                        val duration = System.currentTimeMillis() - start
                        when (res) {
                            is AutonomousResult.Success -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.PASS,
                                    details = "PASS: Birthday message generated, chat opened, message sent (${duration}ms)",
                                    durationMs = duration,
                                )
                            }
                            is AutonomousResult.Failure -> {
                                testItems[index] = testItems[index].copy(
                                    status = TestStatus.FAIL,
                                    details = "FAIL: Step ${res.stepFailed}: ${res.reason}",
                                    durationMs = duration,
                                )
                            }
                            else -> {
                                testItems[index] = testItems[index].copy(status = TestStatus.FAIL, details = "FAIL: Not handled")
                            }
                        }
                    }

                    "volume" -> {
                        val res = directTools.execute(ToolCall("set_volume", JSONObject().put("stream", "media").put("percent", 60)))
                        val duration = System.currentTimeMillis() - start
                        testItems[index] = testItems[index].copy(
                            status = if (res.success) TestStatus.PASS else TestStatus.FAIL,
                            details = if (res.success) "PASS: ${res.message} (${duration}ms)" else "FAIL: ${res.message}",
                            durationMs = duration,
                        )
                    }

                    "alarm" -> {
                        val res = directTools.execute(ToolCall("set_alarm", JSONObject().put("hour", 7).put("minute", 30).put("label", "Harma Test")))
                        val duration = System.currentTimeMillis() - start
                        testItems[index] = testItems[index].copy(
                            status = if (res.success) TestStatus.PASS else TestStatus.FAIL,
                            details = if (res.success) "PASS: Alarm dispatch confirmed (${duration}ms)" else "FAIL: ${res.message}",
                            durationMs = duration,
                        )
                    }

                    "settings" -> {
                        val res = directTools.execute(ToolCall("open_wifi_settings", JSONObject()))
                        val duration = System.currentTimeMillis() - start
                        testItems[index] = testItems[index].copy(
                            status = if (res.success) TestStatus.PASS else TestStatus.FAIL,
                            details = if (res.success) "PASS: Settings panel opened (${duration}ms)" else "FAIL: ${res.message}",
                            durationMs = duration,
                        )
                    }

                    "voice" -> {
                        val tts = com.personal.harmaai.voice.TtsController(context)
                        delay(500L)
                        val spoke = tts.speak("Harma AI voice test completed successfully.")
                        val duration = System.currentTimeMillis() - start
                        testItems[index] = testItems[index].copy(
                            status = if (spoke) TestStatus.PASS else TestStatus.FAIL,
                            details = if (spoke) "PASS: TTS engine initialized, audio focus requested, spoken confirmation dispatched (${duration}ms)" else "FAIL: TTS not ready",
                            durationMs = duration,
                        )
                    }
                }
            } catch (e: Exception) {
                testItems[index] = testItems[index].copy(
                    status = TestStatus.FAIL,
                    details = "ERROR: ${e.message}",
                    durationMs = System.currentTimeMillis() - start,
                )
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                title = { Text("Agent Test Lab", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(
                        onClick = {
                            testItems.indices.forEach { idx ->
                                testItems[idx] = testItems[idx].copy(status = TestStatus.IDLE, details = "", durationMs = 0L)
                            }
                        },
                    ) {
                        Icon(Icons.Default.Refresh, contentDescription = "Reset All")
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = HarmaCard),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Text(
                            "One-Tap Scenario Verification",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Runs deterministic Observe -> Plan -> Act -> Verify tests for core phone actions. Verifies actual hardware and app state.",
                            style = MaterialTheme.typography.bodySmall,
                            color = HarmaMuted,
                        )
                        Spacer(Modifier.height(10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            val passCount = testItems.count { it.status == TestStatus.PASS }
                            val failCount = testItems.count { it.status == TestStatus.FAIL }
                            Box(
                                modifier = Modifier
                                    .background(HarmaGreen.copy(alpha = 0.15f), RoundedCornerShape(6.dp))
                                    .padding(horizontal = 8.dp, vertical = 4.dp),
                            ) {
                                Text("$passCount PASS", color = HarmaGreen, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                            }
                            if (failCount > 0) {
                                Box(
                                    modifier = Modifier
                                        .background(HarmaRed.copy(alpha = 0.15f), RoundedCornerShape(6.dp))
                                        .padding(horizontal = 8.dp, vertical = 4.dp),
                                ) {
                                    Text("$failCount FAIL", color = HarmaRed, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
            }

            items(testItems, key = { it.id }) { item ->
                Card(
                    colors = CardDefaults.cardColors(containerColor = HarmaCard),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Icon(
                                item.icon,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(24.dp),
                            )
                            Spacer(Modifier.width(10.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(item.title, fontWeight = FontWeight.Bold)
                                Text(
                                    "\"${item.command}\"",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = HarmaMuted,
                                    fontFamily = FontFamily.Monospace,
                                )
                            }
                            when (item.status) {
                                TestStatus.IDLE -> {
                                    OutlinedButton(
                                        onClick = { runSingleTest(item) },
                                        modifier = Modifier.height(34.dp),
                                    ) {
                                        Text("RUN", fontSize = 12.sp)
                                    }
                                }
                                TestStatus.RUNNING -> {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(22.dp),
                                        strokeWidth = 2.dp,
                                    )
                                }
                                TestStatus.PASS -> {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Icon(Icons.Default.CheckCircle, null, tint = HarmaGreen, modifier = Modifier.size(18.dp))
                                        Spacer(Modifier.width(4.dp))
                                        Text("PASS", color = HarmaGreen, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                                    }
                                }
                                TestStatus.FAIL -> {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Icon(Icons.Default.Error, null, tint = HarmaRed, modifier = Modifier.size(18.dp))
                                        Spacer(Modifier.width(4.dp))
                                        Text("FAIL", color = HarmaRed, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                                    }
                                }
                            }
                        }

                        if (item.details.isNotBlank()) {
                            Spacer(Modifier.height(8.dp))
                            Text(
                                item.details,
                                style = MaterialTheme.typography.bodySmall,
                                color = when (item.status) {
                                    TestStatus.PASS -> HarmaGreen
                                    TestStatus.FAIL -> HarmaRed
                                    else -> HarmaMuted
                                },
                            )
                        }
                    }
                }
            }

            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

