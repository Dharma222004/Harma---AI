package com.personal.harmaai.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.IBinder
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.personal.harmaai.HarmaAiApplication
import com.personal.harmaai.MainActivity
import com.personal.harmaai.R
import com.personal.harmaai.agent.AgentRuntime
import com.personal.harmaai.agent.AgentStatus
import com.personal.harmaai.network.NetworkMonitor
import com.personal.harmaai.network.NvidiaAgentClient
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.service.HarmaAgentService
import com.personal.harmaai.voice.wakeword.WakeWordListener
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

class HarmaVoiceService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var wakeWordListener: WakeWordListener? = null
    private val groqClient = GroqWhisperClient()
    private var offlineSttEngine: OfflineSttEngine? = null

    private var audioManager: AudioManager? = null
    private var audioFocusRequest: AudioFocusRequest? = null
    private var toneGenerator: ToneGenerator? = null

    private var speechCaptureJob: Job? = null
    private var agentObserverJob: Job? = null

    private val isPausedByCallOrFocus = AtomicBoolean(false)
    private val isUserPaused = AtomicBoolean(false)
    private val isCapturingSpeech = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        audioManager = getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        offlineSttEngine = OfflineSttEngine(this, groqClient)

        try {
            toneGenerator = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 90)
        } catch (_: Exception) {}

        setupAudioFocus()
        initWakeWordListener()
        observeAgentState()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopVoiceService()
            ACTION_TALK_NOW -> startSpeechCaptureDirectly()
            ACTION_PAUSE -> {
                isUserPaused.set(true)
                wakeWordListener?.pause()
                updateNotification("Voice paused by user")
            }
            ACTION_RESUME -> {
                isUserPaused.set(false)
                wakeWordListener?.resume()
                updateNotification("Always listening for 'Hey Harma' (offline-ready)")
            }
            else -> startForegroundVoiceService()
        }
        return START_STICKY
    }

    private fun startForegroundVoiceService() {
        val notification = buildNotification("Always listening for 'Hey Harma' (offline-ready)")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        val app = application as HarmaAiApplication
        val threshold = app.settings.wakeWordThreshold
        wakeWordListener?.start(serviceScope, threshold)
    }

    private fun initWakeWordListener() {
        wakeWordListener = WakeWordListener(
            context = this,
            onWakeWordDetected = { modelName ->
                Log.i(TAG, "Wake word detected via $modelName. Triggering speech capture.")
                HarmaPerf.onWakeWordDetected(modelName)
                val app = application as HarmaAiApplication
                if (NetworkMonitor.isCurrentlyOnline(this)) {
                    groqClient.preWarm(app.settings.groqApiKey)
                    NvidiaAgentClient.preWarm(app.settings.apiKey)
                }
                onWakeWordFired()
            },
            onScoreUpdate = { score, threshold ->
                AgentRuntime.setLiveWakeWordScore(score, threshold)
            },
        )
    }

    private fun onWakeWordFired() {
        if (isCapturingSpeech.get()) return
        // 1. Audio and haptic feedback (Stay over current foreground app so Harma can control it!)
        playBeepAndVibrate()
        // 2. Start offline-first speech capture
        startSpeechCapture()
    }

    private fun startSpeechCaptureDirectly() {
        if (isCapturingSpeech.get()) return
        playBeepAndVibrate()
        startSpeechCapture()
    }

    private fun startSpeechCapture() {
        speechCaptureJob?.cancel()
        speechCaptureJob = serviceScope.launch {
            val sessionId = "voice_${System.currentTimeMillis()}"
            isCapturingSpeech.set(true)
            wakeWordListener?.pause()

            val online = NetworkMonitor.isCurrentlyOnline(this@HarmaVoiceService)
            val modeLabel = if (online) "Listening..." else "Listening (Offline)..."
            AgentRuntime.setVoiceListening(true, modeLabel)
            updateNotification(modeLabel)
            HarmaPerf.onSpeechRecordStart(sessionId)

            val app = application as HarmaAiApplication
            val stt = offlineSttEngine ?: OfflineSttEngine(this@HarmaVoiceService, groqClient)
            val result = stt.listenAndTranscribe(
                languageTag = app.settings.whisperLanguage.ifBlank { "en-US" },
                groqApiKey = app.settings.groqApiKey,
                groqModel = app.settings.groqWhisperModel,
                sessionId = sessionId,
                onPartial = { partial ->
                    AgentRuntime.setVoiceListening(true, "\"$partial\"")
                },
            )

            HarmaPerf.onSpeechRecordStop(sessionId)
            AgentRuntime.setVoiceListening(false)

            result.onSuccess { rawTranscript ->
                val clean = stripWakePrefix(rawTranscript.trim())
                Log.i(TAG, "Transcript received: \"$clean\" (raw: \"$rawTranscript\")")

                if (clean.isBlank()) {
                    AgentRuntime.addSystemMessage("Didn't catch that. Say 'Hey Harma' to try again.")
                } else if (isVoiceStopCommand(clean)) {
                    Log.i(TAG, "Voice stop command detected: \"$clean\"")
                    HarmaAgentService.stopTask(this@HarmaVoiceService)
                    AgentRuntime.addSystemMessage("Task stopped by voice command.")
                } else {
                    playResultConfirmBeep()
                    AgentRuntime.addVoiceUserMessage(clean)
                    HarmaAgentService.startTask(this@HarmaVoiceService, clean, sessionId)
                }
            }.onFailure { error ->
                Log.e(TAG, "Speech transcription failed: ${error.message}")
                AgentRuntime.addSystemMessage("Voice recognition: ${error.message ?: "Could not transcribe audio"}")
            }

            resumeWakeWordIfAppropriate()
        }
    }

    private fun stripWakePrefix(text: String): String {
        return text
            .replace(Regex("^(?i)(hey\\s+harma|hi\\s+harma|ok\\s+harma|hey\\s+jarvis)[,\\s]*"), "")
            .trim()
    }

    private fun isVoiceStopCommand(text: String): Boolean {
        val lower = text.lowercase().trim()
        return lower == "stop" ||
            lower == "cancel" ||
            lower == "hey harma stop" ||
            lower == "hey harma cancel" ||
            lower == "harma stop" ||
            lower.startsWith("stop ") ||
            lower.endsWith(" stop")
    }

    private fun resumeWakeWordIfAppropriate() {
        isCapturingSpeech.set(false)
        if (isUserPaused.get() || isPausedByCallOrFocus.get()) {
            return
        }

        serviceScope.launch {
            while (AgentRuntime.state.value.status == AgentStatus.RUNNING || isTtsSpeaking) {
                delay(800L)
            }
            delay(1200L)
            val app = application as HarmaAiApplication
            if (app.settings.conversationMode && !isUserPaused.get() && !isPausedByCallOrFocus.get() && !isCapturingSpeech.get()) {
                Log.i(TAG, "Conversation mode active: listening for follow-up")
                startSpeechCapture()
                return@launch
            }
            if (!isUserPaused.get() && !isPausedByCallOrFocus.get() && !isCapturingSpeech.get()) {
                wakeWordListener?.threshold = app.settings.wakeWordThreshold
                wakeWordListener?.resume()
                updateNotification("Always listening for 'Hey Harma' (offline-ready)")
            }
        }
    }

    private fun observeAgentState() {
        agentObserverJob = serviceScope.launch {
            AgentRuntime.state.collectLatest { state ->
                if (state.status == AgentStatus.RUNNING) {
                    wakeWordListener?.pause()
                } else if (state.status == AgentStatus.COMPLETED || state.status == AgentStatus.STOPPED || state.status == AgentStatus.FAILED) {
                    resumeWakeWordIfAppropriate()
                }
            }
        }
    }

    private fun playBeepAndVibrate() {
        try {
            toneGenerator?.startTone(ToneGenerator.TONE_PROP_BEEP, 130)
        } catch (_: Exception) {}

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val manager = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                manager?.defaultVibrator?.vibrate(
                    VibrationEffect.createOneShot(120L, VibrationEffect.DEFAULT_AMPLITUDE),
                )
            } else {
                @Suppress("DEPRECATION")
                val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
                vibrator?.vibrate(
                    VibrationEffect.createOneShot(120L, VibrationEffect.DEFAULT_AMPLITUDE),
                )
            }
        } catch (_: Exception) {}
    }

    private fun playResultConfirmBeep() {
        try {
            toneGenerator?.startTone(ToneGenerator.TONE_PROP_ACK, 90)
        } catch (_: Exception) {}
    }

    private fun setupAudioFocus() {
        val am = audioManager ?: return
        val focusListener = AudioManager.OnAudioFocusChangeListener { focusChange ->
            when (focusChange) {
                AudioManager.AUDIOFOCUS_LOSS,
                AudioManager.AUDIOFOCUS_LOSS_TRANSIENT,
                -> {
                    Log.i(TAG, "Audio focus lost or call active. Pausing wake-word listener.")
                    isPausedByCallOrFocus.set(true)
                    wakeWordListener?.pause()
                    updateNotification("Voice paused (call or audio active)")
                }
                AudioManager.AUDIOFOCUS_GAIN -> {
                    Log.i(TAG, "Audio focus regained. Resuming wake-word listener.")
                    isPausedByCallOrFocus.set(false)
                    resumeWakeWordIfAppropriate()
                }
            }
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val playbackAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()

            audioFocusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(playbackAttributes)
                .setAcceptsDelayedFocusGain(true)
                .setOnAudioFocusChangeListener(focusListener)
                .build()

            am.requestAudioFocus(audioFocusRequest!!)
        } else {
            @Suppress("DEPRECATION")
            am.requestAudioFocus(
                focusListener,
                AudioManager.STREAM_NOTIFICATION,
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK,
            )
        }
    }

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Harma AI voice listener",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Keeps Harma AI listening for the 'Hey Harma' wake word hands-free."
                setShowBadge(false)
            },
        )
    }

    private fun buildNotification(status: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val talkNowIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, HarmaVoiceService::class.java).setAction(ACTION_TALK_NOW),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val pauseResumeIntent = PendingIntent.getService(
            this,
            2,
            Intent(this, HarmaVoiceService::class.java).setAction(
                if (isUserPaused.get()) ACTION_RESUME else ACTION_PAUSE,
            ),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            3,
            Intent(this, HarmaVoiceService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val pauseLabel = if (isUserPaused.get()) "Resume" else "Pause"

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Harma AI Voice")
            .setContentText(status)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(0, "Talk Now", talkNowIntent)
            .addAction(0, pauseLabel, pauseResumeIntent)
            .addAction(0, "Stop", stopIntent)
            .build()
    }

    private fun updateNotification(status: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(status))
    }

    private fun stopVoiceService() {
        wakeWordListener?.stop()
        wakeWordListener?.release()
        wakeWordListener = null

        speechCaptureJob?.cancel()
        agentObserverJob?.cancel()

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && audioFocusRequest != null) {
                audioManager?.abandonAudioFocusRequest(audioFocusRequest!!)
            }
            toneGenerator?.release()
            toneGenerator = null
        } catch (_: Exception) {}

        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopVoiceService()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val TAG = "HarmaWake"
        private const val CHANNEL_ID = "harma_ai_voice_channel"
        private const val NOTIFICATION_ID = 2002

        const val ACTION_START = "com.personal.harmaai.voice.START"
        const val ACTION_STOP = "com.personal.harmaai.voice.STOP"
        const val ACTION_TALK_NOW = "com.personal.harmaai.voice.TALK_NOW"
        const val ACTION_PAUSE = "com.personal.harmaai.voice.PAUSE"
        const val ACTION_RESUME = "com.personal.harmaai.voice.RESUME"

        @Volatile
        var isTtsSpeaking = false

        fun start(context: Context) {
            val intent = Intent(context, HarmaVoiceService::class.java).setAction(ACTION_START)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, HarmaVoiceService::class.java).setAction(ACTION_STOP)
            context.startService(intent)
        }

        fun triggerTalkNow(context: Context) {
            val intent = Intent(context, HarmaVoiceService::class.java).setAction(ACTION_TALK_NOW)
            ContextCompat.startForegroundService(context, intent)
        }
    }
}
