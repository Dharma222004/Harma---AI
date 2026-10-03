package ai.harma.app

import ai.harma.app.data.model.*
import com.google.gson.Gson
import org.junit.Assert.*
import org.junit.Test

class HarmaLogicTest {

    private val gson = Gson()

    @Test
    fun testDeviceRegistrationSerialization() {
        val req = DeviceRegistrationRequest(
            device_id = "test-device-123",
            device_name = "Pixel 8 Pro",
            platform = "android",
            android_version = "14",
            app_version = "1.0.0",
            manufacturer = "Google",
            model = "Pixel 8 Pro",
            capabilities = listOf("voice", "microphone", "app_control", "flashlight"),
            permission_states = mapOf("record_audio" to true, "accessibility" to true),
            connection_state = "ONLINE"
        )

        val json = gson.toJson(req)
        assertTrue(json.contains("test-device-123"))
        assertTrue(json.contains("Pixel 8 Pro"))
        assertTrue(json.contains("accessibility"))

        val deserialized = gson.fromJson(json, DeviceRegistrationRequest::class.java)
        assertEquals("test-device-123", deserialized.device_id)
        assertEquals(4, deserialized.capabilities.size)
    }

    @Test
    fun testActionResultReportVerificationStatus() {
        val report = ActionResultReport(
            device_id = "android-test",
            task_id = "task-456",
            action = "WHATSAPP_SEND",
            status = VerificationState.ACTION_EXECUTED_VERIFIED.name,
            message = "Message sent and verified in chat."
        )

        val json = gson.toJson(report)
        assertTrue(json.contains("ACTION_EXECUTED_VERIFIED"))
        assertEquals("WHATSAPP_SEND", report.action)
    }

    @Test
    fun testAutonomyPolicyLevels() {
        val manual = AutonomyLevel.MANUAL
        val supervised = AutonomyLevel.SUPERVISED
        val autonomous = AutonomyLevel.AUTONOMOUS

        assertEquals("Manual", manual.title)
        assertEquals("Supervised", supervised.title)
        assertEquals("Autonomous", autonomous.title)
    }

    @Test
    fun testDuplicateMessageDetectionLogic() {
        val messageHistory = listOf("hello", "how are you", "hi")
        val newMessage = "hi"

        val isDuplicate = messageHistory.takeLast(5).any { it.equals(newMessage.trim(), ignoreCase = true) }
        assertTrue(isDuplicate)

        val nonDuplicate = "different message"
        val isNonDuplicate = messageHistory.takeLast(5).any { it.equals(nonDuplicate.trim(), ignoreCase = true) }
        assertFalse(isNonDuplicate)
    }

    @Test
    fun testContactAmbiguityDetectionLogic() {
        val contactsFound = listOf("Bhuvanesh Kumar", "Bhuvanesh R", "Bhuvanesh")
        val query = "Bhuvanesh"

        val distinctMatches = contactsFound.filter { it.contains(query, ignoreCase = true) }.distinct()
        assertTrue(distinctMatches.size > 1)
        assertEquals(3, distinctMatches.size)
    }
}
