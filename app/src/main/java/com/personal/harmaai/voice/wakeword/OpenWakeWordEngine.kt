package com.personal.harmaai.voice.wakeword

import android.content.Context
import android.util.Log
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.Closeable
import java.nio.FloatBuffer
import kotlin.math.exp

/**
 * On-device openWakeWord pipeline running via ONNX Runtime Mobile.
 *
 * Pipeline:
 * 1. 16 kHz mono 16-bit PCM in 80 ms frames (1280 samples)
 * 2. melspectrogram.onnx -> log-mel spectrogram features
 * 3. 76-frame sliding mel context window
 * 4. embedding_model.onnx -> 96-dimensional speech embedding vector
 * 5. 16-frame sliding embedding context window (16 x 96)
 * 6. hey_harma.onnx (or fallback hey_jarvis.onnx) -> detection probability (0.0 to 1.0)
 */
class OpenWakeWordEngine(private val context: Context) : Closeable {

    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val sessionOptions = OrtSession.SessionOptions().apply {
        setIntraOpNumThreads(2)
    }

    private var melSession: OrtSession? = null
    private var embSession: OrtSession? = null
    private var wakeSession: OrtSession? = null

    private var melInputName = "input"
    private var embInputName = "input_1"
    private var wakeInputName = "input"

    var activeModelName: String = "unknown"
        private set

    // Mel buffer: 76 frames of 32 mel bins = 2432 floats
    private val melBuffer = FloatArray(MEL_CONTEXT_FRAMES * MEL_BANDS)

    // Embedding buffer: 16 frames of 96 dimensions = 1536 floats
    private val embBuffer = FloatArray(EMB_CONTEXT_FRAMES * EMBEDDING_DIM)

    // Reusable float buffer for 1280 audio samples
    private val audioFloatBuffer = FloatArray(CHUNK_SAMPLES)

    init {
        loadModels()
    }

    private fun loadModels() {
        try {
            val assetList = context.assets.list("wakeword")?.toList().orEmpty()
            Log.i(TAG, "Available wakeword assets: $assetList")

            // 1. Mel-spectrogram model
            val melBytes = context.assets.open("wakeword/melspectrogram.onnx").use { it.readBytes() }
            val melSess = env.createSession(melBytes, sessionOptions)
            melInputName = melSess.inputNames.iterator().next()
            melSession = melSess
            Log.i(TAG, "Loaded melspectrogram.onnx (input: $melInputName)")

            // 2. Audio embedding model
            val embBytes = context.assets.open("wakeword/embedding_model.onnx").use { it.readBytes() }
            val embSess = env.createSession(embBytes, sessionOptions)
            embInputName = embSess.inputNames.iterator().next()
            embSession = embSess
            Log.i(TAG, "Loaded embedding_model.onnx (input: $embInputName)")

            // 3. Wake word classifier model: hey_harma.onnx or fallback to hey_jarvis.onnx
            val wakeModelAsset = if (assetList.contains("hey_harma.onnx")) {
                activeModelName = "hey_harma"
                "wakeword/hey_harma.onnx"
            } else {
                activeModelName = "hey_jarvis (fallback)"
                Log.w(
                    TAG,
                    "hey_harma.onnx not found in assets/wakeword. Falling back to pretrained hey_jarvis.onnx for testing.",
                )
                "wakeword/hey_jarvis.onnx"
            }

            val wakeBytes = context.assets.open(wakeModelAsset).use { it.readBytes() }
            val wakeSess = env.createSession(wakeBytes, sessionOptions)
            wakeInputName = wakeSess.inputNames.iterator().next()
            wakeSession = wakeSess
            Log.i(TAG, "Loaded wake classifier $wakeModelAsset (input: $wakeInputName)")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to load openWakeWord ONNX models: ${e.message}", e)
            throw IllegalStateException("Failed to initialize openWakeWord models: ${e.message}", e)
        }
    }

    /**
     * Process an 80 ms audio frame (1280 samples, 16 kHz 16-bit mono PCM).
     * Returns detection score between 0.0 and 1.0.
     */
    @Synchronized
    fun processFrame(samples: ShortArray): Float {
        val melSess = melSession ?: return 0f
        val embSess = embSession ?: return 0f
        val wakeSess = wakeSession ?: return 0f

        val sampleCount = samples.size.coerceAtMost(CHUNK_SAMPLES)
        for (i in 0 until sampleCount) {
            // openWakeWord expects raw 16-bit PCM values in float32 range [-32768f, 32767f]
            audioFloatBuffer[i] = samples[i].toFloat()
        }
        for (i in sampleCount until CHUNK_SAMPLES) {
            audioFloatBuffer[i] = 0f
        }

        // 1. Run melspectrogram
        val audioTensor = OnnxTensor.createTensor(
            env,
            FloatBuffer.wrap(audioFloatBuffer),
            longArrayOf(1, CHUNK_SAMPLES.toLong()),
        )

        var newMelFloats: FloatArray? = null
        try {
            val melResult = melSess.run(mapOf(melInputName to audioTensor))
            try {
                val outputTensor = melResult.get(0) as? OnnxTensor
                if (outputTensor != null) {
                    val fb = outputTensor.floatBuffer
                    newMelFloats = FloatArray(fb.remaining())
                    fb.get(newMelFloats)
                }
            } finally {
                melResult.close()
            }
        } finally {
            audioTensor.close()
        }

        if (newMelFloats == null || newMelFloats.isEmpty()) return 0f

        // 2. Slide new mel frames into melBuffer
        val newMelCount = newMelFloats.size
        if (newMelCount < melBuffer.size) {
            System.arraycopy(melBuffer, newMelCount, melBuffer, 0, melBuffer.size - newMelCount)
            System.arraycopy(newMelFloats, 0, melBuffer, melBuffer.size - newMelCount, newMelCount)
        } else {
            System.arraycopy(newMelFloats, newMelCount - melBuffer.size, melBuffer, 0, melBuffer.size)
        }

        // 3. Run embedding model with shape [1, 76, 32, 1]
        val melTensor = OnnxTensor.createTensor(
            env,
            FloatBuffer.wrap(melBuffer),
            longArrayOf(1, MEL_CONTEXT_FRAMES.toLong(), MEL_BANDS.toLong(), 1L),
        )

        var newEmbedding: FloatArray? = null
        try {
            val embResult = embSess.run(mapOf(embInputName to melTensor))
            try {
                val outputTensor = embResult.get(0) as? OnnxTensor
                if (outputTensor != null) {
                    val fb = outputTensor.floatBuffer
                    val embLen = fb.remaining().coerceAtMost(EMBEDDING_DIM)
                    newEmbedding = FloatArray(EMBEDDING_DIM)
                    fb.get(newEmbedding, 0, embLen)
                }
            } finally {
                embResult.close()
            }
        } finally {
            melTensor.close()
        }

        if (newEmbedding == null) return 0f

        // 4. Slide new 96-dim embedding into embBuffer
        System.arraycopy(embBuffer, EMBEDDING_DIM, embBuffer, 0, embBuffer.size - EMBEDDING_DIM)
        System.arraycopy(newEmbedding, 0, embBuffer, embBuffer.size - EMBEDDING_DIM, EMBEDDING_DIM)

        // 5. Run wake word classifier with shape [1, 16, 96]
        val wakeTensor = OnnxTensor.createTensor(
            env,
            FloatBuffer.wrap(embBuffer),
            longArrayOf(1, EMB_CONTEXT_FRAMES.toLong(), EMBEDDING_DIM.toLong()),
        )

        var score = 0f
        try {
            val wakeResult = wakeSess.run(mapOf(wakeInputName to wakeTensor))
            try {
                val outputTensor = wakeResult.get(0) as? OnnxTensor
                if (outputTensor != null) {
                    val fb = outputTensor.floatBuffer
                    val rawVal = if (fb.hasRemaining()) fb.get() else 0f
                    // If output is raw logit, apply sigmoid; if already probability [0, 1], keep
                    score = if (rawVal in 0f..1f) {
                        rawVal
                    } else {
                        1f / (1f + exp(-rawVal))
                    }
                }
            } finally {
                wakeResult.close()
            }
        } finally {
            wakeTensor.close()
        }

        return score
    }

    @Synchronized
    fun reset() {
        melBuffer.fill(0f)
        embBuffer.fill(0f)
        audioFloatBuffer.fill(0f)
    }

    override fun close() {
        try {
            melSession?.close()
            embSession?.close()
            wakeSession?.close()
            sessionOptions.close()
        } catch (_: Exception) {}
    }

    companion object {
        private const val TAG = "HarmaWake"
        const val SAMPLE_RATE = 16000
        const val CHUNK_SAMPLES = 1280 // 80 ms at 16 kHz
        const val MEL_CONTEXT_FRAMES = 76
        const val MEL_BANDS = 32
        const val EMB_CONTEXT_FRAMES = 16
        const val EMBEDDING_DIM = 96
    }
}

