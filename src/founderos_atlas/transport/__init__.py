"""Read-only device transports for Atlas live discovery."""

from .base import DeviceCredentials, DeviceTransport, ensure_read_only
from .exceptions import (
    AtlasTransportError,
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    PermissionDeniedError,
    ReadOnlyViolationError,
    SSHUnavailableError,
    TransportDependencyError,
    TransportNotConnectedError,
    UnsupportedPlatformError,
)
from .ssh import SUPPORTED_DEVICE_TYPES, SSHDeviceTransport

__all__ = [
    "AtlasTransportError",
    "AuthenticationError",
    "ConnectionLostError",
    "ConnectionTimeoutError",
    "DeviceCredentials",
    "DeviceTransport",
    "PermissionDeniedError",
    "ReadOnlyViolationError",
    "SSHUnavailableError",
    "SUPPORTED_DEVICE_TYPES",
    "SSHDeviceTransport",
    "TransportDependencyError",
    "TransportNotConnectedError",
    "UnsupportedPlatformError",
    "ensure_read_only",
]
