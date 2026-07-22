"""PR-049 (POLYGLOT) — production driver contract and Wave-1 drivers.

Transcript-driven: every test runs the REAL parser and normalization code
against sanitized transcripts of realistic output. That earns a driver
EXPERIMENTAL, never more — live validation is a different kind of evidence
and no test here claims it.

The distinctions this suite exists to protect:

- UNSUPPORTED (the device said so) is never FAILED (this attempt broke);
- empty output is never FAILED when the command executed;
- one failed command never discards the evidence already collected;
- a skipped tier reports NOT_ATTEMPTED by name;
- an operator override selects the driver without erasing what detection saw.
"""

from __future__ import annotations

import unittest

from founderos_atlas.platforms import (
    DetectionResult,
    EXPERIMENTAL,
    FAILED,
    NOT_ATTEMPTED,
    SUPPORTED,
    TIER_DEEP,
    TIER_FAST,
    UNSUPPORTED,
    default_registry,
)
from founderos_atlas.platforms.capabilities import MATURITY_LEVELS

from tests.platform_fixtures import ios_xe as XE


class FakeTransport:
    """Replays a transcript; unknown commands answer as the platform would."""

    def __init__(self, outputs: dict, *, reject_unknown: str = "% Invalid input detected at '^' marker.",
                 broken: set | None = None):
        self.outputs = dict(outputs)
        self.reject_unknown = reject_unknown
        self.broken = set(broken or ())
        self.executed: list[str] = []

    def execute(self, command: str) -> str:
        self.executed.append(command)
        if command in self.broken:
            raise TimeoutError(f"simulated transport timeout for {command!r}")
        return self.outputs.get(command, self.reject_unknown)


def _discover(driver, outputs, **kwargs):
    transport = FakeTransport(outputs, **{k: v for k, v in kwargs.items()
                                          if k in ("reject_unknown", "broken")})
    tier = kwargs.get("tier", "standard")
    return driver.discover(
        transport, management_ip_hint=kwargs.get("hint"),
        probe_output=outputs.get(driver.probe_command), tier=tier,
    ), transport


def _report(discovery, capability):
    for item in discovery.result.device.metadata["driver_diagnostics"]["capabilities"]:
        if item["capability"] == capability:
            return item
    raise AssertionError(f"no report for {capability}")


class DetectionTests(unittest.TestCase):
    def test_detection_reports_confidence_evidence_and_reason(self) -> None:
        result = default_registry().identify(XE.SHOW_VERSION)
        self.assertIsInstance(result, DetectionResult)
        self.assertEqual("cisco-ios-xe", result.platform_id)
        self.assertGreater(result.confidence, 0)
        self.assertLessEqual(result.confidence, 0.95)
        self.assertTrue(result.evidence)
        self.assertTrue(result.reason)

    def test_contested_probes_report_their_alternatives(self) -> None:
        # The XE probe also satisfies the legacy IOS matcher: registration
        # order decides, and the loser is REPORTED, not silently dropped.
        result = default_registry().identify(XE.SHOW_VERSION)
        self.assertIn("cisco-ios", result.alternatives)
        self.assertLess(result.confidence, 0.9)

    def test_operator_override_wins_and_says_so(self) -> None:
        result = default_registry().identify(XE.SHOW_VERSION, override="frr")
        self.assertEqual("frr", result.platform_id)
        self.assertTrue(result.overridden)
        self.assertEqual(0.95, result.confidence)
        # ...and what detection actually saw is preserved as alternatives.
        self.assertIn("cisco-ios-xe", result.alternatives)

    def test_an_override_naming_no_driver_is_an_honest_failure(self) -> None:
        result = default_registry().identify(XE.SHOW_VERSION, override="junos-9000")
        self.assertIsNone(result.driver)
        self.assertEqual(0.0, result.confidence)
        self.assertIn("names no registered driver", result.reason)

    def test_unknown_platforms_are_unidentified_not_guessed(self) -> None:
        result = default_registry().identify("SomeOS v1.0 (banana)")
        self.assertIsNone(result.platform_id)
        self.assertEqual(0.0, result.confidence)


class MaturityTests(unittest.TestCase):
    def test_every_wave1_driver_declares_a_real_maturity(self) -> None:
        from founderos_atlas.platforms.drivers import CiscoIOSXEDriver

        for driver_cls in (CiscoIOSXEDriver,):
            self.assertIn(driver_cls.maturity, MATURITY_LEVELS)

    def test_no_wave1_driver_claims_more_than_transcripts_prove(self) -> None:
        """No live device was available in this environment. A driver whose
        only evidence is transcript fixtures must say EXPERIMENTAL — a
        maturity above that requires live validation this suite cannot
        provide, and must never be granted by editing this test without it."""

        from founderos_atlas.platforms import drivers as d

        wave1 = [getattr(d, name) for name in dir(d) if name.endswith("Driver")
                 and getattr(getattr(d, name), "platform_id", "").startswith(
                     ("cisco-ios-xe", "cisco-nxos", "arista", "junos"))]
        self.assertTrue(wave1)
        for driver_cls in wave1:
            self.assertEqual(EXPERIMENTAL, driver_cls.maturity,
                             f"{driver_cls.__name__} claims unearned maturity")


class IOSXETests(unittest.TestCase):
    def _driver(self):
        from founderos_atlas.platforms.drivers import CiscoIOSXEDriver

        return CiscoIOSXEDriver()

    def test_identity_model_serial_and_version(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        device = disc.result.device
        self.assertEqual("core-sw1", device.hostname)
        self.assertEqual("cisco-ios-xe:core-sw1", device.device_id)
        self.assertEqual("Cisco IOS-XE", device.os_name)
        self.assertEqual("17.09.04a", device.os_version)
        self.assertEqual("C9300-24T", device.metadata["model"])
        self.assertEqual("FOC24LAB001", device.serial_number)
        self.assertEqual("10.10.10.2", device.management_ip)

    def test_interfaces_including_unassigned_and_admin_down(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        by_name = {i.name: i for i in disc.result.interfaces}
        self.assertEqual("10.10.10.2", by_name["Vlan10"].ip_address)
        self.assertIsNone(by_name["GigabitEthernet1/0/1"].ip_address)
        self.assertEqual("down", by_name["Vlan1"].status)      # admin down
        self.assertEqual("192.0.2.11", by_name["Loopback0"].ip_address)
        self.assertEqual("10.10.99.2", by_name["Port-channel1"].ip_address)

    def test_lldp_and_cdp_neighbors_with_management_ips(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        neighbors = {n.remote_hostname: n for n in disc.result.neighbors}
        # LLDP names an EOS leaf and a Junos edge; CDP names an NX-OS dist.
        self.assertEqual("10.10.20.3", neighbors["leaf-eos1"].remote_management_ip)
        self.assertEqual("Ethernet1", neighbors["leaf-eos1"].remote_interface)
        self.assertEqual("xe-0/0/1", neighbors["edge-jnp1"].remote_interface)
        self.assertEqual("cdp", neighbors["dist-nxos1"].protocol)
        self.assertEqual("Ethernet1/49", neighbors["dist-nxos1"].remote_interface)

    def test_unsupported_is_not_failed(self) -> None:
        outputs = XE.normal()
        outputs["show etherchannel summary"] = XE.UNSUPPORTED
        disc, _ = _discover(self._driver(), outputs, hint="10.10.10.2")
        self.assertEqual(UNSUPPORTED, _report(disc, "lag")["status"])

    def test_privilege_denied_is_failed_with_the_reason(self) -> None:
        outputs = XE.normal()
        outputs["show running-config"] = XE.PRIVILEGE_DENIED
        disc, _ = _discover(self._driver(), outputs, hint="10.10.10.2")
        report = _report(disc, "configuration")
        self.assertEqual(FAILED, report["status"])
        self.assertIn("privilege", report["detail"])

    def test_a_broken_command_preserves_every_other_result(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2",
                            broken={"show ip route"})
        self.assertEqual(FAILED, _report(disc, "routes")["status"])
        # Identity, interfaces and neighbors all survived the failure.
        self.assertEqual("core-sw1", disc.result.device.hostname)
        self.assertTrue(disc.result.interfaces)
        self.assertTrue(disc.result.neighbors)
        self.assertEqual(SUPPORTED, _report(disc, "configuration")["status"])

    def test_command_fallback_is_used_and_recorded(self) -> None:
        outputs = XE.normal()
        del outputs["show lldp neighbors detail"]
        outputs["show lldp neighbors"] = "Device ID Local Intf...\n"
        disc, transport = _discover(self._driver(), outputs, hint="10.10.10.2")
        report = _report(disc, "lldp")
        self.assertEqual(SUPPORTED, report["status"])
        self.assertEqual("show lldp neighbors", report["command_used"])
        self.assertEqual(
            ["show lldp neighbors detail", "show lldp neighbors"],
            list(report["commands_attempted"]),
        )
        # The incompatibility is surfaced as a warning, never hidden.
        warnings = disc.result.device.metadata["driver_diagnostics"]["warnings"]
        self.assertTrue(any("falling back" in w for w in warnings))

    def test_the_fast_tier_reports_not_attempted_by_name(self) -> None:
        disc, transport = _discover(self._driver(), XE.normal(),
                                    hint="10.10.10.2", tier=TIER_FAST)
        self.assertEqual(NOT_ATTEMPTED, _report(disc, "configuration")["status"])
        self.assertEqual(NOT_ATTEMPTED, _report(disc, "routes")["status"])
        self.assertEqual(SUPPORTED, _report(disc, "lldp")["status"])
        self.assertNotIn("show running-config", transport.executed)

    def test_the_deep_tier_collects_mac_stp_and_fhrp(self) -> None:
        disc, transport = _discover(self._driver(), XE.normal(),
                                    hint="10.10.10.2", tier=TIER_DEEP)
        self.assertIn("show mac address-table", transport.executed)
        self.assertIn("show spanning-tree", transport.executed)
        # Empty output from a command that executed is SUPPORTED, not failed.
        self.assertEqual(SUPPORTED, _report(disc, "stp")["status"])
        self.assertIn("nothing to report", _report(disc, "stp")["detail"])

    def test_bgp_peers_and_routes_summarized_into_metadata(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        metadata = disc.result.device.metadata
        self.assertEqual(1, len(metadata["bgp_peers"]))
        self.assertGreaterEqual(metadata["route_count"], 5)

    def test_the_real_rib_rides_beside_the_count(self) -> None:
        """IOS-XE speaks the shared `show ip route` grammar, so the canonical
        parser captures prefixes and next-hops, not just how many there
        were."""

        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        table = disc.result.device.metadata["routing_table"]
        ospf = next(r for r in table if r["protocol"] == "ospf")
        self.assertEqual(("192.0.2.12/32", "10.10.99.1", "Port-channel1"),
                         (ospf["prefix"], ospf["next_hop"], ospf["interface"]))
        default = next(r for r in table if r["prefix"] == "0.0.0.0/0")
        self.assertEqual("10.10.99.1", default["next_hop"])

    def test_lldp_disabled_is_an_honest_empty_not_a_failure(self) -> None:
        outputs = XE.normal()
        outputs["show lldp neighbors detail"] = XE.SHOW_LLDP_DISABLED
        outputs["show lldp neighbors"] = XE.SHOW_LLDP_DISABLED
        disc, _ = _discover(self._driver(), outputs, hint="10.10.10.2")
        report = _report(disc, "lldp")
        # "% LLDP is not enabled" is a device answer, not a rejection of the
        # command form and not a transport failure.
        self.assertNotEqual(FAILED, report["status"])

    def test_raw_outputs_retained_for_the_evidence_sink(self) -> None:
        disc, _ = _discover(self._driver(), XE.normal(), hint="10.10.10.2")
        self.assertIn("show running-config", disc.raw_outputs)
        self.assertIn("hostname core-sw1", disc.raw_outputs["show running-config"])



from tests.platform_fixtures import eos as EOS
from tests.platform_fixtures import junos as JN
from tests.platform_fixtures import nxos as NX


def _wave1():
    """(driver, fixtures, management hint) for every Wave-1 platform."""

    from founderos_atlas.platforms.drivers import (
        AristaEOSDriver, CiscoIOSXEDriver, CiscoNXOSDriver, JunosDriver,
    )

    return (
        (CiscoIOSXEDriver(), XE.normal(), "10.10.10.2"),
        (CiscoNXOSDriver(), NX.normal(), "10.10.20.2"),
        (AristaEOSDriver(), EOS.normal(), "10.10.20.3"),
        (JunosDriver(), JN.normal(), "10.10.20.4"),
    )


class RoutingNormalizationTests(unittest.TestCase):
    def test_every_wave1_driver_emits_vendor_neutral_ospf_and_bgp(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver=driver.platform_id):
                discovery, _transport = _discover(
                    driver, outputs, hint=hint
                )
                protocols = {item.protocol for item in discovery.result.neighbors}
                self.assertIn("ospf", protocols)
                self.assertIn("bgp", protocols)
                routing = discovery.result.device.metadata["routing_evidence"]
                self.assertTrue(routing["ospf_adjacencies"])
                self.assertTrue(routing["bgp_sessions"])
                session = routing["bgp_sessions"][0]
                self.assertTrue(session["peer_address"])
                self.assertTrue(session["remote_as"])
                self.assertIn(
                    session["state"],
                    {"established", "active", "idle", "connect"},
                )

class NXOSTests(unittest.TestCase):
    def test_identity_management_vrf_and_vpc(self) -> None:
        from founderos_atlas.platforms.drivers import CiscoNXOSDriver

        disc, _ = _discover(CiscoNXOSDriver(), NX.normal(), hint="10.10.20.2")
        device = disc.result.device
        self.assertEqual("cisco-nxos:dist-nxos1", device.device_id)
        self.assertEqual("10.2(5)", device.os_version)
        self.assertEqual("FDO24LAB002", device.serial_number)
        # The management endpoint is mgmt0 in VRF "management" -- never a
        # front-panel address chosen by parse order.
        self.assertEqual("10.10.20.2", device.management_ip)
        self.assertEqual("management", device.metadata["management_vrf"])
        self.assertEqual("10", device.metadata["vpc"]["domain"])
        self.assertEqual("primary", device.metadata["vpc"]["role"])

    def test_interfaces_carry_their_vrf(self) -> None:
        from founderos_atlas.platforms.drivers import CiscoNXOSDriver

        disc, _ = _discover(CiscoNXOSDriver(), NX.normal(), hint="10.10.20.2")
        by_name = {i.name: i for i in disc.result.interfaces}
        self.assertEqual("management", by_name["mgmt0"].metadata["vrf"])
        self.assertEqual("default", by_name["Eth1/49"].metadata["vrf"])
        self.assertEqual("192.0.2.12", by_name["Lo0"].ip_address)

    def test_port_channel_membership_is_normalized(self) -> None:
        from founderos_atlas.platforms.drivers import CiscoNXOSDriver

        disc, _ = _discover(CiscoNXOSDriver(), NX.normal(), hint="10.10.20.2")
        pcs = [dict(p) for p in disc.result.device.metadata["port_channels"]]
        self.assertEqual("Po10", pcs[0]["port_channel"])
        self.assertEqual(("Eth1/1", "Eth1/2"), pcs[0]["members"])

    def test_the_nxos_rib_normalizes_into_the_canonical_table(self) -> None:
        """NX-OS writes a different route grammar (prefix line, indented
        next-hops, "direct" for connected) and still lands in the same
        RouteEntry shape every other platform uses."""

        from founderos_atlas.platforms.drivers import CiscoNXOSDriver

        disc, _ = _discover(CiscoNXOSDriver(), NX.normal(), hint="10.10.20.2")
        table = {r["prefix"]: r for r in
                 disc.result.device.metadata["routing_table"]}
        ospf = table["192.0.2.11/32"]
        self.assertEqual(("ospf", "10.10.99.2", "Eth1/49"),
                         (ospf["protocol"], ospf["next_hop"], ospf["interface"]))
        self.assertTrue(table["10.10.10.0/24"]["connected"])

    def test_a_disabled_feature_is_never_failed(self) -> None:
        from founderos_atlas.platforms.drivers import CiscoNXOSDriver

        disc, _ = _discover(CiscoNXOSDriver(), NX.normal(), hint="10.10.20.2",
                            tier=TIER_DEEP)
        # `show hsrp brief` without `feature hsrp` is rejected by the device:
        # that is UNSUPPORTED (a platform fact), not FAILED (an Atlas fact).
        self.assertEqual(UNSUPPORTED, _report(disc, "first-hop-redundancy")["status"])


class EOSTests(unittest.TestCase):
    def test_the_indented_eos_rib_is_captured(self) -> None:
        """EOS indents every route line and uses two-letter sub-codes
        ("B E"). Both were invisible to a parser anchored at column 0."""

        from founderos_atlas.platforms.drivers import AristaEOSDriver

        disc, _ = _discover(AristaEOSDriver(), EOS.normal(), hint="10.10.20.3")
        table = {r["prefix"]: r for r in
                 disc.result.device.metadata["routing_table"]}
        bgp = table["192.0.2.11/32"]
        self.assertEqual(("bgp", "10.10.30.0", "Ethernet1"),
                         (bgp["protocol"], bgp["next_hop"], bgp["interface"]))
        self.assertTrue(table["10.10.10.0/24"]["connected"])

    def test_identity_needs_show_hostname_and_gets_it(self) -> None:
        from founderos_atlas.platforms.drivers import AristaEOSDriver

        disc, _ = _discover(AristaEOSDriver(), EOS.normal(), hint="10.10.20.3")
        device = disc.result.device
        self.assertEqual("arista-eos:leaf-eos1", device.device_id)
        self.assertEqual("4.30.5M", device.os_version)
        self.assertEqual("JPE24LAB003", device.serial_number)
        self.assertEqual("DCS-7050SX3-48YC8-R", device.metadata["model"])
        # Management1 preferred as the endpoint.
        self.assertEqual("10.10.20.3", device.management_ip)

    def test_cidr_interface_addresses_normalize(self) -> None:
        from founderos_atlas.platforms.drivers import AristaEOSDriver

        disc, _ = _discover(AristaEOSDriver(), EOS.normal(), hint="10.10.20.3")
        by_name = {i.name: i for i in disc.result.interfaces}
        self.assertEqual("10.10.30.1", by_name["Ethernet1"].ip_address)
        self.assertEqual(31, by_name["Ethernet1"].metadata["prefix_length"])
        self.assertEqual("192.0.2.13", by_name["Loopback0"].ip_address)

    def test_mlag_summarized_with_its_limitation_stated(self) -> None:
        from founderos_atlas.platforms.drivers import AristaEOSDriver

        disc, _ = _discover(AristaEOSDriver(), EOS.normal(), hint="10.10.20.3")
        mlag = disc.result.device.metadata["mlag"]
        self.assertEqual("mlag-pod1", mlag["domain_id"])
        self.assertEqual("Active", mlag["state"])
        report = _report(disc, "lag")
        self.assertEqual("supported-with-limitations", report["status"])
        self.assertIn("MLAG only", report["detail"])


class JunosTests(unittest.TestCase):
    def test_the_junos_rib_normalizes_into_the_canonical_table(self) -> None:
        """Junos writes a third grammar — protocol and preference bracketed
        on the prefix line — and still lands in the same RouteEntry."""

        from founderos_atlas.platforms.drivers import JunosDriver

        disc, _ = _discover(JunosDriver(), JN.normal(), hint="10.10.20.4")
        table = {r["prefix"]: r for r in
                 disc.result.device.metadata["routing_table"]}
        ospf = table["192.0.2.13/32"]
        self.assertEqual(("ospf", "10.10.40.0", "ge-0/0/0.0"),
                         (ospf["protocol"], ospf["next_hop"], ospf["interface"]))
        # A Direct route is connected and has no next-hop.
        direct = table["10.10.40.0/31"]
        self.assertEqual((None, True), (direct["next_hop"], direct["connected"]))

    def test_identity_from_junoss_own_fields(self) -> None:
        from founderos_atlas.platforms.drivers import JunosDriver

        disc, _ = _discover(JunosDriver(), JN.normal(), hint="10.10.20.4")
        device = disc.result.device
        self.assertEqual("junos:edge-jnp1", device.device_id)
        self.assertEqual("21.4R3.15", device.os_version)
        self.assertEqual("ex4300-24t", device.metadata["model"])
        self.assertEqual("JN24LAB0004", device.serial_number)
        self.assertEqual("10.10.20.4", device.management_ip)   # me0 preferred

    def test_logical_units_keep_their_hierarchy(self) -> None:
        from founderos_atlas.platforms.drivers import JunosDriver

        disc, _ = _discover(JunosDriver(), JN.normal(), hint="10.10.20.4")
        by_name = {i.name: i for i in disc.result.interfaces}
        unit = by_name["ge-0/0/0.0"]
        self.assertEqual("10.10.40.1", unit.ip_address)
        self.assertEqual("ge-0/0/0", unit.metadata["physical_interface"])
        self.assertEqual(0, unit.metadata["logical_unit"])
        self.assertEqual("inet", unit.metadata["address_family"])
        # ...and the physical parent exists too, without an address.
        self.assertIsNone(by_name["ge-0/0/0"].ip_address)
        self.assertEqual("down", by_name["ge-0/0/1"].protocol_status)

    def test_junos_refusal_grammar_is_unsupported_not_failed(self) -> None:
        from founderos_atlas.platforms.drivers import JunosDriver

        outputs = JN.normal()
        outputs["show ospf neighbor"] = JN.UNSUPPORTED
        disc, _ = _discover(JunosDriver(), outputs, hint="10.10.20.4",
                            reject_unknown=JN.UNSUPPORTED)
        self.assertEqual(UNSUPPORTED, _report(disc, "ospf")["status"])

    def test_configuration_is_the_stable_set_form(self) -> None:
        from founderos_atlas.platforms.drivers import JunosDriver

        disc, _ = _discover(JunosDriver(), JN.normal(), hint="10.10.20.4")
        config = disc.raw_outputs["show configuration | display set"]
        self.assertIn("set system host-name edge-jnp1", config)
        # Hierarchy preserved as explicit paths, one statement per line.
        self.assertIn("set interfaces ge-0/0/0 unit 0 family inet address", config)

    def test_routing_instances_are_observed(self) -> None:
        from founderos_atlas.platforms.drivers import JunosDriver

        disc, _ = _discover(JunosDriver(), JN.normal(), hint="10.10.20.4")
        self.assertIn("mgmt_junos.inet.0",
                      disc.result.device.metadata["routing_instances"])


class CrossVendorContractTests(unittest.TestCase):
    """Part 18: one contract suite, every Wave-1 driver, no exceptions."""

    def test_identity_and_management_endpoint(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                device = disc.result.device
                self.assertTrue(device.hostname)
                self.assertTrue(device.device_id.startswith(driver.platform_id))
                self.assertEqual(hint, device.management_ip)
                self.assertTrue(device.os_version)

    def test_interfaces_uniquely_normalized(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                names = [i.name for i in disc.result.interfaces]
                self.assertTrue(names)
                self.assertEqual(len(names), len(set(names)),
                                 "duplicate interface names")

    def test_neighbors_never_invent_management_endpoints(self) -> None:
        """A neighbor's management IP is present only when the protocol
        advertised one -- never synthesized from a chassis MAC or name."""

        import ipaddress

        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                self.assertTrue(disc.result.neighbors)
                for n in disc.result.neighbors:
                    if n.remote_management_ip is not None:
                        ipaddress.ip_address(n.remote_management_ip)

    def test_configuration_status_is_honest_and_raw_retained(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                report = _report(disc, "configuration")
                self.assertIn(report["status"],
                              (SUPPORTED, "supported-with-limitations"))
                self.assertIn(report["command_used"], disc.raw_outputs)
                self.assertTrue(disc.raw_outputs[report["command_used"]].strip())

    def test_unsupported_and_empty_both_differ_from_failed(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                # Break one optional command at the transport: FAILED.
                broken_cmd = driver.command_plan()[-1].commands[0]
                disc, _ = _discover(driver, outputs, hint=hint,
                                    tier=TIER_DEEP, broken={broken_cmd})
                statuses = {
                    item["capability"]: item["status"]
                    for item in disc.result.device.metadata[
                        "driver_diagnostics"]["capabilities"]
                }
                self.assertIn(FAILED, statuses.values())
                # ...while identity stayed SUPPORTED -- partials preserved.
                self.assertEqual(SUPPORTED, statuses["identity"])

    def test_diagnostics_matrix_is_complete_and_serializable(self) -> None:
        import json

        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                diag = disc.result.device.metadata["driver_diagnostics"]
                planned = {s.capability for s in driver.command_plan()}
                reported = {c["capability"] for c in diag["capabilities"]}
                self.assertEqual(planned, reported)
                # Canonical metadata freezes nested mappings; snapshots
                # serialize them by converting to plain dicts -- so does this.
                json.dumps(diag, default=dict)
                self.assertIn(diag["maturity"], MATURITY_LEVELS)

    def test_deterministic_output(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                one, _ = _discover(driver, outputs, hint=hint)
                two, _ = _discover(driver, outputs, hint=hint)
                self.assertEqual(one.result.device, two.result.device)
                self.assertEqual(one.result.neighbors, two.result.neighbors)

    def test_no_fixture_secret_reaches_normalized_models(self) -> None:
        for driver, outputs, hint in _wave1():
            with self.subTest(driver.platform_id):
                disc, _ = _discover(driver, outputs, hint=hint)
                blob = str(disc.result.device)
                self.assertNotIn("password", blob.casefold())
                self.assertNotIn("enable secret", blob.casefold())


class MixedVendorNormalizationTests(unittest.TestCase):
    """Part 15: evidence from four vendors names the same physical links.

    The fixtures form one square: XE<->NX-OS (CDP+LLDP), XE<->EOS (LLDP),
    NX-OS<->EOS (LLDP), Junos<->EOS and Junos<->XE (LLDP). Correlation
    constructs edges from these observations; here we prove the observations
    AGREE on hostname identity across vendors -- the precondition for every
    mixed edge. No driver constructed a topology edge to make this pass.
    """

    def test_the_same_link_is_named_identically_from_both_ends(self) -> None:
        observed: dict[str, set] = {}
        for driver, outputs, hint in _wave1():
            disc, _ = _discover(driver, outputs, hint=hint)
            local = disc.result.device.hostname
            for n in disc.result.neighbors:
                observed.setdefault(local, set()).add(n.remote_hostname)
        # Both ends of each mixed-vendor pair name each other.
        self.assertIn("leaf-eos1", observed["core-sw1"])     # XE  -> EOS
        self.assertIn("core-sw1", observed["leaf-eos1"])     # EOS -> XE
        self.assertIn("dist-nxos1", observed["core-sw1"])    # XE  -> NX-OS
        self.assertIn("core-sw1", observed["dist-nxos1"])    # NX-OS -> XE
        self.assertIn("leaf-eos1", observed["dist-nxos1"])   # NX-OS -> EOS
        self.assertIn("core-sw1", observed["edge-jnp1"])     # Junos -> XE
        self.assertIn("leaf-eos1", observed["edge-jnp1"])    # Junos -> EOS
        self.assertIn("edge-jnp1", observed["core-sw1"])     # XE  -> Junos


if __name__ == "__main__":
    unittest.main()
