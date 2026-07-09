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
        today_lines: tuple[str, ...] = ()
        run = self.metadata.get("run")
        if isinstance(run, Mapping):
            bullets = [
                f"- {run.get('devices', self.device_count)} device(s) discovered",
                f"- {run.get('relationships', self.edge_count)} relationship(s) verified",
            ]
            configured = run.get("configurations_collected")
            if configured:
                bullets.append(f"- Configuration collected from {configured} device(s)")
            interfaces_down = run.get("interfaces_down")
            if interfaces_down:
                bullets.append(f"- {interfaces_down} interface(s) down")
            operational_changes = run.get("operational_changes")
            if operational_changes:
                bullets.append(f"- {operational_changes} operational change(s) detected")
            config_changes = run.get("configuration_changes")
            if config_changes:
                bullets.append(f"- {config_changes} configuration change(s) detected")
            elif config_changes == 0 and run.get("configurations_collected"):
                bullets.append("- No configuration changes detected")
            topology_changes = run.get("topology_changes")
            if topology_changes is not None:
                bullets.append(
                    f"- {topology_changes} topology change(s) detected"
                    if topology_changes
                    else "- No topology changes detected"
                )
            failures = run.get("failures")
            if failures:
                bullets.append(f"- Discovery failed for {failures} host(s)")
            today_lines = ("## Today's Summary", "", *bullets, "")
        generation_lines: tuple[str, ...]
        if isinstance(run, Mapping) and run.get("started_at"):
            generation_lines = (
                f"Started: {run.get('started_at')}",
                f"Completed: {run.get('completed_at', 'unrecorded')}",
                f"Duration: {run.get('duration_seconds', 0)} seconds",
            )
        else:
            generation_lines = (f"Generated at: {self.generated_at}",)
        change_lines: tuple[str, ...] = ()
        change_report = self.metadata.get("change_report")
        if isinstance(change_report, Mapping):
            counts = change_report.get("severity_counts") or {}
            entries = tuple(change_report.get("changes") or ())
            detail_lines = tuple(
                f"- [{str(entry.get('severity', '')).title()}] {entry.get('description')} "
                f"— {entry.get('recommendation')}"
                for entry in entries
            ) or ("- No changes detected.",)
            change_lines = (
                "## Change Intelligence",
                "",
                f"- Changes detected: {change_report.get('change_count', 0)}",
                f"- High: {counts.get('high', 0)} | Medium: {counts.get('medium', 0)} "
                f"| Low: {counts.get('low', 0)} | Info: {counts.get('info', 0)}",
                "",
                *detail_lines,
                "",
            )
        operational_lines: tuple[str, ...] = ()
        operational_report = self.metadata.get("operational_report")
        if isinstance(operational_report, Mapping):
            op_counts = operational_report.get("severity_counts") or {}
            entries = tuple(operational_report.get("changes") or ())
            detail_lines = tuple(
                f"- [{str(entry.get('severity', '')).upper()}] {entry.get('description')} "
                f"— {entry.get('recommendation')}"
                for entry in entries
            ) or ("- No operational changes detected.",)
            operational_lines = (
                "## Operational Changes",
                "",
                f"- Operational changes detected: {operational_report.get('change_count', 0)}",
                f"- Interfaces down: {operational_report.get('interfaces_down', 0)}",
                f"- High: {op_counts.get('high', 0)} | Medium: {op_counts.get('medium', 0)} "
                f"| Low: {op_counts.get('low', 0)}",
                "",
                *detail_lines,
                "",
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
                *today_lines,
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
                *change_lines,
                *operational_lines,
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
                *generation_lines,
                "",
            )
        )
