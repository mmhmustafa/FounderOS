"""Lightweight TCP reachability probing (PR-043.6, FALCON).

The discovery audit (PR-043.5) measured that ~98.5% of a management-subnet
scan's wall-clock time was spent inside full SSH connect attempts to dead
addresses (a 15 s timeout each, in series). A cheap TCP probe to the
management ports gates that expensive attempt: if no relevant port
answers within a short timeout, Atlas marks the address unreachable and
moves on immediately instead of paying the SSH timeout.

Deterministic and injectable: the prober is an object with
``is_reachable(host) -> bool``; tests substitute a fake, production uses
``TcpReachability``. No secret is ever involved.
"""

from __future__ import annotations

from collections.abc import Sequence
import socket


# Management ports probed by default, in order: SSH, SNMP, NETCONF, HTTPS.
DEFAULT_PORTS: tuple[int, ...] = (22, 161, 830, 443)
DEFAULT_TIMEOUT = 2.0


class TcpReachability:
    """A TCP-connect reachability prober over configurable ports.

    A host is reachable when ANY probed port accepts a TCP connection
    within ``timeout`` seconds. UDP-only services (SNMP/161) are probed
    as TCP too — a refused connection still proves the host is alive and
    routable, which is all discovery needs before attempting SSH.
    """

    def __init__(
        self,
        ports: Sequence[int] = DEFAULT_PORTS,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        connector=None,
    ) -> None:
        self._ports = tuple(int(p) for p in ports) or DEFAULT_PORTS
        self._timeout = float(timeout)
        # Injectable connector(host, port, timeout) -> bool; defaults to a
        # real non-blocking TCP connect.
        self._connect = connector or _tcp_connect

    @property
    def ports(self) -> tuple[int, ...]:
        return self._ports

    @property
    def timeout(self) -> float:
        return self._timeout

    def is_reachable(self, host: str) -> bool:
        for port in self._ports:
            try:
                if self._connect(host, port, self._timeout):
                    return True
            except OSError:
                continue
        return False


def _tcp_connect(host: str, port: int, timeout: float) -> bool:
    """One TCP connect attempt; True on connect OR active refusal.

    A refused connection (ECONNREFUSED) still means the host is up and
    routing — reachable enough to justify an SSH attempt. Only a timeout
    or unreachable-network counts as not reachable.
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    if result == 0:
        return True
    # errno for connection refused varies by platform; a refusal proves
    # the host answered, so treat it as reachable. Timeouts return EAGAIN/
    # EWOULDBLOCK/ETIMEDOUT which we treat as unreachable.
    import errno

    return result in (errno.ECONNREFUSED,)
