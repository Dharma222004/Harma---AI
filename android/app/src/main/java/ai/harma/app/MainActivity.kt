package ai.harma.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import ai.harma.app.data.model.*
import ai.harma.app.device.AccessibilityHelper
import ai.harma.app.ui.HarmaNavGraph
import ai.harma.app.ui.screens.ConfirmationDialog
import ai.harma.app.ui.theme.HarmaBlack
import ai.harma.app.ui.theme.HarmaTheme
import ai.harma.app.voice.SpeechRecognizerHelper
import ai.harma.app.voice.TtsHelper
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private lateinit var app: HarmaApplication
    private lateinit var speechHelper: SpeechRecognizerHelper
    private lateinit var ttsHelper: TtsHelper

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        lifecycleScope.launch {
            app.repository.registerDevice(permissions)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        app = application as HarmaApplication

        setupVoiceEngine()
        requestInitialPermissions()

        setContent {
            HarmaTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = HarmaBlack
                ) {
                    val voiceState by app.repository.voiceState.collectAsState()
                    val connectionState by app.repository.connectionState.collectAsState()
                    val messages by app.repository.messages.collectAsState()
                    val steps by app.repository.executionSteps.collectAsState()
                    val confirmation by app.repository.activeConfirmation.collectAsState()

                    HarmaNavGraph(
                        voiceState = voiceState,
                        connectionState = connectionState,
                        messages = messages,
                        executionSteps = steps,
                        securePrefs = app.securePreferences,
                        onMicClick = { triggerVoiceListening() },
                        onSendMessage = { prompt -> processUserRequest(prompt) },
                        onUrlUpdated = { newUrl -> app.repository.updateBaseUrl(newUrl) }
                    )

                    // Consequential Action Confirmation Dialog
                    confirmation?.let { conf ->
                        ConfirmationDialog(
                            info = conf,
                            onConfirm = {
                                lifecycleScope.launch {
                                    app.repository.respondConfirmation(conf.confirmation_id, approved = true)
                                    resumeConfirmedAction(conf)
                                }
                            },
                            onCancel = {
                                lifecycleScope.launch {
                                    app.repository.respondConfirmation(conf.confirmation_id, approved = false)
                                    app.repository.addExecutionStep("Action cancelled by user.")
                                    ttsHelper.speak("Action cancelled.")
                                }
                            }
                        )
                    }
                }
            }
        }
    }

    private fun setupVoiceEngine() {
        speechHelper = SpeechRecognizerHelper(this).apply {
            onWakeWordDetected = {
                app.repository.setVoiceState(VoiceState.WAKE_DETECTED)
            }
            onCommandRecognized = { command ->
                app.repository.setVoiceState(VoiceState.TRANSCRIBING)
                processUserRequest(command)
            }
            onErrorOccurred = { error ->
                app.repository.setVoiceState(VoiceState.ERROR)
            }
        }

        ttsHelper = TtsHelper(this) { success ->
            // TTS initialized
        }
    }

    private fun requestInitialPermissions() {
        val permissions = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.RECORD_AUDIO)
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.CAMERA)
        }
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                permissions.add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        if (permissions.isNotEmpty()) {
            permissionLauncher.launch(permissions.toTypedArray())
        } else {
            lifecycleScope.launch {
                app.repository.registerDevice()
            }
        }
    }

    private fun triggerVoiceListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionLauncher.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
            return
        }
        app.repository.setVoiceState(VoiceState.LISTENING)
        speechHelper.startListening()
    }

    private fun processUserRequest(prompt: String) {
        if (prompt.isBlank()) return

        app.repository.addMessage(
            ConversationMessage(text = prompt, isFromUser = true)
        )
        app.repository.clearExecutionSteps()
        app.repository.setVoiceState(VoiceState.UNDERSTANDING)

        lifecycleScope.launch {
            val lower = prompt.lowercase().trim()

            // 1. Device Specific Capability: Flashlight
            if (lower.contains("flashlight") || lower.contains("torch")) {
                val enable = !lower.contains("off")
                app.repository.setVoiceState(VoiceState.EXECUTING)
                app.repository.addExecutionStep(if (enable) "Turning on flashlight..." else "Turning off flashlight...")

                val step = PlanStep(
                    step_id = "torch_1",
                    capability = "FLASHLIGHT",
                    action = "SET_TORCH",
                    parameters = mapOf("enable" to enable),
                    description = "Control hardware flashlight"
                )
                val res = app.capabilityDispatcher.executeStep(step)
                app.repository.addExecutionStep(res.message)
                app.repository.addMessage(
                    ConversationMessage(text = res.message, isFromUser = false, executionSteps = listOf(res.message))
                )
                app.repository.reportActionResult("torch_task", "FLASHLIGHT", res.status.name, res.message)
                app.repository.setVoiceState(VoiceState.SPEAKING)
                ttsHelper.speak(res.message)
                return@launch
            }

            // 2. Device Specific Capability: WhatsApp Send
            if (lower.contains("whatsapp") || (lower.contains("send") && lower.contains("to"))) {
                executeWhatsAppVoiceFlow(prompt)
                return@launch
            }

            // 3. Cloud Harma Runtime Execution
            val response = app.repository.sendChat(prompt)
            if (response != null) {
                app.repository.addMessage(
                    ConversationMessage(text = response.response, isFromUser = false)
                )
                app.repository.setVoiceState(VoiceState.SPEAKING)
                ttsHelper.speak(response.response)
            } else {
                val errorMsg = "Unable to connect to Harma Cloud at ${app.securePreferences.baseUrl}. Check network or server configuration."
                app.repository.addMessage(
                    ConversationMessage(text = errorMsg, isFromUser = false)
                )
                app.repository.setVoiceState(VoiceState.ERROR)
                ttsHelper.speak("Could not reach Harma server.")
            }
        }
    }

    private suspend fun executeWhatsAppVoiceFlow(prompt: String) {
        if (!AccessibilityHelper.isAccessibilityEnabled(this)) {
            val warn = "To let Harma send messages in WhatsApp, Accessibility access must be enabled."
            app.repository.addExecutionStep(warn)
            app.repository.addMessage(ConversationMessage(text = warn, isFromUser = false))
            ttsHelper.speak(warn)
            AccessibilityHelper.openAccessibilitySettings(this)
            return
        }

        // Parse recipient and message
        val recipient = extractRecipient(prompt)
        val message = extractMessage(prompt)

        app.repository.setVoiceState(VoiceState.EXECUTING)
        app.repository.addExecutionStep("Opening WhatsApp...")

        val step = PlanStep(
            step_id = "wa_send_1",
            capability = "WHATSAPP_SEND",
            action = "SEND_MESSAGE",
            parameters = mapOf(
                "recipient" to recipient,
                "message" to message,
                "confirmed" to false
            ),
            description = "Send WhatsApp message to $recipient"
        )

        val res = app.capabilityDispatcher.executeStep(step) { stepUpdate ->
            app.repository.addExecutionStep(stepUpdate)
        }

        if (res.details["requires_confirmation"] == true) {
            // Trigger confirmation dialog
            app.repository.setConfirmation(
                ConfirmationRequiredInfo(
                    confirmation_id = "wa_conf_${System.currentTimeMillis()}",
                    message = "You are about to send \"$message\" to $recipient. Send it?",
                    action_type = "whatsapp_send",
                    target = recipient,
                    payload = mapOf("recipient" to recipient, "message" to message)
                )
            )
            ttsHelper.speak("You are about to send '$message' to $recipient. Send it?")
        } else {
            app.repository.addExecutionStep(res.message)
            app.repository.addMessage(
                ConversationMessage(
                    text = res.message,
                    isFromUser = false,
                    executionSteps = app.repository.executionSteps.value
                )
            )
            app.repository.reportActionResult("wa_task", "WHATSAPP_SEND", res.status.name, res.message)
            app.repository.setVoiceState(VoiceState.SPEAKING)
            ttsHelper.speak(res.message)
        }
    }

    private suspend fun resumeConfirmedAction(conf: ConfirmationRequiredInfo) {
        val recipient = conf.payload["recipient"]?.toString() ?: conf.target
        val message = conf.payload["message"]?.toString() ?: "hi"

        app.repository.setVoiceState(VoiceState.EXECUTING)
        app.repository.addExecutionStep("Confirmed. Completing send to $recipient...")

        val step = PlanStep(
            step_id = "wa_send_confirmed",
            capability = "WHATSAPP_SEND",
            action = "SEND_MESSAGE",
            parameters = mapOf(
                "recipient" to recipient,
                "message" to message,
                "confirmed" to true
            ),
            description = "Confirmed send"
        )

        val res = app.capabilityDispatcher.executeStep(step) { stepUpdate ->
            app.repository.addExecutionStep(stepUpdate)
        }

        app.repository.addExecutionStep(res.message)
        app.repository.addMessage(
            ConversationMessage(
                text = res.message,
                isFromUser = false,
                executionSteps = app.repository.executionSteps.value
            )
        )
        app.repository.reportActionResult("wa_task", "WHATSAPP_SEND", res.status.name, res.message)
        app.repository.setVoiceState(VoiceState.SPEAKING)
        ttsHelper.speak(res.message)
    }

    private fun extractRecipient(prompt: String): String {
        val lower = prompt.lowercase()
        val toIndex = lower.indexOf(" to ")
        if (toIndex != -1) {
            val afterTo = prompt.substring(toIndex + 4).trim()
            val words = afterTo.split(" ")
            return words.firstOrNull()?.replace(Regex("[^A-Za-z0-9]"), "") ?: "Bhuvanesh"
        }
        return "Bhuvanesh"
    }

    private fun extractMessage(prompt: String): String {
        val lower = prompt.lowercase()
        val sendIndex = lower.indexOf("send ")
        val toIndex = lower.indexOf(" to ")

        if (sendIndex != -1 && toIndex != -1 && sendIndex < toIndex) {
            val msg = prompt.substring(sendIndex + 5, toIndex).trim()
            if (msg.isNotEmpty()) return msg
        }
        return "hi"
    }

    override fun onDestroy() {
        super.onDestroy()
        speechHelper.destroy()
        ttsHelper.shutdown()
        app.repository.stopHeartbeat()
    }
}
