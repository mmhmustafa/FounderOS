"""Atlas Console — engineer-controlled interactive SSH (PR-044A, CONSOLE).

An engineer should not have to copy an IP out of Atlas, find the credential,
and hand-build an SSH command in another window. This package lets them open
a session from wherever the device appears — while Atlas keeps hold of the
two things it must not give away: the canonical identity of the device, and
the secret used to reach it.

Three rules shape everything here:

1. **Only verified management endpoints.** A router ID, BGP peer, next hop,
   loopback or unresolved peer is a protocol fact, not a way in. See
   ``resolve``.
2. **Secrets stay server-side.** The browser gets a terminal and bytes; the
   password is read from the credential store at connect time and never
   leaves the process. See ``session`` and ``security``.
3. **The engineer is in control.** Atlas opens no session on its own, and
   executes no command on its own. What is typed is the operator's, and is
   neither filtered nor recorded. See ``session.ConsoleSession.write``.
"""

from __future__ import annotations

from .audit import ConsoleAuditLog
from .hostkeys import HostKeyStore, HostKeyStoreError, fingerprint_sha256
from .manager import (
    ConsoleLimitReached,
    ConsoleSessionManager,
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_DURATION_SECONDS,
)
from .models import (
    ACTION_AUTH_FAILED,
    ACTION_AVAILABLE,
    ACTION_CONNECTED,
    ACTION_CONNECTING,
    ACTION_CREDENTIAL_REQUIRED,
    ACTION_ENDPOINT_UNKNOWN,
    ACTION_EXPLANATIONS,
    ACTION_HOST_KEY_CHANGED,
    ACTION_SESSION_ENDED,
    ACTION_UNSUPPORTED_TRANSPORT,
    ENDPOINT_VERIFIED_BY_DISCOVERY,
    HOST_KEY_CHANGED,
    HOST_KEY_KNOWN,
    HOST_KEY_NEW,
    INELIGIBLE_EVIDENCE,
    ConsoleSessionInfo,
    ConsoleTarget,
    HostKeyVerdict,
    SESSION_CLOSED,
    SESSION_CONNECTED,
    SESSION_CONNECTING,
    SESSION_FAILED,
)
from .resolve import find_target, resolve_target, resolve_targets
from .security import (
    ConsoleAccessDenied,
    ConsoleToken,
    ConsoleTokenStore,
    DEFAULT_TOKEN_TTL_SECONDS,
    LOCAL_OPERATOR,
    Operator,
    origin_allowed,
    require_operator,
)
from .session import (
    ConsoleAuthenticationError,
    ConsoleHostKeyBlocked,
    ConsoleHostKeyUnknown,
    ConsoleSession,
    ConsoleSessionError,
    ConsoleTimeoutError,
    probe_host_key,
)


__all__ = [
    "ACTION_AUTH_FAILED",
    "ACTION_AVAILABLE",
    "ACTION_CONNECTED",
    "ACTION_CONNECTING",
    "ACTION_CREDENTIAL_REQUIRED",
    "ACTION_ENDPOINT_UNKNOWN",
    "ACTION_EXPLANATIONS",
    "ACTION_HOST_KEY_CHANGED",
    "ACTION_SESSION_ENDED",
    "ACTION_UNSUPPORTED_TRANSPORT",
    "ConsoleAccessDenied",
    "ConsoleAuditLog",
    "ConsoleAuthenticationError",
    "ConsoleHostKeyBlocked",
    "ConsoleHostKeyUnknown",
    "ConsoleLimitReached",
    "ConsoleSession",
    "ConsoleSessionError",
    "ConsoleSessionInfo",
    "ConsoleSessionManager",
    "ConsoleTarget",
    "ConsoleTimeoutError",
    "ConsoleToken",
    "ConsoleTokenStore",
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_MAX_DURATION_SECONDS",
    "DEFAULT_TOKEN_TTL_SECONDS",
    "ENDPOINT_VERIFIED_BY_DISCOVERY",
    "HOST_KEY_CHANGED",
    "HOST_KEY_KNOWN",
    "HOST_KEY_NEW",
    "HostKeyStore",
    "HostKeyStoreError",
    "HostKeyVerdict",
    "INELIGIBLE_EVIDENCE",
    "LOCAL_OPERATOR",
    "Operator",
    "SESSION_CLOSED",
    "SESSION_CONNECTED",
    "SESSION_CONNECTING",
    "SESSION_FAILED",
    "fingerprint_sha256",
    "find_target",
    "origin_allowed",
    "probe_host_key",
    "require_operator",
    "resolve_target",
    "resolve_targets",
]
