"""Immutable operational state intelligence models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SEVERITY_ORDER = ("high", "medium", "low")

FIELD_STATUS = "status"
FIELD_PROTOCOL = "protocol"
FIELD_IP = "ip_address"
FIELD_INTERFACE = "interface"

CHANGE_MODIFIED = "modified"
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"


@dataclass(frozen=True)
class StateChange:
    """One operational change on one interface between two discoveries."""

    hostname: str
    interface: str
    field: str
    severity: str
    change_type: str
    description: str
    recommendation: str
    previous_value: str | None = None
    current_value: str | None = None

    def __post_init__(self) -> None:
        for name in ("hostname", "interface", "field", "severity", "change_type",
                     "description", "recommendation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"severity must be one of {SEVERITY_ORDER}")

    @property
    def is_interface_down(self) -> bool:
        return (
            self.field in (FIELD_STATUS, FIELD_PROTOCOL)
            and self.current_value is not None
            and self.current_value.casefold() in ("down", "administratively_down")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "interface": self.interface,
            "field": self.field,
            "severity": self.severity,
            "change_type": self.change_type,
            "description": self.description,
            "recommendation": self.recommendation,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
        }


@dataclass(frozen=True)
class StateChangeReport:
    """Deterministic operational comparison of two topology snapshots."""

    previous_ref: str
    current_ref: str
    changes: tuple[StateChange, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(change, StateChange) for change in self.changes):
            raise ValueError("changes must contain only StateChange values")
        ordered = tuple(
            sorted(
                self.changes,
                key=lambda change: (
                    SEVERITY_ORDER.index(change.severity),
                    change.hostname.casefold(),
                    change.interface.casefold(),
                    change.field,
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
    def devices_changed(self) -> tuple[str, ...]:
        return tuple(
            sorted({change.hostname for change in self.changes}, key=str.casefold)
        )

    @property
    def interfaces_down(self) -> int:
        """Distinct interfaces that went down (an admin-shut interface whose
        status and protocol both drop counts once, not twice)."""

        return len(
            {
                (change.hostname.casefold(), change.interface.casefold())
                for change in self.changes
                if change.is_interface_down
            }
        )

    @property
    def status(self) -> str:
        return "Attention Required" if self.changes else "Healthy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_ref": self.previous_ref,
            "current_ref": self.current_ref,
            "change_count": self.change_count,
            "severity_counts": self.severity_counts,
            "devices_changed": list(self.devices_changed),
            "interfaces_down": self.interfaces_down,
            "status": self.status,
            "changes": [change.to_dict() for change in self.changes],
        }
