"""Typed failures for the read-only Atlas device transport layer."""


class AtlasTransportError(Exception):
    """Base failure for read-only Atlas device transports."""


class TransportDependencyError(AtlasTransportError):
    """A dependency required for live transport (e.g. Netmiko) is not installed."""


class TransportNotConnectedError(AtlasTransportError):
    """A command was requested before the transport session was opened."""


class ReadOnlyViolationError(AtlasTransportError):
    """A command was rejected locally because it is not read-only."""


class AuthenticationError(AtlasTransportError):
    """The device rejected the supplied credentials."""


class ConnectionTimeoutError(AtlasTransportError):
    """The device did not respond within the allowed time."""


class SSHUnavailableError(AtlasTransportError):
    """No SSH service was reachable on the target device."""


class UnsupportedPlatformError(AtlasTransportError):
    """The target platform is not supported by this transport."""


class PermissionDeniedError(AtlasTransportError):
    """The device refused a command due to insufficient privileges."""


class ConnectionLostError(AtlasTransportError):
    """The session dropped while commands were executing."""
