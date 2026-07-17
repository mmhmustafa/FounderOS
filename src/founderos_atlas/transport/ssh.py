"""Netmiko-backed read-only SSH transport for Cisco IOS/IOS-XE devices."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .base import DeviceCredentials, DeviceTransport, ensure_read_only
from .exceptions import (
    AtlasTransportError,
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    PermissionDeniedError,
    SSHUnavailableError,
    TransportDependencyError,
    TransportNotConnectedError,
    UnsupportedPlatformError,
)


# PR-049 (POLYGLOT): the session personality is chosen by the platform
# driver, never hardcoded here. Each entry is a netmiko device_type whose
# prompt handling, pagination and timing netmiko already knows.
SUPPORTED_DEVICE_TYPES = (
    "cisco_ios",
    "cisco_xe",
    "cisco_nxos",
    "arista_eos",
    "juniper_junos",
)

_AUTH_EXCEPTION_NAMES = frozenset(
    {"NetmikoAuthenticationException", "AuthenticationException"}
)
_TIMEOUT_EXCEPTION_NAMES = frozenset({"NetmikoTimeoutException", "ReadTimeout"})
_PERMISSION_MARKERS = (
    "% permission denied",
    "% authorization failed",
    "command authorization failed",
    "% this command is not authorized",
)
_UNSUPPORTED_MARKERS = ("invalid input detected", "% unknown command")

# Session-scoped output settings sent once after connect. These do not enter
# configuration mode and do not change device configuration; devices that do
# not support them are tolerated.
_SESSION_SETUP_COMMANDS = ("terminal length 0",)


class _Connection(Protocol):
    def send_command(self, command: str, **kwargs: Any) -> Any: ...

    def disconnect(self) -> None: ...


ConnectionFactory = Callable[..., _Connection]


class SSHDeviceTransport(DeviceTransport):
    """Read-only SSH session with any reachable Cisco IOS/IOS-XE device.

    The transport stays in exec mode for its whole lifetime: it never calls
    enable(), never opens configuration mode, and rejects non-'show' commands
    before they reach the wire.
    """

    def __init__(
        self,
        credentials: DeviceCredentials,
        *,
        device_type: str = "cisco_ios",
        # PR-043.6 (FALCON): aggressive-but-configurable defaults. The
        # reachability probe already screens dead addresses, so a live
        # host that answered the probe but stalls the SSH handshake fails
        # in seconds rather than the old 15s. Override per profile when a
        # slow-WAN device needs more headroom.
        connect_timeout: float = 5.0,
        command_timeout: float = 30.0,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if not isinstance(credentials, DeviceCredentials):
            raise TypeError("credentials must be DeviceCredentials")
        if device_type not in SUPPORTED_DEVICE_TYPES:
            raise UnsupportedPlatformError(
                f"Unsupported device platform {device_type!r}. "
                f"Supported platforms: {', '.join(SUPPORTED_DEVICE_TYPES)}."
            )
        self._credentials = credentials
        self._device_type = device_type
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        self._connection_factory = connection_factory
        self._connection: _Connection | None = None

    @property
    def host(self) -> str:
        return self._credentials.host

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(host={self._credentials.host!r}, "
            f"port={self._credentials.port}, device_type={self._device_type!r})"
        )

    def connect(self) -> None:
        if self._connection is not None:
            return
        factory = self._connection_factory or _netmiko_connect_handler()
        try:
            self._connection = factory(
                device_type=self._device_type,
                host=self._credentials.host,
                port=self._credentials.port,
                username=self._credentials.username,
                password=self._credentials.password,
                conn_timeout=self._connect_timeout,
            )
        except AtlasTransportError:
            raise
        except Exception as error:
            raise _classify_connect_error(error, self._credentials.host) from error
        self._prepare_session()

    def _prepare_session(self) -> None:
        """Disable output paging where supported; continue safely where not."""

        connection = self._connection
        if connection is None:
            return
        for command in _SESSION_SETUP_COMMANDS:
            try:
                connection.send_command(command, read_timeout=self._command_timeout)
            except Exception:
                # Best effort only: collection still works on devices where
                # paging setup is unsupported (Netmiko also disables paging).
                continue

    def disconnect(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.disconnect()
        except Exception:
            # A failed teardown must never mask already-collected results.
            pass

    def execute(self, command: str) -> str:
        normalized = ensure_read_only(command)
        if self._connection is None:
            raise TransportNotConnectedError(
                "Transport is not connected. Call connect() first."
            )
        try:
            output = self._connection.send_command(
                normalized, read_timeout=self._command_timeout
            )
        except AtlasTransportError:
            raise
        except Exception as error:
            raise _classify_command_error(
                error, self._credentials.host, normalized
            ) from error
        text = str(output)
        _ensure_command_permitted(text, normalized, self._credentials.host)
        return text


def _netmiko_connect_handler() -> ConnectionFactory:
    try:
        from netmiko import ConnectHandler
    except ImportError as error:
        raise TransportDependencyError(
            "Netmiko is required for live SSH discovery. "
            "Install it with: pip install netmiko"
        ) from error
    return ConnectHandler


def _exception_names(error: BaseException) -> frozenset[str]:
    return frozenset(cls.__name__ for cls in type(error).__mro__)


def _classify_connect_error(error: BaseException, host: str) -> AtlasTransportError:
    names = _exception_names(error)
    text = str(error).casefold()
    if names & _AUTH_EXCEPTION_NAMES:
        return AuthenticationError(
            f"Authentication failed for {host}. Verify the username and password."
        )
    if "unsupported" in text and "device_type" in text:
        return UnsupportedPlatformError(
            f"The requested platform is not supported for {host}."
        )
    if isinstance(error, ConnectionRefusedError) or "refused" in text:
        return SSHUnavailableError(
            f"SSH is unavailable on {host}. The connection was refused; "
            "verify SSH is enabled on port 22."
        )
    if (
        names & _TIMEOUT_EXCEPTION_NAMES
        or isinstance(error, TimeoutError)
        or "time" in text
    ):
        return ConnectionTimeoutError(
            f"Connection to {host} timed out. Verify the device is reachable "
            "and SSH is enabled."
        )
    if isinstance(error, OSError):
        return SSHUnavailableError(
            f"Could not reach SSH on {host}. Verify the management IP and network path."
        )
    return SSHUnavailableError(f"Could not open an SSH session with {host}.")


def _classify_command_error(
    error: BaseException, host: str, command: str
) -> AtlasTransportError:
    names = _exception_names(error)
    if names & _TIMEOUT_EXCEPTION_NAMES or isinstance(error, TimeoutError):
        return ConnectionTimeoutError(
            f"Device {host} did not finish {command!r} in time."
        )
    return ConnectionLostError(
        f"The connection to {host} was lost while running {command!r}."
    )


def _ensure_command_permitted(output: str, command: str, host: str) -> None:
    lowered = output.casefold()
    if any(marker in lowered for marker in _PERMISSION_MARKERS):
        raise PermissionDeniedError(
            f"Device {host} denied {command!r}. The account lacks the privilege "
            "required to run it."
        )
    if any(marker in lowered for marker in _UNSUPPORTED_MARKERS):
        raise UnsupportedPlatformError(
            f"Device {host} did not recognize {command!r}. The platform does "
            "not support this command dialect."
        )
