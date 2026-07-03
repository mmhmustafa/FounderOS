"""Fixture-only Atlas demonstration composition."""

from __future__ import annotations

from pathlib import Path

from .discovery import DiscoveryEngine, DiscoveryResult
from .discovery.adapters import CiscoIOSAdapter
from .topology import TopologyGraph


def atlas_app_root() -> Path:
    return Path(__file__).resolve().parents[2] / "apps" / "atlas"


def run_atlas_discovery_demo() -> tuple[DiscoveryResult, TopologyGraph]:
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
    graph = TopologyGraph()
    graph.add_result(result)
    return result, graph
