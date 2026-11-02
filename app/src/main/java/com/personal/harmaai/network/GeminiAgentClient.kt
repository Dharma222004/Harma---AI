package com.personal.harmaai.network

import com.personal.harmaai.agent.AgentSystemPrompt
import com.personal.harmaai.agent.AgentToolCall
import com.personal.harmaai.accessibility.ScreenObservation
import com.personal.harmaai.tools.ToolResult
import com.personal.harmaai.tools.ToolSpec
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class GeminiDecision(
    val text: String,
    val toolCall: AgentToolCall?,
    val modelContent: JSONObject,
    val modelUsed: String,
    val fallbackFrom: String? = null,
)

private class GeminiApiException(
    val statusCode: Int,
    message: String,
) : IOException(message)

class GeminiAgentClient(
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build(),
) {
    @Volatile
    private var preferredWorkingModel: String? = null

    suspend fun decide(
        apiKey: String,
        models: List<String>,
        history: List<JSONObject>,
        tools: List<ToolSpec>,
    ): GeminiDecision {
        require(apiKey.isNotBlank()) { "Gemini API key is missing. Open Harma AI Settings." }
        val configured = models.map(String::trim).filter(String::isNotBlank).distinct()
        val candidates = buildList {
            preferredWorkingModel?.takeIf(configured::contains)?.let(::add)
            addAll(configured)
        }.distinct()
        require(candidates.isNotEmpty()) { "No Gemini model is configured." }

        var lastError: Exception? = null
        for ((index, model) in candidates.withIndex()) {
            if (!MODEL_NAME.matches(model)) continue
            try {
                val decision = requestModel(apiKey, model, history, tools).copy(
                    fallbackFrom = candidates.firstOrNull()?.takeIf { index > 0 },
                )
                preferredWorkingModel = decision.modelUsed
                return decision
            } catch (error: GeminiApiException) {
                lastError = error
                val retryable = error.statusCode == 404 || error.statusCode == 408 ||
                    error.statusCode == 429 || error.statusCode >= 500
                if (!retryable || index == candidates.lastIndex) throw error
                if (error.statusCode == 429 || error.statusCode >= 500) {
                    delay((800L * (index + 1)).coerceAtMost(3_000L))
                }
            } catch (error: IOException) {
                lastError = error
                if (index == candidates.lastIndex) throw error
                delay(500L)
            }
        }
        throw lastError ?: IOException("No valid Gemini model was available.")
    }

    fun initialContent(
        task: String,
        observation: ScreenObservation?,
        screenshotBase64: String = "",
        memory: String = "",
    ): JSONObject {
        val parts = JSONArray().put(
            JSONObject().put(
                "text",
                buildString {
                    append("User task: ").append(task)
                    if (memory.isNotBlank()) append("\nRelevant local memory:\n").append(memory)
                    append("\nCurrent phone observation:\n")
                    append(observation?.compactJson ?: "Accessibility service is not connected.")
                },
            ),
        )
        addScreenshotPart(parts, screenshotBase64)
        return JSONObject().put("role", "user").put("parts", parts)
    }

    fun toolResponseContent(
        call: AgentToolCall,
        result: ToolResult,
        observation: ScreenObservation?,
        screenshotBase64: String = "",
    ): JSONObject {
        val responsePayload = JSONObject()
            .put("success", result.success)
            .put("message", result.message)
            .put("code", result.code)
            .put("data", result.data)
            .put("newScreen", observation?.compactJson ?: "Accessibility service is not connected.")

        val parts = JSONArray().put(
            JSONObject().put(
                "functionResponse",
                JSONObject()
                    .put("name", call.name)
                    .put("response", responsePayload),
            ),
        )
        addScreenshotPart(parts, screenshotBase64)
        return JSONObject().put("role", "user").put("parts", parts)
    }

    private suspend fun requestModel(
        apiKey: String,
        model: String,
        history: List<JSONObject>,
        tools: List<ToolSpec>,
    ): GeminiDecision {
        val historyJson = JSONArray().also { array -> history.forEach(array::put) }
        val declarations = JSONArray().also { array ->
            tools.forEach { spec ->
                array.put(
                    JSONObject()
                        .put("name", spec.name)
                        .put("description", spec.description)
                        .put("parameters", spec.parameters),
                )
            }
        }
        val body = JSONObject()
            .put(
                "systemInstruction",
                JSONObject().put(
                    "parts",
                    JSONArray().put(JSONObject().put("text", AgentSystemPrompt.text)),
                ),
            )
            .put("contents", historyJson)
            .put(
                "tools",
                JSONArray().put(JSONObject().put("functionDeclarations", declarations)),
            )
            .put(
                "toolConfig",
                JSONObject().put(
                    "functionCallingConfig",
                    JSONObject().put("mode", "AUTO"),
                ),
            )
            .put(
                "generationConfig",
                JSONObject()
                    .put("temperature", 0.1)
                    .put("maxOutputTokens", 1400),
            )

        val request = Request.Builder()
            .url("https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent")
            .header("x-goog-api-key", apiKey)
            .post(body.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()

        val response = httpClient.newCall(request).await()
        response.use {
            val raw = it.body?.string().orEmpty()
            if (!it.isSuccessful) {
                val message = runCatching {
                    JSONObject(raw).optJSONObject("error")?.optString("message")
                }.getOrNull().orEmpty()
                throw GeminiApiException(
                    it.code,
                    message.ifBlank { "Gemini request failed with HTTP ${it.code}." },
                )
            }

            val root = JSONObject(raw)
            root.optJSONObject("promptFeedback")?.optString("blockReason")
                ?.takeIf(String::isNotBlank)
                ?.let { reason -> throw GeminiApiException(400, "Gemini blocked the request: $reason") }

            val candidates = root.optJSONArray("candidates")
                ?: throw GeminiApiException(502, "Gemini returned no candidates.")
            if (candidates.length() == 0) {
                throw GeminiApiException(502, "Gemini returned an empty candidate list.")
            }

            val modelContent = candidates.getJSONObject(0).getJSONObject("content")
            val parts = modelContent.optJSONArray("parts") ?: JSONArray()
            var call: AgentToolCall? = null
            val text = buildString {
                for (partIndex in 0 until parts.length()) {
                    val part = parts.optJSONObject(partIndex) ?: continue
                    val partText = part.optString("text")
                    if (partText.isNotBlank()) {
                        if (isNotEmpty()) append('\n')
                        append(partText)
                    }
                    part.optJSONObject("functionCall")?.let { functionCall ->
                        if (call == null) {
                            call = AgentToolCall(
                                name = functionCall.optString("name"),
                                arguments = functionCall.optJSONObject("args") ?: JSONObject(),
                            )
                        }
                    }
                }
            }.trim()
            return GeminiDecision(
                text = text,
                toolCall = call,
                modelContent = modelContent,
                modelUsed = model,
            )
        }
    }

    private fun addScreenshotPart(parts: JSONArray, screenshotBase64: String) {
        if (screenshotBase64.isBlank()) return
        parts.put(
            JSONObject().put(
                "inlineData",
                JSONObject()
                    .put("mimeType", "image/jpeg")
                    .put("data", screenshotBase64),
            ),
        )
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { cancel() }
        enqueue(
            object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    if (continuation.isActive) continuation.resume(response) else response.close()
                }
            },
        )
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        private val MODEL_NAME = Regex("[A-Za-z0-9._-]+")
    }
}
