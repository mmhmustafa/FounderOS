"""Fixture-only Atlas demonstration composition."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .discovery import DiscoveryEngine, DiscoveryResult, NetworkNeighbor
from .discovery.adapters import CiscoIOSAdapter
from .topology import TopologyGraph, TopologyReconciler, TopologySnapshot


def atlas_app_root() -> Path:
    return Path(__file__).resolve().parents[2] / "apps" / "atlas"


def run_atlas_discovery_demo() -> tuple[DiscoveryResult, TopologyGraph, TopologySnapshot]:
    """Run existing Atlas discovery against the bundled Cisco IOS fixtures."""

    fixture_root = atlas_app_root() / "fixtures" / "cisco_ios"
    raw_outputs = {
        "show version": (fixture_root / "show_version.txt").read_text(encoding="utf-8"),
        "show ip interface brief": (
            fixture_root / "show_ip_interface_brief.txt"
        ).read_text(encoding="utf-8"),
        "show cdp neighbors detail": (
            fixture_root / "show_cdp_neighbors_detail.txt"
        ).read_text(encoding="utf-8"),
    }
    result = DiscoveryEngine(CiscoIOSAdapter()).discover(raw_outputs)
    second_device_id = "fixture-session:access-sw-01"
    secondary_neighbor = NetworkNeighbor(
        local_device_id=second_device_id,
        local_interface="GigabitEthernet1/0/3",
        remote_hostname="router-01",
        remote_interface="GigabitEthernet0/0",
        remote_management_ip="10.0.0.254",
        protocol="cdp",
        metadata={"source": "secondary_mock_observation"},
    )
    second_result = replace(
        result,
        device=replace(
            result.device,
            device_id=second_device_id,
            metadata={**dict(result.device.metadata), "discovery_session": "secondary"},
        ),
        neighbors=tuple(
            replace(neighbor, local_device_id=second_device_id)
            for neighbor in result.neighbors
        ) + (secondary_neighbor,),
        metadata={**dict(result.metadata), "discovery_session": "secondary"},
    )
    graph = TopologyReconciler().reconcile((result, second_result))
    snapshot = TopologySnapshot.from_graph(
        graph,
        metadata={"source": "atlas_discovery_demo"},
    )
    return result, graph, snapshot
