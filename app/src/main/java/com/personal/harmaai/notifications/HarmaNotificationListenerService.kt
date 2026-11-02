package com.personal.harmaai.notifications

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject
import java.util.ArrayDeque

data class HarmaNotification(
    val packageName: String,
    val title: String,
    val text: String,
    val postedAt: Long,
)

class HarmaNotificationListenerService : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null || sbn.packageName == packageName) return
        val extras = sbn.notification.extras
        val title = sanitize(extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty())
        val text = sanitize(extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty())
        synchronized(recent) {
            recent.addFirst(HarmaNotification(sbn.packageName, title, text, sbn.postTime))
            while (recent.size > MAX_NOTIFICATIONS) recent.removeLast()
        }
    }

    companion object {
        private const val MAX_NOTIFICATIONS = 50
        private val recent = ArrayDeque<HarmaNotification>()
        private val sensitive = Regex(
            "(?i)(otp|one.?time password|verification code|security code|pin|password|cvv)[^0-9]{0,12}[0-9]{3,8}",
        )

        fun recentJson(limit: Int = 15): JSONObject {
            val items = JSONArray()
            synchronized(recent) {
                recent.take(limit.coerceIn(1, MAX_NOTIFICATIONS)).forEach { item ->
                    items.put(
                        JSONObject()
                            .put("package", item.packageName)
                            .put("title", item.title)
                            .put("text", item.text)
                            .put("postedAt", item.postedAt),
                    )
                }
            }
            return JSONObject().put("notifications", items)
        }

        private fun sanitize(value: String): String = sensitive.replace(value) { match ->
            match.value.replace(Regex("[0-9]"), "•")
        }.take(500)
    }
}
