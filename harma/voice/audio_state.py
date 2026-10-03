"""
Harma Voice — Audio State Machine — Phase 4

A strongly-typed state machine that enforces valid voice lifecycle transitions.
Guards against impossible states (e.g. SPEAKING → WAKE_DETECTED).

Usage:
    sm = AudioStateMachine()
    sm.transition(AudioState.WAITING_FOR_WAKE_WORD)
    sm.transition(AudioState.WAKE_DETECTED)
    sm.transition(AudioState.LISTENING)
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import VoiceStateError
from harma.voice.models import AudioState, VoiceEvent, _VALID_TRANSITIONS

log = get_logger(__name__)

# Listeners receive (old_state, new_state)
StateListener = Callable[[AudioState, AudioState], None]


class AudioStateMachine:
    """
    Thread-safe audio state machine.

    Enforces _VALID_TRANSITIONS.
    Notifies registered listeners on every transition.
    """

    def __init__(self) -> None:
        self._state: AudioState = AudioState.IDLE
        self._previous: Optional[AudioState] = None
        self._lock = threading.Lock()
        self._listeners: List[StateListener] = []
        self._entered_at: float = time.time()

    # ── State access ──────────────────────────────────────────────────────────

    @property
    def state(self) -> AudioState:
        return self._state

    @property
    def previous(self) -> Optional[AudioState]:
        return self._previous

    @property
    def time_in_state(self) -> float:
        """Seconds spent in the current state."""
        return time.time() - self._entered_at

    def is_in(self, *states: AudioState) -> bool:
        return self._state in states

    # ── Transitions ───────────────────────────────────────────────────────────

    def transition(self, new_state: AudioState) -> None:
        """
        Transition to a new state.

        Raises:
            VoiceStateError: If the transition is not permitted.
        """
        with self._lock:
            current = self._state
            allowed = _VALID_TRANSITIONS.get(current, set())
            if new_state not in allowed:
                raise VoiceStateError(
                    f"Illegal voice state transition: {current.value} → {new_state.value}. "
                    f"Allowed: {[s.value for s in allowed]}"
                )
            self._previous = current
            self._state = new_state
            self._entered_at = time.time()

        log.debug(
            "[STATE] %s → %s",
            current.value.upper(), new_state.value.upper(),
        )

        for listener in list(self._listeners):
            try:
                listener(current, new_state)
            except Exception as exc:
                log.warning("[STATE] Listener error: %s", exc)

    def try_transition(self, new_state: AudioState) -> bool:
        """
        Attempt transition, returning False instead of raising on invalid.
        Useful for graceful degradation.
        """
        try:
            self.transition(new_state)
            return True
        except VoiceStateError:
            return False

    def force_idle(self) -> None:
        """Unconditionally reset to IDLE (used for error recovery)."""
        with self._lock:
            old = self._state
            self._previous = old
            self._state = AudioState.IDLE
            self._entered_at = time.time()
        log.info("[STATE] Force-reset to IDLE from %s", old.value)
        for listener in list(self._listeners):
            try:
                listener(old, AudioState.IDLE)
            except Exception:
                pass

    # ── Listeners ─────────────────────────────────────────────────────────────

    def add_listener(self, fn: StateListener) -> None:
        """Register a callback called on every state transition."""
        self._listeners.append(fn)

    def remove_listener(self, fn: StateListener) -> None:
        self._listeners = [l for l in self._listeners if l is not fn]

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AudioStateMachine(state={self._state.value!r}, "
            f"prev={self._previous.value if self._previous else None!r}, "
            f"in_state={self.time_in_state:.1f}s)"
        )
