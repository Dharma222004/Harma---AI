package com.personal.harmaai.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.personal.harmaai.HarmaAiApplication
import com.personal.harmaai.MainActivity
import com.personal.harmaai.R
import com.personal.harmaai.agent.AgentOrchestrator
import com.personal.harmaai.agent.AgentRuntime
import com.personal.harmaai.agent.AgentStatus
import com.personal.harmaai.voice.TtsController
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class HarmaAgentService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var taskJob: Job? = null
    private var stateJob: Job? = null
    private var overlay: FloatingStopOverlay? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var tts: TtsController? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        tts = TtsController(this)
        overlay = FloatingStopOverlay(this) { stopCurrentTask() }
        stateJob = serviceScope.launch {
            AgentRuntime.state.collectLatest { state ->
                val line = if (state.status == AgentStatus.RUNNING) {
                    "Step ${state.stepNumber}: ${state.currentStep}"
                } else {
                    state.currentStep
                }
                overlay?.update("Harma AI • $line")
                if (taskJob?.isActive == true) {
                    val manager = getSystemService(NotificationManager::class.java)
                    manager.notify(NOTIFICATION_ID, buildNotification(line))
                }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopCurrentTask()
            ACTION_START -> {
                val command = intent.getStringExtra(EXTRA_COMMAND).orEmpty().trim()
                val sessionId = intent.getStringExtra(EXTRA_SESSION_ID).orEmpty().ifBlank { command }
                if (command.isNotBlank()) startTask(command, sessionId)
            }
        }
        return START_NOT_STICKY
    }

    private fun startTask(command: String, sessionId: String = "") {
        taskJob?.cancel()
        startForeground(NOTIFICATION_ID, buildNotification("Starting task"))
        overlay?.show("Harma AI • Starting task")
        acquireWakeLock()
        val app = application as HarmaAiApplication
        taskJob = serviceScope.launch(Dispatchers.IO) {
            val orchestrator = AgentOrchestrator(
                context = this@HarmaAgentService,
                settings = app.settings,
                database = app.database,
            )
            orchestrator.run(command, sessionId)
            withContext(Dispatchers.Main) {
                val state = AgentRuntime.state.value
                if (app.settings.ttsEnabled && state.status == AgentStatus.COMPLETED) {
                    val spoken = state.messages.lastOrNull()?.text?.let { message ->
                        tts?.speak(message) { finishServiceRun() }
                    } == true
                    if (!spoken) finishServiceRun()
                } else {
                    finishServiceRun()
                }
            }
        }
    }

    private fun stopCurrentTask() {
        taskJob?.cancel()
        taskJob = null
        AgentRuntime.stop()
        finishServiceRun()
    }

    private fun finishServiceRun() {
        releaseWakeLock()
        overlay?.hide()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun acquireWakeLock() {
        releaseWakeLock()
        val manager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HarmaAI:AgentTask").apply {
            setReferenceCounted(false)
            acquire(15 * 60 * 1000L)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Harma AI agent",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Shows the current Harma AI phone action and emergency stop control."
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
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, HarmaAgentService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Harma AI is acting")
            .setContentText(status)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(0, "STOP", stopIntent)
            .build()
    }

    override fun onDestroy() {
        taskJob?.cancel()
        stateJob?.cancel()
        releaseWakeLock()
        overlay?.hide()
        tts?.shutdown()
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL_ID = "harma_agent_runtime"
        private const val NOTIFICATION_ID = 4101
        private const val ACTION_START = "com.personal.harmaai.action.START_TASK"
        private const val ACTION_STOP = "com.personal.harmaai.action.STOP_TASK"
        private const val EXTRA_COMMAND = "command"
        private const val EXTRA_SESSION_ID = "session_id"

        fun startTask(context: Context, command: String, sessionId: String = "") {
            val intent = Intent(context, HarmaAgentService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_COMMAND, command)
                .putExtra(EXTRA_SESSION_ID, sessionId)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stopTask(context: Context) {
            context.startService(
                Intent(context, HarmaAgentService::class.java).setAction(ACTION_STOP),
            )
        }
    }
}
