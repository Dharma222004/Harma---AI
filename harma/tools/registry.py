"""
Harma Tool Registry

Central hub that manages all available tools.

Features:
  • Register any BaseTool subclass at runtime.
  • Auto-discover tools from built-in packages.
  • Export tool definitions for the LLM.
  • Dispatch tool calls by name.
  • No agent code needs to change when tools are added.
"""

from __future__ import annotations

import importlib
import pkgutil
import inspect
from typing import Optional

from harma.config.logging_config import get_logger
from harma.tools.base import BaseTool, ToolResult, PermissionLevel
from harma.llm.provider import ToolDefinition

log = get_logger(__name__)

# Built-in tool packages to auto-discover (relative to harma.tools)
_BUILTIN_PACKAGES = [
    "harma.tools.system",
    "harma.tools.computer",
    "harma.tools.browser",
    "harma.tools.files",
    "harma.tools.communication",
]


class ToolRegistry:
    """
    Singleton registry for all Harma tools.

    Usage:
        registry = ToolRegistry()
        registry.register(MyTool())
        result = await registry.call("my_tool", arg1="value")
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._schema_cache: list[ToolDefinition] | None = None  # cached tool definitions
        self._schema_cache_filter: str | None = None  # cache key

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, tool: BaseTool) -> None:
        """Register a single tool instance."""
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} has no name set.")
        if tool.name in self._tools:
            log.warning("Tool '%s' already registered — overwriting.", tool.name)
        self._tools[tool.name] = tool
        self._schema_cache = None  # invalidate cache on any registration
        log.debug("Registered tool: %s  [%s]", tool.name, tool.permission_level.value)

    def register_many(self, tools: list[BaseTool]) -> None:
        """Register multiple tool instances."""
        for tool in tools:
            self.register(tool)

    def auto_discover(self) -> None:
        """
        Auto-import all built-in tool packages.

        For each package in _BUILTIN_PACKAGES, this imports the package and
        any BaseTool subclasses found there are expected to register themselves
        — or callers can call register() manually.

        This approach keeps the registry flexible: external tools can also be
        discovered by calling auto_discover_package() with a custom package path.
        """
        for package_path in _BUILTIN_PACKAGES:
            try:
                self._import_package(package_path)
            except ModuleNotFoundError:
                log.debug("Tool package not yet implemented: %s", package_path)

    def _import_package(self, package_path: str) -> None:
        """Import a package and collect all BaseTool subclasses."""
        try:
            pkg = importlib.import_module(package_path)
        except ModuleNotFoundError:
            return

        # Walk submodules
        if hasattr(pkg, "__path__"):
            for _, mod_name, _ in pkgutil.walk_packages(
                pkg.__path__, prefix=package_path + "."
            ):
                try:
                    mod = importlib.import_module(mod_name)
                    self._collect_tools_from_module(mod)
                except Exception as exc:
                    log.debug("Could not import tool module %s: %s", mod_name, exc)
        else:
            self._collect_tools_from_module(pkg)

    def _collect_tools_from_module(self, module) -> None:
        """Find BaseTool subclasses in a module and register instances."""
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseTool)
                and obj is not BaseTool
                and obj.name  # must have a name
                and obj.name not in self._tools
            ):
                try:
                    self.register(obj())
                except Exception as exc:
                    log.warning("Could not instantiate tool %s: %s", obj.__name__, exc)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[BaseTool]:
        """Return a tool by name, or None if not found."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_tool_definitions(
        self,
        permission_filter: Optional[list[PermissionLevel]] = None,
    ) -> list[ToolDefinition]:
        """
        Return LLM-ready ToolDefinition objects.

        Results are cached after first build and invalidated only when tools
        are registered or removed — eliminating per-request schema overhead.

        Args:
            permission_filter: If given, only include tools at these levels.
        """
        cache_key = str(permission_filter)
        if self._schema_cache is not None and self._schema_cache_filter == cache_key:
            return self._schema_cache

        defs = []
        for tool in self._tools.values():
            if permission_filter and tool.permission_level not in permission_filter:
                continue
            defs.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
            )
        self._schema_cache = defs
        self._schema_cache_filter = cache_key
        log.debug("[REGISTRY] Schema cache built: %d tool definitions", len(defs))
        return defs

    # ── Execution ─────────────────────────────────────────────────────────────

    async def call(self, tool_name: str, /, **kwargs) -> ToolResult:
        """
        Execute a tool by name with given arguments.

        Args:
            tool_name: Tool name as registered (positional-only).
            **kwargs: Arguments forwarded to tool.execute().

        Returns:
            ToolResult. Never raises — errors are returned as ToolResult(success=False).
        """
        tool = self.get(tool_name)
        if not tool:
            available = ", ".join(self._tools.keys()) or "(none)"
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool '{tool_name}'. Available: {available}",
            )

        log.info("[TOOL] Executing: %s  args=%s", tool_name, kwargs)
        try:
            result = await tool.execute(**kwargs)
        except Exception as exc:
            log.exception("Tool '%s' raised an unexpected exception: %s", tool_name, exc)
            result = ToolResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' crashed: {exc}",
            )

        if result.success:
            log.info("[OK]  Tool '%s' succeeded: %s", tool_name, result.output[:120])
        else:
            log.warning("[FAIL] Tool '%s' failed: %s", tool_name, result.error)

        return result

    # ── Info ──────────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Human-readable summary of registered tools."""
        if not self._tools:
            return "No tools registered."
        lines = [f"Registered tools ({len(self._tools)}):"]
        for tool in self._tools.values():
            lines.append(f"  • {tool.name:<30} [{tool.permission_level.value}]")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
