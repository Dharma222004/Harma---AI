"""
Harma Agent Context

Carries all shared state for a single Harma session:
  - LLM provider instance
  - Tool registry
  - Short-term memory
  - Permission manager

The agent, planner, and executor receive this context object rather than
each importing singletons directly, making the system testable and modular.
"""

from __future__ import annotations

from typing import Any

from harma.llm.provider import LLMProvider
from harma.llm.factory import get_provider
from harma.memory.short_term import ShortTermMemory
from harma.security.permissions import PermissionManager
from harma.tools.registry import ToolRegistry
from harma.config.logging_config import get_logger

log = get_logger(__name__)


class AgentContext:
    """
    Single context object passed through the agent pipeline.

    Instantiating this class wires Phase 1 + Phase 2 tools together.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        registry: ToolRegistry | None = None,
        memory: ShortTermMemory | None = None,
        permissions: PermissionManager | None = None,
        long_term_memory: Any | None = None,
        android_manager: Any | None = None,
        task_manager: Any | None = None,
        integration_manager: Any | None = None,
    ) -> None:
        # ── Android Subsystem ─────────────────────────────────────────────────
        if android_manager is not None:
            from harma.android.manager import set_android_manager
            set_android_manager(android_manager)
            self.android_manager = android_manager
        else:
            try:
                from harma.android.manager import get_android_manager
                self.android_manager = get_android_manager()
            except Exception as exc:
                log.warning("Could not initialize Android manager: %s", exc)
                self.android_manager = None

        # ── Task Subsystem (Phase 7) ──────────────────────────────────────────
        if task_manager is not None:
            from harma.tasks.manager import set_task_manager
            set_task_manager(task_manager)
            self.task_manager = task_manager
        else:
            try:
                from harma.tasks.manager import get_task_manager
                self.task_manager = get_task_manager()
            except Exception as exc:
                log.warning("Could not initialize Task manager: %s", exc)
                self.task_manager = None

        # ── Integrations & MCP Subsystem (Phase 8) ────────────────────────────
        if integration_manager is not None:
            from harma.integrations.manager import set_integration_manager
            set_integration_manager(integration_manager)
            self.integration_manager = integration_manager
        else:
            try:
                from harma.integrations.manager import get_integration_manager
                self.integration_manager = get_integration_manager()
            except Exception as exc:
                log.warning("Could not initialize Integration manager: %s", exc)
                self.integration_manager = None

        # ── LLM Provider ──────────────────────────────────────────────────────
        self.llm: LLMProvider = provider or get_provider()
        log.info("LLM provider: %s", self.llm.name)

        # ── Tool Registry ─────────────────────────────────────────────────────
        self.registry: ToolRegistry = registry if registry is not None else ToolRegistry()
        if registry is None:
            self._register_builtin_tools()

        # ── Memory ────────────────────────────────────────────────────────────
        self.memory: ShortTermMemory = memory or ShortTermMemory()
        if long_term_memory is not None:
            self.long_term_memory = long_term_memory
        else:
            try:
                from harma.memory.manager import get_memory_manager
                self.long_term_memory = get_memory_manager()
            except Exception as exc:
                log.warning("Could not initialize long-term memory: %s", exc)
                self.long_term_memory = None

        # ── Permissions ───────────────────────────────────────────────────────
        self.permissions: PermissionManager = permissions or PermissionManager()

        # ── Phase 9: Unified Intelligence, Perception & Planning ──────────────
        try:
            from harma.intelligence.planner import AdvancedPlanner
            from harma.intelligence.context_fusion import ContextFusionEngine
            from harma.intelligence.model_router import ModelRouter
            from harma.perception.screen_understanding import ScreenPerception
            from harma.perception.browser_vision import BrowserVision
            from harma.perception.document import DocumentParser
            from harma.perception.extraction import StructuredExtractor

            self.planner = AdvancedPlanner(self.registry)
            self.context_fusion = ContextFusionEngine()
            self.screen_perception = ScreenPerception()
            self.browser_vision = BrowserVision()
            self.document_parser = DocumentParser()
            self.structured_extractor = StructuredExtractor()
            self.model_router = ModelRouter(self.llm)
        except Exception as exc:
            log.warning("Could not fully initialize Phase 9 subsystems: %s", exc)
            self.planner = None
            self.context_fusion = None
            self.screen_perception = None
            self.browser_vision = None
            self.document_parser = None
            self.structured_extractor = None
            self.model_router = None

        log.info("Agent context ready. Tools: %d", len(self.registry))

    def _register_builtin_tools(self) -> None:
        """Register all built-in Phase 1 + Phase 2 tools."""
        # ── Phase 1 tools ─────────────────────────────────────────────────────
        from harma.tools.system.time_tools import GetCurrentTimeTool, GetSystemInfoTool
        from harma.tools.computer.app_tools import OpenApplicationTool, CloseApplicationTool

        phase1_tools = [
            GetCurrentTimeTool(),
            GetSystemInfoTool(),
            OpenApplicationTool(),
            CloseApplicationTool(),
        ]
        for tool in phase1_tools:
            self.registry.register(tool)

        # ── Phase 2 tools ─────────────────────────────────────────────────────
        self._register_phase2_tools()

        # ── Phase 3 tools ─────────────────────────────────────────────────────
        self._register_phase3_tools()

        # ── Phase 5 tools ─────────────────────────────────────────────────────
        self._register_phase5_tools()

        # ── Phase 6 tools ─────────────────────────────────────────────────────
        self._register_phase6_tools()

        # ── Phase 7 tools ─────────────────────────────────────────────────────
        self._register_phase7_tools()

        # ── Phase 8 tools ─────────────────────────────────────────────────────
        self._register_phase8_tools()

        # ── Phase 9 tools ─────────────────────────────────────────────────────
        self._register_phase9_tools()

        # Auto-discover any additional tools in built-in packages
        self.registry.auto_discover()

    def _register_phase2_tools(self) -> None:
        """Register Phase 2 computer-control tools."""
        try:
            from harma.tools.computer.screen_tools import (
                TakeScreenshotTool, ObserveScreenTool, GetScreenSizeTool
            )
            from harma.tools.computer.mouse_tools import (
                MouseMoveTool, MouseClickTool, MouseDoubleClickTool,
                MouseRightClickTool, MouseDragTool, MouseScrollTool,
            )
            from harma.tools.computer.keyboard_tools import (
                TypeTextTool, PressKeyTool, HotkeyTool
            )
            from harma.tools.computer.window_tools import (
                GetActiveWindowTool, ListOpenWindowsTool, FocusApplicationTool,
                FindUIElementTool, ClickElementTool,
            )

            phase2_tools = [
                # Screen
                TakeScreenshotTool(),
                ObserveScreenTool(),
                GetScreenSizeTool(),
                # Mouse
                MouseMoveTool(),
                MouseClickTool(),
                MouseDoubleClickTool(),
                MouseRightClickTool(),
                MouseDragTool(),
                MouseScrollTool(),
                # Keyboard
                TypeTextTool(),
                PressKeyTool(),
                HotkeyTool(),
                # Windows
                GetActiveWindowTool(),
                ListOpenWindowsTool(),
                FocusApplicationTool(),
                FindUIElementTool(),
                ClickElementTool(),
            ]

            for tool in phase2_tools:
                self.registry.register(tool)

            log.info("Phase 2 tools registered: %d", len(phase2_tools))

        except ImportError as exc:
            log.warning(
                "Phase 2 computer-control tools could not be loaded: %s  "
                "(Install: pip install pyautogui pygetwindow psutil pywin32)",
                exc,
            )
        except Exception as exc:
            log.warning("Phase 2 tool registration error: %s", exc)

    def _register_phase3_tools(self) -> None:
        """Register Phase 3 browser automation tools."""
        try:
            from harma.tools.browser.navigation_tools import (
                LaunchBrowserTool, CloseBrowserTool, BrowserStatusTool,
                NavigateToTool, GoBackTool, GoForwardTool, ReloadPageTool,
                GetCurrentUrlTool, GetPageTitleTool, ObservePageTool, SearchWebTool,
            )
            from harma.tools.browser.interaction_tools import (
                BrowserClickTool, BrowserTypeTool, BrowserSelectTool,
                BrowserCheckTool, BrowserUncheckTool, BrowserHoverTool,
                BrowserPressKeyTool, BrowserScrollTool, BrowserUploadFileTool,
                SelectCinemaSeatsTool,
            )
            from harma.tools.browser.extraction_tools import (
                ExtractPageTextTool, ExtractLinksTool, FindTextOnPageTool,
                GetElementTextTool, FindElementTool,
            )
            from harma.tools.browser.tab_tools import (
                ListBrowserTabsTool, NewBrowserTabTool,
                SwitchBrowserTabTool, CloseBrowserTabTool,
            )
            from harma.tools.browser.download_tools import (
                BrowserDownloadTool, ListBrowserDownloadsTool,
            )

            phase3_tools = [
                # Browser lifecycle
                LaunchBrowserTool(), CloseBrowserTool(), BrowserStatusTool(),
                # Navigation
                NavigateToTool(), GoBackTool(), GoForwardTool(),
                ReloadPageTool(), GetCurrentUrlTool(), GetPageTitleTool(),
                # Observation
                ObservePageTool(), SearchWebTool(),
                # Interaction
                BrowserClickTool(), BrowserTypeTool(), BrowserSelectTool(),
                BrowserCheckTool(), BrowserUncheckTool(), BrowserHoverTool(),
                BrowserPressKeyTool(), BrowserScrollTool(), BrowserUploadFileTool(),
                SelectCinemaSeatsTool(),
                # Extraction
                ExtractPageTextTool(), ExtractLinksTool(), FindTextOnPageTool(),
                GetElementTextTool(), FindElementTool(),
                # Tabs
                ListBrowserTabsTool(), NewBrowserTabTool(),
                SwitchBrowserTabTool(), CloseBrowserTabTool(),
                # Downloads
                BrowserDownloadTool(), ListBrowserDownloadsTool(),
            ]

            for tool in phase3_tools:
                self.registry.register(tool)

            log.info("Phase 3 tools registered: %d", len(phase3_tools))

        except ImportError as exc:
            log.warning(
                "Phase 3 browser tools could not be loaded: %s  "
                "(Install: pip install playwright && python -m playwright install chromium)",
                exc,
            )
        except Exception as exc:
            log.warning("Phase 3 tool registration error: %s", exc)

    def _register_phase5_tools(self) -> None:
        """Register Phase 5 long-term memory tools."""
        try:
            from harma.memory.tools import get_memory_tools
            phase5_tools = get_memory_tools()
            for tool in phase5_tools:
                self.registry.register(tool)
            log.info("Phase 5 memory tools registered: %d", len(phase5_tools))
        except ImportError as exc:
            log.warning("Phase 5 memory tools could not be loaded: %s", exc)
        except Exception as exc:
            log.warning("Phase 5 memory tool registration error: %s", exc)

    def _register_phase6_tools(self) -> None:
        """Register Phase 6 Android mobile control tools."""
        try:
            from harma.android.tools import get_android_tools
            phase6_tools = get_android_tools()
            for tool in phase6_tools:
                self.registry.register(tool)
            log.info("Phase 6 Android tools registered: %d", len(phase6_tools))
        except ImportError as exc:
            log.warning("Phase 6 Android tools could not be loaded: %s", exc)
        except Exception as exc:
            log.warning("Phase 6 Android tool registration error: %s", exc)

    def _register_phase7_tools(self) -> None:
        """Register Phase 7 proactive task management tools."""
        try:
            from harma.tasks.tools import get_task_tools
            phase7_tools = get_task_tools(self.task_manager)
            for tool in phase7_tools:
                self.registry.register(tool)
            log.info("Phase 7 task tools registered: %d", len(phase7_tools))
        except ImportError as exc:
            log.warning("Phase 7 task tools could not be loaded: %s", exc)
        except Exception as exc:
            log.warning("Phase 7 task tool registration error: %s", exc)

    def _register_phase8_tools(self) -> None:
        """Register Phase 8 external service & MCP integration tools."""
        try:
            from harma.integrations.tools import get_integration_tools
            phase8_tools = get_integration_tools(self.integration_manager)
            for tool in phase8_tools:
                self.registry.register(tool)
            log.info("Phase 8 integration tools registered: %d", len(phase8_tools))
        except ImportError as exc:
            log.warning("Phase 8 integration tools could not be loaded: %s", exc)
        except Exception as exc:
            log.warning("Phase 8 integration tool registration error: %s", exc)

    def _register_phase9_tools(self) -> None:
        """Register Phase 9 unified intelligence & multimodal perception tools."""
        try:
            from harma.tools.intelligence.plan_tools import PlanGoalTool, GetPlanStatusTool
            from harma.tools.intelligence.perception_tools import (
                PerceiveScreenTool, ParseDocumentTool, ExtractStructuredDataTool
            )

            planner = getattr(self, "planner", None)
            screen_perception = getattr(self, "screen_perception", None)
            doc_parser = getattr(self, "document_parser", None)
            extractor = getattr(self, "structured_extractor", None)

            phase9_tools = [
                PlanGoalTool(planner=planner),
                GetPlanStatusTool(planner=planner),
                PerceiveScreenTool(screen_perception=screen_perception),
                ParseDocumentTool(parser=doc_parser),
                ExtractStructuredDataTool(extractor=extractor),
            ]
            for tool in phase9_tools:
                self.registry.register(tool)
            log.info("Phase 9 intelligence tools registered: %d", len(phase9_tools))
        except ImportError as exc:
            log.warning("Phase 9 intelligence tools could not be loaded: %s", exc)
        except Exception as exc:
            log.warning("Phase 9 intelligence tool registration error: %s", exc)


