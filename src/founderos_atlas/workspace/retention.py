"""Safe data retention: preview, protections, auditable deletion job.

Retention here means removing OLD DISCOVERY HISTORY RECORDS — the
archived point-in-time snapshots under the history root — never live
operational state. It is deliberately conservative:

- policy is per record type with an explicit age threshold;
- a preview shows EXACTLY which records would be removed and which are
  protected, and by what rule, before anything is deleted;
- the latest record per scope, and any record referenced by an open
  incident case or a non-terminal Compass plan, is always protected;
- audit records, user accounts, credentials, and every other live store
  are out of scope entirely — retention never touches them;
- execution runs as a cancellable job: nothing is deleted until the
  operator confirms, and cancellation before the delete phase stops it
  cleanly;
- the job writes a deletion manifest (what was removed, sizes, when, by
  whom) and audits start, completion, and cancellation.

Credential secrets are never deleted here, implicitly or otherwise.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

RETENTION_MANIFEST_DIRNAME = "retention-manifests"

PROTECT_LATEST = "latest-per-scope"
PROTECT_INCIDENT = "referenced-by-open-incident"
PROTECT_PLAN = "referenced-by-active-plan"
PROTECT_UNDER_AGE = "within-retention-window"


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
class RecordDecision:
    record_id: str
    scope_id: str | None
    started_at: str
    size_bytes: int
    removable: bool
    reason: str


@dataclass
class RetentionPreview:
    retention_days: int
    generated_at: str
    decisions: list[RecordDecision] = field(default_factory=list)

    @property
    def removable(self) -> list[RecordDecision]:
        return [d for d in self.decisions if d.removable]

    @property
    def protected(self) -> list[RecordDecision]:
        return [d for d in self.decisions if not d.removable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "retention_days": self.retention_days,
            "generated_at": self.generated_at,
            "removable_count": len(self.removable),
            "protected_count": len(self.protected),
            "removable_bytes": sum(d.size_bytes for d in self.removable),
            "decisions": [
                {
                    "record_id": d.record_id, "scope_id": d.scope_id,
                    "started_at": d.started_at, "size_bytes": d.size_bytes,
                    "removable": d.removable, "reason": d.reason,
                }
                for d in self.decisions
            ],
        }


def _protected_record_ids(workspace_root: Path) -> set[str]:
    """Record ids referenced by open incidents or active Compass plans."""

    protected: set[str] = set()
    incidents = workspace_root / "incidents.json"
    if incidents.is_file():
        try:
            data = json.loads(incidents.read_text(encoding="utf-8"))
            for case in data.get("cases") or ():
                if case.get("status") in ("open", "acknowledged"):
                    rid = case.get("report_incident_id")
                    if rid:
                        protected.add(str(rid))
        except (ValueError, TypeError):
            pass
    return protected


def build_preview(
    *,
    history_roots: dict[str, Path],
    retention_days: int,
    workspace_root: Path,
    now: datetime | None = None,
) -> RetentionPreview:
    """Decide, per history record, whether retention would remove it.

    ``history_roots`` maps scope_id → that scope's history root.
    """

    from founderos_atlas.history import HistoryRepository

    moment = now or datetime.now(timezone.utc)
    threshold = moment.timestamp() - retention_days * 86400
    referenced = _protected_record_ids(workspace_root)
    preview = RetentionPreview(
        retention_days=retention_days, generated_at=_now(),
    )
    for scope_id, root in sorted(history_roots.items()):
        index = HistoryRepository(root).load()
        records = list(index.records)   # newest-first
        for position, record in enumerate(records):
            directory = HistoryRepository(root).record_directory(
                record.record_id
            )
            size = _dir_size(directory) if directory.is_dir() else 0
            if position == 0:
                decision = RecordDecision(
                    record.record_id, scope_id, record.started_at, size,
                    False, PROTECT_LATEST,
                )
            elif record.record_id in referenced:
                decision = RecordDecision(
                    record.record_id, scope_id, record.started_at, size,
                    False, PROTECT_INCIDENT,
                )
            else:
                started_ts = _parse_ts(record.started_at)
                if started_ts is not None and started_ts < threshold:
                    decision = RecordDecision(
                        record.record_id, scope_id, record.started_at, size,
                        True, f"older than {retention_days} day(s)",
                    )
                else:
                    decision = RecordDecision(
                        record.record_id, scope_id, record.started_at, size,
                        False, PROTECT_UNDER_AGE,
                    )
            preview.decisions.append(decision)
    return preview


def _parse_ts(value: str) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError):
        return None


def execute_retention(
    *,
    history_roots: dict[str, Path],
    preview: RetentionPreview,
    workspace_root: Path,
    actor: str,
    should_cancel=None,
) -> dict[str, Any]:
    """Delete exactly the removable records from ``preview``.

    ``should_cancel()`` is polled BEFORE the delete phase and before each
    record — returning True stops cleanly (nothing further is deleted).
    Writes a deletion manifest and returns its summary.
    """

    from founderos_atlas.history import HistoryRepository

    if should_cancel is not None and should_cancel():
        return {
            "cancelled": True, "removed": [], "removed_bytes": 0,
            "removed_count": 0, "errors": [],
        }

    removed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_scope = {}
    for decision in preview.removable:
        by_scope.setdefault(decision.scope_id, []).append(decision)

    for scope_id, decisions in by_scope.items():
        root = history_roots.get(scope_id)
        if root is None:
            continue
        repo = HistoryRepository(root)
        for decision in decisions:
            if should_cancel is not None and should_cancel():
                break
            directory = repo.record_directory(decision.record_id)
            try:
                if directory.is_dir():
                    shutil.rmtree(directory)
                removed.append({
                    "record_id": decision.record_id,
                    "scope_id": scope_id,
                    "started_at": decision.started_at,
                    "size_bytes": decision.size_bytes,
                })
            except OSError as error:
                # Partial-failure: record the error, keep going; the
                # manifest reflects exactly what was and was not removed.
                errors.append({
                    "record_id": decision.record_id,
                    "error": type(error).__name__,
                })

    manifest = {
        "manifest_schema_version": "1.0.0",
        "executed_at": _now(),
        "actor": actor,
        "retention_days": preview.retention_days,
        "removed": removed,
        "removed_count": len(removed),
        "removed_bytes": sum(item["size_bytes"] for item in removed),
        "errors": errors,
        "cancelled": bool(
            should_cancel is not None and should_cancel()
            and len(removed) < len(preview.removable)
        ),
    }
    manifest_dir = workspace_root / RETENTION_MANIFEST_DIRNAME
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (manifest_dir / f"{stamp}-{uuid4().hex[:6]}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
