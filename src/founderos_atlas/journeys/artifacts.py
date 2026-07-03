"""Immutable Atlas Journey artifact models and Markdown rendering."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class MorningBrief:
    overall_status: str
    generated_at: str
    summary: str
    device_count: int
    edge_count: int
    new_devices: tuple[str, ...] = ()
    removed_devices: tuple[str, ...] = ()
    changed_devices: tuple[str, ...] = ()
    warnings: tuple[Mapping[str, Any], ...] = ()
    reconciliation_conflicts: tuple[Mapping[str, Any], ...] = ()
    recommendations: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("overall_status", "generated_at", "summary"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        for name in ("device_count", "edge_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("new_devices", "removed_devices", "changed_devices", "recommendations"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
            object.__setattr__(self, name, tuple(sorted(set(values), key=str.casefold)))
        for name in ("warnings", "reconciliation_conflicts"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(isinstance(value, Mapping) for value in values):
                raise ValueError(f"{name} must be a tuple of mappings")
            object.__setattr__(self, name, tuple(_freeze(value) for value in values))
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "device_count": self.device_count,
            "edge_count": self.edge_count,
            "new_devices": list(self.new_devices),
            "removed_devices": list(self.removed_devices),
            "changed_devices": list(self.changed_devices),
            "warnings": _plain(self.warnings),
            "reconciliation_conflicts": _plain(self.reconciliation_conflicts),
            "recommendations": list(self.recommendations),
            "metadata": _plain(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MorningBrief":
        if not isinstance(value, Mapping):
            raise TypeError("MorningBrief value must be a mapping")
        required = {
            "overall_status", "generated_at", "summary", "device_count", "edge_count",
            "new_devices", "removed_devices", "changed_devices", "warnings",
            "reconciliation_conflicts", "recommendations", "metadata",
        }
        if set(value) != required:
            raise ValueError("MorningBrief value must contain exactly the declared fields")
        return cls(
            overall_status=value["overall_status"],
            generated_at=value["generated_at"],
            summary=value["summary"],
            device_count=value["device_count"],
            edge_count=value["edge_count"],
            new_devices=tuple(value["new_devices"]),
            removed_devices=tuple(value["removed_devices"]),
            changed_devices=tuple(value["changed_devices"]),
            warnings=tuple(value["warnings"]),
            reconciliation_conflicts=tuple(value["reconciliation_conflicts"]),
            recommendations=tuple(value["recommendations"]),
            metadata=value["metadata"],
        )

    def to_markdown(self) -> str:
        def names(values: tuple[str, ...]) -> str:
            return "\n".join(f"- {value}" for value in values) if values else "- None"

        recommendations = (
            "\n".join(f"- {value}" for value in self.recommendations)
            if self.recommendations else "- No immediate action required."
        )
        return "\n".join(
            (
                "# Good Morning",
                "",
                "## Network Status",
                "",
                self.overall_status,
                "",
                "## Summary",
                "",
                self.summary,
                "",
                "## Topology",
                "",
                f"- Devices: {self.device_count}",
                f"- Connections: {self.edge_count}",
                "",
                "## Changes Since Previous Snapshot",
                "",
                f"- New devices: {len(self.new_devices)}",
                f"- Removed devices: {len(self.removed_devices)}",
                f"- Changed devices: {len(self.changed_devices)}",
                "",
                "### New Devices",
                "",
                names(self.new_devices),
                "",
                "### Removed Devices",
                "",
                names(self.removed_devices),
                "",
                "### Changed Devices",
                "",
                names(self.changed_devices),
                "",
                "## Warnings",
                "",
                str(len(self.warnings)),
                "",
                "## Reconciliation Conflicts",
                "",
                str(len(self.reconciliation_conflicts)),
                "",
                "## Recommendations",
                "",
                recommendations,
                "",
                "## Generation",
                "",
                f"Generated at: {self.generated_at}",
                "",
            )
        )
