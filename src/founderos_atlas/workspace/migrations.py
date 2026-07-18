"""Durable, ordered workspace schema migrations.

``workspace-schema.json`` records the applied schema version. At
startup ``migrate_workspace`` applies, in order, every registered
migration newer than the recorded version. Each migration:

- backs the target file up to ``migration-backups/<version>/`` BEFORE
  touching it (restore = copy the file back),
- is idempotent (re-running over migrated data changes nothing),
- appends an audit event describing what ran.

Migrations transform metadata only — never evidence, never secrets.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA_FILENAME = "workspace-schema.json"


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[Path, Path], None]   # (workspace_root, backup_dir)


def _backup(workspace_root: Path, backup_dir: Path, filename: str) -> None:
    source = workspace_root / filename
    if source.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup_dir / filename)


def _migrate_1_revisions(workspace_root: Path, backup_dir: Path) -> None:
    """Stamp explicit revision counters onto pre-RBAC editable records.

    profiles.json and policy-exceptions.json predate optimistic
    concurrency; give each a catalog-level ``revision`` (0) so stale
    edits are detectable from now on. Files that already carry one are
    left untouched.
    """

    for filename in ("profiles.json", "policy-exceptions.json"):
        path = workspace_root / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue  # corruption is verify_workspace's business, not ours
        if isinstance(data, dict) and "revision" not in data:
            _backup(workspace_root, backup_dir, filename)
            data["revision"] = 0
            path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def _migrate_2_display_default(workspace_root: Path, backup_dir: Path) -> None:
    """Existing workspaces keep everything visible by default.

    Progressive disclosure defaults NEW workspaces to the ``simple``
    display level. A workspace that predates the feature has operators
    who already rely on today's full-detail pages, so the upgrade stamps
    ``ux-defaults.json`` with an ``expert`` default — nobody's controls
    disappear on upgrade, and any user can still choose ``simple``.

    "Existing" is judged from prior activity evidence: any workspace
    store already on disk. A brand-new workspace runs this migration
    with an empty directory (only the schema file it is writing) and
    gets no marker — its users honestly start at ``simple``.
    """

    marker = workspace_root / "ux-defaults.json"
    if marker.is_file():
        return  # idempotent
    activity = ("preferences.json", "profiles.json", "users.json",
                "audit.jsonl", "credential-sets.json")
    if not any((workspace_root / name).is_file() for name in activity):
        return
    marker.write_text(
        json.dumps({
            "schema_version": "1.0.0",
            "display_level_default": "expert",
            "reason": (
                "workspace predates progressive disclosure; existing "
                "operators keep full detail by default"
            ),
        }, indent=2) + "\n",
        encoding="utf-8",
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        description="revision counters on profiles and policy exceptions",
        apply=_migrate_1_revisions,
    ),
    Migration(
        version=2,
        description=(
            "expert display-level default for pre-disclosure workspaces"
        ),
        apply=_migrate_2_display_default,
    ),
)

CURRENT_SCHEMA_VERSION = max(
    (migration.version for migration in MIGRATIONS), default=0
)


def applied_version(workspace_root: str | Path) -> int:
    path = Path(workspace_root) / SCHEMA_FILENAME
    if not path.is_file():
        return 0
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("version", 0))
    except (ValueError, TypeError):
        return 0


def migrate_workspace(workspace_root: str | Path) -> list[str]:
    """Apply pending migrations; returns the descriptions applied."""

    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    current = applied_version(root)
    applied: list[str] = []
    for migration in sorted(MIGRATIONS, key=lambda item: item.version):
        if migration.version <= current:
            continue
        backup_dir = root / "migration-backups" / f"v{migration.version}"
        migration.apply(root, backup_dir)
        current = migration.version
        applied.append(f"v{migration.version}: {migration.description}")
        (root / SCHEMA_FILENAME).write_text(
            json.dumps({
                "version": current,
                "migrated_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    if applied:
        try:
            from founderos_atlas.audit import AuditEvent, AuditLog

            AuditLog(root).append(AuditEvent.create(
                category="workspace", operation="migrate",
                subject=f"workspace-schema:v{current}",
                actor="system", source="startup",
                after={"applied": applied},
            ))
        except Exception:  # pragma: no cover - audit must not block startup
            pass
    return applied
