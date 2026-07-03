"""Deterministic in-memory Atlas Discovery Engine."""

from __future__ import annotations

from collections.abc import Mapping

from .adapter import DiscoveryAdapter
from .exceptions import MissingCommandOutputError, UnsupportedAdapterError
from .models import DiscoveryFact, DiscoveryResult


class DiscoveryEngine:
    def __init__(self, adapter: DiscoveryAdapter) -> None:
        if not isinstance(adapter, DiscoveryAdapter):
            raise UnsupportedAdapterError("adapter must implement DiscoveryAdapter")
        if not getattr(adapter, "vendor", "") or not getattr(adapter, "platform_family", ""):
            raise UnsupportedAdapterError("adapter vendor and platform_family are required")
        self._adapter = adapter

    def discover(self, raw_outputs: Mapping[str, str]) -> DiscoveryResult:
        if not isinstance(raw_outputs, Mapping):
            raise TypeError("raw_outputs must be a command-to-text mapping")
        if not all(isinstance(command, str) and isinstance(output, str) for command, output in raw_outputs.items()):
            raise TypeError("raw_outputs keys and values must be strings")
        normalized = dict(raw_outputs)
        for command in self._adapter.required_commands:
            output = normalized.get(command)
            if not isinstance(output, str) or not output.strip():
                raise MissingCommandOutputError(f"required command output is missing: {command}")

        device = self._adapter.parse_inventory(normalized)
        interfaces = self._adapter.parse_interfaces(normalized)
        neighbors = self._adapter.parse_neighbors(normalized)
        facts = (
            DiscoveryFact("inventory", "show version", {"device_id": device.device_id}),
            DiscoveryFact("interfaces", "show ip interface brief", {"count": len(interfaces)}),
            DiscoveryFact("neighbors", "show cdp neighbors detail", {"count": len(neighbors)}),
        )
        return DiscoveryResult(
            device=device,
            interfaces=interfaces,
            neighbors=neighbors,
            facts=facts,
            adapter_vendor=self._adapter.vendor,
            platform_family=self._adapter.platform_family,
            metadata={"transport": "none", "deterministic": True, "persistence": False},
        )
