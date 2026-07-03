"""Transport-free Atlas discovery adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from .models import NetworkDevice, NetworkInterface, NetworkNeighbor


class DiscoveryAdapter(ABC):
    """Normalize already-collected command output; never connect to a device."""

    vendor: str
    platform_family: str
    required_commands: tuple[str, ...]

    @abstractmethod
    def parse_inventory(self, raw_outputs: Mapping[str, str]) -> NetworkDevice:
        raise NotImplementedError

    @abstractmethod
    def parse_interfaces(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkInterface, ...]:
        raise NotImplementedError

    @abstractmethod
    def parse_neighbors(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkNeighbor, ...]:
        raise NotImplementedError
