"""Enterprise multi-credential strategy: sets, scopes, safe resolution.

Discovery across a real enterprise needs more than one credential — per
vendor, per site, per device role, per administrative domain. This package
models named credential sets whose entries carry a priority and a generic
scope, resolves an ordered, bounded candidate list for each device, tries
candidates safely (no repeats, lockout protection, stop on first success),
and remembers only the credential *reference* that worked. Secrets stay in
the secure credential provider — never on these models, never in metadata,
history, or logs.
"""

from .memory import CredentialSuccessMemory
from .models import (
    CredentialEntry,
    CredentialScope,
    CredentialSet,
    DeviceContext,
)
from .repository import CredentialSetRepository
from .resolver import (
    DEFAULT_MAX_ATTEMPTS,
    CredentialAttempt,
    CredentialCandidate,
    CredentialResolver,
)
from .service import CredentialSetService
from .transport import MultiCredentialTransportFactory

__all__ = [
    "CredentialSetService",
    "CredentialAttempt",
    "CredentialCandidate",
    "CredentialEntry",
    "CredentialResolver",
    "CredentialScope",
    "CredentialSet",
    "CredentialSetRepository",
    "CredentialSuccessMemory",
    "DEFAULT_MAX_ATTEMPTS",
    "DeviceContext",
    "MultiCredentialTransportFactory",
]
