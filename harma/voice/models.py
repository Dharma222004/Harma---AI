"""
Harma Voice — Data Models — Phase 4

Strongly-typed data structures for the entire voice subsystem.
No scattered booleans. Every state and event is a typed object.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Audio State Machine
# ─────────────────────────────────────────────────────────────────────────────

class AudioState(Enum):
    """
    The low-level audio hardware lifecycle (Phase 4).

    Transitions:
        IDLE → WAITING_FOR_WAKE_WORD
        WAITING_FOR_WAKE_WORD → WAKE_DETECTED | IDLE (shutdown)
        WAKE_DETECTED → LISTENING
        LISTENING → PROCESSING | TIMEOUT | IDLE
        PROCESSING → SPEAKING | IDLE
        SPEAKING → IDLE | INTERRUPTED
        INTERRUPTED → LISTENING | IDLE
        TIMEOUT → IDLE
        ERROR → IDLE
    """
    IDLE                  = "idle"
    WAITING_FOR_WAKE_WORD = "waiting_for_wake_word"
    WAKE_DETECTED         = "wake_detected"
    LISTENING             = "listening"
    PROCESSING            = "processing"
    SPEAKING              = "speaking"
    INTERRUPTED           = "interrupted"
    TIMEOUT               = "timeout"
    ERROR                 = "error"


# Valid state transitions — enforced by AudioStateMachine
_VALID_TRANSITIONS: dict[AudioState, set[AudioState]] = {
    AudioState.IDLE: {
        AudioState.WAITING_FOR_WAKE_WORD,
        AudioState.LISTENING,   # push-to-talk mode skips wake word
    },
    AudioState.WAITING_FOR_WAKE_WORD: {
        AudioState.WAKE_DETECTED,
        AudioState.IDLE,
        AudioState.ERROR,
    },
    AudioState.WAKE_DETECTED: {
        AudioState.LISTENING,
        AudioState.IDLE,
        AudioState.ERROR,
    },
    AudioState.LISTENING: {
        AudioState.PROCESSING,
        AudioState.TIMEOUT,
        AudioState.IDLE,
        AudioState.ERROR,
    },
    AudioState.PROCESSING: {
        AudioState.SPEAKING,
        AudioState.IDLE,
        AudioState.ERROR,
    },
    AudioState.SPEAKING: {
        AudioState.IDLE,
        AudioState.INTERRUPTED,
        AudioState.ERROR,
    },
    AudioState.INTERRUPTED: {
        AudioState.LISTENING,
        AudioState.IDLE,
    },
    AudioState.TIMEOUT: {
        AudioState.IDLE,
        AudioState.WAITING_FOR_WAKE_WORD,
    },
    AudioState.ERROR: {
        AudioState.IDLE,
        AudioState.WAITING_FOR_WAKE_WORD,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Assistant Voice State Machine (Spec §3)
# ─────────────────────────────────────────────────────────────────────────────

class VoiceState(str, Enum):
    """
    High-level Voice-First Assistant State Machine.
    Strict lifecycle:
        WAITING_FOR_WAKE_WORD → WAKE_DETECTED → LISTENING → TRANSCRIBING
        → UNDERSTANDING → EXECUTING → SPEAKING → WAITING_FOR_WAKE_WORD
    """
    IDLE                  = "IDLE"
    WAITING_FOR_WAKE_WORD = "WAITING_FOR_WAKE_WORD"
    WAKE_DETECTED         = "WAKE_DETECTED"
    LISTENING             = "LISTENING"
    TRANSCRIBING          = "TRANSCRIBING"
    UNDERSTANDING         = "UNDERSTANDING"
    EXECUTING             = "EXECUTING"
    SPEAKING              = "SPEAKING"
    INTERRUPTED           = "INTERRUPTED"
    ERROR                 = "ERROR"


_VOICE_TRANSITIONS: dict[VoiceState, set[VoiceState]] = {
    VoiceState.IDLE: {
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.LISTENING,
        VoiceState.ERROR,
    },
    VoiceState.WAITING_FOR_WAKE_WORD: {
        VoiceState.WAKE_DETECTED,
        VoiceState.LISTENING,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.WAKE_DETECTED: {
        VoiceState.LISTENING,
        VoiceState.SPEAKING,   # immediate chime / greeting
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.LISTENING: {
        VoiceState.TRANSCRIBING,
        VoiceState.UNDERSTANDING,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.TRANSCRIBING: {
        VoiceState.UNDERSTANDING,
        VoiceState.SPEAKING,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.UNDERSTANDING: {
        VoiceState.EXECUTING,
        VoiceState.SPEAKING,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.EXECUTING: {
        VoiceState.SPEAKING,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.SPEAKING: {
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.LISTENING,   # follow-up conversation window
        VoiceState.INTERRUPTED,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.INTERRUPTED: {
        VoiceState.LISTENING,
        VoiceState.SPEAKING,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.ERROR: {
        VoiceState.IDLE,
        VoiceState.WAITING_FOR_WAKE_WORD,
        VoiceState.LISTENING,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Audio Buffer
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AudioBuffer:
    """
    Raw audio frames collected from the microphone.

    frames:      list of bytes chunks
    sample_rate: Hz (e.g. 16000)
    channels:    1 = mono
    """
    frames: list[bytes] = field(default_factory=list)
    sample_rate: int = 16000
    channels: int = 1
    captured_at: float = field(default_factory=time.time)

    def append(self, frame: bytes) -> None:
        self.frames.append(frame)

    def total_bytes(self) -> int:
        return sum(len(f) for f in self.frames)

    def duration_seconds(self) -> float:
        """Approximate duration based on 16-bit samples."""
        total_samples = self.total_bytes() // 2  # 16-bit = 2 bytes/sample
        if self.sample_rate == 0:
            return 0.0
        return total_samples / (self.sample_rate * self.channels)

    def is_empty(self) -> bool:
        return len(self.frames) == 0 or self.total_bytes() == 0

    def to_bytes(self) -> bytes:
        return b"".join(self.frames)

    def clear(self) -> None:
        self.frames.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Voice Command
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VoiceCommand:
    """
    A fully-transcribed voice command ready for the agent.

    transcript:   The spoken text, normalised to lowercase.
    raw:          The original transcription (not lowercased).
    confidence:   Provider confidence score 0.0–1.0 (or None).
    latency_ms:   STT latency in milliseconds.
    """
    transcript: str
    raw: str = ""
    confidence: Optional[float] = None
    latency_ms: float = 0.0
    captured_at: float = field(default_factory=time.time)

    def is_exit_command(self) -> bool:
        """True if the user wants to end conversation mode."""
        t = self.transcript.lower().strip()
        try:
            from harma.voice.language import is_end_conversation, is_shutdown_command
            if is_end_conversation(t) or is_shutdown_command(t):
                return True
        except Exception:
            pass
        exits = {
            "goodbye harma", "goodbye", "bye harma",
            "stop listening", "exit conversation",
            "stop conversation", "end conversation",
            "that's all", "thats all", "stop",
            "quit", "exit",
        }
        return t in exits

    def is_confirmation(self) -> bool:
        """True if the user confirmed an action."""
        t = self.transcript.lower().strip()
        try:
            from harma.voice.language import classify_yes_no
            res = classify_yes_no(t)
            if res == "yes":
                return True
        except Exception:
            pass
        return t in {"yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "go ahead", "do it"}

    def is_rejection(self) -> bool:
        """True if the user cancelled an action."""
        t = self.transcript.lower().strip()
        try:
            from harma.voice.language import classify_yes_no
            res = classify_yes_no(t)
            if res == "no":
                return True
        except Exception:
            pass
        return t in {"no", "nope", "cancel", "don't", "stop", "abort", "never mind", "nevermind"}

    def is_interrupt(self) -> bool:
        """True if the user wants to interrupt current speech."""
        t = self.transcript.lower().strip()
        return t in {"stop", "wait", "pause", "quiet", "silence", "enough", "shhh"}


# ─────────────────────────────────────────────────────────────────────────────
# Voice Events (for logging / observability)
# ─────────────────────────────────────────────────────────────────────────────

class VoiceEvent(str, Enum):
    """Named events for structured voice logging."""
    VOICE_STARTED           = "VOICE_STARTED"
    VOICE_STOPPED           = "VOICE_STOPPED"
    WAKE_WORD_DETECTED      = "WAKE_WORD_DETECTED"
    WAKE_WORD_NOT_DETECTED  = "WAKE_WORD_NOT_DETECTED"
    LISTENING_STARTED       = "LISTENING_STARTED"
    LISTENING_STOPPED       = "LISTENING_STOPPED"
    VAD_SPEECH_START        = "VAD_SPEECH_START"
    VAD_SPEECH_END          = "VAD_SPEECH_END"
    VAD_TIMEOUT             = "VAD_TIMEOUT"
    STT_STARTED             = "STT_STARTED"
    STT_COMPLETED           = "STT_COMPLETED"
    STT_FAILED              = "STT_FAILED"
    STT_EMPTY               = "STT_EMPTY"
    COMMAND_RECEIVED        = "COMMAND_RECEIVED"
    AGENT_STARTED           = "AGENT_STARTED"
    AGENT_COMPLETED         = "AGENT_COMPLETED"
    TTS_STARTED             = "TTS_STARTED"
    TTS_COMPLETED           = "TTS_COMPLETED"
    TTS_INTERRUPTED         = "TTS_INTERRUPTED"
    TTS_FAILED              = "TTS_FAILED"
    STATE_CHANGED           = "STATE_CHANGED"
    VOICE_ERROR             = "VOICE_ERROR"
    CONFIRMATION_REQUESTED  = "CONFIRMATION_REQUESTED"
    CONVERSATION_STARTED    = "CONVERSATION_STARTED"
    CONVERSATION_ENDED      = "CONVERSATION_ENDED"
    CONVERSATION_TIMEOUT    = "CONVERSATION_TIMEOUT"


# ─────────────────────────────────────────────────────────────────────────────
# Timing / Latency
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineLatency:
    """Timing metrics for a single voice→agent→tts pipeline run."""
    stt_ms: float = 0.0
    agent_ms: float = 0.0
    tts_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.stt_ms + self.agent_ms + self.tts_ms

    def summary(self) -> str:
        return (
            f"STT: {self.stt_ms:.0f}ms  "
            f"Agent: {self.agent_ms:.0f}ms  "
            f"TTS: {self.tts_ms:.0f}ms  "
            f"Total: {self.total_ms:.0f}ms"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Device Info
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AudioDevice:
    """Represents an audio input device."""
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool = False

    def describe(self) -> str:
        default_marker = " [DEFAULT]" if self.is_default else ""
        return f"[{self.index}] {self.name}  {self.max_input_channels}ch  {self.default_sample_rate:.0f}Hz{default_marker}"
