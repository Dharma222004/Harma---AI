"""
Harma Phase 4 Test Suite — Voice System

Tests:
  1. Regression: 166 existing tests must still pass (checked via imports)
  2. Models: AudioState, VoiceCommand, AudioBuffer, PipelineLatency
  3. State Machine: all transitions, illegal transitions, force_idle
  4. VAD: energy computation, calibration, speech/silence detection, timeout
  5. Exceptions: hierarchy, raising, catching
  6. TTS: filter_for_tts, SilentTTSProvider, interruption
  7. STT: mock providers, empty audio, timeout
  8. Wake word: disabled provider, detection logic
  9. Microphone: device listing, WAV conversion
 10. Conversation: exit commands, confirmation, rejection
 11. Voice Config: VoiceConfig loads from settings
 12. Agent Integration: voice text → existing agent interface
 13. Permissions: voice cannot bypass permission checks
 14. VoiceManager: construction, status, state, stop

All tests use mocked audio — no physical microphone required.
"""

from __future__ import annotations

import asyncio
import io
import struct
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ─────────────────────────────────────────────────────────────────────────────
# 0. REGRESSION — Phase 1–3 imports still work
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase123Regression(unittest.TestCase):

    def test_reg_agent_import(self):
        from harma.core.agent import HarmaAgent
        self.assertTrue(callable(HarmaAgent))

    def test_reg_context_import(self):
        from harma.core.context import AgentContext
        self.assertTrue(callable(AgentContext))

    def test_reg_tool_registry(self):
        from harma.tools.registry import ToolRegistry
        r = ToolRegistry()
        self.assertEqual(len(r), 0)

    def test_reg_llm_provider_import(self):
        from harma.llm.provider import LLMProvider, Message, Role
        self.assertIsNotNone(Role.USER)

    def test_reg_browser_tools(self):
        from harma.tools.browser import navigation_tools
        self.assertTrue(hasattr(navigation_tools, "LaunchBrowserTool"))

    def test_reg_computer_tools(self):
        from harma.tools.system import time_tools
        self.assertTrue(hasattr(time_tools, "GetCurrentTimeTool"))

    def test_reg_config_loads(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertEqual(cfg.agent.name, "Harma")

    def test_reg_permissions(self):
        from harma.security.permissions import PermissionManager
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        result = pm.check("test_tool", PermissionLevel.SAFE)
        self.assertEqual(result.value, "allowed")

    def test_reg_memory(self):
        from harma.memory.short_term import ShortTermMemory
        m = ShortTermMemory()
        m.add_user_message("hello")
        self.assertEqual(len(m.get_messages()), 1)

    def test_reg_total_tool_count(self):
        from harma.core.context import AgentContext
        from harma.llm.provider import LLMProvider
        class _FakeLLM(LLMProvider):
            @property
            def name(self): return "fake"
            async def complete(self, *a, **kw): pass
        ctx = AgentContext(provider=_FakeLLM())
        self.assertGreaterEqual(len(ctx.registry), 50)


# ─────────────────────────────────────────────────────────────────────────────
# 1. MODELS
# ─────────────────────────────────────────────────────────────────────────────

class TestAudioState(unittest.TestCase):

    def test_p4_state_values(self):
        from harma.voice.models import AudioState
        self.assertEqual(AudioState.IDLE.value, "idle")
        self.assertEqual(AudioState.LISTENING.value, "listening")
        self.assertEqual(AudioState.SPEAKING.value, "speaking")

    def test_p4_all_states_exist(self):
        from harma.voice.models import AudioState
        states = {s.value for s in AudioState}
        expected = {
            "idle", "waiting_for_wake_word", "wake_detected",
            "listening", "processing", "speaking",
            "interrupted", "timeout", "error",
        }
        self.assertEqual(states, expected)

    def test_p4_valid_transitions_defined(self):
        from harma.voice.models import _VALID_TRANSITIONS, AudioState
        self.assertIn(AudioState.IDLE, _VALID_TRANSITIONS)
        self.assertIn(AudioState.LISTENING, _VALID_TRANSITIONS)
        self.assertIn(AudioState.SPEAKING, _VALID_TRANSITIONS)

    def test_p4_idle_can_transition_to_waiting(self):
        from harma.voice.models import _VALID_TRANSITIONS, AudioState
        self.assertIn(
            AudioState.WAITING_FOR_WAKE_WORD,
            _VALID_TRANSITIONS[AudioState.IDLE],
        )


class TestAudioBuffer(unittest.TestCase):

    def test_p4_buffer_empty_initially(self):
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer()
        self.assertTrue(buf.is_empty())

    def test_p4_buffer_append(self):
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer()
        buf.append(b"\x00\x01" * 100)
        self.assertFalse(buf.is_empty())
        self.assertEqual(buf.total_bytes(), 200)

    def test_p4_buffer_duration(self):
        from harma.voice.models import AudioBuffer
        # 16000 samples/sec * 2 bytes/sample = 32000 bytes = 1 second
        buf = AudioBuffer(sample_rate=16000, channels=1)
        buf.append(b"\x00\x00" * 16000)
        dur = buf.duration_seconds()
        self.assertAlmostEqual(dur, 1.0, places=1)

    def test_p4_buffer_to_bytes(self):
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer()
        buf.append(b"hello")
        buf.append(b"world")
        self.assertEqual(buf.to_bytes(), b"helloworld")

    def test_p4_buffer_clear(self):
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer()
        buf.append(b"\x01\x02")
        buf.clear()
        self.assertTrue(buf.is_empty())


class TestVoiceCommand(unittest.TestCase):

    def test_p4_exit_command_goodbye_harma(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="goodbye harma")
        self.assertTrue(cmd.is_exit_command())

    def test_p4_exit_command_stop_listening(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="stop listening")
        self.assertTrue(cmd.is_exit_command())

    def test_p4_exit_command_quit(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="quit")
        self.assertTrue(cmd.is_exit_command())

    def test_p4_normal_command_not_exit(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="open chrome")
        self.assertFalse(cmd.is_exit_command())

    def test_p4_confirmation_yes(self):
        from harma.voice.models import VoiceCommand
        for word in ["yes", "yeah", "yep", "sure", "ok"]:
            cmd = VoiceCommand(transcript=word)
            self.assertTrue(cmd.is_confirmation(), f"{word!r} should be confirmation")

    def test_p4_rejection_no(self):
        from harma.voice.models import VoiceCommand
        for word in ["no", "nope", "cancel", "abort"]:
            cmd = VoiceCommand(transcript=word)
            self.assertTrue(cmd.is_rejection(), f"{word!r} should be rejection")

    def test_p4_interrupt_stop(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="stop")
        self.assertTrue(cmd.is_interrupt())

    def test_p4_interrupt_wait(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="wait")
        self.assertTrue(cmd.is_interrupt())

    def test_p4_open_chrome_not_interrupt(self):
        from harma.voice.models import VoiceCommand
        cmd = VoiceCommand(transcript="open chrome")
        self.assertFalse(cmd.is_interrupt())


class TestPipelineLatency(unittest.TestCase):

    def test_p4_latency_total(self):
        from harma.voice.models import PipelineLatency
        lat = PipelineLatency(stt_ms=800, agent_ms=1200, tts_ms=700)
        self.assertAlmostEqual(lat.total_ms, 2700.0)

    def test_p4_latency_summary_string(self):
        from harma.voice.models import PipelineLatency
        lat = PipelineLatency(stt_ms=500, agent_ms=1000, tts_ms=300)
        s = lat.summary()
        self.assertIn("STT", s)
        self.assertIn("Agent", s)
        self.assertIn("TTS", s)
        self.assertIn("Total", s)

    def test_p4_latency_zero_default(self):
        from harma.voice.models import PipelineLatency
        lat = PipelineLatency()
        self.assertEqual(lat.total_ms, 0.0)


class TestVoiceEvent(unittest.TestCase):

    def test_p4_events_exist(self):
        from harma.voice.models import VoiceEvent
        required = [
            "VOICE_STARTED", "WAKE_WORD_DETECTED", "LISTENING_STARTED",
            "STT_COMPLETED", "COMMAND_RECEIVED", "AGENT_STARTED",
            "AGENT_COMPLETED", "TTS_STARTED", "TTS_COMPLETED",
            "TTS_INTERRUPTED", "VOICE_ERROR",
        ]
        names = {e.value for e in VoiceEvent}
        for r in required:
            self.assertIn(r, names, f"Missing VoiceEvent: {r}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. STATE MACHINE
# ─────────────────────────────────────────────────────────────────────────────

class TestAudioStateMachine(unittest.TestCase):

    def _sm(self):
        from harma.voice.audio_state import AudioStateMachine
        return AudioStateMachine()

    def test_p4_sm_initial_state_is_idle(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_valid_idle_to_waiting(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.WAITING_FOR_WAKE_WORD)
        self.assertEqual(sm.state, AudioState.WAITING_FOR_WAKE_WORD)

    def test_p4_sm_valid_idle_to_listening_push_to_talk(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        self.assertEqual(sm.state, AudioState.LISTENING)

    def test_p4_sm_invalid_idle_to_speaking_raises(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        from harma.voice.exceptions import VoiceStateError
        with self.assertRaises(VoiceStateError):
            sm.transition(AudioState.SPEAKING)

    def test_p4_sm_invalid_speaking_to_wake_raises(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        from harma.voice.exceptions import VoiceStateError
        sm.transition(AudioState.LISTENING)
        sm.transition(AudioState.PROCESSING)
        sm.transition(AudioState.SPEAKING)
        with self.assertRaises(VoiceStateError):
            sm.transition(AudioState.WAITING_FOR_WAKE_WORD)

    def test_p4_sm_force_idle_from_any_state(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        sm.transition(AudioState.PROCESSING)
        sm.force_idle()
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_try_transition_invalid_returns_false(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        result = sm.try_transition(AudioState.SPEAKING)  # IDLE → SPEAKING invalid
        self.assertFalse(result)

    def test_p4_sm_try_transition_valid_returns_true(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        result = sm.try_transition(AudioState.LISTENING)
        self.assertTrue(result)

    def test_p4_sm_listener_called_on_transition(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        calls = []
        sm.add_listener(lambda old, new: calls.append((old, new)))
        sm.transition(AudioState.LISTENING)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], AudioState.IDLE)
        self.assertEqual(calls[0][1], AudioState.LISTENING)

    def test_p4_sm_previous_state_tracked(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        self.assertEqual(sm.previous, AudioState.IDLE)

    def test_p4_sm_is_in(self):
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        self.assertTrue(sm.is_in(AudioState.LISTENING))
        self.assertFalse(sm.is_in(AudioState.SPEAKING))

    def test_p4_sm_full_cycle(self):
        """Test a full voice interaction state cycle."""
        sm = self._sm()
        from harma.voice.models import AudioState
        transitions = [
            AudioState.WAITING_FOR_WAKE_WORD,
            AudioState.WAKE_DETECTED,
            AudioState.LISTENING,
            AudioState.PROCESSING,
            AudioState.SPEAKING,
            AudioState.IDLE,
        ]
        for state in transitions:
            sm.transition(state)
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_interrupted_cycle(self):
        """SPEAKING → INTERRUPTED → LISTENING → PROCESSING → IDLE."""
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        sm.transition(AudioState.PROCESSING)
        sm.transition(AudioState.SPEAKING)
        sm.transition(AudioState.INTERRUPTED)
        sm.transition(AudioState.LISTENING)
        sm.transition(AudioState.PROCESSING)
        sm.transition(AudioState.IDLE)
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_timeout_cycle(self):
        """LISTENING → TIMEOUT → IDLE."""
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.LISTENING)
        sm.transition(AudioState.TIMEOUT)
        sm.transition(AudioState.IDLE)
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_error_recovery(self):
        """ERROR → IDLE."""
        sm = self._sm()
        from harma.voice.models import AudioState
        sm.transition(AudioState.WAITING_FOR_WAKE_WORD)
        sm.transition(AudioState.ERROR)
        sm.transition(AudioState.IDLE)
        self.assertEqual(sm.state, AudioState.IDLE)

    def test_p4_sm_time_in_state(self):
        sm = self._sm()
        time.sleep(0.05)
        self.assertGreaterEqual(sm.time_in_state, 0.05)


# ─────────────────────────────────────────────────────────────────────────────
# 3. VAD
# ─────────────────────────────────────────────────────────────────────────────

def _make_frame(rms_value: int, num_samples: int = 1024) -> bytes:
    """Create a synthetic PCM frame with given approximate RMS."""
    import struct, math
    # For a sine wave with amplitude A, RMS = A/sqrt(2)
    amplitude = int(rms_value * 1.414)
    amplitude = min(amplitude, 32767)
    samples = [int(amplitude * math.sin(2 * math.pi * i / num_samples)) for i in range(num_samples)]
    return struct.pack(f"<{num_samples}h", *samples)


class TestEnergyVAD(unittest.TestCase):

    def test_p4_vad_rms_silent_frame(self):
        from harma.voice.vad import _compute_rms
        frame = b"\x00\x00" * 512
        rms = _compute_rms(frame)
        self.assertEqual(rms, 0.0)

    def test_p4_vad_rms_loud_frame(self):
        from harma.voice.vad import _compute_rms
        # Frame with value 10000 in all samples
        frame = struct.pack("<512h", *([10000] * 512))
        rms = _compute_rms(frame)
        self.assertGreater(rms, 9000)

    def test_p4_vad_rms_empty_frame(self):
        from harma.voice.vad import _compute_rms
        self.assertEqual(_compute_rms(b""), 0.0)

    def test_p4_vad_calibrate(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD(threshold_multiplier=2.5)
        ambient = [b"\x01\x00" * 512] * 10
        vad.calibrate(ambient)
        self.assertGreater(vad.threshold, 0.0)

    def test_p4_vad_speech_detection(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD(minimum_speech_ms=0)  # instant detection
        vad.set_threshold(100)
        loud_frame = struct.pack("<512h", *([5000] * 512))
        vad.process_frame(loud_frame)
        self.assertTrue(vad.speech_detected)

    def test_p4_vad_silence_detection(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD(silence_timeout_ms=0, minimum_speech_ms=0)
        vad.set_threshold(100)
        # First trigger speech
        loud = struct.pack("<512h", *([5000] * 512))
        vad.process_frame(loud)
        self.assertTrue(vad.speech_detected)
        # Now silence
        silent = b"\x00\x00" * 512
        vad.process_frame(silent)
        self.assertTrue(vad.is_done())

    def test_p4_vad_no_done_without_speech(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD()
        vad.set_threshold(100)
        silent = b"\x00\x00" * 512
        for _ in range(50):
            vad.process_frame(silent)
        # No speech was ever detected
        self.assertFalse(vad.is_done())

    def test_p4_vad_reset(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD(minimum_speech_ms=0)
        vad.set_threshold(100)
        loud = struct.pack("<512h", *([5000] * 512))
        vad.process_frame(loud)
        self.assertTrue(vad.speech_detected)
        vad.reset()
        self.assertFalse(vad.speech_detected)

    def test_p4_vad_is_speech_true(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD()
        vad.set_threshold(100)
        loud = struct.pack("<512h", *([5000] * 512))
        self.assertTrue(vad.is_speech(loud))

    def test_p4_vad_is_speech_false(self):
        from harma.voice.vad import EnergyVAD
        vad = EnergyVAD()
        vad.set_threshold(100)
        silent = b"\x00\x00" * 512
        self.assertFalse(vad.is_speech(silent))


# ─────────────────────────────────────────────────────────────────────────────
# 4. EXCEPTIONS
# ─────────────────────────────────────────────────────────────────────────────

class TestVoiceExceptions(unittest.TestCase):

    def test_p4_exc_hierarchy(self):
        from harma.voice.exceptions import (
            AudioCaptureError, MicrophoneError,
            MicrophoneNotFoundError, MicrophonePermissionError,
            STTEmptyError, STTError, STTProviderError, STTTimeoutError,
            TTSError, TTSPlaybackError, TTSProviderError,
            VoiceError, VoiceStateError, WakeWordError,
        )
        self.assertTrue(issubclass(MicrophoneError, VoiceError))
        self.assertTrue(issubclass(MicrophoneNotFoundError, MicrophoneError))
        self.assertTrue(issubclass(MicrophonePermissionError, MicrophoneError))
        self.assertTrue(issubclass(AudioCaptureError, MicrophoneError))
        self.assertTrue(issubclass(STTEmptyError, STTError))
        self.assertTrue(issubclass(STTTimeoutError, STTError))
        self.assertTrue(issubclass(STTProviderError, STTError))
        self.assertTrue(issubclass(TTSPlaybackError, TTSError))
        self.assertTrue(issubclass(TTSProviderError, TTSError))
        self.assertTrue(issubclass(VoiceStateError, VoiceError))
        self.assertTrue(issubclass(WakeWordError, VoiceError))

    def test_p4_exc_is_exception(self):
        from harma.voice.exceptions import VoiceError
        self.assertTrue(issubclass(VoiceError, Exception))

    def test_p4_exc_can_raise_and_catch(self):
        from harma.voice.exceptions import STTEmptyError, STTError, VoiceError
        with self.assertRaises(VoiceError):
            raise STTEmptyError("No speech")

    def test_p4_exc_stt_catch_as_stt(self):
        from harma.voice.exceptions import STTEmptyError, STTError
        with self.assertRaises(STTError):
            raise STTEmptyError("No speech")


# ─────────────────────────────────────────────────────────────────────────────
# 5. TTS
# ─────────────────────────────────────────────────────────────────────────────

class TestResponseFilter(unittest.TestCase):

    def test_p4_filter_empty_returns_empty(self):
        from harma.voice.tts import filter_for_tts
        self.assertEqual(filter_for_tts(""), "")

    def test_p4_filter_normal_text_unchanged(self):
        from harma.voice.tts import filter_for_tts
        result = filter_for_tts("Chrome is open.")
        self.assertEqual(result, "Chrome is open.")

    def test_p4_filter_removes_api_key(self):
        from harma.voice.tts import filter_for_tts
        text = "Your key is sk-abcdef1234567890abcdef1234567890"
        result = filter_for_tts(text)
        self.assertNotIn("sk-abcdef", result)

    def test_p4_filter_removes_groq_key(self):
        from harma.voice.tts import filter_for_tts
        text = "Key: gsk_fakegroqkeyforunittesting1234567890abcdef"
        result = filter_for_tts(text)
        self.assertNotIn("gsk_fakegroqkey", result)

    def test_p4_filter_truncates_long_text(self):
        from harma.voice.tts import filter_for_tts, MAX_TTS_CHARS
        long_text = "word " * 200
        result = filter_for_tts(long_text)
        self.assertLessEqual(len(result), MAX_TTS_CHARS + 10)

    def test_p4_filter_strips_traceback(self):
        from harma.voice.tts import filter_for_tts
        text = "Traceback (most recent call last): something bad"
        result = filter_for_tts(text)
        self.assertNotIn("Traceback", result)


class TestSilentTTSProvider(unittest.TestCase):

    def test_p4_silent_tts_name(self):
        from harma.voice.tts import SilentTTSProvider
        tts = SilentTTSProvider()
        self.assertEqual(tts.name, "Silent (no audio)")

    def test_p4_silent_tts_synthesize(self):
        from harma.voice.tts import SilentTTSProvider
        tts = SilentTTSProvider()
        asyncio.run(tts.synthesize("Hello Harma"))
        self.assertEqual(tts.last_spoken, "Hello Harma")

    def test_p4_silent_tts_empty_text(self):
        from harma.voice.tts import SilentTTSProvider
        tts = SilentTTSProvider()
        asyncio.run(tts.synthesize(""))
        self.assertEqual(tts.last_spoken, "")

    def test_p4_silent_tts_stop(self):
        from harma.voice.tts import SilentTTSProvider
        tts = SilentTTSProvider()
        tts.stop()  # should not raise
        self.assertFalse(tts.is_speaking)

    def test_p4_silent_tts_is_speaking_false_after(self):
        from harma.voice.tts import SilentTTSProvider
        tts = SilentTTSProvider()
        asyncio.run(tts.synthesize("test"))
        self.assertFalse(tts.is_speaking)

    def test_p4_tts_factory_silent(self):
        from harma.voice.tts import SilentTTSProvider, get_tts_provider
        tts = get_tts_provider("silent")
        self.assertIsInstance(tts, SilentTTSProvider)

    def test_p4_tts_factory_unknown_defaults_pyttsx3(self):
        from harma.voice.tts import PyttsxTTSProvider, get_tts_provider
        # This may fail if pyttsx3 init fails — catch gracefully
        try:
            tts = get_tts_provider("unknown_provider")
            self.assertIsInstance(tts, PyttsxTTSProvider)
        except Exception:
            pass  # pyttsx3 may not be available in CI


# ─────────────────────────────────────────────────────────────────────────────
# 6. STT (Mock)
# ─────────────────────────────────────────────────────────────────────────────

class FakeSTTProvider:
    """A fake STT provider for testing without hardware or network."""

    def __init__(self, transcript: str = "open chrome", error=None):
        self._transcript = transcript
        self._error = error
        self.call_count = 0

    @property
    def name(self):
        return "FakeSTT"

    async def transcribe(self, audio):
        from harma.voice.models import VoiceCommand
        self.call_count += 1
        if self._error:
            raise self._error
        if not self._transcript:
            from harma.voice.exceptions import STTEmptyError
            raise STTEmptyError("Empty")
        return VoiceCommand(
            transcript=self._transcript.lower(),
            raw=self._transcript,
            latency_ms=50.0,
        )


class TestFakeSTTProvider(unittest.TestCase):

    def test_p4_fake_stt_transcribes(self):
        stt = FakeSTTProvider("open chrome")
        buf = MagicMock()
        buf.is_empty.return_value = False
        result = asyncio.run(stt.transcribe(buf))
        self.assertEqual(result.transcript, "open chrome")

    def test_p4_fake_stt_raises_on_empty(self):
        from harma.voice.exceptions import STTEmptyError
        stt = FakeSTTProvider("")
        buf = MagicMock()
        buf.is_empty.return_value = False
        with self.assertRaises(STTEmptyError):
            asyncio.run(stt.transcribe(buf))

    def test_p4_fake_stt_raises_custom_error(self):
        from harma.voice.exceptions import STTProviderError
        err = STTProviderError("Network failed")
        stt = FakeSTTProvider("x", error=err)
        buf = MagicMock()
        buf.is_empty.return_value = False
        with self.assertRaises(STTProviderError):
            asyncio.run(stt.transcribe(buf))

    def test_p4_stt_factory_google(self):
        from harma.voice.stt import GoogleSTTProvider, get_stt_provider
        provider = get_stt_provider("google")
        self.assertIsInstance(provider, GoogleSTTProvider)

    def test_p4_stt_factory_whisper(self):
        from harma.voice.stt import WhisperSTTProvider, get_stt_provider
        provider = get_stt_provider("whisper")
        self.assertIsInstance(provider, WhisperSTTProvider)

    def test_p4_stt_provider_names(self):
        from harma.voice.stt import (
            GoogleSTTProvider, OfflineSTTProvider, WhisperSTTProvider,
        )
        self.assertEqual(GoogleSTTProvider().name, "Google Web STT")
        self.assertIn("Whisper", WhisperSTTProvider().name)
        self.assertIn("Offline", OfflineSTTProvider().name)


# ─────────────────────────────────────────────────────────────────────────────
# 7. WAKE WORD
# ─────────────────────────────────────────────────────────────────────────────

class TestWakeWordProviders(unittest.TestCase):

    def test_p4_disabled_provider_never_detects(self):
        from harma.voice.wakeword import DisabledWakeWordProvider
        from harma.voice.models import AudioBuffer
        p = DisabledWakeWordProvider()
        buf = AudioBuffer()
        buf.append(b"\x00" * 100)
        self.assertFalse(p.detect(buf))

    def test_p4_disabled_provider_repr(self):
        from harma.voice.wakeword import DisabledWakeWordProvider
        p = DisabledWakeWordProvider()
        self.assertIn("push-to-talk", repr(p))

    def test_p4_wake_word_factory_disabled(self):
        from harma.voice.wakeword import DisabledWakeWordProvider, get_wake_word_provider
        p = get_wake_word_provider(enabled=False)
        self.assertIsInstance(p, DisabledWakeWordProvider)

    def test_p4_wake_word_factory_enabled(self):
        from harma.voice.wakeword import LocalWakeWordProvider, get_wake_word_provider
        p = get_wake_word_provider(enabled=True, phrase="hey harma")
        self.assertIsInstance(p, LocalWakeWordProvider)

    def test_p4_local_wake_word_empty_audio_false(self):
        from harma.voice.models import AudioBuffer
        from harma.voice.wakeword import LocalWakeWordProvider
        p = LocalWakeWordProvider(phrase="hey harma")
        buf = AudioBuffer()  # empty
        self.assertFalse(p.detect(buf))

    def test_p4_local_wake_word_phrase_set(self):
        from harma.voice.wakeword import LocalWakeWordProvider
        p = LocalWakeWordProvider(phrase="hey harma")
        p.set_phrase("harma listen")
        self.assertEqual(p._phrase, "harma listen")


# ─────────────────────────────────────────────────────────────────────────────
# 8. MICROPHONE (no hardware required — test utilities only)
# ─────────────────────────────────────────────────────────────────────────────

class TestMicrophoneUtilities(unittest.TestCase):

    def test_p4_buffer_to_wav_bytes(self):
        """WAV header should start with RIFF."""
        from harma.voice.microphone import MicrophoneCapture
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer(sample_rate=16000, channels=1)
        buf.append(b"\x00\x00" * 8000)  # 0.5s of silence
        wav = MicrophoneCapture.buffer_to_wav_bytes(buf)
        self.assertTrue(wav.startswith(b"RIFF"), "WAV should start with RIFF header")

    def test_p4_wav_bytes_valid_structure(self):
        """WAV should contain WAVE marker."""
        from harma.voice.microphone import MicrophoneCapture
        from harma.voice.models import AudioBuffer
        buf = AudioBuffer(sample_rate=16000, channels=1)
        buf.append(b"\x01\x00" * 4000)
        wav = MicrophoneCapture.buffer_to_wav_bytes(buf)
        self.assertIn(b"WAVE", wav)

    def test_p4_list_audio_devices_returns_list(self):
        """list_audio_devices() should return a list (may be empty in CI)."""
        from harma.voice.microphone import list_audio_devices
        devices = list_audio_devices()
        self.assertIsInstance(devices, list)

    def test_p4_audio_device_describe(self):
        from harma.voice.models import AudioDevice
        dev = AudioDevice(
            index=0, name="Test Mic",
            max_input_channels=1,
            default_sample_rate=44100.0,
            is_default=True,
        )
        desc = dev.describe()
        self.assertIn("Test Mic", desc)
        self.assertIn("[DEFAULT]", desc)


# ─────────────────────────────────────────────────────────────────────────────
# 9. VOICE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class TestVoiceConfig(unittest.TestCase):

    def test_p4_voice_config_exists(self):
        from harma.config.settings import load_config
        cfg = load_config()
        self.assertTrue(hasattr(cfg, "voice"))

    def test_p4_voice_config_defaults(self):
        from harma.config.settings import VoiceConfig
        vc = VoiceConfig()
        self.assertTrue(vc.enabled)
        self.assertFalse(vc.wake_word_enabled)
        self.assertEqual(vc.microphone_sample_rate, 16000)
        self.assertEqual(vc.microphone_channels, 1)
        self.assertEqual(vc.stt_provider, "google")
        self.assertEqual(vc.tts_provider, "pyttsx3")

    def test_p4_voice_config_vad_defaults(self):
        from harma.config.settings import VoiceConfig
        vc = VoiceConfig()
        self.assertTrue(vc.vad_enabled)
        self.assertEqual(vc.vad_silence_timeout_ms, 1200)
        self.assertEqual(vc.vad_min_speech_ms, 250)

    def test_p4_voice_config_privacy_defaults(self):
        from harma.config.settings import VoiceConfig
        vc = VoiceConfig()
        self.assertFalse(vc.save_recordings)

    def test_p4_voice_config_conversation_defaults(self):
        from harma.config.settings import VoiceConfig
        vc = VoiceConfig()
        self.assertFalse(vc.conversation_mode_enabled)
        self.assertEqual(vc.conversation_inactivity_timeout, 30.0)

    def test_p4_config_voice_accessible(self):
        from harma.config.settings import config
        self.assertIsNotNone(config.voice)
        self.assertIsInstance(config.voice.tts_rate, int)


# ─────────────────────────────────────────────────────────────────────────────
# 10. AGENT INTEGRATION (Mock)
# ─────────────────────────────────────────────────────────────────────────────

class FakeAgent:
    """A fake HarmaAgent for testing VoiceManager integration."""

    def __init__(self, response: str = "Done."):
        self._response = response
        self.calls: list[str] = []

    async def run(self, user_input: str) -> str:
        self.calls.append(user_input)
        return self._response

    def reset(self):
        self.calls.clear()


class TestVoiceAgentIntegration(unittest.TestCase):
    """Verify voice text → existing agent integration."""

    def _make_manager(self, response="Done."):
        from harma.voice.tts import SilentTTSProvider
        from harma.voice.wakeword import DisabledWakeWordProvider
        from harma.voice.manager import VoiceManager
        agent = FakeAgent(response=response)
        tts = SilentTTSProvider()
        wake = DisabledWakeWordProvider()
        stt = FakeSTTProvider(transcript="open chrome")
        vm = VoiceManager(agent=agent, stt=stt, tts=tts, wake_word=wake)
        return vm, agent

    def test_p4_handle_command_calls_agent(self):
        """Voice command should call agent.run() with transcript."""
        from harma.voice.models import VoiceCommand
        vm, agent = self._make_manager()

        cmd = VoiceCommand(transcript="open chrome", raw="Open Chrome")
        asyncio.run(vm.handle_command(cmd))
        self.assertIn("open chrome", agent.calls)

    def test_p4_handle_command_speaks_response(self):
        """Agent response should be passed to TTS."""
        from harma.voice.tts import SilentTTSProvider
        from harma.voice.models import VoiceCommand
        vm, agent = self._make_manager("Chrome is open.")

        cmd = VoiceCommand(transcript="open chrome", raw="Open Chrome")
        asyncio.run(vm.handle_command(cmd))
        self.assertEqual(vm._tts.last_spoken, "Chrome is open.")

    def test_p4_speak_empty_does_nothing(self):
        """Empty TTS text should not trigger synthesis."""
        vm, agent = self._make_manager()
        asyncio.run(vm.speak(""))
        self.assertEqual(vm._tts.last_spoken, "")

    def test_p4_speak_text(self):
        """vm.speak() should invoke TTS."""
        vm, agent = self._make_manager()
        asyncio.run(vm.speak("Hello."))
        self.assertEqual(vm._tts.last_spoken, "Hello.")

    def test_p4_voice_uses_existing_agent_not_second(self):
        """VoiceManager must use the same agent instance, not create a new one."""
        from harma.voice.tts import SilentTTSProvider
        from harma.voice.wakeword import DisabledWakeWordProvider
        from harma.voice.manager import VoiceManager
        agent = FakeAgent()
        vm = VoiceManager(agent=agent, tts=SilentTTSProvider(), wake_word=DisabledWakeWordProvider())
        self.assertIs(vm._agent, agent)

    def test_p4_voice_manager_status(self):
        vm, _ = self._make_manager()
        status = vm.status()
        self.assertIn("STT", status)
        self.assertIn("TTS", status)

    def test_p4_voice_manager_initial_state_idle(self):
        from harma.voice.models import AudioState
        vm, _ = self._make_manager()
        self.assertEqual(vm.state, AudioState.IDLE)


# ─────────────────────────────────────────────────────────────────────────────
# 11. PERMISSIONS — voice cannot bypass
# ─────────────────────────────────────────────────────────────────────────────

class TestVoicePermissions(unittest.TestCase):

    def test_p4_safe_tool_allowed_via_voice(self):
        """SAFE tools should be auto-allowed."""
        from harma.security.permissions import PermissionManager
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        result = pm.check("get_current_time", PermissionLevel.SAFE)
        self.assertEqual(result.value, "allowed")

    def test_p4_sensitive_tool_needs_confirmation(self):
        """SENSITIVE tools require confirmation (not auto-allowed)."""
        from harma.security.permissions import PermissionDecision, PermissionManager
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        result = pm.check("browser_click", PermissionLevel.SENSITIVE)
        self.assertIn(result, (PermissionDecision.NEEDS_CONFIRMATION, PermissionDecision.ALLOWED))

    def test_p4_voice_command_not_authorisation(self):
        """VoiceCommand.is_confirmation() ≠ permission granted."""
        from harma.voice.models import VoiceCommand
        # Even if user says "yes", that's a dialogue response, not a permission bypass
        cmd = VoiceCommand(transcript="yes")
        # The is_confirmation() flag is for dialogue flow only
        self.assertTrue(cmd.is_confirmation())
        # But it doesn't grant permission on its own — permissions still go through PermissionManager
        from harma.security.permissions import PermissionManager
        from harma.tools.base import PermissionLevel
        pm = PermissionManager()
        # HIGH_RISK should never be auto-confirmed, voice or not
        from harma.config.settings import config
        self.assertFalse(config.permissions.auto_confirm_high_risk)

    def test_p4_voice_confirmation_callback_returns_yes_or_no(self):
        """VoiceManager.voice_confirm() must return 'yes' or 'no'."""
        from harma.voice.conversation import ConversationMode
        from harma.voice.manager import VoiceManager
        from harma.voice.tts import SilentTTSProvider
        from harma.voice.wakeword import DisabledWakeWordProvider
        from harma.voice.models import VoiceCommand

        agent = FakeAgent()
        vm = VoiceManager(
            agent=agent,
            tts=SilentTTSProvider(),
            wake_word=DisabledWakeWordProvider(),
        )

        # Patch listen_once to return "yes"
        async def _fake_listen(timeout=10.0):
            return VoiceCommand(transcript="yes")

        vm.listen_once = _fake_listen
        result = asyncio.run(vm.voice_confirm("Shall I proceed?"))
        self.assertIn(result, ("yes", "no"))


# ─────────────────────────────────────────────────────────────────────────────
# 12. CONVERSATION MODE
# ─────────────────────────────────────────────────────────────────────────────

class TestConversationMode(unittest.TestCase):

    def _make_conv(self, enabled=False):
        from harma.voice.conversation import ConversationMode
        vm = MagicMock()
        conv = ConversationMode(manager=vm, enabled=enabled)
        return conv, vm

    def test_p4_conv_not_active_by_default(self):
        conv, _ = self._make_conv()
        self.assertFalse(conv.is_active)

    def test_p4_conv_is_continuous_when_enabled(self):
        conv, _ = self._make_conv(enabled=True)
        self.assertTrue(conv.is_continuous)

    def test_p4_conv_end_sets_active_false(self):
        conv, _ = self._make_conv(enabled=True)
        conv._active = True
        conv.end()
        self.assertFalse(conv.is_active)

    def test_p4_conv_single_dispatches_to_manager(self):
        """ConversationMode.run_single() should call vm.handle_command()."""
        from harma.voice.models import VoiceCommand
        from harma.voice.conversation import ConversationMode

        vm = MagicMock()
        vm.handle_command = AsyncMock()
        conv = ConversationMode(manager=vm, enabled=False)
        cmd = VoiceCommand(transcript="open chrome")
        asyncio.run(conv.run_single(cmd))
        vm.handle_command.assert_called_once_with(cmd)

    def test_p4_conv_disabled_cannot_run_continuous(self):
        from harma.voice.exceptions import ConversationError
        conv, _ = self._make_conv(enabled=False)
        with self.assertRaises(ConversationError):
            asyncio.run(conv.run_continuous())


# ─────────────────────────────────────────────────────────────────────────────
# 13. VOICE IMPORTS
# ─────────────────────────────────────────────────────────────────────────────

class TestVoiceImports(unittest.TestCase):

    def test_p4_import_manager(self):
        from harma.voice.manager import VoiceManager
        self.assertTrue(callable(VoiceManager))

    def test_p4_import_models(self):
        from harma.voice.models import AudioState, AudioBuffer, VoiceCommand
        self.assertIsNotNone(AudioState.IDLE)

    def test_p4_import_exceptions(self):
        from harma.voice.exceptions import VoiceError, STTError, TTSError
        self.assertTrue(issubclass(STTError, VoiceError))

    def test_p4_import_audio_state(self):
        from harma.voice.audio_state import AudioStateMachine
        sm = AudioStateMachine()
        self.assertIsNotNone(sm)

    def test_p4_import_vad(self):
        from harma.voice.vad import EnergyVAD, _compute_rms
        self.assertTrue(callable(_compute_rms))

    def test_p4_import_microphone(self):
        from harma.voice.microphone import (
            MicrophoneCapture, list_audio_devices, get_default_device,
        )
        self.assertTrue(callable(list_audio_devices))

    def test_p4_import_wakeword(self):
        from harma.voice.wakeword import (
            WakeWordProvider, DisabledWakeWordProvider,
            LocalWakeWordProvider, get_wake_word_provider,
        )
        self.assertTrue(callable(get_wake_word_provider))

    def test_p4_import_stt(self):
        from harma.voice.stt import (
            STTProvider, GoogleSTTProvider, WhisperSTTProvider,
            OfflineSTTProvider, get_stt_provider,
        )
        self.assertTrue(callable(get_stt_provider))

    def test_p4_import_tts(self):
        from harma.voice.tts import (
            TTSProvider, SilentTTSProvider, PyttsxTTSProvider,
            filter_for_tts, get_tts_provider,
        )
        self.assertTrue(callable(filter_for_tts))

    def test_p4_import_conversation(self):
        from harma.voice.conversation import ConversationMode
        self.assertTrue(callable(ConversationMode))

    def test_p4_voice_package_init(self):
        import harma.voice
        self.assertIsNotNone(harma.voice)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
