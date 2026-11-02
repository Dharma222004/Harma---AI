package com.personal.harmaai.agent

import android.content.Context
import android.database.ContentObserver
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.telephony.TelephonyManager
import android.util.Log
import com.personal.harmaai.accessibility.AgentAccessibilityService
import java.util.concurrent.atomic.AtomicBoolean

class CameraVerifier(private val context: Context) {
    private val newPhotoObserved = AtomicBoolean(false)
    private var observer: ContentObserver? = null

    fun startListening() {
        newPhotoObserved.set(false)
        val obs = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean, uri: Uri?) {
                super.onChange(selfChange, uri)
                Log.i(TAG, "Observed MediaStore image change: $uri")
                newPhotoObserved.set(true)
            }
        }
        observer = obs
        try {
            context.contentResolver.registerContentObserver(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                true,
                obs,
            )
            Log.i(TAG, "Registered MediaStore ContentObserver")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to register MediaStore ContentObserver: ${e.message}")
        }
    }

    fun hasPhotoSavedSince(startTimestampMillis: Long): Boolean {
        if (newPhotoObserved.get()) {
            Log.i(TAG, "Photo verified via ContentObserver notification")
            return true
        }

        try {
            val projection = arrayOf(
                MediaStore.Images.Media._ID,
                MediaStore.Images.Media.DATE_ADDED,
                MediaStore.Images.Media.DATE_TAKEN,
                MediaStore.Images.Media.DISPLAY_NAME,
            )
            val sortOrder = "${MediaStore.Images.Media.DATE_ADDED} DESC"
            context.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                projection,
                null,
                null,
                sortOrder,
            )?.use { cursor ->
                val dateAddedCol = cursor.getColumnIndex(MediaStore.Images.Media.DATE_ADDED)
                val dateTakenCol = cursor.getColumnIndex(MediaStore.Images.Media.DATE_TAKEN)
                val nameCol = cursor.getColumnIndex(MediaStore.Images.Media.DISPLAY_NAME)
                var count = 0
                while (cursor.moveToNext() && count < 5) {
                    count++
                    val dateAddedSec = if (dateAddedCol >= 0) cursor.getLong(dateAddedCol) else 0L
                    val dateTakenMs = if (dateTakenCol >= 0) cursor.getLong(dateTakenCol) else 0L
                    val dateAddedMs = dateAddedSec * 1000L
                    val name = if (nameCol >= 0) cursor.getString(nameCol) else "photo"

                    // Check if file was added after action start (allowing 4s clock tolerance)
                    if (dateAddedMs >= startTimestampMillis - 4000L || dateTakenMs >= startTimestampMillis - 4000L) {
                        Log.i(TAG, "Photo verified via MediaStore query: '$name' (added: $dateAddedMs, start: $startTimestampMillis)")
                        return true
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "MediaStore query check encountered exception: ${e.message}")
        }
        return false
    }

    fun stopListening() {
        observer?.let {
            try {
                context.contentResolver.unregisterContentObserver(it)
                Log.i(TAG, "Unregistered MediaStore ContentObserver")
            } catch (_: Exception) {}
            observer = null
        }
    }

    companion object {
        private const val TAG = "CameraVerifier"
    }
}

class CallVerifier(private val context: Context) {
    fun isCallActive(): Boolean {
        // 1. Check TelephonyManager call state
        try {
            val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
            if (tm != null) {
                @Suppress("DEPRECATION")
                val state = tm.callState
                if (state == TelephonyManager.CALL_STATE_OFFHOOK || state == TelephonyManager.CALL_STATE_RINGING) {
                    Log.i(TAG, "Call verified active via TelephonyManager: state=$state")
                    return true
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "TelephonyManager check error: ${e.message}")
        }

        // 2. Check active in-call window / package via AccessibilityService
        val accessibility = AgentAccessibilityService.current()
        if (accessibility != null) {
            val observation = accessibility.captureObservation()
            val pkg = observation.packageName.lowercase()
            val inCallPackages = listOf("incall", "dialer", "telecom", "phone", "call")
            val inCallKeywords = listOf(
                "calling",
                "dialing",
                "in call",
                "end call",
                "speaker",
                "mute",
                "bluetooth",
                "keypad",
                "00:0",
                "00:1",
            )

            val isKnownInCallPkg = inCallPackages.any { pkg.contains(it) }
            val hasInCallNode = observation.nodes.any { node ->
                val text = node.text.lowercase()
                val desc = node.contentDescription.lowercase()
                inCallKeywords.any { text.contains(it) || desc.contains(it) }
            }
            if (isKnownInCallPkg && hasInCallNode) {
                Log.i(TAG, "Call verified active via Accessibility in package '$pkg'")
                return true
            }
        }

        return false
    }

    companion object {
        private const val TAG = "CallVerifier"
    }
}

class AudioPlayingVerifier(private val context: Context) {
    fun isAudioPlaying(): Boolean {
        try {
            val am = context.getSystemService(Context.AUDIO_SERVICE) as? android.media.AudioManager
            if (am != null && am.isMusicActive) {
                Log.i(TAG, "Audio playing confirmed via AudioManager.isMusicActive")
                return true
            }
        } catch (_: Exception) {}

        val accessibility = AgentAccessibilityService.current()
        if (accessibility != null) {
            val obs = accessibility.captureObservation()
            val hasPlayerControls = obs.nodes.any { node ->
                val desc = node.contentDescription.lowercase()
                val text = node.text.lowercase()
                val id = node.viewId.lowercase()
                desc.contains("pause") || text.contains("pause") ||
                    id.contains("player_control") || id.contains("progress_bar") ||
                    desc.contains("playing")
            }
            if (hasPlayerControls) {
                Log.i(TAG, "Audio playing confirmed via Accessibility player controls")
                return true
            }
        }
        return false
    }

    companion object {
        private const val TAG = "AudioPlayingVerifier"
    }
}

class WhatsAppVerifier(private val context: Context) {
    fun isMessageSent(): Boolean {
        val accessibility = AgentAccessibilityService.current() ?: return false
        val obs = accessibility.captureObservation()
        if (!obs.packageName.contains("whatsapp", ignoreCase = true)) return false

        val tickKeywords = listOf("sent", "delivered", "read", "status", "tick")
        return obs.nodes.any { node ->
            val desc = node.contentDescription.lowercase()
            val text = node.text.lowercase()
            val id = node.viewId.lowercase()
            id.contains("status_tick") || id.contains("msg_status") ||
                tickKeywords.any { desc.contains(it) || text.contains(it) }
        }
    }

    companion object {
        private const val TAG = "WhatsAppVerifier"
    }
}

