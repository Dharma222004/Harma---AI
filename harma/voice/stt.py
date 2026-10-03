"""
Harma Voice — Speech-to-Text (STT) — Phase 4

Provider abstraction for converting audio to text.

Architecture:
    STTProvider (abstract)
        ├── GoogleSTTProvider    — SpeechRecognition + Google Web STT (free, online)
        ├── WhisperSTTProvider   — OpenAI Whisper API (cloud, high accuracy)
        └── OfflineSTTProvider   — SpeechRecognition + CMU Sphinx (no internet)

Security:
    - Only audio captured after wake-word detection is sent to STT.
    - Transcripts are logged at DEBUG level only if logging is verbose.
    - No raw audio is logged.

Privacy:
    - GoogleSTTProvider sends audio to Google's servers.
    - WhisperSTTProvider sends audio to OpenAI's servers.
    - OfflineSTTProvider keeps everything local.
    - The provider is configurable in config.yaml.
"""

from __future__ import annotations

import asyncio
import io
import time
from abc import ABC, abstractmethod
from typing import Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import (
    STTEmptyError, STTProviderError, STTTimeoutError,
)
from harma.voice.models import AudioBuffer, VoiceCommand

log = get_logger(__name__)

# Default timeout for STT operations
DEFAULT_STT_TIMEOUT = 15.0   # seconds


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Provider
# ─────────────────────────────────────────────────────────────────────────────

class STTProvider(ABC):
    """
    Abstract speech-to-text provider.

    All implementations must be interchangeable.
    """

    @abstractmethod
    async def transcribe(self, audio: AudioBuffer) -> VoiceCommand:
        """
        Convert audio to text.

        Args:
            audio: Captured microphone audio.

        Returns:
            VoiceCommand with transcript and metadata.

        Raises:
            STTEmptyError:    Transcript is empty/unintelligible.
            STTTimeoutError:  Transcription took too long.
            STTProviderError: Provider returned an error.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""


# ─────────────────────────────────────────────────────────────────────────────
# Google Web STT (default — free, online)
# ─────────────────────────────────────────────────────────────────────────────

class GoogleSTTProvider(STTProvider):
    """
    Uses SpeechRecognition with Google Web Speech API.

    Advantages: Free, fast, good accuracy for English.
    Disadvantages: Requires internet. Limited to ~1 min audio.
    Privacy: Audio is sent to Google's servers.
    """

    def __init__(
        self,
        language: str = "en-IN",
        timeout: float = DEFAULT_STT_TIMEOUT,
    ) -> None:
        self._language = language
        self._timeout = timeout
        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
        except ImportError:
            raise STTProviderError(
                "SpeechRecognition package required.\n"
                "Install: pip install SpeechRecognition"
            )
        log.info("[STT] GoogleSTTProvider ready  lang=%s", language)

    @property
    def name(self) -> str:
        return "Google Web STT"

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language:
            self._language = language
            log.info("[STT] Language switched to: %s", language)

    async def transcribe(self, audio: AudioBuffer) -> VoiceCommand:
        if audio.is_empty():
            raise STTEmptyError("Audio buffer is empty.")

        t_start = time.time()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._do_transcribe, audio),
                timeout=self._timeout,
            )
            latency_ms = (time.time() - t_start) * 1000
            log.info("[STT] Transcribed  latency=%.0fms  chars=%d", latency_ms, len(result))
            return VoiceCommand(
                transcript=result.strip().lower(),
                raw=result.strip(),
                latency_ms=latency_ms,
            )
        except asyncio.TimeoutError:
            raise STTTimeoutError(f"STT timed out after {self._timeout}s")

    def _do_transcribe(self, audio: AudioBuffer) -> str:
        """Synchronous transcription — run in thread."""
        from harma.voice.microphone import MicrophoneCapture
        sr = self._sr
        wav_bytes = MicrophoneCapture.buffer_to_wav_bytes(audio)
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = self._recognizer.record(source)
        try:
            return self._recognizer.recognize_google(
                audio_data, language=self._language
            )
        except sr.UnknownValueError:
            raise STTEmptyError("Google STT could not understand audio.")
        except sr.RequestError as exc:
            raise STTProviderError(f"Google STT request failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI Whisper API
# ─────────────────────────────────────────────────────────────────────────────

class WhisperSTTProvider(STTProvider):
    """
    Uses the OpenAI Whisper API for high-accuracy transcription.

    Requires: openai package + HARMA_API_KEY or OPENAI_API_KEY.
    Privacy: Audio is sent to OpenAI's servers.
    """

    def __init__(
        self,
        model: str = "whisper-1",
        language: Optional[str] = None,
        timeout: float = DEFAULT_STT_TIMEOUT,
        api_key: Optional[str] = None,
    ) -> None:
        self._model = model
        self._language = language
        self._timeout = timeout
        self._api_key = api_key
        try:
            import openai
            self._openai = openai
        except ImportError:
            raise STTProviderError("openai package required: pip install openai")
        log.info("[STT] WhisperSTTProvider ready  model=%s", model)

    @property
    def name(self) -> str:
        return f"Whisper ({self._model})"

    async def transcribe(self, audio: AudioBuffer) -> VoiceCommand:
        if audio.is_empty():
            raise STTEmptyError("Audio buffer is empty.")

        t_start = time.time()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._do_transcribe, audio),
                timeout=self._timeout,
            )
            latency_ms = (time.time() - t_start) * 1000
            log.info("[STT] Whisper transcribed  latency=%.0fms  chars=%d", latency_ms, len(result))
            return VoiceCommand(
                transcript=result.strip().lower(),
                raw=result.strip(),
                latency_ms=latency_ms,
            )
        except asyncio.TimeoutError:
            raise STTTimeoutError(f"Whisper timed out after {self._timeout}s")

    def _do_transcribe(self, audio: AudioBuffer) -> str:
        from harma.voice.microphone import MicrophoneCapture
        import os
        import tempfile

        wav_bytes = MicrophoneCapture.buffer_to_wav_bytes(audio)
        client = self._openai.OpenAI(
            api_key=self._api_key or os.environ.get("HARMA_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                kwargs = {"model": self._model, "file": f}
                if self._language:
                    kwargs["language"] = self._language
                response = client.audio.transcriptions.create(**kwargs)
            return response.text
        except Exception as exc:
            raise STTProviderError(f"Whisper API error: {exc}") from exc
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Offline STT (CMU Sphinx — no internet)
# ─────────────────────────────────────────────────────────────────────────────

class OfflineSTTProvider(STTProvider):
    """
    Offline STT using CMU Sphinx via SpeechRecognition.

    Requires: pip install pocketsphinx
    Privacy: Fully local, no network.
    Accuracy: Lower than cloud providers.
    """

    def __init__(self, timeout: float = DEFAULT_STT_TIMEOUT) -> None:
        self._timeout = timeout
        try:
            import speech_recognition as sr
            self._sr = sr
            self._recognizer = sr.Recognizer()
        except ImportError:
            raise STTProviderError("SpeechRecognition required: pip install SpeechRecognition")
        log.info("[STT] OfflineSTTProvider ready (CMU Sphinx)")

    @property
    def name(self) -> str:
        return "Offline (CMU Sphinx)"

    async def transcribe(self, audio: AudioBuffer) -> VoiceCommand:
        if audio.is_empty():
            raise STTEmptyError("Audio buffer is empty.")
        t_start = time.time()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._do_transcribe, audio),
                timeout=self._timeout,
            )
            latency_ms = (time.time() - t_start) * 1000
            return VoiceCommand(transcript=result.lower(), raw=result, latency_ms=latency_ms)
        except asyncio.TimeoutError:
            raise STTTimeoutError(f"Offline STT timed out after {self._timeout}s")

    def _do_transcribe(self, audio: AudioBuffer) -> str:
        from harma.voice.microphone import MicrophoneCapture
        sr = self._sr
        wav_bytes = MicrophoneCapture.buffer_to_wav_bytes(audio)
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = self._recognizer.record(source)
        try:
            return self._recognizer.recognize_sphinx(audio_data)
        except sr.UnknownValueError:
            raise STTEmptyError("Sphinx could not understand audio.")
        except Exception as exc:
            raise STTProviderError(f"Sphinx error: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_stt_provider(provider_name: str = "google", **kwargs) -> STTProvider:
    """
    Factory: return the requested STT provider.

    provider_name: "google" | "whisper" | "offline"
    """
    name = provider_name.lower().strip()
    if name == "google":
        return GoogleSTTProvider(**kwargs)
    elif name == "whisper":
        return WhisperSTTProvider(**kwargs)
    elif name in ("offline", "sphinx"):
        return OfflineSTTProvider(**kwargs)
    else:
        log.warning("[STT] Unknown provider %r — defaulting to Google.", provider_name)
        return GoogleSTTProvider()
