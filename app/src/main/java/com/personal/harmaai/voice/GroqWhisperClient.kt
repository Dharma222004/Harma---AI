package com.personal.harmaai.voice

import android.util.Log
import com.personal.harmaai.perf.HarmaPerf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.ConnectionPool
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit

class GroqWhisperClient(
    private val client: OkHttpClient = defaultHttpClient,
) {
    fun preWarm(apiKey: String) {
        val trimmed = apiKey.trim()
        if (trimmed.isBlank()) return
        val req = Request.Builder()
            .url("https://api.groq.com/openai/v1/models")
            .header("Authorization", "Bearer $trimmed")
            .head()
            .build()
        client.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {}
            override fun onResponse(call: Call, response: Response) { response.close() }
        })
    }

    suspend fun transcribe(
        audioFile: File,
        apiKey: String,
        model: String = DEFAULT_MODEL,
        language: String = "en",
        prompt: String = "Hey Harma",
        sessionId: String = "",
    ): Result<String> = withContext(Dispatchers.IO) {
        val trimmedKey = apiKey.trim()
        if (trimmedKey.isBlank()) {
            Log.w(TAG, "Groq API key is blank.")
            return@withContext Result.failure(
                IllegalArgumentException("Groq API key is missing. Add your Groq API key in Harma AI Settings."),
            )
        }
        if (!audioFile.exists() || audioFile.length() == 0L) {
            Log.w(TAG, "Audio recording is empty or missing: ${audioFile.absolutePath}")
            return@withContext Result.failure(
                IllegalArgumentException("Audio recording is empty or not found."),
            )
        }

        if (sessionId.isNotBlank()) {
            HarmaPerf.onSttUploadStart(sessionId)
        }

        val mediaType = "audio/wav".toMediaType()

        var backoffMs = 1000L
        val maxAttempts = 3

        for (attempt in 1..maxAttempts) {
            val bodyBuilder = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("model", model.ifBlank { DEFAULT_MODEL })
                .addFormDataPart("response_format", "json")
                .addFormDataPart("temperature", "0")
                .addFormDataPart("prompt", prompt)
                .addFormDataPart(
                    "file",
                    audioFile.name,
                    audioFile.asRequestBody(mediaType),
                )

            val lang = language.trim().lowercase()
            if (lang.isNotBlank() && lang != "auto") {
                bodyBuilder.addFormDataPart("language", lang)
            }

            val request = Request.Builder()
                .url(ENDPOINT)
                .header("Authorization", "Bearer $trimmedKey")
                .post(bodyBuilder.build())
                .build()

            try {
                Log.d(TAG, "Sending audio to Groq Whisper (attempt $attempt, size: ${audioFile.length()} bytes, lang: $lang)...")
                client.newCall(request).execute().use { response ->
                    val responseCode = response.code
                    val responseBody = response.body?.string().orEmpty()

                    when {
                        response.isSuccessful -> {
                            val json = JSONObject(responseBody)
                            val transcript = json.optString("text").trim()
                            Log.i(TAG, "Groq Whisper transcribed successfully: \"$transcript\"")
                            if (sessionId.isNotBlank()) {
                                HarmaPerf.onSttResponse(sessionId, transcript)
                            }
                            return@withContext Result.success(transcript)
                        }

                        responseCode == 401 -> {
                            Log.e(TAG, "Groq API authentication failed (401). Invalid API key.")
                            return@withContext Result.failure(
                                IOException("Groq API key is invalid (HTTP 401). Please check your key in Settings."),
                            )
                        }

                        responseCode == 429 -> {
                            Log.w(TAG, "Groq rate limit hit (429). Backing off for ${backoffMs}ms before retry $attempt/$maxAttempts...")
                            if (attempt < maxAttempts) {
                                delay(backoffMs)
                                backoffMs *= 2
                                // continue to next attempt
                            } else {
                                return@withContext Result.failure(
                                    IOException("Groq Whisper rate limit exceeded (HTTP 429). Please try again in a moment."),
                                )
                            }
                        }

                        else -> {
                            val errorMsg = runCatching {
                                JSONObject(responseBody).optJSONObject("error")?.optString("message")
                            }.getOrNull()?.takeIf { it.isNotBlank() }
                                ?: "Groq API returned error HTTP $responseCode: $responseBody"
                            Log.e(TAG, "Groq API error: $errorMsg")
                            return@withContext Result.failure(IOException(errorMsg))
                        }
                    }
                }
            } catch (e: UnknownHostException) {
                Log.e(TAG, "No internet connection: ${e.message}")
                return@withContext Result.failure(
                    IOException("No internet connection. Harma AI needs internet access to transcribe voice with Groq."),
                )
            } catch (e: SocketTimeoutException) {
                Log.w(TAG, "Groq API request timed out on attempt $attempt.")
                if (attempt < maxAttempts) {
                    delay(backoffMs)
                    backoffMs *= 2
                } else {
                    return@withContext Result.failure(
                        IOException("Groq Whisper request timed out. Please check your network connection."),
                    )
                }
            } catch (e: Exception) {
                Log.e(TAG, "Groq transcription failed: ${e.message}", e)
                return@withContext Result.failure(e)
            }
        }

        Result.failure(IOException("Transcription failed after $maxAttempts attempts."))
    }

    companion object {
        private const val TAG = "HarmaStt"
        const val DEFAULT_MODEL = "whisper-large-v3-turbo"
        private const val ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"

        private val sharedConnectionPool = ConnectionPool(5, 5, TimeUnit.MINUTES)
        val defaultHttpClient: OkHttpClient = OkHttpClient.Builder()
            .connectionPool(sharedConnectionPool)
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
}
