"""
Tests for HARMA — VOICE-FIRST ASSISTANT RUNTIME
Validates Siri-style Voice Activation + Autonomous Task Execution + Android Assistant Integration
Testing Spec Requirements:
  - Spec §1, §42, §43: Single Authoritative Runtime (One Core, Voice is Modality)
  - Spec §2: Unified Input Architecture & Normalization
  - Spec §3: Strict Voice State Machine
  - Spec §4: "Hey Harma" Wake Word Handling
  - Spec §5, §34: Mode B Continuous Conversation & Follow-up Context
  - Spec §6, §30: Barge-in & Cancellation Propagation
  - Spec §13-23: Android Capabilities (Flashlight, Wi-Fi, Mobile Data Fallback, Bluetooth, Volume, Lock, Navigation, Camera)
  - Spec §24-27: Capability Abstraction, Environment Resolver & Device Registry
  - Spec §28, §29: Voice Response Conciseness & Real-State Verification
  - Spec §31, §32: Consequential Action Safety & Low ASR Confidence
  - Spec §39-42: Android Assistant Architecture & Permission Manager
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.android.capability_layer import AndroidCapabilityLayer
from harma.android.manager import AndroidManager
from harma.android.models import DeviceStatus
from harma.android.permissions import AndroidPermissionManager
from harma.android.tools import (
    AndroidBluetoothTool,
    AndroidCameraTool,
    AndroidFlashlightTool,
    AndroidLockTool,
    AndroidMobileDataTool,
    AndroidNavigateTool,
    AndroidVolumeTool,
    AndroidWifiTool,
    get_android_tools,
)
from harma.android.transports.mock import FakeAndroidTransport
from harma.core.environment import (
    DeviceInfo,
    DeviceRegistry,
    EnvironmentResolver,
    EnvironmentType,
    get_device_registry,
)
from harma.core.input_normalizer import (
    ActionRisk,
    HarmaRequest,
    InputModality,
    InputNormalizer,
)
from harma.voice.exceptions import VoiceStateError
from harma.voice.manager import VoiceManager
from harma.voice.models import AudioState, VoiceCommand, VoiceEvent, VoiceState
from harma.voice.state_machine import VoiceStateMachine
from harma.voice.tts import SilentTTSProvider
from harma.voice.wakeword import DisabledWakeWordProvider


class MockAgentForTesting:
    def __init__(self, reply: str = "Done.", status: str = "completed", verif: str = "verified"):
        self.reply = reply
        self.last_execution_meta = {
            "status": status,
            "tool_calls": [{"tool": "test_tool", "status": "success"}],
            "verification": {"status": verif},
        }
        self.calls: list[str] = []
        self.cancelled = False

    async def run(self, prompt: str, request_id: str | None = None) -> str:
        self.calls.append(prompt)
        await asyncio.sleep(0.01)
        return self.reply

    def cancel(self, run_id: str | None = None) -> list[str]:
        self.cancelled = True
        return ["mock_run"]

    def cancel_plan(self) -> None:
        self.cancelled = True


class TestVoiceStateMachineSpec3(unittest.TestCase):
    """Test strict Voice State Machine lifecycle per Spec §3."""

    def test_voice_state_machine_normal_lifecycle(self):
        sm = VoiceStateMachine(VoiceState.IDLE)
        transitions_recorded = []

        sm.add_listener(lambda old, new: transitions_recorded.append((old, new)))

        # WAITING_FOR_WAKE_WORD → WAKE_DETECTED → LISTENING → TRANSCRIBING →
        # UNDERSTANDING → EXECUTING → SPEAKING → WAITING_FOR_WAKE_WORD
        sm.transition(VoiceState.WAITING_FOR_WAKE_WORD)
        sm.transition(VoiceState.WAKE_DETECTED)
        sm.transition(VoiceState.LISTENING)
        sm.transition(VoiceState.TRANSCRIBING)
        sm.transition(VoiceState.UNDERSTANDING)
        sm.transition(VoiceState.EXECUTING)
        sm.transition(VoiceState.SPEAKING)
        sm.transition(VoiceState.WAITING_FOR_WAKE_WORD)

        self.assertEqual(sm.state, VoiceState.WAITING_FOR_WAKE_WORD)
        self.assertEqual(len(transitions_recorded), 8)

    def test_voice_state_machine_illegal_transition_raises(self):
        sm = VoiceStateMachine(VoiceState.IDLE)
        # Cannot jump from IDLE directly to EXECUTING
        with self.assertRaises(VoiceStateError):
            sm.transition(VoiceState.EXECUTING)

    def test_voice_state_machine_interruption_transition(self):
        sm = VoiceStateMachine(VoiceState.SPEAKING)
        sm.transition(VoiceState.INTERRUPTED)
        self.assertEqual(sm.state, VoiceState.INTERRUPTED)
        sm.transition(VoiceState.WAITING_FOR_WAKE_WORD)
        self.assertEqual(sm.state, VoiceState.WAITING_FOR_WAKE_WORD)

    def test_voice_state_idempotent_transition(self):
        sm = VoiceStateMachine(VoiceState.LISTENING)
        # Transition to same state is a safe no-op
        sm.transition(VoiceState.LISTENING)
        self.assertEqual(sm.state, VoiceState.LISTENING)


class TestUnifiedInputNormalizerSpec2(unittest.TestCase):
    """Test InputNormalizer wake-word stripping, device routing, risk analysis (Spec §2, §4, §31, §32)."""

    def setUp(self):
        self.normalizer = InputNormalizer()

    def test_strip_wake_word(self):
        req = self.normalizer.normalize(
            "Hey Harma, open Edge and open YouTube", modality=InputModality.VOICE
        )
        self.assertEqual(req.clean_goal, "open Edge and open YouTube")
        self.assertFalse(req.is_control_command)

    def test_target_device_detection(self):
        req_phone = self.normalizer.normalize("open YouTube on my phone")
        self.assertEqual(req_phone.target_device, "android")

        req_pc = self.normalizer.normalize("open Chrome on my laptop")
        self.assertEqual(req_pc.target_device, "desktop")

    def test_consequential_action_requires_confirmation(self):
        req_money = self.normalizer.normalize(
            "send 500 rupees to Arun", modality=InputModality.VOICE
        )
        self.assertTrue(req_money.requires_confirmation)
        self.assertEqual(req_money.risk_level, ActionRisk.CONSEQUENTIAL)

        req_delete = self.normalizer.normalize("delete all database files")
        self.assertTrue(req_delete.requires_confirmation)

    def test_low_asr_confidence_requires_confirmation(self):
        req_low = self.normalizer.normalize(
            "turn on wifi", modality=InputModality.VOICE, confidence=0.55
        )
        self.assertTrue(req_low.requires_confirmation)
        self.assertIn("confidence", req_low.confirmation_reason.lower())

    def test_control_commands_detected(self):
        req_cancel = self.normalizer.normalize("stop")
        self.assertTrue(req_cancel.is_control_command)
        self.assertEqual(req_cancel.control_intent, "cancel")

        req_reset = self.normalizer.normalize("clear memory")
        self.assertTrue(req_reset.is_control_command)
        self.assertEqual(req_reset.control_intent, "reset")


class TestAndroidCapabilitiesSpec13to23(unittest.IsolatedAsyncioTestCase):
    """Test Android Capability Layer, Tools, and mobile data fallback rules (Spec §13-23)."""

    def setUp(self):
        self.transport = FakeAndroidTransport()
        self.manager = AndroidManager(transport=self.transport)
        self.cap = AndroidCapabilityLayer(manager=self.manager)

    async def test_flashlight_on_off_and_verification(self):
        tool = AndroidFlashlightTool(manager=self.manager)

        # Turn ON
        res_on = await tool.execute(enable=True)
        self.assertIn("turned on", res_on.output.lower())
        self.assertTrue(await self.manager.get_flashlight())

        # Turn OFF
        res_off = await tool.execute(enable=False)
        self.assertIn("turned off", res_off.output.lower())
        self.assertFalse(await self.manager.get_flashlight())

    async def test_wifi_toggle_and_verification(self):
        tool = AndroidWifiTool(manager=self.manager)

        res_on = await tool.execute(enable=True)
        self.assertIn("enabled", res_on.output.lower())
        self.assertTrue(await self.manager.get_wifi())

        res_off = await tool.execute(enable=False)
        self.assertIn("disabled", res_off.output.lower())
        self.assertFalse(await self.manager.get_wifi())

    async def test_mobile_data_security_panel_fallback_spec17(self):
        """
        Spec §17: Never falsely report success for mobile data without permission.
        Must fallback to supported internet settings panel.
        """
        tool = AndroidMobileDataTool(manager=self.manager)
        res = await tool.execute(enable=True)

        self.assertIn("internet settings", res.output.lower())
        # Crucial: mobile data must NOT be falsely marked as enabled
        self.assertFalse(await self.manager.get_mobile_data())

    async def test_bluetooth_toggle(self):
        tool = AndroidBluetoothTool(manager=self.manager)
        res_on = await tool.execute(enable=True)
        self.assertIn("enabled", res_on.output.lower())
        self.assertTrue(await self.manager.get_bluetooth())

    async def test_volume_control(self):
        tool = AndroidVolumeTool(manager=self.manager)
        res_set = await tool.execute(action="set", level=65)
        self.assertIn("65%", res_set.output)
        self.assertEqual(await self.manager.get_volume(), 65)

    async def test_navigation_tool(self):
        tool = AndroidNavigateTool(manager=self.manager)
        res = await tool.execute(destination="Chennai Central")
        self.assertIn("Chennai Central", res.output)

    async def test_lock_and_unlock(self):
        tool = AndroidLockTool(manager=self.manager)
        res_lock = await tool.execute(action="lock")
        self.assertIn("locked", res_lock.output.lower())
        status = await self.manager.get_device_status()
        self.assertFalse(status.screen_on)

    async def test_permission_manager_spec41(self):
        pm = AndroidPermissionManager()
        has_perm, missing = pm.check_capability("voice")
        self.assertTrue(has_perm)
        self.assertEqual(len(missing), 0)

        # Bluetooth requires BLUETOOTH_CONNECT
        pm.revoke_permission("android.permission.BLUETOOTH_CONNECT")
        has_bt, missing_bt = pm.check_capability("bluetooth")
        self.assertFalse(has_bt)
        self.assertIn("android.permission.BLUETOOTH_CONNECT", missing_bt)


class TestEnvironmentResolverSpec24to27(unittest.TestCase):
    """Test device capability resolution and environment routing."""

    def setUp(self):
        self.resolver = EnvironmentResolver()
        self.registry = get_device_registry()
        self.registry.clear()

        self.registry.register(
            DeviceInfo(
                device_id="dev_pc",
                device_type=EnvironmentType.DESKTOP,
                name="Workstation PC",
                capabilities=["browser", "computer", "shell", "files"],
                is_connected=True,
                is_active=True,
                platform="windows",
            )
        )
        self.registry.register(
            DeviceInfo(
                device_id="dev_phone",
                device_type=EnvironmentType.ANDROID,
                name="Pixel Handset",
                capabilities=["flashlight", "wifi", "mobile_data", "camera", "apps", "browser"],
                is_connected=True,
                is_active=True,
                platform="android",
            )
        )

    def test_routing_with_target_device_hint(self):
        req = HarmaRequest(
            request_id="1",
            clean_goal="open YouTube on my phone",
            raw_input="open YouTube on my phone",
            modality=InputModality.VOICE,
            language="en",
            target_device="android",
        )
        env = self.resolver.resolve_for_request(req)
        self.assertEqual(env, EnvironmentType.ANDROID)

    def test_routing_android_exclusive_capability(self):
        req = HarmaRequest(
            request_id="2",
            clean_goal="turn on the flashlight",
            raw_input="turn on the flashlight",
            modality=InputModality.VOICE,
            language="en",
        )
        env = self.resolver.resolve_for_request(req)
        self.assertEqual(env, EnvironmentType.ANDROID)

    def test_routing_desktop_default(self):
        req = HarmaRequest(
            request_id="3",
            clean_goal="open Edge and search for docs",
            raw_input="open Edge and search for docs",
            modality=InputModality.VOICE,
            language="en",
        )
        env = self.resolver.resolve_for_request(req)
        self.assertEqual(env, EnvironmentType.DESKTOP)


class TestVoiceFirstRuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    """Test VoiceManager with real verification, cancellation, and follow-up (Spec §5, §6, §28, §29, §30)."""

    async def test_verified_voice_response_spec28(self):
        agent = MockAgentForTesting(reply="YouTube is playing a Tamil song.", verif="verified")
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        cmd = VoiceCommand(transcript="Hey Harma, open YouTube and play Tamil song")
        await vm.handle_command(cmd)

        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(tts.last_spoken, "YouTube is playing a Tamil song.")

    async def test_unverified_action_voice_response_spec29(self):
        """
        Spec §29: If ACTION_EXECUTED but VERIFICATION_FAILED:
        say: 'I performed the action, but I couldn't verify the result.'
        """
        agent = MockAgentForTesting(
            reply="Clicked button.", status="completed", verif="unverified"
        )
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        cmd = VoiceCommand(transcript="tap on the login button")
        await vm.handle_command(cmd)

        self.assertEqual(tts.last_spoken, "I performed the action, but I couldn't verify the result.")

    async def test_cancellation_and_barge_in_spec6_spec30(self):
        agent = MockAgentForTesting()
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        cmd = VoiceCommand(transcript="cancel")
        await vm.handle_command(cmd)

        self.assertTrue(agent.cancelled)
        self.assertTrue(any(w in tts.last_spoken.lower() for w in ("stopped", "cancel", "okay")))

    async def test_follow_up_context_inheritance_spec5_spec34(self):
        agent = MockAgentForTesting("Done.")
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        # First command
        cmd1 = VoiceCommand(transcript="open YouTube")
        await vm.handle_command(cmd1)
        self.assertEqual(vm._session_context, "open YouTube")

        # Follow-up command (does not repeat 'YouTube')
        cmd2 = VoiceCommand(transcript="search for new Tamil songs")
        await vm.handle_command(cmd2)

        # Agent should receive inherited context
        self.assertEqual(len(agent.calls), 2)
        self.assertIn("open YouTube", agent.calls[1])
        self.assertIn("search for new Tamil songs", agent.calls[1])


class TestAndroidAssistantBridgeSpec39to43(unittest.IsolatedAsyncioTestCase):
    """Test AndroidAssistantBridge integration into the authoritative Harma Core."""

    async def test_assistant_bridge_execution_and_verification(self):
        from harma.android.assistant.bridge import AndroidAssistantBridge

        agent = MockAgentForTesting("Torch turned on.", verif="verified")
        bridge = AndroidAssistantBridge(agent=agent)

        res = await bridge.handle_user_utterance("Hey Harma, turn on the flashlight")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["speech"], "Torch turned on.")

    async def test_assistant_bridge_barge_in(self):
        from harma.android.assistant.bridge import AndroidAssistantBridge

        agent = MockAgentForTesting()
        bridge = AndroidAssistantBridge(agent=agent)

        res = await bridge.handle_user_utterance("stop")
        self.assertEqual(res["status"], "cancelled")
        self.assertTrue(agent.cancelled)


if __name__ == "__main__":
    unittest.main()
