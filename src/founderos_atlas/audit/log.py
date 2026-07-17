"""Append-only audit storage (``<workspace_root>/audit.jsonl``).

Same durability contract as the site-override audit: atomic replace,
append-only, per-workspace lock. Reading is filtered in memory — an
audit log is thousands of lines, not millions per read, and callers
paginate before rendering.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .models import AuditEvent


AUDIT_FILENAME = "audit.jsonl"


class AuditLog:
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

    @property
    def path(self) -> Path:
        return self._root / AUDIT_FILENAME

    def append(self, event: AuditEvent) -> AuditEvent:
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            existing = (
                self.path.read_text(encoding="utf-8")
                if self.path.is_file() else ""
            )
            temporary = self.path.with_name(
                f".{self.path.name}.{uuid4().hex}.writing"
            )
            try:
                temporary.write_text(
                    existing
                    + json.dumps(event.to_dict(), sort_keys=True,
                                 ensure_ascii=False)
                    + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return event

    def events(
        self,
        *,
        category: str | None = None,
        subject: str | None = None,
        actor: str | None = None,
        scope_id: str | None = None,
    ) -> tuple[AuditEvent, ...]:
        if not self.path.is_file():
            return ()
        found: list[AuditEvent] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = AuditEvent.from_dict(json.loads(line))
                if category is not None and event.category != category:
                    continue
                if subject is not None and event.subject != subject:
                    continue
                if actor is not None and event.actor != actor:
                    continue
                if scope_id is not None and event.scope_id != scope_id:
                    continue
                found.append(event)
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The audit log {self.path} could not be read: {error}"
            ) from error
        return tuple(found)
