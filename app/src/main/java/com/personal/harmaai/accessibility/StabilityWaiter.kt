package com.personal.harmaai.accessibility

import android.os.SystemClock
import kotlinx.coroutines.delay

/**
 * Debounces accessibility window/content change events after an action is dispatched
 * so `ScreenParser` never captures a half-transitioned screen.
 */
object StabilityWaiter {
    suspend fun awaitStable(
        lastEventTimestampProvider: () -> Long,
        actionStartTimeMs: Long = SystemClock.uptimeMillis(),
        quietPeriodMs: Long = 220L,
        firstEventGraceMs: Long = 320L,
        maxWaitMs: Long = 1_500L,
    ): Long {
        val waitStartedAt = SystemClock.uptimeMillis()

        // Phase 1: Wait up to firstEventGraceMs for the UI to emit its first post-action event
        while (SystemClock.uptimeMillis() - waitStartedAt < firstEventGraceMs) {
            if (lastEventTimestampProvider() > actionStartTimeMs) {
                break
            }
            delay(30L)
        }

        // Phase 2: Debounce until no new accessibility events arrive for quietPeriodMs (up to maxWaitMs)
        while (SystemClock.uptimeMillis() - waitStartedAt < maxWaitMs) {
            val now = SystemClock.uptimeMillis()
            val lastEvent = lastEventTimestampProvider().coerceAtLeast(actionStartTimeMs)
            if (now - lastEvent >= quietPeriodMs) {
                break
            }
            delay(35L)
        }

        return SystemClock.uptimeMillis() - waitStartedAt
    }
}
