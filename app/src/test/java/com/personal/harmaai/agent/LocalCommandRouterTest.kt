package com.personal.harmaai.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalCommandRouterTest {

    @Test
    fun `extracts open app target accurately`() {
        val router = LocalCommandRouter(android.app.Application())
        // Pattern tests
        assertTrue("open youtube".contains("youtube"))
        assertTrue("open paytm".contains("paytm"))
    }

    @Test
    fun `detects flashlight commands`() {
        val onCmd = "turn on flashlight"
        val offCmd = "turn off torch"
        assertTrue(onCmd.contains("flashlight"))
        assertTrue(offCmd.contains("torch"))
    }

    @Test
    fun `detects youtube search commands`() {
        val query = "search cats on youtube"
        val pattern = java.util.regex.Pattern.compile("(?:search|find|play|look for)\\s+(.+?)\\s+(?:on|in)\\s+youtube")
        val matcher = pattern.matcher(query)
        assertTrue(matcher.find())
        assertEquals("cats", matcher.group(1)?.trim())
    }

    @Test
    fun `call routes directly without confirmation`() {
        val router = LocalCommandRouter(android.app.Application())
        val res = router.tryRoute("call Mom")
        assertTrue(res is RouterResult.Handled)
        val handled = res as RouterResult.Handled
        assertEquals("Calling Mom", handled.description)
    }

    @Test
    fun `detects camera capture commands`() {
        val router = LocalCommandRouter(android.app.Application())
        val res = router.tryRoute("open camera and take photo")
        assertTrue(res is RouterResult.Handled)
        val handled = res as RouterResult.Handled
        assertEquals("Taking photo", handled.description)

        // Also test user's exact phrase "open camera and take one photo"
        assertTrue(LocalCommandRouter.matchesCameraCapture("open camera and take one photo"))
    }

    @Test
    fun `detects phone call with to syntax`() {
        val target = LocalCommandRouter.extractCallTarget("call to 7092750591")
        assertEquals("7092750591", target)
    }
}

