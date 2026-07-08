"""Acceptance tests for PR-021 controlled multi-hop live discovery."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from founderos_atlas.discovery import (
    DeviceVisit,
    MultiHopConfig,
    discover_multihop,
)
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.topology import TopologyReconciler
from founderos_atlas.transport import ConnectionTimeoutError, SSHDeviceTransport
from founderos_runtime.cli import main

from tests.test_atlas_transport import FakeConnection, PASSWORD, make_credentials


def show_version(hostname: str) -> str:
    return (
        "Cisco IOS Software, IOSv Software (VIOS-ADVENTERPRISEK9-M), "
        "Version 15.9(3)M12, RELEASE SOFTWARE (fc1)\n"
        "Technical Support: http://www.cisco.com/techsupport\n"
        "\n"
        f"{hostname} uptime is 10 minutes\n"
        'System image file is "flash0:/vios-adventerprisek9-m"\n'
        "\n"
        "Cisco IOSv (revision 1.0) with 435457K/87040K bytes of memory.\n"
        f"Processor board ID SERIAL-{hostname.upper()}\n"
    )


def interface_brief(ip: str) -> str:
    return (
        "Interface                  IP-Address      OK? Method Status                Protocol\n"
        f"GigabitEthernet0/0         {ip:<15} YES manual up                    up\n"
        "GigabitEthernet0/1         unassigned      YES unset  up                    up\n"
    )


def cdp_detail(neighbors: tuple[tuple[str, str | None], ...]) -> str:
    blocks = []
    for index, (remote_hostname, remote_ip) in enumerate(neighbors, start=1):
        address = f"  IP address: {remote_ip}\n" if remote_ip is not None else ""
        blocks.append(
            "-------------------------\n"
            f"Device ID: {remote_hostname}\n"
            "Entry address(es):\n"
            f"{address}"
            "Platform: cisco IOSv,  Capabilities: Router\n"
            f"Interface: GigabitEthernet0/{index},  "
            f"Port ID (outgoing port): GigabitEthernet0/{index}\n"
            "Holdtime : 120 sec\n"
        )
    return "".join(blocks)


def device_outputs(
    hostname: str, ip: str, neighbors: tuple[tuple[str, str | None], ...] = ()
) -> dict[str, str]:
    return {
        "show version": show_version(hostname),
        "show ip interface brief": interface_brief(ip),
        "show cdp neighbors detail": cdp_detail(neighbors),
    }


class ScriptedNetwork:
    """Multi-device fake network driven through the real SSH transport."""

    def __init__(
        self,
        topology: dict[str, dict[str, str]],
        unreachable: frozenset[str] = frozenset(),
    ) -> None:
        self.topology = topology
        self.unreachable = set(unreachable)
        self.connections: dict[str, FakeConnection] = {}
        self.connect_attempts: list[str] = []

    def transport_factory(self, host: str) -> SSHDeviceTransport:
        def connection_factory(**kwargs) -> FakeConnection:
            self.connect_attempts.append(host)
            if host in self.unreachable or host not in self.topology:
                raise TimeoutError(f"connection to {host} timed out")
            connection = FakeConnection(dict(self.topology[host]))
            self.connections[host] = connection
            return connection

        return SSHDeviceTransport(
            make_credentials(host=host), connection_factory=connection_factory
        )

    def commands_sent(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (host, command)
            for host, connection in sorted(self.connections.items())
            for command in connection.commands
        )


def linear_chain() -> ScriptedNetwork:
    """r1 -> r2 -> r3, each device also lists the previous hop."""

    return ScriptedNetwork(
        {
            "10.0.0.1": device_outputs("r1", "10.0.0.1", (("r2", "10.0.0.2"),)),
            "10.0.0.2": device_outputs(
                "r2", "10.0.0.2", (("r1", "10.0.0.1"), ("r3", "10.0.0.3"))
            ),
            "10.0.0.3": device_outputs("r3", "10.0.0.3", (("r2", "10.0.0.2"),)),
        }
    )


class MultiHopTraversalTests(unittest.TestCase):
    def test_seed_device_discovery(self) -> None:
        network = ScriptedNetwork({"10.0.0.1": device_outputs("r1", "10.0.0.1")})
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(1, len(report.results))
        self.assertEqual("r1", report.results[0].device.hostname)
        self.assertEqual(
            (DeviceVisit("10.0.0.1", 0, "connected", "seed", hostname="r1"),),
            report.visits,
        )

    def test_neighbor_discovery(self) -> None:
        network = linear_chain()
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(["r1", "r2"], [r.device.hostname for r in report.results])
        self.assertEqual(2, len(report.connected))
        hop = report.connected[1]
        self.assertEqual(("10.0.0.2", 1, "cdp neighbor of r1"), (hop.host, hop.depth, hop.detail))

    def test_duplicate_avoidance(self) -> None:
        network = linear_chain()
        report = discover_multihop(
            "10.0.0.1", network.transport_factory, config=MultiHopConfig(max_depth=3)
        )
        # r2 lists r1 and r3 lists r2 back; every host is contacted exactly once.
        self.assertEqual(["10.0.0.1", "10.0.0.2", "10.0.0.3"], network.connect_attempts)
        self.assertEqual(3, len(report.results))
        self.assertEqual((), report.failed)

    def test_same_device_reached_by_second_address_is_skipped(self) -> None:
        r1_outputs = device_outputs("r1", "10.0.0.1", (("r1-loopback", "10.0.0.99"),))
        network = ScriptedNetwork(
            {"10.0.0.1": r1_outputs, "10.0.0.99": device_outputs("r1", "10.0.0.1")}
        )
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(1, len(report.results))
        self.assertEqual(1, len(report.skipped))
        self.assertIn("already discovered as cisco-ios:r1", report.skipped[0].detail)

    def test_max_depth_enforcement(self) -> None:
        network = linear_chain()
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(1, report.config.max_depth)
        self.assertEqual(2, len(report.results))
        self.assertNotIn("10.0.0.3", network.connect_attempts)

        deeper = linear_chain()
        report = discover_multihop(
            "10.0.0.1", deeper.transport_factory, config=MultiHopConfig(max_depth=2)
        )
        self.assertEqual(["r1", "r2", "r3"], [r.device.hostname for r in report.results])

    def test_max_devices_enforcement(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "r1",
                    "10.0.0.1",
                    (("r2", "10.0.0.2"), ("r3", "10.0.0.3"), ("r4", "10.0.0.4")),
                ),
                "10.0.0.2": device_outputs("r2", "10.0.0.2"),
                "10.0.0.3": device_outputs("r3", "10.0.0.3"),
                "10.0.0.4": device_outputs("r4", "10.0.0.4"),
            }
        )
        report = discover_multihop(
            "10.0.0.1", network.transport_factory, config=MultiHopConfig(max_devices=2)
        )
        self.assertEqual(2, len(report.results))
        limit_skips = [v for v in report.skipped if v.detail == "maximum device limit reached"]
        self.assertEqual(2, len(limit_skips))
        self.assertEqual(["10.0.0.1", "10.0.0.2"], network.connect_attempts)

    def test_unreachable_neighbor_is_skipped_with_warning(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "r1", "10.0.0.1", (("r2", "10.0.0.2"), ("r3", "10.0.0.3"))
                ),
                "10.0.0.3": device_outputs("r3", "10.0.0.3"),
            },
            unreachable=frozenset({"10.0.0.2"}),
        )
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(["r1", "r3"], [r.device.hostname for r in report.results])
        self.assertEqual(1, len(report.failed))
        self.assertEqual("10.0.0.2", report.failed[0].host)
        self.assertIn("timed out", report.failed[0].detail)
        self.assertNotIn(PASSWORD, report.failed[0].detail)

    def test_seed_failure_is_fatal(self) -> None:
        network = ScriptedNetwork({}, unreachable=frozenset({"10.0.0.1"}))
        with self.assertRaises(ConnectionTimeoutError):
            discover_multihop("10.0.0.1", network.transport_factory)

    def test_neighbor_without_management_ip_is_recorded_once(self) -> None:
        network = ScriptedNetwork(
            {"10.0.0.1": device_outputs("r1", "10.0.0.1", (("ap-legacy", None),))}
        )
        report = discover_multihop("10.0.0.1", network.transport_factory)
        self.assertEqual(1, len(report.results))
        self.assertEqual(1, len(report.skipped))
        self.assertEqual("no management IP advertised over CDP", report.skipped[0].detail)

    def test_config_limits_are_validated(self) -> None:
        for kwargs in ({"max_depth": -1}, {"max_devices": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    MultiHopConfig(**kwargs)

    def test_only_read_only_commands_reach_devices(self) -> None:
        network = linear_chain()
        discover_multihop(
            "10.0.0.1", network.transport_factory, config=MultiHopConfig(max_depth=2)
        )
        commands = network.commands_sent()
        self.assertTrue(commands)
        for _, command in commands:
            self.assertTrue(
                command == "terminal length 0" or command.startswith("show "),
                f"unexpected command sent: {command!r}",
            )

    def test_traversal_is_deterministic(self) -> None:
        first = discover_multihop(
            "10.0.0.1", linear_chain().transport_factory, config=MultiHopConfig(max_depth=2)
        )
        second = discover_multihop(
            "10.0.0.1", linear_chain().transport_factory, config=MultiHopConfig(max_depth=2)
        )
        self.assertEqual(first, second)


class MultiHopCompositionTests(unittest.TestCase):
    def test_reconciliation_is_used(self) -> None:
        network = linear_chain()
        original = TopologyReconciler.reconcile
        calls: list[int] = []

        def spying_reconcile(self, results):
            observations = tuple(results)
            calls.append(len(observations))
            return original(self, observations)

        with patch.object(TopologyReconciler, "reconcile", spying_reconcile):
            report, graph, snapshot = run_multihop_discovery(
                network.transport_factory, "10.0.0.1"
            )
        self.assertEqual([2], calls)
        self.assertEqual(2, graph.summary()["device_count"])
        self.assertEqual("multihop", snapshot.metadata["discovery_mode"])
        self.assertEqual(1, snapshot.metadata["max_depth"])
        self.assertEqual(10, snapshot.metadata["max_devices"])

    def test_snapshots_are_deterministic(self) -> None:
        _, _, first = run_multihop_discovery(
            linear_chain().transport_factory, "10.0.0.1"
        )
        _, _, second = run_multihop_discovery(
            linear_chain().transport_factory, "10.0.0.1"
        )
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.to_dict(), second.to_dict())


class MultiHopCliTests(unittest.TestCase):
    def run_cli(self, network: ScriptedNetwork, answers: tuple[str, ...]):
        replies = iter(answers)
        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as workdir:
            root = Path(workdir)
            with (
                patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
                patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = main(
                    ["atlas", "discover"],
                    atlas_transport_factory=lambda credentials: network.transport_factory(
                        credentials.host
                    ),
                    atlas_input_reader=lambda prompt: next(replies),
                    atlas_password_reader=lambda prompt: PASSWORD,
                    atlas_topology_output=root / "atlas_topology.html",
                    atlas_snapshot_output=root / "topology_snapshot.json",
                    atlas_morning_brief_output=root / "morning_brief.md",
                    atlas_browser_opener=opened.append,
                )
            artifacts = {
                name: (root / name).read_text(encoding="utf-8")
                if (root / name).exists()
                else None
                for name in (
                    "atlas_topology.html",
                    "topology_snapshot.json",
                    "morning_brief.md",
                )
            }
        return code, stdout.getvalue(), stderr.getvalue(), opened, artifacts

    def test_multihop_cli_generates_all_artifacts(self) -> None:
        code, output, error, opened, artifacts = self.run_cli(
            linear_chain(), ("10.0.0.1", "atlas", "", "")
        )
        self.assertEqual(0, code, error)
        self.assertEqual("", error)
        self.assertIn("Discovery Progress", output)
        self.assertIn("Seed: 10.0.0.1 | Max depth: 1 | Max devices: 10", output)
        self.assertIn("[connected] r1 (10.0.0.1) - seed", output)
        self.assertIn("[connected] r2 (10.0.0.2) - cdp neighbor of r1", output)
        self.assertIn("Connected: 2 | Skipped: 0 | Failed: 0", output)
        self.assertIn("Live discovery completed successfully.", output)
        self.assertEqual(1, len(opened))
        snapshot = json.loads(artifacts["topology_snapshot.json"] or "{}")
        self.assertEqual(2, snapshot["device_count"])
        self.assertEqual(
            ["r1", "r2"], [d["hostname"] for d in snapshot["devices"]]
        )
        self.assertIn("r2", artifacts["atlas_topology.html"] or "")
        self.assertIn("## Network Status", artifacts["morning_brief.md"] or "")
        self.assertNotIn(PASSWORD, output)

    def test_cli_honors_custom_depth_and_device_limits(self) -> None:
        code, output, error, _, artifacts = self.run_cli(
            linear_chain(), ("10.0.0.1", "atlas", "2", "5")
        )
        self.assertEqual(0, code, error)
        self.assertIn("Seed: 10.0.0.1 | Max depth: 2 | Max devices: 5", output)
        self.assertIn("[connected] r3 (10.0.0.3) - cdp neighbor of r2", output)
        snapshot = json.loads(artifacts["topology_snapshot.json"] or "{}")
        self.assertEqual(3, snapshot["device_count"])

    def test_cli_reports_failed_neighbors_without_aborting(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("r1", "10.0.0.1", (("r2", "10.0.0.2"),)),
            },
            unreachable=frozenset({"10.0.0.2"}),
        )
        code, output, error, _, artifacts = self.run_cli(
            network, ("10.0.0.1", "atlas", "", "")
        )
        self.assertEqual(0, code, error)
        self.assertIn("[failed] 10.0.0.2 - ", output)
        self.assertIn("Failed: 1", output)
        snapshot = json.loads(artifacts["topology_snapshot.json"] or "{}")
        self.assertEqual(1, snapshot["device_count"])

    def test_invalid_limit_input_is_rejected_cleanly(self) -> None:
        code, output, error, opened, artifacts = self.run_cli(
            linear_chain(), ("10.0.0.1", "atlas", "abc", "")
        )
        self.assertEqual(1, code)
        self.assertEqual("", output)
        self.assertIn("Max depth must be a whole number", error)
        self.assertEqual([], opened)
        self.assertIsNone(artifacts["topology_snapshot.json"])

    def test_cli_output_is_deterministic(self) -> None:
        import re

        runs = []
        for _ in range(2):
            code, output, error, _, artifacts = self.run_cli(
                linear_chain(), ("10.0.0.1", "atlas", "", "")
            )
            self.assertEqual(0, code, error)
            runs.append((re.sub(r"saved: \S+", "saved: <path>", output), artifacts))
        self.assertEqual(runs[0], runs[1])


if __name__ == "__main__":
    unittest.main()
