"""Vendor-neutral Atlas discovery contracts and engine."""

from .adapter import DiscoveryAdapter
from .engine import DiscoveryEngine
from .exceptions import (
    AtlasDiscoveryError,
    DiscoveryParseError,
    MissingCommandOutputError,
    UnsupportedAdapterError,
)
from .models import (
    DiscoveryFact,
    DiscoveryResult,
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
)
from .multihop import (
    DeviceVisit,
    MultiHopConfig,
    MultiHopDiscoveryReport,
    discover_multihop,
)

__all__ = [
    "AtlasDiscoveryError",
    "DeviceVisit",
    "DiscoveryAdapter",
    "DiscoveryEngine",
    "DiscoveryFact",
    "DiscoveryParseError",
    "DiscoveryResult",
    "MissingCommandOutputError",
    "MultiHopConfig",
    "MultiHopDiscoveryReport",
    "NetworkDevice",
    "NetworkInterface",
    "NetworkNeighbor",
    "UnsupportedAdapterError",
    "discover_multihop",
]
