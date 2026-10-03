"""
Harma CLI Interface — Phase 1

A beautiful terminal interface for interacting with Harma.
Uses ANSI colours and a clean format so conversations feel natural.

This is the primary user-facing entry point for Phase 1.
Voice interface will be added in Phase 4.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

from harma.config.logging_config import get_logger
from harma.config.settings import config

log = get_logger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Harma's brand — a warm indigo/violet
HARMA_COLOUR = "\033[38;5;135m"    # violet
USER_COLOUR = "\033[38;5;75m"      # sky blue
ERROR_COLOUR = "\033[38;5;196m"    # red
SUCCESS_COLOUR = "\033[38;5;82m"   # green
THINKING_COLOUR = "\033[38;5;244m" # grey

HARMA_NAME = config.agent.name


def _print_banner() -> None:
    """Print Harma startup banner."""
    banner = f"""
{HARMA_COLOUR}{BOLD}
  ██╗  ██╗ █████╗ ██████╗ ███╗   ███╗ █████╗
  ██║  ██║██╔══██╗██╔══██╗████╗ ████║██╔══██╗
  ███████║███████║██████╔╝██╔████╔██║███████║
  ██╔══██║██╔══██║██╔══██╗██║╚██╔╝██║██╔══██║
  ██║  ██║██║  ██║██║  ██║██║ ╚═╝ ██║██║  ██║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝
{RESET}
{DIM}  Personal AI Agent — Phase 1{RESET}
{DIM}  Type your message. Say 'quit' or 'exit' to stop.{RESET}
{DIM}  Commands: !status  !reset  !tools  !help{RESET}
"""
    print(banner)


def _harma_says(message: str) -> None:
    print(f"\n{HARMA_COLOUR}{BOLD}Harma{RESET}  {message}\n")


def _user_prompt() -> str:
    return input(f"{USER_COLOUR}{BOLD}You{RESET}  › ").strip()


def _thinking() -> None:
    print(f"{THINKING_COLOUR}  …thinking{RESET}", end="\r", flush=True)


def _clear_thinking() -> None:
    print(" " * 20, end="\r", flush=True)


async def run_cli(provider_name: Optional[str] = None) -> None:
    """
    Main CLI loop.

    Args:
        provider_name: Override the configured LLM provider.
    """
    # Lazy import to keep startup fast
    from harma.core.context import AgentContext
    from harma.core.agent import HarmaAgent
    from harma.llm.factory import get_provider

    _print_banner()

    # Build context
    try:
        provider = get_provider(provider_name)
        ctx = AgentContext(provider=provider)
    except Exception as exc:
        print(f"{ERROR_COLOUR}Failed to initialise Harma: {exc}{RESET}")
        print("\nMake sure your API key is set. See README.md for setup instructions.")
        sys.exit(1)

    model_name = getattr(provider, "model", getattr(config.llm, "model", ""))
    print(f"{DIM}  Harma LLM{RESET}")
    print(f"{DIM}  Provider : {provider.name}{RESET}")
    print(f"{DIM}  Model    : {model_name}{RESET}")
    print(f"{DIM}  Status   : Connected{RESET}\n")

    agent = HarmaAgent(ctx)
    _harma_says("Yes? How can I help?")

    while True:
        try:
            user_input = _user_prompt()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye.{RESET}\n")
            break

        if not user_input:
            continue

        # ── Built-in commands ─────────────────────────────────────────────────
        if user_input.lower() in ("quit", "exit", "bye", "q"):
            print(f"\n{DIM}Goodbye.{RESET}\n")
            break

        if user_input == "!status":
            print(f"\n{DIM}{agent.status()}{RESET}\n")
            continue

        if user_input == "!reset":
            agent.reset()
            _harma_says("Memory cleared. Fresh start.")
            continue

        if user_input == "!tools":
            print(f"\n{DIM}{ctx.registry.summary()}{RESET}\n")
            continue

        if user_input.startswith(("/plan", "/dry-run", "/observe", "/vision", "/context")):
            cmd_parts = user_input.split(maxsplit=1)
            cmd = cmd_parts[0].lower()
            arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

            if cmd == "/plan":
                if arg == "status":
                    _harma_says(agent.get_plan_status())
                elif arg == "cancel":
                    agent.cancel_plan()
                    _harma_says("Active plan cancelled.")
                elif arg == "pause":
                    agent.pause_plan()
                    _harma_says("Active plan paused.")
                elif arg == "resume":
                    agent.resume_plan()
                    _harma_says("Active plan resumed.")
                elif arg:
                    _thinking()
                    resp = await agent.run_plan(arg, dry_run=False)
                    _clear_thinking()
                    _harma_says(resp)
                else:
                    _harma_says("Usage: /plan <goal> | /plan status | /plan pause | /plan resume | /plan cancel")
                continue

            elif cmd == "/dry-run":
                if arg:
                    _thinking()
                    resp = await agent.run_plan(arg, dry_run=True)
                    _clear_thinking()
                    _harma_says(resp)
                else:
                    _harma_says("Usage: /dry-run <goal>")
                continue

            elif cmd in ("/observe", "/vision"):
                _thinking()
                obs = await ctx.screen_perception.perceive_screen(query=arg)
                _clear_thinking()
                _harma_says(f"[Observation]: {obs.content}")
                continue

            elif cmd == "/context":
                _thinking()
                try:
                    from harma.intelligence.context_models import UnifiedContext
                    u_ctx = UnifiedContext(user_request="Active context inspection")
                    fused = ctx.context_fusion.build_unified_prompt(u_ctx)
                    _clear_thinking()
                    _harma_says(f"[Active Unified Context]:\n{fused}")
                except Exception as c_exc:
                    _clear_thinking()
                    _harma_says(f"Context inspection error: {c_exc}")
                continue

        if user_input == "!help":
            print(f"""
{DIM}Commands:
  !status       Show agent status and memory summary
  !reset        Clear conversation memory
  !tools        List available tools
  !help         Show this help

  /plan <goal>  Create and execute structured plan
  /plan status  Inspect active plan progress
  /plan pause   Pause running plan
  /plan resume  Resume paused plan
  /plan cancel  Cancel running plan
  /dry-run <g>  Simulate execution plan without side effects
  /observe      Perceive screen with multimodal vision
  /context      Show active fused context

  quit / exit   Exit Harma{RESET}
""")
            continue

        # ── Run agent ─────────────────────────────────────────────────────────
        _thinking()
        try:
            response = await agent.run(user_input)
            _clear_thinking()
            _harma_says(response)
        except KeyboardInterrupt:
            _clear_thinking()
            print(f"\n{DIM}(Interrupted){RESET}\n")
        except Exception as exc:
            _clear_thinking()
            log.exception("Unexpected error in agent loop: %s", exc)
            _harma_says(
                f"Something went wrong internally: {exc}\n"
                f"Please check the logs for details."
            )
