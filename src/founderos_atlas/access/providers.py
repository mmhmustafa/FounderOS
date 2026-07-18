"""Authentication providers: local development, passwords, proxy SSO.

``resolve_auth_mode`` decides the mode once at startup:

- ``local`` — the historical single-operator development mode. The
  request is granted a full-privilege ``local-operator`` principal, but
  ONLY when the client address is loopback: if the server is ever
  exposed beyond the machine, remote clients are refused rather than
  silently trusted. This is the default so existing local workflows and
  the test suite keep working unchanged.
- ``password`` — production mode backed by the workspace user store
  (scrypt hashes) and server-side sessions.
- ``proxy`` — production mode for an SSO-terminating reverse proxy
  (OIDC/SAML happens at the proxy). The proxy asserts the identity in
  a header and must prove itself with a shared secret in another
  header; without that proof the assertion is ignored. Roles come from
  the user store (accounts may be password-less) so the proxy cannot
  invent authority Atlas never granted.

Anything smarter (direct OIDC, SCIM provisioning) belongs behind this
same interface.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from ipaddress import ip_address

from .models import Principal
from .sessions import SessionStore
from .users import UserStore

AUTH_MODES = ("local", "password", "proxy")

PROXY_USER_HEADER = "X-Atlas-Remote-User"
PROXY_SECRET_HEADER = "X-Atlas-Proxy-Secret"


def resolve_auth_mode(explicit: str | None = None) -> str:
    mode = (explicit or os.environ.get("ATLAS_AUTH_MODE") or "local").strip()
    if mode not in AUTH_MODES:
        raise ValueError(
            f"ATLAS_AUTH_MODE must be one of {', '.join(AUTH_MODES)}; "
            f"got {mode!r}."
        )
    return mode


def is_loopback(remote_addr: str | None) -> bool:
    if not remote_addr:
        return False
    try:
        return ip_address(remote_addr).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class AuthDecision:
    """What a provider concluded about one request."""

    principal: Principal | None
    failure: str | None = None      # human-safe reason when refused outright
    needs_login: bool = False       # unauthenticated: send to /login
    session_record: object = None   # live SessionRecord when session-backed


# Headers a proxy uses to describe the client it forwards for. Their
# PRESENCE is the signal local mode acts on; their VALUES are never
# trusted to determine anything.
FORWARDING_HEADERS = (
    "Forwarded",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Proto",
    "X-Forwarded",
    "Forwarded-For",
    "X-Real-IP",
    "X-Client-IP",
    "True-Client-IP",
    "CF-Connecting-IP",
)


class LocalDevelopmentAuth:
    """Loopback-only auto-principal that FAILS CLOSED behind proxies.

    ``request.remote_addr`` being loopback proves only that the TCP peer
    is local — a reverse proxy on the same machine makes every remote
    user look exactly like that. Local mode therefore refuses any
    request that carries proxy/forwarding headers: a proxied request
    announces itself, and announcing yourself to local mode is a
    refusal, not an identity.

    ``allow_forwarded=True`` (``ATLAS_LOCAL_ALLOW_FORWARDED=1``) is the
    one narrow, explicit developer override for tools that add such
    headers on genuinely local traffic (e.g. a localhost TLS dev
    wrapper). It still never grants non-loopback peers anything, never
    reads the header values, and startup logs a prominent warning.
    """

    mode = "local"

    def __init__(self, *, allow_forwarded: bool = False) -> None:
        self.allow_forwarded = allow_forwarded

    def identify(self, request) -> AuthDecision:
        from .models import LOCAL_OPERATOR

        if not is_loopback(request.remote_addr):
            return AuthDecision(
                principal=None,
                failure=(
                    "Local development mode only serves the local machine. "
                    "Run Atlas in a production auth mode "
                    "(ATLAS_AUTH_MODE=password or proxy) to allow other "
                    "clients."
                ),
            )
        if not self.allow_forwarded:
            offered = [
                name for name in FORWARDING_HEADERS
                if request.headers.get(name)
            ]
            if offered:
                return AuthDecision(
                    principal=None,
                    failure=(
                        "Local development mode refuses proxied requests: "
                        f"forwarding header(s) {', '.join(sorted(offered))} "
                        "are present, so this connection is not provably "
                        "the local operator. Serve other users with "
                        "ATLAS_AUTH_MODE=password or proxy. (A deliberate "
                        "local-only dev proxy can set "
                        "ATLAS_LOCAL_ALLOW_FORWARDED=1.)"
                    ),
                )
        return AuthDecision(principal=LOCAL_OPERATOR)

    def login(self, request):  # pragma: no cover - no login page in local mode
        raise NotImplementedError("local mode has no login")


class PasswordAuth:
    """User-store passwords and server-side sessions."""

    mode = "password"

    def __init__(self, users: UserStore, sessions: SessionStore) -> None:
        self.users = users
        self.sessions = sessions

    def identify(self, request) -> AuthDecision:
        from .sessions import SESSION_COOKIE

        record = self.sessions.resolve(request.cookies.get(SESSION_COOKIE))
        if record is None:
            return AuthDecision(principal=None, needs_login=True)
        account = self.users.get(record.username)
        if account is None or account.disabled:
            self.sessions.invalidate_user(record.username)
            return AuthDecision(principal=None, needs_login=True)
        return AuthDecision(
            principal=Principal.for_roles(
                username=account.username,
                display_name=account.display_name,
                roles=account.roles,
                session_id=record.token_hash[:12],
                auth_mode=self.mode,
            ),
            session_record=record,
        )

    def login(self, username: str, password: str) -> str | None:
        """A fresh session token on success (rotation: the login response
        always sets a token no prior request has seen), else None."""

        account = self.users.authenticate(username, password)
        if account is None:
            return None
        return self.sessions.create(account.username, auth_mode=self.mode)


class ProxySSOAuth:
    """Identity asserted by an authenticated reverse proxy.

    The proxy terminates SSO and TLS, then forwards the login in
    ``X-Atlas-Remote-User`` and proves itself in ``X-Atlas-Proxy-Secret``
    (compared with ``secrets.compare_digest``). Requests without a valid
    proof are treated as unauthenticated even if they carry the user
    header — a client talking to Atlas directly cannot impersonate the
    proxy without the secret.
    """

    mode = "proxy"

    def __init__(self, users: UserStore, proxy_secret: str) -> None:
        if not proxy_secret or len(proxy_secret) < 16:
            raise ValueError(
                "Proxy mode requires ATLAS_PROXY_SECRET (>= 16 characters) "
                "shared with the reverse proxy."
            )
        self.users = users
        self._secret = proxy_secret

    def identify(self, request) -> AuthDecision:
        offered = request.headers.get(PROXY_SECRET_HEADER, "")
        if not secrets.compare_digest(offered, self._secret):
            return AuthDecision(
                principal=None,
                failure=(
                    "This deployment only accepts requests through its "
                    "authenticating proxy."
                ),
            )
        username = str(request.headers.get(PROXY_USER_HEADER) or "").strip()
        if not username:
            return AuthDecision(principal=None, needs_login=True)
        account = self.users.get(username)
        if account is None or account.disabled:
            # Authenticated at the proxy but not provisioned in Atlas:
            # refuse with a message that names the fix, grant nothing.
            return AuthDecision(
                principal=None,
                failure=(
                    f"{username} authenticated at the proxy but has no "
                    "Atlas account. A system administrator must create one "
                    "and assign roles."
                ),
            )
        return AuthDecision(principal=Principal.for_roles(
            username=account.username,
            display_name=account.display_name,
            roles=account.roles,
            auth_mode=self.mode,
        ))
