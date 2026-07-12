"""Acceptance tests for PR-043 — the Multi-Platform Discovery Framework.

Atlas discovers platforms and reasons about enterprises — never vendors.
These tests cover the driver framework itself (detection, registry,
capability honesty), the FRRouting driver (the second platform after
IOS), mixed-platform traversal, unknown-platform handling, and the full
pipeline with an FRR lab flowing into the unchanged downstream engines.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.discovery.multihop import MultiHopConfig, discover_multihop
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.platforms import (
    CAP_COLLECTED,
    CAP_NOT_COLLECTED,
    CAP_NOT_CONFIGURED,
    CAP_UNAVAILABLE,
    CiscoIOSDriver,
    FRRoutingAdapter,
    FRRoutingDriver,
    PlatformDriver,
    PlatformRegistry,
    UnsupportedPlatformError,
    default_registry,
)

from tests.test_multihop_discovery import (
    ScriptedNetwork,
    device_outputs,
    show_version,
)
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    make_service,
    run_discover,
    scope_dir,
)
from tests.test_unified_pipeline import full_outputs


# -- FRRouting vtysh fixtures ---------------------------------------------------

def frr_version(hostname: str) -> str:
    return (
        f"FRRouting 8.4.2 ({hostname}) on Linux(5.15.0-91-generic).\n"
        "Copyright 1996-2005 Kunihiro Ishiguro, et al.\n"
        "configured with:\n    '--localstatedir=/var/run/frr'\n"
    )


def frr_interfaces(ip: str, peer_ip_prefix: str = "10.99.0") -> str:
    return (
        "Interface eth0 is up, line protocol is up\n"
        "  Link ups:       1    last: 2026/07/10 08:00:00.00\n"
        "  vrf: default\n"
        "  index 2 metric 0 mtu 1500 speed 1000\n"
        "  flags: <UP,BROADCAST,RUNNING,MULTICAST>\n"
        "  Type: Ethernet\n"
        f"  inet {ip}/24\n"
        "Interface eth1 is up, line protocol is up\n"
        "  vrf: default\n"
        "  index 3 metric 0 mtu 1500 speed 1000\n"
        f"  inet {peer_ip_prefix}.1/24\n"
        "Interface lo is up, line protocol is up\n"
        "  vrf: default\n"
        "  index 1 metric 0 mtu 65536\n"
    )


def frr_ospf_neighbors(neighbors: tuple[tuple[str, str, str], ...]) -> str:
    header = (
        "Neighbor ID     Pri State           Up Time         Dead Time "
        "Address         Interface                        RXmtL RqstL DBsmL\n"
    )
    rows = "".join(
        f"{neighbor_id:<15} 1   Full/DR         1h02m03s        31.568s   "
        f"{address:<15} {interface}:10.99.0.1                0     0     0\n"
        for neighbor_id, address, interface in neighbors
    )
    return header + rows


FRR_ROUTES = (
    "Codes: K - kernel route, C - connected, S - static, O - OSPF,\n"
    "       B - BGP, > - selected route, * - FIB route\n"
    "\n"
    "C>* 10.20.0.0/24 is directly connected, eth0, 01:02:03\n"
    "C>* 10.99.0.0/24 is directly connected, eth1, 01:02:03\n"
    "O>* 10.0.0.0/24 [110/20] via 10.99.0.2, eth1, weight 1, 00:12:34\n"
)

FRR_BGP_MISSING = "% BGP instance not found\n"
FRR_LLDP_UNKNOWN = '% Unknown command: show lldp neighbors\n'


def frr_outputs(
    hostname: str,
    ip: str,
    ospf_neighbors: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, str]:
    return {
        "show version": frr_version(hostname),
        "show interface": frr_interfaces(ip),
        "show ip ospf neighbor": (
            frr_ospf_neighbors(ospf_neighbors)
            if ospf_neighbors
            else "% OSPF instance not found\n"
        ),
        "show ip route": FRR_ROUTES,
        "show bgp summary": FRR_BGP_MISSING,
        "show lldp neighbors": FRR_LLDP_UNKNOWN,
        "show running-config": f"frr version 8.4.2\nhostname {hostname}\n!\nend\n",
    }


class StubTransport:
    """The minimal open-transport surface a driver consumes."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def execute(self, command: str) -> str:
        self.commands.append(command)
        return self.outputs[command]


class DetectionAndRegistryTests(unittest.TestCase):
    def test_probe_output_identifies_each_platform(self) -> None:
        registry = default_registry()
        ios = registry.detect(show_version("R1"))
        self.assertIsInstance(ios, CiscoIOSDriver)
        frr = registry.detect(frr_version("delhi-r1"))
        self.assertIsInstance(frr, FRRoutingDriver)
        self.assertIsNone(registry.detect("JUNOS 21.4R1.12 built ..."))
        self.assertIsNone(registry.detect(""))

    def test_detection_order_is_registration_order(self) -> None:
        registry = default_registry()
        self.assertEqual(
            ("Cisco IOS / IOS-XE", "FRRouting"), registry.supported_platforms()
        )
        self.assertEqual(("show version",), registry.probe_commands())

    def test_unsupported_platform_message_explains_why(self) -> None:
        message = default_registry().unsupported_message("JUNOS 21.4R1.12")
        self.assertIn("Unsupported platform detected", message)
        self.assertIn("Platform detected: Unknown", message)
        self.assertIn("Cisco IOS / IOS-XE", message)
        self.assertIn("FRRouting", message)
        self.assertIn("Junos", message)  # the honest future roadmap
        self.assertIn("JUNOS 21.4R1.12", message)  # WHY: what the probe said

    def test_registry_is_extensible_without_touching_discovery(self) -> None:
        class JunosProbeOnlyDriver(FRRoutingDriver):
            platform_id = "junos"
            display_name = "Junos (test stub)"
            vendor = "juniper"

            @classmethod
            def matches(cls, probe_output: str) -> bool:
                return "JUNOS" in probe_output

        registry = default_registry()
        registry.register(JunosProbeOnlyDriver)
        detected = registry.detect("JUNOS 21.4R1.12")
        self.assertIsInstance(detected, JunosProbeOnlyDriver)
        self.assertIn("Junos (test stub)", registry.supported_platforms())

    def test_registry_rejects_non_drivers(self) -> None:
        with self.assertRaises(TypeError):
            PlatformRegistry().register(object)  # type: ignore[arg-type]


class FRRoutingAdapterTests(unittest.TestCase):
    def outputs(self) -> dict[str, str]:
        return frr_outputs(
            "delhi-r1", "10.20.0.1",
            ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
        )

    def test_inventory_normalizes_into_the_canonical_device(self) -> None:
        device = FRRoutingAdapter().parse_inventory(self.outputs())
        self.assertEqual("frr:delhi-r1", device.device_id)
        self.assertEqual("delhi-r1", device.hostname)
        self.assertEqual("10.20.0.1", device.management_ip)
        self.assertEqual("frrouting", device.vendor)
        self.assertEqual("FRRouting", device.platform)
        self.assertEqual("8.4.2", device.os_version)
        self.assertIsNone(device.serial_number)  # honest: no chassis serial

    def test_interfaces_parse_names_state_and_addresses(self) -> None:
        interfaces = FRRoutingAdapter().parse_interfaces(self.outputs())
        by_name = {item.name: item for item in interfaces}
        self.assertEqual({"eth0", "eth1", "lo"}, set(by_name))
        self.assertEqual("10.20.0.1", by_name["eth0"].ip_address)
        self.assertEqual("up", by_name["eth0"].status)
        self.assertEqual("up", by_name["eth0"].protocol_status)
        self.assertIsNone(by_name["lo"].ip_address)

    def test_ospf_neighbors_become_canonical_neighbors(self) -> None:
        neighbors = FRRoutingAdapter().parse_neighbors(self.outputs())
        self.assertEqual(1, len(neighbors))
        neighbor = neighbors[0]
        self.assertEqual("ospf", neighbor.protocol)
        self.assertEqual("10.99.0.2", neighbor.remote_management_ip)
        self.assertEqual("eth1", neighbor.local_interface)
        self.assertEqual("10.99.0.2", neighbor.remote_hostname)

    def test_missing_ospf_is_empty_not_an_error(self) -> None:
        outputs = self.outputs()
        outputs["show ip ospf neighbor"] = "% OSPF instance not found\n"
        self.assertEqual((), FRRoutingAdapter().parse_neighbors(outputs))

    def test_management_ip_falls_back_to_the_connection_address(self) -> None:
        outputs = self.outputs()
        outputs["show interface"] = "Interface lo is up, line protocol is up\n"
        device = FRRoutingAdapter().parse_inventory(
            outputs, management_ip_hint="10.20.0.9"
        )
        self.assertEqual("10.20.0.9", device.management_ip)
        self.assertIn(
            "connection address", " ".join(device.metadata["parse_warnings"])
        )


class FRRoutingDriverTests(unittest.TestCase):
    def test_capabilities_are_recorded_never_raised(self) -> None:
        transport = StubTransport(
            frr_outputs(
                "delhi-r1", "10.20.0.1",
                ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
            )
        )
        discovery = FRRoutingDriver().discover(
            transport, management_ip_hint="10.20.0.1"
        )
        states = {
            status.name: status.state for status in discovery.capabilities
        }
        self.assertEqual(CAP_COLLECTED, states["identity"])
        self.assertEqual(CAP_COLLECTED, states["interfaces"])
        self.assertEqual(CAP_COLLECTED, states["ospf-neighbors"])
        self.assertEqual(CAP_COLLECTED, states["routes"])
        self.assertEqual(CAP_NOT_CONFIGURED, states["bgp"])
        self.assertEqual(CAP_UNAVAILABLE, states["lldp-neighbors"])
        # Discovery SUCCEEDED despite two missing capabilities.
        self.assertEqual("delhi-r1", discovery.result.device.hostname)

    def test_route_evidence_lands_in_canonical_metadata(self) -> None:
        transport = StubTransport(frr_outputs("delhi-r1", "10.20.0.1"))
        discovery = FRRoutingDriver().discover(
            transport, management_ip_hint="10.20.0.1"
        )
        routes = discovery.result.device.metadata["routes"]
        self.assertEqual(3, routes["total"])
        self.assertEqual({"connected": 2, "ospf": 1}, routes["by_protocol"])
        stamp = discovery.result.device.metadata["platform_driver"]
        self.assertEqual("frr", stamp["platform_id"])
        self.assertEqual("FRRoutingDriver", stamp["driver"])
        self.assertEqual("collected", stamp["capabilities"]["routes"])

    def test_command_failures_degrade_to_unavailable(self) -> None:
        outputs = frr_outputs("delhi-r1", "10.20.0.1")
        del outputs["show ip route"]  # transport raises KeyError
        discovery = FRRoutingDriver().discover(
            StubTransport(outputs), management_ip_hint="10.20.0.1"
        )
        self.assertEqual(
            CAP_UNAVAILABLE, discovery.capability("routes").state
        )
        self.assertEqual("delhi-r1", discovery.result.device.hostname)

    def test_probe_output_is_reused_never_re_executed(self) -> None:
        outputs = frr_outputs("delhi-r1", "10.20.0.1")
        transport = StubTransport(outputs)
        FRRoutingDriver().discover(
            transport,
            management_ip_hint="10.20.0.1",
            probe_output=outputs["show version"],
        )
        self.assertNotIn("show version", transport.commands)

    def test_ios_driver_marks_routes_not_collected(self) -> None:
        from tests.test_multihop_discovery import interface_brief

        transport = StubTransport(
            {
                "show version": show_version("R1"),
                "show ip interface brief": interface_brief("10.0.0.1"),
                "show cdp neighbors detail": "",
            }
        )
        discovery = CiscoIOSDriver().discover(
            transport, management_ip_hint="10.0.0.1"
        )
        self.assertEqual(
            CAP_NOT_COLLECTED, discovery.capability("routes").state
        )
        self.assertEqual(
            "cisco-ios",
            discovery.result.device.metadata["platform_driver"]["platform_id"],
        )


def mixed_network() -> ScriptedNetwork:
    """R1 (Cisco IOS) ↔ delhi-r1 (FRRouting) — one enterprise, two platforms.

    R1 announces delhi-r1 over CDP; delhi-r1 sees R1 as an OSPF neighbor.
    """

    return ScriptedNetwork(
        {
            "10.0.0.1": device_outputs(
                "R1", "10.0.0.1", (("delhi-r1", "10.20.0.1"),)
            ),
            "10.20.0.1": frr_outputs(
                "delhi-r1", "10.20.0.1",
                ospf_neighbors=(("10.0.0.1", "10.0.0.1", "eth0"),),
            ),
        }
    )


class MixedPlatformTraversalTests(unittest.TestCase):
    def test_detection_loads_the_right_driver_per_host(self) -> None:
        report = discover_multihop(
            "10.0.0.1",
            mixed_network().transport_factory,
            config=MultiHopConfig(max_depth=1),
        )
        by_hostname = {
            result.device.hostname: result for result in report.results
        }
        self.assertEqual({"R1", "delhi-r1"}, set(by_hostname))
        self.assertEqual("ios", by_hostname["R1"].platform_family)
        self.assertEqual("frr", by_hostname["delhi-r1"].platform_family)
        self.assertEqual(
            "cisco", by_hostname["R1"].device.vendor
        )
        self.assertEqual(
            "frrouting", by_hostname["delhi-r1"].device.vendor
        )

    def test_ospf_neighbors_traverse_like_cdp_neighbors(self) -> None:
        network = ScriptedNetwork(
            {
                "10.20.0.1": frr_outputs(
                    "delhi-r1", "10.20.0.1",
                    ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
                ),
                "10.99.0.2": frr_outputs("delhi-r2", "10.99.0.2"),
            }
        )
        report = discover_multihop(
            "10.20.0.1", network.transport_factory,
            config=MultiHopConfig(max_depth=1),
        )
        hostnames = [result.device.hostname for result in report.results]
        self.assertEqual(["delhi-r1", "delhi-r2"], hostnames)
        origins = [visit.detail for visit in report.connected]
        self.assertIn("ospf neighbor of delhi-r1", origins)

    def test_unknown_platform_fails_honestly_per_device(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "R1", "10.0.0.1", (("mystery", "10.0.0.9"),)
                ),
                "10.0.0.9": {"show version": "JUNOS 21.4R1.12 built ..."},
            }
        )
        report = discover_multihop(
            "10.0.0.1", network.transport_factory,
            config=MultiHopConfig(max_depth=1),
        )
        self.assertEqual(1, len(report.results))  # R1 still discovered
        failed = report.failed[0]
        self.assertEqual("10.0.0.9", failed.host)
        self.assertIn("Unsupported platform detected", failed.detail)
        self.assertIn("FRRouting", failed.detail)

    def test_unknown_platform_seed_raises_the_honest_message(self) -> None:
        network = ScriptedNetwork(
            {"10.0.0.9": {"show version": "JUNOS 21.4R1.12 built ..."}}
        )
        with self.assertRaises(UnsupportedPlatformError) as ctx:
            discover_multihop("10.0.0.9", network.transport_factory)
        self.assertIn("Supported drivers", str(ctx.exception))

    def test_pinned_adapter_path_is_unchanged(self) -> None:
        report = discover_multihop(
            "10.0.0.1",
            mixed_network().transport_factory,
            adapter=CiscoIOSAdapter(),
            config=MultiHopConfig(max_depth=0),
        )
        self.assertEqual(1, len(report.results))
        self.assertEqual("R1", report.results[0].device.hostname)

    def test_snapshot_records_the_platform_mix(self) -> None:
        _report, _graph, snapshot = run_multihop_discovery(
            mixed_network().transport_factory,
            "10.0.0.1",
            config=MultiHopConfig(max_depth=1),
        )
        self.assertEqual(
            {"frr": 1, "ios": 1}, dict(snapshot.metadata["platforms"])
        )
        hostnames = {
            str(device["hostname"]) for device in snapshot.devices
        }
        self.assertEqual({"R1", "delhi-r1"}, hostnames)

    def test_only_read_only_commands_reach_frr_devices(self) -> None:
        network = mixed_network()
        discover_multihop(
            "10.0.0.1", network.transport_factory,
            config=MultiHopConfig(max_depth=1),
        )
        for _, command in network.commands_sent():
            self.assertTrue(
                command == "terminal length 0" or command.startswith("show "),
                f"unexpected command sent: {command!r}",
            )


def delhi_network() -> ScriptedNetwork:
    """The Delhi FRRouting lab: delhi-r1 with an OSPF neighbor delhi-r2."""

    return ScriptedNetwork(
        {
            "10.20.0.1": frr_outputs(
                "delhi-r1", "10.20.0.1",
                ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
            ),
            "10.99.0.2": frr_outputs("delhi-r2", "10.99.0.2"),
        }
    )


class MultiPlatformPipelineTests(unittest.TestCase):
    """The CML scenario: two IOS labs + one FRR lab, downstream unchanged."""

    def build_world(self, workdir: Path):
        from founderos_atlas.web import create_app
        from tests.test_federation import hyderabad_network

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        add_profile(service, "Delhi", "10.20.0.1")
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        run_discover(
            workdir, service, delhi_network(), "Delhi",
            FIXED + timedelta(minutes=30),
        )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_frr_lab_flows_through_the_unchanged_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _service, client = self.build_world(workdir)
            snapshot = json.loads(
                (scope_dir(workdir, "delhi") / "topology_snapshot.json")
                .read_text("utf-8")
            )
            hostnames = {d["hostname"] for d in snapshot["devices"]}
            self.assertEqual({"delhi-r1", "delhi-r2"}, hostnames)
            self.assertEqual({"frr": 2}, dict(snapshot["metadata"]["platforms"]))
            delhi = next(
                d for d in snapshot["devices"] if d["hostname"] == "delhi-r1"
            )
            self.assertEqual("FRRouting", delhi["platform"])
            self.assertEqual(
                "frr", delhi["metadata"]["platform_driver"]["platform_id"]
            )

            # Enterprise Graph unchanged: both labs federate together.
            page = client.get("/topology?scope=all").data
            for hostname in (b"A1", b"GW", b"delhi-r1", b"delhi-r2"):
                self.assertIn(hostname, page)

            # Mission unchanged.
            mission = client.get("/?scope=all").data
            self.assertIn(b"Delhi", mission)
            self.assertIn(b"Enterprise Health", mission)

            # Prediction unchanged: FRR interfaces are canonical.
            predict = client.get("/predict?scope=all").data
            self.assertIn(b"delhi-r1", predict)
            response = client.post(
                "/predict/run",
                data={"device": "delhi-r1", "interface": "eth1"},
                follow_redirects=True,
            )
            self.assertIn(b"Risk:", response.data)

            # Search + Advisor unchanged: canonical models only.
            found = client.get("/api/search?q=delhi-r1").get_json()
            groups = {g["id"] for g in found["groups"]}
            self.assertIn("devices", groups)
            advisor = client.post(
                "/api/advisor/ask", json={"question": "Find delhi-r1"}
            ).get_json()
            self.assertIn("delhi-r1", advisor["summary"])

    def test_paths_walk_across_the_frr_lab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _service, client = self.build_world(workdir)
            client.get("/paths?scope=delhi")
            response = client.post(
                "/paths/run",
                data={"source": "delhi-r1", "destination": "delhi-r2"},
                follow_redirects=True,
            )
            self.assertIn(b"Connected", response.data)

    def test_discovery_page_shows_the_platform_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _service, client = self.build_world(workdir)
            page = client.get("/discovery").data
            self.assertIn(b"Platforms", page)


if __name__ == "__main__":
    unittest.main()
