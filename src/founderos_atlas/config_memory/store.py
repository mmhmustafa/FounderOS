"""Content-addressed configuration memory store (PR-044, Parts 2–4).

Layout under the memory root (local, sensitive — same posture as the
existing ``configs/`` artifacts):

    config-memory/
      blobs/<sha256>.txt      the exact configuration text, stored ONCE
      index.json              provenance: devices → versions → observations

Storage rules:

- **Content-addressed**: the blob filename IS the SHA-256 of the text. Two
  devices with byte-identical configuration share one blob; a device that
  reverts to an earlier configuration re-uses the earlier blob.
- **Duplicate suppression** (Part 3): when a device reports the same
  configuration as its current version, Atlas records another *observation*
  — it does not write the text again and does not create a new version.
  ``first_seen`` / ``last_seen`` / ``observation_count`` track the sighting.
- **Provenance only in the index**: ``index.json`` never contains
  configuration text. The text lives only in ``blobs/``.
- **Deterministic**: identity comes from content, never from a clock.

The store is pure local filesystem state and is safe to delete: it is
memory, not evidence of record — a rebuilt store simply starts remembering
again from the next discovery.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .models import (
    CONFIG_MEMORY_SCHEMA_VERSION,
    ConfigObservation,
    ConfigSnapshot,
    ConfigVersion,
    DeviceConfigHistory,
    RECORD_NEW_DEVICE,
    RECORD_NEW_VERSION,
    RECORD_UNCHANGED,
    RecordOutcome,
    config_version_id,
)


INDEX_FILENAME = "index.json"
BLOBS_DIRNAME = "blobs"


def config_sha256(text: str) -> str:
    """The content address of configuration text — the stable identity."""

    return sha256(text.encode("utf-8")).hexdigest()


class ConfigMemoryStore:
    """Versioned, content-addressed memory of device configurations."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    # -- paths ---------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def index_path(self) -> Path:
        return self._root / INDEX_FILENAME

    @property
    def blobs_dir(self) -> Path:
        return self._root / BLOBS_DIRNAME

    def blob_path(self, digest: str) -> Path:
        return self.blobs_dir / f"{digest}.txt"

    # -- reading -------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self.index_path.is_file():
            return {"schema_version": CONFIG_MEMORY_SCHEMA_VERSION, "devices": {}}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": CONFIG_MEMORY_SCHEMA_VERSION, "devices": {}}
        devices = data.get("devices")
        if not isinstance(devices, dict):
            return {"schema_version": CONFIG_MEMORY_SCHEMA_VERSION, "devices": {}}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    def device_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._load()["devices"]))

    def history(self, device_id: str) -> DeviceConfigHistory | None:
        """Every remembered version of one device, oldest → newest."""

        entry = self._load()["devices"].get(device_id)
        if not entry:
            return None
        versions = tuple(
            ConfigVersion.from_dict(item)
            for item in sorted(
                entry.get("versions") or (), key=lambda v: int(v["version"])
            )
        )
        return DeviceConfigHistory(
            device_id=device_id,
            hostname=str(entry.get("hostname") or device_id),
            network=str(entry.get("network") or "unknown"),
            versions=versions,
        )

    def histories(self) -> tuple[DeviceConfigHistory, ...]:
        """Every device Atlas remembers, sorted by hostname."""

        found = [self.history(device_id) for device_id in self.device_ids()]
        return tuple(
            sorted(
                (item for item in found if item is not None),
                key=lambda h: h.hostname.casefold(),
            )
        )

    def config_text(self, digest: str) -> str | None:
        """The exact configuration text for a content address.

        SENSITIVE: this is raw device configuration. Callers that render it
        must mask it (``config_intelligence.mask_line``) first.
        """

        path = self.blob_path(str(digest).strip().casefold())
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def version_text(self, device_id: str, version: int) -> str | None:
        history = self.history(device_id)
        if history is None:
            return None
        found = history.version(version)
        return self.config_text(found.config_sha256) if found else None

    # -- writing -------------------------------------------------------------

    def record(
        self,
        running_config: str,
        *,
        device_id: str,
        hostname: str,
        network: str,
        profile_id: str,
        discovery_session: str,
        collected_at: str,
        platform: str = "unknown",
        vendor: str = "unknown",
        os_name: str = "unknown",
        os_version: str = "unknown",
        management_ip: str = "unknown",
    ) -> RecordOutcome:
        """Remember one collected configuration.

        Identical text as the device's current version → an observation
        only (no new version, no duplicate blob). Different text → a new
        version, with the blob written only if this content address has
        never been stored (it may already exist from another device or an
        earlier version this configuration reverted to).
        """

        if not isinstance(running_config, str) or not running_config.strip():
            raise ValueError("running_config must be non-empty text")
        digest = config_sha256(running_config)
        data = self._load()
        devices = data["devices"]
        entry = devices.get(device_id)
        observation = ConfigObservation(
            observed_at=collected_at,
            discovery_session=discovery_session,
            profile_id=profile_id,
        )

        existing_versions = list((entry or {}).get("versions") or [])
        current = existing_versions[-1] if existing_versions else None

        # Duplicate suppression: same content as the CURRENT version.
        if current is not None and str(current["config_sha256"]) == digest:
            current.setdefault("observations", []).append(observation.to_dict())
            entry["hostname"] = hostname
            entry["network"] = network
            self._write(data)
            return RecordOutcome(
                outcome=RECORD_UNCHANGED,
                device_id=device_id,
                hostname=hostname,
                version=int(current["version"]),
                config_sha256=digest,
                stored_blob=False,
                previous_sha256=digest,
            )

        # A new version (first ever, or the configuration changed).
        next_version = (int(current["version"]) + 1) if current else 1
        snapshot = ConfigSnapshot(
            snapshot_id=config_version_id(digest),
            config_sha256=digest,
            device_id=device_id,
            hostname=hostname,
            network=network,
            profile_id=profile_id,
            platform=platform,
            vendor=vendor,
            os_name=os_name,
            os_version=os_version,
            management_ip=management_ip,
            collected_at=collected_at,
            discovery_session=discovery_session,
            line_count=running_config.count("\n") + 1,
        )
        version = ConfigVersion(
            version=next_version,
            config_sha256=digest,
            snapshot=snapshot,
            observations=(observation,),
        )
        # Content-addressed: write the blob only if this exact text is new.
        stored_blob = self._store_blob(digest, running_config)
        if entry is None:
            entry = {"hostname": hostname, "network": network, "versions": []}
            devices[device_id] = entry
        entry["hostname"] = hostname
        entry["network"] = network
        entry["versions"] = existing_versions + [version.to_dict()]
        data["schema_version"] = CONFIG_MEMORY_SCHEMA_VERSION
        self._write(data)
        return RecordOutcome(
            outcome=RECORD_NEW_DEVICE if current is None else RECORD_NEW_VERSION,
            device_id=device_id,
            hostname=hostname,
            version=next_version,
            config_sha256=digest,
            stored_blob=stored_blob,
            previous_sha256=str(current["config_sha256"]) if current else None,
        )

    def _store_blob(self, digest: str, text: str) -> bool:
        """Write the text once. Returns True when newly stored."""

        path = self.blob_path(digest)
        if path.is_file():
            return False  # already stored — content-addressed dedup
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True

    # -- statistics ----------------------------------------------------------

    def statistics(self) -> dict[str, Any]:
        """Honest storage facts — how much memory is being kept, and how
        much duplication content-addressing avoided."""

        histories = self.histories()
        versions = sum(history.version_count for history in histories)
        observations = sum(history.total_observations for history in histories)
        blobs = (
            sorted(self.blobs_dir.glob("*.txt")) if self.blobs_dir.is_dir() else []
        )
        stored_bytes = sum(path.stat().st_size for path in blobs)
        return {
            "devices": len(histories),
            "versions": versions,
            "observations": observations,
            "unique_configurations": len(blobs),
            "stored_bytes": stored_bytes,
            # Observations that cost no storage because the content was
            # already known (the Part 3 win).
            "deduplicated_observations": max(0, observations - len(blobs)),
        }
