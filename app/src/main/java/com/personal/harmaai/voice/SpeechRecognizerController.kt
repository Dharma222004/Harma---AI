package com.personal.harmaai.voice

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.content.ContextCompat
import java.util.Locale

class SpeechRecognizerController(
    context: Context,
    private val callback: Callback,
) : RecognitionListener {
    interface Callback {
        fun onListeningChanged(isListening: Boolean) = Unit
        fun onPartialText(text: String) = Unit
        fun onFinalText(text: String)
        fun onRmsChanged(rmsdB: Float) = Unit
        fun onError(message: String) = Unit
    }

    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var isListening = false

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(appContext)

    fun startListening(languageTag: String = Locale.getDefault().toLanguageTag()) {
        runOnMain {
            if (isListening) return@runOnMain
            if (
                ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                callback.onError("Microphone permission is required for voice commands.")
                return@runOnMain
            }
            if (!isAvailable()) {
                callback.onError("Speech recognition is not available on this device.")
                return@runOnMain
            }

            if (recognizer == null) {
                recognizer = SpeechRecognizer.createSpeechRecognizer(appContext).also {
                    it.setRecognitionListener(this)
                }
            }

            val preferOffline = !com.personal.harmaai.network.NetworkMonitor.isCurrentlyOnline(appContext)
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, preferOffline)
            }

            runCatching { recognizer?.startListening(intent) }
                .onSuccess { setListening(true) }
                .onFailure { callback.onError("Could not start voice recognition: ${it.message}") }
        }
    }

    fun stopListening() = runOnMain {
        runCatching { recognizer?.stopListening() }
        setListening(false)
    }

    fun cancel() = runOnMain {
        runCatching { recognizer?.cancel() }
        setListening(false)
    }

    fun destroy() = runOnMain {
        runCatching { recognizer?.destroy() }
        recognizer = null
        setListening(false)
    }

    override fun onReadyForSpeech(params: Bundle?) = setListening(true)
    override fun onBeginningOfSpeech() = Unit
    override fun onRmsChanged(rmsdB: Float) {
        callback.onRmsChanged(rmsdB)
    }
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onEndOfSpeech() = setListening(false)

    override fun onError(error: Int) {
        setListening(false)
        callback.onError(errorMessage(error))
    }

    override fun onResults(results: Bundle?) {
        setListening(false)
        val text = results
            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()
            ?.trim()
            .orEmpty()
        if (text.isBlank()) callback.onError("No speech was recognized.") else callback.onFinalText(text)
    }

    override fun onPartialResults(partialResults: Bundle?) {
        val text = partialResults
            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()
            ?.trim()
            .orEmpty()
        if (text.isNotBlank()) callback.onPartialText(text)
    }

    override fun onEvent(eventType: Int, params: Bundle?) = Unit

    private fun setListening(value: Boolean) {
        if (isListening == value) return
        isListening = value
        callback.onListeningChanged(value)
    }

    private fun runOnMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block() else mainHandler.post(block)
    }

    private fun errorMessage(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_AUDIO -> "Audio recording failed."
        SpeechRecognizer.ERROR_CLIENT -> "Voice recognition was cancelled."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is required."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
            "A network error interrupted voice recognition."
        SpeechRecognizer.ERROR_NO_MATCH -> "No speech was recognized."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Voice recognition is already busy."
        SpeechRecognizer.ERROR_SERVER -> "The speech recognition service returned an error."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech was detected."
        else -> "Voice recognition failed (code $error)."
    }
}
