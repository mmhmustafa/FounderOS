"""Atlas Management — verified web management access (PR-044B, PORTAL).

A companion to the console. Where `console/` opens an SSH session to a
device's verified management endpoint, `management/` opens that device's web
management interface — from the same canonical identity, with the same
honesty about what has and has not been proven.

Two rules carry over unchanged, and one is new:

1. **Only a verified management endpoint.** A router ID, BGP peer, next hop,
   unverified loopback, or unresolved peer is never the base for a web URL.
   Reused from `console.resolve`, not re-derived.
2. **No credential ever leaves Atlas.** A URL never carries one, Atlas never
   auto-submits stored credentials into a device UI, and the audit records
   the URL and outcome, never a password, cookie, or form field.
3. **A listening port is only a candidate.** "Verified" means the service
   answered as a web interface — and Atlas never claims a TLS certificate is
   safe when it has not checked it, nor suppresses the browser's own warning.
"""

from __future__ import annotations

from .certs import inspect_certificate
from .models import (
    DEFAULT_HTTP_PORTS,
    DEFAULT_HTTPS_PORTS,
    PROTOCOL_HTTP,
    PROTOCOL_HTTPS,
    STATE_EXPLANATIONS,
    STATE_HTTP_VERIFIED,
    STATE_HTTPS_VERIFIED,
    STATE_NOT_VERIFIED,
    ManagementService,
    TlsCertificate,
    VERIFICATION_CANDIDATE,
    VERIFICATION_OPERATOR,
    VERIFICATION_VERIFIED,
    WebAccess,
)
from .resolve import resolve_web_access
from .store import ManagementServiceStore
from .verify import (
    DEFAULT_CONNECT_TIMEOUT,
    WebServiceVerifier,
    detect_certificate_change,
)


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_HTTP_PORTS",
    "DEFAULT_HTTPS_PORTS",
    "ManagementService",
    "ManagementServiceStore",
    "PROTOCOL_HTTP",
    "PROTOCOL_HTTPS",
    "STATE_EXPLANATIONS",
    "STATE_HTTPS_VERIFIED",
    "STATE_HTTP_VERIFIED",
    "STATE_NOT_VERIFIED",
    "TlsCertificate",
    "VERIFICATION_CANDIDATE",
    "VERIFICATION_OPERATOR",
    "VERIFICATION_VERIFIED",
    "WebAccess",
    "WebServiceVerifier",
    "detect_certificate_change",
    "inspect_certificate",
    "resolve_web_access",
]
