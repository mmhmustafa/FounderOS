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
from .policy import (
    BOUNDARY_ALLOWED,
    BOUNDARY_DENIED,
    BOUNDARY_OBSERVE_ONLY,
    BOUNDARY_UNKNOWN,
    BoundaryDecision,
    BoundaryPolicy,
)

__all__ = [
    "AtlasDiscoveryError",
    "BOUNDARY_ALLOWED",
    "BOUNDARY_DENIED",
    "BOUNDARY_OBSERVE_ONLY",
    "BOUNDARY_UNKNOWN",
    "BoundaryDecision",
    "BoundaryPolicy",
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
