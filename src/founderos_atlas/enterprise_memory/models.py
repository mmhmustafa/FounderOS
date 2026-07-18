"""Enterprise Memory models (PR-045, MEMORY).

Atlas can say what the network looks like *now*; Enterprise Memory is the
durable layer that lets it also say what it looked like before, what was
collected, and when. This module defines the immutable records that layer
stores.

Three design commitments shape every model here:

1. **Collection is separated from interpretation.** Raw evidence is the exact
   bytes a device returned. It is preserved even if today's parser cannot
   fully understand it, so a future parser can reprocess history without
   reconnecting to a single device.
2. **Everything is content-addressed and immutable.** A record's identity is
   the SHA-256 of its content. Identical content is stored once; a record is
   never modified in place.
3. **The store is source-agnostic.** CLI is one evidence *source*; the same
   records describe a future Syslog line, SNMP walk, or telemetry frame
   without redesigning Enterprise Memory.

No model here holds a secret in its metadata. Raw output that contains a
credential (a ``show running-config``) lives only in the local, sensitive
blob store; every metadata field is credential-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from founderos_atlas.release import VERSION


# The parser generation that interpreted evidence at collection time. Stamped
# on every record so a later reprocessing pass knows which parser produced the
# derived view, and can decide what to re-derive. Bump when the parsers change
# in a way that could change interpretation of stored raw evidence.
PARSER_VERSION = "2026.07"

# The Atlas build that collected the evidence. Recorded on evidence and
# snapshots so history can be attributed to the software that produced it —
# a future reprocessing pass can tell "collected by an older Atlas" apart.
ATLAS_VERSION = VERSION

# How the evidence was collected. Reserved values name future transports so
# the field never needs widening.
TRANSPORT_SSH = "ssh"
TRANSPORT_SNMP = "snmp"            # future
TRANSPORT_NETCONF = "netconf"     # future
TRANSPORT_RESTCONF = "restconf"   # future
TRANSPORT_HTTP = "http"           # future
TRANSPORT_STREAM = "streaming"    # future


# -- evidence sources (extensibility: design requirement #4) -----------------

SOURCE_CLI = "cli"
SOURCE_SYSLOG = "syslog"          # future
SOURCE_SNMP = "snmp"              # future
SOURCE_NETFLOW = "netflow"        # future
SOURCE_TELEMETRY = "telemetry"    # future

# Collection outcomes for one piece of evidence.
COLLECTION_OK = "collected"
COLLECTION_EMPTY = "empty"
COLLECTION_UNAVAILABLE = "unavailable"
COLLECTION_ERROR = "error"

# Discovery session lifecycle.
SESSION_RUNNING = "running"
SESSION_COMPLETED = "completed"
SESSION_FAILED = "failed"
SESSION_INTERRUPTED = "interrupted"

# Discovery modes.
MODE_SEED = "seed"
MODE_CIDR = "cidr"
MODE_IMPORTED = "imported"


def content_sha256(text: str) -> str:
    """The content address of a blob's text. Newline-normalized so the same
    logical content hashes identically across platforms."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8")).hexdigest()


def evidence_blob_id(digest: str) -> str:
    return f"atlas-evidence:{digest}"


def snapshot_id_for(digest: str) -> str:
    return f"atlas-snapshot:{digest}"


# -- discovery session -------------------------------------------------------


@dataclass(frozen=True)
class DiscoverySession:
    """One discovery run, as a first-class, immutable object.

    This is the spine of Enterprise Memory: every piece of raw evidence and
    every configuration snapshot references the session that produced it.
    """

    session_id: str
    network: str
    profile_id: str
    profile_name: str
    started_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None
    user: str = "local-operator"
    credential_ref: str | None = None       # reference only — never a secret
    mode: str = MODE_SEED
    seeds: tuple[str, ...] = ()
    cidr: str | None = None
    device_count: int = 0
    authenticated_count: int = 0
    configuration_count: int = 0
    evidence_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    status: str = SESSION_RUNNING
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "network": self.network,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "user": self.user,
            "credential_ref": self.credential_ref,
            "mode": self.mode,
            "seeds": list(self.seeds),
            "cidr": self.cidr,
            "device_count": self.device_count,
            "authenticated_count": self.authenticated_count,
            "configuration_count": self.configuration_count,
            "evidence_count": self.evidence_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "status": self.status,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoverySession":
        return cls(
            session_id=str(value["session_id"]),
            network=str(value.get("network") or ""),
            profile_id=str(value.get("profile_id") or ""),
            profile_name=str(value.get("profile_name") or ""),
            started_at=str(value.get("started_at") or ""),
            completed_at=value.get("completed_at"),
            duration_seconds=value.get("duration_seconds"),
            user=str(value.get("user") or "local-operator"),
            credential_ref=value.get("credential_ref"),
            mode=str(value.get("mode") or MODE_SEED),
            seeds=tuple(value.get("seeds") or ()),
            cidr=value.get("cidr"),
            device_count=int(value.get("device_count") or 0),
            authenticated_count=int(value.get("authenticated_count") or 0),
            configuration_count=int(value.get("configuration_count") or 0),
            evidence_count=int(value.get("evidence_count") or 0),
            error_count=int(value.get("error_count") or 0),
            warning_count=int(value.get("warning_count") or 0),
            status=str(value.get("status") or SESSION_RUNNING),
            detail=value.get("detail"),
        )


# -- raw evidence ------------------------------------------------------------


@dataclass(frozen=True)
class RawEvidenceRecord:
    """One collected command's provenance — never its output.

    The output lives, compressed, in the content-addressed blob store keyed by
    ``content_sha256``. This record says *what* was collected, *when*, *from
    where*, and *how it went* — all credential-free, so the index is safe to
    read and serve. Immutable: a command re-run that returns identical output
    adds an observation, never a second record or a second blob.
    """

    device_id: str
    hostname: str
    command: str
    source: str                       # cli | syslog | snmp | …
    collected_at: str                 # Atlas timestamp: when Atlas recorded it
    collection_status: str            # the command's exit status
    parser_version: str
    discovery_session: str
    content_sha256: str               # "" when nothing was captured
    byte_size: int = 0
    stored_bytes: int = 0             # compressed size actually written
    detail: str | None = None
    # Strengthened provenance (PR-045R): enough to reprocess this evidence
    # later without ever reconnecting to the device.
    transport: str = TRANSPORT_SSH
    platform: str | None = None
    software_version: str | None = None
    platform_driver: str | None = None
    atlas_version: str = ATLAS_VERSION
    collection_duration_ms: int | None = None   # reserved (not captured yet)
    prompt: str | None = None                    # reserved (not captured yet)
    # Source-specific extras for future evidence sources (SNMP OIDs, syslog
    # facility, telemetry path…) — so a new source never needs a model change.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence_id(self) -> str:
        return evidence_blob_id(self.content_sha256) if self.content_sha256 else ""

    @property
    def captured(self) -> bool:
        return bool(self.content_sha256)

    @property
    def exit_status(self) -> str:
        """Alias: collection_status IS the command's exit status."""

        return self.collection_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "command": self.command,
            "source": self.source,
            "collected_at": self.collected_at,
            "collection_status": self.collection_status,
            "exit_status": self.collection_status,
            "parser_version": self.parser_version,
            "discovery_session": self.discovery_session,
            "content_sha256": self.content_sha256,
            "evidence_id": self.evidence_id,
            "byte_size": self.byte_size,
            "stored_bytes": self.stored_bytes,
            "detail": self.detail,
            "transport": self.transport,
            "platform": self.platform,
            "software_version": self.software_version,
            "platform_driver": self.platform_driver,
            "atlas_version": self.atlas_version,
            "collection_duration_ms": self.collection_duration_ms,
            "prompt": self.prompt,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RawEvidenceRecord":
        return cls(
            device_id=str(value["device_id"]),
            hostname=str(value.get("hostname") or ""),
            command=str(value.get("command") or ""),
            source=str(value.get("source") or SOURCE_CLI),
            collected_at=str(value.get("collected_at") or ""),
            collection_status=str(value.get("collection_status") or COLLECTION_OK),
            parser_version=str(value.get("parser_version") or PARSER_VERSION),
            discovery_session=str(value.get("discovery_session") or ""),
            content_sha256=str(value.get("content_sha256") or ""),
            byte_size=int(value.get("byte_size") or 0),
            stored_bytes=int(value.get("stored_bytes") or 0),
            detail=value.get("detail"),
            transport=str(value.get("transport") or TRANSPORT_SSH),
            platform=value.get("platform"),
            software_version=value.get("software_version"),
            platform_driver=value.get("platform_driver"),
            atlas_version=str(value.get("atlas_version") or ATLAS_VERSION),
            collection_duration_ms=value.get("collection_duration_ms"),
            prompt=value.get("prompt"),
            metadata=dict(value.get("metadata") or {}),
        )


# -- configuration snapshot --------------------------------------------------


@dataclass(frozen=True)
class ConfigurationSnapshot:
    """An immutable configuration snapshot, as a view over one evidence blob.

    A configuration is not stored twice: it *is* the ``show running-config``
    raw evidence, addressed by the same content hash. This record is the
    higher-level index Enterprise Memory keeps over that blob — device,
    session, platform, software version, hostname — so configuration history
    can be answered without re-reading every evidence record.
    """

    snapshot_id: str
    device_id: str
    hostname: str
    discovery_session: str
    captured_at: str
    platform: str
    software_version: str | None
    config_sha256: str
    byte_size: int = 0
    collection_status: str = COLLECTION_OK
    # Strengthened provenance (PR-045R, Part 3). References only — no secrets.
    credential_ref: str | None = None
    discovery_policy: str | None = None
    platform_driver: str | None = None
    atlas_version: str = ATLAS_VERSION
    # A lightweight structural fingerprint (Part 6): counts, not parsing.
    fingerprint: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "discovery_session": self.discovery_session,
            "captured_at": self.captured_at,
            "platform": self.platform,
            "software_version": self.software_version,
            "config_sha256": self.config_sha256,
            "byte_size": self.byte_size,
            "collection_status": self.collection_status,
            "credential_ref": self.credential_ref,
            "discovery_policy": self.discovery_policy,
            "platform_driver": self.platform_driver,
            "atlas_version": self.atlas_version,
            "fingerprint": dict(self.fingerprint) if self.fingerprint else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ConfigurationSnapshot":
        return cls(
            snapshot_id=str(value["snapshot_id"]),
            device_id=str(value["device_id"]),
            hostname=str(value.get("hostname") or ""),
            discovery_session=str(value.get("discovery_session") or ""),
            captured_at=str(value.get("captured_at") or ""),
            platform=str(value.get("platform") or "unknown"),
            software_version=value.get("software_version"),
            config_sha256=str(value.get("config_sha256") or ""),
            byte_size=int(value.get("byte_size") or 0),
            collection_status=str(value.get("collection_status") or COLLECTION_OK),
            credential_ref=value.get("credential_ref"),
            discovery_policy=value.get("discovery_policy"),
            platform_driver=value.get("platform_driver"),
            atlas_version=str(value.get("atlas_version") or ATLAS_VERSION),
            fingerprint=(dict(value["fingerprint"]) if value.get("fingerprint") else None),
        )


# -- observations over a stored blob -----------------------------------------


@dataclass(frozen=True)
class BlobObservation:
    """First/last-seen and reference bookkeeping for a content-addressed blob.

    This is how content-addressed storage stays efficient AND honest: when the
    same content is collected again, no second copy is written, but the fact
    that it was seen again — and by which session — is recorded here.
    """

    content_sha256: str
    first_seen: str
    last_seen: str
    observation_count: int
    discovery_sessions: tuple[str, ...]
    stored_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "observation_count": self.observation_count,
            "discovery_sessions": list(self.discovery_sessions),
            "stored_bytes": self.stored_bytes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BlobObservation":
        return cls(
            content_sha256=str(value["content_sha256"]),
            first_seen=str(value.get("first_seen") or ""),
            last_seen=str(value.get("last_seen") or ""),
            observation_count=int(value.get("observation_count") or 1),
            discovery_sessions=tuple(value.get("discovery_sessions") or ()),
            stored_bytes=int(value.get("stored_bytes") or 0),
        )


# -- device memory (aggregate view) ------------------------------------------


@dataclass(frozen=True)
class DeviceMemory:
    """Everything Enterprise Memory holds about one canonical device."""

    device_id: str
    hostname: str
    network: str
    discovery_sessions: tuple[str, ...]
    configuration_snapshots: tuple[ConfigurationSnapshot, ...]
    evidence: tuple[RawEvidenceRecord, ...]

    @property
    def configuration_versions(self) -> int:
        return len({s.config_sha256 for s in self.configuration_snapshots if s.config_sha256})

    @property
    def configuration_count(self) -> int:
        return len(self.configuration_snapshots)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @property
    def observation_count(self) -> int:
        """How many times Atlas has recorded evidence for this device."""

        return len(self.evidence)

    @property
    def latest_configuration(self) -> ConfigurationSnapshot | None:
        ordered = sorted(self.configuration_snapshots, key=lambda s: s.captured_at)
        return ordered[-1] if ordered else None

    @property
    def latest_discovery(self) -> str | None:
        """The most recent discovery session that touched this device."""

        return self.discovery_sessions[-1] if self.discovery_sessions else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "discovery_sessions": list(self.discovery_sessions),
            "configuration_snapshots": [s.to_dict() for s in self.configuration_snapshots],
            "evidence": [e.to_dict() for e in self.evidence],
            "configuration_versions": self.configuration_versions,
            "configuration_count": self.configuration_count,
            "evidence_count": self.evidence_count,
            "observation_count": self.observation_count,
            "latest_discovery": self.latest_discovery,
            "latest_configuration": (
                self.latest_configuration.to_dict()
                if self.latest_configuration
                else None
            ),
        }
