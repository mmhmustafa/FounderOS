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
from .engine import DiscoveryEngine
from .exceptions import AtlasDiscoveryError
from .models import DiscoveryResult, NetworkNeighbor
from .policy import BoundaryPolicy


def management_candidate(neighbor: NetworkNeighbor) -> bool:
    """Whether recursive SSH to this neighbor is evidence-justified.

    Atlas may attempt a discovered address ONLY when deterministic
    evidence marks it as a usable management endpoint (PR-043.1):

    - the driver explicitly said so (``metadata.management_endpoint``),
      e.g. a previously verified canonical endpoint; or
    - the protocol itself advertises management addresses (CDP/LLDP
      announce the device's own entry point; ``manual`` is an operator
      statement).

    Routing evidence NEVER qualifies: an OSPF router ID, a BGP peer
    address, a next hop, or a loopback proves a protocol relationship,
    not SSH manageability. User seeds are handled separately and are
    always attempted.
    """

    flag = neighbor.metadata.get("management_endpoint")
    if flag is not None:
        return bool(flag)
    return neighbor.protocol in ("cdp", "lldp", "manual")


def _discover_with_registry(transport, registry, host: str) -> DiscoveryResult:
    """Detect the platform with a lightweight probe, then drive discovery.

    The probe output is handed to the matching driver so the detection
    command is never executed twice. An unrecognized platform raises the
    registry's honest, actionable explanation.
    """

    from founderos_atlas.platforms import UnsupportedPlatformError

    probe_output = ""
    driver = None
    for probe_command in registry.probe_commands():
        probe_output = transport.execute(probe_command)
        driver = registry.detect(probe_output)
        if driver is not None and driver.probe_command == probe_command:
            break
        if driver is not None:
            break
    if driver is None:
        raise UnsupportedPlatformError(registry.unsupported_message(probe_output))
    discovery = driver.discover(
        transport, management_ip_hint=host, probe_output=probe_output
    )
    return discovery.result


HostTransportFactory = Callable[[str], DeviceTransport]
NeighborObserver = Callable[[NetworkNeighbor], None]

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
    seed_hosts: tuple[str, ...] = ()

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
    registry=None,
    config: MultiHopConfig | None = None,
    policy: BoundaryPolicy | None = None,
    extra_seeds: tuple[str, ...] = (),
    on_neighbor: NeighborObserver | None = None,
) -> MultiHopDiscoveryReport:
    """Discover the seed device(s), then reachable neighbors breadth-first.

    Platform handling (PR-043): by default every host is platform-detected
    with a lightweight probe and discovered through the matching
    ``PlatformDriver`` from the ``registry`` (defaulting to Atlas's
    built-in registry: Cisco IOS/IOS-XE, FRRouting). Passing an explicit
    ``adapter`` pins the legacy single-adapter behavior for callers and
    tests that inject their own parser. An unrecognized platform is a
    per-device failure with an honest explanation — never a crash of the
    whole discovery (unless it is the only seed, the unchanged contract).

    With one seed, its failure aborts the discovery (unchanged contract);
    with multiple seeds, individual seed failures are recorded and discovery
    continues as long as at least one seed succeeds. Hosts are visited at
    most once, devices reachable via several addresses are deduplicated by
    device identity, and traversal stops at ``max_depth`` hops or
    ``max_devices`` discovered devices.

    ``policy`` bounds traversal: every observed neighbor is classified
    (allowed / denied / observe-only / unknown) and only ``allowed``
    neighbors are followed — the rest are recorded as visits with the
    boundary reason, never silently followed and never erased. Seeds are
    explicit user entry points and are always attempted. ``on_neighbor``
    receives every observed neighbor (e.g. to prime credential hints).
    """

    if not isinstance(seed_host, str) or not seed_host.strip():
        raise ValueError("seed_host must be a non-empty string")
    if not callable(transport_factory):
        raise TypeError("transport_factory must be callable")
    resolved_adapter = adapter
    resolved_registry = registry
    if resolved_adapter is None and resolved_registry is None:
        from founderos_atlas.platforms import default_registry

        resolved_registry = default_registry()
    resolved_config = config if config is not None else MultiHopConfig()
    engine = DiscoveryEngine(resolved_adapter) if resolved_adapter else None

    seed = seed_host.strip()
    seeds: list[str] = [seed]
    for candidate in extra_seeds:
        cleaned = str(candidate).strip()
        if cleaned and cleaned not in seeds:
            seeds.append(cleaned)
    results: list[DiscoveryResult] = []
    visits: list[DeviceVisit] = []
    seen_device_ids: set[str] = set()
    enqueued_hosts: set[str] = set(seeds)
    recorded_missing_ip: set[str] = set()
    recorded_boundary: set[str] = set()
    first_seed_error: Exception | None = None
    queue: deque[tuple[str, int, str]] = deque(
        (host, 0, "seed") for host in seeds
    )

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
                if engine is not None:
                    # Legacy pinned-adapter path: unchanged behavior.
                    raw_outputs = transport.execute_many(
                        resolved_adapter.required_commands
                    )
                    result = engine.discover(raw_outputs, management_ip_hint=host)
                else:
                    result = _discover_with_registry(
                        transport, resolved_registry, host
                    )
        except (AtlasTransportError, AtlasDiscoveryError) as error:
            if depth == 0:
                if len(seeds) == 1:
                    raise
                if first_seed_error is None:
                    first_seed_error = error
                visits.append(DeviceVisit(host, depth, FAILED, str(error)))
                continue
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
            if on_neighbor is not None:
                on_neighbor(neighbor)
            if not management_candidate(neighbor):
                # A routing adjacency or protocol peer: preserved as an
                # unresolved observation — never an SSH target, never a
                # false "unreachable" (PR-043.1).
                marker = (
                    f"unresolved|{neighbor.remote_hostname.casefold()}"
                    f"|{neighbor.protocol}"
                )
                if marker not in recorded_boundary:
                    recorded_boundary.add(marker)
                    observation = str(
                        neighbor.metadata.get("observation")
                        or f"{neighbor.protocol} adjacency"
                    )
                    visits.append(
                        DeviceVisit(
                            neighbor.remote_hostname,
                            depth + 1,
                            SKIPPED,
                            "not attempted — "
                            f"{neighbor.protocol.upper()} {observation} "
                            "is not a verified management endpoint",
                            hostname=neighbor.remote_hostname,
                        )
                    )
                continue
            next_host = neighbor.remote_management_ip
            if policy is not None:
                decision = policy.evaluate_neighbor(
                    hostname=neighbor.remote_hostname,
                    management_ip=next_host,
                    protocol=neighbor.protocol,
                )
                if not decision.traversable:
                    marker = (
                        f"{neighbor.remote_hostname.casefold()}|{next_host or ''}"
                    )
                    if marker not in recorded_boundary:
                        recorded_boundary.add(marker)
                        visits.append(
                            DeviceVisit(
                                next_host or neighbor.remote_hostname,
                                depth + 1,
                                SKIPPED,
                                f"boundary {decision.verdict}: {decision.reason}",
                                hostname=neighbor.remote_hostname,
                            )
                        )
                    continue
            if next_host is None:
                if neighbor.remote_hostname.casefold() not in recorded_missing_ip:
                    recorded_missing_ip.add(neighbor.remote_hostname.casefold())
                    visits.append(
                        DeviceVisit(
                            neighbor.remote_hostname,
                            depth + 1,
                            SKIPPED,
                            "no management IP advertised over "
                            f"{neighbor.protocol.upper()}",
                            hostname=neighbor.remote_hostname,
                        )
                    )
                continue
            if next_host in enqueued_hosts:
                continue
            enqueued_hosts.add(next_host)
            queue.append(
                (
                    next_host,
                    depth + 1,
                    f"{neighbor.protocol} neighbor of {result.device.hostname}",
                )
            )

    if not results and first_seed_error is not None:
        # Every seed failed: surface the first (usually most relevant) error
        # so the operator sees the same friendly message single-seed runs get.
        raise first_seed_error

    return MultiHopDiscoveryReport(
        seed_host=seed,
        config=resolved_config,
        results=tuple(results),
        visits=tuple(visits),
        seed_hosts=tuple(seeds),
    )
