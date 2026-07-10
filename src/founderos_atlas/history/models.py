"""Immutable Atlas discovery history models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


DISCOVERY_VERSION = "1.0.0"

CONFIG_NOT_REQUESTED = "not_requested"
CONFIG_COLLECTED = "collected"
CONFIG_PARTIAL = "partial"
CONFIG_FAILED = "failed"

_CONFIG_STATUSES = (
    CONFIG_NOT_REQUESTED,
    CONFIG_COLLECTED,
    CONFIG_PARTIAL,
    CONFIG_FAILED,
)


@dataclass(frozen=True)
class DiscoveryRecord:
    """One preserved discovery: the contract of discovery_metadata.json."""

    record_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    device_count: int
    relationship_count: int
    warning_count: int
    failures: tuple[str, ...]
    configuration_status: str
    configured_device_count: int
    quality_score: float
    network_status: str
    snapshot_id: str
    discovery_version: str = DISCOVERY_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Discovery scope (PR-031A). None on records preserved before profile
    # scoping existed — those belong to the default (unscoped) scope.
    profile_id: str | None = None
    profile_name: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "record_id", "started_at", "completed_at", "network_status",
            "snapshot_id", "discovery_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("device_count", "relationship_count", "warning_count", "configured_device_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.duration_seconds, int | float) or self.duration_seconds < 0:
            raise ValueError("duration_seconds must be a non-negative number")
        object.__setattr__(self, "duration_seconds", float(self.duration_seconds))
        if not isinstance(self.quality_score, int | float):
            raise ValueError("quality_score must be a number")
        object.__setattr__(self, "quality_score", float(self.quality_score))
        if self.configuration_status not in _CONFIG_STATUSES:
            raise ValueError(f"configuration_status must be one of {_CONFIG_STATUSES}")
        if not isinstance(self.failures, tuple) or not all(
            isinstance(item, str) for item in self.failures
        ):
            raise ValueError("failures must be a tuple of strings")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        for name in ("profile_id", "profile_name"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be null or a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "device_count": self.device_count,
            "relationship_count": self.relationship_count,
            "warning_count": self.warning_count,
            "failures": list(self.failures),
            "configuration_status": self.configuration_status,
            "configured_device_count": self.configured_device_count,
            "quality_score": self.quality_score,
            "network_status": self.network_status,
            "snapshot_id": self.snapshot_id,
            "discovery_version": self.discovery_version,
            "metadata": dict(self.metadata),
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoveryRecord":
        if not isinstance(value, Mapping):
            raise ValueError("discovery record must be a mapping")
        try:
            return cls(
                record_id=value["record_id"],
                started_at=value["started_at"],
                completed_at=value["completed_at"],
                duration_seconds=value["duration_seconds"],
                device_count=value["device_count"],
                relationship_count=value["relationship_count"],
                warning_count=value["warning_count"],
                failures=tuple(value["failures"]),
                configuration_status=value["configuration_status"],
                configured_device_count=value["configured_device_count"],
                quality_score=value["quality_score"],
                network_status=value["network_status"],
                snapshot_id=value["snapshot_id"],
                discovery_version=value.get("discovery_version", DISCOVERY_VERSION),
                metadata=value.get("metadata", {}),
                profile_id=value.get("profile_id"),
                profile_name=value.get("profile_name"),
            )
        except KeyError as error:
            raise ValueError(f"discovery record is missing field {error}") from error
        except TypeError as error:
            raise ValueError(f"discovery record has an invalid shape: {error}") from error
