"""Abandoned per-profile artifact directories: find them, set them aside.

Deleting a discovery profile removes the profile record and its
credential reference — deliberately, because the network's knowledge is
a derived view over the profiles that remain. What it has never removed
is the directory of artifacts that profile collected: its snapshots,
captured configurations and run history keep sitting under
``.atlas/profiles/<profile_id>/`` with nothing left that refers to them.

Nothing reads those directories afterwards, so they are inert. They are
also invisible: an operator has no way to see them, no way to know what
they cost, and every reason to suspect them when something looks stale.
That is the actual harm — not corruption, but a hidden pile that draws
blame. This module makes the pile visible and reclaimable.

Conservative by construction:

- a directory is orphaned ONLY when no saved profile claims it, and
  archived profiles still claim theirs — an archived profile is a
  profile, not a leftover;
- anything that is not a profile-id-shaped directory is left alone,
  including Atlas's own ``_archived_orphans_*`` folders, so a second
  sweep never eats the results of the first;
- reclaiming MOVES a directory into a timestamped archive beside the
  profiles; it never deletes. A mistake costs a rename to undo;
- every sweep writes a manifest naming exactly what moved, how big it
  was, and who asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from .scopes import PROFILE_SCOPES_SUBDIR


ORPHAN_ARCHIVE_PREFIX = "_archived_orphans_"
ORPHAN_MANIFEST_NAME = "manifest.json"

# Artifacts worth naming individually when describing what a directory
# still holds, so the operator decides with the contents in view.
_NOTABLE = (
    ("topology_snapshot.json", "topology snapshot"),
    ("configs", "captured configurations"),
    ("history", "discovery history"),
    ("path_investigations.json", "path investigations"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


@dataclass(frozen=True)
class OrphanScope:
    """One artifact directory no saved profile claims."""

    scope_id: str
    path: Path
    size_bytes: int
    file_count: int
    last_modified: str | None
    holds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 1),
            "file_count": self.file_count,
            "last_modified": self.last_modified,
            "holds": list(self.holds),
        }


def find_orphan_scopes(
    base_output_dir: str | Path, profiles
) -> tuple[OrphanScope, ...]:
    """Artifact directories with no profile left to claim them.

    ``profiles`` must include archived profiles: an archived profile is
    still a profile, and its artifacts are not abandoned. Callers that
    pass only the active ones would propose deleting live data.
    """

    root = Path(base_output_dir) / PROFILE_SCOPES_SUBDIR
    if not root.is_dir():
        return ()
    claimed = {
        str(getattr(profile, "profile_id", "") or "").strip()
        for profile in profiles or ()
    }
    claimed.discard("")
    found: list[OrphanScope] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        # Atlas's own archives live beside the scopes; sweeping them
        # again would bury the results of the previous sweep.
        if entry.name.startswith(ORPHAN_ARCHIVE_PREFIX):
            continue
        if entry.name in claimed:
            continue
        files = [item for item in entry.rglob("*") if item.is_file()]
        newest: float | None = None
        size = 0
        for item in files:
            try:
                stat = item.stat()
            except OSError:
                continue
            size += stat.st_size
            if newest is None or stat.st_mtime > newest:
                newest = stat.st_mtime
        holds = tuple(
            label for name, label in _NOTABLE if (entry / name).exists()
        )
        found.append(
            OrphanScope(
                scope_id=entry.name,
                path=entry,
                size_bytes=size,
                file_count=len(files),
                last_modified=(
                    datetime.fromtimestamp(newest, timezone.utc)
                    .isoformat(timespec="seconds")
                    if newest is not None else None
                ),
                holds=holds,
            )
        )
    return tuple(found)


def orphan_summary(orphans) -> dict[str, Any]:
    """Counts and totals for the screen, in one shape."""

    items = tuple(orphans)
    total = sum(item.size_bytes for item in items)
    return {
        "count": len(items),
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 1),
        "scopes": [item.to_dict() for item in items],
    }


def archive_orphan_scopes(
    base_output_dir: str | Path,
    scope_ids,
    *,
    actor: str = "unknown",
    profiles=(),
    now: str | None = None,
) -> dict[str, Any]:
    """Move the named directories aside, and write down what moved.

    Re-derives the orphan set rather than trusting the caller's list:
    the screen an operator acted on may be minutes old, and a profile
    created since must not have its artifacts moved out from under it.
    Anything named but no longer orphaned is skipped and reported.
    """

    root = Path(base_output_dir) / PROFILE_SCOPES_SUBDIR
    wanted = [str(item).strip() for item in scope_ids or () if str(item).strip()]
    stamp = (now or _now()).replace(":", "").replace("-", "")
    archive_dir = root / f"{ORPHAN_ARCHIVE_PREFIX}{stamp}"

    current = {item.scope_id: item for item in find_orphan_scopes(
        base_output_dir, profiles
    )}
    moved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for scope_id in wanted:
        orphan = current.get(scope_id)
        if orphan is None:
            skipped.append({
                "scope_id": scope_id,
                "reason": "no longer an unclaimed directory — nothing moved",
            })
            continue
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(orphan.path), str(archive_dir / scope_id))
        except OSError as error:
            errors.append({"scope_id": scope_id, "error": str(error)})
            continue
        moved.append(orphan.to_dict())

    manifest = {
        "archived_at": now or _now(),
        "actor": actor,
        "archive_dir": str(archive_dir),
        "moved": moved,
        "moved_count": len(moved),
        "moved_bytes": sum(item["size_bytes"] for item in moved),
        "skipped": skipped,
        "errors": errors,
    }
    if moved or errors:
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / ORPHAN_MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as error:      # the move is what matters
            manifest["errors"].append(
                {"scope_id": "(manifest)", "error": str(error)}
            )
    return manifest


def list_orphan_archives(base_output_dir: str | Path) -> tuple[dict[str, Any], ...]:
    """Past sweeps, newest first — so "moved aside" stays findable."""

    root = Path(base_output_dir) / PROFILE_SCOPES_SUBDIR
    if not root.is_dir():
        return ()
    archives: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(
            ORPHAN_ARCHIVE_PREFIX
        ):
            continue
        manifest_path = entry / ORPHAN_MANIFEST_NAME
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    manifest = loaded
            except (OSError, json.JSONDecodeError):
                manifest = {}
        archives.append({
            "name": entry.name,
            "path": str(entry),
            "archived_at": manifest.get("archived_at"),
            "actor": manifest.get("actor"),
            "moved_count": manifest.get(
                "moved_count",
                len([item for item in entry.iterdir() if item.is_dir()]),
            ),
            "size_bytes": _dir_size(entry),
            "size_mb": round(_dir_size(entry) / (1024 * 1024), 1),
        })
    archives.sort(key=lambda item: item["name"], reverse=True)
    return tuple(archives)
