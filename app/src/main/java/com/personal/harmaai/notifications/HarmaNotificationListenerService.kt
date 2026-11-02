package com.personal.harmaai.notifications

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.lang.ref.WeakReference
import java.util.ArrayDeque

data class HarmaNotification(
    val key: String,
    val packageName: String,
    val appName: String,
    val title: String,
    val conversationTitle: String = "",
    val text: String,
    val postedAt: Long,
    val canReply: Boolean = false,
    @Transient val replyPendingIntent: PendingIntent? = null,
    @Transient val remoteInputs: Array<RemoteInput>? = null,
    @Transient val markAsReadIntent: PendingIntent? = null,
) {
    val displaySender: String
        get() = when {
            conversationTitle.isNotBlank() && title.isNotBlank() && conversationTitle != title ->
                "$title ($conversationTitle)"
            title.isNotBlank() -> title
            conversationTitle.isNotBlank() -> conversationTitle
            else -> appName
        }
}

data class NotificationReadResult(
    val success: Boolean,
    val summary: String,
    val notifications: List<HarmaNotification>,
    val permissionMissing: Boolean = false,
)

data class NotificationReplyResult(
    val success: Boolean,
    val message: String,
    val sender: String = "",
    val appName: String = "",
    val packageName: String = "",
    val permissionMissing: Boolean = false,
)

/**
 * Captures incoming notifications and extracts actionable Android [RemoteInput] intents
 * from WhatsApp, Telegram, Instagram, Google Messages, Signal, Slack, etc.
 *
 * Enables zero-screen-tapping background message reading and instant voice replies.
 */
class HarmaNotificationListenerService : NotificationListenerService() {

    override fun onListenerConnected() {
        super.onListenerConnected()
        instanceRef = WeakReference(this)
        Log.i(TAG, "HarmaNotificationListenerService connected")
        syncActiveNotifications()
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        if (instanceRef?.get() === this) {
            instanceRef = null
        }
        Log.i(TAG, "HarmaNotificationListenerService disconnected")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null || sbn.packageName == packageName) return
        val parsed = parseStatusBarNotification(sbn) ?: return
        upsertNotification(parsed)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        if (sbn == null) return
        synchronized(recent) {
            // Keep message history for reading, but clear stale PendingIntent if dismissed by user
            val updated = recent.map { item ->
                if (item.key == sbn.key) {
                    item.copy(canReply = false, replyPendingIntent = null, remoteInputs = null)
                } else {
                    item
                }
            }
            recent.clear()
            recent.addAll(updated)
        }
    }

    private fun syncActiveNotifications() {
        val activeList = runCatching { activeNotifications }.getOrNull() ?: return
        for (sbn in activeList) {
            if (sbn.packageName == packageName) continue
            val parsed = parseStatusBarNotification(sbn) ?: continue
            upsertNotification(parsed)
        }
    }

    private fun parseStatusBarNotification(sbn: StatusBarNotification): HarmaNotification? {
        val notif = sbn.notification ?: return null
        if ((notif.flags and Notification.FLAG_GROUP_SUMMARY) != 0) {
            return null
        }

        val extras = notif.extras ?: Bundle.EMPTY
        val rawTitle = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        val rawConversation = extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString()?.trim().orEmpty()
        val rawBigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim().orEmpty()
        val rawText = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        val chosenText = rawBigText.ifBlank { rawText }

        if (rawTitle.isBlank() && chosenText.isBlank()) return null

        val title = sanitize(rawTitle)
        val conversationTitle = sanitize(rawConversation)
        val text = sanitize(chosenText)

        val replyAction = findReplyAction(notif)
        val markAsRead = findMarkAsReadAction(notif)
        val resolvedAppName = resolveAppLabel(this, sbn.packageName)

        return HarmaNotification(
            key = sbn.key ?: "${sbn.packageName}:${sbn.id}:${sbn.postTime}",
            packageName = sbn.packageName,
            appName = resolvedAppName,
            title = title,
            conversationTitle = conversationTitle,
            text = text,
            postedAt = sbn.postTime,
            canReply = replyAction != null && !containsSensitiveOtp(rawTitle, chosenText),
            replyPendingIntent = replyAction?.first,
            remoteInputs = replyAction?.second,
            markAsReadIntent = markAsRead,
        )
    }

    companion object {
        private const val TAG = "HarmaNotifListener"
        private const val MAX_NOTIFICATIONS = 50
        private val recent = ArrayDeque<HarmaNotification>()
        @Volatile
        private var instanceRef: WeakReference<HarmaNotificationListenerService>? = null

        private val sensitive = Regex(
            "(?i)(otp|one.?time password|verification code|security code|pin|password|cvv)[^0-9]{0,12}[0-9]{3,8}",
        )

        private val MESSAGING_PACKAGES = setOf(
            "com.whatsapp",
            "com.whatsapp.w4b",
            "org.telegram.messenger",
            "com.instagram.android",
            "com.google.android.apps.messaging",
            "com.samsung.android.messaging",
            "org.thoughtcrime.securesms",
            "com.facebook.orca",
            "com.Slack",
            "com.discord",
        )

        fun isConnected(): Boolean = instanceRef?.get() != null

        fun isPermissionGranted(context: Context): Boolean {
            val enabledListeners = Settings.Secure.getString(
                context.contentResolver,
                "enabled_notification_listeners",
            ).orEmpty()
            return enabledListeners.contains(context.packageName)
        }

        /**
         * Used by unit tests and simulator to seed notifications cleanly.
         */
        internal fun recordForTest(notification: HarmaNotification) {
            upsertNotification(notification)
        }

        internal fun clearForTest() {
            synchronized(recent) {
                recent.clear()
            }
        }

        private fun upsertNotification(item: HarmaNotification) {
            synchronized(recent) {
                recent.removeAll { existing ->
                    existing.key == item.key ||
                        (existing.packageName == item.packageName &&
                            existing.title.equals(item.title, ignoreCase = true) &&
                            existing.text == item.text)
                }
                recent.addFirst(item)
                while (recent.size > MAX_NOTIFICATIONS) {
                    recent.removeLast()
                }
            }
        }

        private fun findReplyAction(notification: Notification): Pair<PendingIntent, Array<RemoteInput>>? {
            val directActions = notification.actions?.toList().orEmpty()
            val wearableActions = runCatching {
                Notification.WearableExtender(notification).actions
            }.getOrNull().orEmpty()

            val allActions = directActions + wearableActions
            for (action in allActions) {
                val inputs = action.remoteInputs
                val pending = action.actionIntent
                if (pending != null && !inputs.isNullOrEmpty()) {
                    val freeForm = inputs.filter { it.allowFreeFormInput }
                    if (freeForm.isNotEmpty()) {
                        return pending to freeForm.toTypedArray()
                    }
                    return pending to inputs
                }
            }
            return null
        }

        private fun findMarkAsReadAction(notification: Notification): PendingIntent? {
            val actions = notification.actions ?: return null
            return actions.firstOrNull { action ->
                val label = action.title?.toString()?.lowercase().orEmpty()
                action.remoteInputs.isNullOrEmpty() &&
                    (label.contains("mark as read") || label == "read")
            }?.actionIntent
        }

        private fun resolveAppLabel(context: Context, pkg: String): String {
            val known = when (pkg) {
                "com.whatsapp" -> "WhatsApp"
                "com.whatsapp.w4b" -> "WhatsApp Business"
                "org.telegram.messenger" -> "Telegram"
                "com.instagram.android" -> "Instagram"
                "com.google.android.apps.messaging", "com.samsung.android.messaging" -> "Messages"
                "org.thoughtcrime.securesms" -> "Signal"
                "com.facebook.orca" -> "Messenger"
                "com.Slack" -> "Slack"
                "com.discord" -> "Discord"
                else -> null
            }
            if (known != null) return known
            return runCatching {
                val pm = context.packageManager
                val info = pm.getApplicationInfo(pkg, 0)
                pm.getApplicationLabel(info).toString()
            }.getOrDefault(pkg.substringAfterLast('.'))
        }

        /**
         * Reads the most recent messages/notifications, optionally filtered by sender name or app.
         */
        fun readRecentMessages(
            context: Context? = null,
            senderFilter: String = "",
            appFilter: String = "",
            limit: Int = 5,
        ): NotificationReadResult {
            instanceRef?.get()?.syncActiveNotifications()

            if (context != null && !isPermissionGranted(context) && recent.isEmpty()) {
                return NotificationReadResult(
                    success = false,
                    summary = "Notification access is not enabled for Harma AI. Please enable Harma AI in Notification Access settings to read and reply to messages hands-free.",
                    notifications = emptyList(),
                    permissionMissing = true,
                )
            }

            val senderQuery = senderFilter.trim().lowercase()
            val appQuery = appFilter.trim().lowercase()

            val matched = synchronized(recent) {
                recent.filter { item ->
                    val matchesSender = senderQuery.isBlank() ||
                        item.title.lowercase().contains(senderQuery) ||
                        item.conversationTitle.lowercase().contains(senderQuery)
                    val matchesApp = appQuery.isBlank() ||
                        item.appName.lowercase().contains(appQuery) ||
                        item.packageName.lowercase().contains(appQuery)
                    matchesSender && matchesApp
                }
            }

            // Prioritize replyable messaging notifications first
            val sorted = matched.sortedWith(
                compareByDescending<HarmaNotification> { it.canReply || it.packageName in MESSAGING_PACKAGES }
                    .thenByDescending { it.postedAt },
            ).take(limit.coerceIn(1, 15))

            if (sorted.isEmpty()) {
                val filterDesc = when {
                    senderQuery.isNotBlank() && appQuery.isNotBlank() -> " from $senderFilter on $appFilter"
                    senderQuery.isNotBlank() -> " from $senderFilter"
                    appQuery.isNotBlank() -> " on $appFilter"
                    else -> ""
                }
                return NotificationReadResult(
                    success = true,
                    summary = "You have no recent messages$filterDesc.",
                    notifications = emptyList(),
                )
            }

            val spokenSummary = buildString {
                append("You have ${sorted.size} recent ${if (sorted.size == 1) "message" else "messages"}. ")
                sorted.forEachIndexed { idx, item ->
                    if (idx > 0) append(" Next, ")
                    append("from ${item.displaySender} on ${item.appName}: \"${item.text}\".")
                }
            }

            return NotificationReadResult(
                success = true,
                summary = spokenSummary,
                notifications = sorted,
            )
        }

        /**
         * Checks whether an active replyable notification exists for a given sender/app.
         */
        fun hasReplyableNotification(senderQuery: String = "", appOrPackageQuery: String = ""): Boolean {
            instanceRef?.get()?.syncActiveNotifications()
            return findBestReplyCandidate(senderQuery, appOrPackageQuery) != null
        }

        fun findBestReplyCandidate(
            senderQuery: String = "",
            appOrPackageQuery: String = "",
        ): HarmaNotification? {
            val cleanSender = senderQuery.trim().lowercase()
                .removePrefix("to ")
                .removeSuffix(" message")
                .trim()
            val isGenericLastTarget = cleanSender in setOf(
                "", "last", "latest", "recent", "that", "this", "it", "them", "him", "her",
                "last message", "that message", "latest message", "the message",
            )
            val cleanApp = appOrPackageQuery.trim().lowercase()

            synchronized(recent) {
                val replyable = recent.filter {
                    it.canReply && it.replyPendingIntent != null && !it.remoteInputs.isNullOrEmpty()
                }
                if (replyable.isEmpty()) return null

                val appFiltered = if (cleanApp.isBlank()) {
                    replyable
                } else {
                    replyable.filter {
                        it.appName.lowercase().contains(cleanApp) ||
                            it.packageName.lowercase().contains(cleanApp)
                    }
                }
                if (appFiltered.isEmpty()) return null

                if (isGenericLastTarget) {
                    return appFiltered.first()
                }

                // 1. Exact title match
                appFiltered.firstOrNull {
                    it.title.equals(cleanSender, ignoreCase = true) ||
                        it.conversationTitle.equals(cleanSender, ignoreCase = true)
                }?.let { return it }

                // 2. Partial title / conversation match
                appFiltered.firstOrNull {
                    it.title.lowercase().contains(cleanSender) ||
                        it.conversationTitle.lowercase().contains(cleanSender) ||
                        it.appName.lowercase().contains(cleanSender)
                }?.let { return it }

                return null
            }
        }

        /**
         * Sends an instant background reply through the notification's [RemoteInput] PendingIntent
         * without opening the app or tapping any UI elements.
         */
        fun replyToNotification(
            context: Context,
            senderQuery: String = "",
            appQuery: String = "",
            replyText: String,
        ): NotificationReplyResult {
            val cleanReply = replyText.trim()
            if (cleanReply.isBlank()) {
                return NotificationReplyResult(
                    success = false,
                    message = "Reply message text cannot be empty.",
                )
            }

            instanceRef?.get()?.syncActiveNotifications()

            if (!isPermissionGranted(context)) {
                return NotificationReplyResult(
                    success = false,
                    message = "Notification access is required for instant background replies. Please enable Harma AI in Notification Access settings.",
                    permissionMissing = true,
                )
            }

            val candidate = findBestReplyCandidate(senderQuery, appQuery)
                ?: return NotificationReplyResult(
                    success = false,
                    message = if (senderQuery.isBlank()) {
                        "No recent message notification with direct reply support was found."
                    } else {
                        "No recent replyable notification found from '$senderQuery'."
                    },
                )

            val pendingIntent = candidate.replyPendingIntent
            val remoteInputs = candidate.remoteInputs
            if (pendingIntent == null || remoteInputs.isNullOrEmpty()) {
                return NotificationReplyResult(
                    success = false,
                    message = "The notification from ${candidate.displaySender} does not expose a RemoteInput reply action.",
                )
            }

            return try {
                val fillInIntent = Intent().addFlags(Intent.FLAG_RECEIVER_FOREGROUND)
                val resultsBundle = Bundle()
                for (remoteInput in remoteInputs) {
                    resultsBundle.putCharSequence(remoteInput.resultKey, cleanReply)
                }
                RemoteInput.addResultsToIntent(remoteInputs, fillInIntent, resultsBundle)
                pendingIntent.send(context, 0, fillInIntent)

                // Optionally trigger mark-as-read if the notification provides one
                runCatching {
                    candidate.markAsReadIntent?.send()
                }

                Log.i(TAG, "Sent RemoteInput background reply to '${candidate.displaySender}' on ${candidate.appName}")
                NotificationReplyResult(
                    success = true,
                    message = "Replied to ${candidate.displaySender} on ${candidate.appName}: \"$cleanReply\" (sent directly in the background).",
                    sender = candidate.displaySender,
                    appName = candidate.appName,
                    packageName = candidate.packageName,
                )
            } catch (cancelled: PendingIntent.CanceledException) {
                Log.w(TAG, "Reply PendingIntent was canceled for ${candidate.displaySender}", cancelled)
                NotificationReplyResult(
                    success = false,
                    message = "The notification from ${candidate.displaySender} expired or was already dismissed.",
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send RemoteInput reply", e)
                NotificationReplyResult(
                    success = false,
                    message = "Could not send background reply: ${e.message ?: e.javaClass.simpleName}",
                )
            }
        }

        fun recentJson(limit: Int = 15): JSONObject {
            instanceRef?.get()?.syncActiveNotifications()
            val items = JSONArray()
            synchronized(recent) {
                recent.take(limit.coerceIn(1, MAX_NOTIFICATIONS)).forEach { item ->
                    items.put(
                        JSONObject()
                            .put("package", item.packageName)
                            .put("app", item.appName)
                            .put("title", item.title)
                            .put("conversation", item.conversationTitle)
                            .put("text", item.text)
                            .put("canReply", item.canReply)
                            .put("postedAt", item.postedAt),
                    )
                }
            }
            return JSONObject().put("notifications", items)
        }

        private fun containsSensitiveOtp(title: String, body: String): Boolean =
            sensitive.containsMatchIn("$title $body")

        internal fun sanitize(value: String): String = sensitive.replace(value) { match ->
            match.value.replace(Regex("[0-9]"), "•")
        }.take(500)
    }
}
