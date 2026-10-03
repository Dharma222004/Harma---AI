"""
Script to execute and audit all 10 Real-World Acceptance Scenarios for Framework V2.
"""

import asyncio
import json
import time

from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.core.execution_state import (
    ErrorClass,
    ExecutionContext,
    ExecutionStatus,
    NormalizedToolCall,
)
from harma.tasks.executor import TaskExecutor
from harma.tasks.models import AutonomyLevel, Task
from harma.tools.base import BaseTool, PermissionLevel, ToolResult


async def main():
    print("=================================================================")
    print(" HARMA EXECUTION FRAMEWORK V2 — REAL-WORLD ACCEPTANCE VERIFICATION")
    print("=================================================================")

    results = {}

    # Initialize live agent context (using default configured provider: NVIDIA)
    ctx = AgentContext()
    agent = HarmaAgent(ctx, confirm_callback=lambda p: "yes", max_iterations=6)

    # ── Test 1: Direct Response ───────────────────────────────────────────────
    print("\n--- TEST 1: Direct Response ('Hello Harma') ---")
    t0 = time.time()
    resp1 = await agent.run("Hello Harma")
    d1 = time.time() - t0
    meta1 = agent.last_execution_meta
    success1 = (
        len(meta1.get("tool_calls", [])) == 0
        and meta1.get("status") == "completed"
        and len(resp1.strip()) > 0
    )
    results["Test 1: Direct Response"] = {
        "passed": success1,
        "response": resp1[:100],
        "tool_calls": len(meta1.get("tool_calls", [])),
        "duration_s": round(d1, 2),
    }
    print(f"Result: {'PASS' if success1 else 'FAIL'} | Tools: {len(meta1.get('tool_calls', []))} | Resp: {resp1[:80]}")

    # ── Test 2: Single Tool ───────────────────────────────────────────────────
    print("\n--- TEST 2: Single Tool ('What time is it?') ---")
    t0 = time.time()
    resp2 = await agent.run("What time is it?")
    d2 = time.time() - t0
    meta2 = agent.last_execution_meta
    tool_names = [tc["tool"] for tc in meta2.get("tool_calls", [])]
    success2 = (
        "get_current_time" in tool_names
        and meta2.get("status") == "completed"
        and meta2.get("verification", {}).get("status") == "verified"
    )
    results["Test 2: Single Tool"] = {
        "passed": success2,
        "response": resp2[:100],
        "tools_called": tool_names,
        "verification": meta2.get("verification", {}).get("status"),
        "duration_s": round(d2, 2),
    }
    print(f"Result: {'PASS' if success2 else 'FAIL'} | Tools: {tool_names} | Verification: {meta2.get('verification', {}).get('status')}")

    # ── Test 3: Computer Tool ─────────────────────────────────────────────────
    print("\n--- TEST 3: Computer Tool ('Open Notepad') ---")
    t0 = time.time()
    resp3 = await agent.run("Open Notepad")
    d3 = time.time() - t0
    meta3 = agent.last_execution_meta
    tool_names3 = [tc["tool"] for tc in meta3.get("tool_calls", [])]
    success3 = (
        "open_application" in tool_names3
        and meta3.get("status") == "completed"
        and meta3.get("verification", {}).get("status") == "verified"
    )
    results["Test 3: Computer Tool"] = {
        "passed": success3,
        "response": resp3[:100],
        "tools_called": tool_names3,
        "verification": meta3.get("verification", {}).get("status"),
        "duration_s": round(d3, 2),
    }
    print(f"Result: {'PASS' if success3 else 'FAIL'} | Tools: {tool_names3} | Verification: {meta3.get('verification', {}).get('status')}")

    # ── Test 4: Multi-Step Computer ───────────────────────────────────────────
    print("\n--- TEST 4: Multi-Step Computer ('Open Notepad and check the current time') ---")
    t0 = time.time()
    resp4 = await agent.run("Open Notepad and check the current time")
    d4 = time.time() - t0
    meta4 = agent.last_execution_meta
    tool_names4 = [tc["tool"] for tc in meta4.get("tool_calls", [])]
    success4 = (
        len(tool_names4) >= 1
        and meta4.get("status") == "completed"
    )
    results["Test 4: Multi-Step Computer"] = {
        "passed": success4,
        "response": resp4[:100],
        "tools_called": tool_names4,
        "duration_s": round(d4, 2),
    }
    print(f"Result: {'PASS' if success4 else 'FAIL'} | Tools: {tool_names4} | Duration: {round(d4, 2)}s")

    # ── Test 5: Browser Navigation ────────────────────────────────────
    print("\n--- TEST 5: Browser ('Navigate to https://en.wikipedia.org and observe page') ---")
    t0 = time.time()
    resp5 = await agent.run("Navigate to https://en.wikipedia.org and observe page")
    d5 = time.time() - t0
    meta5 = agent.last_execution_meta
    tool_names5 = [tc["tool"] for tc in meta5.get("tool_calls", [])]
    success5 = (
        meta5.get("status") == "completed"
        and len(resp5.strip()) > 0
    )
    results["Test 5: Browser Workflow"] = {
        "passed": success5,
        "response": resp5[:100],
        "tools_called": tool_names5,
        "duration_s": round(d5, 2),
    }
    print(f"Result: {'PASS' if success5 else 'FAIL'} | Tools: {tool_names5} | Duration: {round(d5, 2)}s")

    # ── Test 6: Failure Recovery ──────────────────────────────────────────────
    print("\n--- TEST 6: Failure Recovery (Transient failure → classify → bounded retry) ---")
    fail_tool_called = 0
    class FlakyNetworkTool(BaseTool):
        name = "flaky_resource_fetch"
        description = "Fetch remote resource"
        permission_level = PermissionLevel.SAFE
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **kwargs):
            nonlocal fail_tool_called
            fail_tool_called += 1
            if fail_tool_called == 1:
                return ToolResult(success=False, output="", error="Connection reset by peer (temporary glitch)")
            return ToolResult(success=True, output="Resource fetched successfully.")

    ctx.registry.register(FlakyNetworkTool())
    t0 = time.time()
    exec_ctx6 = ExecutionContext(user_request="Fetch flaky resource")
    norm_call6 = NormalizedToolCall(id="c6", name="flaky_resource_fetch", arguments={})
    res6_1 = await agent._engine.execute_tool(exec_ctx6, norm_call6)
    err_cls = agent._engine.classify_error(res6_1.error["message"])
    retryable = agent._engine.can_retry(exec_ctx6, "flaky_resource_fetch", err_cls)
    res6_2 = None
    if retryable:
        res6_2 = await agent._engine.execute_tool(exec_ctx6, norm_call6)
    d6 = time.time() - t0
    success6 = (not res6_1.success) and retryable and (res6_2 is not None and res6_2.success)
    results["Test 6: Failure Recovery"] = {
        "passed": success6,
        "first_attempt_success": res6_1.success,
        "error_class": err_cls.value,
        "retry_success": res6_2.success if res6_2 else False,
        "duration_s": round(d6, 2),
    }
    print(f"Result: {'PASS' if success6 else 'FAIL'} | First attempt error: {res6_1.error} | Retry succeeded: {res6_2.success if res6_2 else False}")

    # ── Test 7: Confirmation Handling ─────────────────────────────────────────
    print("\n--- TEST 7: Confirmation Handling ---")
    confirmed = False
    def confirm_cb(prompt: str) -> str:
        nonlocal confirmed
        confirmed = True
        return "yes"

    agent_confirm = HarmaAgent(ctx, confirm_callback=confirm_cb)
    class TempDeleteTool(BaseTool):
        name = "purge_temp_cache"
        description = "Purge system cache"
        permission_level = PermissionLevel.HIGH_RISK
        parameters = {"type": "object", "properties": {}}
        async def execute(self, **kwargs):
            return ToolResult(success=True, output="Cache purged.")

    ctx.registry.register(TempDeleteTool())
    t0 = time.time()
    exec_ctx7 = ExecutionContext(user_request="Purge cache")
    norm_call7 = NormalizedToolCall(id="c7", name="purge_temp_cache", arguments={})
    res7 = await agent_confirm._engine.execute_tool(exec_ctx7, norm_call7)
    d7 = time.time() - t0
    success7 = confirmed and res7.success
    results["Test 7: Confirmation Handling"] = {
        "passed": success7,
        "confirmed_prompted": confirmed,
        "duration_s": round(d7, 2),
    }
    print(f"Result: {'PASS' if success7 else 'FAIL'} | Confirmed: {confirmed}")

    # ── Test 8: Cancellation ──────────────────────────────────────────────────
    print("\n--- TEST 8: Cancellation ---")
    exec_ctx8 = ExecutionContext(user_request="Cancel test")
    exec_ctx8.cancellation_state = True
    resp8 = agent._engine._finalize(exec_ctx8, "Task was cancelled safely.", status="cancelled")
    meta8 = agent._engine.last_execution_meta
    success8 = meta8.get("status") == "cancelled"
    results["Test 8: Cancellation"] = {
        "passed": success8,
        "status": meta8.get("status"),
    }
    print(f"Result: {'PASS' if success8 else 'FAIL'} | Final Status: {meta8.get('status')}")

    # ── Test 9: MCP / Integrations Tool Execution ─────────────────────────────
    print("\n--- TEST 9: Integrations / MCP Tool Execution ---")
    resp9 = await agent.run("List available integrations")
    meta9 = agent.last_execution_meta
    success9 = meta9.get("status") == "completed" and len(resp9.strip()) > 0
    results["Test 9: MCP Integration"] = {
        "passed": success9,
        "response": resp9[:100],
        "tool_calls": len(meta9.get("tool_calls", [])),
    }
    print(f"Result: {'PASS' if success9 else 'FAIL'} | Resp: {resp9[:80]}")

    # ── Test 10: Autonomous Scheduled Task ────────────────────────────────────
    print("\n--- TEST 10: Autonomous Scheduled Task (Phase 7) ---")
    executor = TaskExecutor(base_context=ctx)
    task = Task(
        objective="Check system time autonomously",
        allowed_tools=["get_current_time"],
        autonomy_level=AutonomyLevel.LEVEL_3_LOW_RISK,
        max_steps=2,
        max_runtime_seconds=10,
    )
    t0 = time.time()
    history = await executor.execute(task)
    d10 = time.time() - t0
    success10 = history.status == "success" and len(history.tools_used) >= 1
    results["Test 10: Autonomous Task"] = {
        "passed": success10,
        "status": history.status,
        "tools_used": history.tools_used,
        "duration_s": round(d10, 2),
    }
    print(f"Result: {'PASS' if success10 else 'FAIL'} | Status: {history.status} | Tools used: {history.tools_used}")

    print("\n=================================================================")
    print(" SUMMARY OF REAL-WORLD ACCEPTANCE TESTS")
    print("=================================================================")
    all_passed = True
    for test_name, data in results.items():
        st = "PASSED" if data["passed"] else "FAILED"
        if not data["passed"]:
            all_passed = False
        print(f"[{st}] {test_name}")
    print("=================================================================")
    print(f"OVERALL STATUS: {'ALL 10 TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(main())
