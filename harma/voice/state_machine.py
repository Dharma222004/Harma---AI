"""
Harma Voice — Voice State Machine (Spec §3)

Strict Voice State Machine for Harma Personal AI Assistant:
    IDLE
    WAITING_FOR_WAKE_WORD
    WAKE_DETECTED
    LISTENING
    TRANSCRIBING
    UNDERSTANDING
    EXECUTING
    SPEAKING
    INTERRUPTED
    ERROR

Normal lifecycle:
    WAITING_FOR_WAKE_WORD
            ↓
      WAKE_DETECTED
            ↓
        LISTENING
            ↓
       TRANSCRIBING
            ↓
       UNDERSTANDING
            ↓
        EXECUTING
            ↓
        SPEAKING
            ↓
    WAITING_FOR_WAKE_WORD (or LISTENING for follow-up session)
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import VoiceStateError
from harma.voice.models import VoiceState, _VOICE_TRANSITIONS

log = get_logger(__name__)

VoiceStateListener = Callable[[VoiceState, VoiceState], None]


class VoiceStateMachine:
    """
    Thread-safe implementation of Harma's Voice State Machine.
    Guarantees valid transitions and notifies registered listeners.
    """

    def __init__(self, initial_state: VoiceState = VoiceState.IDLE) -> None:
        self._state: VoiceState = initial_state
        self._previous: Optional[VoiceState] = None
        self._lock = threading.Lock()
        self._listeners: List[VoiceStateListener] = []
        self._entered_at: float = time.time()

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def previous(self) -> Optional[VoiceState]:
        return self._previous

    @property
    def time_in_state(self) -> float:
        return time.time() - self._entered_at

    def is_in(self, *states: VoiceState) -> bool:
        return self._state in states

    def add_listener(self, listener: VoiceStateListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: VoiceStateListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def transition(self, new_state: VoiceState) -> None:
        with self._lock:
            current = self._state
            if current == new_state:
                return
            allowed = _VOICE_TRANSITIONS.get(current, set())
            if new_state not in allowed:
                raise VoiceStateError(
                    f"Illegal voice state transition: {current.value} → {new_state.value}. "
                    f"Allowed: {[s.value for s in allowed]}"
                )
            self._previous = current
            self._state = new_state
            self._entered_at = time.time()

        log.debug("[VOICE-STATE] %s → %s", current.value, new_state.value)

        for listener in list(self._listeners):
            try:
                listener(current, new_state)
            except Exception as exc:
                log.warning("[VOICE-STATE] Listener error: %s", exc)

    def try_transition(self, new_state: VoiceState) -> bool:
        try:
            self.transition(new_state)
            return True
        except VoiceStateError:
            return False

    def force_state(self, state: VoiceState) -> None:
        """Force state reset on error or shutdown."""
        with self._lock:
            self._previous = self._state
            self._state = state
            self._entered_at = time.time()
