package com.personal.harmaai.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Build
import android.util.Base64
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Hearing
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Photo
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.personal.harmaai.R
import com.personal.harmaai.agent.AgentRuntime
import com.personal.harmaai.agent.AgentStatus
import com.personal.harmaai.agent.AgentStep
import com.personal.harmaai.agent.ChatAuthor
import com.personal.harmaai.agent.HarmaMessage
import com.personal.harmaai.data.SettingsStore
import com.personal.harmaai.data.TaskEntity
import com.personal.harmaai.permissions.DeviceBackgroundPolicy
import com.personal.harmaai.permissions.PermissionNavigator
import com.personal.harmaai.permissions.PermissionSnapshot
import com.personal.harmaai.voice.AudioRecorder
import com.personal.harmaai.voice.GroqWhisperClient
import com.personal.harmaai.voice.HarmaVoiceService
import com.personal.harmaai.voice.VoiceActivityDetector
import kotlinx.coroutines.launch
import com.personal.harmaai.ui.theme.HarmaAmber
import com.personal.harmaai.ui.theme.HarmaBorder
import com.personal.harmaai.ui.theme.HarmaCard
import com.personal.harmaai.ui.theme.HarmaGreen
import com.personal.harmaai.ui.theme.HarmaMuted
import com.personal.harmaai.ui.theme.HarmaRed
import com.personal.harmaai.voice.SpeechRecognizerController
import java.text.DateFormat
import java.util.Date

private enum class Screen {
    CHAT,
    SETUP,
    SETTINGS,
    HISTORY,
    TEST_LAB,
}

@Composable
fun HarmaAiApp(viewModel: HarmaViewModel = viewModel()) {
    var screen by rememberSaveable {
        mutableStateOf(if (viewModel.settings.onboardingCompleted) Screen.CHAT else Screen.SETUP)
    }
    when (screen) {
        Screen.CHAT -> ChatScreen(
            viewModel = viewModel,
            onSetup = { screen = Screen.SETUP },
            onSettings = { screen = Screen.SETTINGS },
            onHistory = { screen = Screen.HISTORY },
            onTestLab = { screen = Screen.TEST_LAB },
        )
        Screen.SETUP -> SetupScreen(
            settings = viewModel.settings,
            onBack = { screen = Screen.CHAT },
        )
        Screen.SETTINGS -> SettingsScreen(
            settings = viewModel.settings,
            onBack = { screen = Screen.CHAT },
            onTestLab = { screen = Screen.TEST_LAB },
        )
        Screen.HISTORY -> HistoryScreen(viewModel = viewModel, onBack = { screen = Screen.CHAT })
        Screen.TEST_LAB -> AgentTestLabScreen(
            settings = viewModel.settings,
            onBack = { screen = Screen.CHAT },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatScreen(
    viewModel: HarmaViewModel,
    onSetup: () -> Unit,
    onSettings: () -> Unit,
    onHistory: () -> Unit,
    onTestLab: () -> Unit,
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val state by viewModel.runtime.collectAsStateWithLifecycle()
    var input by rememberSaveable { mutableStateOf("") }
    var listening by remember { mutableStateOf(false) }
    var isRecordingGroq by remember { mutableStateOf(false) }
    var isTranscribingGroq by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    val audioRecorder = remember { AudioRecorder(context) }
    val groqClient = remember { GroqWhisperClient() }

    val voice = remember {
        SpeechRecognizerController(
            context,
            object : SpeechRecognizerController.Callback {
                override fun onListeningChanged(isListening: Boolean) {
                    listening = isListening
                }

                override fun onPartialText(text: String) {
                    input = text
                }

                override fun onRmsChanged(rmsdB: Float) {
                    com.personal.harmaai.agent.AgentRuntime.setLiveRms(rmsdB)
                }

                override fun onFinalText(text: String) {
                    input = ""
                    val cleaned = text.replace(Regex("(?i)^(\\s*hey\\s+harma|hi\\s+harma|ok\\s+harma|harma)[,\\s]*"), "").trim()
                    val command = if (cleaned.isNotBlank()) cleaned else text
                    viewModel.submit(command)
                }

                override fun onError(message: String) {
                    com.personal.harmaai.agent.AgentRuntime.addSystemMessage(message)
                }
            },
        )
    }
    DisposableEffect(Unit) {
        onDispose {
            voice.destroy()
            audioRecorder.cancel()
        }
    }

    var showMicRationale by remember { mutableStateOf(false) }

    val microphoneLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> if (granted) voice.startListening() }

    LaunchedEffect(state.messages.size, state.steps.size) {
        val total = state.messages.size + state.steps.size
        if (total > 0) listState.animateScrollToItem(total - 1)
    }

    if (showMicRationale) {
        AlertDialog(
            onDismissRequest = { showMicRationale = false },
            title = { Text("Microphone Access Required") },
            text = {
                Text("Harma AI uses microphone access strictly to listen to your voice and convert your spoken words into agent actions. Audio is only captured while you hold or tap the microphone button and is never stored or transmitted in the background.")
            },
            confirmButton = {
                Button(onClick = {
                    showMicRationale = false
                    microphoneLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }) {
                    Text("Grant Permission")
                }
            },
            dismissButton = {
                TextButton(onClick = { showMicRationale = false }) {
                    Text("Cancel")
                }
            },
        )
    }

    state.pendingConfirmation?.let { pending ->
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Confirm sensitive action") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(pending.description)
                    Text(pending.toolName, fontWeight = FontWeight.Bold)
                    Text(pending.arguments, color = HarmaMuted)
                }
            },
            confirmButton = {
                Button(onClick = { viewModel.confirm(true) }) { Text("Allow once") }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.confirm(false) }) { Text("Deny") }
            },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            painter = painterResource(R.drawable.harma_logo),
                            contentDescription = null,
                            modifier = Modifier.size(42.dp).clip(CircleShape),
                        )
                        Spacer(Modifier.size(10.dp))
                        Column {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("Harma AI", fontWeight = FontWeight.Bold)
                                if (viewModel.settings.alwaysListenEnabled) {
                                    Spacer(Modifier.size(6.dp))
                                    Box(
                                        modifier = Modifier
                                            .background(HarmaGreen.copy(alpha = 0.2f), RoundedCornerShape(4.dp))
                                            .padding(horizontal = 5.dp, vertical = 1.dp),
                                    ) {
                                        Text(
                                            "Hey Harma",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = HarmaGreen,
                                            fontWeight = FontWeight.Bold,
                                        )
                                    }
                                }
                            }
                            Text(
                                stateLabel(state.status, state.currentStep),
                                style = MaterialTheme.typography.labelMedium,
                                color = statusColor(state.status),
                            )
                        }
                    }
                },
                actions = {
                    IconButton(onClick = onTestLab) { Icon(Icons.Default.Build, "Agent Test Lab") }
                    IconButton(onClick = onHistory) { Icon(Icons.Default.History, "History") }
                    IconButton(onClick = onSetup) { Icon(Icons.Default.Security, "Permissions") }
                    IconButton(onClick = onSettings) { Icon(Icons.Default.Settings, "Settings") }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
                .navigationBarsPadding(),
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item { Spacer(Modifier.height(4.dp)) }
                if (state.messages.size <= 1 && state.steps.isEmpty()) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 20.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            HarmaOrb(
                                status = state.status,
                                isListening = state.isVoiceListening || listening,
                                liveRmsDb = state.liveRmsDb,
                                size = 110.dp,
                            )
                        }
                    }
                }
                items(state.messages, key = { "m-${it.id}" }) { MessageBubble(it) }
                if (state.steps.isNotEmpty()) {
                    item {
                        Text(
                            "Live action log",
                            style = MaterialTheme.typography.labelLarge,
                            color = HarmaMuted,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                    items(state.steps, key = { "s-${it.id}" }) { step ->
                        StepCard(step, onRetry = { viewModel.submit(state.currentTask) })
                    }
                }
                item { Spacer(Modifier.height(4.dp)) }
            }

            if (state.status == AgentStatus.RUNNING || state.status == AgentStatus.WAITING_FOR_CONFIRMATION) {
                Button(
                    onClick = viewModel::stop,
                    colors = ButtonDefaults.buttonColors(containerColor = HarmaRed),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Default.Stop, null)
                    Spacer(Modifier.size(8.dp))
                    Text("STOP Harma AI")
                }
            }

            val isListening = isRecordingGroq || isTranscribingGroq || state.isVoiceListening
            val isWorking = isTranscribingGroq || state.voiceStateText.contains("Working") || state.voiceStateText.contains("Transcribing")
            AnimatedVisibility(visible = isListening) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 14.dp, vertical = 2.dp)
                        .background(
                            if (isWorking) HarmaAmber.copy(alpha = 0.15f) else HarmaGreen.copy(alpha = 0.15f),
                            RoundedCornerShape(8.dp),
                        )
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Icon(
                        if (isWorking) Icons.Default.Hearing else Icons.Default.Mic,
                        contentDescription = null,
                        tint = if (isWorking) HarmaAmber else HarmaGreen,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        if (isWorking) "Transcribing with Groq Whisper..." else "Listening... Speak your command",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isWorking) HarmaAmber else HarmaGreen,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }

            // Suggestion chips
            if (state.status == AgentStatus.IDLE) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    val suggestions = listOf(
                        "💡 Flashlight" to "turn on flashlight",
                        "🎵 Play on YouTube" to "open youtube and play a song",
                        "🎂 Birthday wish" to "send birthday wishes to Rahul on whatsapp",
                    )
                    suggestions.forEach { (label, cmd) ->
                        OutlinedButton(
                            onClick = {
                                input = cmd
                                viewModel.submit(cmd)
                            },
                            shape = RoundedCornerShape(20.dp),
                            modifier = Modifier.height(34.dp),
                            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                        ) {
                            Text(label, style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth().padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("Tell Harma AI what to do") },
                    enabled = state.status != AgentStatus.RUNNING,
                    maxLines = 4,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(
                        onSend = {
                            viewModel.submit(input)
                            input = ""
                        },
                    ),
                )
                IconButton(
                    onClick = {
                        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                            showMicRationale = true
                        } else {
                            val groqKey = viewModel.settings.groqApiKey
                            if (groqKey.isNotBlank()) {
                                HarmaVoiceService.triggerTalkNow(context)
                            } else {
                                if (listening) {
                                    voice.cancel()
                                } else {
                                    voice.startListening()
                                }
                            }
                        }
                    },
                    enabled = state.status != AgentStatus.RUNNING,
                ) {
                    Icon(
                        when {
                            state.isVoiceListening -> Icons.Default.Stop
                            listening -> Icons.Default.MicOff
                            else -> Icons.Default.Mic
                        },
                        contentDescription = "Voice command",
                        tint = if (state.isVoiceListening) HarmaGreen else LocalContentColor.current,
                    )
                }
                FilledIconButton(
                    onClick = {
                        viewModel.submit(input)
                        input = ""
                    },
                    enabled = input.isNotBlank() && state.status != AgentStatus.RUNNING,
                ) {
                    Icon(Icons.AutoMirrored.Filled.Send, "Send")
                }
            }
        }
    }
}

@Composable
private fun MessageBubble(message: HarmaMessage) {
    val isUser = message.author == ChatAuthor.USER
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(if (isUser) .82f else .9f),
            shape = RoundedCornerShape(18.dp),
            colors = CardDefaults.cardColors(
                containerColor = when (message.author) {
                    ChatAuthor.USER -> MaterialTheme.colorScheme.primaryContainer
                    ChatAuthor.SYSTEM -> MaterialTheme.colorScheme.secondaryContainer
                    ChatAuthor.HARMA -> HarmaCard
                },
            ),
        ) {
            Row(
                modifier = Modifier.padding(14.dp),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (message.isVoice) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = "Voice input",
                        modifier = Modifier.size(16.dp).padding(top = 2.dp),
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
                Text(message.text)
            }
        }
    }
}

@Composable
private fun StepCard(step: AgentStep, onRetry: (() -> Unit)? = null) {
    var showScreenshot by remember { mutableStateOf(false) }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (step.screenshotBase64.isNotBlank()) Modifier.clickable { showScreenshot = true } else Modifier),
        colors = CardDefaults.cardColors(containerColor = HarmaCard),
        shape = RoundedCornerShape(12.dp),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Box(
                modifier = Modifier.size(28.dp).clip(CircleShape).background(
                    when (step.success) {
                        true -> HarmaGreen.copy(alpha = 0.2f)
                        false -> HarmaRed.copy(alpha = 0.2f)
                        null -> HarmaAmber.copy(alpha = 0.2f)
                    },
                ),
                contentAlignment = Alignment.Center,
            ) {
                when (step.success) {
                    true -> Icon(Icons.Default.CheckCircle, null, tint = HarmaGreen, modifier = Modifier.size(18.dp))
                    false -> Icon(Icons.Default.Error, null, tint = HarmaRed, modifier = Modifier.size(18.dp))
                    null -> CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp), color = HarmaAmber)
                }
            }
            Column(Modifier.weight(1f)) {
                Text(step.title, fontWeight = FontWeight.SemiBold)
                if (step.detail.isNotBlank()) {
                    Text(step.detail, color = if (step.success == false) HarmaRed else HarmaMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
            if (step.success == false && onRetry != null) {
                OutlinedButton(
                    onClick = onRetry,
                    shape = RoundedCornerShape(12.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp, vertical = 2.dp),
                    modifier = Modifier.height(28.dp),
                ) {
                    Text("Retry", fontSize = 11.sp, color = HarmaAmber)
                }
            }
            if (step.screenshotBase64.isNotBlank()) Icon(Icons.Default.Photo, "View screenshot", tint = HarmaMuted)
        }
    }
    if (showScreenshot) ScreenshotDialog(step.screenshotBase64) { showScreenshot = false }
}

@Composable
private fun ScreenshotDialog(base64: String, onDismiss: () -> Unit) {
    val bitmap = remember(base64) {
        runCatching {
            val bytes = Base64.decode(base64, Base64.DEFAULT)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
        }.getOrNull()
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Screen observed by Harma AI") },
        text = {
            bitmap?.let {
                Image(
                    bitmap = it,
                    contentDescription = "Agent screenshot",
                    modifier = Modifier.fillMaxWidth(),
                    contentScale = ContentScale.Fit,
                )
            } ?: Text("Screenshot could not be decoded.")
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SetupScreen(settings: SettingsStore, onBack: () -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var snapshot by remember { mutableStateOf(PermissionNavigator.snapshot(context)) }
    val micLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { snapshot = PermissionNavigator.snapshot(context) }
    val notificationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { snapshot = PermissionNavigator.snapshot(context) }
    val phoneLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { snapshot = PermissionNavigator.snapshot(context) }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) snapshot = PermissionNavigator.snapshot(context)
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Scaffold(topBar = { SimpleBackBar("Harma AI setup", onBack) }) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Image(
                    painter = painterResource(R.drawable.harma_logo_wide),
                    contentDescription = null,
                    modifier = Modifier.fillMaxWidth().height(140.dp),
                    contentScale = ContentScale.Fit,
                )
                Card(
                    colors = CardDefaults.cardColors(containerColor = HarmaCard),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Trust & Security First", fontWeight = FontWeight.Bold, color = HarmaGreen)
                        Text(
                            "• Why Accessibility is needed: Allows Harma AI to see screen controls and perform actions (tap, scroll, type) on your direct command.\n" +
                            "• What it can see: Only active interactive UI elements required for your task.\n" +
                            "• Zero Passwords or PINs: Harma AI never reads or enters passwords, PINs, OTPs, or payment details. Protected screens are blocked automatically.\n" +
                            "• You are always in control: An emergency STOP button is always present in your notification shade, or press Volume Down twice to halt.",
                            style = MaterialTheme.typography.bodySmall,
                            color = HarmaMuted,
                        )
                    }
                }
            }
            item {
                PermissionCard(
                    title = "Voice input (Microphone)",
                    description = "Used strictly when you say 'Hey Harma' or tap the mic button to speak instructions. Never records in the background.",
                    granted = snapshot.microphone,
                    button = "Allow Microphone",
                ) { micLauncher.launch(Manifest.permission.RECORD_AUDIO) }
            }
            if (Build.VERSION.SDK_INT >= 33) {
                item {
                    PermissionCard(
                        title = "Notifications & Stop control",
                        description = "Displays the agent status and the immediate STOP button in your notification drawer while a task is running.",
                        granted = snapshot.notifications,
                        button = "Allow Notifications",
                    ) { notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) }
                }
            }
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = HarmaCard),
                    border = if (!snapshot.accessibility) androidx.compose.foundation.BorderStroke(1.dp, HarmaAmber) else null,
                ) {
                    Column(
                        Modifier.fillMaxWidth().padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Accessibility phone control", fontWeight = FontWeight.SemiBold)
                            Text(
                                when {
                                    snapshot.accessibility -> "READY"
                                    snapshot.accessibilitySetting -> "CONNECTING..."
                                    else -> "NEEDED"
                                },
                                color = if (snapshot.accessibility) HarmaGreen else HarmaAmber,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Text(
                            "Required for Harma AI to read screen context and execute taps, text entry, and navigation. This step cannot be skipped.",
                            color = HarmaMuted,
                        )

                        // Sideload and Android 13+ Restricted Settings guidance
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f),
                            ),
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        ) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(
                                    "Sideload Guide: If Accessibility is greyed out",
                                    fontWeight = FontWeight.SemiBold,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Text(
                                    "On Android 13+ sideloaded apps, Android restricts accessibility by default:\n" +
                                        "1. Tap 'Open App Info' below\n" +
                                        "2. Tap the ⋮ (three dots) in top-right corner\n" +
                                        "3. Select 'Allow restricted settings' and confirm PIN\n" +
                                        "4. Return here and tap 'Open Accessibility Settings'",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = HarmaMuted,
                                )
                                OutlinedButton(onClick = { PermissionNavigator.openAppDetails(context) }) {
                                    Text("Open App Info (Allow restricted settings)")
                                }
                            }
                        }

                        OutlinedButton(
                            onClick = { PermissionNavigator.openAccessibility(context) },
                            enabled = !snapshot.accessibility,
                        ) {
                            Text(if (snapshot.accessibility) "Connected & Ready" else "Open Accessibility Settings")
                        }
                    }
                }
            }
            item {
                PermissionCard(
                    title = "Battery optimization exemption",
                    description = "Keeps an active user-started agent task running continuously without Android killing the background process.",
                    granted = snapshot.batteryExempt,
                    button = "Request exemption",
                ) { PermissionNavigator.requestBatteryExemption(context) }
            }
            item {
                PermissionCard(
                    title = "Do Not Disturb access",
                    description = "Allows Harma AI to change ringer mode to silent or normal when requested.",
                    granted = snapshot.dndAccess,
                    button = "Open setting",
                ) { PermissionNavigator.openDndAccess(context) }
            }
            item {
                PermissionCard(
                    title = "Direct phone call permission (CALL_PHONE)",
                    description = "Enables Harma AI to initiate direct calls autonomously when you say 'call <number/contact>'.",
                    granted = snapshot.phoneCall,
                    button = "Grant permission",
                ) { phoneLauncher.launch(Manifest.permission.CALL_PHONE) }
            }
            item {
                val bgGuide = remember(context) { DeviceBackgroundPolicy.getGuide(context) }
                Card(colors = CardDefaults.cardColors(containerColor = HarmaCard)) {
                    Column(
                        Modifier.fillMaxWidth().padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(bgGuide.title, fontWeight = FontWeight.SemiBold)
                            Text("OPTIONAL", color = HarmaAmber)
                        }
                        Text(
                            "Optimised for ${bgGuide.brandName}:",
                            fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        bgGuide.steps.forEachIndexed { i, step ->
                            Text("${i + 1}. $step", color = HarmaMuted)
                        }
                        Text(
                            "Note: Menu names vary by phone.",
                            style = MaterialTheme.typography.bodySmall,
                            color = HarmaMuted,
                        )
                        OutlinedButton(onClick = { PermissionNavigator.openBackgroundSettings(context) }) {
                            Text(bgGuide.settingsButtonLabel)
                        }
                    }
                }
            }
            item {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    if (!snapshot.accessibility) {
                        Text(
                            "Accessibility service must be enabled to continue.",
                            color = HarmaAmber,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    Button(
                        onClick = {
                            settings.onboardingCompleted = true
                            onBack()
                        },
                        enabled = snapshot.accessibility,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = HarmaGreen,
                            contentColor = androidx.compose.ui.graphics.Color.Black,
                        ),
                    ) {
                        Icon(Icons.Default.CheckCircle, null)
                        Spacer(Modifier.size(8.dp))
                        Text(if (snapshot.accessibility) "Continue to Harma AI" else "Turn on Accessibility to Continue")
                    }
                }
            }
        }
    }
}

@Composable
private fun PermissionCard(
    title: String,
    description: String,
    granted: Boolean,
    button: String,
    manual: Boolean = false,
    onClick: () -> Unit,
) {
    Card(colors = CardDefaults.cardColors(containerColor = HarmaCard)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(
                    when {
                        granted -> "READY"
                        manual -> "MANUAL"
                        else -> "NEEDED"
                    },
                    color = if (granted) HarmaGreen else HarmaAmber,
                )
            }
            Text(description, color = HarmaMuted)
            OutlinedButton(onClick = onClick, enabled = manual || !granted) {
                Text(if (granted && !manual) "Granted" else button)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsScreen(
    settings: SettingsStore,
    onBack: () -> Unit,
    onTestLab: () -> Unit = {},
) {
    val context = LocalContext.current
    // Keep credentials out of Compose saved-instance-state Bundles.
    var apiKey by remember { mutableStateOf(settings.apiKey) }
    var primaryModel by rememberSaveable { mutableStateOf(settings.primaryModel) }
    var fastModel by rememberSaveable { mutableStateOf(settings.fastModel) }
    var smartModel by rememberSaveable { mutableStateOf(settings.smartModel) }
    var fallbackModels by rememberSaveable { mutableStateOf(settings.fallbackModels.joinToString("\n")) }
    var groqApiKey by remember { mutableStateOf(settings.groqApiKey) }
    var groqModel by rememberSaveable { mutableStateOf(settings.groqWhisperModel) }
    var alwaysListen by rememberSaveable { mutableStateOf(settings.alwaysListenEnabled) }
    var wakeWordThreshold by rememberSaveable { mutableStateOf(settings.wakeWordThreshold) }
    var whisperLanguage by rememberSaveable { mutableStateOf(settings.whisperLanguage) }
    var speechRate by rememberSaveable { mutableStateOf(settings.speechRate) }
    var speechPitch by rememberSaveable { mutableStateOf(settings.speechPitch) }
    var conversationMode by rememberSaveable { mutableStateOf(settings.conversationMode) }
    var autoSend by rememberSaveable { mutableStateOf(settings.autoSendWithoutConfirmation) }
    var showTestVoiceDialog by remember { mutableStateOf(false) }
    var isTestingVoice by remember { mutableStateOf(false) }
    var testVoiceResult by remember { mutableStateOf("") }
    var showTestWakeWordDialog by remember { mutableStateOf(false) }
    var isTestingNvidia by remember { mutableStateOf(false) }
    var testNvidiaResult by remember { mutableStateOf("") }
    val coroutineScope = rememberCoroutineScope()
    var maxSteps by rememberSaveable { mutableStateOf(settings.maxSteps.toString()) }
    var delayMs by rememberSaveable { mutableStateOf(settings.stepDelayMs.toString()) }
    var confirmations by rememberSaveable { mutableStateOf(settings.confirmationsEnabled) }
    var vision by rememberSaveable { mutableStateOf(settings.visionEnabled) }
    var tts by rememberSaveable { mutableStateOf(settings.ttsEnabled) }
    var allowedApps by rememberSaveable { mutableStateOf(settings.allowedApps.joinToString(", ")) }
    var deniedApps by rememberSaveable { mutableStateOf(settings.deniedApps.joinToString(", ")) }
    var keyVisible by remember { mutableStateOf(false) }
    var groqKeyVisible by remember { mutableStateOf(false) }
    var saved by rememberSaveable { mutableStateOf(false) }

    Scaffold(topBar = { SimpleBackBar("Harma AI settings", onBack) }) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = HarmaCard),
                    modifier = Modifier.fillMaxWidth().clickable { onTestLab() },
                ) {
                    Row(
                        modifier = Modifier.padding(14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.Build, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(24.dp))
                        Spacer(Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text("Agent Test Lab", fontWeight = FontWeight.Bold)
                            Text("Run one-tap verification for camera, calls, flashlight, YouTube, WhatsApp", style = MaterialTheme.typography.bodySmall, color = HarmaMuted)
                        }
                    }
                }
            }

            item { Text("NVIDIA agent", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
            item {
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it; saved = false; testNvidiaResult = "" },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("NVIDIA API key") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    visualTransformation = if (keyVisible) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { keyVisible = !keyVisible }) {
                            Icon(if (keyVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility, null)
                        }
                    },
                )
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedButton(
                        onClick = {
                            if (apiKey.isBlank()) {
                                testNvidiaResult = "Enter an NVIDIA API key first."
                                return@OutlinedButton
                            }
                            isTestingNvidia = true
                            testNvidiaResult = "Testing connection..."
                            coroutineScope.launch {
                                val (ok, msg) = com.personal.harmaai.network.NvidiaAgentClient.testConnection(apiKey)
                                isTestingNvidia = false
                                testNvidiaResult = msg
                            }
                        },
                        enabled = !isTestingNvidia,
                    ) {
                        Text(if (isTestingNvidia) "Testing..." else "Test Connection")
                    }
                    if (testNvidiaResult.isNotBlank()) {
                        Text(
                            testNvidiaResult,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (testNvidiaResult.contains("success")) HarmaGreen else HarmaRed,
                            modifier = Modifier.padding(start = 8.dp),
                        )
                    }
                }
            }
            item {
                Text(
                    "Stored only in Android encrypted settings and never bundled into the APK.",
                    color = HarmaMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            item { SettingField("Fast model (actions & simple steps)", fastModel) { fastModel = it; saved = false } }
            item { SettingField("Smart model (complex planning & vision)", smartModel) { smartModel = it; saved = false } }
            item { SettingField("Active model override", primaryModel) { primaryModel = it; saved = false } }
            item {
                OutlinedTextField(
                    value = fallbackModels,
                    onValueChange = { fallbackModels = it; saved = false },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Fallback models, one per line") },
                    minLines = 2,
                )
            }
            item { SettingField("Maximum agent steps (1–50)", maxSteps) { maxSteps = it; saved = false } }
            item { SettingField("UI settle delay in milliseconds", delayMs) { delayMs = it; saved = false } }
            item { ToggleSetting("Confirm calls, messages, and payments before executing", confirmations) { confirmations = it; saved = false } }
            item { ToggleSetting("Auto-send messages without confirmation (advanced)", autoSend) { autoSend = it; saved = false } }
            item { ToggleSetting("Screenshot vision fallback", vision) { vision = it; saved = false } }
            item { ToggleSetting("Speak completed results (TTS voice)", tts) { tts = it; saved = false } }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Speech Rate: ${String.format(java.util.Locale.US, "%.1fx", speechRate)}", fontWeight = FontWeight.SemiBold)
                    Slider(
                        value = speechRate,
                        onValueChange = { speechRate = it; saved = false },
                        valueRange = 0.5f..2.0f,
                        steps = 15,
                    )
                }
            }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Speech Pitch: ${String.format(java.util.Locale.US, "%.1fx", speechPitch)}", fontWeight = FontWeight.SemiBold)
                    Slider(
                        value = speechPitch,
                        onValueChange = { speechPitch = it; saved = false },
                        valueRange = 0.5f..2.0f,
                        steps = 15,
                    )
                }
            }
            item { ToggleSetting("Conversation mode (keep listening 6s after reply)", conversationMode) { conversationMode = it; saved = false } }
            item { SettingField("Allowed apps (optional, comma-separated)", allowedApps) { allowedApps = it; saved = false } }
            item { SettingField("Denied apps (comma-separated)", deniedApps) { deniedApps = it; saved = false } }
            item {
                Text(
                    "Voice Control & Groq Whisper",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(top = 10.dp),
                )
            }
            item {
                OutlinedTextField(
                    value = groqApiKey,
                    onValueChange = { groqApiKey = it; saved = false },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Groq API key") },
                    placeholder = { Text("gsk_...") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    visualTransformation = if (groqKeyVisible) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { groqKeyVisible = !groqKeyVisible }) {
                            Icon(if (groqKeyVisible) Icons.Default.VisibilityOff else Icons.Default.Visibility, null)
                        }
                    },
                )
            }
            item {
                Text(
                    "Enables ultra-fast (~300ms) voice understanding with Groq Whisper. Stored in encrypted settings.",
                    color = HarmaMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            item { SettingField("Groq Whisper model", groqModel) { groqModel = it; saved = false } }
            item {
                SettingField("Speech language (en, ta, hi, or auto)", whisperLanguage) {
                    whisperLanguage = it
                    saved = false
                }
            }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        "Wake word threshold: ${String.format(java.util.Locale.US, "%.2f", wakeWordThreshold)}",
                        fontWeight = FontWeight.SemiBold,
                    )
                    Slider(
                        value = wakeWordThreshold,
                        onValueChange = { wakeWordThreshold = it; saved = false },
                        valueRange = 0.3f..0.9f,
                        steps = 12,
                    )
                    Text(
                        "Lower values make 'Hey Harma' easier to trigger; higher values reduce false triggers. Default is 0.50.",
                        color = HarmaMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            item {
                ToggleSetting("Always listen for 'Hey Harma' (Hands-free agent)", alwaysListen) {
                    alwaysListen = it
                    saved = false
                }
            }
            item {
                Text(
                    "When enabled, openWakeWord runs on-device in the background. No audio is ever sent to the cloud while waiting for the wake word. The microphone indicator remains visible.",
                    color = HarmaMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = {
                            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                                testVoiceResult = "Please allow microphone permission first."
                                showTestVoiceDialog = true
                                return@OutlinedButton
                            }
                            if (groqApiKey.isBlank()) {
                                testVoiceResult = "Add a Groq API key in the field above first."
                                showTestVoiceDialog = true
                                return@OutlinedButton
                            }
                            isTestingVoice = true
                            testVoiceResult = "Recording 5 seconds... Speak your test command!"
                            showTestVoiceDialog = true
                            coroutineScope.launch {
                                val detector = VoiceActivityDetector(context)
                                val file = detector.recordSpeechWithVad()
                                if (file != null && file.length() > 0) {
                                    testVoiceResult = "Transcribing with Groq Whisper ($groqModel)..."
                                    val res = GroqWhisperClient().transcribe(
                                        audioFile = file,
                                        apiKey = groqApiKey,
                                        model = groqModel,
                                        language = whisperLanguage,
                                    )
                                    file.delete()
                                    testVoiceResult = res.getOrElse { "Transcription error: ${it.message}" }
                                } else {
                                    testVoiceResult = "No speech detected during the 5-second test."
                                }
                                isTestingVoice = false
                            }
                        },
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Default.Mic, null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.size(6.dp))
                        Text(if (isTestingVoice) "Testing..." else "Test Voice")
                    }

                    OutlinedButton(
                        onClick = {
                            showTestWakeWordDialog = true
                            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                                HarmaVoiceService.start(context)
                            }
                        },
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Default.Hearing, null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.size(6.dp))
                        Text("Test Wake Word")
                    }
                }
            }
            item {
                Button(
                    onClick = {
                        settings.apiKey = apiKey
                        settings.fastModel = fastModel
                        settings.smartModel = smartModel
                        settings.primaryModel = primaryModel
                        settings.fallbackModels = fallbackModels.split('\n', ',', ';')
                        settings.groqApiKey = groqApiKey
                        settings.groqWhisperModel = groqModel
                        settings.alwaysListenEnabled = alwaysListen
                        settings.wakeWordThreshold = wakeWordThreshold
                        settings.whisperLanguage = whisperLanguage
                        settings.maxSteps = maxSteps.toIntOrNull() ?: SettingsStore.DEFAULT_MAX_STEPS
                        settings.stepDelayMs = delayMs.toLongOrNull() ?: SettingsStore.DEFAULT_STEP_DELAY_MS
                        settings.confirmationsEnabled = confirmations
                        settings.autoSendWithoutConfirmation = autoSend
                        settings.speechRate = speechRate
                        settings.speechPitch = speechPitch
                        settings.conversationMode = conversationMode
                        settings.visionEnabled = vision
                        settings.ttsEnabled = tts
                        settings.allowedApps = allowedApps.split(',').map(String::trim).filter(String::isNotBlank).toSet()
                        settings.deniedApps = deniedApps.split(',').map(String::trim).filter(String::isNotBlank).toSet()

                        if (alwaysListen) {
                            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                                HarmaVoiceService.start(context)
                            }
                        } else {
                            HarmaVoiceService.stop(context)
                        }

                        saved = true
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Save Harma AI settings") }
            }
            if (saved) item { Text("Settings saved securely.", color = HarmaGreen) }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }

    if (showTestVoiceDialog) {
        AlertDialog(
            onDismissRequest = { if (!isTestingVoice) showTestVoiceDialog = false },
            title = { Text("Groq Whisper Test") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (isTestingVoice) {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    }
                    Text(testVoiceResult, style = MaterialTheme.typography.bodyLarge)
                }
            },
            confirmButton = {
                TextButton(onClick = { showTestVoiceDialog = false }, enabled = !isTestingVoice) { Text("OK") }
            },
        )
    }

    if (showTestWakeWordDialog) {
        val runtimeState by AgentRuntime.state.collectAsStateWithLifecycle()
        AlertDialog(
            onDismissRequest = { showTestWakeWordDialog = false },
            title = { Text("openWakeWord Live Meter") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Model: openWakeWord on-device ONNX", style = MaterialTheme.typography.bodySmall, color = HarmaMuted)
                    Text("Say 'Hey Harma' to see the live score:", style = MaterialTheme.typography.bodyMedium)
                    LinearProgressIndicator(
                        progress = { runtimeState.liveWakeWordScore.coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth().height(14.dp).clip(RoundedCornerShape(7.dp)),
                        color = if (runtimeState.liveWakeWordScore >= wakeWordThreshold) HarmaGreen else MaterialTheme.colorScheme.primary,
                    )
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(
                            "Live Score: ${String.format(java.util.Locale.US, "%.2f", runtimeState.liveWakeWordScore)}",
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "Threshold: ${String.format(java.util.Locale.US, "%.2f", wakeWordThreshold)}",
                            color = HarmaAmber,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Text(
                        "Triggers when 2 consecutive frames cross the threshold. Cooldown: 2 seconds.",
                        style = MaterialTheme.typography.bodySmall,
                        color = HarmaMuted,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = { showTestWakeWordDialog = false }) { Text("Close") }
            },
        )
    }
}

@Composable
private fun SettingField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, onChange, modifier = Modifier.fillMaxWidth(), label = { Text(label) })
}

@Composable
private fun ToggleSetting(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().border(1.dp, HarmaBorder, RoundedCornerShape(12.dp)).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChecked)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HistoryScreen(viewModel: HarmaViewModel, onBack: () -> Unit) {
    val tasks by viewModel.recentTasks.collectAsStateWithLifecycle()
    Scaffold(topBar = { SimpleBackBar("Harma AI history", onBack) }) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (tasks.isEmpty()) item { Text("No tasks recorded yet.", color = HarmaMuted) }
            items(tasks, key = TaskEntity::id) { task ->
                Card(colors = CardDefaults.cardColors(containerColor = HarmaCard)) {
                    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(task.command, fontWeight = FontWeight.SemiBold)
                        Text(task.status, color = if (task.status == AgentStatus.COMPLETED.name) HarmaGreen else HarmaAmber)
                        task.summary?.takeIf(String::isNotBlank)?.let { Text(it, color = HarmaMuted) }
                        Text(DateFormat.getDateTimeInstance().format(Date(task.startedAt)), style = MaterialTheme.typography.labelSmall, color = HarmaMuted)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SimpleBackBar(title: String, onBack: () -> Unit) {
    TopAppBar(
        title = { Text(title, fontWeight = FontWeight.SemiBold) },
        navigationIcon = {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
    )
}

private fun runtimeGranted(snapshot: PermissionSnapshot): Boolean = snapshot.microphone && snapshot.notifications

private fun stateLabel(status: AgentStatus, step: String): String = when (status) {
    AgentStatus.IDLE -> "Ready for a task"
    AgentStatus.RUNNING -> step
    AgentStatus.WAITING_FOR_CONFIRMATION -> "Waiting for confirmation"
    AgentStatus.WAITING_FOR_USER -> "Waiting for your answer"
    AgentStatus.COMPLETED -> "Task completed"
    AgentStatus.FAILED -> "Task failed"
    AgentStatus.STOPPED -> "Stopped"
}

private fun statusColor(status: AgentStatus) = when (status) {
    AgentStatus.IDLE, AgentStatus.COMPLETED -> HarmaGreen
    AgentStatus.RUNNING, AgentStatus.WAITING_FOR_CONFIRMATION, AgentStatus.WAITING_FOR_USER -> HarmaAmber
    AgentStatus.FAILED, AgentStatus.STOPPED -> HarmaRed
}
