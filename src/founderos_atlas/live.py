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
    reachability=None,
    workers: int = 1,
) -> tuple[MultiHopDiscoveryReport, TopologyGraph, TopologySnapshot]:
    """Discover the seed(s) and reachable neighbors, then reconcile.

    Traversal lives in ``discovery.multihop``; this composition only wires it
    to the existing reconciliation and snapshot pipeline. ``policy``,
    ``extra_seeds``, ``on_neighbor``, and the platform ``registry``
    (PR-043) pass through to the traversal. ``workers`` and
    ``reachability`` (PR-043.6) enable the concurrent, reachability-gated
    production path.
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
        reachability=reachability,
        workers=workers,
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
            # PR-043.8 (CONSISTENCY): the discovery statistics travel WITH
            # the Enterprise Knowledge Graph so every consumer reads the
            # same address-space facts. Unused (unreachable) addresses are
            # Information here, never failures.
            "discovery_statistics": _discovery_statistics(
                report, graph.device_count()
            ).to_dict(),
            **_correlation_metadata(graph),
            **({"failed_hosts": failed_hosts} if failed_hosts else {}),
        },
    )
    return report, graph, snapshot


def _discovery_statistics(report, device_count: int):
    """Classify the multihop report's per-address outcomes into the
    canonical discovery statistics (PR-043.8). Delegated to the shared
    classifier so the snapshot and every consumer agree."""

    from founderos_atlas.enterprise import classify_discovery_visits

    return classify_discovery_visits(
        connected=len(report.connected),
        failed_details=tuple(visit.detail for visit in report.failed),
        skipped=len(report.skipped),
        managed_devices=device_count,
    )


def _correlation_metadata(graph: TopologyGraph) -> dict:
    """Fuse the reconciled graph's evidence into enterprise knowledge
    (PR-043.7): correlated relationships with provenance, the address
    ownership index summary, and honest unresolved observations. Topology
    presentation consumes THIS — never raw per-protocol edges alone."""

    from founderos_atlas.correlation import EvidenceCorrelationEngine

    devices = [
        {
            "device_id": device.device_id,
            "hostname": device.hostname,
            "management_ip": device.management_ip,
            "metadata": dict(device.metadata),
            "interfaces": [
                {
                    "name": interface.name,
                    "ip_address": interface.ip_address,
                    "description": interface.description,
                    "metadata": dict(interface.metadata),
                }
                for interface in graph.interfaces(device.device_id)
            ],
        }
        for device in graph.devices()
    ]
    edges = [
        {
            "local_device_id": edge.local_device_id,
            "local_interface": edge.local_interface,
            "remote_hostname": edge.remote_hostname,
            "remote_interface": edge.remote_interface,
            "remote_management_ip": edge.remote_management_ip,
            "protocol": edge.protocol,
            "metadata": dict(edge.metadata),
        }
        for edge in graph.edges()
    ]
    correlation = EvidenceCorrelationEngine().correlate(devices, edges)
    ownership = correlation.ownership.to_dict()
    return {
        "correlation": correlation.summary(),
        "correlated_relationships": tuple(
            relationship.to_dict() for relationship in correlation.relationships
        ),
        "unresolved_observations": tuple(
            observation.to_dict() for observation in correlation.unresolved
        ),
        # The Enterprise Address Ownership Index (Part 4): every
        # discovered address belongs to exactly one canonical device;
        # conflicted addresses are excluded and reported.
        "address_ownership": ownership["addresses"],
        **(
            {"ownership_conflicts": ownership["conflicts"]}
            if ownership["conflicts"] else {}
        ),
    }


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
            **_correlation_metadata(graph),
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
    workers: int | None = None,
    reachability=None,
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
    # PR-043.7 (FUSION, Part 1): every entry method executes the SAME
    # parallel, reachability-gated production path as seed discovery —
    # the worker pool is sized to the candidate list exactly like
    # ``atlas_discover_command`` sizes it. No legacy sequential path.
    resolved_workers = (
        workers if workers is not None else min(32, max(4, len(addresses)))
    )
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
        reachability=reachability,
        workers=resolved_workers,
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
