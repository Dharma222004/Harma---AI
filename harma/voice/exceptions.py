"""
Harma Voice — Exceptions — Phase 4

Typed exception hierarchy for every voice subsystem failure.
All exceptions are caught at the VoiceManager level and converted to
user-friendly messages. Stack traces are never spoken aloud.
"""

from __future__ import annotations


class VoiceError(Exception):
    """Base class for all Harma voice errors."""


class MicrophoneError(VoiceError):
    """Microphone device problems: not found, permission denied, I/O error."""


class MicrophoneNotFoundError(MicrophoneError):
    """Requested microphone device does not exist."""


class MicrophonePermissionError(MicrophoneError):
    """Operating system denied microphone access."""


class AudioCaptureError(MicrophoneError):
    """Error occurred while reading audio frames from the device."""


class WakeWordError(VoiceError):
    """Wake-word engine failure."""


class WakeWordInitError(WakeWordError):
    """Failed to initialise the wake-word engine."""


class VADError(VoiceError):
    """Voice activity detection failure."""


class STTError(VoiceError):
    """Speech-to-text failure."""


class STTTimeoutError(STTError):
    """Transcription took too long."""


class STTEmptyError(STTError):
    """Transcription produced an empty or unintelligible result."""


class STTProviderError(STTError):
    """Provider-side error (network, auth, quota)."""


class TTSError(VoiceError):
    """Text-to-speech failure."""


class TTSPlaybackError(TTSError):
    """Audio playback failed."""


class TTSProviderError(TTSError):
    """TTS provider returned an error."""


class VoiceStateError(VoiceError):
    """Illegal state transition attempted."""


class ConversationError(VoiceError):
    """Conversation-mode lifecycle error."""
