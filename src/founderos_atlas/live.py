"""Live Atlas discovery compositions built from transport and engine layers."""

from __future__ import annotations

from dataclasses import replace

from .discovery import DiscoveryEngine, DiscoveryResult
from .discovery.adapter import DiscoveryAdapter
from .discovery.adapters import CiscoIOSAdapter
from .discovery.multihop import (
    HostTransportFactory,
    MultiHopConfig,
    MultiHopDiscoveryReport,
    discover_multihop,
)
from .identity import IdentityResolver
from .topology import TopologyGraph, TopologyReconciler, TopologySnapshot
from .transport import DeviceTransport


def run_live_discovery(
    transport: DeviceTransport,
    adapter: DiscoveryAdapter | None = None,
) -> tuple[DiscoveryResult, TopologyGraph, TopologySnapshot]:
    """Collect raw command output over a transport and reuse the fixture pipeline.

    The transport only supplies raw text; parsing, reconciliation, and
    snapshot creation are the same code paths the fixture demo uses.
    """

    if not isinstance(transport, DeviceTransport):
        raise TypeError("transport must implement DeviceTransport")
    resolved_adapter = adapter if adapter is not None else CiscoIOSAdapter()
    engine = DiscoveryEngine(resolved_adapter)
    with transport:
        raw_outputs = transport.execute_many(resolved_adapter.required_commands)
    # The connected address is the deterministic identity fallback when the
    # device output does not yield a hostname or management IP.
    host = getattr(transport, "host", None)
    result = engine.discover(
        raw_outputs,
        management_ip_hint=host if isinstance(host, str) else None,
    )
    graph = TopologyReconciler().reconcile((result,))
    snapshot = TopologySnapshot.from_graph(
        graph,
        metadata={
            "source": "atlas_live_discovery",
            "transport": "ssh",
            "read_only": True,
        },
    )
    return result, graph, snapshot


def run_multihop_discovery(
    transport_factory: HostTransportFactory,
    seed_host: str,
    *,
    adapter: DiscoveryAdapter | None = None,
    config: MultiHopConfig | None = None,
    policy=None,
    extra_seeds: tuple[str, ...] = (),
    on_neighbor=None,
) -> tuple[MultiHopDiscoveryReport, TopologyGraph, TopologySnapshot]:
    """Discover the seed(s) and reachable neighbors, then reconcile.

    Traversal lives in ``discovery.multihop``; this composition only wires it
    to the existing reconciliation and snapshot pipeline. ``policy``,
    ``extra_seeds``, and ``on_neighbor`` pass through to the traversal.
    """

    report = discover_multihop(
        seed_host,
        transport_factory,
        adapter=adapter,
        config=config,
        policy=policy,
        extra_seeds=extra_seeds,
        on_neighbor=on_neighbor,
    )
    resolution = IdentityResolver().resolve(report.results)
    canonical_results = resolution.canonicalize(report.results)
    # Record how many hops from the seed each device was found at, so the
    # viewer can show discovery depth per node.
    canonical_results = tuple(
        replace(
            result,
            device=replace(
                result.device,
                metadata={**dict(result.device.metadata), "discovery_depth": visit.depth},
            ),
        )
        for visit, result in zip(report.connected, canonical_results)
    )
    graph = TopologyReconciler().reconcile(canonical_results)
    failed_hosts = tuple(sorted(visit.host for visit in report.failed))
    snapshot = TopologySnapshot.from_graph(
        graph,
        metadata={
            "source": "atlas_live_discovery",
            "transport": "ssh",
            "read_only": True,
            "discovery_mode": "multihop",
            "max_depth": report.config.max_depth,
            "max_devices": report.config.max_devices,
            "identity_resolution": True,
            **({"failed_hosts": failed_hosts} if failed_hosts else {}),
        },
    )
    return report, graph, snapshot
