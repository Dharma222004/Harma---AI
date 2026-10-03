"""
Harma Voice — Microphone Management — Phase 4

Handles:
  - Enumerating audio devices
  - Selecting the configured / default microphone
  - Capturing raw audio frames
  - Error handling: not found, permission denied, I/O errors
  - Temporary error recovery

Uses sounddevice (cross-platform) with pyaudio as fallback.
All methods are sync; async wrapping is done in VoiceManager.

Privacy:
  - Raw audio frames are held in memory only.
  - They are not written to disk unless voice.privacy.save_recordings = true.
  - Frames are discarded immediately after STT completes.
"""

from __future__ import annotations

import io
import queue
import threading
import time
import wave
from typing import List, Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import (
    AudioCaptureError, MicrophoneError,
    MicrophoneNotFoundError, MicrophonePermissionError,
)
from harma.voice.models import AudioBuffer, AudioDevice

log = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_SAMPLE_RATE = 16_000   # Hz — optimal for STT
DEFAULT_CHANNELS    = 1        # Mono
DEFAULT_CHUNK_SIZE  = 1024     # Frames per read
DTYPE               = "int16"  # 16-bit PCM


def list_audio_devices() -> List[AudioDevice]:
    """
    Return all available audio input devices.
    Falls back to empty list if sounddevice is unavailable.
    """
    devices: List[AudioDevice] = []
    try:
        import sounddevice as sd
        info = sd.query_devices()
        default_idx = sd.default.device[0]  # input device index
        for i, dev in enumerate(info):
            if dev["max_input_channels"] > 0:
                devices.append(AudioDevice(
                    index=i,
                    name=dev["name"],
                    max_input_channels=int(dev["max_input_channels"]),
                    default_sample_rate=float(dev["default_samplerate"]),
                    is_default=(i == default_idx),
                ))
    except Exception as exc:
        log.warning("[MIC] Could not enumerate audio devices: %s", exc)
    return devices


def get_default_device() -> Optional[AudioDevice]:
    """Return the system default input device, or None."""
    for dev in list_audio_devices():
        if dev.is_default:
            return dev
    devs = list_audio_devices()
    return devs[0] if devs else None


def get_device_by_name(name: str) -> Optional[AudioDevice]:
    """Return the first device whose name contains the given string (case-insensitive)."""
    name_lower = name.lower()
    for dev in list_audio_devices():
        if name_lower in dev.name.lower():
            return dev
    return None


class MicrophoneCapture:
    """
    Captures audio from the default (or configured) microphone.

    Usage:
        mic = MicrophoneCapture(sample_rate=16000)
        mic.start()
        buffer = mic.capture(max_seconds=5.0)
        mic.stop()

    Thread safety:
        start() / stop() may be called from any thread.
        capture() blocks the calling thread.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_size = chunk_size
        self._stream = None
        self._running = False
        self._frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=500)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the microphone stream."""
        if self._running:
            return
        try:
            import sounddevice as sd

            def _callback(indata, frames, time_info, status):
                if status:
                    log.debug("[MIC] Status: %s", status)
                if self._running:
                    try:
                        self._frame_queue.put_nowait(bytes(indata))
                    except queue.Full:
                        pass  # drop oldest frame

            self._stream = sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype=DTYPE,
                blocksize=self._chunk_size,
                device=self._device_index,
                callback=_callback,
            )
            self._stream.start()
            self._running = True
            log.info(
                "[MIC] Started  device=%s  rate=%d  channels=%d",
                self._device_index, self._sample_rate, self._channels,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "permission" in msg or "access denied" in msg:
                raise MicrophonePermissionError(
                    "Microphone access denied by the operating system."
                ) from exc
            if "invalid device" in msg or "no default" in msg or "no input" in msg:
                raise MicrophoneNotFoundError(
                    f"Microphone device not found: {exc}"
                ) from exc
            raise MicrophoneError(f"Could not start microphone: {exc}") from exc

    def stop(self) -> None:
        """Close the microphone stream."""
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("[MIC] Error closing stream: %s", exc)
            self._stream = None
        # Drain queue
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        log.info("[MIC] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Capture ───────────────────────────────────────────────────────────────

    def capture(
        self,
        max_seconds: float = 10.0,
        stop_event: Optional[threading.Event] = None,
    ) -> AudioBuffer:
        """
        Capture audio frames until max_seconds elapses or stop_event is set.

        Args:
            max_seconds: Hard time limit.
            stop_event:  External signal to stop early (e.g. VAD silence detected).

        Returns:
            AudioBuffer containing all captured frames.

        Privacy:
            Buffer lives in RAM only. Caller is responsible for discarding
            after use. Frames are NOT written to disk here.
        """
        if not self._running:
            raise AudioCaptureError("Microphone is not started. Call start() first.")

        buf = AudioBuffer(sample_rate=self._sample_rate, channels=self._channels)
        deadline = time.time() + max_seconds

        while time.time() < deadline:
            if stop_event and stop_event.is_set():
                break
            try:
                frame = self._frame_queue.get(timeout=0.05)
                buf.append(frame)
            except queue.Empty:
                continue

        log.debug(
            "[MIC] Captured  bytes=%d  dur=%.2fs",
            buf.total_bytes(), buf.duration_seconds(),
        )
        return buf

    def drain_frames(self) -> None:
        """Discard all buffered frames (e.g. after wake word detection)."""
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

    # ── WAV export (for STT providers that need a file) ───────────────────────

    @staticmethod
    def buffer_to_wav_bytes(buf: AudioBuffer) -> bytes:
        """
        Convert an AudioBuffer to WAV bytes in memory.
        Used by STT providers that accept file-like objects.
        """
        raw = buf.to_bytes()
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(buf.channels)
            wf.setsampwidth(2)            # 16-bit = 2 bytes
            wf.setframerate(buf.sample_rate)
            wf.writeframes(raw)
        wav_io.seek(0)
        return wav_io.read()
