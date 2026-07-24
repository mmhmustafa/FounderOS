"""Measure the RTT across each discovered link — an opt-in ACTIVE pass.

Every other signal Atlas reads is passive: it looks at what a device
already reports. Latency is the one that must be MEASURED — real packets,
timed — so this is not part of read-only discovery. It is the console
case, exactly like the live traceroute: it sends packets, it is off by
default, and every surface that offers it says so.

The measurement is device-to-device: Atlas asks each device to ping its
own neighbour, so the number reflects the distance BETWEEN them — the
signal that says which devices sit in one site (sub-millisecond) and which
are a WAN apart (milliseconds). A ping from the Atlas host would instead
measure distance from Atlas, which is not what groups a network.

Nothing here decides anything. It records rtt_ms per link; site derivation
reads it (sites/derivation.py) and the operator sees it. An unreachable or
unanswered link yields no measurement — an honest gap, never a zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .probe import (
    _ping_command,
    parse_ping_rtt,
    ping_settled,
    platform_family,
    run_probe_command,
)


@dataclass(frozen=True)
class LinkProbe:
    """One measurement to make: reach ``local`` and ping ``target``.

    The caller assembles these from the credentials and addresses the
    discovery/console layer already holds — this module never resolves a
    secret itself, it only orchestrates the timed pings and reads the RTT.
    """

    local_device_id: str
    remote_hostname: str
    host: str                 # the local device's management address
    port: int
    username: str
    password: str
    target_ip: str            # the neighbour's address, what we ping
    platform: str = ""        # vendor/os hint, to pick the ping syntax


@dataclass(frozen=True)
class LinkLatency:
    """The measured RTT for one link, or the reason there is none."""

    local_device_id: str
    remote_hostname: str
    rtt_ms: float | None
    detail: str

    def to_edge_key(self) -> tuple[str, str]:
        return (self.local_device_id, self.remote_hostname)


def measure_link_latency(
    probes: Iterable[LinkProbe],
    *,
    host_key_store: Any,
    run_command: Callable[..., str] | None = None,
    command_timeout: float = 20.0,
) -> tuple[LinkLatency, ...]:
    """Ping each link's neighbour from its own device; read the RTT.

    ``run_command`` is injected so the orchestration is testable without
    SSH; it defaults to the console probe transport, which sends real
    packets. A failure to reach a device, or a ping that never answered,
    becomes a LinkLatency with rtt_ms=None and a reason — the pass never
    raises for one bad link, and never records a zero it did not measure.
    """

    runner = run_command or run_probe_command
    results: list[LinkLatency] = []
    for probe in probes:
        family = platform_family(probe.platform)
        # The shared probe helper fixes a small echo count per platform —
        # enough to average one link without a flood, and the same bounded
        # ping the reachability probe already uses.
        command = _ping_command(probe.target_ip, family=family)
        try:
            output = runner(
                host=probe.host,
                port=probe.port,
                username=probe.username,
                password=probe.password,
                command=command,
                host_key_store=host_key_store,
                command_timeout=command_timeout,
                stop_when=ping_settled,
                stop_note="enough echoes to time the link",
            )
        except Exception as error:  # noqa: BLE001 - one link never kills the pass
            results.append(LinkLatency(
                local_device_id=probe.local_device_id,
                remote_hostname=probe.remote_hostname,
                rtt_ms=None,
                detail=f"could not reach {probe.local_device_id}: {error}",
            ))
            continue
        rtt = parse_ping_rtt(output)
        results.append(LinkLatency(
            local_device_id=probe.local_device_id,
            remote_hostname=probe.remote_hostname,
            rtt_ms=rtt,
            detail=("measured" if rtt is not None
                    else "the link answered no timed reply"),
        ))
    return tuple(results)


def apply_latency_to_edges(
    edges: Iterable[Mapping[str, Any]],
    measurements: Iterable[LinkLatency],
) -> list[dict]:
    """Write each measured rtt_ms onto its edge, returning new edge dicts.

    Keyed by (local_device_id, remote_hostname), the same identity the
    edge already carries. A link with no measurement is left untouched —
    absence stays absence, so derivation falls back to topology rather
    than reading a missing measurement as instant.
    """

    by_key = {
        m.to_edge_key(): m.rtt_ms
        for m in measurements if m.rtt_ms is not None
    }
    out: list[dict] = []
    for edge in edges:
        record = dict(edge)
        key = (str(record.get("local_device_id") or ""),
               str(record.get("remote_hostname") or ""))
        rtt = by_key.get(key)
        if rtt is not None:
            meta = dict(record.get("metadata") or {})
            meta["rtt_ms"] = rtt
            record["metadata"] = meta
        out.append(record)
    return out
