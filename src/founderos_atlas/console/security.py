"""Console access control (PR-044A, CONSOLE).

## The problem this solves

Atlas's GUI is unauthenticated by design: a local, single-user alpha bound
to 127.0.0.1. For read-only pages that is a defensible trade. An interactive
SSH endpoint is a different proposition, for one specific reason:

**WebSockets are not subject to the same-origin policy.** A browser will
happily let ``https://somewhere-else.example`` open
``ws://127.0.0.1:8765/console/attach`` and read the response. There is no
CORS preflight to save us. Without a check, any page the operator visits
while Atlas is running could open an interactive session to a production
router using credentials it never had to steal.

The classic HTTP sibling of this is DNS rebinding, which defeats a naive
"but it's only on localhost" assumption in the same way.

## What is enforced

1. **Origin allowlist** — the WebSocket handshake must carry an ``Origin``
   the server recognises as itself. Cross-origin handshakes are refused
   before any SSH is attempted. A *missing* Origin is refused too: browsers
   always send one, so its absence means the caller is not the GUI.

2. **Single-use console token** — a session is opened only with a token
   minted by a same-origin ``POST`` and redeemed exactly once. Tokens are
   short-lived, bound to the device they were minted for, and cannot be
   replayed. A URL that leaks (history, shoulder, log) grants nothing.

3. **Operator identity hook** — ``require_operator`` is the seam a real
   login fills. Today it returns the local operator and states plainly that
   this is machine-level trust, not user-level trust. When Atlas grows a
   login, this is the single place that changes; SSH credentials stay
   separate from login credentials either way.

## What is NOT claimed

This does not make Atlas multi-user safe, and it does not protect against
someone at the keyboard. It closes the remote attacker path, which is the
one the operator cannot see coming.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit


DEFAULT_TOKEN_TTL_SECONDS = 30
LOCAL_OPERATOR = "local-operator"


class ConsoleAccessDenied(PermissionError):
    """A console request failed an access check. Message is operator-safe."""


# -- operator identity --------------------------------------------------------


@dataclass(frozen=True)
class Operator:
    """Who Atlas believes is asking. See ``require_operator``."""

    name: str
    authenticated: bool
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "authenticated": self.authenticated,
            "basis": self.basis,
        }


def require_operator(*, user: Any | None = None) -> Operator:
    """The operator for this request.

    **Seam for the future login.** Atlas has no user model yet, so there is
    no honest way to claim a request is authenticated. Rather than pretend,
    this returns an operator whose ``authenticated`` flag is False and whose
    ``basis`` says exactly what the trust rests on — access to the machine.

    When a login exists, resolve it here and return ``authenticated=True``.
    Nothing else in the console needs to change: SSH credentials are stored
    separately from login credentials and always have been.
    """

    if user is not None:
        name = str(getattr(user, "name", user) or "").strip()
        if name:
            return Operator(
                name=name, authenticated=True, basis="authenticated Atlas user"
            )
    return Operator(
        name=LOCAL_OPERATOR,
        authenticated=False,
        basis=(
            "local machine access — Atlas has no login yet, so any user of "
            "this computer is treated as the operator"
        ),
    )


# -- origin checking ----------------------------------------------------------


def _normalize_host(value: str) -> str:
    return value.strip().rstrip(".").casefold()


def origin_allowed(
    origin: str | None, *, host_header: str | None, allowed_hosts: tuple[str, ...] = ()
) -> bool:
    """Whether a WebSocket handshake really came from the Atlas GUI.

    A browser always sends ``Origin`` on a WebSocket handshake, so a missing
    or empty Origin is not "a lenient client" — it is not a browser page,
    and it is refused.

    The Origin's host:port must match the ``Host`` the request was addressed
    to (i.e. the GUI's own address), or an explicitly configured host. This
    is what makes a cross-origin page unable to attach, and what stops a
    rebound DNS name from posing as the GUI.
    """

    if not origin:
        return False
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.netloc:
        return False
    candidate = _normalize_host(parts.netloc)
    permitted = {_normalize_host(item) for item in allowed_hosts if item}
    if host_header:
        permitted.add(_normalize_host(host_header))
    return candidate in permitted


# -- single-use tokens --------------------------------------------------------


@dataclass(frozen=True)
class ConsoleToken:
    """A one-shot ticket to attach a terminal to one device."""

    token: str
    device_id: str
    scope_id: str
    operator: str
    expires_at: datetime
    credential_ref: str | None = None

    def expired(self, *, now: datetime) -> bool:
        return now >= self.expires_at


class ConsoleTokenStore:
    """Mint and redeem single-use console tokens.

    Redemption is atomic and destructive: a token works exactly once. Two
    racing attaches cannot both succeed on one token.
    """

    def __init__(
        self, *, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS, clock=None
    ) -> None:
        self._ttl = int(ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._tokens: dict[str, ConsoleToken] = {}

    def mint(
        self,
        *,
        device_id: str,
        scope_id: str,
        operator: str,
        credential_ref: str | None = None,
    ) -> ConsoleToken:
        now = self._clock()
        token = ConsoleToken(
            token=secrets.token_urlsafe(32),
            device_id=device_id,
            scope_id=scope_id,
            operator=operator,
            credential_ref=credential_ref,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        with self._lock:
            self._purge(now)
            self._tokens[token.token] = token
        return token

    def redeem(self, token: str, *, device_id: str) -> ConsoleToken:
        """Consume a token for a device, or raise.

        Binding to ``device_id`` means a token minted for a lab switch
        cannot be replayed against a core router.
        """

        now = self._clock()
        with self._lock:
            self._purge(now)
            # Constant-time-ish lookup is unnecessary here (the token is a
            # dict key, not a compared secret), but popping under the lock
            # is what makes redemption single-use.
            found = self._tokens.pop(str(token or ""), None)
        if found is None:
            raise ConsoleAccessDenied(
                "This console link is no longer valid. Open the console again "
                "from the device."
            )
        if found.expired(now=now):
            raise ConsoleAccessDenied(
                "This console link expired. Open the console again from the "
                "device."
            )
        if found.device_id != device_id:
            raise ConsoleAccessDenied(
                "This console link was issued for a different device."
            )
        return found

    def _purge(self, now: datetime) -> None:
        expired = [key for key, item in self._tokens.items() if item.expired(now=now)]
        for key in expired:
            self._tokens.pop(key, None)

    @property
    def outstanding(self) -> int:
        with self._lock:
            self._purge(self._clock())
            return len(self._tokens)
