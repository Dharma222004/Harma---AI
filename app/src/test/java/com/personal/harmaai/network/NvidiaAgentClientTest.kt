package com.personal.harmaai.network

import com.personal.harmaai.tools.ToolRisk
import com.personal.harmaai.tools.ToolSpec
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NvidiaAgentClientTest {
    private val client = NvidiaAgentClient()

    @Test
    fun `request uses NVIDIA multimodal and single-tool protocol`() {
        val body = client.buildRequestBody(
            model = NvidiaAgentClient.DEFAULT_MODEL,
            history = listOf(
                AgentMessage.User("Inspect this screen", jpegBase64 = "AQID"),
            ),
            tools = listOf(
                ToolSpec(
                    name = "set_flashlight",
                    description = "Set the torch.",
                    risk = ToolRisk.SAFE,
                    parameters = JSONObject()
                        .put("type", "OBJECT")
                        .put(
                            "properties",
                            JSONObject().put(
                                "on",
                                JSONObject().put("type", "BOOLEAN"),
                            ),
                        )
                        .put("required", JSONArray().put("on")),
                ),
            ),
        )

        assertEquals(NvidiaAgentClient.DEFAULT_MODEL, body.getString("model"))
        assertFalse(body.getBoolean("parallel_tool_calls"))
        assertTrue(body.getBoolean("stream"))
        assertFalse(
            body.getJSONObject("chat_template_kwargs").getBoolean("enable_thinking"),
        )
        val userParts = body.getJSONArray("messages").getJSONObject(1).getJSONArray("content")
        assertEquals("text", userParts.getJSONObject(0).getString("type"))
        assertEquals("image_url", userParts.getJSONObject(1).getString("type"))
        assertEquals(
            "data:image/jpeg;base64,AQID",
            userParts.getJSONObject(1).getJSONObject("image_url").getString("url"),
        )
        val schema = body.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("function")
            .getJSONObject("parameters")
        assertEquals("object", schema.getString("type"))
        assertEquals(
            "boolean",
            schema.getJSONObject("properties").getJSONObject("on").getString("type"),
        )
    }

    @Test
    fun `tool call response preserves id arguments and hidden reasoning`() {
        val decision = client.parseDecision(
            raw = """
                {
                  "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
                  "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                      "role": "assistant",
                      "content": "",
                      "reasoning_content": "private chain",
                      "tool_calls": [{
                        "id": "call_123",
                        "type": "function",
                        "function": {
                          "name": "set_flashlight",
                          "arguments": "{\"on\":true}"
                        }
                      }]
                    }
                  }]
                }
            """.trimIndent(),
            requestedModel = NvidiaAgentClient.DEFAULT_MODEL,
        )

        val call = assertNotNull(decision.toolCall).let { decision.toolCall!! }
        assertEquals("call_123", call.id)
        assertEquals("set_flashlight", call.name)
        assertTrue(call.arguments.getBoolean("on"))
        assertEquals("private chain", decision.assistantMessage.reasoningContent)
        assertFalse(decision.assistantMessage.toString().contains("private chain"))
    }

    @Test
    fun `tool result uses matching call id`() {
        val call = AgentLlmToolCall(
            id = "call_abc",
            name = "get_battery",
            arguments = JSONObject(),
        )
        val messages = AgentConversation.toolResultMessages(
            call = call,
            result = com.personal.harmaai.tools.ToolResult.success("Battery is 50%."),
            observation = null,
        )

        val tool = messages.single() as AgentMessage.Tool
        assertEquals("call_abc", tool.toolCallId)
        assertEquals("get_battery", tool.toolName)
        assertTrue(JSONObject(tool.content).getBoolean("success"))
    }

    @Test
    fun `retry classification and retry-after are bounded`() {
        assertTrue(NvidiaAgentClient.isRetryableStatus(429))
        assertTrue(NvidiaAgentClient.isRetryableStatus(503))
        assertFalse(NvidiaAgentClient.isRetryableStatus(401))
        assertEquals(2_000L, NvidiaAgentClient.retryAfterMillis("2"))
        assertEquals(30_000L, NvidiaAgentClient.retryAfterMillis("999999999999"))
        assertEquals(null, NvidiaAgentClient.retryAfterMillis("invalid"))
    }
}
