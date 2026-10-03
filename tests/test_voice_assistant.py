"""
Tests for Harma Voice Assistant — Siri-Style Always-On Voice Control & Multilingual Support
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from harma.voice.language import (
    ENGLISH, TAMIL, TELUGU, LANGUAGES,
    resolve_language, detect_language_switch, strip_wake_phrase,
    classify_yes_no, is_cancel_command, is_end_conversation,
    is_shutdown_command, is_reset_command, reply_instruction,
)
from harma.voice.models import AudioBuffer, AudioState, VoiceCommand
from harma.voice.tts import EdgeTTSProvider, SilentTTSProvider, get_tts_provider
from harma.voice.stt import GoogleSTTProvider, get_stt_provider
from harma.voice.wakeword import (
    VoskWakeWordProvider, LocalWakeWordProvider, DisabledWakeWordProvider,
    get_wake_word_provider,
)
from harma.voice.manager import VoiceManager


class TestVoiceLanguageSupport(unittest.TestCase):
    """Test language registry, detection, and wake-word stripping."""

    def test_resolve_language(self):
        self.assertEqual(resolve_language("en").code, "en")
        self.assertEqual(resolve_language("ta").code, "ta")
        self.assertEqual(resolve_language("te").code, "te")
        self.assertEqual(resolve_language("tamil").code, "ta")
        self.assertEqual(resolve_language("telugu").code, "te")
        self.assertEqual(resolve_language("ta-IN").code, "ta")
        self.assertEqual(resolve_language("unknown_lang", default=ENGLISH).code, "en")

    def test_strip_wake_phrase(self):
        self.assertEqual(strip_wake_phrase("Hey Harma, open notepad"), "open notepad")
        self.assertEqual(strip_wake_phrase("hey harma what's the weather"), "what's the weather")
        self.assertEqual(strip_wake_phrase("hey karma open browser"), "open browser")
        self.assertEqual(strip_wake_phrase("harma play music"), "play music")
        self.assertEqual(strip_wake_phrase("Hey Harma"), "")
        self.assertEqual(strip_wake_phrase("just do this"), "just do this")

    def test_detect_language_switch(self):
        self.assertEqual(detect_language_switch("switch to Tamil").code, "ta")
        self.assertEqual(detect_language_switch("change language to Telugu").code, "te")
        self.assertEqual(detect_language_switch("speak in English").code, "en")
        self.assertEqual(detect_language_switch("speak in Tamil").code, "ta")
        # Ordinary queries shouldn't trigger language switch
        self.assertIsNone(detect_language_switch("search for tamil movies near me"))
        self.assertIsNone(detect_language_switch("what is the weather today"))

    def test_multilingual_yes_no(self):
        self.assertEqual(classify_yes_no("yes"), "yes")
        self.assertEqual(classify_yes_no("sure"), "yes")
        self.assertEqual(classify_yes_no("no"), "no")
        self.assertEqual(classify_yes_no("cancel"), "no")
        # Tamil
        self.assertEqual(classify_yes_no("ஆமாம்"), "yes")
        self.assertEqual(classify_yes_no("சரி"), "yes")
        self.assertEqual(classify_yes_no("வேண்டாம்"), "no")
        # Telugu
        self.assertEqual(classify_yes_no("అవును"), "yes")
        self.assertEqual(classify_yes_no("వద్దు"), "no")

    def test_control_intents(self):
        self.assertTrue(is_cancel_command("stop"))
        self.assertTrue(is_cancel_command("cancel that"))
        self.assertTrue(is_end_conversation("thank you"))
        self.assertTrue(is_end_conversation("that's all"))
        self.assertTrue(is_shutdown_command("exit voice mode"))
        self.assertTrue(is_shutdown_command("turn off voice"))
        self.assertTrue(is_reset_command("reset"))
        self.assertTrue(is_reset_command("clear memory"))

    def test_reply_instruction(self):
        self.assertEqual(reply_instruction(ENGLISH), "")
        self.assertIn("Tamil", reply_instruction(TAMIL))
        self.assertIn("Telugu", reply_instruction(TELUGU))


class TestEdgeTTSIntegration(unittest.TestCase):
    """Test Edge TTS neural voice provider."""

    def test_edge_tts_factory(self):
        tts = get_tts_provider("edge_tts")
        self.assertIsInstance(tts, EdgeTTSProvider)
        self.assertIn("Edge", tts.name)

    def test_edge_tts_voice_change(self):
        tts = EdgeTTSProvider(voice="en-IN-NeerjaNeural")
        self.assertEqual(tts.voice, "en-IN-NeerjaNeural")
        tts.set_voice("ta-IN-PallaviNeural")
        self.assertEqual(tts.voice, "ta-IN-PallaviNeural")

    def test_edge_tts_stop_resets_speaking(self):
        tts = EdgeTTSProvider()
        tts.stop()
        self.assertFalse(tts.is_speaking)


class TestVoiceCommandModel(unittest.TestCase):
    """Test multilingual methods on VoiceCommand."""

    def test_voice_command_confirmations(self):
        cmd_en = VoiceCommand(transcript="yes")
        self.assertTrue(cmd_en.is_confirmation())

        cmd_ta = VoiceCommand(transcript="ஆமாம்")
        self.assertTrue(cmd_ta.is_confirmation())

        cmd_no = VoiceCommand(transcript="no")
        self.assertTrue(cmd_no.is_rejection())

        cmd_exit = VoiceCommand(transcript="that's all")
        self.assertTrue(cmd_exit.is_exit_command())


class MockAgent:
    def __init__(self, reply: str = "Execution completed"):
        self.reply = reply
        self.calls = []
        self.did_reset = False

    async def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.reply

    def reset(self):
        self.did_reset = True


class TestVoiceManagerSiriFeatures(unittest.IsolatedAsyncioTestCase):
    """Test VoiceManager language switching, Siri flow, and command processing."""

    async def test_language_switch_via_command(self):
        agent = MockAgent()
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        self.assertEqual(vm.language.code, "en")
        cmd = VoiceCommand(transcript="switch to Tamil")
        await vm.handle_command(cmd)

        self.assertEqual(vm.language.code, "ta")
        self.assertIn("சரி", tts.last_spoken)

    async def test_reset_command(self):
        agent = MockAgent()
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())

        cmd = VoiceCommand(transcript="clear memory")
        await vm.handle_command(cmd)

        self.assertTrue(agent.did_reset)

    async def test_normal_command_executes_agent_with_language_directive(self):
        agent = MockAgent("Notepad opened successfully.")
        tts = SilentTTSProvider()
        vm = VoiceManager(agent=agent, tts=tts, wake_word=DisabledWakeWordProvider())
        vm.set_language("ta")

        cmd = VoiceCommand(transcript="Hey Harma, open notepad")
        await vm.handle_command(cmd)

        self.assertEqual(len(agent.calls), 1)
        self.assertTrue(agent.calls[0].startswith("open notepad"))
        self.assertIn("Tamil", agent.calls[0])
        self.assertEqual(tts.last_spoken, "Notepad opened successfully.")


if __name__ == "__main__":
    unittest.main()
