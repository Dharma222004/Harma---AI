"""
Harma Android App Management & Discovery

Handles listing installed apps, fuzzy lookup, resolving display names to package names,
launching, and closing applications.
"""

from __future__ import annotations

from typing import Optional

from harma.android.exceptions import AmbiguousAppError, AppNotFoundError
from harma.android.models import AndroidActionResult, AppInfo
from harma.android.transports.base import AndroidTransport
from harma.config.logging_config import get_logger

log = get_logger(__name__)

# Common well-known Android applications catalog
WELL_KNOWN_APPS: list[AppInfo] = [
    AppInfo(name="Settings", package="com.android.settings", is_system=True, aliases=["system settings", "device settings"]),
    AppInfo(name="Chrome", package="com.android.chrome", is_system=False, aliases=["browser", "google chrome"]),
    AppInfo(name="WhatsApp", package="com.whatsapp", is_system=False, aliases=["wa", "whatsapp messenger"]),
    AppInfo(name="YouTube", package="com.google.android.youtube", is_system=False, aliases=["yt"]),
    AppInfo(name="Calculator", package="com.google.android.calculator", is_system=True, aliases=["calc"]),
    AppInfo(name="Maps", package="com.google.android.apps.maps", is_system=False, aliases=["google maps", "navigation"]),
    AppInfo(name="Gmail", package="com.google.android.gm", is_system=False, aliases=["email", "mail"]),
    AppInfo(name="Camera", package="com.android.camera2", is_system=True, aliases=["cam"]),
    AppInfo(name="Photos", package="com.google.android.apps.photos", is_system=False, aliases=["gallery"]),
    AppInfo(name="Messages", package="com.google.android.apps.messaging", is_system=True, aliases=["sms", "messaging"]),
    AppInfo(name="Phone", package="com.google.android.dialer", is_system=True, aliases=["dialer", "call"]),
    AppInfo(name="Clock", package="com.google.android.deskclock", is_system=True, aliases=["alarm"]),
    AppInfo(name="Play Store", package="com.android.vending", is_system=True, aliases=["google play", "store"]),
]


class AppManager:
    """
    Manages Android applications on a device.
    """

    def __init__(self, transport: AndroidTransport) -> None:
        self.transport = transport
        self._known_apps: dict[str, AppInfo] = {app.package: app for app in WELL_KNOWN_APPS}

    async def list_installed_apps(self, device_id: str) -> list[AppInfo]:
        """
        List all installed packages on the device, enriched with display names where known.
        """
        packages = await self.transport.list_packages(device_id)
        result: list[AppInfo] = []

        for pkg in packages:
            if pkg in self._known_apps:
                result.append(self._known_apps[pkg])
            else:
                # Derive a friendly display name from package suffix
                parts = pkg.split(".")
                name = parts[-1].capitalize() if parts else pkg
                result.append(
                    AppInfo(
                        name=name,
                        package=pkg,
                        is_system=pkg.startswith("com.android.") or pkg.startswith("android"),
                    )
                )

        return sorted(result, key=lambda a: a.name)

    async def find_app(self, device_id: str, query: str) -> AppInfo:
        """
        Resolve a user query (e.g. "WhatsApp", "Chrome", "settings") to an installed AppInfo.
        Handles:
          1. Exact name / package match
          2. Case-insensitive exact match
          3. Alias match
          4. Substring match
        Raises:
          - AmbiguousAppError if multiple non-exact matches exist
          - AppNotFoundError if no matching app is found
        """
        q = query.strip().lower()
        if not q:
            raise AppNotFoundError(query)

        installed_apps = await self.list_installed_apps(device_id)

        # 1. Exact match on package or name
        for app in installed_apps:
            if app.package == query or app.name.lower() == q:
                return app

        # 2. Alias match
        for app in installed_apps:
            if any(alias.lower() == q for alias in app.aliases):
                return app

        # 3. Matches by prefix or suffix
        candidates: list[AppInfo] = []
        for app in installed_apps:
            if (
                app.name.lower().startswith(q)
                or app.package.lower().endswith(f".{q}")
                or f".{q}." in app.package.lower()
            ):
                candidates.append(app)

        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            raise AmbiguousAppError(query, [c.name for c in candidates])

        # 4. General substring match
        sub_candidates = [app for app in installed_apps if q in app.name.lower() or q in app.package.lower()]
        if len(sub_candidates) == 1:
            return sub_candidates[0]
        elif len(sub_candidates) > 1:
            raise AmbiguousAppError(query, [c.name for c in sub_candidates])

        # Suggestions for error message
        suggestions = [app.name for app in installed_apps if app.name[:3].lower() == q[:3]]
        raise AppNotFoundError(query, suggestions=suggestions[:5])

    async def launch_app(self, device_id: str, app_name_or_package: str) -> AndroidActionResult:
        """
        Resolve app name and launch application.
        """
        app = await self.find_app(device_id, app_name_or_package)
        success = await self.transport.launch_app(device_id, app.package)

        # Verify current app
        cur_pkg, cur_act = await self.transport.get_current_app(device_id)
        verified = (cur_pkg == app.package)

        return AndroidActionResult(
            success=success,
            action="launch_app",
            detail=f"Launched '{app.name}' ({app.package})",
            verified=verified,
            data={"name": app.name, "package": app.package, "current_app": cur_pkg},
        )

    async def close_app(self, device_id: str, app_name_or_package: str) -> AndroidActionResult:
        """
        Resolve app name and close (force-stop) application.
        """
        app = await self.find_app(device_id, app_name_or_package)
        success = await self.transport.close_app(device_id, app.package)

        # Verify current app is not the closed app
        cur_pkg, _ = await self.transport.get_current_app(device_id)
        verified = (cur_pkg != app.package)

        return AndroidActionResult(
            success=success,
            action="close_app",
            detail=f"Closed application '{app.name}' ({app.package})",
            verified=verified,
            data={"name": app.name, "package": app.package},
        )

    async def get_current_app(self, device_id: str) -> AppInfo:
        """
        Get info about the currently active foreground application.
        """
        cur_pkg, _ = await self.transport.get_current_app(device_id)
        if cur_pkg in self._known_apps:
            return self._known_apps[cur_pkg]
        parts = cur_pkg.split(".")
        name = parts[-1].capitalize() if parts else cur_pkg
        return AppInfo(name=name, package=cur_pkg)
