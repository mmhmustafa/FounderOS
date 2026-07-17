"""The internal notification inbox: ownership without email.

Notifications are workspace records (JSONL, atomic replace, per-store
lock) addressed to a username or to a role (``role:policy-manager``).
They carry a kind, a link to the exact object, and a status the
recipient controls (unread → read → done). Emitters live where events
happen: discovery job failure, edit conflicts, policy regressions,
approval requests, assignments.

No external delivery is attempted here by design; an email/webhook
bridge belongs behind this same store so the in-app record stays the
source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

NOTIFICATIONS_FILENAME = "notifications.jsonl"
MAX_NOTIFICATIONS = 2000

KIND_ASSIGNMENT = "assignment"
KIND_DISCOVERY_FAILED = "discovery-failed"
KIND_STALE_EVIDENCE = "stale-evidence"
KIND_POLICY_REGRESSION = "policy-regression"
KIND_EDIT_CONFLICT = "edit-conflict"
KIND_APPROVAL_REQUEST = "approval-request"
KIND_INCIDENT = "incident"

STATUSES = ("unread", "read", "done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Notification:
    notification_id: str
    created_at: str
    kind: str
    title: str
    detail: str
    href: str
    audience: str                 # "username" or "role:<role>"
    status: str = "unread"
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "created_at": self.created_at, "kind": self.kind,
            "title": self.title, "detail": self.detail, "href": self.href,
            "audience": self.audience, "status": self.status,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Notification":
        return cls(
            notification_id=str(value["notification_id"]),
            created_at=str(value["created_at"]),
            kind=str(value["kind"]),
            title=str(value["title"]),
            detail=str(value.get("detail") or ""),
            href=str(value.get("href") or ""),
            audience=str(value.get("audience") or "role:system-admin"),
            status=str(value.get("status") or "unread"),
            correlation_id=(
                str(value["correlation_id"])
                if value.get("correlation_id") else None
            ),
        )


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


class NotificationStore:
    def __init__(self, workspace_root: str | Path) -> None:
        self.path = Path(workspace_root) / NOTIFICATIONS_FILENAME
        self._lock = _lock_for(self.path)

    def _read(self) -> list[Notification]:
        if not self.path.is_file():
            return []
        items: list[Notification] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(Notification.from_dict(json.loads(line)))
            except (ValueError, TypeError, KeyError):
                continue  # one bad line must not hide the rest
        return items

    def _write(self, items: list[Notification]) -> None:
        # Newest-last on disk; cap so the inbox cannot grow without bound.
        trimmed = items[-MAX_NOTIFICATIONS:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                "".join(
                    json.dumps(item.to_dict(), sort_keys=True) + "\n"
                    for item in trimmed
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- emitting ----------------------------------------------------------

    def notify(
        self,
        *,
        kind: str,
        title: str,
        audience: str,
        detail: str = "",
        href: str = "",
        correlation_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> Notification | None:
        """Append a notification. With ``dedupe_key``, an existing UNREAD
        notification with the same kind+audience+href is not repeated."""

        with self._lock:
            items = self._read()
            if dedupe_key is not None:
                for existing in items:
                    if (
                        existing.status == "unread"
                        and existing.kind == kind
                        and existing.audience == audience
                        and existing.href == href
                    ):
                        return None
            record = Notification(
                notification_id=f"note:{uuid4().hex}",
                created_at=_now(), kind=kind, title=title, detail=detail,
                href=href, audience=audience, correlation_id=correlation_id,
            )
            items.append(record)
            self._write(items)
            return record

    # -- reading -----------------------------------------------------------

    def for_principal(
        self, username: str, roles, *, include_done: bool = False
    ) -> list[Notification]:
        audiences = {str(username).casefold()}
        audiences.update(f"role:{role}".casefold() for role in roles)
        found = [
            item for item in self._read()
            if item.audience.casefold() in audiences
            and (include_done or item.status != "done")
        ]
        found.sort(key=lambda item: item.created_at, reverse=True)
        return found

    def unread_count(self, username: str, roles) -> int:
        return sum(
            1 for item in self.for_principal(username, roles)
            if item.status == "unread"
        )

    # -- acting ------------------------------------------------------------

    def set_status(self, notification_id: str, status: str) -> bool:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        with self._lock:
            items = self._read()
            for index, item in enumerate(items):
                if item.notification_id == notification_id:
                    items[index] = replace(item, status=status)
                    self._write(items)
                    return True
            return False
