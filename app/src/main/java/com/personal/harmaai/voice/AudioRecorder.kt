package com.personal.harmaai.voice

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

class AudioRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null
    private var isRecording = false

    fun startRecording(): File {
        cancel()
        val file = File(context.cacheDir, "harma_voice_${System.currentTimeMillis()}.m4a")
        outputFile = file

        val mr = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

        mr.apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setAudioSamplingRate(16000)
            setAudioEncodingBitRate(64000)
            setOutputFile(file.absolutePath)
            prepare()
            start()
        }
        recorder = mr
        isRecording = true
        return file
    }

    fun stopRecording(): File? {
        if (!isRecording) return null
        return try {
            recorder?.stop()
            recorder?.release()
            recorder = null
            isRecording = false
            outputFile?.takeIf { it.exists() && it.length() > 0 }
        } catch (_: Exception) {
            recorder?.release()
            recorder = null
            isRecording = false
            null
        }
    }

    fun cancel() {
        try {
            if (isRecording) {
                recorder?.stop()
            }
        } catch (_: Exception) {}
        recorder?.release()
        recorder = null
        isRecording = false
        outputFile?.delete()
        outputFile = null
    }

    fun isRecording(): Boolean = isRecording
}
