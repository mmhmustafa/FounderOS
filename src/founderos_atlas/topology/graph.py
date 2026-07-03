"""Deterministic in-memory graph of reconciled devices and neighbor edges."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from founderos_atlas.discovery.models import (
    DiscoveryResult,
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
)


class TopologyGraphError(Exception):
    """Base topology graph failure."""


class DuplicateDeviceError(TopologyGraphError):
    """The same explicit device identity was supplied with conflicting facts."""


@dataclass(frozen=True, order=True)
class TopologyWarning:
    code: str
    device_id: str
    field: str
    existing_value: str
    incoming_value: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "device_id": self.device_id,
            "field": self.field,
            "existing_value": self.existing_value,
            "incoming_value": self.incoming_value,
        }


class TopologyGraph:
    def __init__(self) -> None:
        self._devices: dict[str, NetworkDevice] = {}
        self._interfaces: dict[str, dict[str, NetworkInterface]] = {}
        self._edges: dict[tuple[str, str, str, str], NetworkNeighbor] = {}
        self._aliases: dict[str, str] = {}
        self._identity_index: dict[tuple[str, str], str] = {}
        self._warnings: set[TopologyWarning] = set()
        self._input_device_count = 0

    def add_device(self, device: NetworkDevice) -> None:
        """Add one exact device; retained for strict single-result compatibility."""

        if not isinstance(device, NetworkDevice):
            raise TypeError("device must be a NetworkDevice")
        existing = self._devices.get(device.device_id)
        if existing is not None and existing != device:
            raise DuplicateDeviceError(f"conflicting device facts for {device.device_id!r}")
        self._devices[device.device_id] = device
        self._aliases[device.device_id] = device.device_id
        self._register_identity(device, device.device_id)
        self._interfaces.setdefault(device.device_id, {})

    def add_neighbor(self, neighbor: NetworkNeighbor) -> None:
        if not isinstance(neighbor, NetworkNeighbor):
            raise TypeError("neighbor must be a NetworkNeighbor")
        local_id = self._canonical_id(neighbor.local_device_id)
        normalized = replace(neighbor, local_device_id=local_id)
        key = self._edge_key(normalized)
        existing = self._edges.get(key)
        if existing is not None and existing != normalized:
            raise TopologyGraphError(f"conflicting neighbor facts for edge {key!r}")
        self._edges[key] = normalized

    def add_result(self, result: DiscoveryResult) -> None:
        """Strictly add one result without cross-identity reconciliation."""

        if not isinstance(result, DiscoveryResult):
            raise TypeError("result must be a DiscoveryResult")
        self._input_device_count += 1
        self.add_device(result.device)
        self._store_interfaces(result.device.device_id, result.interfaces)
        for neighbor in result.neighbors:
            self.add_neighbor(neighbor)

    def merge_discovery_result(self, result: DiscoveryResult) -> NetworkDevice:
        """Merge one observation using deterministic identity and conflict rules."""

        if not isinstance(result, DiscoveryResult):
            raise TypeError("result must be a DiscoveryResult")
        self._input_device_count += 1
        canonical = self._merge_device(result.device)
        self._merge_interfaces(canonical.device_id, result.interfaces)
        self._aliases[result.device.device_id] = canonical.device_id
        for neighbor in result.neighbors:
            self.add_neighbor(replace(neighbor, local_device_id=canonical.device_id))
        return canonical

    def merge_graph(self, other: "TopologyGraph") -> None:
        if not isinstance(other, TopologyGraph):
            raise TypeError("other must be a TopologyGraph")
        id_map: dict[str, str] = {}
        for device in other.devices():
            canonical = self._merge_device(device)
            id_map[device.device_id] = canonical.device_id
            self._merge_interfaces(canonical.device_id, other.interfaces(device.device_id))
        for edge in other.edges():
            local_id = id_map.get(edge.local_device_id, self._canonical_id(edge.local_device_id))
            self.add_neighbor(replace(edge, local_device_id=local_id))
        self._warnings.update(other.warnings())
        self._input_device_count += other._input_device_count

    def devices(self) -> tuple[NetworkDevice, ...]:
        return tuple(self._devices[key] for key in sorted(self._devices))

    def device_count(self) -> int:
        return len(self._devices)

    def edge_count(self) -> int:
        return len(self._edges)

    def find_device(self, identity: str) -> NetworkDevice | None:
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("identity must be a non-empty string")
        query = identity.strip().casefold()
        for kind in ("hostname", "management_ip", "serial_number", "device_id"):
            canonical_id = self._identity_index.get((kind, query))
            if canonical_id is not None:
                return self._devices[canonical_id]
        alias = self._aliases.get(identity)
        return self._devices.get(alias) if alias else None

    def interfaces(self, device_id: str) -> tuple[NetworkInterface, ...]:
        canonical_id = self._canonical_id(device_id)
        values = self._interfaces.get(canonical_id, {})
        return tuple(values[key] for key in sorted(values, key=str.casefold))

    def neighbors(self, device_id: str) -> tuple[NetworkNeighbor, ...]:
        canonical_id = self._canonical_id(device_id)
        return tuple(edge for edge in self.edges() if edge.local_device_id == canonical_id)

    def edges(self) -> tuple[NetworkNeighbor, ...]:
        return tuple(self._edges[key] for key in sorted(self._edges))

    def warnings(self) -> tuple[TopologyWarning, ...]:
        return tuple(sorted(self._warnings))

    def summary(self) -> dict[str, object]:
        return {
            "input_device_count": self._input_device_count,
            "device_count": self.device_count(),
            "edge_count": self.edge_count(),
            "duplicates_removed": max(0, self._input_device_count - self.device_count()),
            "interface_count": sum(len(items) for items in self._interfaces.values()),
            "warning_count": len(self._warnings),
            "warnings": [warning.to_dict() for warning in self.warnings()],
            "devices": [device.device_id for device in self.devices()],
            "protocols": sorted({edge.protocol for edge in self._edges.values()}),
            "deterministic": True,
            "in_memory_only": True,
        }

    def _merge_device(self, incoming: NetworkDevice) -> NetworkDevice:
        existing = self._identity_match(incoming)
        if existing is None:
            self.add_device(incoming)
            return incoming

        for field in (
            "hostname", "management_ip", "serial_number", "vendor", "platform",
            "os_name", "os_version",
        ):
            existing_value = getattr(existing, field)
            incoming_value = getattr(incoming, field)
            if existing_value and incoming_value and existing_value.casefold() != incoming_value.casefold():
                self._warn("device_fact_conflict", existing.device_id, field, existing_value, incoming_value)

        metadata = dict(existing.metadata)
        for key, value in incoming.metadata.items():
            if key in metadata and metadata[key] != value:
                self._warn(
                    "device_metadata_conflict", existing.device_id, f"metadata.{key}",
                    repr(metadata[key]), repr(value),
                )
            else:
                metadata[key] = value
        merged = replace(existing, metadata=metadata)
        self._devices[existing.device_id] = merged
        self._aliases[incoming.device_id] = existing.device_id
        self._register_identity(incoming, existing.device_id)
        return merged

    def _identity_match(self, incoming: NetworkDevice) -> NetworkDevice | None:
        for key in self._identity_keys(incoming):
            canonical_id = self._identity_index.get(key)
            if canonical_id is not None:
                return self._devices[canonical_id]
        return None

    def _register_identity(self, device: NetworkDevice, canonical_id: str) -> None:
        for key in self._identity_keys(device):
            self._identity_index.setdefault(key, canonical_id)

    @staticmethod
    def _identity_keys(device: NetworkDevice) -> tuple[tuple[str, str], ...]:
        values = (
            ("hostname", device.hostname),
            ("management_ip", device.management_ip),
            ("serial_number", device.serial_number),
            ("device_id", device.device_id),
        )
        return tuple(
            (kind, value.casefold()) for kind, value in values if value is not None
        )

    def _merge_interfaces(
        self, device_id: str, interfaces: tuple[NetworkInterface, ...]
    ) -> None:
        target = self._interfaces.setdefault(device_id, {})
        for incoming in interfaces:
            key = incoming.name.casefold()
            existing = target.get(key)
            if existing is None:
                target[key] = incoming
                continue
            metadata = dict(existing.metadata)
            for metadata_key, value in incoming.metadata.items():
                if metadata_key in metadata and metadata[metadata_key] != value:
                    self._warn(
                        "interface_metadata_conflict", device_id,
                        f"interface.{incoming.name}.metadata.{metadata_key}",
                        repr(metadata[metadata_key]), repr(value),
                    )
                else:
                    metadata[metadata_key] = value
            for field in ("ip_address", "status", "protocol_status", "description"):
                existing_value = getattr(existing, field)
                incoming_value = getattr(incoming, field)
                if existing_value is not None and incoming_value is not None and existing_value != incoming_value:
                    self._warn(
                        "interface_fact_conflict", device_id,
                        f"interface.{incoming.name}.{field}", str(existing_value), str(incoming_value),
                    )
            target[key] = replace(existing, metadata=metadata)

    def _store_interfaces(
        self, device_id: str, interfaces: tuple[NetworkInterface, ...]
    ) -> None:
        target = self._interfaces.setdefault(device_id, {})
        for interface in interfaces:
            key = interface.name.casefold()
            existing = target.get(key)
            if existing is not None and existing != interface:
                raise TopologyGraphError(
                    f"conflicting interface facts for {device_id!r} {interface.name!r}"
                )
            target[key] = interface

    def _canonical_id(self, device_id: str) -> str:
        return self._aliases.get(device_id, device_id)

    @staticmethod
    def _edge_key(neighbor: NetworkNeighbor) -> tuple[str, str, str, str]:
        return (
            neighbor.local_device_id,
            neighbor.local_interface.casefold(),
            neighbor.remote_hostname.casefold(),
            (neighbor.remote_interface or "").casefold(),
        )

    def _warn(
        self,
        code: str,
        device_id: str,
        field: str,
        existing_value: Any,
        incoming_value: Any,
    ) -> None:
        self._warnings.add(
            TopologyWarning(
                code=code,
                device_id=device_id,
                field=field,
                existing_value=str(existing_value),
                incoming_value=str(incoming_value),
            )
        )
