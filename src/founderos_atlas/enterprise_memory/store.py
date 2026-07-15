"""The Enterprise Memory durable store (PR-045, MEMORY).

The long-term persistence layer beneath discovery. It holds three things,
all immutable, all content-addressed where content is involved:

- **Discovery sessions** — one record per discovery run.
- **Raw evidence** — the exact bytes every command returned, gzip-compressed
  in a content-addressed blob store, deduplicated across devices and runs.
- **Configuration snapshots** — an index over the ``show running-config``
  evidence blobs, so configuration history is a first-class query.

Layout under the memory root (one per scope):

```
enterprise-memory/
  sessions.json
  snapshots.json
  evidence/
    records.json
    observations.json
    blobs/<sha256>.gz
```

Immutability is structural: a blob is written once and never rewritten; a
re-collection of identical content writes no second copy and instead records
another *observation* (first/last seen, count, referencing sessions). Raw
output is preserved verbatim — masking is a concern of the *retrieval*
boundary, never of storage, so a future parser reprocessing history sees
exactly what the device said.
"""

from __future__ import annotations

import gzip
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    COLLECTION_EMPTY,
    COLLECTION_OK,
    PARSER_VERSION,
    SOURCE_CLI,
    BlobObservation,
    ConfigurationSnapshot,
    DeviceMemory,
    DiscoverySession,
    RawEvidenceRecord,
    content_sha256,
    snapshot_id_for,
)


class EnterpriseMemoryStore:
    """Durable, immutable, content-addressed Enterprise Memory."""

    def __init__(self, root: Path, *, clock=None) -> None:
        self._root = Path(root)
        self._evidence = self._root / "evidence"
        self._blobs = self._evidence / "blobs"
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- small JSON helpers -----------------------------------------------

    def _read(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def _write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    # -- content-addressed blobs ------------------------------------------

    def _blob_path(self, digest: str) -> Path:
        return self._blobs / f"{digest}.gz"

    def _store_blob(self, digest: str, text: str) -> tuple[bool, int]:
        """Write a blob if it is new. Returns (was_new, stored_bytes).

        Immutable: an existing blob is never rewritten. Compression is gzip.
        """

        path = self._blob_path(digest)
        if path.exists():
            return False, path.stat().st_size
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        # mtime=0 keeps the gzip header deterministic (same content → same
        # bytes on disk), which matters for reproducibility and tests.
        path.write_bytes(_deterministic_gzip(normalized))
        return True, path.stat().st_size

    def blob_text(self, digest: str) -> str | None:
        """Decompress a blob back to its exact original text, or ``None``."""

        if not digest:
            return None
        path = self._blob_path(digest)
        if not path.exists():
            return None
        try:
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, ValueError):
            return None

    def _record_observation(
        self, digest: str, session: str, now: str, stored_bytes: int
    ) -> None:
        """Update first/last-seen bookkeeping for a content blob. Caller holds
        the lock."""

        path = self._evidence / "observations.json"
        data = self._read(path, {})
        entry = data.get(digest)
        if entry is None:
            data[digest] = BlobObservation(
                content_sha256=digest, first_seen=now, last_seen=now,
                observation_count=1, discovery_sessions=(session,),
                stored_bytes=stored_bytes,
            ).to_dict()
        else:
            obs = BlobObservation.from_dict(entry)
            sessions = obs.discovery_sessions
            if session not in sessions:
                sessions = (*sessions, session)
            data[digest] = BlobObservation(
                content_sha256=digest, first_seen=obs.first_seen, last_seen=now,
                observation_count=obs.observation_count + 1,
                discovery_sessions=sessions,
                stored_bytes=obs.stored_bytes or stored_bytes,
            ).to_dict()
        self._write(path, data)

    def observation(self, digest: str) -> BlobObservation | None:
        entry = self._read(self._evidence / "observations.json", {}).get(digest)
        return BlobObservation.from_dict(entry) if entry else None

    # -- discovery sessions ------------------------------------------------

    def begin_session(self, session: DiscoverySession) -> DiscoverySession:
        with self._lock:
            path = self._root / "sessions.json"
            data = self._read(path, [])
            data = [row for row in data if row.get("session_id") != session.session_id]
            data.append(session.to_dict())
            self._write(path, data)
        return session

    def complete_session(self, session: DiscoverySession) -> DiscoverySession:
        """Finalize a session (same id, terminal status). Sessions are records
        of what happened, so the completion write is the one legitimate update
        — it never touches evidence or snapshots."""

        return self.begin_session(session)

    def get_session(self, session_id: str) -> DiscoverySession | None:
        for row in self._read(self._root / "sessions.json", []):
            if row.get("session_id") == session_id:
                return DiscoverySession.from_dict(row)
        return None

    def list_sessions(self) -> tuple[DiscoverySession, ...]:
        rows = self._read(self._root / "sessions.json", [])
        sessions = [DiscoverySession.from_dict(row) for row in rows]
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return tuple(sessions)

    # -- raw evidence ------------------------------------------------------

    def store_evidence(
        self,
        *,
        device_id: str,
        hostname: str,
        command: str,
        output: str | None,
        collection_status: str = COLLECTION_OK,
        discovery_session: str,
        source: str = SOURCE_CLI,
        parser_version: str = PARSER_VERSION,
        detail: str | None = None,
        transport: str = "ssh",
        platform: str | None = None,
        software_version: str | None = None,
        platform_driver: str | None = None,
        metadata: dict | None = None,
    ) -> RawEvidenceRecord:
        """Persist one command's raw output, immutably and deduplicated.

        Empty/unavailable evidence is still recorded (the fact that a command
        produced nothing is itself evidence), but stores no blob. The strong
        provenance (transport, platform, driver, …) travels with the record so
        it can be reprocessed later without reconnecting to the device.
        """

        now = self._now()
        text = output or ""
        common = dict(
            device_id=device_id, hostname=hostname, command=command,
            source=source, collected_at=now, parser_version=parser_version,
            discovery_session=discovery_session, detail=detail,
            transport=transport, platform=platform,
            software_version=software_version, platform_driver=platform_driver,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if text.strip():
                digest = content_sha256(text)
                was_new, stored = self._store_blob(digest, text)
                self._record_observation(digest, discovery_session, now, stored)
                record = RawEvidenceRecord(
                    collection_status=collection_status,
                    content_sha256=digest,
                    byte_size=len(text.encode("utf-8")),
                    stored_bytes=stored if was_new else 0, **common,
                )
            else:
                record = RawEvidenceRecord(
                    collection_status=(
                        collection_status if collection_status != COLLECTION_OK
                        else COLLECTION_EMPTY
                    ),
                    content_sha256="", byte_size=0, stored_bytes=0, **common,
                )
            self._append_record(record)
        return record

    def _append_record(self, record: RawEvidenceRecord) -> None:
        path = self._evidence / "records.json"
        data = self._read(path, [])
        data.append(record.to_dict())
        self._write(path, data)

    def evidence_records(
        self, *, device_id: str | None = None, discovery_session: str | None = None
    ) -> tuple[RawEvidenceRecord, ...]:
        rows = self._read(self._evidence / "records.json", [])
        records = [RawEvidenceRecord.from_dict(row) for row in rows]
        if device_id is not None:
            records = [r for r in records if r.device_id == device_id]
        if discovery_session is not None:
            records = [r for r in records if r.discovery_session == discovery_session]
        return tuple(records)

    def evidence_text(self, digest: str) -> str | None:
        return self.blob_text(digest)

    # -- configuration snapshots ------------------------------------------

    def store_configuration(
        self,
        *,
        device_id: str,
        hostname: str,
        discovery_session: str,
        running_config: str | None,
        platform: str = "unknown",
        software_version: str | None = None,
        collection_status: str = COLLECTION_OK,
        credential_ref: str | None = None,
        discovery_policy: str | None = None,
        platform_driver: str | None = None,
    ) -> ConfigurationSnapshot | None:
        """Record a configuration snapshot over its running-config blob.

        The config text is stored ONCE, as raw evidence (the running-config
        command), so a snapshot never duplicates a blob the evidence store
        already holds. Returns ``None`` when no configuration was captured.
        """

        if not running_config or not running_config.strip():
            return None
        with self._lock:
            digest = content_sha256(running_config)
            was_new, stored = self._store_blob(digest, running_config)
            now = self._now()
            self._record_observation(digest, discovery_session, now, stored)
            from .fingerprint import fingerprint as _fingerprint

            print_ = _fingerprint(running_config)
            snapshot = ConfigurationSnapshot(
                snapshot_id=snapshot_id_for(digest),
                device_id=device_id, hostname=hostname,
                discovery_session=discovery_session, captured_at=now,
                platform=platform, software_version=software_version,
                config_sha256=digest,
                byte_size=len(running_config.encode("utf-8")),
                collection_status=collection_status,
                credential_ref=credential_ref,
                discovery_policy=discovery_policy,
                platform_driver=platform_driver,
                fingerprint=print_.to_dict() if print_ else None,
            )
            path = self._root / "snapshots.json"
            data = self._read(path, [])
            # A snapshot is (device, session, content). The same device
            # reporting identical config in the SAME session is one snapshot;
            # a later session records another (history), even if the content
            # is unchanged — the blob is still shared.
            key = (device_id, discovery_session, digest)
            if not any(
                (row.get("device_id"), row.get("discovery_session"),
                 row.get("config_sha256")) == key
                for row in data
            ):
                data.append(snapshot.to_dict())
                self._write(path, data)
        return snapshot

    def configuration_snapshots(
        self, *, device_id: str | None = None
    ) -> tuple[ConfigurationSnapshot, ...]:
        rows = self._read(self._root / "snapshots.json", [])
        snaps = [ConfigurationSnapshot.from_dict(row) for row in rows]
        if device_id is not None:
            snaps = [s for s in snaps if s.device_id == device_id]
        snaps.sort(key=lambda s: s.captured_at)
        return tuple(snaps)

    def configuration_text(self, digest: str) -> str | None:
        return self.blob_text(digest)

    # -- aggregate views ---------------------------------------------------

    def device_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for record in self.evidence_records():
            if record.device_id not in seen:
                seen.append(record.device_id)
        for snap in self.configuration_snapshots():
            if snap.device_id not in seen:
                seen.append(snap.device_id)
        return tuple(sorted(seen))

    def device_memory(self, device_id: str) -> DeviceMemory | None:
        evidence = self.evidence_records(device_id=device_id)
        snapshots = self.configuration_snapshots(device_id=device_id)
        if not evidence and not snapshots:
            return None
        hostname = ""
        network = ""
        sessions: list[str] = []
        for record in evidence:
            hostname = hostname or record.hostname
            if record.discovery_session not in sessions:
                sessions.append(record.discovery_session)
        for snap in snapshots:
            hostname = hostname or snap.hostname
            if snap.discovery_session not in sessions:
                sessions.append(snap.discovery_session)
        # Network from the owning sessions, best effort.
        for sid in sessions:
            session = self.get_session(sid)
            if session and session.network:
                network = session.network
                break
        return DeviceMemory(
            device_id=device_id, hostname=hostname, network=network,
            discovery_sessions=tuple(sessions),
            configuration_snapshots=snapshots, evidence=evidence,
        )

    def statistics(self) -> dict[str, Any]:
        observations = self._read(self._evidence / "observations.json", {})
        records = self.evidence_records()
        snapshots = self.configuration_snapshots()
        unique_blobs = len(observations)
        total_observations = sum(
            int(v.get("observation_count") or 0) for v in observations.values()
        )
        stored_bytes = sum(int(v.get("stored_bytes") or 0) for v in observations.values())
        return {
            "sessions": len(self.list_sessions()),
            "devices": len(self.device_ids()),
            "evidence_records": len(records),
            "configuration_snapshots": len(snapshots),
            "unique_blobs": unique_blobs,
            "total_observations": total_observations,
            "deduplicated": max(0, total_observations - unique_blobs),
            "stored_bytes": stored_bytes,
        }


def _deterministic_gzip(text: str) -> bytes:
    """gzip bytes with a fixed header, so identical content is byte-identical
    on disk regardless of when it was written (reproducibility, tests)."""

    import io

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as handle:
        handle.write(text.encode("utf-8"))
    return buffer.getvalue()
