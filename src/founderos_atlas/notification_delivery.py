"""Secret-free notification delivery outbox and provider boundaries.

The in-app Action Center remains the source of truth. External delivery sends
only minimal context and an authenticated application-relative deep link.
Credentials are resolved by the caller and are never persisted in this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping
from uuid import uuid4

from founderos_atlas.web.redirects import safe_redirect_target

OUTBOX_FILENAME = "notification-outbox.jsonl"
STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_RETRY = "retry"
STATUS_FAILED = "failed"
_OUTBOX_LOCKS: dict[str, RLock] = {}
_OUTBOX_LOCKS_GUARD = RLock()


def _outbox_lock(path: Path) -> RLock:
    """Share one lock across every in-process handle to an outbox path."""

    with _OUTBOX_LOCKS_GUARD:
        return _OUTBOX_LOCKS.setdefault(str(path.resolve()), RLock())


class DeliveryProviderError(RuntimeError):
    """A provider failed without exposing its credential-bearing exception."""


@dataclass(frozen=True)
class DeliveryMessage:
    message_id: str
    action_id: str
    provider: str
    destination_ref: str
    title: str
    priority: str
    href: str
    scope_id: str | None
    created_at: str
    idempotency_key: str
    status: str = STATUS_PENDING
    attempts: int = 0
    next_attempt_at: str | None = None
    delivered_at: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        if safe_redirect_target(self.href, "") != self.href:
            raise ValueError(
                "delivery links must be a safe application-relative path"
            )
        if self.status not in {
            STATUS_PENDING, STATUS_DELIVERED, STATUS_RETRY, STATUS_FAILED,
        }:
            raise ValueError("invalid delivery status")

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeliveryMessage":
        return cls(**{
            key: value.get(key, field.default)
            for key, field in cls.__dataclass_fields__.items()
        })

    def payload(self) -> dict[str, Any]:
        """The deliberately minimal content allowed to leave Atlas."""

        return {
            "action_id": self.action_id,
            "title": self.title,
            "priority": self.priority,
            "href": self.href,
            "scope_id": self.scope_id,
        }


class DeliveryProvider(ABC):
    name: str

    @abstractmethod
    def deliver(self, message: DeliveryMessage) -> None:
        pass

    def available(self) -> bool:
        return True


class CallbackProvider(DeliveryProvider):
    """Email/Teams/Slack adapter using an injected, credential-safe sender."""

    def __init__(self, name: str, sender: Callable[[dict], None]) -> None:
        self.name = str(name)
        self._sender = sender

    def deliver(self, message: DeliveryMessage) -> None:
        try:
            self._sender(message.payload())
        except Exception as error:
            raise DeliveryProviderError(
                f"{self.name} notification delivery failed"
            ) from error


class SignedWebhookProvider(DeliveryProvider):
    name = "webhook"

    def __init__(
        self,
        sender: Callable[[bytes, Mapping[str, str]], None],
        *,
        signing_secret: str,
    ) -> None:
        if not signing_secret:
            raise ValueError("a webhook signing secret is required")
        self._sender = sender
        self._secret = signing_secret.encode("utf-8")

    def deliver(self, message: DeliveryMessage) -> None:
        body = json.dumps(
            message.payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        signature = hmac.new(
            self._secret, body, hashlib.sha256
        ).hexdigest()
        try:
            self._sender(body, {
                "Content-Type": "application/json",
                "X-Atlas-Signature-SHA256": signature,
                "Idempotency-Key": message.idempotency_key,
            })
        except Exception as error:
            raise DeliveryProviderError(
                "webhook notification delivery failed"
            ) from error


class DeliveryOutbox:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        max_messages: int = 5000,
    ) -> None:
        self.path = Path(workspace_root) / OUTBOX_FILENAME
        self.max_messages = max(1, int(max_messages))
        self._lock = _outbox_lock(self.path)

    def _read(self) -> list[DeliveryMessage]:
        if not self.path.is_file():
            return []
        values: list[DeliveryMessage] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                values.append(DeliveryMessage.from_dict(json.loads(line)))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        return values

    def _write(self, messages: list[DeliveryMessage]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                "".join(
                    json.dumps(item.to_dict(), sort_keys=True) + "\n"
                    for item in messages[-self.max_messages:]
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def enqueue(
        self,
        *,
        action_id: str,
        provider: str,
        destination_ref: str,
        title: str,
        priority: str,
        href: str,
        scope_id: str | None = None,
        created_at: datetime | None = None,
    ) -> DeliveryMessage | None:
        moment = (created_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        key = f"{action_id}:{provider}:{destination_ref}"
        with self._lock:
            messages = self._read()
            if any(
                item.idempotency_key == key
                and item.status in {STATUS_PENDING, STATUS_RETRY, STATUS_DELIVERED}
                for item in messages
            ):
                return None
            message = DeliveryMessage(
                message_id=f"delivery:{uuid4().hex}",
                action_id=action_id,
                provider=provider,
                destination_ref=destination_ref,
                title=title,
                priority=priority,
                href=href,
                scope_id=scope_id,
                created_at=moment.isoformat(timespec="seconds"),
                idempotency_key=key,
            )
            self._write([*messages, message])
        return message

    def pending(self, *, now: datetime | None = None) -> list[DeliveryMessage]:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        values = [
            item for item in self._read()
            if item.status == STATUS_PENDING
            or (
                item.status == STATUS_RETRY
                and item.next_attempt_at
                and datetime.fromisoformat(item.next_attempt_at).astimezone(
                    timezone.utc
                ) <= moment
            )
        ]
        values.sort(key=lambda item: item.created_at)
        return values

    def dispatch(
        self,
        providers: Mapping[str, DeliveryProvider],
        *,
        now: datetime | None = None,
        max_attempts: int = 4,
        batch_limit: int = 50,
    ) -> dict[str, int]:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        due = self.pending(now=moment)[:max(1, min(batch_limit, 500))]
        counts = {"delivered": 0, "retry": 0, "failed": 0}
        with self._lock:
            messages = self._read()
            replacements: dict[str, DeliveryMessage] = {}
            for message in due:
                provider = providers.get(message.provider)
                attempt = message.attempts + 1
                if provider is None or not provider.available():
                    replacements[message.message_id] = replace(
                        message,
                        status=STATUS_FAILED,
                        attempts=attempt,
                        last_error="notification provider unavailable",
                    )
                    counts["failed"] += 1
                    continue
                try:
                    provider.deliver(message)
                except DeliveryProviderError:
                    if attempt >= max_attempts:
                        state = STATUS_FAILED
                        next_attempt = None
                        counts["failed"] += 1
                    else:
                        state = STATUS_RETRY
                        next_attempt = (
                            moment + timedelta(minutes=2 ** (attempt - 1))
                        ).isoformat(timespec="seconds")
                        counts["retry"] += 1
                    replacements[message.message_id] = replace(
                        message,
                        status=state,
                        attempts=attempt,
                        next_attempt_at=next_attempt,
                        last_error="provider delivery failed",
                    )
                else:
                    replacements[message.message_id] = replace(
                        message,
                        status=STATUS_DELIVERED,
                        attempts=attempt,
                        delivered_at=moment.isoformat(timespec="seconds"),
                        next_attempt_at=None,
                        last_error=None,
                    )
                    counts["delivered"] += 1
            if replacements:
                self._write([
                    replacements.get(item.message_id, item)
                    for item in messages
                ])
        return counts
