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
        # PR-048 added the two AtlasLab platforms. They are registered last so
        # a lab platform could never shadow a production one, and they answer
        # the same probe — detection still costs exactly one command.
        self.assertEqual(
            (
                # PR-049: IOS-XE before legacy IOS -- both matchers accept an
                # XE probe, so order decides which plan an XE device gets.
                "Cisco IOS-XE",
                "Cisco IOS / IOS-XE",
                "Cisco NX-OS",
                "Arista EOS",
                "Juniper Junos",
                "Fortinet FortiOS",
                "Palo Alto PAN-OS",
                "Aruba CX",
                "Cisco Wireless LAN Controller",
                "F5 BIG-IP",
                "Citrix ADC",
                "A10 ACOS",
                "FRRouting",
                "AtlasLab firewall",
                "AtlasLab switch",
            ),
            registry.supported_platforms(),
        )
        self.assertEqual(
            (
                "show version", "get system status", "show system info",
                "show sysinfo", "show sys version", "show ns version",
            ),
            registry.probe_commands(),
        )

    def test_unsupported_platform_message_explains_why(self) -> None:
        message = default_registry().unsupported_message("JUNOS 21.4R1.12")
        self.assertIn("Unsupported platform detected", message)
        self.assertIn("Platform detected: Unknown", message)
        self.assertIn("Cisco IOS / IOS-XE", message)
        self.assertIn("FRRouting", message)
        # PR-049 made NX-OS/EOS/Junos real drivers; the honest future
        # roadmap is now Wave 2.
        self.assertIn("PAN-OS", message)
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

    def test_ospf_neighbors_become_routing_adjacencies(self) -> None:
        """PR-043.1: router IDs and peer addresses are OBSERVATIONS —
        never management endpoints."""

        neighbors = FRRoutingAdapter().parse_neighbors(self.outputs())
        self.assertEqual(1, len(neighbors))
        neighbor = neighbors[0]
        self.assertEqual("ospf", neighbor.protocol)
        self.assertIsNone(neighbor.remote_management_ip)  # never an endpoint
        self.assertEqual("eth1", neighbor.local_interface)
        self.assertEqual("10.99.0.2", neighbor.remote_hostname)
        self.assertEqual(
            "routing-adjacency", neighbor.metadata["observation"]
        )
        self.assertEqual("10.99.0.2", neighbor.metadata["router_id"])
        self.assertEqual(
            "10.99.0.2", neighbor.metadata["adjacency_address"]
        )
        self.assertIs(False, neighbor.metadata["management_endpoint"])

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
        # The count summary is kept, but the full RIB now rides alongside it:
        # every route with its prefix, next-hop, and interface.
        table = discovery.result.device.metadata["routing_table"]
        self.assertEqual(3, len(table))
        ospf = next(r for r in table if r["protocol"] == "ospf")
        self.assertEqual(
            ("10.0.0.0/24", "10.99.0.2", "eth1"),
            (ospf["prefix"], ospf["next_hop"], ospf["interface"]),
        )
        connected = next(r for r in table if r["prefix"] == "10.20.0.0/24")
        self.assertEqual((None, "eth0", True),
                         (connected["next_hop"], connected["interface"],
                          connected["connected"]))
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

    def test_ios_driver_captures_the_routing_table(self) -> None:
        from tests.test_multihop_discovery import interface_brief

        transport = StubTransport(
            {
                "show version": show_version("R1"),
                "show ip interface brief": interface_brief("10.0.0.1"),
                "show cdp neighbors detail": "",
                "show ip route": (
                    "C        10.0.0.0/24 is directly connected, "
                    "GigabitEthernet0/0\n"
                    "O        10.2.2.0/24 [110/20] via 10.0.0.2, 00:05:12, "
                    "GigabitEthernet0/1\n"
                    "S*       0.0.0.0/0 [1/0] via 10.0.0.254\n"
                ),
            }
        )
        discovery = CiscoIOSDriver().discover(
            transport, management_ip_hint="10.0.0.1"
        )
        self.assertEqual(CAP_COLLECTED, discovery.capability("routes").state)
        table = discovery.result.device.metadata["routing_table"]
        self.assertEqual(3, len(table))
        ospf = next(r for r in table if r["protocol"] == "ospf")
        self.assertEqual("10.2.2.0/24", ospf["prefix"])
        self.assertEqual("10.0.0.2", ospf["next_hop"])
        self.assertEqual("GigabitEthernet0/1", ospf["interface"])
        default = next(r for r in table if r["prefix"] == "0.0.0.0/0")
        self.assertEqual(("static", "10.0.0.254"),
                         (default["protocol"], default["next_hop"]))

    def test_ios_driver_captures_policy_routing(self) -> None:
        """Policy routes decide a flow BEFORE the table does, so a
        forwarding verdict blind to them can be confidently wrong."""

        from tests.test_multihop_discovery import interface_brief

        transport = StubTransport(
            {
                "show version": show_version("R1"),
                "show ip interface brief": interface_brief("10.0.0.1"),
                "show cdp neighbors detail": "",
                "show ip route": "C  10.0.0.0/24 is directly connected, Gi0/0\n",
                "show ip policy": (
                    "Interface      Route map\n"
                    "GigabitEthernet0/1 PBR-BRANCH\n"
                ),
                "show route-map": (
                    "route-map PBR-BRANCH, permit, sequence 10\n"
                    "  Match clauses:\n"
                    "  Set clauses:\n"
                    "    ip next-hop 192.0.2.5\n"
                    "  Policy routing matches: 0 packets, 0 bytes\n"
                ),
            }
        )
        discovery = CiscoIOSDriver().discover(
            transport, management_ip_hint="10.0.0.1"
        )
        metadata = discovery.result.device.metadata
        self.assertTrue(metadata["policy_routes_captured"])
        policies = metadata["policy_routes"]
        self.assertEqual(1, len(policies))
        self.assertEqual("GigabitEthernet0/1", policies[0]["ingress_interface"])
        self.assertEqual("192.0.2.5", policies[0]["next_hop"])

    def test_a_device_with_no_policy_routing_says_so(self) -> None:
        """"Asked, and this device policy-routes nothing" is a FACT the
        engine needs. It must not look like "never asked", which is the
        key being absent — silence and evidence of absence are different
        answers and the engine treats them differently."""

        from tests.test_multihop_discovery import interface_brief

        transport = StubTransport(
            {
                "show version": show_version("R1"),
                "show ip interface brief": interface_brief("10.0.0.1"),
                "show cdp neighbors detail": "",
                "show ip policy": "",
                "show route-map": "",
            }
        )
        discovery = CiscoIOSDriver().discover(
            transport, management_ip_hint="10.0.0.1"
        )
        metadata = discovery.result.device.metadata
        self.assertTrue(metadata["policy_routes_captured"])
        self.assertEqual((), tuple(metadata["policy_routes"]))

    def test_policy_capture_never_implies_routes_were_collected(self) -> None:
        """A device that answered the policy commands but not `show ip
        route` has collected NO routes. Reporting "0 route(s)" collected
        would say it had."""

        from tests.test_multihop_discovery import interface_brief

        transport = StubTransport(
            {
                "show version": show_version("R1"),
                "show ip interface brief": interface_brief("10.0.0.1"),
                "show cdp neighbors detail": "",
                "show ip policy": "",
            }
        )
        discovery = CiscoIOSDriver().discover(
            transport, management_ip_hint="10.0.0.1"
        )
        self.assertNotEqual(
            CAP_COLLECTED, discovery.capability("routes").state
        )
        self.assertNotIn("routing_table", discovery.result.device.metadata)

    def test_ios_driver_states_routes_uncollected_when_absent(self) -> None:
        """Honesty: no `show ip route` output means routes are marked
        not-collected, never an empty table implied to be complete."""

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
        # Not collected (the collection plan's own status stands); crucially
        # NO routing_table is invented.
        self.assertNotEqual(
            CAP_COLLECTED, discovery.capability("routes").state
        )
        self.assertNotIn(
            "routing_table", discovery.result.device.metadata
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

    def test_ospf_adjacencies_are_observed_never_traversed(self) -> None:
        """PR-043.1: a routing adjacency is preserved as an unresolved
        observation — Atlas never SSHes a router ID, and the peer is
        never falsely reported unreachable."""

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
        self.assertEqual(["delhi-r1"], hostnames)  # peer NOT discovered
        self.assertEqual((), report.failed)        # and NOT "unreachable"
        skipped = [visit for visit in report.skipped]
        self.assertEqual(1, len(skipped))
        self.assertEqual("10.99.0.2", skipped[0].host)
        self.assertIn("not attempted", skipped[0].detail)
        self.assertIn("OSPF", skipped[0].detail)
        self.assertIn("not a verified management endpoint", skipped[0].detail)
        # No SSH was ever attempted to the router ID.
        self.assertNotIn("10.99.0.2", network.connect_attempts)

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
        # delhi-r2 is reachable only through routing evidence, so the
        # engineer supplies it as an explicit seed — user-provided seeds
        # remain eligible (PR-043.1); router IDs alone never are.
        add_profile(service, "Delhi", "10.20.0.1", seeds=("10.99.0.2",))
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
            self.assertIn(b"data-picker", predict)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=all"
                ).get_json()["results"]
            }
            self.assertIn("delhi-r1", names)
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


class ManagementEligibilityTests(unittest.TestCase):
    """PR-043.1: recursive SSH only with management-endpoint evidence."""

    def neighbor(self, protocol: str, metadata: dict | None = None):
        from founderos_atlas.discovery.models import NetworkNeighbor

        return NetworkNeighbor(
            local_device_id="frr:x",
            local_interface="eth0",
            remote_hostname="peer",
            remote_management_ip="10.9.9.9",
            protocol=protocol,
            metadata=metadata or {},
        )

    def test_routing_evidence_never_qualifies(self) -> None:
        from founderos_atlas.discovery.multihop import management_candidate

        for protocol in ("ospf", "bgp", "isis"):
            self.assertFalse(
                management_candidate(self.neighbor(protocol)), protocol
            )
        self.assertFalse(
            management_candidate(
                self.neighbor("ospf", {"management_endpoint": False})
            )
        )

    def test_link_layer_and_operator_evidence_qualifies(self) -> None:
        from founderos_atlas.discovery.multihop import management_candidate

        for protocol in ("cdp", "lldp", "manual"):
            self.assertTrue(
                management_candidate(self.neighbor(protocol)), protocol
            )
        # An LLDP management address is a candidate endpoint (spec #4).
        self.assertTrue(
            management_candidate(
                self.neighbor("lldp", {"management_endpoint": True})
            )
        )

    def test_previously_verified_endpoint_remains_eligible(self) -> None:
        from founderos_atlas.discovery.multihop import management_candidate

        # Even over a routing protocol, an EXPLICIT verified-endpoint
        # marker (e.g. a previously verified canonical endpoint) wins.
        self.assertTrue(
            management_candidate(
                self.neighbor("ospf", {"management_endpoint": True})
            )
        )

    def test_route_next_hops_never_become_devices(self) -> None:
        """Routes are metadata evidence — never nodes, never seeds."""

        _report, _graph, snapshot = run_multihop_discovery(
            ScriptedNetwork(
                {"10.20.0.1": frr_outputs("delhi-r1", "10.20.0.1")}
            ).transport_factory,
            "10.20.0.1",
        )
        data = snapshot.to_dict()
        self.assertEqual(1, data["device_count"])  # next hops not devices
        self.assertEqual(
            3, data["devices"][0]["metadata"]["routes"]["total"]
        )

    def test_unresolved_peer_not_counted_and_not_unreachable(self) -> None:
        report, _graph, snapshot = run_multihop_discovery(
            ScriptedNetwork(
                {
                    "10.20.0.1": frr_outputs(
                        "delhi-r1", "10.20.0.1",
                        ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
                    ),
                }
            ).transport_factory,
            "10.20.0.1",
            config=MultiHopConfig(max_depth=1),
        )
        data = snapshot.to_dict()
        self.assertEqual(1, data["device_count"])  # the peer is NOT a device
        self.assertEqual((), report.failed)        # and NOT "unreachable"
        self.assertNotIn("failed_hosts", data["metadata"])
        relations = data["metadata"]["relationships"]
        self.assertEqual(0, relations["physical_links"])
        self.assertEqual(1, relations["routing_adjacencies"])
        self.assertEqual(1, relations["unresolved_peers"])


class RoleClassificationTests(unittest.TestCase):
    def test_roles_come_from_evidence(self) -> None:
        from founderos_atlas.platforms import classify_role

        cases = (
            ({"platform": "FRRouting", "vendor": "frrouting"},
             "router", "FRRouting"),
            ({"platform": "WS-C2960X-48FPS-L"}, "layer2_switch", "switch"),
            ({"platform": "WS-C3850", "interfaces": [
                {"name": "Vlan10", "ip_address": "10.0.0.1"}]},
             "layer3_switch", "routed SVI"),
            ({"platform": "IOSv", "interfaces": [{"name": "Vlan1"}]},
             "layer2_switch", "VLAN interface"),
            ({"platform": "ASA5516"}, "firewall", "firewall"),
            ({"platform": "IOSv"}, "router", "router platform"),
            ({"platform": "unknown-thing"}, "unknown", "no role evidence"),
            ({"platform": "IOSv", "metadata": {"role": "load_balancer"}},
             "load_balancer", "override"),
        )
        for device, expected_role, evidence_bit in cases:
            role, evidence = classify_role(device)
            self.assertEqual(expected_role, role, device)
            self.assertIn(evidence_bit.casefold(), evidence.casefold(), device)

    def test_role_is_never_inferred_from_hostname(self) -> None:
        from founderos_atlas.platforms import classify_role

        role, evidence = classify_role(
            {"hostname": "SW1", "platform": "mystery"}
        )
        self.assertEqual("unknown", role)  # "SW1" proves nothing
        self.assertIn("no role evidence", evidence)


class StencilAndPresentationTests(unittest.TestCase):
    def viewer(self, snapshot):
        from founderos_atlas.visualization import TopologyRenderer

        return TopologyRenderer(snapshot)

    def frr_snapshot(self):
        _report, _graph, snapshot = run_multihop_discovery(
            ScriptedNetwork(
                {
                    "10.20.0.1": frr_outputs(
                        "delhi-r1", "10.20.0.1",
                        ospf_neighbors=(("10.99.0.2", "10.99.0.2", "eth1"),),
                    ),
                }
            ).transport_factory,
            "10.20.0.1",
            config=MultiHopConfig(max_depth=1),
        )
        return snapshot

    def test_stencils_are_distinct_reusable_svgs(self) -> None:
        from founderos_atlas.platforms import DEVICE_ROLES
        from founderos_atlas.visualization.stencils import (
            stencil_data_uri, stencil_svg,
        )

        seen = set()
        for role in DEVICE_ROLES:
            svg = stencil_svg(role)
            self.assertIn("<svg", svg)
            self.assertNotIn(svg, seen, role)  # visually distinct markup
            seen.add(svg)
            self.assertTrue(
                stencil_data_uri(role).startswith("data:image/svg+xml")
            )
        # The unresolved-peer stencil is dashed; the fallback is unknown.
        self.assertIn("stroke-dasharray", stencil_svg("unresolved_peer"))
        self.assertEqual(stencil_svg("unknown"), stencil_svg("nonsense-role"))

    def test_stencils_share_thin_outline_rendering_contract(self) -> None:
        from xml.etree import ElementTree

        from founderos_atlas.platforms import DEVICE_ROLES
        from founderos_atlas.visualization.stencils import STENCILS, stencil_svg

        expected_roles = set(DEVICE_ROLES) | {
            "site", "site-wan", "site-internet", "site-cloud",
            # Site-type refinements: premises kinds share the premises
            # glyph, transit shares WAN, unclassified/custom render with
            # full site quality (see sites/models.py SITE_TYPES).
            "site-branch", "site-campus", "site-datacenter", "site-transit",
            "site-unclassified", "site-custom",
        }
        self.assertEqual(expected_roles, set(STENCILS))
        # Ordinary sites are overview clouds now; their names are overlaid in
        # the cloud body by Cytoscape rather than floating above a building.
        self.assertIn('A16 16', stencil_svg("site"))
        self.assertNotIn('<rect', stencil_svg("site"))

        forbidden_tags = {"filter", "image", "linearGradient", "radialGradient"}
        for role in sorted(expected_roles):
            svg = stencil_svg(role)
            root = ElementTree.fromstring(svg)
            self.assertEqual("512", root.attrib.get("width"), role)
            self.assertEqual("512", root.attrib.get("height"), role)
            self.assertEqual("0 0 64 64", root.attrib.get("viewBox"), role)
            self.assertEqual(
                "geometricPrecision", root.attrib.get("shape-rendering"), role
            )

            stroke_widths: list[float] = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                self.assertNotIn(tag, forbidden_tags, role)
                self.assertNotIn("filter", element.attrib, role)
                # The old grounding ellipse used element opacity; restrained
                # tint fills use the explicit fill-opacity channel instead.
                self.assertNotIn("opacity", element.attrib, role)
                if "stroke-width" in element.attrib:
                    stroke_widths.append(float(element.attrib["stroke-width"]))

            self.assertTrue(stroke_widths, role)
            self.assertTrue(
                all(width in {1.25, 1.5} for width in stroke_widths),
                f"{role}: {stroke_widths}",
            )

    def test_router_and_unresolved_nodes_get_their_stencils(self) -> None:
        elements = self.viewer(self.frr_snapshot()).elements()
        by_kind = {}
        for node in elements["nodes"]:
            by_kind.setdefault(node["data"].get("kind"), []).append(node["data"])
        router = by_kind["discovered"][0]
        self.assertEqual("router", router["role"])
        self.assertIn("FRRouting", router["role_evidence"])
        self.assertIn("data:image/svg+xml", router["stencil"])
        peer = by_kind["observed"][0]
        self.assertEqual("unresolved_peer", peer["role"])
        self.assertEqual("10.99.0.2", peer["router_id"])
        self.assertEqual("OSPF", peer["observed_via"])
        self.assertEqual("Unknown", peer["management_ip"])
        self.assertIn("Not attempted", peer["discovery_status"])

    def test_relationship_types_stay_distinct_in_the_viewer(self) -> None:
        renderer = self.viewer(self.frr_snapshot())
        edges = renderer.elements()["edges"]
        self.assertEqual(
            {"routing-adjacency"},
            {edge["data"]["relationship"] for edge in edges},
        )
        summary = renderer.relationship_summary()
        self.assertEqual(0, summary["physical_links"])
        self.assertEqual(1, summary["routing_adjacencies"])
        self.assertEqual(1, summary["unresolved_peers"])
        html = renderer.render()
        # Line styles per relationship; health borders separate from role.
        self.assertIn('edge[relationship = "routing-adjacency"]', html)
        self.assertIn("'line-style': 'dashed'", html)
        self.assertIn('edge[relationship = "protocol-peer"]', html)
        self.assertIn("'line-style': 'dotted'", html)
        self.assertIn('node[change = "removed"]', html)
        self.assertIn("background-image", html)
        self.assertIn(
            "This peer was observed through routing evidence.", html
        )

    def test_ios_lab_gets_solid_physical_links(self) -> None:
        from tests.test_multihop_discovery import linear_chain

        _report, _graph, snapshot = run_multihop_discovery(
            linear_chain().transport_factory, "10.0.0.1",
            config=MultiHopConfig(max_depth=2),
        )
        renderer = self.viewer(snapshot)
        summary = renderer.relationship_summary()
        self.assertGreater(summary["physical_links"], 0)
        self.assertEqual(0, summary["routing_adjacencies"])
        self.assertEqual(0, summary["unresolved_peers"])
        for edge in renderer.elements()["edges"]:
            self.assertEqual("physical", edge["data"]["relationship"])

    def test_serialization_stays_deterministic(self) -> None:
        first = self.viewer(self.frr_snapshot()).elements()
        second = self.viewer(self.frr_snapshot()).elements()
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


if __name__ == "__main__":
    unittest.main()
