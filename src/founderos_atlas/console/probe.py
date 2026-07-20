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
from time import monotonic, sleep
from typing import Any, Callable

from .session import (
    ConsoleSessionError,
    ConsoleTimeoutError,
    _classify,
    _paramiko_client,
    _VerifyingPolicy,
)


PROBE_TIMEOUT_SECONDS = 45.0

PROBE_PATH = "path"
PROBE_SERVICE = "service"

# Platform families. A network device's SSH session is usually its CLI,
# not a shell — the lab's FRR nodes drop into vtysh exactly as a Cisco
# gives you IOS. So a probe is only ever the command THAT CLI accepts,
# and where a CLI offers none, "unsupported" is the honest answer.
FAMILY_CISCO = "cisco"
FAMILY_JUNOS = "junos"
FAMILY_EOS = "eos"
FAMILY_FRR = "frr"
FAMILY_LINUX = "linux"
FAMILY_UNKNOWN = "unknown"

_FAMILY_HINTS = (
    (FAMILY_JUNOS, ("junos", "juniper")),
    (FAMILY_EOS, ("eos", "arista")),
    (FAMILY_FRR, ("frr", "frrouting", "vtysh", "quagga")),
    (FAMILY_CISCO, ("ios", "nx-os", "nxos", "cisco", "catalyst")),
    (FAMILY_LINUX, ("linux", "ubuntu", "debian", "alpine", "busybox")),
)

# Service states — what a TCP connect attempt proved.
SERVICE_OPEN = "open"
SERVICE_REFUSED = "refused"
SERVICE_NO_ANSWER = "no-answer"
SERVICE_UNKNOWN = "unknown"

# The one command shape this probe will ever send. IOS, IOS-XE, NX-OS,
# EOS, Junos, FRR and Linux all accept ``traceroute <address>``.
_ADDRESS_ONLY = re.compile(r"^[0-9a-fA-F:.]+$")

_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")
_IP_TOKEN = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


class ProbeUnsupported(RuntimeError):
    """This platform's CLI offers no such probe.

    Not a failure — an answer. Reported to the operator as "Atlas
    cannot ask this device that question", never worked around by
    probing from somewhere else and calling it the same evidence.
    """


def platform_family(*hints: Any) -> str:
    """Classify a device from its vendor/platform/os_name strings."""

    blob = " ".join(str(hint or "") for hint in hints).casefold()
    for family, needles in _FAMILY_HINTS:
        if any(needle in blob for needle in needles):
            return family
    return FAMILY_UNKNOWN


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


def _validated(address: str) -> str:
    """An address, or nothing. Never free text.

    Building every command from a validated address (and an integer
    port) is what keeps this endpoint from becoming a remote shell.
    """

    value = str(address).strip()
    if not _ADDRESS_ONLY.match(value):
        raise ValueError("destination must be a bare IP address")
    ip_address(value)
    return value


def _validated_port(port: Any) -> int:
    number = int(port)
    if not 1 <= number <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return number


def traceroute_command(
    destination_address: str, *, family: str = FAMILY_UNKNOWN
) -> str:
    """The path probe for this platform's CLI.

    Where the CLI accepts options, they bound the probe: a network
    device's default traceroute walks 30 hops with several probes
    each, which can outlive any sensible request. Where the CLI takes
    the bare form only (IOS, vtysh), the server-side deadline is the
    bound and partial output is still read.
    """

    address = _validated(destination_address)
    if family == FAMILY_LINUX:
        return f"traceroute -n -w 2 -q 1 -m 15 {address}"
    if family == FAMILY_EOS:
        return f"bash timeout 30 traceroute -n -w 2 -q 1 -m 15 {address}"
    if family == FAMILY_JUNOS:
        return f"traceroute {address} wait 2 ttl 15"
    # Cisco IOS/NX-OS and FRR's vtysh take the bare form only; anything
    # else they reject outright as an unknown command.
    return f"traceroute {address}"


def service_command(
    destination_address: str, port: Any, *, family: str = FAMILY_UNKNOWN
) -> str:
    """A TCP connect probe for this platform's CLI.

    Raises ``ProbeUnsupported`` where the CLI has no way to open a TCP
    connection — FRR's vtysh, notably, which is a routing CLI and not a
    shell. Atlas says so rather than probing from a different vantage
    point and passing the result off as the same evidence.
    """

    address = _validated(destination_address)
    number = _validated_port(port)
    if family == FAMILY_LINUX:
        return f"nc -z -w 5 -v {address} {number}"
    if family == FAMILY_EOS:
        return f"bash timeout 8 nc -z -w 5 -v {address} {number}"
    if family == FAMILY_JUNOS:
        return f"telnet {address} port {number} inactivity-timeout 5"
    if family == FAMILY_CISCO:
        return f"telnet {address} {number} /timeout 5"
    raise ProbeUnsupported(
        "This platform's CLI offers no TCP connection test, so Atlas "
        "cannot check the port from this device. Its routing CLI can "
        "trace the path, but not open a socket."
    )


def parse_service_result(text: str) -> tuple[str, str]:
    """What a TCP connect attempt proved, and the line that proves it.

    Three outcomes carry real meaning and are kept apart: the service
    accepted (``open``), the destination actively refused (``refused``
    — the path delivered and the host answered, so the network is not
    the problem), or nothing came back (``no-answer`` — consistent
    with a drop, a filter, or a dead host, and Atlas does not pretend
    to tell those apart).
    """

    lowered = text.casefold()
    for line in text.splitlines():
        folded = line.casefold()
        if "refused" in folded:
            return SERVICE_REFUSED, line.strip()
        if any(
            token in folded
            for token in ("open", "succeeded", "connected to", "escape character")
        ):
            return SERVICE_OPEN, line.strip()
    if any(
        token in lowered
        for token in ("timed out", "timeout", "unreachable", "no route")
    ):
        for line in text.splitlines():
            folded = line.casefold()
            if any(
                token in folded
                for token in ("timed out", "timeout", "unreachable", "no route")
            ):
                return SERVICE_NO_ANSWER, line.strip()
    if not text.strip():
        return SERVICE_NO_ANSWER, "the device returned no output"
    return SERVICE_UNKNOWN, text.strip().splitlines()[-1][:200]


def probe_hint(text: str) -> str | None:
    """An actionable remedy when the device refused to run the probe.

    A bare "no hops" reading tells an operator nothing. These are the
    failures whose cause is knowable from the device's own words.
    """

    lowered = text.casefold()
    if "operation not permitted" in lowered and "socket" in lowered:
        return (
            "The login account cannot open a raw socket, so traceroute "
            "could not run. Grant the traceroute binary CAP_NET_RAW on "
            "the device image, or probe from an account that has it."
        )
    if "not found" in lowered or "unknown command" in lowered:
        return (
            "The device's CLI does not have this command. Atlas can "
            "only run what this platform's CLI accepts."
        )
    if "permission denied" in lowered:
        return "The login account is not permitted to run this command."
    return None


def run_probe_command(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    command: str,
    host_key_store,
    allow_new_host_key: bool = False,
    connect_timeout: float = 10.0,
    command_timeout: float = PROBE_TIMEOUT_SECONDS,
    client_factory: Callable[[], Any] | None = None,
    stop_when: Callable[[str], bool] | None = None,
) -> str:
    """Run one command over SSH and return its output text.

    Same client, same host-key policy, same secret hygiene as
    ``ConsoleSession`` — the password is used for ``connect`` and
    dropped; it never lands on an object or in an error.

    ``allow_new_host_key`` defaults to False for the same reason the
    console's does: this connection sends a stored credential, and a
    host Atlas has never verified might not be the device it means.
    Trust-on-first-use would hand the password to whoever answered.
    The caller is expected to route the operator to the console, where
    a fingerprint can be compared and accepted deliberately.
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
        output, ended = _execute(
            client, command, command_timeout, stop_when
        )
    except Exception:  # noqa: BLE001 - operator-safe, no trace
        _safe_close(client)
        raise ConsoleTimeoutError(
            f"The probe command did not complete on {host}."
        ) from None
    _safe_close(client)
    text = output.decode("utf-8", "replace")
    if ended == "timeout":
        text += (
            f"\n[atlas] The probe was still running after "
            f"{int(command_timeout)}s and was cut short — the hops above "
            "are what the device reported in that window.\n"
        )
    elif ended == "silent":
        text += (
            f"\n[atlas] Stopped after {SILENT_HOP_LIMIT} consecutive hops "
            "went unanswered — a device is dropping the probes, and "
            "waiting out the remaining hops would add delay, not "
            "evidence. The hops above are what answered.\n"
        )
    return text


def _execute(
    client: Any,
    command: str,
    timeout: float,
    stop_when: Callable[[str], bool] | None = None,
) -> tuple[bytes, str]:
    """Run the command and read its output as ONE ordered stream.

    Device tools split their output across stdout and stderr — busybox
    traceroute prints a hop's number on one and its addresses on the
    other. Reading the two separately and stitching them together
    afterwards interleaves them wrongly and silently loses hops, so
    the channel is told to combine them at the source, in the order
    the device produced them (which is what an operator would see).
    """

    transport = None
    getter = getattr(client, "get_transport", None)
    if callable(getter):
        transport = getter()
    if transport is None or not hasattr(transport, "open_session"):
        # Scripted client in tests: no real channel to combine.
        _stdin, stdout, stderr = client.exec_command(
            command, timeout=timeout
        )
        output, timed_out = _read_bounded(stdout, timeout)
        if stderr is not None:
            try:
                errors, _ = _read_bounded(stderr, 1.0)
            except Exception:  # noqa: BLE001
                errors = b""
            if errors.strip():
                output += b"\n[stderr] " + errors.strip() + b"\n"
        return output, ("timeout" if timed_out else "complete")

    channel = transport.open_session()
    channel.settimeout(timeout)
    channel.set_combine_stderr(True)
    channel.exec_command(command)
    return _drain(channel, timeout, stop_when)


def _drain(
    channel: Any,
    timeout: float,
    stop_when: Callable[[str], bool] | None = None,
) -> tuple[bytes, str]:
    deadline = monotonic() + timeout
    chunks: list[bytes] = []
    while monotonic() < deadline:
        if channel.recv_ready():
            try:
                data = channel.recv(65536)
            except Exception:  # noqa: BLE001 - a dead channel reads as EOF
                break
            if not data:
                break
            chunks.append(data)
            if stop_when is not None:
                try:
                    if stop_when(b"".join(chunks).decode("utf-8", "replace")):
                        return b"".join(chunks), "silent"
                except Exception:  # noqa: BLE001 - a bad predicate
                    stop_when = None      # never let it end the read
            continue
        if channel.exit_status_ready():
            break
        sleep(0.05)
    else:
        return b"".join(chunks), "timeout"
    while channel.recv_ready():
        try:
            data = channel.recv(65536)
        except Exception:  # noqa: BLE001
            break
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks), "complete"


def _read_bounded(stream: Any, timeout: float) -> tuple[bytes, bool]:
    """Read a command's output, keeping whatever arrived before the
    deadline.

    A device traceroute can outlive any request — silent hops are
    waited on one by one. Throwing away the hops that DID answer
    because the tail never did would discard the evidence the operator
    actually wanted, so a cut-short read returns its partial output and
    says that it was cut short.
    """

    channel = getattr(stream, "channel", None)
    if channel is None:                      # scripted stream in tests
        return stream.read(), False
    deadline = monotonic() + timeout
    chunks: list[bytes] = []
    while monotonic() < deadline:
        if channel.recv_ready():
            try:
                data = channel.recv(65536)
            except Exception:  # noqa: BLE001 - a dead channel reads as EOF
                break
            if not data:
                break
            chunks.append(data)
            continue
        if channel.exit_status_ready():
            break
        sleep(0.05)
    else:
        return b"".join(chunks), True
    # Drain anything buffered after the command finished.
    while channel.recv_ready():
        try:
            data = channel.recv(65536)
        except Exception:  # noqa: BLE001
            break
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks), False


SILENT_HOP_LIMIT = 3


def silent_tail(text: str, limit: int = SILENT_HOP_LIMIT) -> bool:
    """True once the last ``limit`` completed hops all went unanswered.

    A traceroute that has met a device dropping its probes will not
    recover: it waits out every remaining hop, one timeout at a time,
    for minutes. The hops already collected are the evidence; the
    silence that follows adds nothing but delay, so the probe stops
    and says where it stopped.
    """

    lines = text.splitlines()
    # The last line may still be mid-write; judge only completed ones.
    hops = [line for line in lines[:-1] if _HOP_LINE.match(line)]
    if len(hops) < limit:
        return False
    return all(not _IP_TOKEN.search(line) for line in hops[-limit:])


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


def dataplane_address(
    snapshot_devices, hostname: str, management_ip: str | None
) -> tuple[str, str] | None:
    """A destination address on the forwarding plane, when known.

    In out-of-band-managed networks a traceroute toward the management
    address never crosses the fabric the prediction is about — it
    validates the wrong plane (or, where management is unrouted from
    the dataplane, nothing at all). The snapshot's interface table is
    the evidence for a better target: a loopback if one has an
    address (reachable over any path), else the first non-management
    interface address. Returns ``(address, interface_name)`` or
    ``None`` when the snapshot offers nothing beyond management.
    """

    wanted = str(hostname or "").casefold()
    loopback: tuple[str, str] | None = None
    first: tuple[str, str] | None = None
    for device in snapshot_devices or ():
        if not isinstance(device, dict):
            continue
        if str(device.get("hostname") or "").casefold() != wanted:
            continue
        for item in device.get("interfaces") or ():
            if not isinstance(item, dict):
                continue
            value = str(item.get("ip_address") or "").split("/")[0].strip()
            if not value:
                continue
            try:
                ip_address(value)
            except ValueError:
                continue
            if value == management_ip or value.startswith("127."):
                continue
            name = str(item.get("name") or "")
            if name.casefold().startswith(("lo", "loopback")):
                if loopback is None:
                    loopback = (value, name)
            elif first is None:
                first = (value, name)
    return loopback or first


def _safe_close(client: Any) -> None:
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass
