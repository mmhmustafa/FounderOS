"""Live single-device Atlas discovery composed from transport and engine."""

from __future__ import annotations

from .discovery import DiscoveryEngine, DiscoveryResult
from .discovery.adapter import DiscoveryAdapter
from .discovery.adapters import CiscoIOSAdapter
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
