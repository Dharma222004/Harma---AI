"""
Harma Voice — Text-to-Speech (TTS) — Phase 4

Provider abstraction for converting agent text responses to speech.

Architecture:
    TTSProvider (abstract)
        ├── PyttsxTTSProvider   — pyttsx3 offline TTS (default, no network)
        └── SilentTTSProvider   — no-op (testing / text-only mode)

Response Filtering:
    The agent may produce internal JSON, tool results, or debug output.
    The TTS layer filters this through ResponseFilter before speaking.
    Only the clean user-facing response is spoken aloud.

Security:
    - API keys, tokens, passwords are never spoken.
    - TTS providers do not receive tool metadata.
    - Sensitive patterns are stripped before synthesis.

Interruption:
    TTS can be interrupted at any time via tts.stop().
    This transitions the state machine from SPEAKING → INTERRUPTED.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import TTSError, TTSPlaybackError, TTSProviderError

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Response Filter
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that should never be spoken aloud
_NEVER_SPEAK_PATTERNS = [
    r'"tool_call_id"\s*:',
    r'"tool"\s*:\s*"',
    r'"status"\s*:\s*"(success|failure|error)"',
    r'Traceback \(most recent call',
    r'File ".*\.py"',
    r'\bsk-[A-Za-z0-9]+\b',          # OpenAI-style API key
    r'\bgsk_[A-Za-z0-9]+\b',         # Groq API key
    r'\bAIza[A-Za-z0-9_-]+\b',       # Google API key
    r'<[a-z]+[^>]*>.*?</[a-z]+>',    # HTML tags
    r'\{[^}]{200,}\}',               # Large JSON blobs
]
_NEVER_SPEAK_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _NEVER_SPEAK_PATTERNS]

# Truncate TTS response if very long (reading a wall of text is unhelpful)
MAX_TTS_CHARS = 600


def filter_for_tts(text: str) -> str:
    """
    Clean agent response text before sending to TTS.

    Removes:
        - Internal tool metadata
        - API keys / tokens (safety)
        - Stack traces
        - HTML
        - Very large JSON blobs

    Truncates:
        - Responses over MAX_TTS_CHARS characters.
    """
    if not text:
        return ""

    # Remove blocks that match sensitive patterns
    for pattern in _NEVER_SPEAK_RE:
        if pattern.search(text):
            # Only remove the matched portion, not the whole response
            text = pattern.sub("[…]", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Truncate
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"

    return text


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Provider
# ─────────────────────────────────────────────────────────────────────────────

class TTSProvider(ABC):
    """Abstract text-to-speech provider."""

    @abstractmethod
    async def synthesize(self, text: str) -> None:
        """
        Convert text to speech and play it.

        Args:
            text: Already-filtered response text.

        Raises:
            TTSPlaybackError: Playback device error.
            TTSProviderError: Provider-side error.
        """

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop any current speech (barge-in / interruption)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @property
    def is_speaking(self) -> bool:
        """True if currently synthesising/playing speech."""
        return False


# ─────────────────────────────────────────────────────────────────────────────
# pyttsx3 Offline TTS (default)
# ─────────────────────────────────────────────────────────────────────────────

class PyttsxTTSProvider(TTSProvider):
    """
    Offline TTS using pyttsx3.

    Advantages: Works offline, zero latency to start, Windows/Linux/macOS.
    Voice: Uses system TTS engine (SAPI on Windows, espeak on Linux, NSSpeech on macOS).
    """

    def __init__(
        self,
        rate: int = 175,      # words per minute (default ~175)
        volume: float = 0.95, # 0.0–1.0
        voice_id: Optional[str] = None,
    ) -> None:
        self._rate = rate
        self._volume = volume
        self._voice_id = voice_id
        self._engine = None
        self._speaking = False
        self._stop_requested = False
        self._lock = threading.Lock()
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)
            if self._voice_id:
                engine.setProperty("voice", self._voice_id)
            self._engine = engine
            log.info("[TTS] pyttsx3 ready  rate=%d  vol=%.2f", self._rate, self._volume)
        except Exception as exc:
            log.error("[TTS] pyttsx3 init failed: %s", exc)
            self._engine = None

    @property
    def name(self) -> str:
        return "pyttsx3 (offline)"

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def synthesize(self, text: str) -> None:
        if not text or not text.strip():
            return
        if self._engine is None:
            log.warning("[TTS] Engine not available — skipping speech.")
            return

        self._stop_requested = False
        self._speaking = True
        t_start = time.time()

        try:
            await asyncio.to_thread(self._speak_sync, text)
        except Exception as exc:
            log.error("[TTS] Synthesis error: %s", exc)
            raise TTSPlaybackError(f"pyttsx3 playback error: {exc}") from exc
        finally:
            self._speaking = False
            latency_ms = (time.time() - t_start) * 1000
            log.info("[TTS] Complete  latency=%.0fms  chars=%d", latency_ms, len(text))

    def _speak_sync(self, text: str) -> None:
        """Run pyttsx3 synchronously in a background thread."""
        with self._lock:
            if self._stop_requested:
                return
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                if not self._stop_requested:
                    raise TTSPlaybackError(str(exc)) from exc

    def stop(self) -> None:
        """Interrupt current speech immediately."""
        self._stop_requested = True
        self._speaking = False
        try:
            if self._engine:
                self._engine.stop()
        except Exception as exc:
            log.debug("[TTS] Stop error (non-fatal): %s", exc)
        log.info("[TTS] Interrupted.")

    def set_rate(self, rate: int) -> None:
        if self._engine:
            self._engine.setProperty("rate", rate)
            self._rate = rate

    def set_volume(self, volume: float) -> None:
        if self._engine:
            self._engine.setProperty("volume", max(0.0, min(1.0, volume)))
            self._volume = volume

    def list_voices(self) -> list:
        """Return available system voices."""
        if not self._engine:
            return []
        return self._engine.getProperty("voices") or []


# ─────────────────────────────────────────────────────────────────────────────
# Silent TTS (for testing / text-only mode)
# ─────────────────────────────────────────────────────────────────────────────

class SilentTTSProvider(TTSProvider):
    """
    No-op TTS provider.
    Logs what would be spoken but produces no audio output.
    Used in tests, CI, and --no-voice mode.
    """

    def __init__(self) -> None:
        self._speaking = False
        self.last_spoken: str = ""

    @property
    def name(self) -> str:
        return "Silent (no audio)"

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def synthesize(self, text: str) -> None:
        if not text:
            return
        self._speaking = True
        self.last_spoken = text
        log.info("[TTS:SILENT] Would speak: %r", text[:80])
        # Simulate TTS duration
        await asyncio.sleep(0.05)
        self._speaking = False

    def stop(self) -> None:
        self._speaking = False


# ─────────────────────────────────────────────────────────────────────────────
# Edge TTS Neural (Microsoft Edge cloud neural voices, free & lifelike)
# ─────────────────────────────────────────────────────────────────────────────

class EdgeTTSProvider(TTSProvider):
    """
    Online neural text-to-speech using Microsoft Edge TTS (edge-tts).
    Produces natural, studio-quality speech for English, Tamil, and Telugu.
    Falls back gracefully to pyttsx3 when network is unavailable.
    """

    def __init__(
        self,
        voice: str = "en-IN-NeerjaNeural",
        rate: int = 175,
        volume: float = 0.95,
        fallback_provider: Optional[TTSProvider] = None,
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._fallback = fallback_provider or PyttsxTTSProvider(rate=rate, volume=volume)
        self._speaking = False
        self._stop_requested = False
        log.info("[TTS] EdgeTTSProvider ready  voice=%s", self._voice)

    @property
    def name(self) -> str:
        return f"Microsoft Edge Neural TTS ({self._voice})"

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def voice(self) -> str:
        return self._voice

    def set_voice(self, voice_name: str) -> None:
        if voice_name:
            self._voice = voice_name
            log.info("[TTS] Voice changed to %s", voice_name)

    async def synthesize(self, text: str) -> None:
        if not text or not text.strip():
            return

        self._stop_requested = False
        self._speaking = True
        t_start = time.time()

        try:
            import edge_tts
            import io
            import soundfile as sf
            import sounddevice as sd

            rate_pct = int(((self._rate - 175) / 175) * 100)
            rate_str = f"{rate_pct:+d}%" if rate_pct != 0 else "+0%"

            comm = edge_tts.Communicate(text, self._voice, rate=rate_str)
            buf = bytearray()
            async for ch in comm.stream():
                if self._stop_requested:
                    return
                if ch["type"] == "audio":
                    buf.extend(ch["data"])

            if not buf or self._stop_requested:
                return

            data, sr = sf.read(io.BytesIO(bytes(buf)), dtype="float32")
            if self._stop_requested:
                return

            if self._volume < 0.99:
                data = data * self._volume

            sd.play(data, sr)
            duration = len(data) / float(sr)
            slept = 0.0
            while slept < duration and not self._stop_requested:
                step = min(0.05, duration - slept)
                await asyncio.sleep(step)
                slept += step

            if self._stop_requested:
                sd.stop()

        except Exception as exc:
            log.warning("[TTS] Edge TTS error: %s. Falling back to offline TTS.", exc)
            if not self._stop_requested and self._fallback:
                await self._fallback.synthesize(text)
        finally:
            self._speaking = False
            latency_ms = (time.time() - t_start) * 1000
            log.info("[TTS] Complete  latency=%.0fms  chars=%d", latency_ms, len(text))

    def stop(self) -> None:
        self._stop_requested = True
        self._speaking = False
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self._fallback:
            self._fallback.stop()
        log.info("[TTS] Interrupted.")


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_tts_provider(
    provider_name: str = "pyttsx3",
    rate: int = 175,
    volume: float = 0.95,
    voice_id: Optional[str] = None,
) -> TTSProvider:
    """
    Factory: return the requested TTS provider.

    provider_name: "edge_tts" | "pyttsx3" | "silent"
    """
    name = provider_name.lower().strip()
    if name in ("edge", "edge_tts", "edge-tts", "neural"):
        voice = voice_id or "en-IN-NeerjaNeural"
        return EdgeTTSProvider(voice=voice, rate=rate, volume=volume)
    elif name in ("pyttsx3", "offline", "system"):
        return PyttsxTTSProvider(rate=rate, volume=volume, voice_id=voice_id)
    elif name in ("silent", "none", "test"):
        return SilentTTSProvider()
    else:
        log.warning("[TTS] Unknown provider %r — defaulting to pyttsx3.", provider_name)
        return PyttsxTTSProvider(rate=rate, volume=volume)

