"""
Harma Performance V2 Benchmark Suite

Executes the 7 mandatory benchmark tasks and collects full latency, token,
and execution traces.

Tasks:
  Benchmark A — Direct response: "Hello Harma"
  Benchmark B — Deterministic tool: "What time is it?"
  Benchmark C — Single computer action: "Open Chrome"
  Benchmark D — Multi-step computer task: "Open WhatsApp and check if contact Dharmadurai is visible"
  Benchmark E — Browser task: "Open Chrome and navigate to https://example.com"
  Benchmark F — MCP task: Read-only MCP tool discovery/status query
  Benchmark G — Memory task: "Remember that my favourite programming language is Rust"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from harma.computer.windows import ensure_default_desktop
from harma.core.agent import HarmaAgent
from harma.core.context import AgentContext
from harma.core.perf import RequestTrace, Stage


async def run_benchmark(agent: HarmaAgent, name: str, prompt: str) -> dict[str, Any]:
    print(f"\n==================================================")
    print(f" RUNNING: {name}")
    print(f" Prompt:  {prompt}")
    print(f"==================================================")

    t0 = time.perf_counter()
    resp = await agent.run(prompt)
    total_sec = time.perf_counter() - t0

    meta = getattr(agent, "last_execution_meta", {}) or {}
    perf = meta.get("perf", {}) or {}
    durations = perf.get("durations_ms", {}) or {}
    counts = perf.get("counts", {}) or {}
    exec_ctx = meta.get("execution_context", {}) or {}

    llm_call_count = counts.get("llm_calls", exec_ctx.get("llm_calls", 0))
    tokens_in = counts.get("tokens_in", 0)
    tokens_out = counts.get("tokens_out", 0)
    llm_ms = durations.get("llm_ms", 0.0) or 0.0
    tool_exec_ms = durations.get("tool_execution_ms", 0.0) or 0.0
    tool_disc_ms = durations.get("tool_discovery_ms", 0.0) or 0.0
    mem_ms = durations.get("memory_retrieval_ms", 0.0) or 0.0
    selected_tools = counts.get("selected_tools", 0)
    total_tools = counts.get("total_tools", 101)

    record = {
        "benchmark": name,
        "prompt": prompt,
        "total_ms": round(total_sec * 1000, 1),
        "llm_calls_count": llm_call_count,
        "llm_latency_ms": round(llm_ms, 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tool_discovery_ms": round(tool_disc_ms, 1),
        "tool_execution_ms": round(tool_exec_ms, 1),
        "memory_retrieval_ms": round(mem_ms, 1),
        "selected_tools": selected_tools,
        "total_tools": total_tools,
        "tool_calls_count": len(meta.get("tool_calls", [])),
        "tool_names": [tc.get("tool") for tc in meta.get("tool_calls", [])],
        "verification_status": meta.get("verification", {}).get("status", "unknown"),
        "response_preview": resp[:120].strip() if resp else "",
    }

    print(f"Completed in {record['total_ms']}ms | LLM calls: {record['llm_calls_count']} | Tools: {record['tool_names']}")
    print(f"Tokens in/out: {record['tokens_in']}/{record['tokens_out']} | Selected tools: {record['selected_tools']}/{record['total_tools']}")
    print(f"Response: {record['response_preview']}")
    return record


async def main():
    ensure_default_desktop()
    sys.stdout.reconfigure(encoding="utf-8")

    out_arg = "benchmark_optimized_results.json"
    for arg in sys.argv[1:]:
        if arg.startswith("--output="):
            out_arg = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            out_arg = arg

    ctx = AgentContext()
    agent = HarmaAgent(ctx, confirm_callback=lambda p: "yes", max_iterations=6)

    benchmarks = [
        ("Benchmark A: Direct Response", "Hello Harma"),
        ("Benchmark B: Deterministic Tool", "What time is it?"),
        ("Benchmark C: Single Computer Action", "Open Chrome"),
        ("Benchmark D: Multi-Step Computer", "Open WhatsApp and check if Dharmadurai is visible"),
        ("Benchmark E: Browser Task", "Open Chrome and navigate to https://example.com"),
        ("Benchmark F: MCP Task", "Show status of external integrations"),
        ("Benchmark G: Memory Task", "Remember that my favourite programming language is Rust"),
    ]

    all_records = []
    for name, prompt in benchmarks:
        try:
            rec = await run_benchmark(agent, name, prompt)
            all_records.append(rec)
        except Exception as e:
            print(f"Benchmark {name} failed: {e}")
            all_records.append({
                "benchmark": name,
                "prompt": prompt,
                "error": str(e),
            })

    with open(out_arg, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2)

    print(f"\n==================================================")
    print(f" Saved benchmark results to {out_arg}")
    print(f"==================================================")


if __name__ == "__main__":
    asyncio.run(main())
