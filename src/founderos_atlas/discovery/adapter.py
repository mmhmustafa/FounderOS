"""Transport-free Atlas discovery adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from .models import NetworkDevice, NetworkInterface, NetworkNeighbor


class DiscoveryAdapter(ABC):
    """Normalize already-collected command output; never connect to a device.

    ``required_commands`` lists every command the adapter consumes; these
    exact strings are also the keys of ``raw_outputs``. Commands listed in
    ``optional_commands`` may legitimately produce empty output (for example
    a device with CDP disabled) and must parse to empty results instead of
    failing.
    """

    vendor: str
    platform_family: str
    required_commands: tuple[str, ...]
    optional_commands: tuple[str, ...] = ()

    @abstractmethod
    def parse_inventory(
        self,
        raw_outputs: Mapping[str, str],
        management_ip_hint: str | None = None,
    ) -> NetworkDevice:
        """Build the device identity.

        ``management_ip_hint`` is the address the caller actually connected
        to (when known). Adapters should fall back to it, with a recorded
        warning, when the management IP cannot be parsed from output.
        """

        raise NotImplementedError

    @abstractmethod
    def parse_interfaces(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkInterface, ...]:
        raise NotImplementedError

    @abstractmethod
    def parse_neighbors(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkNeighbor, ...]:
        raise NotImplementedError
