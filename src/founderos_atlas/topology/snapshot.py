"""Immutable content-addressed Atlas topology snapshot contract."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any

from .graph import TopologyGraph


SNAPSHOT_SCHEMA_VERSION = "1.0.0"


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized = {str(key): item for key, item in value.items()}
        return {key: _plain(normalized[key]) for key in sorted(normalized)}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return deepcopy(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized = {str(key): item for key, item in value.items()}
        return MappingProxyType({key: _freeze(normalized[key]) for key in sorted(normalized)})
    if isinstance(value, tuple | list):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True)
class TopologySnapshot:
    snapshot_id: str
    created_at: str | None
    devices: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    warnings: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.startswith("atlas-topology:"):
            raise ValueError("snapshot_id must be an Atlas content address")
        if self.created_at is not None and (
            not isinstance(self.created_at, str) or not self.created_at.strip()
        ):
            raise ValueError("created_at must be null or a non-empty deterministic timestamp")
        for field_name, values in (
            ("devices", self.devices), ("edges", self.edges), ("warnings", self.warnings)
        ):
            if not isinstance(values, tuple) or not all(isinstance(item, Mapping) for item in values):
                raise ValueError(f"{field_name} must be a tuple of mappings")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "snapshot_id", self.snapshot_id.strip())
        object.__setattr__(self, "created_at", self.created_at.strip() if self.created_at else None)
        object.__setattr__(self, "devices", tuple(_freeze(item) for item in self.devices))
        object.__setattr__(self, "edges", tuple(_freeze(item) for item in self.edges))
        object.__setattr__(self, "warnings", tuple(_freeze(item) for item in self.warnings))
        object.__setattr__(self, "metadata", _freeze(self.metadata))
        expected_id = self._content_address()
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot_id does not match canonical snapshot content")
        _canonical_json(self.to_dict())

    @property
    def device_count(self) -> int:
        return len(self.devices)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "device_count": self.device_count,
            "edge_count": self.edge_count,
            "devices": _plain(self.devices),
            "edges": _plain(self.edges),
            "warnings": _plain(self.warnings),
            "metadata": _plain(self.metadata),
        }

    def _content_address(self) -> str:
        content = {
            "created_at": self.created_at,
            "devices": self.devices,
            "edges": self.edges,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }
        digest = sha256(_canonical_json(content).encode("utf-8")).hexdigest()
        return f"atlas-topology:{digest}"

    @classmethod
    def from_graph(
        cls,
        graph: TopologyGraph,
        *,
        created_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "TopologySnapshot":
        if not isinstance(graph, TopologyGraph):
            raise TypeError("graph must be a TopologyGraph")
        summary = graph.summary()
        devices = tuple(
            {
                "device_id": device.device_id,
                "hostname": device.hostname,
                "management_ip": device.management_ip,
                "vendor": device.vendor,
                "platform": device.platform,
                "os_name": device.os_name,
                "os_version": device.os_version,
                "serial_number": device.serial_number,
                "interfaces": tuple(
                    {
                        "name": interface.name,
                        "ip_address": interface.ip_address,
                        "status": interface.status,
                        "protocol_status": interface.protocol_status,
                        "description": interface.description,
                        "metadata": interface.metadata,
                    }
                    for interface in graph.interfaces(device.device_id)
                ),
                "metadata": device.metadata,
            }
            for device in graph.devices()
        )
        edges = tuple(
            {
                "local_device_id": edge.local_device_id,
                "local_interface": edge.local_interface,
                "remote_hostname": edge.remote_hostname,
                "remote_interface": edge.remote_interface,
                "remote_management_ip": edge.remote_management_ip,
                "protocol": edge.protocol,
                "metadata": edge.metadata,
            }
            for edge in graph.edges()
        )
        warnings = tuple(warning.to_dict() for warning in graph.warnings())
        snapshot_metadata = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "input_device_count": summary["input_device_count"],
            "duplicates_removed": summary["duplicates_removed"],
            "warning_count": summary["warning_count"],
            "deterministic": True,
            "in_memory_only": True,
            **dict(metadata or {}),
        }
        content = {
            "created_at": created_at,
            "devices": devices,
            "edges": edges,
            "warnings": warnings,
            "metadata": snapshot_metadata,
        }
        resolved_id = f"atlas-topology:{sha256(_canonical_json(content).encode('utf-8')).hexdigest()}"
        return cls(
            snapshot_id=resolved_id,
            created_at=created_at,
            devices=devices,
            edges=edges,
            warnings=warnings,
            metadata=snapshot_metadata,
        )
