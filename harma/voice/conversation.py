"""
Harma Voice — Conversation Mode — Phase 4

Manages single-command and continuous conversation modes.

Single-command mode (default):
    Wake → Listen → Execute → Speak → Idle

Continuous conversation mode:
    Wake → Listen → Execute → Speak → Listen → ... (until exit or timeout)

Confirmation dialogue:
    When the agent needs user approval (SENSITIVE/HIGH_RISK actions),
    the conversation manager handles the spoken confirmation flow:
        "Shall I proceed?" → Listen → "yes" / "no"

Exit commands:
    "Goodbye Harma", "Stop listening", "Exit conversation", etc.
    Detected by VoiceCommand.is_exit_command().

Timeout:
    If no speech is detected for inactivity_timeout_seconds, conversation exits.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Callable, Optional

from harma.config.logging_config import get_logger
from harma.voice.exceptions import ConversationError
from harma.voice.models import AudioState, VoiceCommand, VoiceEvent

if TYPE_CHECKING:
    from harma.voice.manager import VoiceManager

log = get_logger(__name__)

# Default confirmation prompts
_CONFIRM_PROMPT = "Shall I proceed?"
_CONFIRM_YES_PROMPT = "Please say yes to confirm or no to cancel."


class ConversationMode:
    """
    Manages voice conversation lifecycle.

    Does NOT contain agent logic.
    Calls back to VoiceManager for each command.
    """

    def __init__(
        self,
        manager: "VoiceManager",
        enabled: bool = False,
        inactivity_timeout: float = 30.0,
        max_duration: float = 600.0,    # 10 minutes hard cap
    ) -> None:
        self._manager = manager
        self._enabled = enabled
        self._inactivity_timeout = inactivity_timeout
        self._max_duration = max_duration
        self._active = False
        self._last_activity = 0.0
        self._start_time = 0.0

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_continuous(self) -> bool:
        return self._enabled

    # ── Conversation entry points ─────────────────────────────────────────────

    async def run_single(self, command: VoiceCommand) -> None:
        """
        Process a single voice command.
        After the agent responds, return to idle (no auto-listen).
        """
        log.info("[CONV] Single command: %r", command.transcript)
        self._bump_activity()
        await self._dispatch(command)

    async def run_continuous(self) -> None:
        """
        Run continuous conversation until exit command, timeout, or shutdown.
        """
        if not self._enabled:
            raise ConversationError("Continuous conversation mode is not enabled.")

        self._active = True
        self._start_time = time.time()
        self._bump_activity()
        log.info("[CONV] Continuous conversation started.")
        self._emit(VoiceEvent.CONVERSATION_STARTED)

        try:
            while self._active:
                # Hard cap
                if time.time() - self._start_time > self._max_duration:
                    log.info("[CONV] Max duration reached — ending conversation.")
                    self._emit(VoiceEvent.CONVERSATION_ENDED)
                    break

                # Inactivity timeout
                if time.time() - self._last_activity > self._inactivity_timeout:
                    log.info("[CONV] Inactivity timeout — ending conversation.")
                    self._emit(VoiceEvent.CONVERSATION_TIMEOUT)
                    await self._manager.speak("I didn't hear anything. Goodbye for now.")
                    break

                # Listen for next command
                command = await self._manager.listen_once()
                if command is None:
                    await asyncio.sleep(0.5)
                    continue

                self._bump_activity()

                # Exit command?
                if command.is_exit_command():
                    log.info("[CONV] Exit command received.")
                    await self._manager.speak("Goodbye!")
                    self._emit(VoiceEvent.CONVERSATION_ENDED)
                    break

                await self._dispatch(command)

        finally:
            self._active = False
            log.info("[CONV] Conversation ended.")

    def end(self) -> None:
        """Externally signal the conversation to end."""
        self._active = False

    # ── Confirmation dialogue ─────────────────────────────────────────────────

    async def get_voice_confirmation(self, prompt: Optional[str] = None) -> str:
        """
        Speak a confirmation prompt and listen for yes/no response.

        Returns:
            "yes" or "no" — never empty, never None.
        """
        spoken_prompt = prompt or _CONFIRM_PROMPT
        await self._manager.speak(spoken_prompt)

        command = await self._manager.listen_once(timeout=10.0)
        if command is None:
            return "no"  # silence = no

        if command.is_confirmation():
            return "yes"
        if command.is_rejection():
            return "no"

        # Ambiguous — ask once more
        await self._manager.speak(_CONFIRM_YES_PROMPT)
        command2 = await self._manager.listen_once(timeout=10.0)
        if command2 and command2.is_confirmation():
            return "yes"
        return "no"

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _dispatch(self, command: VoiceCommand) -> None:
        """Send a command to the VoiceManager's agent integration."""
        try:
            await self._manager.handle_command(command)
        except Exception as exc:
            log.error("[CONV] Command dispatch error: %s", exc)
            await self._manager.speak("Something went wrong. Please try again.")

    def _bump_activity(self) -> None:
        self._last_activity = time.time()

    def _emit(self, event: VoiceEvent) -> None:
        log.info("[CONV] Event: %s", event.value)
