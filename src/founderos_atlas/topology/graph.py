"""Deterministic in-memory graph of discovered devices and neighbor edges."""

from __future__ import annotations

from founderos_atlas.discovery.models import DiscoveryResult, NetworkDevice, NetworkNeighbor


class TopologyGraphError(Exception):
    """Base topology graph failure."""


class DuplicateDeviceError(TopologyGraphError):
    """The same device identity was supplied with conflicting facts."""


class TopologyGraph:
    def __init__(self) -> None:
        self._devices: dict[str, NetworkDevice] = {}
        self._edges: dict[tuple[str, str, str, str], NetworkNeighbor] = {}

    def add_device(self, device: NetworkDevice) -> None:
        if not isinstance(device, NetworkDevice):
            raise TypeError("device must be a NetworkDevice")
        existing = self._devices.get(device.device_id)
        if existing is not None and existing != device:
            raise DuplicateDeviceError(f"conflicting device facts for {device.device_id!r}")
        self._devices[device.device_id] = device

    def add_neighbor(self, neighbor: NetworkNeighbor) -> None:
        if not isinstance(neighbor, NetworkNeighbor):
            raise TypeError("neighbor must be a NetworkNeighbor")
        key = (
            neighbor.local_device_id,
            neighbor.local_interface.casefold(),
            neighbor.remote_hostname.casefold(),
            (neighbor.remote_interface or "").casefold(),
        )
        existing = self._edges.get(key)
        if existing is not None and existing != neighbor:
            raise TopologyGraphError(f"conflicting neighbor facts for edge {key!r}")
        self._edges[key] = neighbor

    def add_result(self, result: DiscoveryResult) -> None:
        if not isinstance(result, DiscoveryResult):
            raise TypeError("result must be a DiscoveryResult")
        self.add_device(result.device)
        for neighbor in result.neighbors:
            self.add_neighbor(neighbor)

    def devices(self) -> tuple[NetworkDevice, ...]:
        return tuple(self._devices[key] for key in sorted(self._devices))

    def neighbors(self, device_id: str) -> tuple[NetworkNeighbor, ...]:
        return tuple(
            edge for edge in self.edges() if edge.local_device_id == device_id
        )

    def edges(self) -> tuple[NetworkNeighbor, ...]:
        return tuple(self._edges[key] for key in sorted(self._edges))

    def summary(self) -> dict[str, object]:
        return {
            "device_count": len(self._devices),
            "edge_count": len(self._edges),
            "devices": [device.device_id for device in self.devices()],
            "protocols": sorted({edge.protocol for edge in self._edges.values()}),
            "deterministic": True,
            "in_memory_only": True,
        }
