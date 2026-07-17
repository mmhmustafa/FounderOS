"""The audit event model: one shape for every operator mutation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


AUDIT_SCHEMA_VERSION = "1.0.0"

# Field names that must never appear in an audit payload. A caller that
# needs to audit a credential change records the credential REFERENCE.
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {"password", "secret", "token", "private_key", "passphrase"}
)


def redact_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """A payload copy with forbidden keys replaced by a redaction marker.

    Defence in depth: callers should never pass secrets, and if one does
    anyway the value is dropped before it can reach disk.
    """

    cleaned: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if str(key).casefold() in _FORBIDDEN_PAYLOAD_KEYS:
            cleaned[key] = "[redacted]"
        elif isinstance(value, Mapping):
            cleaned[key] = redact_payload(value)
        else:
            cleaned[key] = value
    return cleaned


@dataclass(frozen=True)
class AuditEvent:
    """One mutation, fully accounted for.

    ``before``/``after`` are small mappings describing the changed state
    (references and labels, never secrets). ``source`` names the surface
    that performed the mutation (``web``, ``cli``, ``api``).
    ``correlation_id`` groups the events of one logical operation (a bulk
    action emits one event per subject under one correlation id).
    """

    event_id: str
    occurred_at: str
    actor: str
    scope_id: str
    category: str                     # policy-exception | assignment | ...
    operation: str                    # create | update | revoke | ...
    subject: str
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None
    source: str = "web"
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "occurred_at", "actor", "category",
                     "operation", "subject"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        object.__setattr__(self, "before", redact_payload(self.before))
        object.__setattr__(self, "after", redact_payload(self.after))

    @classmethod
    def create(
        cls,
        *,
        category: str,
        operation: str,
        subject: str,
        actor: str = "local-operator",
        scope_id: str = "all",
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        reason: str | None = None,
        source: str = "web",
        correlation_id: str | None = None,
        occurred_at: str | None = None,
    ) -> "AuditEvent":
        return cls(
            event_id=f"audit:{uuid4().hex}",
            occurred_at=occurred_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            actor=actor,
            scope_id=scope_id,
            category=category,
            operation=operation,
            subject=subject,
            before=dict(before or {}),
            after=dict(after or {}),
            reason=(str(reason).strip() or None) if reason else None,
            source=source,
            correlation_id=correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "scope_id": self.scope_id,
            "category": self.category,
            "operation": self.operation,
            "subject": self.subject,
            "before": dict(self.before),
            "after": dict(self.after),
            "reason": self.reason,
            "source": self.source,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuditEvent":
        return cls(
            event_id=str(value["event_id"]),
            occurred_at=str(value["occurred_at"]),
            actor=str(value.get("actor") or "local-operator"),
            scope_id=str(value.get("scope_id") or "all"),
            category=str(value["category"]),
            operation=str(value["operation"]),
            subject=str(value["subject"]),
            before=dict(value.get("before") or {}),
            after=dict(value.get("after") or {}),
            reason=(str(value["reason"]) if value.get("reason") else None),
            source=str(value.get("source") or "web"),
            correlation_id=(
                str(value["correlation_id"])
                if value.get("correlation_id") else None
            ),
        )
