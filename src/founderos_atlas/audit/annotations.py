"""Audited operational annotations: ownership, acknowledgements, notes,
suppressions — small keyed facts an operator attaches to a subject.

One store serves every feature that needs "attach X to subject Y with
an audit trail": policy assignment, change acknowledgement/assignment/
annotation/suppression. Each mutation writes a unified audit event with
before/after, so consolidated audit filtering and export cover them all
without feature-specific plumbing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .log import AuditLog
from .models import AuditEvent


ANNOTATIONS_FILENAME = "annotations.json"
ANNOTATIONS_SCHEMA_VERSION = "1.0.0"


class AnnotationStore:
    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root) if workspace_root is not None
            else default_workspace_root()
        )
        resolved = str(self._root.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(resolved, RLock())
        self._audit = AuditLog(self._root)

    @property
    def path(self) -> Path:
        return self._root / ANNOTATIONS_FILENAME

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value.get("annotations") or {})
        except (OSError, ValueError, TypeError,
                json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The annotations file {self.path} could not be read: {error}"
            ) from error

    def get(self, kind: str, subject: str) -> dict[str, Any] | None:
        return (self._load().get(kind) or {}).get(subject)

    def all(self, kind: str) -> dict[str, dict[str, Any]]:
        return dict(self._load().get(kind) or {})

    def set(
        self,
        *,
        kind: str,
        subject: str,
        fields: Mapping[str, Any],
        actor: str = "local-operator",
        reason: str | None = None,
        correlation_id: str | None = None,
        occurred_at: str | None = None,
        scope_id: str = "all",
    ) -> dict[str, Any]:
        stamp = occurred_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        record = {
            **{key: value for key, value in dict(fields).items()
               if value not in (None, "")},
            "updated_at": stamp,
            "updated_by": actor,
        }
        with self._lock:
            data = self._load()
            before = (data.get(kind) or {}).get(subject) or {}
            data.setdefault(kind, {})[subject] = record
            self._write(data)
            self._audit.append(AuditEvent.create(
                category=kind, operation="set" if not before else "update",
                subject=subject, actor=actor, scope_id=scope_id,
                before=before, after=record, reason=reason,
                correlation_id=correlation_id, occurred_at=stamp,
            ))
        return record

    # -- batch mutations (PR-178.2) -----------------------------------------
    #
    # One operator intent over N subjects: ONE read-modify-write of the
    # annotations file and ONE audit block, all events sharing the batch's
    # correlation id. The measured alternative — set()/clear() in a loop —
    # rewrote both files N times (~80x slower at 50 subjects) and could
    # abort halfway. The transaction contract, stated exactly: the
    # annotation write is atomic; the audit block is a second atomic
    # write; if the audit block fails the annotation pre-image is
    # restored and the error propagates. A process death BETWEEN the two
    # writes can still leave an unaudited mutation — the same exposure
    # the single-row path has, reduced from N windows to one.

    def set_many(
        self,
        *,
        kind: str,
        records: Mapping[str, Mapping[str, Any]],
        actor: str = "local-operator",
        reason: str | None = None,
        correlation_id: str | None = None,
        occurred_at: str | None = None,
        scope_ids: Mapping[str, str] | None = None,
        actor_roles=(),
    ) -> tuple[str, ...]:
        """Write ``subject -> fields`` records in one batch; returns the
        subjects written. ``scope_ids`` maps each subject to the scope
        its audit event records (default "all")."""

        if not records:
            return ()
        stamp = occurred_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        scope_ids = dict(scope_ids or {})
        with self._lock:
            data = self._load()
            pre_image = self.path.read_text(encoding="utf-8") \
                if self.path.is_file() else None
            events: list[AuditEvent] = []
            for subject, fields in records.items():
                record = {
                    **{key: value for key, value in dict(fields).items()
                       if value not in (None, "")},
                    "updated_at": stamp,
                    "updated_by": actor,
                }
                before = (data.get(kind) or {}).get(subject) or {}
                data.setdefault(kind, {})[subject] = record
                events.append(AuditEvent.create(
                    category=kind,
                    operation="set" if not before else "update",
                    subject=subject, actor=actor,
                    scope_id=scope_ids.get(subject, "all"),
                    before=before, after=record, reason=reason,
                    correlation_id=correlation_id, occurred_at=stamp,
                    actor_roles=actor_roles,
                ))
            self._write(data)
            self._append_or_restore(events, pre_image)
        return tuple(records)

    def clear_many(
        self,
        *,
        kind: str,
        subjects,
        actor: str = "local-operator",
        reason: str | None = None,
        correlation_id: str | None = None,
        occurred_at: str | None = None,
        scope_ids: Mapping[str, str] | None = None,
        actor_roles=(),
    ) -> tuple[str, ...]:
        """Remove the given subjects' records in one batch; returns the
        subjects actually cleared. A subject already absent at write
        time is skipped (and not audited) — the batch result reports it
        as unchanged rather than failing the others."""

        subjects = [str(subject) for subject in subjects]
        if not subjects:
            return ()
        stamp = occurred_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        scope_ids = dict(scope_ids or {})
        with self._lock:
            data = self._load()
            pre_image = self.path.read_text(encoding="utf-8") \
                if self.path.is_file() else None
            events: list[AuditEvent] = []
            cleared: list[str] = []
            for subject in subjects:
                before = (data.get(kind) or {}).get(subject)
                if before is None:
                    continue
                del data[kind][subject]
                cleared.append(subject)
                events.append(AuditEvent.create(
                    category=kind, operation="clear", subject=subject,
                    actor=actor, scope_id=scope_ids.get(subject, "all"),
                    before=before, after={}, reason=reason,
                    correlation_id=correlation_id, occurred_at=stamp,
                    actor_roles=actor_roles,
                ))
            if data.get(kind) is not None and not data[kind]:
                del data[kind]
            if not cleared:
                return ()
            self._write(data)
            self._append_or_restore(events, pre_image)
        return tuple(cleared)

    def _append_or_restore(
        self, events: list[AuditEvent], pre_image: str | None
    ) -> None:
        """Append the audit block; on failure restore the annotation
        pre-image so an unaudited mutation is never left behind."""

        try:
            self._audit.append_many(events)
        except Exception:
            if pre_image is None:
                self.path.unlink(missing_ok=True)
            else:
                restore = self.path.with_name(
                    f".{self.path.name}.{uuid4().hex}.restoring"
                )
                try:
                    restore.write_text(pre_image, encoding="utf-8")
                    restore.replace(self.path)
                finally:
                    restore.unlink(missing_ok=True)
            raise

    def clear(
        self,
        *,
        kind: str,
        subject: str,
        actor: str = "local-operator",
        reason: str | None = None,
        occurred_at: str | None = None,
        scope_id: str = "all",
    ) -> None:
        with self._lock:
            data = self._load()
            before = (data.get(kind) or {}).get(subject)
            if before is None:
                raise ValueError(f"no {kind} annotation exists for {subject}")
            del data[kind][subject]
            if not data[kind]:
                del data[kind]
            self._write(data)
            self._audit.append(AuditEvent.create(
                category=kind, operation="clear", subject=subject,
                actor=actor, scope_id=scope_id, before=before, after={},
                reason=reason, occurred_at=occurred_at,
            ))

    def _write(self, data: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": ANNOTATIONS_SCHEMA_VERSION,
                        "annotations": data,
                    },
                    indent=2, sort_keys=True, ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
