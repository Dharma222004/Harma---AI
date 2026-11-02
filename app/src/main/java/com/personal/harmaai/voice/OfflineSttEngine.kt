package com.personal.harmaai.voice

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import com.personal.harmaai.network.NetworkMonitor
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale
import kotlin.coroutines.resume

/**
 * Offline-first Speech-to-Text engine (Step 2):
 *
 * Strategy:
 * 1. Primary Offline Path: Uses Android's `OnDeviceSpeechRecognizer` (API 31+) or standard
 *    `SpeechRecognizer` with `EXTRA_PREFER_OFFLINE = true` so "Hey Harma, <command>" works
 *    100% offline with zero network dependency.
 * 2. Optional Cloud Path: When validated internet is available and a Groq Whisper API key is
 *    configured, can transcribe a VAD-captured WAV file via `GroqWhisperClient`, automatically
 *    falling back to on-device recognition if the network request fails.
 */
class OfflineSttEngine(
    context: Context,
    private val groqClient: GroqWhisperClient = GroqWhisperClient(),
) {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())

    suspend fun listenAndTranscribe(
        languageTag: String = Locale.getDefault().toLanguageTag(),
        groqApiKey: String = "",
        groqModel: String = "whisper-large-v3-turbo",
        sessionId: String = "",
        onPartial: (String) -> Unit = {},
    ): Result<String> {
        val isOnline = NetworkMonitor.isCurrentlyOnline(appContext)

        // 1. Try on-device SpeechRecognizer first when offline OR when no cloud STT key is set
        if (!isOnline || groqApiKey.isBlank()) {
            val offlineResult = recognizeOnDevice(languageTag, preferOffline = true, onPartial = onPartial)
            if (offlineResult.isSuccess) return offlineResult
            if (!isOnline) {
                return offlineResult
            }
        }

        // 2. When online with a configured Groq key, record with VAD and transcribe with Whisper,
        //    falling back to on-device SpeechRecognizer if VAD/Groq fails.
        if (isOnline && groqApiKey.isNotBlank()) {
            val vad = VoiceActivityDetector(appContext)
            val wavFile = vad.recordSpeechWithVad(sessionId = sessionId)
            if (wavFile != null && wavFile.length() > 0L) {
                val whisperRes = groqClient.transcribe(
                    audioFile = wavFile,
                    apiKey = groqApiKey,
                    model = groqModel,
                    language = languageTag.substringBefore('-').ifBlank { "en" },
                    sessionId = sessionId,
                )
                runCatching { wavFile.delete() }
                if (whisperRes.isSuccess) {
                    return whisperRes
                }
                Log.w(TAG, "Cloud Whisper failed (${whisperRes.exceptionOrNull()?.message}); falling back to on-device STT.")
            }
        }

        return recognizeOnDevice(languageTag, preferOffline = !isOnline, onPartial = onPartial)
    }

    suspend fun recognizeOnDevice(
        languageTag: String = Locale.getDefault().toLanguageTag(),
        preferOffline: Boolean = true,
        timeoutMs: Long = 10_000L,
        onPartial: (String) -> Unit = {},
    ): Result<String> {
        val text = withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine<Result<String>> { continuation ->
                mainHandler.post {
                    if (!SpeechRecognizer.isRecognitionAvailable(appContext)) {
                        if (continuation.isActive) {
                            continuation.resume(Result.failure(IllegalStateException("On-device speech recognition is unavailable on this device.")))
                        }
                        return@post
                    }

                    val recognizer = try {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                            preferOffline &&
                            SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)
                        ) {
                            SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
                        } else {
                            SpeechRecognizer.createSpeechRecognizer(appContext)
                        }
                    } catch (e: Exception) {
                        if (continuation.isActive) {
                            continuation.resume(Result.failure(e))
                        }
                        return@post
                    }

                    var lastPartial = ""

                    val listener = object : RecognitionListener {
                        override fun onReadyForSpeech(params: Bundle?) = Unit
                        override fun onBeginningOfSpeech() = Unit
                        override fun onRmsChanged(rmsdB: Float) = Unit
                        override fun onBufferReceived(buffer: ByteArray?) = Unit
                        override fun onEndOfSpeech() = Unit

                        override fun onPartialResults(partialResults: Bundle?) {
                            val partial = partialResults
                                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                                ?.firstOrNull()
                                ?.trim()
                                .orEmpty()
                            if (partial.isNotBlank()) {
                                lastPartial = partial
                                onPartial(partial)
                            }
                        }

                        override fun onResults(results: Bundle?) {
                            val finalTranscript = results
                                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                                ?.firstOrNull()
                                ?.trim()
                                .orEmpty()
                                .ifBlank { lastPartial }
                            runCatching { recognizer.destroy() }
                            if (continuation.isActive) {
                                if (finalTranscript.isNotBlank()) {
                                    continuation.resume(Result.success(finalTranscript))
                                } else {
                                    continuation.resume(Result.failure(IllegalStateException("No speech detected.")))
                                }
                            }
                        }

                        override fun onError(error: Int) {
                            runCatching { recognizer.destroy() }
                            if (continuation.isActive) {
                                if (lastPartial.isNotBlank()) {
                                    continuation.resume(Result.success(lastPartial))
                                } else {
                                    continuation.resume(
                                        Result.failure(IllegalStateException("SpeechRecognizer error code $error")),
                                    )
                                }
                            }
                        }

                        override fun onEvent(eventType: Int, params: Bundle?) = Unit
                    }

                    recognizer.setRecognitionListener(listener)
                    val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
                        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                        putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                        putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, preferOffline)
                    }

                    continuation.invokeOnCancellation {
                        mainHandler.post {
                            runCatching {
                                recognizer.cancel()
                                recognizer.destroy()
                            }
                        }
                    }

                    runCatching { recognizer.startListening(intent) }.onFailure { err ->
                        runCatching { recognizer.destroy() }
                        if (continuation.isActive) {
                            continuation.resume(Result.failure(err))
                        }
                    }
                }
            }
        }
        return text ?: Result.failure(IllegalStateException("Speech recognition timed out."))
    }

    companion object {
        private const val TAG = "OfflineSttEngine"
    }
}
