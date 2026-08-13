"""Safe, typed failure classification (PR-179).

Atlas raises a rich hierarchy of typed, operator-safe failures — and the
job layer used to flatten almost all of them into "Discovery failed
unexpectedly". This module is the ONE place that turns an exception into
what the operator is told:

    classify(error) -> FailureVerdict(failure_class, operator_message,
                                      next_action_label, next_action_href,
                                      diagnostic_code, severity)

The trust rule is explicit and non-negotiable:

- ONLY the exception classes in ``_ALLOWLIST`` may surface their own
  message, matched by EXACT type — never by inheritance, never by name,
  never by duck-typing. Every raise site of every allowlisted class was
  audited: their messages are Atlas-authored, secret-free, and written
  for operators (the transport layer already converts foreign
  netmiko/paramiko errors into typed exceptions with canonical text).
- ``WorkspaceCorruptedError`` is allowlisted as a CLASS but its message
  is NOT trusted — it names filesystem paths, so it gets canonical copy.
- Everything else (foreign, wrapped, untyped) keeps the pre-existing
  discipline: its text may be used internally to SELECT an allowlisted
  message (the ``friendly_failure`` substring rules), and is never
  returned, rendered, or persisted.

Severity follows the approved contract: user-correctable and
environmental failures are warnings, unsupported platforms are neutral
(Atlas knowing it cannot collect something is not an Atlas fault),
storage integrity and internal defects are errors. The caller logs the
traceback for INTERNAL verdicts; this module stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass

from founderos_atlas.platforms.registry import (
    UnsupportedPlatformError as DiscoveryUnsupportedPlatformError,
)
from founderos_atlas.transport.exceptions import (
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    PermissionDeniedError,
    SSHUnavailableError,
    TransportDependencyError,
    UnsupportedPlatformError,
)
from founderos_atlas.workspace.exceptions import (
    CredentialNotFoundError,
    CredentialStoreUnavailableError,
    WorkspaceCorruptedError,
)

# Failure classes — the taxonomy the architecture approved.
CLASS_USER_CORRECTABLE = "user-correctable"
CLASS_ENVIRONMENTAL = "environmental"
CLASS_UNSUPPORTED = "unsupported"
CLASS_STORAGE_INTEGRITY = "storage-integrity"
CLASS_INTERNAL = "internal"

SEVERITY_WARNING = "warning"
SEVERITY_NEUTRAL = "neutral"
SEVERITY_ERROR = "error"


@dataclass(frozen=True)
class FailureVerdict:
    """What the operator is told, and nothing else.

    ``operator_message`` is the complete safe sentence; ``next_action``
    is a real Atlas destination (never an invented page);
    ``diagnostic_code`` is the stable, secret-free code persisted to the
    job log for support.
    """

    failure_class: str
    operator_message: str
    diagnostic_code: str
    severity: str
    next_action_label: str | None = None
    next_action_href: str | None = None


# key: the EXACT exception type. value: (failure_class, severity,
# diagnostic_code, trust_own_message, next_action_label, next_action_href,
# canonical_message-or-None).
_ALLOWLIST: dict[type, tuple] = {
    CredentialNotFoundError: (
        CLASS_USER_CORRECTABLE, SEVERITY_WARNING, "credential-missing",
        True, "Edit the profile", "/profiles", None,
    ),
    CredentialStoreUnavailableError: (
        CLASS_USER_CORRECTABLE, SEVERITY_WARNING,
        "credential-provider-unavailable",
        # §6: the shipped copy for this condition was audited CORRECT
        # and stays unchanged. Raise sites (including third-party
        # keyring adapters) can be terse ("no secure credential
        # store"), so the canonical sentence with its remedy wins.
        False, "Open Settings", "/settings",
        "Secure credential storage is unavailable. Check Atlas "
        "Settings, or reinstall the credential backend with: pip "
        'install "founderos-runtime[credentials]"',
    ),
    AuthenticationError: (
        CLASS_USER_CORRECTABLE, SEVERITY_WARNING, "authentication-failed",
        True, "Review credentials", "/credentials", None,
    ),
    PermissionDeniedError: (
        CLASS_USER_CORRECTABLE, SEVERITY_WARNING, "privilege-refused",
        True, "Review credentials", "/credentials", None,
    ),
    TransportDependencyError: (
        CLASS_USER_CORRECTABLE, SEVERITY_WARNING, "transport-dependency-missing",
        True, None, None, None,
    ),
    SSHUnavailableError: (
        CLASS_ENVIRONMENTAL, SEVERITY_WARNING, "ssh-unavailable",
        True, None, None, None,
    ),
    ConnectionTimeoutError: (
        CLASS_ENVIRONMENTAL, SEVERITY_WARNING, "connection-timeout",
        True, None, None, None,
    ),
    ConnectionLostError: (
        CLASS_ENVIRONMENTAL, SEVERITY_WARNING, "connection-lost",
        True, None, None, None,
    ),
    UnsupportedPlatformError: (
        CLASS_UNSUPPORTED, SEVERITY_NEUTRAL, "platform-unsupported",
        True, None, None, None,
    ),
    DiscoveryUnsupportedPlatformError: (
        CLASS_UNSUPPORTED, SEVERITY_NEUTRAL, "platform-unsupported",
        True, None, None, None,
    ),
    WorkspaceCorruptedError: (
        CLASS_STORAGE_INTEGRITY, SEVERITY_ERROR, "workspace-corrupted",
        # Its message names filesystem paths — NEVER surfaced.
        False, "Check system integrity", "/system/integrity",
        "A stored Atlas file could not be read. Existing network evidence "
        "is unaffected; open System Integrity to see which file and what "
        "to do about it.",
    ),
}

_INTERNAL_MESSAGE = (
    "Atlas could not complete this discovery — an internal error occurred. "
    "Results already collected were preserved."
)


def classify(
    error: BaseException,
    *,
    profile_name: str = "",
    management_ip: str | None = None,
) -> FailureVerdict:
    """The operator-facing verdict for one failure.

    Exact-type allowlist first; the legacy substring selector second
    (it only ever SELECTS canonical copy — foreign text is never
    returned); a safe internal verdict last. Callers log ``exc_info``
    for INTERNAL verdicts — this function never logs and never returns
    foreign text.
    """

    entry = _ALLOWLIST.get(type(error))
    if entry is None:
        # The live pipeline wraps failures before the job layer sees
        # them — ``raise CliError(str(error)) from error`` — so on that
        # path the wrapper's TYPE says nothing while the typed original
        # still sits on the explicit-cause chain (measured: a live
        # seed-connect AuthenticationError arrived here as CliError).
        # Walk ``__cause__`` only — never ``__context__``, which is
        # implicit and can be anything active during handling — and
        # apply the same exact-type rule to what is found there. The
        # cause instance IS the object the audited raise site created,
        # so the trust decision is identical; inheritance still grants
        # nothing at any depth.
        seen: set[int] = set()
        cause = getattr(error, "__cause__", None)
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            entry = _ALLOWLIST.get(type(cause))
            if entry is not None:
                error = cause
                break
            cause = getattr(cause, "__cause__", None)
    if entry is not None:
        (failure_class, severity, code, trust_message,
         action_label, action_href, canonical) = entry
        if trust_message:
            message = str(error).strip() or canonical or _INTERNAL_MESSAGE
        else:
            message = canonical
        return FailureVerdict(
            failure_class=failure_class,
            operator_message=message,
            diagnostic_code=code,
            severity=severity,
            next_action_label=action_label,
            next_action_href=action_href,
        )

    # Foreign/untyped: the text SELECTS one of the pre-existing
    # allowlisted messages (web/jobs.friendly_failure) and is then
    # discarded. Imported lazily to avoid an import cycle with jobs.py.
    from .jobs import friendly_failure

    detail = str(error) or type(error).__name__
    message, code = friendly_failure(detail, profile_name, management_ip)
    if code == "discovery-failed":
        # The selector had nothing specific: this is an INTERNAL defect
        # (or something Atlas cannot distinguish from one). The caller
        # logs the traceback; the operator gets truth without internals.
        return FailureVerdict(
            failure_class=CLASS_INTERNAL,
            operator_message=_INTERNAL_MESSAGE,
            diagnostic_code="internal-error",
            severity=SEVERITY_ERROR,
        )
    known = {
        "authentication-failed": (
            CLASS_USER_CORRECTABLE, SEVERITY_WARNING,
            "Review credentials", "/credentials",
        ),
        "credential-provider-unavailable": (
            CLASS_USER_CORRECTABLE, SEVERITY_WARNING,
            "Open Settings", "/settings",
        ),
        "connection-timeout": (
            CLASS_ENVIRONMENTAL, SEVERITY_WARNING, None, None,
        ),
        "host-key-verification-failed": (
            CLASS_ENVIRONMENTAL, SEVERITY_WARNING, None, None,
        ),
    }
    failure_class, severity, action_label, action_href = known[code]
    return FailureVerdict(
        failure_class=failure_class,
        operator_message=message,
        diagnostic_code=code,
        severity=severity,
        next_action_label=action_label,
        next_action_href=action_href,
    )
