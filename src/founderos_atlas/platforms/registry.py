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
FUTURE_PLATFORMS = ("Cisco IOS-XR", "Huawei VRP", "MikroTik RouterOS")


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

    def driver_for(self, platform_id: str) -> PlatformDriver | None:
        """The driver an operator override names, by platform id (Part 4)."""

        for driver_cls in self._drivers:
            if getattr(driver_cls, "platform_id", None) == platform_id:
                return driver_cls()
        return None

    def identify(
        self,
        probe_output: str,
        *,
        override: str | None = None,
        banner: str | None = None,
        prompt: str | None = None,
    ):
        """Detection with its reasoning attached (PR-049, Part 4).

        Deterministic: matchers run in registration order; the first match
        wins exactly as ``detect`` decides, and every OTHER accepting matcher
        is reported as an alternative rather than silently discarded. The
        confidence is fixed by evidence kind (never a guess): a unique match
        scores 0.9, a contested one 0.6, an operator override 0.95 — all
        under Atlas's 0.95 cap.

        ``banner`` and ``prompt`` are optional side-channel observations
        (the SSH banner, the CLI prompt). A driver whose declared
        fingerprints match contributes extra EVIDENCE lines; when several
        probe matchers contest a device, a fingerprint corroboration
        breaks the tie back up to 0.9. A fingerprint alone never selects
        a driver — the probe output stays authoritative.

        ``override`` is the operator saying "I know what this is". It selects
        the driver but never erases what detection actually saw.
        """

        import re as _re

        from .capabilities import DetectionResult

        text = probe_output or ""
        matched = [cls for cls in self._drivers if cls.matches(text)]
        first_line = next(
            (line.strip() for line in text.splitlines() if line.strip()), ""
        )

        def _fingerprint_evidence(cls) -> tuple[str, ...]:
            found: list[str] = []
            for source, label, patterns in (
                (banner, "banner", getattr(cls, "banner_fingerprints", ())),
                (prompt, "prompt", getattr(cls, "prompt_fingerprints", ())),
            ):
                if not source:
                    continue
                for pattern in patterns:
                    if _re.search(pattern, source, _re.IGNORECASE):
                        found.append(
                            f"{label} matched {pattern!r} in "
                            f"{source.strip()[:60]!r}"
                        )
            return tuple(found)
        if override:
            chosen = self.driver_for(override)
            if chosen is None:
                return DetectionResult(
                    platform_id=None, driver=None, confidence=0.0,
                    evidence=(f"probe replied: {first_line[:100]!r}",),
                    alternatives=tuple(c.platform_id for c in matched),
                    reason=f"operator override {override!r} names no registered driver",
                    overridden=True,
                )
            return DetectionResult(
                platform_id=chosen.platform_id,
                driver=type(chosen).__name__,
                confidence=0.95,
                evidence=(f"operator override: {override}",
                          f"probe replied: {first_line[:100]!r}"),
                alternatives=tuple(
                    c.platform_id for c in matched
                    if c.platform_id != chosen.platform_id
                ),
                reason="operator override",
                overridden=True,
            )
        if not matched:
            return DetectionResult(
                platform_id=None, driver=None, confidence=0.0,
                evidence=(f"probe replied: {first_line[:100]!r}",),
                reason="no registered matcher accepted the probe output",
            )
        winner = matched[0]
        others = tuple(c.platform_id for c in matched[1:])
        fingerprints = _fingerprint_evidence(winner)
        contested = bool(others)
        # A contested probe corroborated by the winner's own banner/prompt
        # fingerprints is no longer a coin toss.
        confidence = 0.9 if (not contested or fingerprints) else 0.6
        evidence = (
            f"probe replied: {first_line[:100]!r}",
            f"matcher: {winner.__name__}",
            *fingerprints,
        )
        return DetectionResult(
            platform_id=winner.platform_id,
            driver=winner.__name__,
            confidence=confidence,
            evidence=evidence,
            alternatives=others,
            reason=(
                "single matcher accepted the probe" if not contested else (
                    "contested probe corroborated by fingerprint evidence"
                    if fingerprints else
                    "first of several accepting matchers (registration order)"
                )
            ),
        )

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

    from .drivers.atlaslab_firewall import AtlasLabFirewallDriver
    from .drivers.atlaslab_switch import AtlasLabSwitchDriver
    from .drivers.ios import CiscoIOSDriver
    from .drivers.ios_xe import CiscoIOSXEDriver
    from .drivers.nxos import CiscoNXOSDriver
    from .drivers.eos import AristaEOSDriver
    from .drivers.adc import A10AcosDriver, CitrixAdcDriver, F5BigIpDriver
    from .drivers.aruba_cx import ArubaCXDriver
    from .drivers.cisco_wlc import CiscoWlcDriver
    from .drivers.fortios import FortiOSDriver
    from .drivers.panos import PanOsDriver
    from .drivers.junos import JunosDriver
    from .drivers.frr import FRRoutingDriver

    registry = PlatformRegistry()
    # PR-049: IOS-XE before legacy IOS. Both matchers accept an IOS-XE probe
    # ("Cisco IOS XE Software" also contains "Cisco IOS Software" on the next
    # line), so order decides: XE devices get the production plan, classic
    # IOS keeps its proven minimal one.
    registry.register(CiscoIOSXEDriver)
    registry.register(CiscoIOSDriver)
    registry.register(CiscoNXOSDriver)
    registry.register(AristaEOSDriver)
    registry.register(JunosDriver)
    # Firewalls answer their own probes; matchers are disjoint from the
    # router families above.
    registry.register(FortiOSDriver)
    registry.register(PanOsDriver)
    registry.register(ArubaCXDriver)
    registry.register(CiscoWlcDriver)
    registry.register(F5BigIpDriver)
    registry.register(CitrixAdcDriver)
    registry.register(A10AcosDriver)
    registry.register(FRRoutingDriver)
    # PR-048: the AtlasLab platforms answer the same probe. Their matchers are
    # disjoint from the two above (a device says "AtlasLab firewall" or
    # "FRRouting", never both), so registration order is not load-bearing --
    # but they are registered last so a future overlap could never shadow a
    # production platform with a lab one.
    registry.register(AtlasLabFirewallDriver)
    registry.register(AtlasLabSwitchDriver)
    return registry
