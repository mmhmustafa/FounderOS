"""Console session registry and lifecycle (PR-044A, CONSOLE).

Owns every live SSH session the GUI has opened, and the rules that end them:

- **idle timeout** — an unattended terminal on a core router is a liability.
- **maximum session duration** — a hard ceiling regardless of activity.
- **maximum concurrent sessions** — one browser cannot exhaust the box, and
  a runaway page cannot open sessions without bound.
- **cleanup after browser closure** — a closed tab detaches the WebSocket;
  the SSH session it abandoned is reaped rather than left holding a VTY line
  on the device.

Timeouts are evaluated against an injected clock, so the tests that prove
them do not sleep.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .models import (
    SESSION_CLOSED,
    SESSION_CONNECTED,
    SESSION_FAILED,
    ConsoleSessionInfo,
)


DEFAULT_IDLE_TIMEOUT_SECONDS = 900          # 15 minutes unattended
DEFAULT_MAX_DURATION_SECONDS = 14400        # 4 hours absolute
DEFAULT_MAX_CONCURRENT = 8


class ConsoleLimitReached(RuntimeError):
    """Operator-safe: too many sessions are already open."""


@dataclass
class _LiveSession:
    session_id: str
    device_id: str
    hostname: str
    management_ip: str
    port: int
    username: str
    credential_ref: str
    operator: str
    session: Any                     # ConsoleSession
    opened_at: datetime
    last_activity: datetime
    state: str = SESSION_CONNECTED
    result: str | None = None
    detail: str | None = None
    closed_at: datetime | None = None

    def info(self) -> ConsoleSessionInfo:
        return ConsoleSessionInfo(
            session_id=self.session_id,
            device_id=self.device_id,
            hostname=self.hostname,
            management_ip=self.management_ip,
            port=self.port,
            username=self.username,
            credential_ref=self.credential_ref,
            operator=self.operator,
            state=self.state,
            opened_at=self.opened_at.isoformat(timespec="seconds"),
            closed_at=(
                self.closed_at.isoformat(timespec="seconds")
                if self.closed_at
                else None
            ),
            result=self.result,
            detail=self.detail,
        )


class ConsoleSessionManager:
    """Every live console session, and the rules that end them."""

    def __init__(
        self,
        *,
        audit=None,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit = audit
        self._idle = int(idle_timeout_seconds)
        self._max_duration = int(max_duration_seconds)
        self._max_concurrent = int(max_concurrent)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._sessions: dict[str, _LiveSession] = {}

    # -- registry ----------------------------------------------------------

    def register(
        self,
        session: Any,
        *,
        device_id: str,
        hostname: str,
        management_ip: str,
        port: int,
        username: str,
        credential_ref: str,
        operator: str,
    ) -> ConsoleSessionInfo:
        """Take ownership of a connected session."""

        now = self._clock()
        with self._lock:
            self._reap(now)
            if len(self._sessions) >= self._max_concurrent:
                raise ConsoleLimitReached(
                    f"Atlas already has {self._max_concurrent} console "
                    "session(s) open, which is the maximum. Close one and try "
                    "again."
                )
            live = _LiveSession(
                session_id=secrets.token_urlsafe(12),
                device_id=device_id,
                hostname=hostname,
                management_ip=management_ip,
                port=port,
                username=username,
                credential_ref=credential_ref,
                operator=operator,
                session=session,
                opened_at=now,
                last_activity=now,
            )
            self._sessions[live.session_id] = live
        self._record("connected", live, result="connected")
        return live.info()

    def check_capacity(self) -> None:
        """Raise if a new session would exceed the limit. Cheap pre-check."""

        with self._lock:
            self._reap(self._clock())
            if len(self._sessions) >= self._max_concurrent:
                raise ConsoleLimitReached(
                    f"Atlas already has {self._max_concurrent} console "
                    "session(s) open, which is the maximum. Close one and try "
                    "again."
                )

    def get(self, session_id: str) -> Any | None:
        with self._lock:
            live = self._sessions.get(session_id)
        return live.session if live else None

    def touch(self, session_id: str) -> None:
        """Record activity. Called on every byte in either direction."""

        with self._lock:
            live = self._sessions.get(session_id)
            if live is not None:
                live.last_activity = self._clock()

    def sessions(self) -> tuple[ConsoleSessionInfo, ...]:
        with self._lock:
            self._reap(self._clock())
            return tuple(live.info() for live in self._sessions.values())

    @property
    def active_count(self) -> int:
        with self._lock:
            self._reap(self._clock())
            return len(self._sessions)

    # -- ending ------------------------------------------------------------

    def close(
        self, session_id: str, *, reason: str = "disconnected by operator"
    ) -> ConsoleSessionInfo | None:
        with self._lock:
            live = self._sessions.pop(session_id, None)
        if live is None:
            return None
        return self._finish(live, result=reason)

    def close_all(self, *, reason: str = "server shutdown") -> int:
        with self._lock:
            items = list(self._sessions.values())
            self._sessions.clear()
        for live in items:
            self._finish(live, result=reason)
        return len(items)

    def expire_due(self) -> tuple[ConsoleSessionInfo, ...]:
        """End sessions that hit a limit. Returns what was ended, and why."""

        now = self._clock()
        ended: list[ConsoleSessionInfo] = []
        with self._lock:
            for session_id, live in list(self._sessions.items()):
                reason = self._expiry_reason(live, now)
                if reason is None:
                    continue
                self._sessions.pop(session_id, None)
                ended.append(self._finish(live, result=reason))
        return tuple(ended)

    def _expiry_reason(self, live: _LiveSession, now: datetime) -> str | None:
        if self._max_duration and now - live.opened_at >= timedelta(
            seconds=self._max_duration
        ):
            return "maximum session duration reached"
        if self._idle and now - live.last_activity >= timedelta(seconds=self._idle):
            return "idle timeout"
        # A session whose SSH channel died (device rebooted, tab closed and
        # the far end noticed) is not "open" just because we still hold it.
        session = live.session
        try:
            if not session.connected:
                return "device disconnected"
        except Exception:  # noqa: BLE001
            return "device disconnected"
        return None

    def _reap(self, now: datetime) -> None:
        """Drop expired sessions. Caller holds the lock."""

        for session_id, live in list(self._sessions.items()):
            if self._expiry_reason(live, now) is not None:
                self._sessions.pop(session_id, None)
                # Close outside of the audit path to keep _reap cheap; the
                # session's own close() is idempotent.
                try:
                    live.session.close()
                except Exception:  # noqa: BLE001
                    pass

    def _finish(self, live: _LiveSession, *, result: str) -> ConsoleSessionInfo:
        try:
            live.session.close()
        except Exception:  # noqa: BLE001
            pass
        live.state = SESSION_CLOSED if "fail" not in result else SESSION_FAILED
        live.result = result
        live.closed_at = self._clock()
        self._record("disconnected", live, result=result)
        return live.info()

    def _record(self, event: str, live: _LiveSession, *, result: str) -> None:
        if self._audit is None:
            return
        self._audit.record(
            event,
            session_id=live.session_id,
            operator=live.operator,
            device_id=live.device_id,
            hostname=live.hostname,
            management_ip=live.management_ip,
            port=live.port,
            credential_ref=live.credential_ref,
            result=result,
        )
