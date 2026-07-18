"""Server-side sessions: opaque tokens, hashed at rest, revocable.

The browser holds only a random 256-bit token; the store holds its
SHA-256. Stealing the session file therefore does not yield usable
tokens, and logout/invalidation is immediate — no waiting for a signed
cookie to expire. A fresh token is minted at every login (session
fixation cannot survive authentication) and each session carries its
own CSRF token, absolute expiry, and idle deadline.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

SESSIONS_FILENAME = "sessions.json"
DEFAULT_MAX_AGE_SECONDS = 12 * 3600
DEFAULT_IDLE_TIMEOUT_SECONDS = 2 * 3600
SESSION_COOKIE = "atlas_session"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str
    username: str
    csrf_token: str
    created_at: str
    expires_at: str
    idle_deadline: str
    auth_mode: str = "password"

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_hash": self.token_hash, "username": self.username,
            "csrf_token": self.csrf_token, "created_at": self.created_at,
            "expires_at": self.expires_at,
            "idle_deadline": self.idle_deadline, "auth_mode": self.auth_mode,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SessionRecord":
        return cls(
            token_hash=str(value["token_hash"]),
            username=str(value["username"]),
            csrf_token=str(value.get("csrf_token") or ""),
            created_at=str(value.get("created_at") or ""),
            expires_at=str(value.get("expires_at") or ""),
            idle_deadline=str(value.get("idle_deadline") or ""),
            auth_mode=str(value.get("auth_mode") or "password"),
        )


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


class SessionStore:
    """sessions.json under the workspace root. Small by design: expired
    records are pruned on every write."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self.path = Path(workspace_root) / SESSIONS_FILENAME
        self.max_age = timedelta(seconds=int(max_age_seconds))
        self.idle_timeout = timedelta(seconds=int(idle_timeout_seconds))
        self._lock = _lock_for(self.path)

    def _read(self) -> list[SessionRecord]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [
                SessionRecord.from_dict(item)
                for item in raw.get("sessions") or ()
            ]
        except (ValueError, TypeError, KeyError):
            # A corrupt session file must never lock every operator out of
            # recovery: treat it as "no sessions" (everyone re-authenticates).
            return []

    def _write(self, sessions: list[SessionRecord]) -> None:
        now_iso = _now().isoformat(timespec="seconds")
        alive = [
            record for record in sessions
            if record.expires_at > now_iso and record.idle_deadline > now_iso
        ]
        payload = {"schema_version": "1.0.0",
                   "sessions": [record.to_dict() for record in alive]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- lifecycle ---------------------------------------------------------

    def create(self, username: str, *, auth_mode: str = "password") -> str:
        """Mint a session and return the raw token (its only appearance)."""

        token = secrets.token_urlsafe(32)
        now = _now()
        record = SessionRecord(
            token_hash=_hash(token),
            username=str(username),
            csrf_token=secrets.token_urlsafe(32),
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + self.max_age).isoformat(timespec="seconds"),
            idle_deadline=(now + self.idle_timeout).isoformat(timespec="seconds"),
            auth_mode=auth_mode,
        )
        with self._lock:
            self._write([*self._read(), record])
        return token

    def resolve(self, token: str | None) -> SessionRecord | None:
        """The live session for ``token``, sliding its idle deadline."""

        if not token:
            return None
        needle = _hash(token)
        now = _now()
        now_iso = now.isoformat(timespec="seconds")
        with self._lock:
            sessions = self._read()
            for index, record in enumerate(sessions):
                if record.token_hash != needle:
                    continue
                if record.expires_at <= now_iso or record.idle_deadline <= now_iso:
                    return None
                refreshed = replace(
                    record,
                    idle_deadline=(now + self.idle_timeout).isoformat(
                        timespec="seconds"
                    ),
                )
                sessions[index] = refreshed
                self._write(sessions)
                return refreshed
        return None

    def invalidate(self, token: str | None) -> None:
        if not token:
            return
        needle = _hash(token)
        with self._lock:
            self._write([
                record for record in self._read()
                if record.token_hash != needle
            ])

    def invalidate_user(self, username: str) -> int:
        """Revoke every session of ``username`` (disable/delete flows)."""

        needle = str(username).casefold()
        with self._lock:
            sessions = self._read()
            remaining = [
                record for record in sessions
                if record.username.casefold() != needle
            ]
            self._write(remaining)
            return len(sessions) - len(remaining)

    def active_count_for(self, username: str) -> int:
        needle = str(username).casefold()
        now_iso = _now().isoformat(timespec="seconds")
        return sum(
            1 for record in self._read()
            if record.username.casefold() == needle
            and record.expires_at > now_iso
            and record.idle_deadline > now_iso
        )

    def active_count(self) -> int:
        now_iso = _now().isoformat(timespec="seconds")
        return sum(
            1 for record in self._read()
            if record.expires_at > now_iso and record.idle_deadline > now_iso
        )
