"""Immutable configuration intelligence models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SEVERITY_ORDER = ("high", "medium", "low")

CATEGORY_INTERFACES = "interfaces"
CATEGORY_ROUTING = "routing"
CATEGORY_OSPF = "ospf"
CATEGORY_BGP = "bgp"
CATEGORY_STATIC_ROUTES = "static-routes"
CATEGORY_VLANS = "vlans"
CATEGORY_ACLS = "acls"
CATEGORY_NAT = "nat"
CATEGORY_LOGGING = "logging"
CATEGORY_SNMP = "snmp"
CATEGORY_NTP = "ntp"
CATEGORY_AAA = "aaa"
CATEGORY_LINE_ACCESS = "line-access"
CATEGORY_OTHER = "other"


@dataclass(frozen=True)
class ConfigChange:
    """One classified configuration change; line content is already masked."""

    hostname: str
    category: str
    severity: str
    summary: str
    recommendation: str
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]
    raw_diff_reference: str

    def __post_init__(self) -> None:
        for name in ("hostname", "category", "summary", "recommendation", "raw_diff_reference"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"severity must be one of {SEVERITY_ORDER}")
        for name in ("added_lines", "removed_lines"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"{name} must be a tuple of strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "category": self.category,
            "severity": self.severity,
            "summary": self.summary,
            "recommendation": self.recommendation,
            "added_lines": list(self.added_lines),
            "removed_lines": list(self.removed_lines),
            "raw_diff_reference": self.raw_diff_reference,
        }


@dataclass(frozen=True)
class ConfigChangeReport:
    """Deterministic classified comparison of two device configurations."""

    hostname: str
    previous_ref: str
    current_ref: str
    changes: tuple[ConfigChange, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(change, ConfigChange) for change in self.changes):
            raise ValueError("changes must contain only ConfigChange values")
        ordered = tuple(
            sorted(
                self.changes,
                key=lambda change: (
                    SEVERITY_ORDER.index(change.severity),
                    change.category,
                    change.raw_diff_reference.casefold(),
                    change.summary,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "previous_ref": self.previous_ref,
            "current_ref": self.current_ref,
            "change_count": self.change_count,
            "severity_counts": self.severity_counts,
            "category_counts": self.category_counts,
            "changes": [change.to_dict() for change in self.changes],
            "secrets_masked": True,
        }
