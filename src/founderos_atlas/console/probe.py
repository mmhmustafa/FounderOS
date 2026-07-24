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
PROBE_REACHABILITY = "reachability"
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

# What a protocol-correct reachability probe proved.
PING_REACHABLE = "reachable"
PING_UNREACHABLE = "unreachable"
PING_UNKNOWN = "unknown"

# The one command shape this probe will ever send. IOS, IOS-XE, NX-OS,
# EOS, Junos, FRR and Linux all accept ``traceroute <address>``.
_ADDRESS_ONLY = re.compile(r"^[0-9a-fA-F:.]+$")

_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")
_IP_TOKEN = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


@dataclass(frozen=True)
class Probe:
    """A command, and what it actually puts on the wire.

    These two facts are one decision and must never drift apart. They
    used to live in separate functions — the command built per family,
    the protocol returned by a helper that answered "udp" for
    everything — which was true only for as long as no platform gained
    a way to send anything else. The first ``-I`` added to a command
    would have made that helper quietly lie, and a caller comparing
    declared intent against it would have reported a false match.
    Returning them together makes that class of bug unrepresentable;
    ``test_every_probe_reports_the_protocol_it_sends`` enforces it.
    """

    command: str
    protocol: str          # udp | icmp | tcp
    kind: str              # path | reachability | service
    port: int | None = None


# Flags that change what a probe puts on the wire, and the command
# names whose protocol is implied. Used to audit a Probe against its
# own command — see the drift guard in the tests.
_PROTOCOL_FLAGS = (
    (re.compile(r"(?:^|\s)-I(?:\s|$)"), "icmp"),
    (re.compile(r"(?:^|\s)--icmp(?:\s|$)"), "icmp"),
    (re.compile(r"(?:^|\s)-T(?:\s|$)"), "tcp"),
    (re.compile(r"(?:^|\s)--tcp(?:\s|$)"), "tcp"),
    (re.compile(r"(?:^|\s)-U(?:\s|$)"), "udp"),
)
_PROTOCOL_BY_TOOL = (
    (re.compile(r"(?:^|\s)ping(?:\s|$)"), "icmp"),
    (re.compile(r"(?:^|\s)nc(?:\s|$)"), "tcp"),
    (re.compile(r"(?:^|\s)telnet(?:\s|$)"), "tcp"),
    (re.compile(r"(?:^|\s)traceroute(?:\s|$)"), "udp"),
)


def protocol_of_command(command: str) -> str:
    """What a command will actually put on the wire, read from itself.

    Derived from the command rather than declared beside it, so it can
    be used to audit a ``Probe`` against its own text: any future flag
    that changes the protocol must change this answer too.
    """

    text = str(command or "")
    for pattern, protocol in _PROTOCOL_FLAGS:
        if pattern.search(text):
            return protocol
    for pattern, protocol in _PROTOCOL_BY_TOOL:
        if pattern.search(text):
            return protocol
    return "unknown"


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


def path_probe(
    destination_address: str,
    *,
    family: str = FAMILY_UNKNOWN,
    protocol: str | None = None,
) -> Probe:
    """The path probe for this platform's CLI, and what it really sends.

    Where the CLI accepts options they do two jobs: bound the probe (a
    device's default traceroute walks 30 hops with several probes each,
    which can outlive any sensible request) and, where possible, put
    the operator's OWN protocol on the wire. Where the CLI takes the
    bare form only — IOS, and vtysh, which rejects every option as an
    unknown command — the probe is UDP whatever was declared, and says
    so rather than letting the caller assume otherwise.

    ``protocol`` is the declared intent. Honouring it is best-effort by
    design: only a shell-backed CLI can be told, and only for ICMP.
    TCP path probes are deliberately not attempted — busybox
    traceroute has no ``-T``, and inventing syntax a device may reject
    would trade a wrong answer for a broken one. ``service_probe``
    answers TCP questions properly.
    """

    address = _validated(destination_address)
    wanted = (protocol or "").casefold()

    if family == FAMILY_LINUX:
        if wanted == "icmp":
            return Probe(
                command=f"traceroute -I -n -w 2 -q 1 -m 15 {address}",
                protocol="icmp",
                kind=PROBE_PATH,
            )
        return Probe(
            command=f"traceroute -n -w 2 -q 1 -m 15 {address}",
            protocol="udp",
            kind=PROBE_PATH,
        )
    if family == FAMILY_EOS:
        if wanted == "icmp":
            return Probe(
                command=(
                    f"bash timeout 30 traceroute -I -n -w 2 -q 1 -m 15 "
                    f"{address}"
                ),
                protocol="icmp",
                kind=PROBE_PATH,
            )
        return Probe(
            command=(
                f"bash timeout 30 traceroute -n -w 2 -q 1 -m 15 {address}"
            ),
            protocol="udp",
            kind=PROBE_PATH,
        )
    if family == FAMILY_JUNOS:
        return Probe(
            command=f"traceroute {address} wait 2 ttl 15",
            protocol="udp",
            kind=PROBE_PATH,
        )
    # Cisco IOS/NX-OS and FRR's vtysh take the bare form only.
    return Probe(
        command=f"traceroute {address}", protocol="udp", kind=PROBE_PATH
    )


def reachability_probe(
    destination_address: str, *, family: str = FAMILY_UNKNOWN
) -> Probe:
    """A protocol-correct ICMP reachability probe."""

    return Probe(
        command=_ping_command(destination_address, family=family),
        protocol="icmp",
        kind=PROBE_REACHABILITY,
    )


def _ping_command(
    destination_address: str, *, family: str = FAMILY_UNKNOWN
) -> str:
    """A protocol-correct ICMP reachability probe.

    Every CLI here has ``ping``, including the routing CLIs that reject
    every traceroute option — which makes this the one probe that can
    answer an ICMP question honestly on those platforms. Bounded where
    the CLI accepts a count; where it does not, the read deadline and
    the settled-check bound it instead of pinging forever.
    """

    address = _validated(destination_address)
    if family in (FAMILY_LINUX, FAMILY_FRR):
        # busybox/iputils accept these; vtysh does NOT, so FRR falls
        # through to the bare form below.
        if family == FAMILY_LINUX:
            return f"ping -c 3 -W 2 {address}"
        return f"ping {address}"
    if family == FAMILY_EOS:
        return f"bash timeout 8 ping -c 3 -W 2 {address}"
    if family == FAMILY_JUNOS:
        return f"ping {address} count 3"
    # IOS/NX-OS send a fixed small count and stop on their own.
    return f"ping {address}"


def ping_settled(text: str) -> bool:
    """Enough of a ping has come back to answer the question.

    A bare ``ping`` on a routing CLI runs until it is stopped. Two
    replies, or a summary line, is all the evidence needed.
    """

    lowered = text.casefold()
    if "packet loss" in lowered or "success rate" in lowered:
        return True
    replies = len(re.findall(r"bytes from", lowered))
    return replies >= 2 or bool(re.search(r"!{3,}", text))


def parse_ping(text: str) -> tuple[str, str]:
    """What the reachability probe proved, and the line proving it."""

    lowered = text.casefold()
    for line in text.splitlines():
        folded = line.casefold()
        if "100% packet loss" in folded or "100.0% packet loss" in folded:
            return PING_UNREACHABLE, line.strip()
        if "success rate is 0 percent" in folded:
            return PING_UNREACHABLE, line.strip()
    for line in text.splitlines():
        folded = line.casefold()
        if "bytes from" in folded or re.search(r"!{3,}", line):
            return PING_REACHABLE, line.strip()
        if "packet loss" in folded and "100%" not in folded:
            return PING_REACHABLE, line.strip()
    if "unreachable" in lowered or "timed out" in lowered:
        return PING_UNREACHABLE, text.strip().splitlines()[-1][:200]
    if not text.strip():
        return PING_UNKNOWN, "the device returned no output"
    return PING_UNKNOWN, text.strip().splitlines()[-1][:200]


# The average RTT sits in the ping SUMMARY, one of two shapes across the
# CLIs here — Linux "round-trip min/avg/max = 0.061/0.166/0.367 ms" and
# the iputils "rtt min/avg/max/mdev = .../avg/... ms". Both put the average
# in the SECOND slash-field; a device that answered but printed no summary
# (a single "bytes from ..." line) has no average to read, and None says
# so rather than inventing 0.
_RTT_SUMMARY = re.compile(
    r"(?:round-trip|rtt)\s+min/avg/max(?:/\w+)?\s*=\s*"
    r"[\d.]+/([\d.]+)/[\d.]+",
    re.IGNORECASE,
)


def parse_ping_rtt(text: str) -> float | None:
    """The average round-trip time in milliseconds, or None.

    Read only from a ping that actually returned a summary. 100% loss, no
    output, or a reply with no timing line all yield None — an absent
    measurement, never a zero that would read as "instant".
    """

    match = _RTT_SUMMARY.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def service_probe(
    destination_address: str, port: Any, *, family: str = FAMILY_UNKNOWN
) -> Probe:
    """A TCP connect probe for this platform's CLI.

    Raises ``ProbeUnsupported`` where the CLI has no way to open a TCP
    connection — FRR's vtysh, notably, which is a routing CLI and not a
    shell. Atlas says so rather than probing from a different vantage
    point and passing the result off as the same evidence.
    """

    address = _validated(destination_address)
    number = _validated_port(port)
    if family == FAMILY_LINUX:
        command = f"nc -z -w 5 -v {address} {number}"
    elif family == FAMILY_EOS:
        command = f"bash timeout 8 nc -z -w 5 -v {address} {number}"
    elif family == FAMILY_JUNOS:
        command = f"telnet {address} port {number} inactivity-timeout 5"
    elif family == FAMILY_CISCO:
        command = f"telnet {address} {number} /timeout 5"
    else:
        raise ProbeUnsupported(
            "This platform's CLI offers no TCP connection test, so Atlas "
            "cannot check the port from this device. Its routing CLI can "
            "trace the path, but not open a socket."
        )
    return Probe(
        command=command, protocol="tcp", kind=PROBE_SERVICE, port=number
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
    stop_note: str | None = None,
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
    elif ended == "early":
        text += (
            "\n[atlas] "
            + (stop_note or "The probe was stopped early.")
            + "\n"
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
                        return b"".join(chunks), "early"
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

# Why a probe was stopped early is the caller's knowledge, not this
# module's: the same early-stop machinery serves a traceroute meeting a
# black hole and a ping that has already answered, and those mean
# opposite things. Saying "a device is dropping the probes" over a
# successful ping would be worse than saying nothing.
SILENT_HOP_NOTE = (
    f"Stopped after {SILENT_HOP_LIMIT} consecutive hops went unanswered "
    "— a device is dropping the probes, and waiting out the remaining "
    "hops would add delay, not evidence. The hops above are what "
    "answered."
)
PING_SETTLED_NOTE = (
    "Stopped once the device had answered — the replies above settle "
    "the question, and a bare ping would otherwise run until stopped."
)


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
