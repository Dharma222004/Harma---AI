"""
Test suite for Harma UI/UX Redesign.
Verifies:
1. Semantic HTML structure, header, sidebar, bottom navigation, command palette, voice orb.
2. Complete panel set (Home, Chat, Plans, Confirmations, Tasks, Memory, Integrations, Devices, Activity, Permissions, Health, Audit, Performance, Settings).
3. Design system tokens, light/dark themes, responsive media queries, and touch targets in CSS.
4. Mobile navigation, Command Palette, Home screen, and WebSocket handlers in app.js.
"""

import unittest
import httpx
from harma.api.server import create_app
from harma.api.events import EventBus
from harma.api.state import HarmaStateCoordinator
from harma.core.context import AgentContext


class TestUiRedesign(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ctx = AgentContext()
        self.bus = EventBus()
        self.coord = HarmaStateCoordinator(self.ctx, self.bus)
        self.app = create_app(coordinator=self.coord)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_html_document_metadata_and_a11y(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        # Document metadata & viewport-fit
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Harma Control Center", html)
        self.assertIn('name="viewport"', html)
        self.assertIn("viewport-fit=cover", html)
        self.assertIn('name="theme-color"', html)

        # Semantic landmarks
        self.assertIn('<header class="app-header"', html)
        self.assertIn('<nav class="sidebar"', html)
        self.assertIn('<main class="main-content"', html)
        self.assertIn('role="banner"', html)
        self.assertIn('role="navigation"', html)
        self.assertIn('role="main"', html)

    async def test_all_panels_exist(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        panels = [
            "panel-home",
            "panel-chat",
            "panel-plans",
            "panel-confirmations",
            "panel-tasks",
            "panel-memory",
            "panel-integrations",
            "panel-devices",
            "panel-activity",
            "panel-permissions",
            "panel-health",
            "panel-audit",
            "panel-performance",
            "panel-settings",
        ]
        for p in panels:
            self.assertIn(f'id="{p}"', html, f"Missing panel: {p}")

    async def test_home_screen_components(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        # Home branding
        self.assertIn("home-logo", html)
        self.assertIn("home-wordmark", html)
        self.assertIn("Your personal AI operating system", html)

        # Voice orb on home screen
        self.assertIn('id="home-voice-orb"', html)
        self.assertIn('id="home-voice-state"', html)

        # Quick input
        self.assertIn('id="home-quick-input"', html)
        self.assertIn('id="home-send-btn"', html)

    async def test_mobile_bottom_nav_and_drawer(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        # Bottom nav bar
        self.assertIn('class="bottom-nav"', html)
        self.assertIn('data-tab="home"', html)
        self.assertIn('data-tab="chat"', html)
        self.assertIn('data-tab="confirmations"', html)
        self.assertIn('data-tab="activity"', html)
        self.assertIn('id="btn-more-drawer"', html)

        # More drawer with auxiliary tabs
        self.assertIn('id="more-drawer"', html)
        self.assertIn('class="more-drawer-btn"', html)

    async def test_command_palette_structure(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        self.assertIn('id="command-palette-overlay"', html)
        self.assertIn('id="command-palette"', html)
        self.assertIn('id="command-input"', html)
        self.assertIn('id="command-results"', html)
        self.assertIn('data-action="emergency-stop"', html)

    async def test_emergency_stop_controls(self):
        r = await self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text

        self.assertIn('id="emergency-banner"', html)
        self.assertIn('id="btn-emergency-stop"', html)
        self.assertIn('id="btn-emergency-resume"', html)

    async def test_css_design_tokens_and_themes(self):
        r = await self.client.get("/static/style.css")
        self.assertEqual(r.status_code, 200)
        css = r.text

        # Design tokens
        self.assertIn("--bg-primary", css)
        self.assertIn("--text-primary", css)
        self.assertIn("--border", css)
        self.assertIn("--font-sans", css)
        self.assertIn("--radius-md", css)

        # Themes
        self.assertIn(".theme-dark", css)
        self.assertIn(".theme-light", css)

        # Responsive media queries & a11y reduced-motion
        self.assertIn("768px", css)
        self.assertIn("1023px", css)
        self.assertIn("prefers-reduced-motion", css)

        # Mobile bottom navigation styles
        self.assertIn(".bottom-nav", css)
        self.assertIn(".more-drawer", css)

        # Voice orb animations
        self.assertIn(".voice-orb", css)
        self.assertIn("state-listening", css)

    async def test_js_capabilities_and_interactions(self):
        r = await self.client.get("/static/app.js")
        self.assertEqual(r.status_code, 200)
        js = r.text

        # Core functionality
        self.assertIn("connectWebSocket", js)
        self.assertIn("handleIncomingEvent", js)
        self.assertIn("switchTab", js)
        self.assertIn("triggerEmergencyStop", js)

        # UI redesign features
        self.assertIn("initMobileNav", js)
        self.assertIn("initCommandPalette", js)
        self.assertIn("initHomeScreen", js)
        self.assertIn("initTheme", js)
        self.assertIn("loadPerformance", js)


if __name__ == "__main__":
    unittest.main()
