"""
Harma Voice — Voice Activity Detection (VAD) — Phase 4

Pure-Python energy-based VAD.
No C++ build tools required (unlike webrtcvad).

Algorithm:
  1. Compute RMS energy of each audio frame.
  2. Compare against a calibrated threshold.
  3. Speech = RMS > threshold for >= minimum_speech_ms.
  4. Silence = RMS < threshold for >= silence_timeout_ms.

The threshold is auto-calibrated from the first 500ms of ambient audio,
then adjusted with a configurable multiplier.

This approach works well for typical office/home environments.
For very noisy environments, switch to a dedicated VAD model.
"""

from __future__ import annotations

import array
import math
import struct
import threading
import time
from typing import Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import VADError
from harma.voice.models import AudioBuffer

log = get_logger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_SILENCE_TIMEOUT_MS  = 1200   # Stop listening after 1.2s of silence
DEFAULT_MIN_SPEECH_MS       = 250    # Require 250ms of speech before recording
DEFAULT_THRESHOLD_MULTIPLIER = 2.5   # threshold = ambient_rms * multiplier
DEFAULT_AMBIENT_FRAMES      = 20     # Frames to sample for ambient calibration
MAX_RECORDING_SECONDS       = 30     # Absolute upper limit on recording duration


def _compute_rms(frame: bytes) -> float:
    """
    Compute Root Mean Square energy of a 16-bit PCM audio frame.
    Returns 0.0 if the frame is empty.
    """
    if not frame or len(frame) < 2:
        return 0.0
    try:
        count = len(frame) // 2
        shorts = struct.unpack(f"<{count}h", frame[:count * 2])
        sum_sq = sum(s * s for s in shorts)
        return math.sqrt(sum_sq / count)
    except Exception:
        return 0.0


class EnergyVAD:
    """
    Energy-based Voice Activity Detector.

    Thread-safe. Can be used from a callback or a polling loop.

    Usage:
        vad = EnergyVAD(silence_timeout_ms=1200, minimum_speech_ms=300)
        vad.calibrate(ambient_frames)   # optional; sets threshold
        speaking = vad.is_speech(frame)
        done     = vad.is_done()        # True = speech ended
    """

    def __init__(
        self,
        silence_timeout_ms: int = DEFAULT_SILENCE_TIMEOUT_MS,
        minimum_speech_ms: int = DEFAULT_MIN_SPEECH_MS,
        threshold_multiplier: float = DEFAULT_THRESHOLD_MULTIPLIER,
        sample_rate: int = 16_000,
        chunk_size: int = 1024,
    ) -> None:
        self._silence_timeout_ms = silence_timeout_ms
        self._min_speech_ms = minimum_speech_ms
        self._threshold_multiplier = threshold_multiplier
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size

        # Duration of one frame in ms
        self._frame_ms = (chunk_size / sample_rate) * 1000

        # State
        self._threshold: float = 500.0   # default; overridden by calibrate()
        self._speech_frames: int = 0     # consecutive speech frames
        self._silence_frames: int = 0    # consecutive silence frames
        self._speech_detected: bool = False
        self._lock = threading.Lock()

    # ── Calibration ───────────────────────────────────────────────────────────

    def calibrate(self, ambient_frames: list[bytes]) -> None:
        """
        Set the energy threshold from ambient (background) audio frames.
        Call this with the first ~20 frames of microphone input before
        the wake word is detected.
        """
        if not ambient_frames:
            return
        rms_values = [_compute_rms(f) for f in ambient_frames if f]
        if not rms_values:
            return
        ambient_rms = sum(rms_values) / len(rms_values)
        self._threshold = max(ambient_rms * self._threshold_multiplier, 200.0)
        log.info(
            "[VAD] Calibrated  ambient_rms=%.1f  threshold=%.1f",
            ambient_rms, self._threshold,
        )

    def set_threshold(self, threshold: float) -> None:
        """Manually set the energy threshold."""
        self._threshold = threshold

    # ── Frame processing ──────────────────────────────────────────────────────

    def process_frame(self, frame: bytes) -> bool:
        """
        Process one audio frame. Returns True if currently in speech.

        Side effects:
            Updates speech/silence frame counters.
            Sets _speech_detected once minimum_speech_ms threshold is reached.
        """
        rms = _compute_rms(frame)
        with self._lock:
            if rms >= self._threshold:
                self._speech_frames += 1
                self._silence_frames = 0
                if self._speech_frames * self._frame_ms >= self._min_speech_ms:
                    self._speech_detected = True
                return True
            else:
                self._silence_frames += 1
                self._speech_frames = 0
                return False

    def is_speech(self, frame: bytes) -> bool:
        """True if this frame contains speech."""
        return self.process_frame(frame)

    def is_done(self) -> bool:
        """
        True when:
          - At least minimum_speech_ms of speech was detected, AND
          - silence_timeout_ms of silence has elapsed since speech stopped.
        """
        with self._lock:
            if not self._speech_detected:
                return False
            silence_ms = self._silence_frames * self._frame_ms
            return silence_ms >= self._silence_timeout_ms

    def reset(self) -> None:
        """Reset for a new utterance."""
        with self._lock:
            self._speech_frames = 0
            self._silence_frames = 0
            self._speech_detected = False

    @property
    def speech_detected(self) -> bool:
        return self._speech_detected

    @property
    def threshold(self) -> float:
        return self._threshold


class VADRecorder:
    """
    High-level VAD-aware recorder.

    Records audio from a MicrophoneCapture, stopping when the user
    stops speaking (VAD silence detection).

    Usage:
        mic = MicrophoneCapture()
        mic.start()
        recorder = VADRecorder(vad, mic)
        buffer = await recorder.record(max_seconds=30)
    """

    def __init__(self, vad: EnergyVAD, sample_rate: int = 16_000, chunk_size: int = 1024) -> None:
        self._vad = vad
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size

    def record_from_stream(
        self,
        frame_source,  # callable -> bytes | None
        max_seconds: float = MAX_RECORDING_SECONDS,
    ) -> AudioBuffer:
        """
        Record from a frame_source callable until VAD silence or max_seconds.

        frame_source() must return the next audio frame (bytes) or None.
        """
        self._vad.reset()
        buf = AudioBuffer(sample_rate=self._sample_rate, channels=1)
        deadline = time.time() + max_seconds

        while time.time() < deadline:
            frame = frame_source()
            if frame is None:
                time.sleep(0.01)
                continue

            buf.append(frame)
            self._vad.process_frame(frame)

            if self._vad.is_done():
                log.info(
                    "[VAD] Speech ended  dur=%.2fs  bytes=%d",
                    buf.duration_seconds(), buf.total_bytes(),
                )
                break

        return buf
