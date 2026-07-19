"""One-shot live probe from a device (packet trace Phase 3, PROBE).

Runs a single ``traceroute`` on a device Atlas has authenticated to,
over the console stack — paramiko with the same host-key verification
as an interactive session. This is deliberately **not**
``transport/ssh.py``: that transport's read-only contract rightly
rejects anything but ``show``, because it governs what Atlas does on
its own initiative. A live validation is the console case — an
operator explicitly asking for one active command, permission-gated as
``console.use`` and audited like a console connection.

The probe sends real packets. Every surface that offers it says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any, Callable

from .session import (
    ConsoleSessionError,
    ConsoleTimeoutError,
    _classify,
    _paramiko_client,
    _VerifyingPolicy,
)


PROBE_TIMEOUT_SECONDS = 60.0

# The one command shape this probe will ever send. IOS, IOS-XE, NX-OS,
# EOS, Junos, FRR and Linux all accept ``traceroute <address>``.
_ADDRESS_ONLY = re.compile(r"^[0-9a-fA-F:.]+$")

_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")
_IP_TOKEN = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


@dataclass(frozen=True)
class ProbeHop:
    """One traceroute hop as the device reported it."""

    index: int
    address: str | None      # None when the hop did not answer (* * *)
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "address": self.address,
            "raw": self.raw,
            "evidence_state": "observed",
        }


def traceroute_command(destination_address: str) -> str:
    """The exact command the probe runs — address only, nothing else.

    Building the command from a validated address (never from free
    text) is what keeps this endpoint from becoming a remote shell.
    """

    address = str(destination_address).strip()
    if not _ADDRESS_ONLY.match(address):
        raise ValueError("destination must be a bare IP address")
    ip_address(address)
    return f"traceroute {address}"


def run_probe_command(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    command: str,
    host_key_store,
    allow_new_host_key: bool = True,
    connect_timeout: float = 10.0,
    command_timeout: float = PROBE_TIMEOUT_SECONDS,
    client_factory: Callable[[], Any] | None = None,
) -> str:
    """Run one command over SSH and return its output text.

    Same client, same host-key policy, same secret hygiene as
    ``ConsoleSession`` — the password is used for ``connect`` and
    dropped; it never lands on an object or in an error.
    """

    from founderos_atlas.ssh_security import disabled_ssh_algorithms

    client = (client_factory or _paramiko_client)()
    policy = _VerifyingPolicy(
        host_key_store, host=host, port=port, allow_new=allow_new_host_key
    )
    client.set_missing_host_key_policy(policy)
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
            disabled_algorithms=disabled_ssh_algorithms(),
        )
    except ConsoleSessionError:
        _safe_close(client)
        raise
    except Exception as error:  # noqa: BLE001 - classified below
        _safe_close(client)
        raise _classify(error, host) from None
    finally:
        password = ""
    try:
        _stdin, stdout, _stderr = client.exec_command(
            command, timeout=command_timeout
        )
        output = stdout.read()
    except Exception:  # noqa: BLE001 - operator-safe, no trace
        _safe_close(client)
        raise ConsoleTimeoutError(
            f"The probe command did not complete on {host}."
        ) from None
    _safe_close(client)
    return output.decode("utf-8", "replace")


def parse_traceroute(text: str) -> tuple[ProbeHop, ...]:
    """Hop lines out of traceroute output, honestly.

    A hop that answered yields its first reported address; a silent hop
    (``* * *``) yields ``address=None`` — unknown, never invented. Any
    platform's preamble ("Type escape sequence…", "Tracing the route
    to…") simply does not look like a hop line and is skipped.
    """

    hops: list[ProbeHop] = []
    for line in text.splitlines():
        match = _HOP_LINE.match(line)
        if not match:
            continue
        index = int(match.group(1))
        remainder = match.group(2)
        address_match = _IP_TOKEN.search(remainder)
        address = address_match.group(1) if address_match else None
        if address is not None:
            try:
                ip_address(address)
            except ValueError:
                address = None
        hops.append(ProbeHop(index=index, address=address, raw=line.strip()))
    return tuple(hops)


def _safe_close(client: Any) -> None:
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass
