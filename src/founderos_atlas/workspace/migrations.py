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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_FILENAME = "workspace-schema.json"


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    # (workspace_root, backup_dir, context). ``context`` carries facts
    # some migrations need beyond the workspace tree — today only
    # ``output_dir`` (where discovery artifacts live), for v3's scope
    # attribution. Migrations that do not need it ignore it.
    apply: Callable[[Path, Path, Mapping[str, Any]], None]


def _backup(workspace_root: Path, backup_dir: Path, filename: str) -> None:
    source = workspace_root / filename
    if source.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup_dir / filename)


def _migrate_1_revisions(
    workspace_root: Path, backup_dir: Path, context: Mapping[str, Any]
) -> None:
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


def _migrate_2_display_default(
    workspace_root: Path, backup_dir: Path, context: Mapping[str, Any]
) -> None:
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


_CHANGE_ANNOTATION_KINDS = (
    "change-ack", "change-assignment", "change-note", "change-suppression",
)


def _live_scope_dirs(
    workspace_root: Path, output_dir: Path
) -> dict[str, Path]:
    """scope_id -> artifact directory, for every scope that can render.

    Scopes are the saved profiles (from the workspace's profiles.json —
    archived included, their artifacts are still theirs) plus the legacy
    default scope at the output root. Orphan artifact directories with
    no profile are deliberately EXCLUDED: nothing renders them, so
    attributing an annotation there would hide operator state.
    """

    scopes: dict[str, Path] = {"default": output_dir}
    profiles_path = workspace_root / "profiles.json"
    if profiles_path.is_file():
        try:
            document = json.loads(profiles_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = {}
        for entry in document.get("profiles") or ():
            profile_id = str((entry or {}).get("profile_id") or "").strip()
            if profile_id:
                scopes[profile_id] = (
                    output_dir / ".atlas" / "profiles" / profile_id
                )
    return scopes


def _migrate_3_scoped_change_annotations(
    workspace_root: Path, backup_dir: Path, context: Mapping[str, Any]
) -> None:
    """Converge legacy change annotations onto scoped v2 subjects.

    PR-178.2A. Pre-isolation subjects (``change:<hash>``) are scope-
    blind: the identical delta in two networks shared one record, so an
    action in one scope silently changed the other. The runtime fix is
    in the write/read paths (v2 writes, read-only v1 fallback) and does
    NOT depend on this migration — this pass only MOVES the legacy
    records whose owning scope is provable, shrinking the fallback set.

    Classification per stored legacy subject, per annotation kind,
    against the change content each live scope currently reports:

    - UNAMBIGUOUS (exactly one scope) → MOVED to that scope's v2 key.
      The v1 key is removed — retaining it would let a future scope
      with the same delta fall back to it and reopen the leak.
    - AMBIGUOUS (2+ scopes) → LEFT under the v1 key. Copying would
      invent an operator decision; the record keeps serving through the
      read fallback and decays per scope on the first action there.
    - UNRESOLVABLE (0 scopes) → LEFT. History may still need it.
    - An existing v2 record at the destination is NEVER overwritten —
      newer scoped operator state wins; the legacy record stays (fully
      shadowed in its one scope).

    Without an ``output_dir`` in the context nothing can be attributed:
    the migration resolves nothing, touches nothing, and says so in its
    summary event. The runtime fallback keeps the product correct.
    """

    path = workspace_root / "annotations.json"
    if not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # corruption is verify_workspace's business, not ours
    annotations = document.get("annotations") or {}
    legacy_by_kind = {
        kind: [
            subject for subject in (annotations.get(kind) or {})
            if subject.startswith("change:")
            and not subject.startswith("change:v2:")
        ]
        for kind in _CHANGE_ANNOTATION_KINDS
    }
    if not any(legacy_by_kind.values()):
        return  # nothing legacy — new workspaces stop here

    from founderos_atlas.change.identity import subject_v2_for_hash

    counts: dict[str, dict[str, int]] = {
        kind: {"moved": 0, "ambiguous": 0, "unresolvable": 0,
               "kept_existing_v2": 0, "unattributed": 0}
        for kind, subjects in legacy_by_kind.items() if subjects
    }
    moves: list[tuple[str, str, str, str]] = []
    output_dir = (context or {}).get("output_dir")

    if output_dir is None:
        # No artifact tree to classify against: resolve nothing, guess
        # nothing. The summary says exactly that.
        for kind, subjects in legacy_by_kind.items():
            if subjects:
                counts[kind]["unattributed"] = len(subjects)
        note = "no output directory available — nothing was attributed"
    else:
        from founderos_atlas.change.explorer import unified_rows
        from founderos_atlas.change.identity import content_hash

        def load(report_path: Path):
            if not report_path.is_file():
                return None
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None

        hashes_by_scope: dict[str, set[str]] = {}
        for scope_id, scope_dir in _live_scope_dirs(
            workspace_root, Path(output_dir)
        ).items():
            rows = unified_rows(
                topology_report=load(scope_dir / "change_report.json"),
                config_report=load(scope_dir / "config_change_report.json"),
                state_report=load(scope_dir / "state_change_report.json"),
                scope_id=scope_id,
            )
            hashes_by_scope[scope_id] = {content_hash(row) for row in rows}

        for kind, subjects in legacy_by_kind.items():
            for subject in subjects:
                digest = subject[len("change:"):]
                owners = [
                    scope_id
                    for scope_id, hashes in hashes_by_scope.items()
                    if digest in hashes
                ]
                if len(owners) == 1:
                    destination = subject_v2_for_hash(owners[0], digest)
                    if destination in (annotations.get(kind) or {}):
                        counts[kind]["kept_existing_v2"] += 1
                    else:
                        moves.append((kind, subject, destination, owners[0]))
                        counts[kind]["moved"] += 1
                elif owners:
                    counts[kind]["ambiguous"] += 1
                else:
                    counts[kind]["unresolvable"] += 1
        note = "unambiguous legacy records moved to their scoped subject"

    if moves:
        _backup(workspace_root, backup_dir, "annotations.json")
        for kind, old_subject, new_subject, _scope in moves:
            annotations[kind][new_subject] = annotations[kind].pop(old_subject)
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Audit: one summary + one system event per moved record. Historical
    # events are never rewritten; these are NEW events explaining the
    # remap, actor="system"/source="startup" so the chronicle keeps them
    # out of the operator Timeline while /audit retains them.
    try:
        from founderos_atlas.audit import AuditEvent, AuditLog

        log = AuditLog(workspace_root)
        for kind, old_subject, new_subject, scope_id in moves:
            log.append(AuditEvent.create(
                category=kind, operation="migrate",
                subject=new_subject, actor="system", source="startup",
                scope_id=scope_id,
                before={"subject": old_subject},
                after={"subject": new_subject},
                reason=(
                    "unambiguous scope attribution: only this scope "
                    "currently reports this change content"
                ),
            ))
        log.append(AuditEvent.create(
            category="workspace", operation="migrate",
            subject="change-annotation-identity:v3",
            actor="system", source="startup",
            after={"counts": counts, "note": note},
        ))
    except Exception:  # pragma: no cover - audit must not block startup
        pass


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
    Migration(
        version=3,
        description=(
            "scoped change-annotation identity (unambiguous legacy "
            "records move to change:v2:<scope>:<hash>)"
        ),
        apply=_migrate_3_scoped_change_annotations,
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


def migrate_workspace(
    workspace_root: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> list[str]:
    """Apply pending migrations; returns the descriptions applied.

    ``output_dir`` is where discovery artifacts live — a DIFFERENT tree
    from the workspace. Migrations that classify against current
    artifacts (v3) receive it via the context; when it is absent they
    resolve nothing and stay safe, because runtime correctness never
    depends on a migration completing (PR-178.2A §12).
    """

    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    context: dict[str, Any] = {
        "output_dir": Path(output_dir) if output_dir is not None else None,
    }
    current = applied_version(root)
    applied: list[str] = []
    for migration in sorted(MIGRATIONS, key=lambda item: item.version):
        if migration.version <= current:
            continue
        backup_dir = root / "migration-backups" / f"v{migration.version}"
        migration.apply(root, backup_dir, context)
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
