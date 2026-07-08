"""Acceptance tests for PR-021.1 canonical device identity resolution."""

from __future__ import annotations

import unittest

from founderos_atlas.identity import (
    DEFAULT_MATCH_RULES,
    DeviceIdentity,
    ExtraIdentifierMatch,
    IdentityResolver,
    normalize_hostname,
    short_hostname,
)
from founderos_atlas.discovery import DiscoveryEngine
from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.visualization import TopologyRenderer

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def discover(outputs_by_host: dict[str, dict[str, str]], host: str):
    engine = DiscoveryEngine(CiscoIOSAdapter())
    return engine.discover(outputs_by_host[host], management_ip_hint=host)


def cml_lab() -> ScriptedNetwork:
    """The real CML scenario: bare hostnames locally, FQDNs over CDP."""

    return ScriptedNetwork(
        {
            "10.0.0.1": device_outputs(
                "R1", "10.0.0.1", (("SW1.atlas.local", "10.0.0.2"),)
            ),
            "10.0.0.2": device_outputs(
                "SW1", "10.0.0.2", (("R1.atlas.local", "10.0.0.1"),)
            ),
        }
    )


class HostnameNormalizationTests(unittest.TestCase):
    def test_variants_normalize_to_one_identity(self) -> None:
        for value in ("R1", "r1", "R1.", " R1 "):
            with self.subTest(value=value):
                self.assertEqual("r1", normalize_hostname(value))
        self.assertEqual("r1", short_hostname("R1.atlas.local"))

    def test_normalization_is_matching_only(self) -> None:
        network = cml_lab()
        results = (
            discover(network.topology, "10.0.0.1"),
            discover(network.topology, "10.0.0.2"),
        )
        resolution = IdentityResolver().resolve(results)
        names = {device.canonical_hostname for device in resolution.devices}
        self.assertEqual({"R1", "SW1"}, names)  # original casing preserved


class IdentityResolutionTests(unittest.TestCase):
    def resolve_cml(self):
        network = cml_lab()
        results = (
            discover(network.topology, "10.0.0.1"),
            discover(network.topology, "10.0.0.2"),
        )
        return IdentityResolver().resolve(results), results

    def test_hostname_fqdn_references_merge_onto_devices(self) -> None:
        resolution, _ = self.resolve_cml()
        self.assertEqual(2, len(resolution.devices))
        self.assertEqual((), resolution.observed_only)
        self.assertEqual("R1", resolution.display_hostname("R1.atlas.local"))
        self.assertEqual("SW1", resolution.display_hostname("sw1.atlas.local"))

    def test_alias_preservation(self) -> None:
        resolution, _ = self.resolve_cml()
        by_name = {device.canonical_hostname: device for device in resolution.devices}
        self.assertEqual(("R1.atlas.local",), by_name["R1"].aliases)
        self.assertEqual(("SW1.atlas.local",), by_name["SW1"].aliases)
        self.assertEqual(("R1.atlas.local",), resolution.aliases_for("R1"))

    def test_case_differences_merge(self) -> None:
        network = ScriptedNetwork(
            {"10.0.0.1": device_outputs("R1", "10.0.0.1", (("r1", "10.0.0.1"),))}
        )
        results = (discover(network.topology, "10.0.0.1"),)
        resolution = IdentityResolver().resolve(results)
        self.assertEqual(1, len(resolution.devices))
        self.assertEqual("R1", resolution.devices[0].canonical_hostname)

    def test_canonicalize_preserves_original_observations(self) -> None:
        resolution, results = self.resolve_cml()
        canonical = resolution.canonicalize(results)
        r1 = canonical[0]
        self.assertEqual("SW1", r1.neighbors[0].remote_hostname)
        self.assertEqual(
            "SW1.atlas.local", r1.neighbors[0].metadata["observed_remote_hostname"]
        )
        # Untouched originals remain available on the raw results.
        self.assertEqual("SW1.atlas.local", results[0].neighbors[0].remote_hostname)

    def test_no_false_merges_across_domains(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "core",
                    "10.0.0.1",
                    (("web.prod.local", None), ("web.dev.local", None)),
                )
            }
        )
        results = (discover(network.topology, "10.0.0.1"),)
        resolution = IdentityResolver().resolve(results)
        self.assertEqual(2, len(resolution.observed_only))
        displays = {
            resolution.display_hostname("web.prod.local"),
            resolution.display_hostname("web.dev.local"),
        }
        self.assertEqual(2, len(displays))  # distinct labels, no shared "web"

    def test_similar_hostnames_do_not_merge(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("r1", "10.0.0.1"),
                "10.0.0.10": device_outputs("r10", "10.0.0.10"),
            }
        )
        results = (
            discover(network.topology, "10.0.0.1"),
            discover(network.topology, "10.0.0.10"),
        )
        resolution = IdentityResolver().resolve(results)
        self.assertEqual(2, len(resolution.devices))

    def test_management_ip_precedence_over_hostname(self) -> None:
        # CDP advertises an unrelated name but the shared IP identifies SW1.
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "R1", "10.0.0.1", (("switch-mgmt-alias", "10.0.0.2"),)
                ),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2"),
            }
        )
        results = (
            discover(network.topology, "10.0.0.1"),
            discover(network.topology, "10.0.0.2"),
        )
        resolution = IdentityResolver().resolve(results)
        self.assertEqual(2, len(resolution.devices))
        self.assertEqual((), resolution.observed_only)
        self.assertEqual("SW1", resolution.display_hostname("switch-mgmt-alias"))
        by_name = {device.canonical_hostname: device for device in resolution.devices}
        self.assertIn("switch-mgmt-alias", by_name["SW1"].aliases)

    def test_future_vendor_rule_extension(self) -> None:
        first = DeviceIdentity(
            hostnames=("edge-a",),
            management_ips=("192.0.2.1",),
            extra_identifiers={"chassis_id": "AA:BB:CC:00:11:22"},
        )
        second = DeviceIdentity(
            hostnames=("edge-b",),
            management_ips=("192.0.2.2",),
            extra_identifiers={"chassis_id": "aa:bb:cc:00:11:22"},
        )
        default_rules_match = any(
            rule.matches(first, second) for rule in DEFAULT_MATCH_RULES
        )
        self.assertFalse(default_rules_match)
        chassis_rule = ExtraIdentifierMatch("chassis_id")
        self.assertTrue(chassis_rule.matches(first, second))
        resolver = IdentityResolver(rules=(*DEFAULT_MATCH_RULES, chassis_rule))
        self.assertTrue(resolver._matches(first, second))

    def test_resolution_is_deterministic(self) -> None:
        first, results = self.resolve_cml()
        second = IdentityResolver().resolve(results)
        self.assertEqual(first.devices, second.devices)
        self.assertEqual(first.canonicalize(results), second.canonicalize(results))


class RelationshipReconciliationTests(unittest.TestCase):
    """Definition of Done: R1 -------- SW1. Two devices. One relationship."""

    @classmethod
    def setUpClass(cls) -> None:
        network = cml_lab()
        cls.report, cls.graph, cls.snapshot = run_multihop_discovery(
            network.transport_factory, "10.0.0.1"
        )
        cls.elements = TopologyRenderer(cls.snapshot).elements()

    def test_two_devices_not_four(self) -> None:
        self.assertEqual(2, self.snapshot.device_count)
        hostnames = {device["hostname"] for device in self.snapshot.devices}
        self.assertEqual({"R1", "SW1"}, hostnames)
        self.assertEqual(2, len(self.elements["nodes"]))
        kinds = {node["data"]["kind"] for node in self.elements["nodes"]}
        self.assertEqual({"discovered"}, kinds)  # no observed placeholders

    def test_one_displayed_relationship(self) -> None:
        self.assertEqual(1, len(self.elements["edges"]))
        edge = self.elements["edges"][0]["data"]
        self.assertEqual(2, edge["observations"])
        node_ids = {node["data"]["id"] for node in self.elements["nodes"]}
        self.assertIn(edge["source"], node_ids)
        self.assertIn(edge["target"], node_ids)

    def test_snapshot_contract_keeps_directed_observations(self) -> None:
        self.assertEqual(2, self.snapshot.edge_count)

    def test_aliases_available_in_node_details(self) -> None:
        aliases = {
            node["data"]["label"]: node["data"]["aliases"]
            for node in self.elements["nodes"]
        }
        self.assertEqual(["R1.atlas.local"], aliases["R1"])
        self.assertEqual(["SW1.atlas.local"], aliases["SW1"])
        html = TopologyRenderer(self.snapshot).render()
        self.assertIn("Aliases", html)
        self.assertIn("R1.atlas.local", html)

    def test_metadata_records_identity_resolution(self) -> None:
        self.assertTrue(self.snapshot.metadata["identity_resolution"])

    def test_single_direction_edge_still_renders_once(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs(
                    "R1", "10.0.0.1", (("SW1.atlas.local", "10.0.0.2"),)
                ),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2"),
            }
        )
        _, _, snapshot = run_multihop_discovery(network.transport_factory, "10.0.0.1")
        elements = TopologyRenderer(snapshot).elements()
        self.assertEqual(2, len(elements["nodes"]))
        self.assertEqual(1, len(elements["edges"]))
        self.assertEqual(1, elements["edges"][0]["data"]["observations"])


if __name__ == "__main__":
    unittest.main()
