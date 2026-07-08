"""Controlled multi-hop live discovery orchestration for Atlas.

This module owns breadth-first neighbor traversal only. It speaks to devices
exclusively through injected ``DeviceTransport`` factories (never Netmiko
directly), parses through the existing ``DiscoveryEngine``, and leaves
reconciliation, snapshots, and rendering to their own layers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ..transport import AtlasTransportError, DeviceTransport
from .adapter import DiscoveryAdapter
from .adapters import CiscoIOSAdapter
from .engine import DiscoveryEngine
from .exceptions import AtlasDiscoveryError
from .models import DiscoveryResult


HostTransportFactory = Callable[[str], DeviceTransport]

CONNECTED = "connected"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True)
class MultiHopConfig:
    """Traversal limits; defaults are deliberately conservative."""

    max_depth: int = 1
    max_devices: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.max_depth, int) or isinstance(self.max_depth, bool) or self.max_depth < 0:
            raise ValueError("max_depth must be an integer of 0 or more")
        if not isinstance(self.max_devices, int) or isinstance(self.max_devices, bool) or self.max_devices < 1:
            raise ValueError("max_devices must be an integer of 1 or more")


@dataclass(frozen=True)
class DeviceVisit:
    """One traversal decision, in deterministic visit order."""

    host: str
    depth: int
    status: str  # connected | skipped | failed
    detail: str
    hostname: str | None = None


@dataclass(frozen=True)
class MultiHopDiscoveryReport:
    seed_host: str
    config: MultiHopConfig
    results: tuple[DiscoveryResult, ...]
    visits: tuple[DeviceVisit, ...]

    @property
    def connected(self) -> tuple[DeviceVisit, ...]:
        return tuple(visit for visit in self.visits if visit.status == CONNECTED)

    @property
    def skipped(self) -> tuple[DeviceVisit, ...]:
        return tuple(visit for visit in self.visits if visit.status == SKIPPED)

    @property
    def failed(self) -> tuple[DeviceVisit, ...]:
        return tuple(visit for visit in self.visits if visit.status == FAILED)

    @property
    def neighbor_count(self) -> int:
        return sum(len(result.neighbors) for result in self.results)


def discover_multihop(
    seed_host: str,
    transport_factory: HostTransportFactory,
    *,
    adapter: DiscoveryAdapter | None = None,
    config: MultiHopConfig | None = None,
) -> MultiHopDiscoveryReport:
    """Discover the seed device, then reachable CDP neighbors breadth-first.

    The seed must succeed; any failure past the seed is recorded and skipped
    so one unreachable neighbor never aborts the whole discovery. Hosts are
    visited at most once, devices reachable via several addresses are
    deduplicated by device identity, and traversal stops at ``max_depth``
    hops or ``max_devices`` discovered devices.
    """

    if not isinstance(seed_host, str) or not seed_host.strip():
        raise ValueError("seed_host must be a non-empty string")
    if not callable(transport_factory):
        raise TypeError("transport_factory must be callable")
    resolved_adapter = adapter if adapter is not None else CiscoIOSAdapter()
    resolved_config = config if config is not None else MultiHopConfig()
    engine = DiscoveryEngine(resolved_adapter)

    seed = seed_host.strip()
    results: list[DiscoveryResult] = []
    visits: list[DeviceVisit] = []
    seen_device_ids: set[str] = set()
    enqueued_hosts: set[str] = {seed}
    recorded_missing_ip: set[str] = set()
    queue: deque[tuple[str, int, str]] = deque([(seed, 0, "seed")])

    while queue:
        host, depth, origin = queue.popleft()
        if len(results) >= resolved_config.max_devices:
            visits.append(
                DeviceVisit(host, depth, SKIPPED, "maximum device limit reached")
            )
            continue
        try:
            transport = transport_factory(host)
            with transport:
                raw_outputs = transport.execute_many(resolved_adapter.required_commands)
            result = engine.discover(raw_outputs, management_ip_hint=host)
        except (AtlasTransportError, AtlasDiscoveryError) as error:
            if depth == 0:
                raise
            visits.append(DeviceVisit(host, depth, FAILED, str(error)))
            continue
        if result.device.device_id in seen_device_ids:
            visits.append(
                DeviceVisit(
                    host,
                    depth,
                    SKIPPED,
                    f"already discovered as {result.device.device_id}",
                    hostname=result.device.hostname,
                )
            )
            continue
        seen_device_ids.add(result.device.device_id)
        results.append(result)
        visits.append(
            DeviceVisit(host, depth, CONNECTED, origin, hostname=result.device.hostname)
        )
        if depth >= resolved_config.max_depth:
            continue
        ordered_neighbors = sorted(
            result.neighbors,
            key=lambda item: (
                item.remote_hostname.casefold(),
                item.remote_management_ip or "",
            ),
        )
        for neighbor in ordered_neighbors:
            next_host = neighbor.remote_management_ip
            if next_host is None:
                if neighbor.remote_hostname.casefold() not in recorded_missing_ip:
                    recorded_missing_ip.add(neighbor.remote_hostname.casefold())
                    visits.append(
                        DeviceVisit(
                            neighbor.remote_hostname,
                            depth + 1,
                            SKIPPED,
                            "no management IP advertised over CDP",
                            hostname=neighbor.remote_hostname,
                        )
                    )
                continue
            if next_host in enqueued_hosts:
                continue
            enqueued_hosts.add(next_host)
            queue.append(
                (next_host, depth + 1, f"cdp neighbor of {result.device.hostname}")
            )

    return MultiHopDiscoveryReport(
        seed_host=seed,
        config=resolved_config,
        results=tuple(results),
        visits=tuple(visits),
    )
