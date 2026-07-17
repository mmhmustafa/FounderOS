"""Audited policy exceptions: reason, owner, approval, expiry, revocation.

An exception never edits a verdict — the engine's result stands. It
reclassifies a failed/warning result into the ``excepted`` bucket until
it expires or is revoked, and every grant/revoke lands in the unified
audit log (founderos_atlas.audit) with before/after and reason.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.audit import AuditEvent, AuditLog
from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .explorer import result_subject


POLICY_EXCEPTIONS_FILENAME = "policy-exceptions.json"
POLICY_EXCEPTIONS_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class PolicyException:
    subject: str                      # policy-result:<policy_id>:<hostname>
    policy_id: str
    hostname: str
    reason: str
    owner: str
    approved_by: str | None
    expires_at: str | None            # ISO instant; None = until revoked
    created_at: str
    created_by: str

    def is_active(self, now: str) -> bool:
        if not self.expires_at:
            return True
        return now <= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "policy_id": self.policy_id,
            "hostname": self.hostname,
            "reason": self.reason,
            "owner": self.owner,
            "approved_by": self.approved_by,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyException":
        return cls(
            subject=str(value["subject"]),
            policy_id=str(value["policy_id"]),
            hostname=str(value["hostname"]),
            reason=str(value["reason"]),
            owner=str(value.get("owner") or "local-operator"),
            approved_by=(
                str(value["approved_by"]) if value.get("approved_by") else None
            ),
            expires_at=(
                str(value["expires_at"]) if value.get("expires_at") else None
            ),
            created_at=str(value["created_at"]),
            created_by=str(value.get("created_by") or "local-operator"),
        )


class PolicyExceptionRepository:
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
        return self._root / POLICY_EXCEPTIONS_FILENAME

    def load(self) -> tuple[PolicyException, ...]:
        if not self.path.is_file():
            return ()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return tuple(
                PolicyException.from_dict(item)
                for item in value.get("exceptions") or ()
            )
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The policy exceptions file {self.path} could not be read: "
                f"{error}"
            ) from error

    def active_subjects(self, now: str) -> frozenset[str]:
        return frozenset(
            item.subject for item in self.load() if item.is_active(now)
        )

    def find(self, subject: str) -> PolicyException | None:
        for item in self.load():
            if item.subject == subject:
                return item
        return None

    def grant(
        self,
        *,
        policy_id: str,
        hostname: str,
        reason: str,
        owner: str,
        approved_by: str | None = None,
        expires_at: str | None = None,
        actor: str = "local-operator",
        correlation_id: str | None = None,
        occurred_at: str | None = None,
    ) -> PolicyException:
        if not str(reason or "").strip():
            raise ValueError("an exception requires a reason")
        if not str(owner or "").strip():
            raise ValueError("an exception requires an owner")
        subject = result_subject(policy_id, hostname)
        stamp = occurred_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        exception = PolicyException(
            subject=subject, policy_id=policy_id, hostname=hostname,
            reason=str(reason).strip(), owner=str(owner).strip(),
            approved_by=(str(approved_by).strip() or None)
            if approved_by else None,
            expires_at=(str(expires_at).strip() or None)
            if expires_at else None,
            created_at=stamp, created_by=actor,
        )
        with self._lock:
            existing = self.find(subject)
            remaining = [
                item for item in self.load() if item.subject != subject
            ]
            self._write(tuple(sorted(
                (*remaining, exception), key=lambda item: item.subject
            )))
            self._audit.append(AuditEvent.create(
                category="policy-exception",
                operation="grant" if existing is None else "update",
                subject=subject,
                actor=actor,
                before=existing.to_dict() if existing else {},
                after=exception.to_dict(),
                reason=exception.reason,
                correlation_id=correlation_id,
                occurred_at=stamp,
            ))
        return exception

    def revoke(
        self,
        *,
        policy_id: str,
        hostname: str,
        reason: str | None = None,
        actor: str = "local-operator",
        occurred_at: str | None = None,
    ) -> PolicyException:
        subject = result_subject(policy_id, hostname)
        with self._lock:
            existing = self.find(subject)
            if existing is None:
                raise ValueError("no exception covers this result")
            self._write(tuple(
                item for item in self.load() if item.subject != subject
            ))
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            self._audit.append(AuditEvent.create(
                category="policy-exception",
                operation="revoke",
                subject=subject,
                actor=actor,
                before=existing.to_dict(),
                after={},
                reason=reason,
                occurred_at=stamp,
            ))
        return existing

    def _write(self, exceptions: tuple[PolicyException, ...]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": POLICY_EXCEPTIONS_SCHEMA_VERSION,
                        "exceptions": [
                            item.to_dict() for item in exceptions
                        ],
                    },
                    indent=2, sort_keys=True, ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
