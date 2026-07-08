"""Immutable configuration collection models for Atlas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any


STATUS_COLLECTED = "collected"
STATUS_UNSUPPORTED = "unsupported"
STATUS_DENIED = "denied"
STATUS_FAILED = "failed"
STATUS_EMPTY = "empty"

COLLECTION_COMPLETE = "complete"
COLLECTION_PARTIAL = "partial"

METADATA_SCHEMA_VERSION = "1.0.0"


class AtlasConfigurationError(Exception):
    """Base failure for read-only configuration collection."""


class ConfigurationCollectionError(AtlasConfigurationError):
    """The required running configuration could not be collected."""


@dataclass(frozen=True)
class CommandOutcome:
    """What happened to one collection command."""

    command: str
    status: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"command": self.command, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class ConfigurationArtifact:
    """One device's collected configuration plus collection provenance.

    ``running_config`` (and any additional outputs) contain sensitive device
    material. Atlas never logs, prints, or transmits this content; it exists
    only to be written to local artifact files by ``storage``.
    """

    device_id: str
    hostname: str
    vendor: str
    platform: str
    os_name: str
    os_version: str
    management_ip: str
    running_config: str
    additional_outputs: Mapping[str, str] = field(default_factory=dict)
    commands: tuple[CommandOutcome, ...] = ()
    status: str = COLLECTION_COMPLETE
    warnings: tuple[str, ...] = ()
    collected_at: str = "unrecorded"

    def __post_init__(self) -> None:
        for name in (
            "device_id", "hostname", "vendor", "platform",
            "os_name", "os_version", "management_ip", "collected_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.running_config, str) or not self.running_config.strip():
            raise ValueError("running_config must be non-empty text")
        if self.status not in (COLLECTION_COMPLETE, COLLECTION_PARTIAL):
            raise ValueError("status must be complete or partial")
        if not all(isinstance(item, CommandOutcome) for item in self.commands):
            raise ValueError("commands must contain CommandOutcome values")
        if not all(isinstance(item, str) and item.strip() for item in self.warnings):
            raise ValueError("warnings must be non-empty strings")
        object.__setattr__(
            self,
            "additional_outputs",
            MappingProxyType(dict(self.additional_outputs)),
        )

    @property
    def running_config_sha256(self) -> str:
        return sha256(self.running_config.encode("utf-8")).hexdigest()

    def to_metadata_dict(self) -> dict[str, Any]:
        """Collection provenance only — never configuration content."""

        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "platform": self.platform,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "management_ip": self.management_ip,
            "collected_at": self.collected_at,
            "collection_status": self.status,
            "commands": [outcome.to_dict() for outcome in self.commands],
            "warnings": list(self.warnings),
            "running_config_lines": self.running_config.count("\n") + 1,
            "running_config_sha256": self.running_config_sha256,
            "read_only": True,
        }
