"""The Atlas history repository: every discovery is preserved, none replaced.

The repository is deliberately artifact-oriented so future capabilities —
configuration diff, incident replay, historical topology playback, AI
reasoning — read records without a storage redesign: each record directory
is self-describing (``discovery_metadata.json``) and carries full copies of
the run's artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DiscoveryRecord
from .storage import HistoryStorage


DEFAULT_HISTORY_ROOT = Path(".atlas") / "history"


@dataclass(frozen=True)
class HistoryIndex:
    """Loaded history: valid records newest-first plus non-fatal issues."""

    records: tuple[DiscoveryRecord, ...]
    issues: tuple[str, ...]

    @property
    def latest(self) -> DiscoveryRecord | None:
        return self.records[0] if self.records else None


class HistoryRepository:
    def __init__(self, root: str | Path = DEFAULT_HISTORY_ROOT) -> None:
        self._storage = HistoryStorage(root)

    @property
    def root(self) -> Path:
        return self._storage.root

    def save_discovery(
        self,
        *,
        started_at: str,
        completed_at: str,
        duration_seconds: float,
        device_count: int,
        relationship_count: int,
        warning_count: int,
        failures: tuple[str, ...],
        configuration_status: str,
        configured_device_count: int,
        quality_score: float,
        network_status: str,
        snapshot_id: str,
        artifacts: Mapping[str, str | Path] | None = None,
        config_directories: Mapping[str, str | Path] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DiscoveryRecord:
        """Preserve one discovery: allocate, copy artifacts, write metadata."""

        record_dir = self._storage.allocate_record_dir(started_at)
        copied: list[str] = []
        for name, source in sorted((artifacts or {}).items()):
            if self._storage.copy_artifact(record_dir, source, name) is not None:
                copied.append(name)
        for hostname, source in sorted((config_directories or {}).items()):
            if self._storage.copy_directory(record_dir, source, f"configs/{hostname}") is not None:
                copied.append(f"configs/{hostname}")
        record = DiscoveryRecord(
            record_id=record_dir.name,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            device_count=device_count,
            relationship_count=relationship_count,
            warning_count=warning_count,
            failures=failures,
            configuration_status=configuration_status,
            configured_device_count=configured_device_count,
            quality_score=quality_score,
            network_status=network_status,
            snapshot_id=snapshot_id,
            metadata={**dict(metadata or {}), "artifacts": sorted(copied)},
        )
        self._storage.write_metadata(record_dir, record.to_dict())
        return record

    def attach_artifact(
        self, record_id: str, source: str | Path, name: str | None = None
    ) -> Path | None:
        """Copy one more artifact into an existing record (e.g. the dashboard,
        which is regenerated after the record exists so it can list it)."""

        record_dir = self.record_directory(record_id)
        if not record_dir.is_dir():
            return None
        return self._storage.copy_artifact(record_dir, source, name)

    def load(self) -> HistoryIndex:
        """Load all records newest-first; corrupt entries become issues."""

        records: list[DiscoveryRecord] = []
        issues: list[str] = []
        for record_dir in self._storage.record_dirs():
            try:
                data = self._storage.read_metadata(record_dir)
                records.append(DiscoveryRecord.from_dict(data))
            except (OSError, ValueError) as error:
                issues.append(f"{record_dir.name}: could not load ({error})")
        return HistoryIndex(records=tuple(records), issues=tuple(issues))

    def latest(self) -> DiscoveryRecord | None:
        return self.load().latest

    def record_directory(self, record_id: str) -> Path:
        return self._storage.root / record_id

    def snapshot_path(self, record_id: str) -> Path:
        return self.record_directory(record_id) / "topology_snapshot.json"
