package com.personal.harmaai.voice.wakeword

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

class WakeWordListener(
    private val context: Context,
    private val onWakeWordDetected: (modelName: String) -> Unit,
    private val onScoreUpdate: ((score: Float, threshold: Float) -> Unit)? = null,
) {
    private var engine: OpenWakeWordEngine? = null
    private var audioRecord: AudioRecord? = null
    private var workerJob: Job? = null
    private val isRunning = AtomicBoolean(false)
    private val isPaused = AtomicBoolean(false)

    @Volatile
    var threshold: Float = 0.5f

    @Volatile
    private var consecutiveHits = 0

    @Volatile
    private var lastTriggerAt = 0L

    val activeModelName: String
        get() = engine?.activeModelName ?: "unknown"

    @Synchronized
    fun start(scope: CoroutineScope, initialThreshold: Float = 0.5f) {
        if (isRunning.get()) return
        threshold = initialThreshold.coerceIn(0.3f, 0.9f)

        try {
            if (engine == null) {
                engine = OpenWakeWordEngine(context)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Cannot start wake word listener: ${e.message}", e)
            return
        }

        initAudioRecord()
        val record = audioRecord ?: run {
            Log.e(TAG, "AudioRecord could not be initialized.")
            return
        }

        try {
            record.startRecording()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start AudioRecord: ${e.message}", e)
            return
        }

        isRunning.set(true)
        isPaused.set(false)
        consecutiveHits = 0

        workerJob = scope.launch(Dispatchers.Default) {
            val audioBuffer = ShortArray(OpenWakeWordEngine.CHUNK_SAMPLES)
            var activeTailFrames = 0
            Log.i(TAG, "openWakeWord listener started with threshold $threshold, model: $activeModelName")

            while (isActive && isRunning.get()) {
                if (isPaused.get()) {
                    consecutiveHits = 0
                    activeTailFrames = 0
                    Thread.sleep(80L)
                    continue
                }

                val currentRecord = audioRecord
                if (currentRecord == null || currentRecord.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                    // Mic-in-use conflict or released: wait and attempt gentle re-acquisition
                    Thread.sleep(400L)
                    if (!isPaused.get() && isRunning.get()) {
                        runCatching {
                            initAudioRecord()
                            audioRecord?.startRecording()
                        }
                    }
                    continue
                }

                val readCount = currentRecord.read(audioBuffer, 0, audioBuffer.size)
                if (readCount < audioBuffer.size) {
                    if (readCount < 0) {
                        // Mic temporarily in use by another app
                        Thread.sleep(300L)
                    }
                    continue
                }

                // Low-power RMS energy pre-gate: skip heavy ONNX inference during room silence
                val rms = computeRms(audioBuffer)
                if (rms >= SILENCE_RMS_GATE) {
                    activeTailFrames = ACTIVE_TAIL_FRAMES
                } else if (activeTailFrames > 0) {
                    activeTailFrames--
                } else if (consecutiveHits == 0) {
                    onScoreUpdate?.invoke(0f, threshold)
                    continue
                }

                val score = try {
                    engine?.processFrame(audioBuffer) ?: 0f
                } catch (e: Exception) {
                    Log.w(TAG, "Error in wake frame inference: ${e.message}")
                    0f
                }

                onScoreUpdate?.invoke(score, threshold)

                val now = SystemClock.elapsedRealtime()
                if (score >= threshold) {
                    consecutiveHits++
                    Log.d(TAG, "Score above threshold ($score >= $threshold), consecutive: $consecutiveHits")
                    if (consecutiveHits >= REQUIRED_CONSECUTIVE_FRAMES && now - lastTriggerAt >= COOLDOWN_MS) {
                        lastTriggerAt = now
                        consecutiveHits = 0
                        activeTailFrames = 0
                        engine?.reset()
                        Log.i(TAG, ">>> Wake word triggered! Score: $score, model: $activeModelName <<<")
                        onWakeWordDetected(activeModelName)
                    }
                } else {
                    consecutiveHits = 0
                }
            }
        }
    }

    private fun computeRms(samples: ShortArray): Double {
        var sumSq = 0.0
        for (s in samples) {
            val v = s.toDouble()
            sumSq += v * v
        }
        return sqrt(sumSq / samples.size.coerceAtLeast(1))
    }

    fun pause() {
        isPaused.set(true)
        consecutiveHits = 0
        try {
            audioRecord?.stop()
        } catch (_: Exception) {}
        engine?.reset()
    }

    fun resume() {
        engine?.reset()
        consecutiveHits = 0
        try {
            audioRecord?.startRecording()
        } catch (_: Exception) {}
        isPaused.set(false)
    }

    @Synchronized
    fun stop() {
        isRunning.set(false)
        workerJob?.cancel()
        workerJob = null

        try {
            audioRecord?.stop()
            audioRecord?.release()
        } catch (_: Exception) {}
        audioRecord = null

        engine?.reset()
        consecutiveHits = 0
        Log.i(TAG, "openWakeWord listener stopped.")
    }

    fun release() {
        stop()
        engine?.close()
        engine = null
    }

    @SuppressLint("MissingPermission")
    private fun initAudioRecord() {
        runCatching {
            audioRecord?.stop()
            audioRecord?.release()
        }
        val minBufferSize = AudioRecord.getMinBufferSize(
            OpenWakeWordEngine.SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufferSize = minBufferSize.coerceAtLeast(OpenWakeWordEngine.CHUNK_SAMPLES * 4 * 2)

        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            OpenWakeWordEngine.SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize,
        )
    }

    companion object {
        private const val TAG = "HarmaWake"
        private const val REQUIRED_CONSECUTIVE_FRAMES = 2
        private const val COOLDOWN_MS = 2000L
        private const val SILENCE_RMS_GATE = 75.0
        private const val ACTIVE_TAIL_FRAMES = 14
    }
}
