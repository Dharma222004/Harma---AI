package com.personal.harmaai.agent

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.app.NotificationCompat
import com.personal.harmaai.R
import com.personal.harmaai.data.HarmaDatabase
import com.personal.harmaai.data.QueuedTaskEntity
import com.personal.harmaai.network.NetworkMonitor
import com.personal.harmaai.service.HarmaAgentService
import com.personal.harmaai.voice.TtsController
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Persistent Offline Task Queue (Step 3):
 * - Saves Tier 2 (cloud LLM or online-dependent) commands to Room (`offline_task_queue`) when offline.
 * - Deduplicates identical pending commands and expires stale tasks (>6 hours).
 * - Automatically resumes queued tasks when `NetworkMonitor` reports validated internet is back,
 *   notifying the user via Notification + TTS: "Network is back, continuing your task".
 * - Requires user confirmation before running stale sensitive tasks (e.g., messages, calls, payments
 *   queued >15 minutes ago).
 */
object OfflineTaskQueueManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val isDraining = AtomicBoolean(false)
    private const val CHANNEL_ID = "harma_offline_queue"
    private const val NOTIFICATION_ID = 4205
    private const val STALE_SENSITIVE_THRESHOLD_MS = 15 * 60 * 1000L
    private const val MAX_RETRIES = 2

    private val SENSITIVE_KEYWORDS = Regex(
        "(?i)\\b(send|message|whatsapp|sms|text|call|dial|pay|transfer|delete|remove|uninstall)\\b",
    )

    fun initialize(context: Context, database: HarmaDatabase) {
        val appContext = context.applicationContext
        NetworkMonitor.initialize(appContext)
        NetworkMonitor.addOnReconnectListener {
            drainQueueIfOnline(appContext, database)
        }
        // Also check on app startup if internet is already available and pending tasks exist
        if (NetworkMonitor.isCurrentlyOnline(appContext)) {
            drainQueueIfOnline(appContext, database)
        }
    }

    suspend fun enqueueOfflineTask(
        context: Context,
        database: HarmaDatabase,
        command: String,
    ): QueuedTaskEntity {
        val clean = command.trim()
        val dao = database.queuedTaskDao()
        dao.expireStale()

        val existing = dao.findDuplicatePending(clean)
        if (existing != null) {
            return existing
        }

        val entry = QueuedTaskEntity(
            id = UUID.randomUUID().toString(),
            command = clean,
            status = QueuedTaskEntity.STATUS_PENDING,
            retryCount = 0,
            isSensitive = isSensitiveCommand(clean),
        )
        dao.upsert(entry)
        postQueueNotification(
            context = context.applicationContext,
            title = "Harma AI • Saved for when online",
            body = "Offline right now. Queued: \"$clean\" — will run automatically when internet returns.",
        )
        return entry
    }

    fun drainQueueIfOnline(context: Context, database: HarmaDatabase) {
        val appContext = context.applicationContext
        if (!NetworkMonitor.isCurrentlyOnline(appContext)) return
        if (!isDraining.compareAndSet(false, true)) return

        scope.launch {
            try {
                val dao = database.queuedTaskDao()
                dao.expireStale()
                val pending = dao.getPendingValid()
                if (pending.isEmpty()) return@launch

                for (task in pending) {
                    if (!NetworkMonitor.isCurrentlyOnline(appContext)) break
                    if (task.retryCount > MAX_RETRIES) {
                        dao.updateStatus(task.id, QueuedTaskEntity.STATUS_FAILED, task.retryCount)
                        continue
                    }

                    // Wait if another task is currently running
                    while (AgentRuntime.state.value.status == AgentStatus.RUNNING) {
                        delay(1_000L)
                    }

                    val ageMs = System.currentTimeMillis() - task.createdAt
                    val resumeAnnouncement = "Network is back, continuing your task: ${task.command}"
                    AgentRuntime.addSystemMessage(resumeAnnouncement)
                    postQueueNotification(
                        context = appContext,
                        title = "Network is back, continuing your task",
                        body = "Running queued command: \"${task.command}\"",
                    )
                    speakAnnouncement(appContext, "Network is back, continuing your task.")

                    if (task.isSensitive && ageMs > STALE_SENSITIVE_THRESHOLD_MS) {
                        val approved = AgentRuntime.requestConfirmation(
                            toolName = "queued_offline_task",
                            description = "Run queued task from ${ageMs / 60000} min ago: \"${task.command}\"?",
                            arguments = task.command,
                        )
                        if (!approved) {
                            dao.updateStatus(task.id, QueuedTaskEntity.STATUS_CANCELLED, task.retryCount)
                            continue
                        }
                    }

                    dao.updateStatus(task.id, QueuedTaskEntity.STATUS_RUNNING, task.retryCount + 1)
                    HarmaAgentService.startTask(appContext, task.command, "queued_${task.id}")
                    delay(1_500L)
                    while (AgentRuntime.state.value.status == AgentStatus.RUNNING) {
                        delay(800L)
                    }

                    val finalStatus = AgentRuntime.state.value.status
                    if (finalStatus == AgentStatus.COMPLETED) {
                        dao.updateStatus(task.id, QueuedTaskEntity.STATUS_COMPLETED, task.retryCount + 1)
                    } else if (!NetworkMonitor.isCurrentlyOnline(appContext)) {
                        // Network dropped again mid-run; keep PENDING for next reconnect
                        dao.updateStatus(task.id, QueuedTaskEntity.STATUS_PENDING, task.retryCount + 1)
                        break
                    } else {
                        dao.updateStatus(task.id, QueuedTaskEntity.STATUS_FAILED, task.retryCount + 1)
                    }
                }
            } finally {
                isDraining.set(false)
            }
        }
    }

    fun isSensitiveCommand(command: String): Boolean =
        SENSITIVE_KEYWORDS.containsMatchIn(command)

    private fun speakAnnouncement(context: Context, message: String) {
        runCatching {
            val tts = TtsController(context)
            tts.speak(message) {
                tts.shutdown()
            }
        }
    }

    private fun postQueueNotification(context: Context, title: String, body: String) {
        runCatching {
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Harma AI Offline Task Queue",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "Notifies when offline tasks are queued or automatically resumed."
                },
            )
            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .build()
            manager.notify(NOTIFICATION_ID, notification)
        }
    }
}
