package ai.harma.assistant

import android.os.Bundle
import android.service.voice.AlwaysOnHotwordDetector
import android.service.voice.VoiceInteractionService
import android.util.Log
import java.util.Locale

/**
 * Harma VoiceInteractionService (Spec §39, §42)
 *
 * Lightweight system-managed service kept alive by the Android OS when Harma is
 * chosen as the default Assistant application.
 *
 * Responsibilities:
 *  - Manages hardware/DSP AlwaysOnHotwordDetector for "Hey Harma" (Spec §38, §50).
 *  - Hands off active commands to HarmaVoiceSessionService (keeps memory footprint minimal).
 *  - Respects Android 14+ background execution rules (Spec §40).
 */
class HarmaVoiceInteractionService : VoiceInteractionService() {

    companion object {
        private const val TAG = "HarmaVoiceService"
        const val WAKE_PHRASE = "Hey Harma"
    }

    private var hotwordDetector: AlwaysOnHotwordDetector? = null

    override fun onReady() {
        super.onReady()
        Log.i(TAG, "Harma VoiceInteractionService ready as system assistant")

        // Initialize lightweight hardware hotword detector for "Hey Harma"
        initHotwordDetector()
    }

    private fun initHotwordDetector() {
        try {
            hotwordDetector = createAlwaysOnHotwordDetector(
                WAKE_PHRASE,
                Locale.getDefault(),
                object : AlwaysOnHotwordDetector.Callback() {
                    override fun onAvailabilityChanged(status: Int) {
                        Log.d(TAG, "Hotword detector availability status=$status")
                    }

                    override fun onDetected(eventPayload: AlwaysOnHotwordDetector.EventPayload) {
                        Log.i(TAG, "Wake word 'Hey Harma' detected via hardware DSP!")
                        // Trigger voice session overlay immediately (Spec §4, §39)
                        val args = Bundle().apply {
                            putString("trigger", "hotword")
                            putLong("detected_at", System.currentTimeMillis())
                        }
                        showSession(args, VoiceInteractionSession.SHOW_SOURCE_ASSIST_GESTURE)
                    }

                    override fun onError() {
                        Log.e(TAG, "Error in AlwaysOnHotwordDetector")
                    }

                    override fun onRecognitionPaused() {
                        Log.d(TAG, "Hotword recognition paused")
                    }

                    override fun onRecognitionResumed() {
                        Log.d(TAG, "Hotword recognition resumed")
                    }
                }
            )
            hotwordDetector?.startRecognition(AlwaysOnHotwordDetector.RECOGNITION_FLAG_ENABLE_AUDIO_TRIM)
        } catch (e: Exception) {
            Log.w(TAG, "Hardware hotword detector unavailable; falling back to software capture", e)
        }
    }

    override fun onShutdown() {
        super.onShutdown()
        hotwordDetector?.stopRecognition()
        hotwordDetector = null
        Log.i(TAG, "Harma VoiceInteractionService shutdown")
    }
}
