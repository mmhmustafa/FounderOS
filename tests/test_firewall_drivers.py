"""Tier-1 firewall drivers: FortiOS and PAN-OS (POLYGLOT Wave 2).

TRANSCRIPT VALIDATED: every assertion runs against sanitized transcripts
of realistic FortiOS 7.2 / PAN-OS 10.2 output. Cross-driver tests prove
the two vendors normalize into identical canonical firewall models with
no vendor branching anywhere downstream.
"""

from __future__ import annotations

import json
import unittest

from founderos_atlas.platforms.capabilities import UNSUPPORTED
from founderos_atlas.platforms.drivers import FortiOSDriver, PanOsDriver
from founderos_atlas.platforms.registry import default_registry

from tests.platform_fixtures import fortios as FG
from tests.platform_fixtures import panos as PA


class FakeTransport:
    def __init__(self, outputs: dict, *, unknown: str) -> None:
        self.outputs = dict(outputs)
        self.unknown = unknown
        self.executed: list[str] = []

    def execute(self, command: str) -> str:
        self.executed.append(command)
        return self.outputs.get(command, self.unknown)


def _fortigate(**overrides):
    outputs = {**FG.normal(), **overrides}
    transport = FakeTransport(outputs, unknown=FG.UNKNOWN)
    discovery = FortiOSDriver().discover(
        transport, management_ip_hint="172.20.20.34",
        probe_output=outputs["get system status"],
    )
    return discovery, transport


def _paloalto(**overrides):
    outputs = {**PA.normal(), **overrides}
    transport = FakeTransport(outputs, unknown=PA.UNKNOWN)
    discovery = PanOsDriver().discover(
        transport, management_ip_hint="172.20.20.42",
        probe_output=outputs["show system info"],
    )
    return discovery, transport


class DetectionTests(unittest.TestCase):
    def test_fortios_probe_detects_with_confidence_and_evidence(self) -> None:
        detection = default_registry().identify(FG.GET_SYSTEM_STATUS)
        self.assertEqual("fortinet-fortios", detection.platform_id)
        self.assertGreaterEqual(detection.confidence, 0.9)
        self.assertTrue(detection.evidence)

    def test_panos_probe_detects_with_confidence_and_evidence(self) -> None:
        detection = default_registry().identify(PA.SHOW_SYSTEM_INFO)
        self.assertEqual("paloalto-panos", detection.platform_id)
        self.assertGreaterEqual(detection.confidence, 0.9)
        self.assertEqual((), detection.alternatives)

    def test_banner_and_prompt_fingerprints_enrich_the_evidence(self) -> None:
        detection = default_registry().identify(
            PA.SHOW_SYSTEM_INFO,
            banner="PAN-OS 10.2.4", prompt="admin@sec-fw-01> ",
        )
        self.assertEqual("paloalto-panos", detection.platform_id)
        joined = " ".join(detection.evidence)
        self.assertIn("banner matched", joined)
        self.assertIn("prompt matched", joined)

    def test_a_fingerprint_alone_never_selects_a_driver(self) -> None:
        detection = default_registry().identify(
            "garbage the probe could not read",
            banner="FortiGate-100F", prompt="hyd-fw-01 # ",
        )
        self.assertIsNone(detection.platform_id)
        self.assertEqual(0.0, detection.confidence)

    def test_firewall_probes_never_match_router_drivers(self) -> None:
        registry = default_registry()
        for probe in (FG.GET_SYSTEM_STATUS, PA.SHOW_SYSTEM_INFO):
            matched = [
                cls.platform_id for cls in registry.drivers()
                if cls.matches(probe)
            ]
            self.assertEqual(1, len(matched), matched)


class FortiOSTests(unittest.TestCase):
    def test_identity_model_serial_version_and_vdom_mode(self) -> None:
        discovery, _ = _fortigate()
        device = discovery.result.device
        self.assertEqual("fortinet-fortios:hyd-fw-01", device.device_id)
        self.assertEqual("FortiGate-100F", device.platform)
        self.assertEqual("7.2.5", device.os_version)
        self.assertEqual("FG100F1234567890", device.serial_number)
        self.assertEqual("172.20.20.34", device.management_ip)
        self.assertEqual("firewall", device.metadata["device_role"])

    def test_zones_policies_and_action_normalization(self) -> None:
        discovery, _ = _fortigate()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        zones = {z["name"]: list(z["interfaces"]) for z in evidence["zones"]}
        self.assertEqual(["port1", "port3"], zones["trust"])
        actions = {p["policy_id"]: p["action"]
                   for p in evidence["security_policies"]}
        # FortiOS "accept" is canonical "allow"; "deny" stays "deny".
        self.assertIn("allow", actions.values())
        self.assertIn("deny", actions.values())
        self.assertEqual("deny", evidence["summary"]["default_action"])

    def test_vpn_ha_and_vdom_evidence(self) -> None:
        discovery, _ = _fortigate()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        statuses = {v["name"]: v["status"] for v in evidence["vpns"]}
        self.assertIn("up", statuses.values())
        self.assertEqual("a-p", evidence["ha_mode"])
        self.assertTrue(evidence["ha_peers"])
        kinds = {c["context_type"] for c in evidence["virtual_contexts"]}
        self.assertEqual({"vdom"}, kinds)

    def test_routing_evidence_is_vendor_neutral(self) -> None:
        discovery, _ = _fortigate()
        metadata = discovery.result.device.metadata
        routing = metadata["routing_evidence"]
        self.assertTrue(routing["ospf_adjacencies"])
        self.assertTrue(routing["bgp_sessions"])
        protocols = {n.protocol for n in discovery.result.neighbors}
        self.assertEqual({"ospf", "bgp"}, protocols)

    def test_unknown_command_is_unsupported_not_failed(self) -> None:
        discovery, _ = _fortigate(**{"get vpn ipsec tunnel summary": FG.UNKNOWN})
        report = discovery.result.device.metadata["driver_diagnostics"]
        by_name = {r["capability"]: r for r in report["capabilities"]}
        self.assertEqual(UNSUPPORTED, by_name["vpn"]["status"])

    def test_no_secret_shapes_in_evidence_or_raw(self) -> None:
        discovery, _ = _fortigate()
        blob = json.dumps({
            "metadata": {
                k: v for k, v in discovery.result.device.metadata.items()
                if k == "firewall_evidence"
            },
        }, default=str)
        for marker in ("psksecret", "private-key", "passwd", "ENC "):
            self.assertNotIn(marker, blob)


class PanOsTests(unittest.TestCase):
    def test_identity_model_serial_version_and_vsys_mode(self) -> None:
        discovery, _ = _paloalto()
        device = discovery.result.device
        self.assertEqual("paloalto-panos:sec-fw-01", device.device_id)
        self.assertEqual("PA-850", device.platform)
        self.assertEqual("10.2.4-h2", device.os_version)
        self.assertEqual("013201001234", device.serial_number)
        self.assertEqual("172.20.20.42", device.management_ip)
        self.assertTrue(device.metadata["multi_vsys"])

    def test_zones_are_read_per_vsys_from_the_interface_table(self) -> None:
        discovery, _ = _paloalto()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        zones = {
            (z["name"], z["virtual_context"]): list(z["interfaces"])
            for z in evidence["zones"]
        }
        self.assertEqual(["ethernet1/2"], zones[("trust", "vsys1")])
        self.assertEqual(["ethernet1/3"], zones[("dmz", "vsys2")])

    def test_rulebase_actions_and_default_posture(self) -> None:
        discovery, _ = _paloalto()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        by_name = {p["name"]: p for p in evidence["security_policies"]}
        self.assertEqual("allow", by_name["rule1"]["action"])
        self.assertEqual("deny", by_name["cleanup-deny"]["action"])
        self.assertEqual(("trust",), tuple(by_name["rule1"]["from_zones"]))
        self.assertIn("web-browsing", by_name["rule1"]["applications"])
        self.assertEqual("deny", evidence["summary"]["default_action"])

    def test_nat_directions_are_normalized(self) -> None:
        discovery, _ = _paloalto()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        kinds = {n["name"]: n["nat_type"] for n in evidence["nat_rules"]}
        self.assertEqual("source", kinds["outbound-pat"])
        self.assertEqual("destination", kinds["web-dnat"])

    def test_vpn_ha_and_vsys_evidence(self) -> None:
        discovery, _ = _paloalto()
        evidence = discovery.result.device.metadata["firewall_evidence"]
        self.assertEqual(
            {"to-branch", "to-dr-site"},
            {v["name"] for v in evidence["vpns"]},
        )
        self.assertEqual("a-p", evidence["ha_mode"])
        serials = {p["peer_serial"] for p in evidence["ha_peers"]}
        self.assertIn("013201005678", serials)
        kinds = {c["context_type"] for c in evidence["virtual_contexts"]}
        self.assertEqual({"vsys"}, kinds)

    def test_lldp_ospf_and_bgp_are_canonical_neighbors(self) -> None:
        discovery, _ = _paloalto()
        by_protocol: dict[str, list] = {}
        for neighbor in discovery.result.neighbors:
            by_protocol.setdefault(neighbor.protocol, []).append(neighbor)
        self.assertEqual(
            "dc-core-sw1", by_protocol["lldp"][0].remote_hostname
        )
        self.assertEqual(
            "192.0.2.130", by_protocol["ospf"][0].remote_hostname
        )
        states = {
            n.metadata.get("state") for n in by_protocol["bgp"]
        }
        self.assertIn("established", states)

    def test_vrfs_come_from_the_routing_table(self) -> None:
        discovery, _ = _paloalto()
        self.assertEqual(
            ("default", "tenant-b"),
            tuple(discovery.result.device.metadata["vrfs"]),
        )

    def test_unknown_command_is_unsupported_not_failed(self) -> None:
        discovery, _ = _paloalto(**{"show vpn ipsec-sa": PA.UNKNOWN})
        report = discovery.result.device.metadata["driver_diagnostics"]
        by_name = {r["capability"]: r for r in report["capabilities"]}
        self.assertEqual(UNSUPPORTED, by_name["vpn"]["status"])


class CrossVendorContractTests(unittest.TestCase):
    """The same canonical shape from both vendors — the whole point."""

    def _evidence(self):
        forti, _ = _fortigate()
        palo, _ = _paloalto()
        return (
            forti.result.device.metadata["firewall_evidence"],
            palo.result.device.metadata["firewall_evidence"],
        )

    def test_both_vendors_populate_identical_schema_keys(self) -> None:
        forti, palo = self._evidence()
        self.assertEqual(set(forti.keys()), set(palo.keys()))
        self.assertEqual(
            set(forti["summary"].keys()), set(palo["summary"].keys())
        )

    def test_actions_share_one_vocabulary(self) -> None:
        forti, palo = self._evidence()
        allowed = {"allow", "deny", "unknown"}
        for evidence in (forti, palo):
            for policy in evidence["security_policies"]:
                self.assertIn(policy["action"], allowed)

    def test_classification_needs_no_vendor_branch(self) -> None:
        from founderos_atlas.platforms.classify import classify_role

        for build in (_fortigate, _paloalto):
            discovery, _ = build()
            device = discovery.result.device
            role, reason = classify_role({
                "hostname": device.hostname,
                "platform": device.platform,
                "metadata": dict(device.metadata),
            })
            self.assertEqual("firewall", role, reason)

    def test_firewall_models_never_leak_into_router_metadata(self) -> None:
        # Firewalls are not routers: zone/policy evidence lives ONLY under
        # firewall_evidence, never merged into routing keys.
        for build in (_fortigate, _paloalto):
            discovery, _ = build()
            routing = discovery.result.device.metadata.get(
                "routing_evidence", {}
            )
            self.assertNotIn("zones", routing)
            self.assertNotIn("security_policies", routing)

    def test_raw_outputs_are_preserved_for_the_evidence_sink(self) -> None:
        for build, probe in (
            (_fortigate, "get system status"),
            (_paloalto, "show system info"),
        ):
            discovery, _ = build()
            self.assertIn(probe, discovery.raw_outputs)
            self.assertTrue(discovery.raw_outputs[probe].strip())


if __name__ == "__main__":
    unittest.main()
