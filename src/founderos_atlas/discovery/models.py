"""Immutable vendor-neutral Atlas discovery models."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from ipaddress import ip_address
from types import MappingProxyType
from typing import Any


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _required(value, field_name)


def _ip(value: str | None, field_name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} must be a valid IP address")
        return None
    try:
        return str(ip_address(value))
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid IP address") from error


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized = {str(key): item for key, item in value.items()}
        return MappingProxyType({key: _freeze(normalized[key]) for key in sorted(normalized)})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def _freeze_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return _freeze(value)


@dataclass(frozen=True)
class NetworkDevice:
    device_id: str
    hostname: str
    management_ip: str
    vendor: str
    platform: str
    os_name: str
    os_version: str
    serial_number: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("device_id", "hostname", "vendor", "platform", "os_name", "os_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "management_ip", _ip(self.management_ip, "management_ip", required=True))
        object.__setattr__(self, "serial_number", _optional(self.serial_number, "serial_number"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    ip_address: str | None
    status: str
    protocol_status: str | None = None
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required(self.name, "name"))
        object.__setattr__(self, "ip_address", _ip(self.ip_address, "ip_address"))
        object.__setattr__(self, "status", _required(self.status, "status").lower())
        object.__setattr__(self, "protocol_status", _optional(self.protocol_status, "protocol_status"))
        object.__setattr__(self, "description", _optional(self.description, "description"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class NetworkNeighbor:
    local_device_id: str
    local_interface: str
    remote_hostname: str
    remote_interface: str | None = None
    remote_management_ip: str | None = None
    protocol: str = "manual"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("local_device_id", "local_interface", "remote_hostname"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "remote_interface", _optional(self.remote_interface, "remote_interface"))
        object.__setattr__(self, "remote_management_ip", _ip(self.remote_management_ip, "remote_management_ip"))
        protocol = _required(self.protocol, "protocol").lower()
        # PR-043: adjacency evidence is platform-neutral. Link-layer
        # discovery (cdp/lldp) and routing adjacencies (ospf/bgp/isis)
        # are all legitimate neighbor sources; the closed set stays a
        # typo guard, extended rather than scattered.
        if protocol not in {
            "cdp", "lldp", "ospf", "bgp", "isis", "manual", "inferred",
        }:
            raise ValueError(
                "protocol must be one of cdp, lldp, ospf, bgp, isis, "
                "manual, or inferred"
            )
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class DiscoveryFact:
    fact_type: str
    source_command: str
    value: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_type", _required(self.fact_type, "fact_type"))
        object.__setattr__(self, "source_command", _required(self.source_command, "source_command"))
        object.__setattr__(self, "value", _freeze_mapping(self.value, "value"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class DiscoveryResult:
    device: NetworkDevice
    interfaces: tuple[NetworkInterface, ...]
    neighbors: tuple[NetworkNeighbor, ...]
    facts: tuple[DiscoveryFact, ...]
    adapter_vendor: str
    platform_family: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.device, NetworkDevice):
            raise ValueError("device must be a NetworkDevice")
        if not all(isinstance(item, NetworkInterface) for item in self.interfaces):
            raise ValueError("interfaces must contain NetworkInterface values")
        if not all(isinstance(item, NetworkNeighbor) for item in self.neighbors):
            raise ValueError("neighbors must contain NetworkNeighbor values")
        if not all(isinstance(item, DiscoveryFact) for item in self.facts):
            raise ValueError("facts must contain DiscoveryFact values")
        interfaces = tuple(sorted(self.interfaces, key=lambda item: item.name.casefold()))
        if len({item.name.casefold() for item in interfaces}) != len(interfaces):
            raise ValueError("interfaces must have unique names")
        neighbors = tuple(sorted(self.neighbors, key=lambda item: (
            item.local_interface.casefold(), item.remote_hostname.casefold(),
            (item.remote_interface or "").casefold(),
        )))
        facts = tuple(sorted(self.facts, key=lambda item: (item.fact_type, item.source_command)))
        object.__setattr__(self, "interfaces", interfaces)
        object.__setattr__(self, "neighbors", neighbors)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "adapter_vendor", _required(self.adapter_vendor, "adapter_vendor"))
        object.__setattr__(self, "platform_family", _required(self.platform_family, "platform_family"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))
