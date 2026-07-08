"""Deterministic in-memory Atlas Discovery Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

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

    def discover(
        self,
        raw_outputs: Mapping[str, str],
        *,
        management_ip_hint: str | None = None,
    ) -> DiscoveryResult:
        if not isinstance(raw_outputs, Mapping):
            raise TypeError("raw_outputs must be a command-to-text mapping")
        if not all(isinstance(command, str) and isinstance(output, str) for command, output in raw_outputs.items()):
            raise TypeError("raw_outputs keys and values must be strings")
        if management_ip_hint is not None and not isinstance(management_ip_hint, str):
            raise TypeError("management_ip_hint must be a string or None")
        normalized = dict(raw_outputs)
        optional = frozenset(getattr(self._adapter, "optional_commands", ()) or ())
        for command in self._adapter.required_commands:
            output = normalized.get(command)
            if not isinstance(output, str) or not output.strip():
                if command in optional:
                    # Optional data may legitimately be absent (e.g. CDP disabled).
                    normalized[command] = output if isinstance(output, str) else ""
                    continue
                raise MissingCommandOutputError(f"required command output is missing: {command}")

        if management_ip_hint is None:
            device = self._adapter.parse_inventory(normalized)
        else:
            device = self._adapter.parse_inventory(
                normalized, management_ip_hint=management_ip_hint
            )
        interfaces = self._adapter.parse_interfaces(normalized)
        neighbors = tuple(
            neighbor
            if neighbor.local_device_id == device.device_id
            else replace(neighbor, local_device_id=device.device_id)
            for neighbor in self._adapter.parse_neighbors(normalized)
        )
        warnings = list(device.metadata.get("parse_warnings", ()))
        if not interfaces:
            warnings.append(
                "no interfaces were parsed from 'show ip interface brief'; "
                "the device output may not match the parser yet"
            )
        facts = (
            DiscoveryFact("inventory", "show version", {"device_id": device.device_id}),
            DiscoveryFact("interfaces", "show ip interface brief", {"count": len(interfaces)}),
            DiscoveryFact("neighbors", "show cdp neighbors detail", {"count": len(neighbors)}),
        )
        metadata: dict[str, object] = {
            "transport": "none",
            "deterministic": True,
            "persistence": False,
        }
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return DiscoveryResult(
            device=device,
            interfaces=interfaces,
            neighbors=neighbors,
            facts=facts,
            adapter_vendor=self._adapter.vendor,
            platform_family=self._adapter.platform_family,
            metadata=metadata,
        )
