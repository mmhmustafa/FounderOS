"""Acceptance coverage for the fixture-only Atlas Discovery foundation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import urllib.request

from founderos_atlas.discovery import (
    DiscoveryEngine,
    DiscoveryResult,
    MissingCommandOutputError,
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
    UnsupportedAdapterError,
)
from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.topology import DuplicateDeviceError, TopologyGraph
from founderos_runtime.evaluation import load_evaluation_rubric
from founderos_runtime.manifest_loader import ManifestLoader


class AtlasDiscoveryFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.atlas_root = Path(__file__).resolve().parents[1] / "apps" / "atlas"
        cls.fixture_root = cls.atlas_root / "fixtures" / "cisco_ios"
        cls.raw_outputs = {
            "show version": (cls.fixture_root / "show_version.txt").read_text(encoding="utf-8"),
            "show ip interface brief": (
                cls.fixture_root / "show_ip_interface_brief.txt"
            ).read_text(encoding="utf-8"),
            "show cdp neighbors detail": (
                cls.fixture_root / "show_cdp_neighbors_detail.txt"
            ).read_text(encoding="utf-8"),
        }

    def setUp(self) -> None:
        self.adapter = CiscoIOSAdapter()
        self.engine = DiscoveryEngine(self.adapter)

    def test_cisco_ios_show_version_parsing(self) -> None:
        device = self.adapter.parse_inventory(self.raw_outputs)
        self.assertEqual("access-sw-01", device.hostname)
        self.assertEqual("10.0.0.10", device.management_ip)
        self.assertEqual("WS-C2960X-48FPS-L", device.platform)
        self.assertEqual("15.2(7)E10", device.os_version)
        self.assertEqual("FOC1234X0YZ", device.serial_number)

    def test_cisco_ios_interface_parsing(self) -> None:
        interfaces = self.adapter.parse_interfaces(self.raw_outputs)
        self.assertEqual(4, len(interfaces))
        vlan = next(item for item in interfaces if item.name == "Vlan1")
        self.assertEqual("10.0.0.10", vlan.ip_address)
        disabled = next(item for item in interfaces if item.name == "GigabitEthernet1/0/2")
        self.assertEqual("administratively_down", disabled.status)

    def test_cisco_ios_cdp_neighbor_parsing(self) -> None:
        neighbors = self.adapter.parse_neighbors(self.raw_outputs)
        self.assertEqual(2, len(neighbors))
        distribution = next(item for item in neighbors if item.remote_hostname == "dist-sw-01")
        self.assertEqual("GigabitEthernet1/0/48", distribution.local_interface)
        self.assertEqual("GigabitEthernet1/0/24", distribution.remote_interface)
        self.assertEqual("10.0.0.2", distribution.remote_management_ip)
        self.assertEqual("cdp", distribution.protocol)

    def test_discovery_engine_returns_result(self) -> None:
        result = self.engine.discover(self.raw_outputs)
        self.assertIsInstance(result, DiscoveryResult)
        self.assertEqual("cisco", result.adapter_vendor)
        self.assertEqual("ios", result.platform_family)
        self.assertEqual(3, len(result.facts))

    def test_discovery_result_is_vendor_neutral(self) -> None:
        result = self.engine.discover(self.raw_outputs)
        self.assertIsInstance(result.device, NetworkDevice)
        self.assertTrue(all(isinstance(item, NetworkInterface) for item in result.interfaces))
        self.assertTrue(all(isinstance(item, NetworkNeighbor) for item in result.neighbors))
        self.assertEqual("none", result.metadata["transport"])
        self.assertFalse(result.metadata["persistence"])

    def test_topology_graph_adds_devices_and_edges(self) -> None:
        result = self.engine.discover(self.raw_outputs)
        graph = TopologyGraph()
        graph.add_result(result)
        self.assertEqual((result.device,), graph.devices())
        self.assertEqual(result.neighbors, graph.neighbors(result.device.device_id))
        self.assertEqual(2, graph.summary()["edge_count"])

    def test_duplicate_devices_are_deterministic(self) -> None:
        result = self.engine.discover(self.raw_outputs)
        graph = TopologyGraph()
        graph.add_result(result)
        graph.add_result(result)
        self.assertEqual(1, graph.summary()["device_count"])
        self.assertEqual(2, graph.summary()["edge_count"])
        with self.assertRaisesRegex(DuplicateDeviceError, "conflicting device facts"):
            graph.add_device(replace(result.device, os_version="different"))

    def test_missing_command_output_is_clear(self) -> None:
        incomplete = dict(self.raw_outputs)
        del incomplete["show version"]
        with self.assertRaisesRegex(
            MissingCommandOutputError, "required command output is missing: show version"
        ):
            self.engine.discover(incomplete)

    def test_unsupported_adapter_is_clear(self) -> None:
        with self.assertRaisesRegex(UnsupportedAdapterError, "DiscoveryAdapter"):
            DiscoveryEngine(object())  # type: ignore[arg-type]

    def test_no_real_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            result = self.engine.discover(self.raw_outputs)
        self.assertEqual("access-sw-01", result.device.hostname)

    def test_assets_are_fixture_only_and_manifests_validate(self) -> None:
        self.assertEqual(
            {
                "show_cdp_neighbors_detail.txt",
                "show_ip_interface_brief.txt",
                "show_version.txt",
            },
            {path.name for path in self.fixture_root.iterdir() if path.is_file()},
        )
        loader = ManifestLoader()
        self.assertEqual(
            "founderos.atlas",
            loader.load_app_manifest(self.atlas_root / "manifests" / "app.yaml")["id"],
        )
        loader.load_workflow_manifest(
            self.atlas_root / "manifests" / "workflows" / "discover-network.yaml"
        )
        loader.load_agent_manifest(
            self.atlas_root / "manifests" / "agents" / "network-discovery-agent.yaml"
        )
        load_evaluation_rubric(
            self.atlas_root / "manifests" / "rubrics" / "topology-quality-rubric.yaml"
        )

    def test_output_is_deterministic(self) -> None:
        first = self.engine.discover(self.raw_outputs)
        second = self.engine.discover(dict(reversed(tuple(self.raw_outputs.items()))))
        self.assertEqual(first, second)
        first_graph = TopologyGraph()
        second_graph = TopologyGraph()
        first_graph.add_result(first)
        second_graph.add_result(second)
        self.assertEqual(first_graph.summary(), second_graph.summary())


if __name__ == "__main__":
    unittest.main()
