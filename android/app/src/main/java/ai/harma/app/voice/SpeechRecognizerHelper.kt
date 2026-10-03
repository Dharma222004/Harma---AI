package ai.harma.app.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import java.util.Locale

/**
 * Speech Recognition and Wake-Word Listener Helper
 * Detects "Hey Harma" and captures spoken voice commands natively.
 */
class SpeechRecognizerHelper(private val context: Context) {

    private var speechRecognizer: SpeechRecognizer? = null
    private var isListening = false

    var onWakeWordDetected: (() -> Unit)? = null
    var onCommandRecognized: ((String) -> Unit)? = null
    var onPartialResult: ((String) -> Unit)? = null
    var onErrorOccurred: ((String) -> Unit)? = null

    companion object {
        const val WAKE_WORD = "hey harma"
        const val WAKE_WORD_SHORT = "harma"
    }

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    fun startListening() {
        if (isListening) return

        if (speechRecognizer == null) {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context)
            speechRecognizer?.setRecognitionListener(createListener())
        }

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }

        try {
            speechRecognizer?.startListening(intent)
            isListening = true
        } catch (e: Exception) {
            onErrorOccurred?.invoke("Speech recognition start failed: ${e.message}")
        }
    }

    fun stopListening() {
        if (!isListening) return
        try {
            speechRecognizer?.stopListening()
        } catch (e: Exception) {
            // Ignore
        } finally {
            isListening = false
        }
    }

    fun destroy() {
        stopListening()
        try {
            speechRecognizer?.destroy()
        } catch (e: Exception) {
            // Ignore
        }
        speechRecognizer = null
    }

    private fun createListener() = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {
            isListening = false
        }

        override fun onError(error: Int) {
            isListening = false
            val errorMsg = when (error) {
                SpeechRecognizer.ERROR_NO_MATCH -> "No speech recognized"
                SpeechRecognizer.ERROR_NETWORK -> "Network error during speech recognition"
                SpeechRecognizer.ERROR_AUDIO -> "Audio recording error"
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission required"
                else -> "Speech recognition error code: $error"
            }
            onErrorOccurred?.invoke(errorMsg)
        }

        override fun onResults(results: Bundle?) {
            isListening = false
            val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION) ?: return
            val bestMatch = matches.firstOrNull() ?: return

            val lower = bestMatch.lowercase().trim()
            if (lower.startsWith(WAKE_WORD)) {
                onWakeWordDetected?.invoke()
                val query = lower.removePrefix(WAKE_WORD).trim()
                if (query.isNotEmpty()) {
                    onCommandRecognized?.invoke(query)
                }
            } else if (lower.startsWith(WAKE_WORD_SHORT)) {
                onWakeWordDetected?.invoke()
                val query = lower.removePrefix(WAKE_WORD_SHORT).trim()
                if (query.isNotEmpty()) {
                    onCommandRecognized?.invoke(query)
                }
            } else {
                onCommandRecognized?.invoke(bestMatch)
            }
        }

        override fun onPartialResults(partialResults: Bundle?) {
            val partials = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            val partial = partials?.firstOrNull() ?: return
            onPartialResult?.invoke(partial)
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }
}
