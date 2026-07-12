"""Atlas Platform Driver Framework (PR-043, codename FOUNDATION).

Atlas discovers PLATFORMS and reasons about ENTERPRISES — never vendors.

    SSH → platform detection (lightweight probe) → platform driver
        → canonical enterprise model → enterprise graph

Every platform-specific behavior lives behind ``PlatformDriver``; the
discovery engine talks only to the registry and the driver interface;
downstream engines consume only canonical models. Capabilities a device
cannot provide are recorded, never raised — discovery succeeds whenever
meaningful evidence is collected. Adding a platform (NX-OS, Junos, EOS,
FortiOS, PAN-OS, …) is one driver class plus one registration.
"""

from .base import (
    CAP_COLLECTED,
    CAP_EMPTY,
    CAP_NOT_COLLECTED,
    CAP_NOT_CONFIGURED,
    CAP_UNAVAILABLE,
    CapabilitySpec,
    CapabilityStatus,
    DEFAULT_PROBE_COMMAND,
    DriverDiscovery,
    PlatformDriver,
)
from .drivers import CiscoIOSDriver, FRRoutingAdapter, FRRoutingDriver
from .registry import (
    FUTURE_PLATFORMS,
    PlatformRegistry,
    UnsupportedPlatformError,
    default_registry,
)

__all__ = [
    "CAP_COLLECTED",
    "CAP_EMPTY",
    "CAP_NOT_COLLECTED",
    "CAP_NOT_CONFIGURED",
    "CAP_UNAVAILABLE",
    "CapabilitySpec",
    "CapabilityStatus",
    "CiscoIOSDriver",
    "DEFAULT_PROBE_COMMAND",
    "DriverDiscovery",
    "FRRoutingAdapter",
    "FRRoutingDriver",
    "FUTURE_PLATFORMS",
    "PlatformDriver",
    "PlatformRegistry",
    "UnsupportedPlatformError",
    "default_registry",
]
