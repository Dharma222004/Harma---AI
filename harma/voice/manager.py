"""
Harma Voice — VoiceManager — Phase 4

The central orchestrator for Phase 4 voice functionality.

VoiceManager wires together:
    Microphone → VAD → Wake Word → STT → [Existing Agent] → TTS

Design principles:
    1. Voice is ONLY an interface layer.
    2. Business logic lives in HarmaAgent (Phase 1).
    3. Existing permissions, memory, and tools are fully reused.
    4. No second agent loop.

Integration:
    VoiceManager holds a reference to HarmaAgent.
    Text from STT is passed directly to agent.run(text).
    Agent response is filtered and passed to TTS.

Permissions:
    Voice commands go through the SAME permission pipeline as text commands.
    Voice is not a special bypass path.

Privacy:
    Audio is never written to disk unless voice.privacy.save_recordings = true.
    Raw audio frames are discarded after STT.
    STT provider choice controls cloud data transmission.

Barge-in:
    If the user speaks while TTS is active, TTS is immediately interrupted.
    The state machine transitions: SPEAKING → INTERRUPTED → LISTENING.
"""

from __future__ import annotations

import asyncio
import queue
import re
import threading
import time
from typing import Optional, Any

from harma.config.logging_config import get_logger
from harma.config.settings import config
from harma.voice.audio_state import AudioStateMachine
from harma.voice.conversation import ConversationMode
from harma.voice.exceptions import (
    MicrophoneError,
    STTEmptyError,
    STTError,
    TTSError,
    VoiceError,
    WakeWordError,
)
from harma.voice.microphone import MicrophoneCapture, get_default_device
from harma.voice.models import (
    AudioBuffer,
    AudioState,
    PipelineLatency,
    VoiceCommand,
    VoiceEvent,
    VoiceState,
)
from harma.voice.state_machine import VoiceStateMachine
from harma.core.input_normalizer import (
    InputNormalizer,
    InputModality,
    HarmaRequest,
    ActionRisk,
)
from harma.core.environment import EnvironmentResolver, get_device_registry
from harma.voice.stt import STTProvider, get_stt_provider
from harma.voice.tts import TTSProvider, filter_for_tts, get_tts_provider
from harma.voice.vad import EnergyVAD
from harma.voice.wakeword import WakeWordProvider, get_wake_word_provider

log = get_logger(__name__)


class VoiceManager:
    """
    The single orchestrator for all voice operations.

    Lifecycle:
        manager = VoiceManager(agent)
        await manager.start()              # open microphone, calibrate
        await manager.run_push_to_talk()   # or run_wake_word_loop()
        await manager.stop()

    The manager is intentionally NOT a second agent.
    It is a thin interface that converts audio ↔ text ↔ HarmaAgent calls.
    """

    def __init__(
        self,
        agent,                             # HarmaAgent — the existing Phase 1 agent
        stt: Optional[STTProvider] = None,
        tts: Optional[TTSProvider] = None,
        wake_word: Optional[WakeWordProvider] = None,
    ) -> None:
        self._agent = agent
        self._state = AudioStateMachine()
        self.voice_state = VoiceStateMachine()
        self._running = False

        # Load voice config
        vcfg = config.voice

        # Build subsystems (use injected or build from config)
        self._stt: STTProvider = stt or get_stt_provider(
            provider_name=vcfg.stt_provider,
            language=vcfg.stt_language,
        )
        self._tts: TTSProvider = tts or get_tts_provider(
            provider_name=vcfg.tts_provider,
            rate=vcfg.tts_rate,
            volume=vcfg.tts_volume,
        )
        self._wake_word: WakeWordProvider = wake_word or get_wake_word_provider(
            enabled=vcfg.wake_word_enabled,
            phrase=vcfg.wake_word_phrase,
        )

        # VAD
        self._vad = EnergyVAD(
            silence_timeout_ms=vcfg.vad_silence_timeout_ms,
            minimum_speech_ms=vcfg.vad_min_speech_ms,
            sample_rate=vcfg.microphone_sample_rate,
        )

        # Microphone
        self._mic = MicrophoneCapture(
            sample_rate=vcfg.microphone_sample_rate,
            channels=vcfg.microphone_channels,
        )

        # Conversation mode
        self._conversation = ConversationMode(
            manager=self,
            enabled=vcfg.conversation_mode_enabled,
            inactivity_timeout=vcfg.conversation_inactivity_timeout,
        )

        # Config snapshots
        self._wake_word_enabled = vcfg.wake_word_enabled
        self._save_recordings = vcfg.save_recordings
        self._recordings_dir = vcfg.recordings_dir

        # Language management (English, Tamil, Telugu)
        from harma.voice.language import resolve_language, Language
        self._lang: Language = resolve_language(vcfg.stt_language)
        if hasattr(self._tts, "set_voice") and not vcfg.tts_voice_id:
            self._tts.set_voice(self._lang.voice_female)

        # Unified Input Normalizer & Environment Resolver (Spec §2, §26)
        self.normalizer = InputNormalizer(default_language=self._lang)
        self.environment_resolver = EnvironmentResolver()

        # Follow-up session context & active task handle (§5, §6, §30, §34)
        self._session_context: Optional[str] = None
        self._active_run_task: Optional[asyncio.Task] = None

        # Stop event for external interruption
        self._stop_event = threading.Event()

        # Register state change logger
        self._state.add_listener(self._on_state_change)

        log.info(
            "[VOICE] VoiceManager ready  STT=%s  TTS=%s  wake=%s  lang=%s",
            self._stt.name, self._tts.name, vcfg.wake_word_enabled, self._lang.name,
        )

    # ── Language Management ───────────────────────────────────────────────────

    @property
    def language(self):
        return self._lang

    def set_language(self, lang_or_code):
        """Switch active language (English, Tamil, Telugu)."""
        from harma.voice.language import resolve_language
        target = resolve_language(lang_or_code)
        self._lang = target
        if hasattr(self, "normalizer"):
            self.normalizer.default_language = target
        if hasattr(self._stt, "set_language"):
            self._stt.set_language(target.stt_code)
        if hasattr(self._tts, "set_voice"):
            self._tts.set_voice(target.voice_female)
        log.info("[VOICE] Active language switched to %s (%s)", target.name, target.stt_code)
        return target

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Open the microphone and perform ambient VAD calibration."""
        try:
            self._mic.start()
            log.info("[VOICE] Microphone started.")

            # Calibrate VAD from 500ms of ambient audio
            ambient = self._mic.capture(max_seconds=0.5)
            if not ambient.is_empty():
                self._vad.calibrate(ambient.frames)

            self._running = True
            self._stop_event.clear()
            self._state.try_transition(AudioState.WAITING_FOR_WAKE_WORD)
            self.voice_state.try_transition(VoiceState.WAITING_FOR_WAKE_WORD)
            self._emit(VoiceEvent.VOICE_STARTED)

        except MicrophoneError as exc:
            log.error("[VOICE] Failed to start microphone: %s", exc)
            self.voice_state.force_state(VoiceState.ERROR)
            raise

    async def stop(self) -> None:
        """Stop all voice operations and close the microphone."""
        self._running = False
        self._stop_event.set()
        await self.cancel_current_task()
        self._tts.stop()
        self._mic.stop()
        self._state.force_idle()
        self.voice_state.force_state(VoiceState.IDLE)
        self._emit(VoiceEvent.VOICE_STOPPED)
        log.info("[VOICE] VoiceManager stopped.")

    # ── Main Loop Modes ───────────────────────────────────────────────────────

    async def run_wake_word_loop(self) -> None:
        """
        Continuous Siri-style wake-word detection loop with follow-up conversation window.

        Flow:
            1. Wait for wake word ('Hey Harma')
            2. On detection -> acknowledge ('Yes?')
            3. Listen for command -> execute via agent -> speak reply
            4. Follow-up window (~8s) -> listen without requiring wake word again
            5. Return to waiting for wake word on timeout or goodbye
        """
        if not self._running:
            await self.start()

        phrase = config.voice.wake_word_phrase
        log.info("[VOICE] Wake-word loop started. Phrase: %r (Lang: %s)", phrase, self._lang.name)
        self.voice_state.try_transition(VoiceState.WAITING_FOR_WAKE_WORD)

        while self._running and not self._stop_event.is_set():
            try:
                # 1. Capture a short chunk and check for wake word
                chunk = await asyncio.to_thread(self._mic.capture, 1.8)
                if chunk.is_empty():
                    continue

                if not self._wake_word.detect(chunk):
                    continue

                # 2. Wake word detected
                self._state.try_transition(AudioState.WAKE_DETECTED)
                self.voice_state.try_transition(VoiceState.WAKE_DETECTED)
                self._emit(VoiceEvent.WAKE_WORD_DETECTED)
                log.info("[VOICE] Wake word detected!")

                # 3. Spoken acknowledgement
                greeting = self._lang.say("listening") or "Yes?"
                await self.speak(greeting)

                # 4. Listen for command
                self.voice_state.try_transition(VoiceState.LISTENING)
                command = await self.listen_once(timeout=config.voice.listen_timeout)
                if command is None:
                    await self.speak(self._lang.say("not_caught"))
                    self._state.try_transition(AudioState.WAITING_FOR_WAKE_WORD)
                    self.voice_state.try_transition(VoiceState.WAITING_FOR_WAKE_WORD)
                    continue

                # 5. Handle command
                should_continue = await self._process_voice_command(command)
                if not should_continue:
                    break

                # 6. Follow-up conversation window (~8 seconds)
                # Like Siri: user can continue speaking without saying "Hey Harma" again (Spec §5)
                followup_timeout = 8.0
                while self._running and not self._stop_event.is_set():
                    self.voice_state.try_transition(VoiceState.LISTENING)
                    next_cmd = await self.listen_once(timeout=followup_timeout)
                    if next_cmd is None:
                        break

                    raw = next_cmd.transcript.strip()
                    from harma.voice.language import is_end_conversation
                    if is_end_conversation(raw):
                        await self.speak(self._lang.say("goodbye"))
                        break

                    should_continue = await self._process_voice_command(next_cmd)
                    if not should_continue:
                        return

                self._session_context = None
                self._state.try_transition(AudioState.WAITING_FOR_WAKE_WORD)
                self.voice_state.try_transition(VoiceState.WAITING_FOR_WAKE_WORD)

            except asyncio.CancelledError:
                break
            except VoiceError as exc:
                log.error("[VOICE] Voice error in wake-word loop: %s", exc)
                self._state.force_idle()
                self.voice_state.force_state(VoiceState.IDLE)
                await asyncio.sleep(1.0)
            except Exception as exc:
                log.exception("[VOICE] Unexpected error: %s", exc)
                self._state.force_idle()
                self.voice_state.force_state(VoiceState.ERROR)
                await asyncio.sleep(2.0)

    async def run_push_to_talk(self) -> None:
        """
        Push-to-talk mode (no wake word required).

        The caller (CLI) triggers this for each user input.
        This is the development/testing mode.
        """
        if not self._running:
            await self.start()

        command = await self.listen_once(timeout=config.voice.listen_timeout)
        if command:
            await self.handle_command(command)

    # ── Core Operations ───────────────────────────────────────────────────────

    async def listen_once(self, timeout: float = 15.0) -> Optional[VoiceCommand]:
        """
        Listen for one complete utterance (VAD-bounded).

        Returns:
            VoiceCommand or None if empty/timeout.
        """
        self._state.try_transition(AudioState.LISTENING)
        self.voice_state.try_transition(VoiceState.LISTENING)
        self._emit(VoiceEvent.LISTENING_STARTED)
        self._mic.drain_frames()
        self._vad.reset()

        stop_event = threading.Event()
        t_start = time.time()
        buf = AudioBuffer(
            sample_rate=config.voice.microphone_sample_rate,
            channels=config.voice.microphone_channels,
        )

        try:
            def _frame_source():
                try:
                    return self._mic._frame_queue.get(timeout=0.05)
                except Exception:
                    return None

            # Record with VAD
            deadline = time.time() + timeout
            while time.time() < deadline and self._running:
                frame = _frame_source()
                if frame is None:
                    continue
                buf.append(frame)
                self._vad.process_frame(frame)
                if self._vad.is_done():
                    break

            self._emit(VoiceEvent.LISTENING_STOPPED)

            if buf.is_empty() or not self._vad.speech_detected:
                log.info("[VOICE] No speech detected — timeout.")
                self._state.try_transition(AudioState.TIMEOUT)
                self._state.try_transition(AudioState.IDLE)
                self.voice_state.try_transition(VoiceState.IDLE)
                return None

        except Exception as exc:
            log.error("[VOICE] Listen error: %s", exc)
            self._state.force_idle()
            self.voice_state.force_state(VoiceState.ERROR)
            return None

        # STT
        return await self._transcribe(buf)

    async def _transcribe(self, audio: AudioBuffer) -> Optional[VoiceCommand]:
        """Run STT on captured audio. Returns VoiceCommand or None."""
        self._state.try_transition(AudioState.PROCESSING)
        self.voice_state.try_transition(VoiceState.TRANSCRIBING)
        self._emit(VoiceEvent.STT_STARTED)

        # Privacy: discard audio immediately after transcription (Spec §51, §52)
        try:
            command = await self._stt.transcribe(audio)
        except STTEmptyError:
            self._emit(VoiceEvent.STT_EMPTY)
            log.info("[VOICE] STT: empty transcript.")
            self._state.try_transition(AudioState.IDLE)
            self.voice_state.try_transition(VoiceState.IDLE)
            return None
        except STTError as exc:
            self._emit(VoiceEvent.STT_FAILED)
            log.warning("[VOICE] STT failed: %s", exc)
            self._state.try_transition(AudioState.IDLE)
            self.voice_state.try_transition(VoiceState.IDLE)
            return None
        finally:
            audio.clear()

        if not command or not command.transcript.strip():
            self._emit(VoiceEvent.STT_EMPTY)
            self._state.try_transition(AudioState.IDLE)
            self.voice_state.try_transition(VoiceState.IDLE)
            return None

        self._emit(VoiceEvent.STT_COMPLETED)
        self._emit(VoiceEvent.COMMAND_RECEIVED)
        log.info(
            "[VOICE] Command: %r  latency=%.0fms",
            command.transcript, command.latency_ms,
        )
        return command

    def _format_voice_response(self, raw_response: str) -> str:
        """
        Format a concise, verified voice response adhering to spec §28 & §29.
        Never says 'Done' if verification failed or was inconclusive.
        """
        meta = getattr(self._agent, "last_execution_meta", {}) or {}
        status = meta.get("status", "")
        verification = meta.get("verification", {})
        verif_status = ""
        if isinstance(verification, dict):
            verif_status = str(verification.get("status", "")).lower()
        elif isinstance(verification, str):
            verif_status = verification.lower()

        tool_calls = meta.get("tool_calls", [])

        # If execution explicitly failed
        if status == "failed":
            if "not find" in raw_response.lower() or "not found" in raw_response.lower():
                return "I couldn't find what you requested."
            return "I couldn't complete the requested action."

        # If tools were executed but verification failed or is unverified (§29)
        if tool_calls and verif_status in ("unverified", "failed"):
            return "I performed the action, but I couldn't verify the result."

        # Format clean, concise voice response (§28)
        clean = filter_for_tts(raw_response)
        if not clean:
            return "Done."

        # If short and natural (under 120 chars), speak directly
        if len(clean) <= 120 and "\n" not in clean:
            return clean

        # Extract first sentence or concise clause for speech
        sentences = [s.strip() for s in re.split(r"[.!?\n]", clean) if s.strip()]
        if sentences:
            first = sentences[0]
            if len(first) > 15:
                return first + "."
        return "Done."

    async def cancel_current_task(self) -> None:
        """
        Immediately interrupt TTS, cancel active agent task, and propagate
        cancellation to the authoritative Harma Runtime (spec §6, §30).
        """
        self.interrupt_speech()
        if self._active_run_task and not self._active_run_task.done():
            self._active_run_task.cancel()
        if hasattr(self._agent, "cancel"):
            try:
                self._agent.cancel()
            except Exception as exc:
                log.debug("[VOICE] Agent cancel error: %s", exc)
        elif hasattr(self._agent, "cancel_plan"):
            try:
                self._agent.cancel_plan()
            except Exception as exc:
                log.debug("[VOICE] Plan cancel error: %s", exc)

        self.voice_state.try_transition(VoiceState.INTERRUPTED)
        self._state.try_transition(AudioState.INTERRUPTED)
        log.info("[VOICE] Active run and speech cancelled by user request.")

    async def _process_voice_command(self, command: VoiceCommand) -> bool:
        """
        Process a voice command utterance.
        Handles system control (shutdown, language switch, reset, cancel) or runs agent.
        Returns False if the voice loop should exit, True to continue.
        """
        from harma.voice.language import reply_instruction

        self.voice_state.try_transition(VoiceState.UNDERSTANDING)
        text = (command.transcript or command.raw or "").strip()
        if not text:
            return True

        # Normalize request through authoritative InputNormalizer (Spec §2)
        conf = command.confidence if command.confidence is not None else 1.0
        req: HarmaRequest = self.normalizer.normalize(
            raw_text=text,
            modality=InputModality.VOICE,
            confidence=conf,
            language=self._lang,
        )

        # 1. Shutdown command
        if req.is_control_command and req.control_intent == "shutdown":
            await self.speak(self._lang.say("shutdown"))
            await self.stop()
            return False

        # 2. Language switch
        if req.is_control_command and req.control_intent == "lang_switch":
            target_code = req.metadata.get("target_language")
            if not target_code:
                from harma.voice.language import detect_language_switch
                target_code = detect_language_switch(clean_text) or detect_language_switch(text)
            if target_code:
                self.set_language(target_code)
                await self.speak(self._lang.say("switched"))
                return True

        # 3. Reset command
        if req.is_control_command and req.control_intent == "reset":
            self._session_context = None
            if hasattr(self._agent, "reset"):
                self._agent.reset()
            await self.speak(self._lang.say("reset"))
            return True

        # 4. Cancel command (Barge-in / Stop / Cancel propagation - §6, §30)
        if req.is_control_command and req.control_intent == "cancel":
            await self.cancel_current_task()
            await self.speak(self._lang.say("cancelled"))
            return True

        clean_text = req.clean_goal
        if not clean_text:
            await self.speak(self._lang.say("listening"))
            return True

        # Consequential / Low-confidence safety gate (Spec §31, §32)
        if req.requires_confirmation:
            self._emit(VoiceEvent.CONFIRMATION_REQUESTED)
            if req.confidence < 0.65:
                prompt_confirm = f"I heard '{clean_text}'. Did you say that?"
            else:
                prompt_confirm = f"This action is consequential: {clean_text}. Do you want me to proceed?"
            confirm_answer = await self.voice_confirm(prompt_confirm)
            confirm_lower = confirm_answer.strip().lower()
            if confirm_lower not in ("yes", "proceed", "sure", "ok", "confirm", "continue", "yep", "yeah"):
                await self.speak(self._lang.say("cancelled"))
                return True

        # Context inheritance for follow-up conversation (§5, §34)
        if self._session_context and not any(k in clean_text.lower() for k in ("open", "launch", "start", "run")):
            full_prompt = f"Context: Continuing from '{self._session_context}'. Instruction: {clean_text}"
        else:
            full_prompt = clean_text

        self._session_context = clean_text

        # Add language reply instruction if non-English
        full_prompt = full_prompt + reply_instruction(self._lang)
        await self._execute_agent_prompt(full_prompt, request=req)
        return True

    async def _execute_agent_prompt(self, prompt: str, request: Optional[HarmaRequest] = None) -> str:
        """Execute agent on prompt and speak verified response."""
        self._emit(VoiceEvent.AGENT_STARTED)
        self.voice_state.try_transition(VoiceState.EXECUTING)
        t_start = time.time()
        try:
            req_id = request.request_id if request else None
            # Store active run task for cancellation support (§6, §30)
            try:
                coro = self._agent.run(prompt, request_id=req_id)
            except TypeError:
                coro = self._agent.run(prompt)
            self._active_run_task = asyncio.create_task(coro)
            response = await self._active_run_task
            agent_ms = (time.time() - t_start) * 1000
            self._emit(VoiceEvent.AGENT_COMPLETED)

            # Generate verified, concise voice response (§28, §29)
            spoken = self._format_voice_response(response)
            if spoken:
                await self.speak(spoken)
            log.info("[VOICE] Pipeline agent=%.0fms", agent_ms)
            return response
        except asyncio.CancelledError:
            log.info("[VOICE] Agent execution cancelled.")
            self.voice_state.try_transition(VoiceState.INTERRUPTED)
            return ""
        except KeyboardInterrupt:
            log.info("[VOICE] Agent interrupted by user.")
            self.voice_state.try_transition(VoiceState.INTERRUPTED)
            return ""
        except Exception as exc:
            log.error("[VOICE] Agent error: %s", exc)
            self.voice_state.try_transition(VoiceState.ERROR)
            await self.speak(self._lang.say("error"))
            return ""
        finally:
            self._active_run_task = None

    async def handle_command(self, command: VoiceCommand) -> None:
        """
        Pass a transcribed command to the existing HarmaAgent.
        Then speak the response.

        This is the key integration point: Voice → Agent.
        The existing permission system, memory, and tools are fully reused.
        """
        await self._process_voice_command(command)

    async def speak(self, text: str) -> None:
        """
        Speak text via TTS.

        Handles:
            - Empty text (no-op)
            - TTS errors (log + continue)
            - State machine transition PROCESSING/IDLE → SPEAKING → IDLE
        """
        if not text or not text.strip():
            return

        # Transition to SPEAKING if possible
        if not self._state.is_in(AudioState.SPEAKING):
            self._state.try_transition(AudioState.SPEAKING)
        self.voice_state.try_transition(VoiceState.SPEAKING)

        self._emit(VoiceEvent.TTS_STARTED)
        t_start = time.time()

        try:
            await self._tts.synthesize(text)
            self._emit(VoiceEvent.TTS_COMPLETED)
        except TTSError as exc:
            self._emit(VoiceEvent.TTS_FAILED)
            log.error("[TTS] Synthesis failed: %s", exc)
        finally:
            tts_ms = (time.time() - t_start) * 1000
            log.info("[TTS] Finished  latency=%.0fms", tts_ms)
            if self._state.is_in(AudioState.SPEAKING):
                self._state.try_transition(AudioState.IDLE)

    def interrupt_speech(self) -> None:
        """
        Immediately stop current TTS speech (barge-in).
        Transitions: SPEAKING → INTERRUPTED.
        """
        self._tts.stop()
        if self._state.is_in(AudioState.SPEAKING):
            self._state.try_transition(AudioState.INTERRUPTED)
        self.voice_state.try_transition(VoiceState.INTERRUPTED)
        self._emit(VoiceEvent.TTS_INTERRUPTED)
        log.info("[VOICE] Speech interrupted by user.")

    # ── Voice confirmation (for permission system) ─────────────────────────────

    async def voice_confirm(self, prompt: str) -> str:
        """
        Speak a confirmation prompt and listen for yes/no.
        Used as the confirm_callback for HarmaAgent when in voice mode.

        Returns: "yes" or "no"
        """
        return await self._conversation.get_voice_confirmation(prompt)

    def make_confirm_callback(self):
        """
        Returns a sync callback compatible with Executor's confirm_callback signature.
        Uses asyncio.run_coroutine_threadsafe for thread-safe async bridging.
        """
        loop = asyncio.get_event_loop()

        def _callback(prompt: str) -> str:
            future = asyncio.run_coroutine_threadsafe(
                self.voice_confirm(prompt), loop
            )
            try:
                return future.result(timeout=30.0)
            except Exception:
                return "no"

        return _callback

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def state(self) -> AudioState:
        return self._state.state

    def status(self) -> str:
        return (
            f"VoiceManager  state={self._state.state.value}  "
            f"voice_state={self.voice_state.state.value}  "
            f"STT={self._stt.name}  TTS={self._tts.name}  "
            f"speaking={self._tts.is_speaking}"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_state_change(self, old: AudioState, new: AudioState) -> None:
        """Log every state transition as a structured event."""
        log.info("[VOICE] %s → %s", old.value.upper(), new.value.upper())

    def _emit(self, event: VoiceEvent) -> None:
        log.debug("[VOICE] Event: %s", event.value)
