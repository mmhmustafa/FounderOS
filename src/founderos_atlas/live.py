"""Live Atlas discovery compositions built from transport and engine layers."""

from __future__ import annotations

from dataclasses import replace

from .discovery import DiscoveryEngine, DiscoveryResult
from .discovery.adapter import DiscoveryAdapter
from .discovery.adapters import CiscoIOSAdapter
from .discovery.executor import (
    DiscoveryExecution,
    OUTCOME_AUTH_FAILED,
    OUTCOME_DISCOVERED,
    OUTCOME_UNREACHABLE,
    OUTCOME_UNSUPPORTED,
    run_pool,
)
from .discovery.multihop import (
    HostTransportFactory,
    MultiHopConfig,
    MultiHopDiscoveryReport,
    _discover_with_registry,
    discover_multihop,
)
from .identity import IdentityResolver
from .topology import TopologyGraph, TopologyReconciler, TopologySnapshot
from .transport import AtlasTransportError, DeviceTransport
from .transport.exceptions import AuthenticationError, PermissionDeniedError


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
    registry=None,
    config: MultiHopConfig | None = None,
    policy=None,
    extra_seeds: tuple[str, ...] = (),
    on_neighbor=None,
) -> tuple[MultiHopDiscoveryReport, TopologyGraph, TopologySnapshot]:
    """Discover the seed(s) and reachable neighbors, then reconcile.

    Traversal lives in ``discovery.multihop``; this composition only wires it
    to the existing reconciliation and snapshot pipeline. ``policy``,
    ``extra_seeds``, ``on_neighbor``, and the platform ``registry``
    (PR-043) pass through to the traversal.
    """

    report = discover_multihop(
        seed_host,
        transport_factory,
        adapter=adapter,
        registry=registry,
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
    # Platform mix (PR-043): how many devices each driver family produced.
    platform_counts: dict[str, int] = {}
    for result in report.results:
        family = result.platform_family or "unknown"
        platform_counts[family] = platform_counts.get(family, 0) + 1
    # Relationship-type counts (PR-043.1): physical links vs routing
    # adjacencies vs protocol peers vs unresolved peer identities —
    # never a bare "edges" number.
    from founderos_atlas.platforms import relationship_counts

    hostname_by_id = {
        device.device_id: device.hostname for device in graph.devices()
    }
    relationships = relationship_counts(
        graph.edges(),
        hostname_by_device_id=hostname_by_id,
        discovered_hostnames={
            device.hostname for device in graph.devices()
        },
    )
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
            "platforms": dict(sorted(platform_counts.items())),
            "relationships": relationships,
            **({"failed_hosts": failed_hosts} if failed_hosts else {}),
        },
    )
    return report, graph, snapshot


def _reconcile_results(results, *, metadata_extra: dict) -> tuple[
    TopologyGraph, TopologySnapshot
]:
    """The shared reconciliation + snapshot path — identical to multihop's,
    so pooled and sequential discovery produce byte-identical graphs for
    the same evidence (PR-043.3)."""

    from founderos_atlas.platforms import relationship_counts

    resolution = IdentityResolver().resolve(results)
    canonical_results = resolution.canonicalize(results)
    graph = TopologyReconciler().reconcile(canonical_results)
    platform_counts: dict[str, int] = {}
    for result in results:
        family = result.platform_family or "unknown"
        platform_counts[family] = platform_counts.get(family, 0) + 1
    hostname_by_id = {
        device.device_id: device.hostname for device in graph.devices()
    }
    relationships = relationship_counts(
        graph.edges(),
        hostname_by_device_id=hostname_by_id,
        discovered_hostnames={device.hostname for device in graph.devices()},
    )
    snapshot = TopologySnapshot.from_graph(
        graph,
        metadata={
            "source": "atlas_live_discovery",
            "transport": "ssh",
            "read_only": True,
            "identity_resolution": True,
            "platforms": dict(sorted(platform_counts.items())),
            "relationships": relationships,
            **metadata_extra,
        },
    )
    return graph, snapshot


def run_pooled_discovery(
    addresses: list[str],
    transport_factory: HostTransportFactory,
    *,
    registry=None,
    worker_count: int = 4,
    completed_addresses: frozenset[str] = frozenset(),
    clock=None,
    on_progress=None,
) -> tuple[DiscoveryExecution, TopologyGraph, TopologySnapshot]:
    """Discover a FLAT candidate list concurrently through the worker pool.

    Used by the enterprise entry modes (management network / multiple
    seeds / CSV import) where candidates are known up front. Each worker
    detects the platform and drives the SAME per-host pipeline
    (``_discover_with_registry``) — correctness and canonical output are
    unchanged; only execution is parallel. Results reconcile in candidate
    order, so the graph is deterministic regardless of completion order.
    """

    from founderos_atlas.platforms import (
        UnsupportedPlatformError,
        default_registry,
    )

    resolved_registry = registry or default_registry()
    execution = DiscoveryExecution(
        list(addresses),
        worker_count=worker_count,
        completed=set(completed_addresses),
        clock=clock,
    )

    def worker(address: str, timer):
        try:
            with timer.stage("tcp_connect"):
                transport = transport_factory(address)
                transport.connect()
            try:
                with timer.stage("discovery"):
                    result = _discover_with_registry(
                        transport, resolved_registry, address
                    )
            finally:
                transport.disconnect()
        except UnsupportedPlatformError as error:
            return None, OUTCOME_UNSUPPORTED, None, str(error)[:120]
        except (AuthenticationError, PermissionDeniedError) as error:
            return None, OUTCOME_AUTH_FAILED, None, str(error)[:120]
        except AtlasTransportError as error:
            return None, OUTCOME_UNREACHABLE, None, str(error)[:120]
        platform = result.platform_family
        return (
            result,
            OUTCOME_DISCOVERED,
            platform,
            f"{result.device.hostname} — {platform} inventory complete",
        )

    run_pool(execution, worker, on_progress=on_progress)
    graph, snapshot = _reconcile_results(
        execution.results_in_order(),
        metadata_extra={
            "discovery_mode": "pooled",
            "worker_count": worker_count,
        },
    )
    return execution, graph, snapshot


def run_discovery_plan(
    plan,
    transport_factory: HostTransportFactory,
    *,
    registry=None,
    policy=None,
    on_neighbor=None,
    completed_addresses: frozenset[str] = frozenset(),
):
    """Run any resolved ``DiscoveryPlan`` (PR-043.2) through the multihop
    engine and report per-candidate outcomes.

    Every entry method (seed / management network / multiple seeds / CSV)
    resolves to a candidate list; this composition seeds the traversal
    with those addresses, reuses per-host platform detection and identity
    dedup unchanged, and maps the traversal's visits back onto the
    candidates. Resume skips already-completed addresses without
    re-attempting them. Returns ``(report, graph, snapshot, candidates,
    summary)``.
    """

    from .discovery import (
        classify_candidate_outcomes,
        summarize_candidates,
    )

    addresses = [
        address
        for address in plan.seed_addresses
        if address not in completed_addresses
    ]
    if not addresses:
        raise ValueError("no candidate addresses remain to attempt")
    report, graph, snapshot = run_multihop_discovery(
        transport_factory,
        addresses[0],
        registry=registry,
        config=MultiHopConfig(
            max_depth=plan.effective_depth, max_devices=plan.max_devices
        ),
        policy=policy,
        extra_seeds=tuple(addresses[1:]),
        on_neighbor=on_neighbor,
    )
    visits = tuple(
        (visit.host, visit.status, visit.detail) for visit in report.visits
    )
    candidates = classify_candidate_outcomes(
        plan, visits, completed_addresses=completed_addresses
    )
    summary = {
        "mode": plan.mode,
        "policy": plan.policy,
        **summarize_candidates(candidates),
        "platforms": dict(snapshot.metadata.get("platforms") or {}),
        "relationships": dict(snapshot.metadata.get("relationships") or {}),
        "devices_discovered": snapshot.device_count,
    }
    return report, graph, snapshot, candidates, summary
