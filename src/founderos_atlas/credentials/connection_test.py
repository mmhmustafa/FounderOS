"""Honest, layered credential connection testing.

"Test secure store" proves only that a reference is readable. This is
the separate, honest *connection* test: against an EXPLICIT authorized
target, resolve the credential without exposing it, then attempt the
minimum safe read-only identity operation and report exactly how far it
got — never inventing success it did not observe.

Outcome ladder (each stage only attempted if the previous passed):

    provider-unreadable  → the secret reference could not be resolved
    unreachable          → no transport reached the target
    transport-failed     → reached but the session could not be opened
    auth-failed          → the device refused the credentials
    unsupported-platform → connected but the platform is not supported
    authorization-insufficient → signed in but denied the identity read
    authenticated        → signed in; identity NOT yet confirmed
    identified           → signed in AND the device returned its identity

The command bodies, passwords, tokens, and keys are never logged; the
audit event records the target, outcome, and platform label only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from founderos_atlas.transport.exceptions import (
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    PermissionDeniedError,
    SSHUnavailableError,
    TransportDependencyError,
    UnsupportedPlatformError,
)

OUTCOME_PROVIDER_UNREADABLE = "provider-unreadable"
OUTCOME_UNREACHABLE = "unreachable"
OUTCOME_TRANSPORT_FAILED = "transport-failed"
OUTCOME_AUTH_FAILED = "auth-failed"
OUTCOME_UNSUPPORTED = "unsupported-platform"
OUTCOME_AUTHZ_INSUFFICIENT = "authorization-insufficient"
OUTCOME_AUTHENTICATED = "authenticated"
OUTCOME_IDENTIFIED = "identified"

# The minimal, universally read-only identity probe. Overridden nowhere:
# a connection test must not run anything platform-specific or writeful.
_IDENTITY_COMMAND = "show version"

_SUCCESS_OUTCOMES = frozenset({OUTCOME_AUTHENTICATED, OUTCOME_IDENTIFIED})


@dataclass(frozen=True)
class ConnectionTestResult:
    outcome: str
    reachable: bool
    provider_readable: bool
    authenticated: bool
    platform: str | None = None
    detail: str = ""
    tested_at: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.outcome in _SUCCESS_OUTCOMES

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reachable": self.reachable,
            "provider_readable": self.provider_readable,
            "authenticated": self.authenticated,
            "platform": self.platform,
            "detail": self.detail,
            "tested_at": self.tested_at,
            "succeeded": self.succeeded,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identity_label(output: str) -> str | None:
    """A short, safe platform label from an identity banner — never the
    whole output (which could carry sensitive config-adjacent detail)."""

    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return None


def test_connection(
    *,
    target: str,
    credential_ref: str,
    provider,
    transport_factory,
    username: str | None = None,
) -> ConnectionTestResult:
    """Resolve the credential and probe ``target`` read-only.

    ``transport_factory(config)`` returns a :class:`DeviceTransport`;
    ``config`` carries ``host``, ``username``, ``password``, and the
    caller's timeout. The password is held only in locals here and is
    never returned, logged, or placed on the result.
    """

    if not str(target or "").strip():
        raise ValueError("a connection test needs an explicit target")

    tested_at = _now()
    password = None
    try:
        password = provider.get(credential_ref)
    except Exception:
        return ConnectionTestResult(
            outcome=OUTCOME_PROVIDER_UNREADABLE,
            reachable=False, provider_readable=False, authenticated=False,
            detail="The secure provider could not resolve the credential "
                   "reference.",
            tested_at=tested_at,
        )
    if not password:
        return ConnectionTestResult(
            outcome=OUTCOME_PROVIDER_UNREADABLE,
            reachable=False, provider_readable=False, authenticated=False,
            detail="The credential reference resolved to an empty secret.",
            tested_at=tested_at,
        )

    config = type("ConnTestConfig", (), {})()
    config.host = str(target).strip()
    config.username = str(username or "").strip() or "atlas"
    config.password = password

    try:
        transport = transport_factory(config)
    except TransportDependencyError as error:
        password = None
        config.password = None
        return ConnectionTestResult(
            outcome=OUTCOME_TRANSPORT_FAILED,
            reachable=False, provider_readable=True, authenticated=False,
            detail=f"Transport unavailable: {error}",
            tested_at=tested_at,
        )
    except Exception:
        password = None
        config.password = None
        return ConnectionTestResult(
            outcome=OUTCOME_TRANSPORT_FAILED,
            reachable=False, provider_readable=True, authenticated=False,
            detail="The transport could not be initialised for the target.",
            tested_at=tested_at,
        )
    finally:
        password = None
        config.password = None

    try:
        transport.connect()
    except (SSHUnavailableError, ConnectionTimeoutError) as error:
        return ConnectionTestResult(
            outcome=OUTCOME_UNREACHABLE,
            reachable=False, provider_readable=True, authenticated=False,
            detail=f"No SSH service responded at the target: "
                   f"{type(error).__name__}.",
            tested_at=tested_at,
        )
    except AuthenticationError:
        return ConnectionTestResult(
            outcome=OUTCOME_AUTH_FAILED,
            reachable=True, provider_readable=True, authenticated=False,
            detail="The target was reached but rejected the credentials.",
            tested_at=tested_at,
        )
    except UnsupportedPlatformError:
        transport.disconnect()
        return ConnectionTestResult(
            outcome=OUTCOME_UNSUPPORTED,
            reachable=True, provider_readable=True, authenticated=True,
            detail="Connected, but the platform is not supported.",
            tested_at=tested_at,
        )
    except Exception as error:
        return ConnectionTestResult(
            outcome=OUTCOME_TRANSPORT_FAILED,
            reachable=True, provider_readable=True, authenticated=False,
            detail=f"The session could not be opened: "
                   f"{type(error).__name__}.",
            tested_at=tested_at,
        )

    # Signed in. Attempt the minimum identity read; distinguish
    # authorization failure from a confirmed identity.
    try:
        output = transport.execute(_IDENTITY_COMMAND)
        platform = _identity_label(output)
        return ConnectionTestResult(
            outcome=OUTCOME_IDENTIFIED,
            reachable=True, provider_readable=True, authenticated=True,
            platform=platform,
            detail="Authenticated and the device returned its identity.",
            tested_at=tested_at,
        )
    except (PermissionDeniedError,) as error:
        return ConnectionTestResult(
            outcome=OUTCOME_AUTHZ_INSUFFICIENT,
            reachable=True, provider_readable=True, authenticated=True,
            detail="Authenticated, but the account cannot run the identity "
                   "command — authorization is insufficient.",
            tested_at=tested_at,
        )
    except (ConnectionLostError, ConnectionTimeoutError):
        return ConnectionTestResult(
            outcome=OUTCOME_AUTHENTICATED,
            reachable=True, provider_readable=True, authenticated=True,
            detail="Authenticated, but the session dropped before the "
                   "identity read completed.",
            tested_at=tested_at,
        )
    except Exception:
        return ConnectionTestResult(
            outcome=OUTCOME_AUTHENTICATED,
            reachable=True, provider_readable=True, authenticated=True,
            detail="Authenticated; the identity command did not complete.",
            tested_at=tested_at,
        )
    finally:
        try:
            transport.disconnect()
        except Exception:  # pragma: no cover - best-effort teardown
            pass
