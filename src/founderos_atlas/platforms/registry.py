"""The central Platform Registry: one place platform logic is loaded from.

Discovery never hardcodes platform checks — it asks the registry to
detect the platform from a lightweight probe and hands the connection to
the returned driver. Adding a platform is one driver class plus one
``register`` call; the rest of Atlas is untouched.
"""

from __future__ import annotations

from founderos_atlas.discovery.exceptions import AtlasDiscoveryError

from .base import DEFAULT_PROBE_COMMAND, PlatformDriver


# Platforms Atlas knows about but does not drive yet — named honestly in
# the unsupported-platform message so engineers know the roadmap.
FUTURE_PLATFORMS = ("Cisco NX-OS", "Junos", "Arista EOS", "FortiOS", "PAN-OS")


class UnsupportedPlatformError(AtlasDiscoveryError):
    """Raised when no registered driver recognizes a device."""


class PlatformRegistry:
    """Ordered, extensible driver registry with probe-based detection."""

    def __init__(self) -> None:
        self._drivers: list[type[PlatformDriver]] = []

    def register(self, driver_cls: type[PlatformDriver]) -> None:
        if not (isinstance(driver_cls, type) and issubclass(driver_cls, PlatformDriver)):
            raise TypeError("driver_cls must be a PlatformDriver subclass")
        if driver_cls not in self._drivers:
            self._drivers.append(driver_cls)

    def drivers(self) -> tuple[type[PlatformDriver], ...]:
        return tuple(self._drivers)

    def supported_platforms(self) -> tuple[str, ...]:
        return tuple(driver.display_name for driver in self._drivers)

    def probe_commands(self) -> tuple[str, ...]:
        """Every distinct probe, registration order preserved."""

        seen: list[str] = []
        for driver in self._drivers:
            probe = getattr(driver, "probe_command", DEFAULT_PROBE_COMMAND)
            if probe not in seen:
                seen.append(probe)
        return tuple(seen) or (DEFAULT_PROBE_COMMAND,)

    def detect(self, probe_output: str) -> PlatformDriver | None:
        """The first registered driver whose matcher accepts the probe."""

        for driver_cls in self._drivers:
            if driver_cls.matches(probe_output or ""):
                return driver_cls()
        return None

    def unsupported_message(self, probe_output: str) -> str:
        """The honest, actionable message for an unrecognized platform."""

        first_line = next(
            (line.strip() for line in (probe_output or "").splitlines() if line.strip()),
            "no probe output",
        )
        supported = ", ".join(self.supported_platforms()) or "none registered"
        future = ", ".join(FUTURE_PLATFORMS)
        return (
            "Unsupported platform detected. "
            f"Platform detected: Unknown (probe replied: {first_line[:120]!r}). "
            f"Supported drivers: {supported}. "
            f"Future: {future}. "
            "Discovery cannot continue on this device because no driver "
            "knows its command dialect — its neighbors discovered through "
            "other devices are unaffected."
        )


def default_registry() -> PlatformRegistry:
    """The standard registry: every built-in driver, detection order fixed."""

    from .drivers.ios import CiscoIOSDriver
    from .drivers.frr import FRRoutingDriver

    registry = PlatformRegistry()
    registry.register(CiscoIOSDriver)
    registry.register(FRRoutingDriver)
    return registry
