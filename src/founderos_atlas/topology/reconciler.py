"""Deterministic reconciliation of multiple Atlas discovery observations."""

from __future__ import annotations

from collections.abc import Iterable

from founderos_atlas.discovery import DiscoveryResult

from .graph import TopologyGraph


class TopologyReconciler:
    """Merge isolated observations into one canonical in-memory topology."""

    def reconcile(self, results: Iterable[DiscoveryResult]) -> TopologyGraph:
        observations = tuple(results)
        if not all(isinstance(result, DiscoveryResult) for result in observations):
            raise TypeError("results must contain only DiscoveryResult values")
        ordered = sorted(
            observations,
            key=lambda result: (
                result.device.hostname.casefold(),
                result.device.management_ip,
                (result.device.serial_number or "").casefold(),
                result.device.device_id,
            ),
        )
        graph = TopologyGraph()
        for result in ordered:
            graph.merge_discovery_result(result)
        return graph
