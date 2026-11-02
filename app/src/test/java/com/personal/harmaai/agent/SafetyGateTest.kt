package com.personal.harmaai.agent

import com.personal.harmaai.tools.ToolRisk
import com.personal.harmaai.tools.ToolSpec
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SafetyGateTest {
    private val gate = SafetyGate()

    @Test
    fun `calls and messages always require confirmation`() {
        assertTrue(gate.needsConfirmation(spec("send_sms"), JSONObject(), null, false))
        assertTrue(gate.needsConfirmation(spec("make_call"), JSONObject(), null, false))
    }

    @Test
    fun `optional sensitive tools respect the confirmation setting`() {
        val clipboard = spec("get_clipboard")
        assertFalse(gate.needsConfirmation(clipboard, JSONObject(), null, false))
        assertTrue(gate.needsConfirmation(clipboard, JSONObject(), null, true))
    }

    private fun spec(name: String) = ToolSpec(
        name = name,
        description = name,
        risk = ToolRisk.SENSITIVE,
        parameters = JSONObject().put("type", "object"),
    )
}
