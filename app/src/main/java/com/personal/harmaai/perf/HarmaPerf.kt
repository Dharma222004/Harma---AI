package com.personal.harmaai.perf

import android.os.SystemClock
import android.util.Log
import java.util.concurrent.ConcurrentHashMap

/**
 * Performance measurement and timing tracer for Harma AI.
 * Logs timing data under tag "HarmaPerf" for each pipeline stage.
 */
object HarmaPerf {
    const val TAG = "HarmaPerf"

    private class CommandMetrics(val command: String, val startedUptimeMs: Long) {
        var wakeWordDetectedAt: Long = 0L
        var speechRecordStartAt: Long = 0L
        var speechRecordStopAt: Long = 0L
        var sttUploadStartAt: Long = 0L
        var sttResponseAt: Long = 0L
        var fastRouterCheckMs: Long = 0L
        var fastRouterMatched: Boolean = false
        var fastRouterAction: String = ""

        var llmRequestSentAt: Long = 0L
        var llmFirstTokenAt: Long = 0L
        var llmResponseAt: Long = 0L
        var llmModel: String = ""

        var screenCaptureTimeMs: Long = 0L
        var screenCharCount: Int = 0
        var screenEstTokens: Int = 0
        var screenNodeCount: Int = 0

        var toolExecTimeMs: Long = 0L
        var toolName: String = ""
        var postActionWaitMs: Long = 0L

        var completedAt: Long = 0L
    }

    private val activeMetrics = ConcurrentHashMap<String, CommandMetrics>()
    @Volatile
    private var lastCompletedMetrics: CommandMetrics? = null

    fun onWakeWordDetected(model: String) {
        val now = SystemClock.uptimeMillis()
        Log.i(TAG, "[$model] Wake word detected at ${now}ms")
    }

    fun onSpeechRecordStart(sessionId: String) {
        val now = SystemClock.uptimeMillis()
        val metrics = CommandMetrics(sessionId, now).apply {
            speechRecordStartAt = now
        }
        activeMetrics[sessionId] = metrics
        Log.i(TAG, "[$sessionId] Recording started")
    }

    fun onSpeechRecordStop(sessionId: String) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics[sessionId] ?: return
        m.speechRecordStopAt = now
        val duration = now - m.speechRecordStartAt
        Log.i(TAG, "[$sessionId] Recording stopped. Speech audio duration: ${duration}ms")
    }

    fun onSttUploadStart(sessionId: String) {
        val now = SystemClock.uptimeMillis()
        activeMetrics[sessionId]?.sttUploadStartAt = now
        Log.i(TAG, "[$sessionId] STT upload started to Groq Whisper")
    }

    fun onSttResponse(sessionId: String, transcript: String) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics[sessionId] ?: return
        m.sttResponseAt = now
        val sttLatency = now - m.sttUploadStartAt
        Log.i(TAG, "[$sessionId] STT complete in ${sttLatency}ms: \"$transcript\"")
    }

    fun onFastRouterCheck(sessionId: String, matched: Boolean, action: String, durationMs: Long) {
        val m = activeMetrics[sessionId] ?: return
        m.fastRouterMatched = matched
        m.fastRouterAction = action
        m.fastRouterCheckMs = durationMs
        Log.i(TAG, "[$sessionId] Fast router check: matched=$matched action=\"$action\" took ${durationMs}ms")
    }

    fun onLlmRequestSent(sessionId: String, model: String, promptTokensEst: Int) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics[sessionId] ?: return
        m.llmRequestSentAt = now
        m.llmModel = model
        Log.i(TAG, "[$sessionId] LLM request sent to $model (~$promptTokensEst prompt tokens)")
    }

    fun onLlmFirstToken(sessionId: String) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics[sessionId] ?: return
        m.llmFirstTokenAt = now
        val ttft = now - m.llmRequestSentAt
        Log.i(TAG, "[$sessionId] LLM first token received (TTFT: ${ttft}ms)")
    }

    fun onLlmResponse(sessionId: String, toolsCount: Int) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics[sessionId] ?: return
        m.llmResponseAt = now
        val duration = now - m.llmRequestSentAt
        Log.i(TAG, "[$sessionId] LLM response received in ${duration}ms (tools returned: $toolsCount)")
    }

    fun onGetScreen(sessionId: String, durationMs: Long, nodes: Int, chars: Int, estTokens: Int) {
        val m = activeMetrics[sessionId] ?: return
        m.screenCaptureTimeMs += durationMs
        m.screenNodeCount = nodes
        m.screenCharCount = chars
        m.screenEstTokens = estTokens
        Log.i(TAG, "[$sessionId] get_screen: ${durationMs}ms ($nodes nodes, $chars chars, ~$estTokens tokens)")
    }

    fun onToolExecution(sessionId: String, toolName: String, durationMs: Long, success: Boolean) {
        val m = activeMetrics[sessionId] ?: return
        m.toolName = toolName
        m.toolExecTimeMs += durationMs
        Log.i(TAG, "[$sessionId] tool_call [$toolName]: ${durationMs}ms (success=$success)")
    }

    fun onWaitAfterAction(sessionId: String, waitMs: Long, reason: String) {
        val m = activeMetrics[sessionId] ?: return
        m.postActionWaitMs += waitMs
        Log.i(TAG, "[$sessionId] post-action wait [$reason]: ${waitMs}ms")
    }

    fun onTaskFinished(sessionId: String, summary: String) {
        val now = SystemClock.uptimeMillis()
        val m = activeMetrics.remove(sessionId) ?: return
        m.completedAt = now
        lastCompletedMetrics = m

        val endOfSpeech = if (m.speechRecordStopAt > 0) m.speechRecordStopAt else m.speechRecordStartAt
        val totalFromEndOfSpeech = (now - endOfSpeech).coerceAtLeast(0L)
        val sttLatency = if (m.sttResponseAt > 0 && m.sttUploadStartAt > 0) m.sttResponseAt - m.sttUploadStartAt else 0L
        val llmLatency = if (m.llmResponseAt > 0 && m.llmRequestSentAt > 0) m.llmResponseAt - m.llmRequestSentAt else 0L

        Log.i(
            TAG,
            """
            ====================== HarmaPerf Summary ======================
            Command: "${m.command}"
            End-of-speech to Task Finished: ${totalFromEndOfSpeech}ms
            - STT Latency: ${sttLatency}ms
            - Fast Router: matched=${m.fastRouterMatched} (${m.fastRouterCheckMs}ms)
            - LLM (${m.llmModel}): ${llmLatency}ms (TTFT: ${if (m.llmFirstTokenAt > 0) m.llmFirstTokenAt - m.llmRequestSentAt else 0}ms)
            - Screen Reading: ${m.screenCaptureTimeMs}ms (${m.screenNodeCount} nodes, ${m.screenCharCount} chars)
            - Tool Execution (${m.toolName}): ${m.toolExecTimeMs}ms
            - Post-Action Waits: ${m.postActionWaitMs}ms
            Summary: $summary
            ================================================================
            """.trimIndent(),
        )
    }

    fun getStageTiming(
        sttMs: Long,
        routerMs: Long,
        llmMs: Long,
        screenMs: Long,
        toolMs: Long,
        waitMs: Long,
    ): Long = sttMs + routerMs + llmMs + screenMs + toolMs + waitMs
}
