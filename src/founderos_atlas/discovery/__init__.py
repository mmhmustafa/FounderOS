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

__all__ = [
    "AtlasDiscoveryError",
    "DiscoveryAdapter",
    "DiscoveryEngine",
    "DiscoveryFact",
    "DiscoveryParseError",
    "DiscoveryResult",
    "MissingCommandOutputError",
    "NetworkDevice",
    "NetworkInterface",
    "NetworkNeighbor",
    "UnsupportedAdapterError",
]
