"""
Harma Voice CLI — Phase 4

Voice-mode terminal interface.

Modes:
  1. Push-to-talk (default, wake_word.enabled: false):
     Press ENTER → speak → Harma responds

  2. Wake-word mode (wake_word.enabled: true):
     Say "Hey Harma" → speak → Harma responds

Usage:
  python main.py --voice                  # push-to-talk
  python main.py --voice --wake-word      # wake-word mode
  python main.py --voice --no-tts         # text-mode (voice input, text output)
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config

log = get_logger(__name__)

# ── Colours ───────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
VIOLET  = "\033[38;5;135m"
BLUE    = "\033[38;5;75m"
GREEN   = "\033[38;5;82m"
RED     = "\033[38;5;196m"
GREY    = "\033[38;5;244m"
YELLOW  = "\033[38;5;226m"


def _print_voice_banner(wake_word_mode: bool, lang_name: str = "English") -> None:
    mode = "Always-On Wake Word (Siri-style)" if wake_word_mode else "Push-to-Talk"
    print(f"""
{VIOLET}{BOLD}  ╭──────────────────────────────────────────────────────────╮
  │                   HARMA VOICE ASSISTANT                  │
  │            Personal Autonomous AI Voice Control          │
  ╰──────────────────────────────────────────────────────────╯{RESET}

{DIM}  Mode:        {mode}{RESET}
{DIM}  Language:    {lang_name} (Voice switch: "switch to Tamil" / "switch to Telugu"){RESET}
{DIM}  Speech STT:  Google Web Speech API{RESET}
{DIM}  Neural TTS:  Microsoft Edge Neural Voices (free, lifelike){RESET}
{DIM}  Follow-Up:   Active (~8s conversational window after each reply){RESET}
""")

    if wake_word_mode:
        print(f"{GREEN}{BOLD}  ▶ Just say \"{config.voice.wake_word_phrase.upper()}\" anytime to give an action.{RESET}")
        print(f"{GREY}  Voice commands: \"switch to Tamil\", \"clear memory\", \"stop\", \"exit voice mode\"{RESET}\n")
    else:
        print(f"{GREY}  Press {BOLD}ENTER{RESET}{GREY} to speak. Say {BOLD}'exit'{RESET}{GREY} to quit.{RESET}\n")


def _status_line(text: str) -> None:
    print(f"{GREY}  ▶ {text}{RESET}", flush=True)


def _user_heard(text: str) -> None:
    print(f"\n{BLUE}{BOLD}You{RESET}  {text}")


def _harma_says(text: str) -> None:
    print(f"{VIOLET}{BOLD}Harma{RESET}  {text}\n")


def _thinking() -> None:
    print(f"{GREY}  …thinking{RESET}", end="\r", flush=True)


def _clear_line() -> None:
    print(" " * 30, end="\r", flush=True)


async def run_voice_cli(
    provider_name: Optional[str] = None,
    wake_word_mode: bool = False,
    no_tts: bool = False,
    lang: Optional[str] = None,
) -> None:
    """
    Main voice CLI loop.

    Args:
        provider_name: LLM provider override.
        wake_word_mode: If True, use wake-word detection instead of push-to-talk.
        no_tts: If True, skip TTS and print response instead.
        lang: Initial language code or name (e.g. 'en', 'ta', 'te').
    """
    from harma.core.agent import HarmaAgent
    from harma.core.context import AgentContext
    from harma.llm.factory import get_provider
    from harma.voice.manager import VoiceManager
    from harma.voice.tts import SilentTTSProvider, get_tts_provider
    from harma.voice.language import resolve_language

    active_lang = resolve_language(lang or config.voice.stt_language)
    _print_voice_banner(wake_word_mode, f"{active_lang.name} ({active_lang.native_name})")

    # ── Build agent (same as text mode — no second agent) ────────────────────
    try:
        provider = get_provider(provider_name)
        ctx = AgentContext(provider=provider)
    except Exception as exc:
        print(f"{RED}Failed to initialise Harma: {exc}{RESET}")
        sys.exit(1)

    # ── TTS provider ─────────────────────────────────────────────────────────
    if no_tts:
        tts = SilentTTSProvider()
    else:
        tts = get_tts_provider(
            provider_name=config.voice.tts_provider,
            rate=config.voice.tts_rate,
            volume=config.voice.tts_volume,
            voice_id=config.voice.tts_voice_id or active_lang.voice_female,
        )

    # ── Build voice manager, inject confirm_callback for permissions ──────────
    agent = HarmaAgent(ctx)
    vm = VoiceManager(agent=agent, tts=tts)
    if lang:
        vm.set_language(lang)

    # Override agent's confirm callback to use voice
    agent._executor._confirm = vm.make_confirm_callback()

    # ── Start microphone ──────────────────────────────────────────────────────
    try:
        _status_line("Starting microphone…")
        await vm.start()
        _status_line("Microphone ready.")
    except Exception as exc:
        print(f"{RED}Microphone error: {exc}{RESET}")
        print(f"{DIM}Check microphone permissions and try again.{RESET}")
        sys.exit(1)

    # ── Main loop ─────────────────────────────────────────────────────────────
    if wake_word_mode:
        _status_line(f'Listening for "{config.voice.wake_word_phrase}"…')
        try:
            # Announce readiness
            if not no_tts:
                await vm.speak(vm.language.say("ready"))
            await vm.run_wake_word_loop()
        except KeyboardInterrupt:
            pass
    else:
        await _push_to_talk_loop(vm, no_tts)

    await vm.stop()
    print(f"\n{DIM}Voice session ended. Goodbye.{RESET}\n")


async def _push_to_talk_loop(vm, no_tts: bool) -> None:
    """Push-to-talk loop: press ENTER to speak."""
    from harma.voice.tts import filter_for_tts

    print(f"{GREEN}Ready.{RESET}  Press {BOLD}ENTER{RESET} to speak, or type {BOLD}quit{RESET} to exit.\n")

    loop = asyncio.get_event_loop()

    while True:
        # Wait for ENTER in a thread (non-blocking for asyncio)
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: input(f"{YELLOW}[Press ENTER to speak, or type a command]{RESET}  "),
            )
        except (EOFError, KeyboardInterrupt):
            break

        cmd = raw.strip().lower()

        # ── Text passthrough (type instead of speak) ──────────────────────────
        if cmd in ("quit", "exit", "bye", "q"):
            break

        if cmd in ("!status", "status"):
            print(f"\n{DIM}{vm.status()}{RESET}\n")
            continue

        if cmd in ("!reset", "reset"):
            vm._agent.reset()
            print(f"{DIM}Memory cleared.{RESET}\n")
            continue

        if cmd in ("!devices", "devices"):
            from harma.voice.microphone import list_audio_devices
            for dev in list_audio_devices():
                print(f"{DIM}  {dev.describe()}{RESET}")
            print()
            continue

        # ── If user typed a non-empty string, use it as text command ──────────
        if cmd and not cmd.startswith("!"):
            _thinking()
            from harma.core.agent import HarmaAgent
            response = await vm._agent.run(cmd)
            _clear_line()
            _harma_says(response)
            if not no_tts:
                spoken = filter_for_tts(response)
                if spoken:
                    await vm.speak(spoken)
            continue

        # ── Voice capture ─────────────────────────────────────────────────────
        _status_line("Listening… speak now.")
        command = await vm.listen_once(timeout=config.voice.listen_timeout)

        if command is None:
            _status_line("No speech detected. Press ENTER to try again.")
            continue

        _user_heard(command.raw or command.transcript)

        # Exit command?
        if command.is_exit_command():
            await vm.speak("Goodbye!")
            break

        # Process through existing agent
        _thinking()
        _clear_line()
        _status_line("Thinking…")

        from harma.voice.tts import filter_for_tts
        try:
            response = await vm._agent.run(command.transcript)
            _clear_line()
            _harma_says(response)
            if not no_tts:
                spoken = filter_for_tts(response)
                if spoken:
                    await vm.speak(spoken)
        except KeyboardInterrupt:
            _clear_line()
            _status_line("(Interrupted)")
        except Exception as exc:
            _clear_line()
            _harma_says(f"Something went wrong: {exc}")

        print()
