"""The durable operational Action Center.

Records are atomically persisted workspace JSONL addressed to a user or role.
Each retains its source, priority, owner, recurrence, evidence freshness and
audited lifecycle. Optional external delivery uses the separate secret-free
outbox; this record remains authoritative.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from founderos_atlas.web.redirects import safe_redirect_target

NOTIFICATIONS_FILENAME = "notifications.jsonl"
MAX_NOTIFICATIONS = 2000

KIND_ASSIGNMENT = "assignment"
KIND_DISCOVERY_FAILED = "discovery-failed"
KIND_STALE_EVIDENCE = "stale-evidence"
KIND_POLICY_REGRESSION = "policy-regression"
KIND_EDIT_CONFLICT = "edit-conflict"
KIND_APPROVAL_REQUEST = "approval-request"
KIND_INCIDENT = "incident"

STATUS_UNREAD = "unread"
STATUS_READ = "read"
STATUS_DONE = "done"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_IN_PROGRESS = "in-progress"
STATUS_RESOLVED = "resolved"
STATUS_SUPPRESSED = "suppressed"
STATUS_SNOOZED = "snoozed"

# ``unread/read/done`` are retained for records and clients created before the
# operational Action Center.  The richer states are deliberately additive so
# an upgrade never rewrites or loses an operator's inbox history.
STATUSES = (
    STATUS_UNREAD,
    STATUS_READ,
    STATUS_DONE,
    STATUS_ACKNOWLEDGED,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
    STATUS_SUPPRESSED,
    STATUS_SNOOZED,
)
ACTIVE_STATUSES = (
    STATUS_UNREAD,
    STATUS_READ,
    STATUS_ACKNOWLEDGED,
    STATUS_IN_PROGRESS,
    STATUS_SNOOZED,
)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_RESOLVED, STATUS_SUPPRESSED)
PRIORITIES = ("critical", "high", "medium", "low", "informational")

_TRANSITIONS = {
    STATUS_UNREAD: {
        STATUS_READ,
        STATUS_ACKNOWLEDGED,
        STATUS_IN_PROGRESS,
        STATUS_DONE,
        STATUS_RESOLVED,
        STATUS_SUPPRESSED,
        STATUS_SNOOZED,
    },
    STATUS_READ: {
        STATUS_ACKNOWLEDGED,
        STATUS_IN_PROGRESS,
        STATUS_DONE,
        STATUS_RESOLVED,
        STATUS_SUPPRESSED,
        STATUS_UNREAD,
        STATUS_SNOOZED,
    },
    STATUS_ACKNOWLEDGED: {
        STATUS_IN_PROGRESS,
        STATUS_RESOLVED,
        STATUS_DONE,
        STATUS_SUPPRESSED,
        STATUS_UNREAD,
        STATUS_SNOOZED,
    },
    STATUS_IN_PROGRESS: {
        STATUS_RESOLVED,
        STATUS_DONE,
        STATUS_SUPPRESSED,
        STATUS_ACKNOWLEDGED,
        STATUS_SNOOZED,
    },
    STATUS_DONE: {STATUS_UNREAD},
    STATUS_RESOLVED: {STATUS_UNREAD},
    STATUS_SUPPRESSED: {STATUS_UNREAD},
    STATUS_SNOOZED: {
        STATUS_UNREAD,
        STATUS_ACKNOWLEDGED,
        STATUS_IN_PROGRESS,
        STATUS_RESOLVED,
        STATUS_DONE,
        STATUS_SUPPRESSED,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snooze_is_active(item: "Notification", now: datetime) -> bool:
    if item.status != STATUS_SNOOZED or not item.due_at:
        return False
    try:
        due = datetime.fromisoformat(item.due_at)
        if due.tzinfo is None:
            return False
        return due.astimezone(timezone.utc) > now
    except (TypeError, ValueError):
        return False


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
    updated_at: str | None = None
    priority: str = "medium"
    owner: str | None = None
    scope_id: str | None = None
    subject: str | None = None
    due_at: str | None = None
    source_refs: tuple[str, ...] = ()
    evidence_freshness: str | None = None
    dedupe_key: str | None = None
    occurrences: int = 1
    recurrence_count: int = 0
    resolved_at: str | None = None
    reason: str | None = None
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "created_at": self.created_at, "kind": self.kind,
            "title": self.title, "detail": self.detail, "href": self.href,
            "audience": self.audience, "status": self.status,
            "correlation_id": self.correlation_id,
            "updated_at": self.updated_at or self.created_at,
            "priority": self.priority, "owner": self.owner,
            "scope_id": self.scope_id, "subject": self.subject,
            "due_at": self.due_at, "source_refs": list(self.source_refs),
            "evidence_freshness": self.evidence_freshness,
            "dedupe_key": self.dedupe_key,
            "occurrences": self.occurrences,
            "recurrence_count": self.recurrence_count,
            "resolved_at": self.resolved_at, "reason": self.reason,
            "revision": self.revision,
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
            updated_at=(
                str(value["updated_at"]) if value.get("updated_at") else None
            ),
            priority=str(value.get("priority") or "medium"),
            owner=(str(value["owner"]) if value.get("owner") else None),
            scope_id=(
                str(value["scope_id"]) if value.get("scope_id") else None
            ),
            subject=(
                str(value["subject"]) if value.get("subject") else None
            ),
            due_at=(str(value["due_at"]) if value.get("due_at") else None),
            source_refs=tuple(
                str(item) for item in value.get("source_refs") or ()
            ),
            evidence_freshness=(
                str(value["evidence_freshness"])
                if value.get("evidence_freshness") else None
            ),
            dedupe_key=(
                str(value["dedupe_key"]) if value.get("dedupe_key") else None
            ),
            occurrences=max(1, int(value.get("occurrences") or 1)),
            recurrence_count=max(
                0, int(value.get("recurrence_count") or 0)
            ),
            resolved_at=(
                str(value["resolved_at"]) if value.get("resolved_at") else None
            ),
            reason=(str(value["reason"]) if value.get("reason") else None),
            revision=max(1, int(value.get("revision") or 1)),
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
        priority: str = "medium",
        owner: str | None = None,
        scope_id: str | None = None,
        subject: str | None = None,
        due_at: str | None = None,
        source_refs=(),
        evidence_freshness: str | None = None,
    ) -> Notification | None:
        """Append or correlate one operational notification.

        A repeated active condition increments its occurrence count instead of
        creating noise.  A condition that returns after it was resolved reopens
        the same durable item and records a recurrence.
        """

        if priority not in PRIORITIES:
            raise ValueError(
                f"priority must be one of {', '.join(PRIORITIES)}"
            )
        title = str(title).strip()
        detail = str(detail).strip()
        href = str(href).strip()
        audience = str(audience).strip()
        if not title or len(title) > 300:
            raise ValueError("notification title must contain 1 to 300 characters")
        if len(detail) > 4000:
            raise ValueError("notification detail is too long")
        if not audience or len(audience) > 300:
            raise ValueError("notification audience is invalid")
        if href and safe_redirect_target(href, "") != href:
            raise ValueError("notification link must be application-relative")
        source_refs = tuple(str(item)[:500] for item in source_refs)[:100]
        with self._lock:
            items = self._read()
            if dedupe_key is not None:
                for index, existing in enumerate(items):
                    if (
                        existing.kind == kind
                        and existing.audience == audience
                        and (
                            existing.dedupe_key == dedupe_key
                            or (
                                existing.dedupe_key is None
                                and existing.href == href
                            )
                        )
                    ):
                        stamp = _now()
                        if existing.status in ACTIVE_STATUSES:
                            items[index] = replace(
                                existing,
                                title=title,
                                detail=detail,
                                href=href,
                                updated_at=stamp,
                                priority=priority,
                                owner=owner or existing.owner,
                                scope_id=scope_id or existing.scope_id,
                                subject=subject or existing.subject,
                                due_at=due_at or existing.due_at,
                                source_refs=tuple(source_refs)
                                or existing.source_refs,
                                evidence_freshness=evidence_freshness
                                or existing.evidence_freshness,
                                dedupe_key=dedupe_key,
                                occurrences=existing.occurrences + 1,
                                correlation_id=correlation_id
                                or existing.correlation_id,
                                revision=existing.revision + 1,
                            )
                            self._write(items)
                            return None
                        items[index] = replace(
                            existing,
                            title=title,
                            detail=detail,
                            href=href,
                            status=STATUS_UNREAD,
                            updated_at=stamp,
                            priority=priority,
                            owner=owner,
                            scope_id=scope_id or existing.scope_id,
                            subject=subject or existing.subject,
                            due_at=due_at,
                            source_refs=tuple(source_refs),
                            evidence_freshness=evidence_freshness,
                            dedupe_key=dedupe_key,
                            occurrences=existing.occurrences + 1,
                            recurrence_count=existing.recurrence_count + 1,
                            resolved_at=None,
                            reason=None,
                            correlation_id=correlation_id
                            or existing.correlation_id,
                            revision=existing.revision + 1,
                        )
                        self._write(items)
                        return items[index]
            stamp = _now()
            record = Notification(
                notification_id=f"note:{uuid4().hex}",
                created_at=stamp, updated_at=stamp,
                kind=kind, title=title, detail=detail,
                href=href, audience=audience, correlation_id=correlation_id,
                priority=priority, owner=owner, scope_id=scope_id,
                subject=subject, due_at=due_at,
                source_refs=tuple(str(item) for item in source_refs),
                evidence_freshness=evidence_freshness,
                dedupe_key=dedupe_key,
            )
            items.append(record)
            self._write(items)
            return record

    # -- reading -----------------------------------------------------------

    def for_principal(
        self,
        username: str,
        roles,
        *,
        include_done: bool = False,
        status: str | None = None,
        priority: str | None = None,
        kind: str | None = None,
        mine: bool = False,
    ) -> list[Notification]:
        audiences = {str(username).casefold()}
        audiences.update(f"role:{role}".casefold() for role in roles)
        found = [
            item for item in self._read()
            if item.audience.casefold() in audiences
            and (include_done or item.status not in TERMINAL_STATUSES)
        ]
        if status:
            found = [item for item in found if item.status == status]
        if priority:
            found = [item for item in found if item.priority == priority]
        if kind:
            found = [item for item in found if item.kind == kind]
        if mine:
            wanted = str(username).casefold()
            found = [
                item for item in found
                if (item.owner or "").casefold() == wanted
            ]
        # Snoozed work remains durable and queryable but stays out of the
        # normal active view until its UTC wake-up instant.
        if status != STATUS_SNOOZED:
            now = datetime.now(timezone.utc)
            found = [
                item for item in found
                if not _snooze_is_active(item, now)
            ]
        priority_order = {
            "critical": 0, "high": 1, "medium": 2, "low": 3,
            "informational": 4,
        }
        found.sort(
            key=lambda item: (
                priority_order.get(item.priority, 9),
                item.updated_at or item.created_at,
            ),
            reverse=False,
        )
        return found

    def unread_count(self, username: str, roles) -> int:
        return sum(
            1 for item in self.for_principal(username, roles)
            if item.status == STATUS_UNREAD
        )

    # -- acting ------------------------------------------------------------

    def set_status(
        self,
        notification_id: str,
        status: str,
        *,
        expected_revision: int | None = None,
        owner: str | None = None,
        reason: str | None = None,
        due_at: str | None = None,
    ) -> bool:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if status == STATUS_SNOOZED:
            if not due_at:
                raise ValueError("snoozing an action item requires a wake-up time")
            try:
                wake = datetime.fromisoformat(due_at)
            except ValueError as error:
                raise ValueError("snooze wake-up time is invalid") from error
            if wake.tzinfo is None or wake <= datetime.now(timezone.utc):
                raise ValueError("snooze wake-up time must be in the future")
        with self._lock:
            items = self._read()
            for index, item in enumerate(items):
                if item.notification_id == notification_id:
                    if (
                        expected_revision is not None
                        and item.revision != int(expected_revision)
                    ):
                        raise RuntimeError(
                            "The action item changed while you were editing. "
                            "Reload it before applying your change."
                        )
                    if (
                        item.status != status
                        and status not in _TRANSITIONS.get(item.status, set())
                    ):
                        raise ValueError(
                            f"cannot move an action item from {item.status} "
                            f"to {status}"
                        )
                    stamp = _now()
                    items[index] = replace(
                        item,
                        status=status,
                        updated_at=stamp,
                        owner=owner if owner is not None else item.owner,
                        reason=reason if reason is not None else item.reason,
                        due_at=(
                            due_at
                            if status == STATUS_SNOOZED
                            else None
                            if item.status == STATUS_SNOOZED
                            else item.due_at
                        ),
                        resolved_at=(
                            stamp if status in TERMINAL_STATUSES else None
                        ),
                        revision=item.revision + 1,
                    )
                    self._write(items)
                    return True
            return False

    def reconcile(
        self,
        *,
        kind: str,
        audience: str,
        active_dedupe_keys,
        evidence_complete: bool,
        evidence_stale: bool = False,
        scope_id: str | None = None,
        reason: str = "A later observation no longer reports this condition.",
    ) -> int:
        """Resolve absent conditions only when fresh, complete evidence proves it.

        Missing or stale evidence is never treated as recovery.
        """

        if not evidence_complete or evidence_stale:
            return 0
        active = {str(item) for item in active_dedupe_keys}
        changed = 0
        with self._lock:
            items = self._read()
            for index, item in enumerate(items):
                if (
                    item.kind == kind
                    and item.audience == audience
                    and item.status in ACTIVE_STATUSES
                    and (scope_id is None or item.scope_id == scope_id)
                    and item.dedupe_key
                    and item.dedupe_key not in active
                ):
                    stamp = _now()
                    items[index] = replace(
                        item,
                        status=STATUS_RESOLVED,
                        updated_at=stamp,
                        resolved_at=stamp,
                        reason=reason,
                        revision=item.revision + 1,
                    )
                    changed += 1
            if changed:
                self._write(items)
        return changed
