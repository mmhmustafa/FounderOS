"""Acceptance coverage for deterministic Atlas multi-device reconciliation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from founderos_atlas import DiscoveryEngine
from founderos_atlas.discovery import DiscoveryResult, NetworkDevice, NetworkInterface, NetworkNeighbor
from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.topology import TopologyGraph, TopologyReconciler


class TopologyReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_root = (
            Path(__file__).resolve().parents[1]
            / "apps" / "atlas" / "fixtures" / "cisco_ios"
        )
        raw_outputs = {
            "show version": (fixture_root / "show_version.txt").read_text(encoding="utf-8"),
            "show ip interface brief": (
                fixture_root / "show_ip_interface_brief.txt"
            ).read_text(encoding="utf-8"),
            "show cdp neighbors detail": (
                fixture_root / "show_cdp_neighbors_detail.txt"
            ).read_text(encoding="utf-8"),
        }
        cls.base = DiscoveryEngine(CiscoIOSAdapter()).discover(raw_outputs)

    def observation(
        self,
        *,
        device_id: str,
        hostname: str,
        management_ip: str,
        vendor: str = "cisco",
        metadata: dict[str, object] | None = None,
        interfaces: tuple[NetworkInterface, ...] | None = None,
        neighbors: tuple[NetworkNeighbor, ...] = (),
    ) -> DiscoveryResult:
        device = NetworkDevice(
            device_id=device_id,
            hostname=hostname,
            management_ip=management_ip,
            vendor=vendor,
            platform="virtual-fixture",
            os_name="fixture-os",
            os_version="1.0",
            serial_number=None,
            metadata=metadata or {},
        )
        normalized_neighbors = tuple(
            replace(neighbor, local_device_id=device_id) for neighbor in neighbors
        )
        return DiscoveryResult(
            device=device,
            interfaces=interfaces or (),
            neighbors=normalized_neighbors,
            facts=(),
            adapter_vendor="fixture",
            platform_family="fixture",
            metadata={"source": "test_fixture"},
        )

    def test_merge_identical_devices(self) -> None:
        graph = TopologyReconciler().reconcile((self.base, self.base))
        self.assertEqual(1, graph.device_count())
        self.assertEqual(1, graph.summary()["duplicates_removed"])

    def test_merge_by_hostname(self) -> None:
        duplicate = replace(
            self.base,
            device=replace(self.base.device, device_id="session:alternate", management_ip="10.0.0.99"),
            neighbors=tuple(
                replace(item, local_device_id="session:alternate") for item in self.base.neighbors
            ),
        )
        graph = TopologyReconciler().reconcile((duplicate, self.base))
        self.assertEqual(1, graph.device_count())
        self.assertEqual("access-sw-01", graph.find_device("access-sw-01").hostname)

    def test_merge_by_management_ip(self) -> None:
        renamed = replace(
            self.base,
            device=replace(self.base.device, device_id="session:renamed", hostname="access-renamed"),
            neighbors=tuple(
                replace(item, local_device_id="session:renamed") for item in self.base.neighbors
            ),
        )
        graph = TopologyReconciler().reconcile((renamed, self.base))
        self.assertEqual(1, graph.device_count())
        self.assertIsNotNone(graph.find_device("10.0.0.10"))

    def test_preserve_neighbors(self) -> None:
        extra = NetworkNeighbor(
            local_device_id="session:alternate",
            local_interface="GigabitEthernet1/0/3",
            remote_hostname="router-01",
            remote_management_ip="10.0.0.254",
            protocol="cdp",
        )
        duplicate = replace(
            self.base,
            device=replace(self.base.device, device_id="session:alternate"),
            neighbors=(extra,),
        )
        graph = TopologyReconciler().reconcile((self.base, duplicate))
        self.assertEqual(3, graph.edge_count())
        self.assertEqual(
            {"ap-01", "dist-sw-01", "router-01"},
            {item.remote_hostname for item in graph.neighbors(self.base.device.device_id)},
        )

    def test_preserve_interfaces(self) -> None:
        extra_interface = NetworkInterface(
            name="Loopback0", ip_address="192.0.2.1", status="up", protocol_status="up",
            metadata={"source": "secondary_fixture"},
        )
        duplicate = replace(
            self.base,
            device=replace(self.base.device, device_id="session:alternate"),
            interfaces=(extra_interface,),
            neighbors=(),
        )
        graph = TopologyReconciler().reconcile((self.base, duplicate))
        self.assertEqual(5, len(graph.interfaces(self.base.device.device_id)))
        self.assertIn("Loopback0", {item.name for item in graph.interfaces(self.base.device.device_id)})

    def test_preserve_metadata(self) -> None:
        first = self.observation(
            device_id="device:a", hostname="core-01", management_ip="10.1.0.1",
            metadata={"site": "primary"},
        )
        second = self.observation(
            device_id="device:b", hostname="core-01", management_ip="10.1.0.1",
            metadata={"rack": "r1"},
        )
        device = TopologyReconciler().reconcile((second, first)).find_device("core-01")
        self.assertEqual("primary", device.metadata["site"])
        self.assertEqual("r1", device.metadata["rack"])

    def test_detect_conflict(self) -> None:
        conflict = replace(
            self.base,
            device=replace(self.base.device, device_id="session:conflict", vendor="juniper"),
            neighbors=(),
        )
        graph = TopologyReconciler().reconcile((conflict, self.base))
        warnings = graph.warnings()
        self.assertTrue(any(item.field == "vendor" for item in warnings))
        self.assertEqual(1, graph.summary()["warning_count"])

    def test_merge_graphs(self) -> None:
        first = TopologyReconciler().reconcile((self.base,))
        second_result = self.observation(
            device_id="device:dist", hostname="dist-sw-01", management_ip="10.0.0.2"
        )
        second = TopologyReconciler().reconcile((second_result,))
        first.merge_graph(second)
        self.assertEqual(2, first.device_count())
        self.assertEqual(2, first.summary()["input_device_count"])

    def test_summary_is_correct(self) -> None:
        graph = TopologyReconciler().reconcile((self.base, self.base))
        summary = graph.summary()
        self.assertEqual(2, summary["input_device_count"])
        self.assertEqual(1, summary["device_count"])
        self.assertEqual(2, summary["edge_count"])
        self.assertEqual(1, summary["duplicates_removed"])
        self.assertEqual(4, summary["interface_count"])

    def test_output_is_deterministic(self) -> None:
        conflict = replace(
            self.base,
            device=replace(self.base.device, device_id="session:z", vendor="juniper"),
            neighbors=(),
        )
        first = TopologyReconciler().reconcile((self.base, conflict))
        second = TopologyReconciler().reconcile((conflict, self.base))
        self.assertEqual(first.devices(), second.devices())
        self.assertEqual(first.interfaces(self.base.device.device_id), second.interfaces(self.base.device.device_id))
        self.assertEqual(first.edges(), second.edges())
        self.assertEqual(first.warnings(), second.warnings())
        self.assertEqual(first.summary(), second.summary())

    def test_no_duplicate_devices(self) -> None:
        hostname_match = replace(
            self.base, device=replace(self.base.device, device_id="session:hostname"), neighbors=()
        )
        ip_match = replace(
            self.base,
            device=replace(self.base.device, device_id="session:ip", hostname="renamed"),
            neighbors=(),
        )
        graph = TopologyReconciler().reconcile((hostname_match, ip_match, self.base))
        self.assertEqual(1, graph.device_count())
        self.assertEqual(2, graph.summary()["duplicates_removed"])

    def test_fixture_only_reconciliation(self) -> None:
        graph = TopologyReconciler().reconcile((self.base,))
        self.assertEqual("none", self.base.metadata["transport"])
        self.assertTrue(graph.summary()["in_memory_only"])


if __name__ == "__main__":
    unittest.main()
