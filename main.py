"""
Harma — Entry Point

Usage:
  python main.py                      # text mode (configured provider)
  python main.py --provider gemini    # override LLM provider
  python main.py --voice              # voice push-to-talk mode
  python main.py --voice --wake-word  # voice with wake-word detection
  python main.py --voice --no-tts     # voice input, text output
  python main.py --version
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harma",
        description="Harma — Personal AI Agent",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider: openai | gemini | groq | claude (default: from config)",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        default=False,
        help="Enable voice mode (push-to-talk)",
    )
    parser.add_argument(
        "--wake-word",
        action="store_true",
        default=False,
        dest="wake_word",
        help="Use wake-word detection instead of push-to-talk (requires --voice)",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        default=False,
        dest="no_tts",
        help="Voice input only — print responses instead of speaking them",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Spoken language: en (English) | ta (Tamil) | te (Telugu)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Harma 1.0.0 - Phase 10 (Control Center, Unified UI & Human-Agent Interaction)",
    )

    subparsers = parser.add_subparsers(dest="command")

    # voice subcommand: python main.py voice [--wake-word] [--push-to-talk] [--lang LANG] [--no-tts]
    voice_parser = subparsers.add_parser("voice", help="Launch Harma Siri-style voice assistant")
    voice_parser.add_argument("--push-to-talk", action="store_true", default=False, help="Use push-to-talk instead of always-on wake word")
    voice_parser.add_argument("--wake-word", action="store_true", default=True, help="Always-on wake word mode (default)")
    voice_parser.add_argument("--lang", type=str, default=None, help="Spoken language: en | ta | te")
    voice_parser.add_argument("--no-tts", action="store_true", default=False, help="Voice input only (no audio speech)")

    # ui subcommand: python main.py ui [--host HOST] [--port PORT] [--open-browser]
    ui_parser = subparsers.add_parser("ui", help="Launch Harma Control Center web interface")
    ui_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    ui_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    ui_parser.add_argument("--open-browser", action="store_true", default=False, help="Open default browser")

    serve_parser = subparsers.add_parser("serve", help="Start Harma API & Control Center server")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    serve_parser.add_argument("--open-browser", action="store_true", default=False, help="Open default browser")

    # plan subcommand: python main.py plan [run|status|dry-run]
    plan_parser = subparsers.add_parser("plan", help="Structured planning and execution")
    plan_sub = plan_parser.add_subparsers(dest="plan_action")

    p_run = plan_sub.add_parser("run", help="Create and execute a structured plan")
    p_run.add_argument("goal", type=str, help="Goal to plan and execute")

    p_dry = plan_sub.add_parser("dry-run", help="Simulate a structured plan without side effects")
    p_dry.add_argument("goal", type=str, help="Goal to simulate")

    plan_sub.add_parser("status", help="Show active plan execution progress")

    # observe subcommand: python main.py observe [screen|document]
    obs_parser = subparsers.add_parser("observe", help="Multimodal screen and document perception")
    obs_sub = obs_parser.add_subparsers(dest="observe_action")

    o_screen = obs_sub.add_parser("screen", help="Inspect screen using multimodal vision")
    o_screen.add_argument("--query", type=str, default="", help="Optional query / target element")

    o_doc = obs_sub.add_parser("document", help="Parse and summarize a local document")
    o_doc.add_argument("file", type=str, help="File path to document")
    o_doc.add_argument("--query", type=str, default="", help="Optional query within document")

    # integrations subcommand: python main.py integrations [list|status|tools|connect|disconnect|enable|disable]
    integ_parser = subparsers.add_parser("integrations", help="Inspect and manage external MCP service integrations")
    integ_sub = integ_parser.add_subparsers(dest="integrations_action")

    integ_sub.add_parser("list", help="List configured and connected external integrations")

    i_stat = integ_sub.add_parser("status", help="Show integration health status")
    i_stat.add_argument("name", type=str, help="Integration name (e.g. github, calendar)")

    i_tools = integ_sub.add_parser("tools", help="List registered tools from integrations")
    i_tools.add_argument("--server", type=str, default=None, help="Optional server name filter")

    i_conn = integ_sub.add_parser("connect", help="Connect an integration server")
    i_conn.add_argument("name", type=str, help="Integration name to connect")

    i_disc = integ_sub.add_parser("disconnect", help="Disconnect an integration server")
    i_disc.add_argument("name", type=str, help="Integration name to disconnect")

    i_enab = integ_sub.add_parser("enable", help="Enable an integration server")
    i_enab.add_argument("name", type=str, help="Integration name to enable")

    i_disa = integ_sub.add_parser("disable", help="Disable an integration server")
    i_disa.add_argument("name", type=str, help="Integration name to disable")

    # tasks subcommand: python main.py tasks [list|status|history|run|pause|resume|cancel|stop-all]
    tasks_parser = subparsers.add_parser("tasks", help="Inspect and manage proactive background tasks")
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_action")

    t_list = tasks_sub.add_parser("list", help="List scheduled and active tasks")
    t_list.add_argument("--status", type=str, default=None, help="Filter by status (scheduled, running, paused, etc.)")

    tasks_sub.add_parser("status", help="Show task subsystem dashboard statistics")

    t_hist = tasks_sub.add_parser("history", help="Show task execution audit history")
    t_hist.add_argument("--task-id", type=str, default=None, help="Optional task ID")
    t_hist.add_argument("--limit", type=int, default=20, help="Max entries")

    t_run = tasks_sub.add_parser("run", help="Run a scheduled task immediately")
    t_run.add_argument("task_id", type=str, help="ID of task to run")

    t_pause = tasks_sub.add_parser("pause", help="Pause a scheduled task")
    t_pause.add_argument("task_id", type=str, help="ID of task to pause")

    t_resume = tasks_sub.add_parser("resume", help="Resume a paused task")
    t_resume.add_argument("task_id", type=str, help="ID of task to resume")

    t_cancel = tasks_sub.add_parser("cancel", help="Cancel a scheduled task")
    t_cancel.add_argument("task_id", type=str, help="ID of task to cancel")

    tasks_sub.add_parser("stop-all", help="Emergency stop: pause all scheduled tasks immediately")

    # android subcommand: python main.py android [devices|status|screenshot|apps]
    android_parser = subparsers.add_parser("android", help="Android device diagnostics and control")
    android_sub = android_parser.add_subparsers(dest="android_action")

    android_sub.add_parser("devices", help="List connected Android devices")

    status_p = android_sub.add_parser("status", help="Show Android device status")
    status_p.add_argument("--device", type=str, default=None, help="Device ID")

    shot_p = android_sub.add_parser("screenshot", help="Capture and observe Android screen")
    shot_p.add_argument("--device", type=str, default=None, help="Device ID")

    apps_p = android_sub.add_parser("apps", help="List installed apps on Android device")
    apps_p.add_argument("--device", type=str, default=None, help="Device ID")

    # memory subcommand: python main.py memory [list|search|stats]
    mem_parser = subparsers.add_parser("memory", help="Inspect and manage long-term memory")
    mem_sub = mem_parser.add_subparsers(dest="memory_action")

    list_p = mem_sub.add_parser("list", help="List recent active memories")
    list_p.add_argument("--limit", type=int, default=20, help="Max memories to show")

    search_p = mem_sub.add_parser("search", help="Search memories by keyword")
    search_p.add_argument("query", type=str, help="Search query")
    search_p.add_argument("--limit", type=int, default=10, help="Max results")

    stats_p = mem_sub.add_parser("stats", help="Show memory storage statistics")

    args = parser.parse_args()

    try:
        if args.command in ("ui", "serve"):
            import socket
            import uvicorn
            from harma.api.server import create_app
            import webbrowser

            port = args.port
            # Check if port is in use; if so, find next available port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind((args.host, port))
                except OSError:
                    for p in range(port + 1, port + 50):
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_s:
                            try:
                                test_s.bind((args.host, p))
                                port = p
                                break
                            except OSError:
                                continue

            print(f"\n==========================================")
            print(f"  HARMA CONTROL CENTER (Phase 10)")
            print(f"  Single AI Brain - Unified Operating UI")
            print(f"  Server URL: http://{args.host}:{port}")
            print(f"==========================================\n")
            if getattr(args, "open_browser", False):
                webbrowser.open(f"http://{args.host}:{port}")
            app = create_app()
            uvicorn.run(app, host=args.host, port=port, log_level="info")
            return

        if args.command == "plan":
            from harma.core.context import AgentContext
            from harma.core.agent import HarmaAgent

            ctx = AgentContext()
            agent = HarmaAgent(ctx)

            if args.plan_action == "run":
                res = asyncio.run(agent.run_plan(args.goal, dry_run=False))
                print(f"\n{res}\n")
            elif args.plan_action == "dry-run":
                res = asyncio.run(agent.run_plan(args.goal, dry_run=True))
                print(f"\n{res}\n")
            elif args.plan_action == "status":
                print(f"\n{agent.get_plan_status()}\n")
            else:
                plan_parser.print_help()
            return

        if args.command == "observe":
            from harma.core.context import AgentContext
            ctx = AgentContext()

            if args.observe_action == "screen":
                obs = asyncio.run(ctx.screen_perception.perceive_screen(query=args.query))
                print(f"\n--- Multimodal Screen Observation ---")
                print(f"Active App:  {obs.active_app}")
                print(f"Window:      {obs.window_title}")
                print(f"Confidence:  {obs.confidence.value}")
                print(f"Summary:     {obs.content}")
                print()
            elif args.observe_action == "document":
                if args.query:
                    ans = ctx.document_parser.query_document(args.file, args.query)
                    print(f"\n--- Document Query Result ---\n{ans}\n")
                else:
                    obs = ctx.document_parser.parse_document(args.file)
                    print(f"\n--- Document Summary ({obs.file_type}) ---")
                    print(f"Summary:     {obs.summary}")
                    print(f"Pages/Chunks:{obs.page_count}")
                    print(f"Entities:    {obs.entities}")
                    print()
            else:
                obs_parser.print_help()
            return

        if args.command == "tasks":
            from harma.tasks.manager import get_task_manager
            from harma.tasks.models import TaskStatus
            mgr = get_task_manager()

            if args.tasks_action == "list":
                st = TaskStatus(args.status) if args.status else None
                tasks = mgr.list_tasks(status=st)
                if not tasks:
                    print("No tasks found.")
                    return
                print(f"\n--- Harma Tasks ({len(tasks)}) ---")
                for t in tasks:
                    print(f"[{t.id[:10]}] {t.name:<25} ({t.status.value:<9}) | trigger={t.trigger.trigger_type.value:<9} | next={str(t.next_run_at)[:19]}")
                    print(f"            objective: {t.objective[:80]}")
                print()

            elif args.tasks_action == "status":
                st = mgr.stats()
                print("\n--- Task Subsystem Status ---")
                print(f"Total Tasks:     {st['total']}")
                print(f"By Status:       {st['by_status']}")
                print(f"Next Run Epoch:  {st['next_execution']}")
                print()

            elif args.tasks_action == "history":
                hist = mgr.get_history(task_id=args.task_id, limit=args.limit)
                if not hist:
                    print("No execution history recorded.")
                    return
                print(f"\n--- Task Execution Audit History ({len(hist)}) ---")
                for h in hist:
                    print(f"[{h.execution_id[:8]}] task={h.task_id[:10]} status={h.status:<8} steps={h.steps_taken:<2} tools={h.tools_used}")
                    if h.summary:
                        print(f"          summary: {h.summary[:80]}")
                    if h.error:
                        print(f"          error:   {h.error}")
                print()

            elif args.tasks_action == "run":
                async def _run_now():
                    print(f"Executing task '{args.task_id}' now...")
                    h = await mgr.run_task_now(args.task_id)
                    print(f"Finished with status: {h.status}")
                    if h.summary:
                        print(f"Result: {h.summary}")
                    if h.error:
                        print(f"Error: {h.error}")
                asyncio.run(_run_now())

            elif args.tasks_action == "pause":
                t = mgr.pause_task(args.task_id)
                print(f"Task '{t.name}' ({t.id}) paused.")

            elif args.tasks_action == "resume":
                t = mgr.resume_task(args.task_id)
                print(f"Task '{t.name}' ({t.id}) resumed.")

            elif args.tasks_action == "cancel":
                t = mgr.cancel_task(args.task_id)
                print(f"Task '{t.name}' ({t.id}) cancelled.")

            elif args.tasks_action == "stop-all":
                async def _stop_all():
                    count = await mgr.stop_all()
                    print(f"Emergency stop: paused {count} active scheduled tasks.")
                asyncio.run(_stop_all())

            else:
                tasks_parser.print_help()
            return

        if args.command == "integrations":
            from harma.integrations.manager import get_integration_manager
            mgr = get_integration_manager()

            async def _run_integ_cli() -> None:
                if args.integrations_action == "list":
                    servers = mgr.list_servers()
                    if not servers:
                        print("No external integrations configured or connected.")
                        return
                    print(f"\n--- Connected & Configured Integrations ({len(servers)}) ---")
                    for s in servers:
                        print(f"[{s.server_name}] status={s.status.upper()} | circuit={s.circuit_status.upper()} | tools={s.tool_count}")
                    print()

                elif args.integrations_action == "status":
                    h = mgr.get_status(args.name)
                    if not h:
                        print(f"Integration '{args.name}' not found.")
                        return
                    print(f"\n--- Integration Health: {h.server_name} ---")
                    print(f"Status:             {h.status.upper()}")
                    print(f"Circuit Breaker:    {h.circuit_status.upper()}")
                    print(f"Available Tools:    {h.tool_count}")
                    print(f"Total Invocations:  {h.total_calls} (Failed: {h.failed_calls})")
                    if h.error_message:
                        print(f"Last Error:         {h.error_message}")
                    print()

                elif args.integrations_action == "tools":
                    tools = mgr.list_tools(server_name=args.server)
                    if not tools:
                        print("No integration tools found.")
                        return
                    print(f"\n--- Available Integration Tools ({len(tools)}) ---")
                    for t in tools:
                        print(f"- {t.name:30} [{t.capability.value.upper()}, {t.permission_level.value}]: {t.description}")
                    print()

                elif args.integrations_action == "connect":
                    ok = await mgr.connect_server(args.name)
                    if ok:
                        h = mgr.get_status(args.name)
                        print(f"Connected to '{args.name}' ({h.tool_count if h else 0} tools mounted).")
                    else:
                        print(f"Failed to connect to integration '{args.name}'.")

                elif args.integrations_action == "disconnect":
                    ok = await mgr.disconnect_server(args.name)
                    if ok:
                        print(f"Disconnected integration '{args.name}'.")
                    else:
                        print(f"Failed to disconnect integration '{args.name}'.")

                elif args.integrations_action == "enable":
                    ok = await mgr.enable_server(args.name)
                    print(f"Integration '{args.name}' enabled.")

                elif args.integrations_action == "disable":
                    ok = await mgr.disable_server(args.name)
                    print(f"Integration '{args.name}' disabled and disconnected.")

                else:
                    integ_parser.print_help()

            asyncio.run(_run_integ_cli())
            return

        if args.command == "android":
            from harma.android.manager import get_android_manager
            mgr = get_android_manager()

            async def _run_android_cli() -> None:
                if args.android_action == "devices":
                    devs = await mgr.list_devices()
                    if not devs:
                        print("No connected Android devices detected.")
                        return
                    print(f"\n--- Connected Android Devices ({len(devs)}) ---")
                    for d in devs:
                        print(f"[{d.device_id}] {d.manufacturer} {d.model} | state={d.state.value} | emulator={d.is_emulator}")
                    print()
                elif args.android_action == "status":
                    st = await mgr.get_status(device_id=args.device)
                    d = st.to_dict()
                    print("\n--- Android Device Status ---")
                    for k, v in d.items():
                        print(f"{k:20}: {v}")
                    print()
                elif args.android_action == "screenshot":
                    obs = await mgr.screenshot(device_id=args.device)
                    print("\n--- Android Screen Observation ---")
                    print(f"App: {obs.current_package}")
                    print(f"Locked: {obs.is_locked}")
                    print(f"Elements: {len(obs.elements)}\n")
                    print(obs.summary)
                    print()
                elif args.android_action == "apps":
                    apps = await mgr.list_apps(device_id=args.device)
                    print(f"\n--- Installed Applications ({len(apps)}) ---")
                    for a in apps:
                        print(f"- {a.name:25} ({a.package})")
                    print()
                else:
                    android_parser.print_help()

            asyncio.run(_run_android_cli())
            return

        if args.command == "memory":
            from harma.memory.manager import get_memory_manager
            mgr = get_memory_manager()
            if not mgr.is_available:
                print("Long-term memory is currently disabled or unavailable.")
                return

            if args.memory_action == "list":
                memories = mgr.list_memories(limit=args.limit)
                if not memories:
                    print("No memories stored yet.")
                    return
                print(f"\n--- Stored Memories ({len(memories)}) ---")
                for m in memories:
                    print(f"[{m.id[:8]}] ({m.memory_type.value}) {m.content}")
                    print(f"       importance={m.importance}  confidence={m.confidence}  created={str(m.created_at)[:19]}")
                print()

            elif args.memory_action == "search":
                results = mgr.search(args.query, top_k=args.limit)
                if not results:
                    print(f"No memories matched query: {args.query!r}")
                    return
                print(f"\n--- Search Results for {args.query!r} ({len(results)}) ---")
                for m in results:
                    print(f"[{m.id[:8]}] ({m.memory_type.value}) {m.content}")
                print()

            elif args.memory_action == "stats":
                st = mgr.stats()
                print("\n--- Memory Statistics ---")
                print(f"Total:      {st.get('total', 0)}")
                print(f"Active:     {st.get('active', 0)}")
                print(f"Superseded: {st.get('superseded', 0)}")
                print(f"Deleted:    {st.get('deleted', 0)}")
                print(f"By type:    {st.get('by_type', {})}")
                print()
            else:
                mem_parser.print_help()
            return

        if args.command == "voice" or args.voice:
            is_push = getattr(args, "push_to_talk", False)
            wake_mode = not is_push if args.command == "voice" else args.wake_word
            from harma.ui.voice_cli import run_voice_cli
            asyncio.run(
                run_voice_cli(
                    provider_name=args.provider,
                    wake_word_mode=wake_mode,
                    no_tts=args.no_tts,
                    lang=getattr(args, "lang", None),
                )
            )
            return
        else:
            from harma.ui.cli import run_cli
            asyncio.run(run_cli(provider_name=args.provider))
    except KeyboardInterrupt:
        print("\nGoodbye.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
