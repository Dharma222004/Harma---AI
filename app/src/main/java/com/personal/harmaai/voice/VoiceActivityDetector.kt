package com.personal.harmaai.voice

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.util.ArrayDeque
import kotlin.math.sqrt

/**
 * Records 16 kHz 16-bit mono PCM with pre-roll and energy-based Voice Activity Detection (VAD).
 * Stops automatically after 1.5 seconds of silence (or 15 seconds max) and outputs a valid WAV file.
 */
class VoiceActivityDetector(private val context: Context) {

    @SuppressLint("MissingPermission")
    suspend fun recordSpeechWithVad(
        sessionId: String = "",
        onSpeechStarted: (() -> Unit)? = null,
        onRmsUpdate: ((rms: Float) -> Unit)? = null,
    ): File? = withContext(Dispatchers.IO) {
        val minBufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufferSize = minBufferSize.coerceAtLeast(FRAME_SAMPLES * 2 * 4)

        val record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize,
        )

        try {
            record.startRecording()
        } catch (e: Exception) {
            Log.e(TAG, "AudioRecord start failed: ${e.message}", e)
            return@withContext null
        }

        val tempWavFile = File(context.cacheDir, "harma_speech_${System.currentTimeMillis()}.wav")
        val pcmDataStream = ByteArrayOutputStream()

        val preRollQueue = ArrayDeque<ShortArray>(PRE_ROLL_CHUNKS)
        val frameBuffer = ShortArray(FRAME_SAMPLES)

        var speechDetected = false
        var speechStartTime = 0L
        var lastSpeechTime = 0L
        val recordingStartTime = SystemClock.uptimeMillis()

        Log.i(TAG, "Recording speech with VAD started...")

        try {
            while (true) {
                val readCount = record.read(frameBuffer, 0, frameBuffer.size)
                if (readCount <= 0) continue

                val now = SystemClock.uptimeMillis()
                val totalDuration = now - recordingStartTime

                // Hard safety limit: 15 seconds max
                if (totalDuration >= MAX_RECORDING_DURATION_MS) {
                    Log.i(TAG, "Reached maximum recording duration (15s). Stopping.")
                    break
                }

                val frameCopy = frameBuffer.copyOf(readCount)

                // Calculate RMS energy
                var sumSquares = 0.0
                for (s in frameCopy) {
                    sumSquares += (s * s).toDouble()
                }
                val rms = sqrt(sumSquares / readCount).toFloat()
                onRmsUpdate?.invoke(rms)

                if (rms >= SPEECH_RMS_THRESHOLD) {
                    if (!speechDetected) {
                        speechDetected = true
                        speechStartTime = now
                        Log.i(TAG, "Speech detected (RMS: $rms). Flushing pre-roll buffer.")
                        onSpeechStarted?.invoke()

                        // Write all pre-roll frames
                        while (preRollQueue.isNotEmpty()) {
                            val chunk = preRollQueue.removeFirst()
                            pcmDataStream.writeShorts(chunk)
                        }
                    }
                    lastSpeechTime = now
                    pcmDataStream.writeShorts(frameCopy)
                } else {
                    if (speechDetected) {
                        pcmDataStream.writeShorts(frameCopy)
                        val speechDuration = now - speechStartTime
                        val silenceDuration = now - lastSpeechTime
                        // Stop after 800ms of silence, ensuring minimum speech duration
                        if (silenceDuration >= SILENCE_TIMEOUT_MS && speechDuration >= MIN_SPEECH_DURATION_MS) {
                            Log.i(TAG, "Silence detected (${silenceDuration}ms, speech was ${speechDuration}ms). Speech completed.")
                            break
                        }
                    } else {
                        // Maintain rolling pre-roll buffer (~400ms)
                        if (preRollQueue.size >= PRE_ROLL_CHUNKS) {
                            preRollQueue.removeFirst()
                        }
                        preRollQueue.addLast(frameCopy)

                        // If user never speaks within 6 seconds, abort cleanly
                        if (totalDuration >= INITIAL_WAIT_TIMEOUT_MS) {
                            Log.i(TAG, "No speech detected within ${INITIAL_WAIT_TIMEOUT_MS}ms. Aborting.")
                            return@withContext null
                        }
                    }
                }
            }
        } finally {
            try {
                record.stop()
                record.release()
            } catch (_: Exception) {}
        }

        val rawPcm = pcmDataStream.toByteArray()
        if (rawPcm.isEmpty() || !speechDetected) {
            Log.w(TAG, "No valid speech audio collected.")
            return@withContext null
        }

        // Write as valid 16 kHz 16-bit mono WAV file
        writeWavFile(tempWavFile, rawPcm)
        Log.i(TAG, "WAV audio written to ${tempWavFile.absolutePath} (${tempWavFile.length()} bytes)")
        return@withContext tempWavFile
    }

    private fun ByteArrayOutputStream.writeShorts(shorts: ShortArray) {
        val bytes = ByteArray(shorts.size * 2)
        var bi = 0
        for (s in shorts) {
            bytes[bi++] = (s.toInt() and 0xFF).toByte()
            bytes[bi++] = ((s.toInt() shr 8) and 0xFF).toByte()
        }
        write(bytes, 0, bytes.size)
    }

    private fun writeWavFile(file: File, pcmData: ByteArray) {
        FileOutputStream(file).use { out ->
            val totalDataLen = pcmData.size + 36
            val byteRate = SAMPLE_RATE * CHANNELS * 2

            // RIFF chunk descriptor
            out.write("RIFF".toByteArray())
            out.writeIntLittleEndian(totalDataLen)
            out.write("WAVE".toByteArray())

            // fmt sub-chunk
            out.write("fmt ".toByteArray())
            out.writeIntLittleEndian(16) // Subchunk1Size (16 for PCM)
            out.writeShortLittleEndian(1) // AudioFormat (1 for PCM)
            out.writeShortLittleEndian(CHANNELS.toShort())
            out.writeIntLittleEndian(SAMPLE_RATE)
            out.writeIntLittleEndian(byteRate)
            out.writeShortLittleEndian((CHANNELS * 2).toShort()) // BlockAlign
            out.writeShortLittleEndian(16) // BitsPerSample

            // data sub-chunk
            out.write("data".toByteArray())
            out.writeIntLittleEndian(pcmData.size)
            out.write(pcmData)
        }
    }

    private fun FileOutputStream.writeIntLittleEndian(value: Int) {
        write(value and 0xFF)
        write((value shr 8) and 0xFF)
        write((value shr 16) and 0xFF)
        write((value shr 24) and 0xFF)
    }

    private fun FileOutputStream.writeShortLittleEndian(value: Short) {
        write(value.toInt() and 0xFF)
        write((value.toInt() shr 8) and 0xFF)
    }

    companion object {
        private const val TAG = "HarmaRecord"
        const val SAMPLE_RATE = 16000
        private const val CHANNELS = 1
        private const val FRAME_SAMPLES = 640 // 40 ms
        private const val PRE_ROLL_CHUNKS = 10 // 10 x 40ms = 400ms pre-roll
        private const val SPEECH_RMS_THRESHOLD = 160f
        private const val SILENCE_TIMEOUT_MS = 1500L
        private const val MIN_SPEECH_DURATION_MS = 250L
        private const val INITIAL_WAIT_TIMEOUT_MS = 6000L
        private const val MAX_RECORDING_DURATION_MS = 15000L
    }
}

