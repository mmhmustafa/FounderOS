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
# PR-181: the device answered, and Atlas could not positively confirm the
# reply is a configuration. Distinct from UNSUPPORTED (the device refused)
# and from EMPTY (the device said nothing) — this is the fail-closed verdict.
STATUS_UNRECOGNISED = "unrecognised"

COLLECTION_COMPLETE = "complete"
COLLECTION_PARTIAL = "partial"

# PR-181: honest whole-collection outcomes for a device whose running
# configuration was NOT collected. These reuse the command-outcome
# vocabulary above — deliberately not a new status system. An artifact in
# one of these states carries no running_config; it carries the verdict,
# the command(s) attempted, and the device's raw reply as forensic
# evidence only.
NON_COLLECTED_STATUSES = frozenset({
    STATUS_UNSUPPORTED,
    STATUS_DENIED,
    STATUS_UNRECOGNISED,
    STATUS_EMPTY,
    STATUS_FAILED,
})

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
    # PR-181 provenance: the command that actually produced (or was asked
    # for) the running configuration. None on legacy artifacts.
    command_used: str | None = None
    # PR-181: for NON-collected outcomes only — the device's actual reply,
    # preserved as forensic evidence. Same sensitivity rules as
    # running_config: never logged, never in metadata; an UNRECOGNISED
    # reply may be a truncated real configuration.
    raw_reply: str = ""
    # PR-181: a safe, operator-facing reason for a non-collected outcome.
    detail: str = ""

    def __post_init__(self) -> None:
        for name in (
            "device_id", "hostname", "vendor", "platform",
            "os_name", "os_version", "management_ip", "collected_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.status in (COLLECTION_COMPLETE, COLLECTION_PARTIAL):
            if not isinstance(self.running_config, str) or not self.running_config.strip():
                raise ValueError("running_config must be non-empty text")
        elif self.status in NON_COLLECTED_STATUSES:
            # An honest non-collection NEVER pretends to hold configuration.
            if not isinstance(self.running_config, str) or self.running_config.strip():
                raise ValueError(
                    "a non-collected artifact must not carry a running_config"
                )
        else:
            raise ValueError(
                "status must be complete, partial, or an honest "
                "non-collected outcome"
            )
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
    def collected(self) -> bool:
        """Whether this artifact holds a positively confirmed configuration."""

        return self.status in (COLLECTION_COMPLETE, COLLECTION_PARTIAL)

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
            "running_config_lines": (
                self.running_config.count("\n") + 1 if self.collected else 0
            ),
            "running_config_sha256": (
                self.running_config_sha256 if self.collected else None
            ),
            "read_only": True,
        }
