"""Immutable change intelligence models for Atlas snapshot comparison."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


SEVERITY_ORDER = ("high", "medium", "low", "info")

CATEGORY_DEVICE = "device"
CATEGORY_HOSTNAME = "hostname"
CATEGORY_MANAGEMENT_IP = "management-ip"
CATEGORY_PLATFORM = "platform"
CATEGORY_OS_VERSION = "os-version"
CATEGORY_INTERFACE = "interface"
CATEGORY_NEIGHBOR = "neighbor"
CATEGORY_DISCOVERY = "discovery"


@dataclass(frozen=True)
class Change:
    """One classified operational change between two snapshots."""

    category: str
    severity: str
    description: str
    recommendation: str
    subject: str
    field: str | None = None
    previous_value: str | None = None
    current_value: str | None = None

    def __post_init__(self) -> None:
        for name in ("category", "severity", "description", "recommendation", "subject"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"severity must be one of {SEVERITY_ORDER}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "recommendation": self.recommendation,
            "subject": self.subject,
            "field": self.field,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
        }


@dataclass(frozen=True)
class ChangeReport:
    """Deterministic comparison outcome between two topology snapshots."""

    previous_snapshot_id: str
    current_snapshot_id: str
    changes: tuple[Change, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(isinstance(change, Change) for change in self.changes):
            raise ValueError("changes must contain only Change values")
        ordered = tuple(
            sorted(
                self.changes,
                key=lambda change: (
                    SEVERITY_ORDER.index(change.severity),
                    change.category,
                    change.subject.casefold(),
                    change.description,
                ),
            )
        )
        object.__setattr__(self, "changes", ordered)

    @property
    def change_count(self) -> int:
        return len(self.changes)

    @property
    def severity_counts(self) -> dict[str, int]:
        counts = {severity: 0 for severity in SEVERITY_ORDER}
        for change in self.changes:
            counts[change.severity] += 1
        return counts

    @property
    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for change in self.changes:
            counts[change.category] = counts.get(change.category, 0) + 1
        return dict(sorted(counts.items()))

    def _device_subjects(self, description_marker: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    change.subject
                    for change in self.changes
                    if change.category == CATEGORY_DEVICE
                    and description_marker in change.description
                },
                key=str.casefold,
            )
        )

    @property
    def new_devices(self) -> tuple[str, ...]:
        return self._device_subjects("was discovered")

    @property
    def removed_devices(self) -> tuple[str, ...]:
        return self._device_subjects("is no longer")

    @property
    def changed_devices(self) -> tuple[str, ...]:
        """Devices with attribute-level changes (not new, removed, or neighbors)."""

        attribute_categories = {
            CATEGORY_HOSTNAME,
            CATEGORY_MANAGEMENT_IP,
            CATEGORY_PLATFORM,
            CATEGORY_OS_VERSION,
            CATEGORY_INTERFACE,
        }
        return tuple(
            sorted(
                {
                    change.subject
                    for change in self.changes
                    if change.category in attribute_categories
                },
                key=str.casefold,
            )
        )

    @property
    def recommendations(self) -> tuple[str, ...]:
        seen: list[str] = []
        for change in self.changes:
            if change.recommendation not in seen:
                seen.append(change.recommendation)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_snapshot_id": self.previous_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "change_count": self.change_count,
            "severity_counts": self.severity_counts,
            "category_counts": self.category_counts,
            "new_devices": list(self.new_devices),
            "removed_devices": list(self.removed_devices),
            "changed_devices": list(self.changed_devices),
            "changes": [change.to_dict() for change in self.changes],
            "metadata": dict(self.metadata),
        }
