package com.personal.harmaai.network

import com.personal.harmaai.agent.AgentSystemPrompt
import com.personal.harmaai.perf.HarmaPerf
import com.personal.harmaai.tools.ToolSpec
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.ConnectionPool
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.pow
import kotlin.random.Random

class AgentLlmException(
    val statusCode: Int,
    val providerCode: String = "",
    val retryable: Boolean = false,
    message: String,
) : IOException(message)

/** NVIDIA NIM/OpenAI-compatible adapter. No API key or hidden reasoning is logged or surfaced. */
class NvidiaAgentClient(
    private val httpClient: OkHttpClient = defaultClient,
) : AgentLlmClient {
    @Volatile
    private var preferredWorkingModel: String? = null

    override suspend fun decide(
        apiKey: String,
        models: List<String>,
        history: List<AgentMessage>,
        tools: List<ToolSpec>,
        sessionId: String,
    ): AgentDecision {
        require(apiKey.isNotBlank()) {
            "NVIDIA API key is missing. Open Harma AI Settings."
        }
        val configured = models
            .map(String::trim)
            .filter(String::isNotBlank)
            .filter(::isValidModelName)
            .distinct()
        require(configured.isNotEmpty()) { "No valid NVIDIA model is configured." }

        val candidates = buildList {
            preferredWorkingModel?.takeIf(configured::contains)?.let(::add)
            addAll(configured)
        }.distinct()

        var lastError: Exception? = null
        for ((index, model) in candidates.withIndex()) {
            try {
                val decision = requestModelWithRetry(
                    apiKey = apiKey.trim(),
                    model = model,
                    history = history,
                    tools = tools,
                    sessionId = sessionId,
                )
                preferredWorkingModel = model
                return decision.copy(
                    fallbackFrom = configured.firstOrNull()
                        ?.takeIf { index > 0 && it != decision.modelUsed },
                )
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (error: AgentLlmException) {
                lastError = error
                if (!error.retryable || index == candidates.lastIndex) throw error
            } catch (error: IOException) {
                lastError = error
                if (index == candidates.lastIndex) throw error
            }
        }
        throw lastError ?: IOException("No NVIDIA model was available.")
    }

    private suspend fun requestModelWithRetry(
        apiKey: String,
        model: String,
        history: List<AgentMessage>,
        tools: List<ToolSpec>,
        sessionId: String,
    ): AgentDecision {
        val body = buildRequestBody(model, history, tools).toString()
        if (sessionId.isNotBlank()) {
            HarmaPerf.onLlmRequestSent(sessionId, model, body.length / 4)
        }
        var lastError: Exception? = null

        for (attempt in 0 until MAX_REQUEST_ATTEMPTS) {
            val request = Request.Builder()
                .url(CHAT_COMPLETIONS_URL)
                .header("Authorization", "Bearer $apiKey")
                .header("Accept", "text/event-stream, application/json")
                .post(body.toRequestBody(JSON_MEDIA_TYPE))
                .build()

            try {
                val response = httpClient.newCall(request).await()
                try {
                    val contentType = response.header("Content-Type").orEmpty().lowercase()
                    if (response.isSuccessful && contentType.contains("text/event-stream")) {
                        val decision = parseStreamingDecision(response, model, sessionId)
                        if (sessionId.isNotBlank()) {
                            HarmaPerf.onLlmResponse(sessionId, if (decision.toolCall != null) 1 else 0)
                        }
                        return decision
                    }

                    val raw = response.body?.string().orEmpty()
                    if (response.code == 202 && !hasChoices(raw)) {
                        val error = AgentLlmException(
                            statusCode = 202,
                            providerCode = "accepted",
                            retryable = true,
                            message = "NVIDIA accepted the request but the result is not ready yet.",
                        )
                        lastError = error
                        if (attempt == MAX_REQUEST_ATTEMPTS - 1) throw error
                        delay(retryDelayMillis(response, attempt))
                        continue
                    }
                    if (!response.isSuccessful) {
                        val error = parseHttpError(response.code, raw)
                        lastError = error
                        if (!error.retryable || attempt == MAX_REQUEST_ATTEMPTS - 1) throw error
                        delay(retryDelayMillis(response, attempt))
                        continue
                    }
                    val decision = parseDecision(raw, model)
                    if (sessionId.isNotBlank()) {
                        HarmaPerf.onLlmResponse(sessionId, if (decision.toolCall != null) 1 else 0)
                    }
                    return decision
                } finally {
                    response.close()
                }
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (error: AgentLlmException) {
                lastError = error
                if (!error.retryable || attempt == MAX_REQUEST_ATTEMPTS - 1) throw error
                delay(defaultBackoffMillis(attempt))
            } catch (error: IOException) {
                lastError = error
                if (attempt == MAX_REQUEST_ATTEMPTS - 1) throw error
                delay(defaultBackoffMillis(attempt))
            }
        }
        throw lastError ?: IOException("NVIDIA request failed.")
    }

    private fun parseStreamingDecision(response: Response, requestedModel: String, sessionId: String): AgentDecision {
        val source = response.body?.source() ?: throw malformedResponse("Empty streaming response body")
        var firstTokenSeen = false
        val toolBuilders = mutableMapOf<Int, Triple<StringBuilder, StringBuilder, StringBuilder>>()
        val textBuilder = StringBuilder()
        var finishReason = ""
        var modelUsed = requestedModel

        while (!source.exhausted()) {
            val line = source.readUtf8Line() ?: break
            val trimmed = line.trim()
            if (!trimmed.startsWith("data:")) continue
            val data = trimmed.removePrefix("data:").trim()
            if (data == "[DONE]") break
            if (data.isBlank()) continue

            val json = try { JSONObject(data) } catch (_: Exception) { continue }
            if (!firstTokenSeen) {
                firstTokenSeen = true
                if (sessionId.isNotBlank()) HarmaPerf.onLlmFirstToken(sessionId)
            }
            json.optString("model").takeIf { it.isNotBlank() }?.let { modelUsed = it }
            val choices = json.optJSONArray("choices") ?: continue
            if (choices.length() == 0) continue
            val choice = choices.getJSONObject(0)
            choice.optString("finish_reason").takeIf { it.isNotBlank() }?.let { finishReason = it }
            val delta = choice.optJSONObject("delta") ?: continue
            delta.optString("content").takeIf { it.isNotBlank() }?.let { textBuilder.append(it) }

            val callsArray = delta.optJSONArray("tool_calls")
            if (callsArray != null) {
                for (i in 0 until callsArray.length()) {
                    val item = callsArray.getJSONObject(i)
                    val idx = item.optInt("index", 0)
                    val entry = toolBuilders.getOrPut(idx) { Triple(StringBuilder(), StringBuilder(), StringBuilder()) }
                    item.optString("id").takeIf { it.isNotBlank() }?.let { entry.first.append(it) }
                    val func = item.optJSONObject("function")
                    if (func != null) {
                        func.optString("name").takeIf { it.isNotBlank() }?.let { entry.second.append(it) }
                        func.optString("arguments").takeIf { it.isNotBlank() }?.let { entry.third.append(it) }
                    }
                }
            }
        }

        val parsedCalls = mutableListOf<AgentLlmToolCall>()
        for ((idx, entry) in toolBuilders) {
            val id = entry.first.toString().ifBlank { "call_$idx" }
            val name = entry.second.toString().trim()
            val argsStr = entry.third.toString().trim().ifBlank { "{}" }
            val argsJson = try {
                JSONObject(argsStr)
            } catch (_: Exception) {
                JSONObject()
            }
            if (name.isNotBlank()) {
                parsedCalls.add(AgentLlmToolCall(id = id, name = name, arguments = argsJson))
            }
        }

        val text = textBuilder.toString().trim()
        val assistant = AgentMessage.Assistant(
            text = text,
            toolCalls = parsedCalls,
            reasoningContent = "",
        )
        return AgentDecision(
            text = text,
            toolCall = parsedCalls.firstOrNull(),
            assistantMessage = assistant,
            modelUsed = modelUsed,
            finishReason = finishReason,
        )
    }

    internal fun buildRequestBody(
        model: String,
        history: List<AgentMessage>,
        tools: List<ToolSpec>,
    ): JSONObject {
        val messages = JSONArray().put(
            JSONObject()
                .put("role", "system")
                .put("content", AgentSystemPrompt.text),
        )
        history.forEach { messages.put(serializeMessage(it)) }

        val toolArray = JSONArray().also { array ->
            tools.forEach { spec ->
                array.put(
                    JSONObject()
                        .put("type", "function")
                        .put(
                            "function",
                            JSONObject()
                                .put("name", spec.name)
                                .put("description", spec.description)
                                .put("parameters", normalizeSchema(spec.parameters)),
                        ),
                )
            }
        }

        return JSONObject()
            .put("model", model)
            .put("messages", messages)
            .put("tools", toolArray)
            .put("tool_choice", "auto")
            .put("parallel_tool_calls", false)
            .put("stream", true)
            .put("temperature", 0.0)
            .put("max_tokens", MAX_OUTPUT_TOKENS)
            .put(
                "chat_template_kwargs",
                JSONObject().put("enable_thinking", false),
            )
    }

    internal fun parseDecision(raw: String, requestedModel: String): AgentDecision {
        val root = try {
            JSONObject(raw)
        } catch (_: JSONException) {
            throw malformedResponse("NVIDIA returned invalid JSON.")
        }
        val choices = root.optJSONArray("choices")
            ?: throw malformedResponse("NVIDIA returned no choices.")
        if (choices.length() == 0) throw malformedResponse("NVIDIA returned an empty choice list.")

        val choice = choices.optJSONObject(0)
            ?: throw malformedResponse("NVIDIA returned an invalid choice.")
        val message = choice.optJSONObject("message")
            ?: throw malformedResponse("NVIDIA returned no assistant message.")
        val text = extractText(message.opt("content"))
        val reasoning = message.optString("reasoning_content")
            .ifBlank { message.optString("reasoning") }

        val parsedCalls = mutableListOf<AgentLlmToolCall>()
        message.optJSONArray("tool_calls")?.let { calls ->
            if (calls.length() > 1) {
                throw malformedResponse(
                    "NVIDIA returned multiple parallel tool calls even though parallel calls are disabled.",
                )
            }
            for (index in 0 until calls.length()) {
                val item = calls.optJSONObject(index)
                    ?: throw malformedResponse("NVIDIA returned an invalid tool call.")
                val id = item.optString("id").trim()
                val function = item.optJSONObject("function")
                    ?: throw malformedResponse("NVIDIA tool call has no function payload.")
                val name = function.optString("name").trim()
                if (id.isBlank() || name.isBlank()) {
                    throw malformedResponse("NVIDIA tool call is missing its ID or function name.")
                }
                val arguments = parseArguments(function.opt("arguments"))
                parsedCalls += AgentLlmToolCall(id = id, name = name, arguments = arguments)
            }
        }

        val assistant = AgentMessage.Assistant(
            text = text,
            toolCalls = parsedCalls,
            reasoningContent = reasoning,
        )
        return AgentDecision(
            text = text,
            toolCall = parsedCalls.firstOrNull(),
            assistantMessage = assistant,
            modelUsed = root.optString("model").ifBlank { requestedModel },
            finishReason = choice.optString("finish_reason"),
        )
    }

    private fun serializeMessage(message: AgentMessage): JSONObject = when (message) {
        is AgentMessage.User -> JSONObject()
            .put("role", "user")
            .put("content", userContent(message))

        is AgentMessage.Assistant -> JSONObject()
            .put("role", "assistant")
            .apply {
                if (message.text.isNotBlank()) {
                    put("content", message.text)
                } else if (message.toolCalls.isNotEmpty()) {
                    put("content", JSONObject.NULL)
                } else {
                    put("content", "")
                }
                if (message.reasoningContent.isNotBlank()) {
                    put("reasoning_content", message.reasoningContent)
                }
                if (message.toolCalls.isNotEmpty()) {
                    put(
                        "tool_calls",
                        JSONArray().also { calls ->
                            message.toolCalls.forEach { call ->
                                calls.put(
                                    JSONObject()
                                        .put("id", call.id)
                                        .put("type", "function")
                                        .put(
                                            "function",
                                            JSONObject()
                                                .put("name", call.name)
                                                .put("arguments", call.arguments.toString()),
                                        ),
                                )
                            }
                        },
                    )
                }
            }

        is AgentMessage.Tool -> JSONObject()
            .put("role", "tool")
            .put("tool_call_id", message.toolCallId)
            .put("name", message.toolName)
            .put("content", message.content)
    }

    private fun userContent(message: AgentMessage.User): Any {
        if (message.jpegBase64.isBlank()) return message.text
        return JSONArray()
            .put(JSONObject().put("type", "text").put("text", message.text))
            .put(
                JSONObject()
                    .put("type", "image_url")
                    .put(
                        "image_url",
                        JSONObject().put(
                            "url",
                            "data:image/jpeg;base64,${message.jpegBase64}",
                        ),
                    ),
            )
    }

    private fun normalizeSchema(source: JSONObject): JSONObject = JSONObject().also { normalized ->
        source.keys().forEach { key ->
            val value = source.opt(key)
            normalized.put(
                key,
                when (value) {
                    is JSONObject -> normalizeSchema(value)
                    is JSONArray -> normalizeArray(value)
                    is String -> if (key == "type") value.lowercase() else value
                    else -> value
                },
            )
        }
    }

    private fun normalizeArray(source: JSONArray): JSONArray = JSONArray().also { normalized ->
        for (index in 0 until source.length()) {
            normalized.put(
                when (val value = source.opt(index)) {
                    is JSONObject -> normalizeSchema(value)
                    is JSONArray -> normalizeArray(value)
                    else -> value
                },
            )
        }
    }

    private fun parseArguments(raw: Any?): JSONObject = when (raw) {
        is JSONObject -> JSONObject(raw.toString())
        is String -> if (raw.isBlank()) {
            JSONObject()
        } else {
            try {
                JSONObject(raw)
            } catch (_: JSONException) {
                throw malformedResponse("NVIDIA returned invalid tool arguments.")
            }
        }
        null, JSONObject.NULL -> JSONObject()
        else -> throw malformedResponse("NVIDIA returned unsupported tool arguments.")
    }

    private fun extractText(content: Any?): String = when (content) {
        is String -> content
        is JSONObject -> content.optString("text")
        is JSONArray -> buildString {
            for (index in 0 until content.length()) {
                val part = content.optJSONObject(index) ?: continue
                val value = part.optString("text")
                if (value.isNotBlank()) {
                    if (isNotEmpty()) append('\n')
                    append(value)
                }
            }
        }
        else -> ""
    }.trim()

    private fun parseHttpError(statusCode: Int, raw: String): AgentLlmException {
        val root = runCatching { JSONObject(raw) }.getOrNull()
        val error = root?.optJSONObject("error")
        val providerCode = error?.optString("code")
            ?.ifBlank { root.optString("code") }
            .orEmpty()
        val message = error?.optString("message")
            ?.ifBlank { root.optString("detail") }
            ?.ifBlank { root.optString("message") }
            .orEmpty()
        return AgentLlmException(
            statusCode = statusCode,
            providerCode = providerCode,
            retryable = isRetryableStatus(statusCode),
            message = message.ifBlank { "NVIDIA request failed with HTTP $statusCode." },
        )
    }

    private fun retryDelayMillis(response: Response, attempt: Int): Long =
        retryAfterMillis(response.header("Retry-After")) ?: defaultBackoffMillis(attempt)

    private fun defaultBackoffMillis(attempt: Int): Long {
        val base = (800.0 * 2.0.pow(attempt.toDouble())).toLong().coerceAtMost(5_000L)
        return base + Random.nextLong(0L, 251L)
    }

    private fun hasChoices(raw: String): Boolean = runCatching {
        JSONObject(raw).optJSONArray("choices")?.length()?.let { it > 0 } == true
    }.getOrDefault(false)

    private fun malformedResponse(message: String): AgentLlmException =
        AgentLlmException(
            statusCode = 502,
            providerCode = "malformed_response",
            retryable = true,
            message = message,
        )

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
        const val DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
        const val BASE_URL = "https://integrate.api.nvidia.com/v1"

        private const val CHAT_COMPLETIONS_URL = "$BASE_URL/chat/completions"
        private const val MAX_OUTPUT_TOKENS = 512
        private const val MAX_REQUEST_ATTEMPTS = 2
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        private val MODEL_NAME = Regex("[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")

        private val sharedConnectionPool = ConnectionPool(5, 5, TimeUnit.MINUTES)
        val defaultClient: OkHttpClient = OkHttpClient.Builder()
            .connectionPool(sharedConnectionPool)
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()

        fun preWarm(apiKey: String) {
            val key = apiKey.trim()
            if (key.isBlank()) return
            val request = Request.Builder()
                .url(CHAT_COMPLETIONS_URL)
                .header("Authorization", "Bearer $key")
                .head()
                .build()
            defaultClient.newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {}
                override fun onResponse(call: Call, response: Response) { response.close() }
            })
        }

        suspend fun testConnection(apiKey: String): Pair<Boolean, String> = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val key = apiKey.trim()
            if (key.isBlank()) return@withContext false to "API key is blank."
            try {
                val request = Request.Builder()
                    .url(CHAT_COMPLETIONS_URL)
                    .header("Authorization", "Bearer $key")
                    .head()
                    .build()
                defaultClient.newCall(request).execute().use { response ->
                    if (response.code in 200..499 && response.code != 401 && response.code != 403) {
                        true to "Connected to NVIDIA NIM successfully! (HTTP ${response.code})"
                    } else if (response.code == 401 || response.code == 403) {
                        false to "Authentication failed (HTTP ${response.code}). Check API key."
                    } else {
                        false to "Server returned HTTP ${response.code}"
                    }
                }
            } catch (e: Exception) {
                false to "Connection failed: ${e.message ?: "Network error"}"
            }
        }

        fun isValidModelName(model: String): Boolean =
            MODEL_NAME.matches(model) && !model.contains("..") && !model.contains("//")

        fun isRetryableStatus(statusCode: Int): Boolean =
            statusCode == 202 || statusCode == 408 || statusCode == 409 ||
                statusCode == 425 || statusCode == 429 || statusCode >= 500

        internal fun retryAfterMillis(
            value: String?,
            nowMillis: Long = System.currentTimeMillis(),
        ): Long? {
            val normalized = value?.trim().orEmpty()
            if (normalized.isBlank()) return null
            normalized.toLongOrNull()?.let { seconds ->
                return seconds.coerceIn(0L, 30L) * 1_000L
            }
            return runCatching {
                val target = ZonedDateTime.parse(
                    normalized,
                    DateTimeFormatter.RFC_1123_DATE_TIME,
                ).toInstant().toEpochMilli()
                (target - nowMillis).coerceIn(0L, 30_000L)
            }.getOrNull()
        }
    }
}
