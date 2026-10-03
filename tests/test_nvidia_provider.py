"""
Tests for NVIDIA LLM Provider Adapter and Harma Integration
"""

import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.config.settings import LLMConfig, config
from harma.llm.adapters.nvidia_adapter import NVIDIAAdapter
from harma.llm.factory import get_provider
from harma.llm.provider import (
    LLMResponse,
    Message,
    Role,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


class TestNVIDIAProviderInitialization(unittest.TestCase):
    """Test NVIDIA adapter initialization, configuration validation and normalization."""

    def test_init_success_with_explicit_args(self):
        adapter = NVIDIAAdapter(
            api_key="nvapi-test1234567890",
            model="nemotron-3-super-120b-a12b",
            base_url="https://integrate.api.nvidia.com/v1",
            timeout=90,
            temperature=0.1,
        )
        self.assertEqual(adapter.name, "NVIDIA")
        self.assertEqual(adapter.model, "nemotron-3-super-120b-a12b")
        self.assertEqual(adapter.effective_model, "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(adapter.base_url, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(adapter._timeout, 90)
        self.assertEqual(adapter._temperature, 0.1)

    def test_init_auto_prefixes_nvapi_if_omitted(self):
        adapter = NVIDIAAdapter(
            api_key="GujjQIMShWtGixnkkFExjrHex1e",
            model="nvidia/nemotron-3-super-120b-a12b",
        )
        self.assertTrue(adapter._api_key.startswith("nvapi-"))
        self.assertEqual(adapter._api_key, "nvapi-GujjQIMShWtGixnkkFExjrHex1e")

    def test_init_auto_prefixes_model_org_if_omitted(self):
        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="nemotron-3-super-120b-a12b",
        )
        self.assertEqual(adapter.model, "nemotron-3-super-120b-a12b")
        self.assertEqual(adapter.effective_model, "nvidia/nemotron-3-super-120b-a12b")

    def test_init_preserves_model_if_org_already_present(self):
        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="meta/llama-3.1-70b-instruct",
        )
        self.assertEqual(adapter.effective_model, "meta/llama-3.1-70b-instruct")

    def test_init_raises_if_api_key_missing(self):
        with patch.object(config.llm, "nvidia_api_key", ""), patch.object(config.llm, "api_key", ""):
            with self.assertRaises(ValueError) as ctx:
                NVIDIAAdapter(api_key="", model="nemotron-3-super-120b-a12b")
            self.assertIn("NVIDIA_API_KEY", str(ctx.exception))

    def test_init_raises_if_model_missing(self):
        with patch.object(config.llm, "nvidia_model", ""), patch.object(config.llm, "model", ""):
            with self.assertRaises(ValueError) as ctx:
                NVIDIAAdapter(api_key="nvapi-testkey", model="")
            self.assertIn("NVIDIA_MODEL", str(ctx.exception))

    def test_factory_resolves_nvidia(self):
        with patch.object(config.llm, "nvidia_api_key", "nvapi-factory-key"), patch.object(config.llm, "nvidia_model", "test-model"):
            provider = get_provider("nvidia")
            self.assertIsInstance(provider, NVIDIAAdapter)
            self.assertEqual(provider.name, "NVIDIA")


class TestNVIDIASchemaConversion(unittest.TestCase):
    """Test message and tool schema conversions to OpenAI/NVIDIA NIM format."""

    def test_to_openai_messages_basic(self):
        msgs = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there!"),
        ]
        converted = NVIDIAAdapter._to_openai_messages(msgs, system="You are Harma.")
        self.assertEqual(len(converted), 3)
        self.assertEqual(converted[0], {"role": "system", "content": "You are Harma."})
        self.assertEqual(converted[1], {"role": "user", "content": "Hello"})
        self.assertEqual(converted[2], {"role": "assistant", "content": "Hi there!"})

    def test_to_openai_messages_with_tool_calls(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="call_1", name="open_application", arguments={"application_name": "Chrome"})
                ]
            )
        ]
        converted = NVIDIAAdapter._to_openai_messages(msgs, system=None)
        self.assertEqual(len(converted), 1)
        entry = converted[0]
        self.assertEqual(entry["role"], "assistant")
        self.assertIsNone(entry["content"])
        self.assertEqual(len(entry["tool_calls"]), 1)
        self.assertEqual(entry["tool_calls"][0]["id"], "call_1")
        self.assertEqual(entry["tool_calls"][0]["function"]["name"], "open_application")
        self.assertEqual(json.loads(entry["tool_calls"][0]["function"]["arguments"]), {"application_name": "Chrome"})

    def test_to_openai_messages_with_tool_results(self):
        msgs = [
            Message(
                role=Role.TOOL,
                tool_results=[
                    ToolResult(tool_call_id="call_1", name="open_application", content='{"success": true}')
                ]
            )
        ]
        converted = NVIDIAAdapter._to_openai_messages(msgs, system=None)
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0], {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"success": true}',
        })

    def test_to_openai_tools(self):
        tools = [
            ToolDefinition(
                name="open_application",
                description="Open an application",
                parameters={
                    "type": "object",
                    "properties": {
                        "application_name": {"type": "string", "description": "Name of app"}
                    },
                    "required": ["application_name"]
                }
            )
        ]
        oai_tools = NVIDIAAdapter._to_openai_tools(tools)
        self.assertEqual(len(oai_tools), 1)
        self.assertEqual(oai_tools[0]["type"], "function")
        self.assertEqual(oai_tools[0]["function"]["name"], "open_application")
        self.assertEqual(oai_tools[0]["function"]["description"], "Open an application")
        self.assertEqual(oai_tools[0]["function"]["parameters"]["required"], ["application_name"])

    def test_parse_tool_calls(self):
        raw_call = MagicMock()
        raw_call.id = "call_abc123"
        raw_call.function.name = "get_current_time"
        raw_call.function.arguments = "{}"

        parsed = NVIDIAAdapter._parse_tool_calls([raw_call])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].id, "call_abc123")
        self.assertEqual(parsed[0].name, "get_current_time")
        self.assertEqual(parsed[0].arguments, {})


class TestNVIDIACompletionExecution(unittest.IsolatedAsyncioTestCase):
    """Test complete() execution, tool-call-only responses, error handling, and latency."""

    async def test_tool_call_only_response_handled_cleanly(self):
        """Verify that a response with tool_calls and empty/None content succeeds without error."""
        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="nemotron-3-super-120b-a12b",
        )

        mock_choice = MagicMock()
        mock_choice.finish_reason = "tool_calls"
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_tc = MagicMock()
        mock_tc.id = "call_test_1"
        mock_tc.function.name = "open_application"
        mock_tc.function.arguments = json.dumps({"application_name": "Chrome"})
        mock_msg.tool_calls = [mock_tc]
        mock_choice.message = mock_msg

        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage.prompt_tokens = 45
        mock_resp.usage.completion_tokens = 20
        mock_resp.usage.total_tokens = 65

        adapter._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [Message(role=Role.USER, content="Open Chrome")]
        tools = [
            ToolDefinition(
                name="open_application",
                description="Open app",
                parameters={"type": "object", "properties": {"application_name": {"type": "string"}}},
            )
        ]

        response = await adapter.complete(messages=messages, tools=tools)

        self.assertIsInstance(response, LLMResponse)
        self.assertEqual(response.content, "")  # empty content is not an error
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "open_application")
        self.assertEqual(response.tool_calls[0].arguments, {"application_name": "Chrome"})
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(response.usage["total_tokens"], 65)
        self.assertGreater(adapter.last_latency_ms, 0.0)

    async def test_error_sanitization_masks_api_key(self):
        """Verify that errors never expose the API key in the response or logs."""
        secret_key = "nvapi-SuperSecretNvidiaApiKey123456789"
        adapter = NVIDIAAdapter(
            api_key=secret_key,
            model="nemotron-3-super-120b-a12b",
        )

        # Simulate exception containing the raw secret key
        adapter._client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError(f"HTTP 401 Unauthorized for key {secret_key}")
        )

        messages = [Message(role=Role.USER, content="Hello")]
        response = await adapter.complete(messages=messages)

        self.assertEqual(response.finish_reason, "error")
        self.assertNotIn(secret_key, response.content)
        self.assertIn("[REDACTED_API_KEY]", response.content)

    async def test_streaming_token_generation(self):
        """Verify streaming chunks extract text deltas accurately."""
        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="nemotron-3-super-120b-a12b",
        )

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hello "))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="world!"))]

        async def mock_stream_iter():
            for c in [chunk1, chunk2]:
                yield c

        adapter._client.chat.completions.create = AsyncMock(return_value=mock_stream_iter())

        tokens = []
        async for chunk in adapter.stream([Message(role=Role.USER, content="Hello")]):
            tokens.append(chunk)

        self.assertEqual("".join(tokens), "Hello world!")

    async def test_health_check_and_diagnostics(self):
        """Verify health check and diagnostic reporting."""
        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="nemotron-3-super-120b-a12b",
        )

        # Mock models.list()
        mock_models = MagicMock()
        mock_models.data = [MagicMock(id="nvidia/nemotron-3-super-120b-a12b")]
        adapter._client.models.list = AsyncMock(return_value=mock_models)

        # Mock completions.create for generation check
        mock_comp = MagicMock()
        mock_comp.choices = [MagicMock()]
        adapter._client.chat.completions.create = AsyncMock(return_value=mock_comp)

        is_healthy = await adapter.health_check()
        self.assertTrue(is_healthy)

        diag = await adapter.get_diagnostics()
        self.assertEqual(diag["provider"], "NVIDIA")
        self.assertEqual(diag["model"], "nemotron-3-super-120b-a12b")
        self.assertEqual(diag["connection"], "OK")
        self.assertEqual(diag["authentication"], "OK")
        self.assertEqual(diag["generation"], "OK")
        self.assertEqual(diag["status"], "Connected")
        self.assertEqual(diag["tool_calling"], "supported")
        self.assertIsNone(diag["error"])


class TestNoUncontrolledCloudFallback(unittest.IsolatedAsyncioTestCase):
    """Verify that NVIDIA failures do not automatically fall back to Gemini/Groq."""

    async def test_no_fallback_when_disabled(self):
        with patch.object(config.llm, "fallback_enabled", False):
            adapter = NVIDIAAdapter(
                api_key="nvapi-testkey",
                model="nemotron-3-super-120b-a12b",
            )
            adapter._client.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("NVIDIA API timeout")
            )

            resp = await adapter.complete([Message(role=Role.USER, content="Test")])
            self.assertEqual(resp.finish_reason, "error")
            self.assertIn("NVIDIA LLM error", resp.content)


class TestNVIDIAAgentPipeline(unittest.IsolatedAsyncioTestCase):
    """Test full agent loop with NVIDIA provider (User -> NVIDIA -> Tool -> NVIDIA -> Response)."""

    async def test_agent_multi_step_flow_with_nvidia(self):
        from harma.core.agent import HarmaAgent
        from harma.core.context import AgentContext
        from harma.tools.base import BaseTool, PermissionLevel, ToolResult as BaseToolResult

        class MockCalculatorTool(BaseTool):
            @property
            def name(self) -> str:
                return "calculate"

            @property
            def description(self) -> str:
                return "Perform arithmetic"

            @property
            def parameters(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"}
                    },
                    "required": ["expression"]
                }

            @property
            def permission_level(self) -> PermissionLevel:
                return PermissionLevel.SAFE

            async def execute(self, **kwargs) -> BaseToolResult:
                return BaseToolResult.ok(output="Result is 42", data={"result": 42})

        adapter = NVIDIAAdapter(
            api_key="nvapi-testkey",
            model="nemotron-3-super-120b-a12b",
        )

        # 1st call: model returns tool call 'calculate'
        tc_msg = MagicMock()
        tc_msg.content = None
        mock_tc = MagicMock()
        mock_tc.id = "call_calc_42"
        mock_tc.function.name = "calculate"
        mock_tc.function.arguments = json.dumps({"expression": "6 * 7"})
        tc_msg.tool_calls = [mock_tc]
        resp1 = MagicMock(choices=[MagicMock(message=tc_msg, finish_reason="tool_calls")], usage=None)

        # 2nd call: model returns final text
        final_msg = MagicMock()
        final_msg.content = "The calculation result is 42."
        final_msg.tool_calls = None
        resp2 = MagicMock(choices=[MagicMock(message=final_msg, finish_reason="stop")], usage=None)

        adapter._client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

        ctx = AgentContext(provider=adapter)
        ctx.registry.register(MockCalculatorTool())

        agent = HarmaAgent(ctx)
        result = await agent.run("Calculate 6 * 7")

        self.assertIn("42", result)
        self.assertEqual(adapter._client.chat.completions.create.call_count, 2)



class TestNVIDIAMultiKeyRotation(unittest.IsolatedAsyncioTestCase):
    """Test multi-key pool rotation, round-robin load balancing, and rate limit failover."""

    def test_init_with_multi_keys_list(self):
        keys = ["nvapi-key111111111111", "key222222222222", "nvapi-key333333333333"]
        adapter = NVIDIAAdapter(api_keys=keys, model="nemotron-3-super-120b-a12b")
        self.assertEqual(len(adapter.keys), 3)
        self.assertTrue(all(k.startswith("nvapi-") for k in adapter.keys))
        self.assertEqual(adapter.keys[0], "nvapi-key111111111111")
        self.assertEqual(adapter.keys[1], "nvapi-key222222222222")
        self.assertEqual(adapter.keys[2], "nvapi-key333333333333")

    def test_init_deduplicates_keys(self):
        keys = ["nvapi-key111111111111", "nvapi-key111111111111", "key111111111111"]
        adapter = NVIDIAAdapter(api_keys=keys, model="nemotron-3-super-120b-a12b")
        self.assertEqual(len(adapter.keys), 1)

    async def test_round_robin_rotation_across_calls(self):
        """Verify sequential complete() calls cycle through healthy keys."""
        k1 = "nvapi-key111111111111"
        k2 = "nvapi-key222222222222"
        k3 = "nvapi-key333333333333"
        adapter = NVIDIAAdapter(api_keys=[k1, k2, k3], model="nemotron-3-super-120b-a12b")

        used_keys = []

        def make_mock(k):
            mock = MagicMock()
            async def mock_create(**kwargs):
                used_keys.append(k)
                mock_msg = MagicMock(content=f"Hello from {k}", tool_calls=None)
                return MagicMock(choices=[MagicMock(message=mock_msg, finish_reason="stop")], usage=None)
            mock.chat.completions.create = AsyncMock(side_effect=mock_create)
            return mock

        adapter._clients[k1] = make_mock(k1)
        adapter._clients[k2] = make_mock(k2)
        adapter._clients[k3] = make_mock(k3)

        messages = [Message(role=Role.USER, content="ping")]
        for _ in range(6):
            await adapter.complete(messages=messages)

        # Should cycle k1 -> k2 -> k3 -> k1 -> k2 -> k3
        self.assertEqual(used_keys, [k1, k2, k3, k1, k2, k3])

    async def test_rate_limit_failover_to_next_key(self):
        """Verify that when a key receives HTTP 429, it fails over immediately to the next key."""
        k1 = "nvapi-key111111111111"
        k2 = "nvapi-key222222222222"
        adapter = NVIDIAAdapter(api_keys=[k1, k2], model="nemotron-3-super-120b-a12b")

        mock1 = MagicMock()
        mock1.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("HTTP 429 Too Many Requests: Rate limit exceeded")
        )

        mock2 = MagicMock()
        mock2_msg = MagicMock(content="Success on key 2", tool_calls=None)
        mock2.chat.completions.create = AsyncMock(
            return_value=MagicMock(choices=[MagicMock(message=mock2_msg, finish_reason="stop")], usage=None)
        )

        adapter._clients[k1] = mock1
        adapter._clients[k2] = mock2

        messages = [Message(role=Role.USER, content="Hello")]
        resp = await adapter.complete(messages=messages)

        self.assertEqual(resp.content, "Success on key 2")
        self.assertEqual(resp.finish_reason, "stop")
        # k1 should have been attempted once, and k2 attempted once
        self.assertEqual(mock1.chat.completions.create.call_count, 1)
        self.assertEqual(mock2.chat.completions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()


