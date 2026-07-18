"""Server-side interactive SSH session (PR-044A, CONSOLE).

The browser never speaks SSH. Atlas holds the SSH connection; the browser
holds a terminal that exchanges *bytes* over a WebSocket. That is what keeps
the password server-side: it is read from the credential store here, handed
to paramiko here, and never serialised anywhere a browser, URL, or log can
see it.

This is deliberately **not** ``transport/ssh.py``. That transport is
read-only by contract: ``ensure_read_only`` rejects anything but ``show``
before it reaches the wire, because *Atlas* must never change a device on
its own initiative. A console is the opposite case — a human typing, in
control, who may legitimately enter configuration mode. Atlas's read-only
posture governs what Atlas does autonomously, not what an engineer does with
their own hands. Reusing the read-only transport here would be wrong in both
directions: it would block a legitimate operator, and it would blur a
guarantee that matters.

Platform-independent by design: the console carries bytes. Platform drivers
own discovery and structured evidence; they have no say in what a terminal
does. IOS, IOS-XE, FRR (vtysh), NX-OS, Junos, EOS and a plain Linux shell
all work the same way here, because none of them are parsed.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .models import HostKeyVerdict


class ConsoleSessionError(RuntimeError):
    """An operator-safe console failure. Never carries a trace."""


class ConsoleAuthenticationError(ConsoleSessionError):
    pass


class ConsoleTimeoutError(ConsoleSessionError):
    pass


class ConsoleHostKeyBlocked(ConsoleSessionError):
    """The device's host key changed; the connection was refused."""

    def __init__(self, verdict: HostKeyVerdict) -> None:
        super().__init__(verdict.message)
        self.verdict = verdict


class ConsoleHostKeyUnknown(ConsoleSessionError):
    """The device's host key has never been accepted."""

    def __init__(self, verdict: HostKeyVerdict) -> None:
        super().__init__(verdict.message)
        self.verdict = verdict


class _VerifyingPolicy:
    """Paramiko host-key policy backed by Atlas's own trust store.

    Paramiko's ``AutoAddPolicy`` — the usual default, and effectively what
    Atlas's discovery does today — accepts anything. That is exactly the
    behaviour this PR exists to remove for interactive sessions.
    """

    def __init__(self, store, *, host: str, port: int, allow_new: bool) -> None:
        self._store = store
        self._host = host
        self._port = port
        self._allow_new = allow_new
        self.verdict: HostKeyVerdict | None = None

    def missing_host_key(self, client, hostname, key) -> None:  # noqa: ARG002
        verdict = self._store.verify(
            self._host, self._port, key.get_name(), key.asbytes()
        )
        self.verdict = verdict
        if verdict.status == "changed":
            raise ConsoleHostKeyBlocked(verdict)
        if verdict.status == "new" and not self._allow_new:
            raise ConsoleHostKeyUnknown(verdict)
        # 'known', or 'new' with the operator's explicit acceptance in hand.


class ConsoleSession:
    """One interactive SSH session, owned by the server.

    Thread-safety: ``write``/``resize``/``close`` may be called from the
    WebSocket thread while ``read`` runs in the pump thread. paramiko's
    channel is safe for concurrent read/write; the lock guards our own
    lifecycle flags.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key_store,
        allow_new_host_key: bool = False,
        connect_timeout: float = 10.0,
        client_factory: Callable[[], Any] | None = None,
        term: str = "xterm-256color",
        width: int = 80,
        height: int = 24,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        # Held only for the duration of connect(); never stored on any object
        # that is serialised, logged, or returned to a route.
        self._password = password
        self._store = host_key_store
        self._allow_new_host_key = allow_new_host_key
        self._connect_timeout = connect_timeout
        self._client_factory = client_factory
        self._term = term
        self._width = width
        self._height = height

        self._client: Any | None = None
        self._channel: Any | None = None
        self._lock = threading.RLock()
        self._closed = False
        self.host_key_verdict: HostKeyVerdict | None = None

    def __repr__(self) -> str:
        # No username, no password, no key material.
        return f"ConsoleSession(host={self._host!r}, port={self._port})"

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        from founderos_atlas.ssh_security import disabled_ssh_algorithms

        client = (self._client_factory or _paramiko_client)()
        policy = _VerifyingPolicy(
            self._store,
            host=self._host,
            port=self._port,
            allow_new=self._allow_new_host_key,
        )
        client.set_missing_host_key_policy(policy)
        try:
            client.connect(
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                timeout=self._connect_timeout,
                allow_agent=False,
                look_for_keys=False,
                disabled_algorithms=disabled_ssh_algorithms(),
            )
        except (ConsoleHostKeyBlocked, ConsoleHostKeyUnknown):
            self._safe_close_client(client)
            raise
        except Exception as error:  # noqa: BLE001 - classified below
            self._safe_close_client(client)
            raise _classify(error, self._host) from None
        finally:
            # The secret has done its work. Drop our reference immediately;
            # it must not survive on the object for a debugger, a repr, or a
            # crash dump to find.
            self._password = ""

        self.host_key_verdict = policy.verdict
        try:
            channel = client.invoke_shell(
                term=self._term, width=self._width, height=self._height
            )
            channel.settimeout(0.0)      # non-blocking; the pump polls
        except Exception as error:  # noqa: BLE001
            self._safe_close_client(client)
            raise ConsoleSessionError(
                f"Could not open a terminal on {self._host}."
            ) from None
        with self._lock:
            self._client = client
            self._channel = channel

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._channel) and not self._closed

    def read(self, size: int = 65536) -> bytes:
        """Whatever the device has said, or b"" if it has said nothing yet."""

        channel = self._channel
        if channel is None:
            return b""
        if not channel.recv_ready():
            return b""
        try:
            return channel.recv(size)
        except Exception:  # noqa: BLE001 - a dead channel reads as EOF
            return b""

    def eof(self) -> bool:
        channel = self._channel
        if channel is None:
            return True
        try:
            return bool(channel.exit_status_ready() and not channel.recv_ready())
        except Exception:  # noqa: BLE001
            return True

    def write(self, data: bytes) -> None:
        """Send the operator's keystrokes. Not inspected, not filtered.

        This is the line where Atlas stops being an observer. What the
        engineer types is theirs; Atlas does not read it, log it, or judge
        it — including 'conf t'.
        """

        channel = self._channel
        if channel is None:
            raise ConsoleSessionError("The session is not connected.")
        try:
            channel.sendall(data)
        except Exception as error:  # noqa: BLE001
            raise ConsoleSessionError(
                f"The connection to {self._host} was lost."
            ) from None

    def resize(self, width: int, height: int) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            channel.resize_pty(width=max(1, int(width)), height=max(1, int(height)))
        except Exception:  # noqa: BLE001 - a resize must never kill a session
            pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            channel, self._channel = self._channel, None
            client, self._client = self._client, None
        for item in (channel, client):
            if item is None:
                continue
            try:
                item.close()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass

    @staticmethod
    def _safe_close_client(client: Any) -> None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def probe_host_key(
    host: str,
    port: int,
    store,
    *,
    timeout: float = 8.0,
    transport_factory: Callable[..., Any] | None = None,
) -> HostKeyVerdict:
    """Ask the device for its host key, without authenticating.

    Used to show an operator a fingerprint *before* they decide to trust it,
    and to confirm at acceptance time that the key being trusted is the one
    they were shown. No credential is involved: the SSH handshake exchanges
    host keys before authentication, which is precisely what makes
    reviewing the fingerprint first possible.
    """

    factory = transport_factory or _paramiko_transport
    transport = None
    try:
        transport = factory(host, port, timeout)
        key = transport.get_remote_server_key()
        return store.verify(host, port, key.get_name(), key.asbytes())
    except ConsoleSessionError:
        raise
    except Exception as error:  # noqa: BLE001
        raise _classify(error, host) from None
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass


def _paramiko_transport(host: str, port: int, timeout: float):
    try:
        import socket

        from paramiko import Transport
    except ImportError as error:  # pragma: no cover - dependency guard
        raise ConsoleSessionError(
            "Paramiko is required for the Atlas console. Install it with: "
            "pip install paramiko"
        ) from error
    sock = socket.create_connection((host, port), timeout=timeout)
    from founderos_atlas.ssh_security import disabled_ssh_algorithms

    transport = Transport(sock, disabled_algorithms=disabled_ssh_algorithms())
    transport.start_client(timeout=timeout)
    return transport


def _paramiko_client():
    try:
        from paramiko import SSHClient
    except ImportError as error:
        raise ConsoleSessionError(
            "Paramiko is required for the Atlas console. Install it with: "
            "pip install paramiko"
        ) from error
    return SSHClient()


def _classify(error: BaseException, host: str) -> ConsoleSessionError:
    """Turn a library exception into something an operator can act on.

    Never surfaces a stack trace or a library type name.
    """

    names = {cls.__name__ for cls in type(error).__mro__}
    text = str(error).casefold()
    if "authenticationexception" in {name.casefold() for name in names}:
        return ConsoleAuthenticationError(
            f"Authentication failed for {host}. The credential Atlas holds for "
            "this device was not accepted."
        )
    if isinstance(error, ConnectionRefusedError) or "refused" in text:
        return ConsoleSessionError(
            f"SSH is unavailable on {host}: the connection was refused. Verify "
            "SSH is enabled and reachable."
        )
    if isinstance(error, TimeoutError) or "timed out" in text or "timeout" in text:
        return ConsoleTimeoutError(
            f"Connection to {host} timed out. Verify the device is reachable "
            "and SSH is enabled."
        )
    if isinstance(error, OSError):
        return ConsoleSessionError(
            f"Could not reach SSH on {host}. Verify the management IP and the "
            "network path."
        )
    return ConsoleSessionError(f"Could not open an SSH session with {host}.")
