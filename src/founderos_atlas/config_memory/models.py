"""Configuration Memory models (PR-044, MEMORY).

Discovery answers "what exists right now?". Configuration Memory answers
"what existed yesterday, what changed, and when?" — every successful
collection becomes a durable, versioned historical observation.

Design rules (unchanged from the rest of Atlas):

- **Deterministic**: identity is content-addressed (SHA-256 of the exact
  configuration text). The same text always produces the same version id;
  no clock or randomness enters identity.
- **No secrets in metadata**: configuration TEXT lives only in the local
  content-addressed blob store (treated as sensitive, like the existing
  ``config`` artifacts). Every model here carries provenance only —
  hashes, counts, timestamps, identities — never configuration content.
  Anything rendered from content passes through the existing
  ``config_intelligence.mask_line`` masking first.
- **Evidence-based**: an observation records that a configuration was seen,
  by which discovery session, at which time. Nothing is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CONFIG_MEMORY_SCHEMA_VERSION = "1.0.0"

# A version id is content-addressed, mirroring the topology snapshot scheme.
CONFIG_ID_PREFIX = "atlas-config"


def config_version_id(config_sha256: str) -> str:
    """The canonical, content-addressed id for a configuration version."""

    cleaned = str(config_sha256).strip().casefold()
    if len(cleaned) != 64 or not all(c in "0123456789abcdef" for c in cleaned):
        raise ValueError("config_sha256 must be a 64-character hex digest")
    return f"{CONFIG_ID_PREFIX}:{cleaned}"


@dataclass(frozen=True)
class ConfigObservation:
    """One sighting of a configuration version — the dedup record.

    When a device reports byte-identical configuration on a later
    discovery, Atlas does NOT store the text again and does NOT create a
    new version; it appends one of these instead (Part 3).
    """

    observed_at: str
    discovery_session: str
    profile_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "discovery_session": self.discovery_session,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ConfigObservation":
        return cls(
            observed_at=str(value["observed_at"]),
            discovery_session=str(value.get("discovery_session") or "unrecorded"),
            profile_id=str(value.get("profile_id") or "unknown"),
        )


@dataclass(frozen=True)
class ConfigSnapshot:
    """The provenance of one collected configuration — never its content.

    This is the Part 2 snapshot metadata: everything needed to identify
    WHERE and WHEN a configuration came from, plus its content address.
    """

    snapshot_id: str          # content-addressed: atlas-config:<sha256>
    config_sha256: str
    device_id: str            # canonical device identity
    hostname: str
    network: str              # the logical network (profile name)
    profile_id: str           # the observation point
    platform: str
    vendor: str
    os_name: str
    os_version: str
    management_ip: str
    collected_at: str
    discovery_session: str
    line_count: int

    def __post_init__(self) -> None:
        expected = config_version_id(self.config_sha256)
        if self.snapshot_id != expected:
            raise ValueError(
                "snapshot_id must be the content address of config_sha256"
            )
        for name in ("device_id", "hostname", "network", "collected_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.line_count, int) or self.line_count < 0:
            raise ValueError("line_count must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "config_sha256": self.config_sha256,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "profile_id": self.profile_id,
            "platform": self.platform,
            "vendor": self.vendor,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "management_ip": self.management_ip,
            "collected_at": self.collected_at,
            "discovery_session": self.discovery_session,
            "line_count": self.line_count,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ConfigSnapshot":
        return cls(
            snapshot_id=str(value["snapshot_id"]),
            config_sha256=str(value["config_sha256"]),
            device_id=str(value["device_id"]),
            hostname=str(value["hostname"]),
            network=str(value.get("network") or "unknown"),
            profile_id=str(value.get("profile_id") or "unknown"),
            platform=str(value.get("platform") or "unknown"),
            vendor=str(value.get("vendor") or "unknown"),
            os_name=str(value.get("os_name") or "unknown"),
            os_version=str(value.get("os_version") or "unknown"),
            management_ip=str(value.get("management_ip") or "unknown"),
            collected_at=str(value["collected_at"]),
            discovery_session=str(value.get("discovery_session") or "unrecorded"),
            line_count=int(value.get("line_count") or 0),
        )


@dataclass(frozen=True)
class ConfigVersion:
    """One distinct configuration version of a device (v1, v2, …).

    ``first_seen`` / ``last_seen`` / ``observation_count`` are the Part 3
    dedup facts: a version that keeps being re-observed unchanged grows its
    observation count without duplicating storage.
    """

    version: int
    config_sha256: str
    snapshot: ConfigSnapshot
    observations: tuple[ConfigObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be a positive integer")
        if not self.observations:
            raise ValueError("a version requires at least one observation")

    @property
    def version_id(self) -> str:
        return self.snapshot.snapshot_id

    @property
    def first_seen(self) -> str:
        return min(item.observed_at for item in self.observations)

    @property
    def last_seen(self) -> str:
        return max(item.observed_at for item in self.observations)

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def label(self) -> str:
        return f"v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "label": self.label,
            "config_sha256": self.config_sha256,
            "version_id": self.version_id,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "observation_count": self.observation_count,
            "snapshot": self.snapshot.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ConfigVersion":
        return cls(
            version=int(value["version"]),
            config_sha256=str(value["config_sha256"]),
            snapshot=ConfigSnapshot.from_dict(value["snapshot"]),
            observations=tuple(
                ConfigObservation.from_dict(item)
                for item in value.get("observations") or ()
            ),
        )


@dataclass(frozen=True)
class DeviceConfigHistory:
    """Every configuration version Atlas remembers for one device."""

    device_id: str
    hostname: str
    network: str
    versions: tuple[ConfigVersion, ...]   # oldest → newest (v1 … vN)

    @property
    def latest(self) -> ConfigVersion | None:
        return self.versions[-1] if self.versions else None

    @property
    def version_count(self) -> int:
        return len(self.versions)

    @property
    def total_observations(self) -> int:
        return sum(version.observation_count for version in self.versions)

    def version(self, number: int) -> ConfigVersion | None:
        for item in self.versions:
            if item.version == number:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "version_count": self.version_count,
            "total_observations": self.total_observations,
            "versions": [version.to_dict() for version in self.versions],
        }


# -- record outcomes ---------------------------------------------------------------

RECORD_NEW_DEVICE = "new-device"        # first configuration ever for this device
RECORD_NEW_VERSION = "new-version"      # configuration changed → v+1
RECORD_UNCHANGED = "unchanged"          # identical text → observation only


@dataclass(frozen=True)
class RecordOutcome:
    """What recording one collected configuration did to memory."""

    outcome: str
    device_id: str
    hostname: str
    version: int
    config_sha256: str
    stored_blob: bool          # False when the text was already stored (dedup)
    previous_sha256: str | None = None

    @property
    def changed(self) -> bool:
        return self.outcome in (RECORD_NEW_DEVICE, RECORD_NEW_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "version": self.version,
            "config_sha256": self.config_sha256,
            "stored_blob": self.stored_blob,
            "previous_sha256": self.previous_sha256,
            "changed": self.changed,
        }


# -- timeline ----------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineEvent:
    """One entry on the enterprise configuration change timeline (Part 7).

    ``summary`` is derived from semantic events where available, else a
    plain version transition. Never contains configuration content beyond
    already-masked semantic detail.
    """

    occurred_at: str
    device_id: str
    hostname: str
    network: str
    version: int
    previous_version: int | None
    summary: str
    change_count: int
    discovery_session: str
    highest_severity: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurred_at": self.occurred_at,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "version": self.version,
            "previous_version": self.previous_version,
            "summary": self.summary,
            "change_count": self.change_count,
            "discovery_session": self.discovery_session,
            "highest_severity": self.highest_severity,
        }
