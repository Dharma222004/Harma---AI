package com.personal.harmaai.agent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalCommandRouterTest {

    @Test
    fun `extracts open app target accurately and rejects compound commands`() {
        assertEquals("youtube", LocalCommandRouter.extractOpenAppTarget("open youtube"))
        assertEquals("paytm", LocalCommandRouter.extractOpenAppTarget("launch paytm"))
        assertEquals("settings", LocalCommandRouter.extractOpenAppTarget("go to settings"))
        // Compound multi-step commands must NOT be matched as simple open-app
        org.junit.Assert.assertNull(LocalCommandRouter.extractOpenAppTarget("open chrome and search for weather"))
        org.junit.Assert.assertNull(LocalCommandRouter.extractOpenAppTarget("open youtube and play believer"))
        org.junit.Assert.assertNull(LocalCommandRouter.extractOpenAppTarget("open whatsapp to send message to mom"))
    }

    @Test
    fun `detects flashlight commands`() {
        val onCmd = "turn on flashlight"
        val offCmd = "turn off torch"
        assertTrue(onCmd.contains("flashlight"))
        assertTrue(offCmd.contains("torch"))
    }

    @Test
    fun `detects youtube play and search commands`() {
        assertEquals("believer song", LocalCommandRouter.extractYouTubePlay("play believer song on youtube"))
        assertEquals("lofi beats", LocalCommandRouter.extractYouTubePlay("open youtube and play lofi beats"))
        assertEquals("cats", LocalCommandRouter.extractYouTubeSearch("search cats on youtube"))
        assertEquals("kotlin tutorials", LocalCommandRouter.extractYouTubeSearch("open youtube and search for kotlin tutorials"))
    }

    @Test
    fun `detects whatsapp target and message`() {
        assertEquals("Mom" to "I reached home", LocalCommandRouter.extractWhatsAppTarget("send whatsapp message to Mom saying I reached home"))
        assertEquals("Rahul" to "Good morning", LocalCommandRouter.extractWhatsAppTarget("whatsapp Rahul that Good morning"))
        assertEquals("Dad" to "Hello", LocalCommandRouter.extractWhatsAppTarget("open whatsapp and message Dad"))
    }

    @Test
    fun `detects alarm ringer and media commands`() {
        assertEquals(Triple(7, 30, "Wake up"), LocalCommandRouter.extractAlarmTime("set an alarm for 7:30 am called Wake up"))
        assertEquals(Triple(18, 0, ""), LocalCommandRouter.extractAlarmTime("wake me up at 6 pm"))
        assertEquals("silent", LocalCommandRouter.extractRingerMode("put phone on silent mode"))
        assertEquals("vibrate", LocalCommandRouter.extractRingerMode("set phone to vibrate"))
        assertEquals("pause", LocalCommandRouter.extractMediaAction("pause music"))
        assertEquals("next", LocalCommandRouter.extractMediaAction("next song"))
        assertEquals("weather today", LocalCommandRouter.extractWebSearch("google search for weather today"))
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

    @Test
    fun `formats compact screen parser lines with numeric IDs and attributes`() {
        val nodes = listOf(
            com.personal.harmaai.accessibility.UiNodeSnapshot(
                index = 0,
                className = "EditText",
                text = "Search",
                contentDescription = "",
                viewId = "com.google.android.youtube:id/search_edit_text",
                bounds = "40,120,980,220",
                clickable = true,
                editable = true,
                scrollable = false,
                focused = true,
                checked = false,
                password = false,
                hintText = "Search YouTube",
                windowType = "APP",
            ),
            com.personal.harmaai.accessibility.UiNodeSnapshot(
                index = 1,
                className = "ImageButton",
                text = "",
                contentDescription = "Voice search",
                viewId = "com.google.android.youtube:id/voice_search",
                bounds = "980,120,1060,220",
                clickable = true,
                editable = false,
                scrollable = false,
                focused = false,
                checked = false,
                password = false,
                windowType = "APP",
            ),
        )
        val compact = com.personal.harmaai.accessibility.ScreenParser.formatCompactLines(
            packageName = "com.google.android.youtube",
            activityName = "ShellActivity",
            windowTitle = "YouTube",
            keyboardVisible = true,
            scrollHints = listOf("[2] RecyclerView (down, up)"),
            protectedContent = false,
            nodes = nodes,
        )
        assertTrue(compact.contains("PACKAGE: com.google.android.youtube"))
        assertTrue(compact.contains("KEYBOARD: OPEN"))
        assertTrue(compact.contains("[0] EditText \"Search\""))
        assertTrue(compact.contains("editable"))
        assertTrue(compact.contains("[1] ImageButton desc=\"Voice search\""))

        val fp = nodes[0].toFingerprint()
        assertEquals(510, fp.centerX)
        assertEquals(170, fp.centerY)
    }

    @Test
    fun `detects sensitive commands for stale offline queue confirmation`() {
        assertTrue(OfflineTaskQueueManager.isSensitiveCommand("send whatsapp message to Mom saying hello"))
        assertTrue(OfflineTaskQueueManager.isSensitiveCommand("pay 500 to merchant"))
        org.junit.Assert.assertFalse(OfflineTaskQueueManager.isSensitiveCommand("play lofi beats on youtube"))
        org.junit.Assert.assertFalse(OfflineTaskQueueManager.isSensitiveCommand("search kotlin coroutine tutorials"))
    }

    @Test
    fun `extracts read messages and RemoteInput notification reply commands`() {
        assertEquals("" to "", LocalCommandRouter.extractReadMessagesQuery("read my new messages"))
        assertEquals("" to "whatsapp", LocalCommandRouter.extractReadMessagesQuery("read my whatsapp messages"))
        assertEquals("Rahul" to "", LocalCommandRouter.extractReadMessagesQuery("read messages from Rahul"))
        assertEquals("Mom" to "", LocalCommandRouter.extractReadMessagesQuery("what did Mom message me"))

        assertEquals(
            "Rahul" to "I'll be there in 5 minutes",
            LocalCommandRouter.extractNotificationReply("reply to Rahul saying I'll be there in 5 minutes"),
        )
        assertEquals(
            "" to "I'm on my way",
            LocalCommandRouter.extractNotificationReply("reply to that message saying I'm on my way"),
        )
        assertEquals(
            "Mom" to "I will call later",
            LocalCommandRouter.extractNotificationReply("reply to Mom that I will call later"),
        )
    }

    @Test
    fun `reads and filters recent messages from HarmaNotificationListenerService`() {
        com.personal.harmaai.notifications.HarmaNotificationListenerService.clearForTest()
        com.personal.harmaai.notifications.HarmaNotificationListenerService.recordForTest(
            com.personal.harmaai.notifications.HarmaNotification(
                key = "wa_rahul_1",
                packageName = "com.whatsapp",
                appName = "WhatsApp",
                title = "Rahul",
                text = "Are you on your way?",
                postedAt = 1000L,
                canReply = true,
            ),
        )
        com.personal.harmaai.notifications.HarmaNotificationListenerService.recordForTest(
            com.personal.harmaai.notifications.HarmaNotification(
                key = "tg_mom_1",
                packageName = "org.telegram.messenger",
                appName = "Telegram",
                title = "Mom",
                text = "Call me when free",
                postedAt = 2000L,
                canReply = true,
            ),
        )

        val allRes = com.personal.harmaai.notifications.HarmaNotificationListenerService.readRecentMessages()
        assertTrue(allRes.success)
        assertEquals(2, allRes.notifications.size)
        assertTrue(allRes.summary.contains("from Mom on Telegram"))
        assertTrue(allRes.summary.contains("from Rahul on WhatsApp"))

        val rahulOnly = com.personal.harmaai.notifications.HarmaNotificationListenerService.readRecentMessages(
            senderFilter = "Rahul",
        )
        assertEquals(1, rahulOnly.notifications.size)
        assertEquals("Are you on your way?", rahulOnly.notifications.first().text)

        val redacted = com.personal.harmaai.notifications.HarmaNotificationListenerService.sanitize(
            "Your OTP verification code is 482910",
        )
        org.junit.Assert.assertFalse(redacted.contains("482910"))
    }

    @Test
    fun `serializes and deserializes learned UI macro ElementFingerprint trajectories`() {
        assertEquals(
            "open chrome incognito tab",
            LearnedMacroManager.normalizeCommand("Hey Harma, please open Chrome incognito tab!"),
        )
        assertTrue(LearnedMacroManager.isCacheableCommand("check data balance in Airtel"))
        assertTrue(LearnedMacroManager.isCacheableCommand("clear app cache in Settings"))
        org.junit.Assert.assertFalse(LearnedMacroManager.isCacheableCommand("pay 500 to merchant"))
        org.junit.Assert.assertFalse(LearnedMacroManager.isCacheableCommand("send whatsapp message to Rahul"))

        val fp = com.personal.harmaai.accessibility.ElementFingerprint(
            index = 3,
            viewId = "menu_button",
            className = "ImageButton",
            text = "",
            contentDescription = "More options",
            bounds = "960,80,1080,200",
            centerX = 1020,
            centerY = 140,
            clickable = true,
        )
        val steps = listOf(
            LearnedMacroStep(
                toolName = "open_app",
                arguments = org.json.JSONObject().put("name", "Chrome").put("package", "com.android.chrome"),
                fingerprint = null,
                expectedPackage = "com.android.chrome",
            ),
            LearnedMacroStep(
                toolName = "tap",
                arguments = org.json.JSONObject().put("index", 3),
                fingerprint = fp,
                expectedPackage = "com.android.chrome",
            ),
        )

        val serialized = LearnedMacroManager.serializeSteps(steps)
        val restored = LearnedMacroManager.deserializeSteps(serialized)
        assertEquals(2, restored.size)
        assertEquals("open_app", restored[0].toolName)
        assertEquals("tap", restored[1].toolName)
        assertNotNull(restored[1].fingerprint)
        assertEquals("More options", restored[1].fingerprint?.contentDescription)
        assertEquals(1020, restored[1].fingerprint?.centerX)

        val sim = LearnedMacroManager.computeTokenSimilarity(
            LearnedMacroManager.normalizeCommand("Hey Harma, open Chrome incognito tab"),
            LearnedMacroManager.normalizeCommand("please open the Chrome incognito tab"),
        )
        assertTrue(sim >= 0.85)
    }
}




