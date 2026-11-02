package com.personal.harmaai.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

class TtsController(
    context: Context,
    private val onReady: (Boolean) -> Unit = {},
) : TextToSpeech.OnInitListener {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val completionCallbacks = ConcurrentHashMap<String, (Boolean) -> Unit>()
    private var engine: TextToSpeech? = TextToSpeech(context.applicationContext, this)
    private var ready = false
    private val audioManager = appContext.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
    private var focusRequest: AudioFocusRequest? = null

    override fun onInit(status: Int) {
        val initialized = if (status == TextToSpeech.SUCCESS) {
            val languageResult = engine?.setLanguage(Locale.getDefault())
            languageResult != TextToSpeech.LANG_MISSING_DATA &&
                languageResult != TextToSpeech.LANG_NOT_SUPPORTED
        } else {
            false
        }
        ready = initialized
        if (initialized) {
            engine?.setSpeechRate(1.02f)
            engine?.setPitch(1f)
            engine?.setOnUtteranceProgressListener(listener)
        }
        mainHandler.post { onReady(initialized) }
    }

    fun isReady(): Boolean = ready

    fun setSpeechParameters(rate: Float, pitch: Float) {
        engine?.setSpeechRate(rate.coerceIn(0.5f, 2.0f))
        engine?.setPitch(pitch.coerceIn(0.5f, 2.0f))
    }

    private fun requestAudioFocus() {
        if (audioManager == null) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .build()
            focusRequest = req
            audioManager.requestAudioFocus(req)
        } else {
            @Suppress("DEPRECATION")
            audioManager.requestAudioFocus(null, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        }
    }

    private fun abandonAudioFocus() {
        if (audioManager == null) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            focusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
            focusRequest = null
        } else {
            @Suppress("DEPRECATION")
            audioManager.abandonAudioFocus(null)
        }
    }

    fun speak(
        text: String,
        flush: Boolean = true,
        onComplete: ((Boolean) -> Unit)? = null,
    ): Boolean {
        val message = text.trim()
        if (!ready || message.isBlank()) return false
        requestAudioFocus()
        val utteranceId = "harma-${UUID.randomUUID()}"
        if (onComplete != null) completionCallbacks[utteranceId] = onComplete
        val queueMode = if (flush) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
        val result = engine?.speak(message, queueMode, null, utteranceId)
        if (result != TextToSpeech.SUCCESS) {
            abandonAudioFocus()
            completionCallbacks.remove(utteranceId)?.invoke(false)
        }
        return result == TextToSpeech.SUCCESS
    }

    fun stop() {
        HarmaVoiceService.isTtsSpeaking = false
        abandonAudioFocus()
        engine?.stop()
        val callbacks = completionCallbacks.values.toList()
        completionCallbacks.clear()
        callbacks.forEach { callback -> mainHandler.post { callback(false) } }
    }

    fun shutdown() {
        HarmaVoiceService.isTtsSpeaking = false
        stop()
        engine?.shutdown()
        engine = null
        ready = false
    }

    private val listener = object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String?) {
            HarmaVoiceService.isTtsSpeaking = true
        }

        override fun onDone(utteranceId: String?) {
            HarmaVoiceService.isTtsSpeaking = false
            abandonAudioFocus()
            complete(utteranceId, true)
        }

        @Deprecated("Deprecated in Java")
        override fun onError(utteranceId: String?) {
            HarmaVoiceService.isTtsSpeaking = false
            abandonAudioFocus()
            complete(utteranceId, false)
        }

        override fun onError(utteranceId: String?, errorCode: Int) {
            HarmaVoiceService.isTtsSpeaking = false
            abandonAudioFocus()
            complete(utteranceId, false)
        }
    }

    private fun complete(utteranceId: String?, success: Boolean) {
        if (utteranceId == null) return
        val callback = completionCallbacks.remove(utteranceId) ?: return
        mainHandler.post { callback(success) }
    }
}
