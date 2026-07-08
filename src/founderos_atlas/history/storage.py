"""Filesystem layout for the Atlas history repository.

One directory per discovery under the history root, named by start time
(``2026-07-09_23-41-18``), never overwritten: a same-second collision gets a
``-2`` suffix. Files only — no database, no Git, no pruning.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any


METADATA_FILENAME = "discovery_metadata.json"


class HistoryStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def allocate_record_dir(self, started_at: str) -> Path:
        """Create a unique timestamped directory; never overwrites."""

        base = folder_name_for(started_at)
        candidate = self._root / base
        suffix = 2
        while candidate.exists():
            candidate = self._root / f"{base}-{suffix}"
            suffix += 1
        candidate.mkdir(parents=True)
        return candidate

    def record_dirs(self) -> tuple[Path, ...]:
        """Record directories, newest first (names sort chronologically)."""

        if not self._root.is_dir():
            return ()
        return tuple(
            sorted(
                (entry for entry in self._root.iterdir() if entry.is_dir()),
                key=lambda entry: entry.name,
                reverse=True,
            )
        )

    def copy_artifact(self, record_dir: Path, source: str | Path, name: str | None = None) -> Path | None:
        source_path = Path(source)
        if not source_path.is_file():
            return None
        destination = record_dir / (name or source_path.name)
        shutil.copy2(source_path, destination)
        return destination

    def copy_directory(self, record_dir: Path, source: str | Path, name: str) -> Path | None:
        source_path = Path(source)
        if not source_path.is_dir():
            return None
        destination = record_dir / name
        shutil.copytree(source_path, destination)
        return destination

    def write_metadata(self, record_dir: Path, data: dict[str, Any]) -> Path:
        destination = record_dir / METADATA_FILENAME
        destination.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        return destination

    def read_metadata(self, record_dir: Path) -> dict[str, Any]:
        path = record_dir / METADATA_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("discovery metadata must be a JSON object")
        return data


def folder_name_for(started_at: str) -> str:
    """``2026-07-09T23:41:18+00:00`` -> ``2026-07-09_23-41-18``."""

    compact = started_at.strip()[:19].replace("T", "_").replace(":", "-")
    cleaned = "".join(ch for ch in compact if ch.isalnum() or ch in "_-")
    return cleaned or "discovery"
