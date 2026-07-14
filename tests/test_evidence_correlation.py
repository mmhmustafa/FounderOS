"""PR-043.7 (FUSION) — Evidence Correlation Engine acceptance tests.

Covers the Part 12 checklist: address/interface/loopback/router-id
ownership, BGP and OSPF reconciliation, point-to-point subnet matching,
interface-description matching, multi-evidence fusion, relationship
confidence, deterministic topology, parallel completion order, repeated
discovery (reconciliation without rediscovery), and the shared
discovery pipeline across Seed and CIDR entry modes.

The ISP lab mirrors Part 6's manual validation exactly:

    isp1   mgmt 172.20.20.7   lo 192.0.2.50
           eth1 192.0.2.65/30 "LINK-TO-edge1-ISP-EDGE"
           eth2 192.0.2.69/30 "LINK-TO-edge2-ISP-EDGE"
           BGP peers 192.0.2.66, 192.0.2.70
    edge1  mgmt 172.20.20.8   eth1 192.0.2.66/30
    edge2  mgmt 172.20.20.9   eth1 192.0.2.70/30
"""

from __future__ import annotations

import inspect
import json
import unittest

from founderos_atlas.correlation import (
    CONFIDENCE_CAP,
    EvidenceCorrelationEngine,
    build_ownership_index,
)
from founderos_atlas.discovery import resolve_plan
from founderos_atlas.discovery.multihop import MultiHopConfig
from founderos_atlas.live import run_discovery_plan, run_multihop_discovery
from founderos_atlas.visualization import TopologyRenderer

from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_platforms import frr_version


# -- the ISP FRRouting lab fixture ------------------------------------------------


def _iface(name: str, inet: str | None, description: str | None = None) -> str:
    block = f"Interface {name} is up, line protocol is up\n  vrf: default\n"
    if description:
        block += f"  Description: {description}\n"
    if inet:
        block += f"  inet {inet}\n"
    return block


def isp_bgp_summary(router_id: str, peers: tuple[str, ...]) -> str:
    rows = "".join(
        f"{peer:<15} 4      6500{index}       100       100        0    0"
        "    0 01:00:00            3        5 N/A\n"
        for index, peer in enumerate(peers, start=2)
    )
    return (
        "IPv4 Unicast Summary (VRF default):\n"
        f"BGP router identifier {router_id}, local AS number 65001 vrf-id 0\n"
        "BGP table version 4\n\n"
        "Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ"
        "  Up/Down State/PfxRcd   PfxSnt Desc\n"
        + rows
    )


def isp1_outputs() -> dict[str, str]:
    return {
        "show version": frr_version("isp1"),
        "show interface": (
            _iface("eth0", "172.20.20.7/24")
            + _iface("eth1", "192.0.2.65/30", "LINK-TO-edge1-ISP-EDGE")
            + _iface("eth2", "192.0.2.69/30", "LINK-TO-edge2-ISP-EDGE")
            + _iface("lo", "192.0.2.50/32")
        ),
        "show ip ospf neighbor": "% OSPF instance not found\n",
        "show ip route": "C>* 192.0.2.64/30 is directly connected, eth1, 01:02:03\n",
        "show bgp summary": isp_bgp_summary(
            "192.0.2.50", ("192.0.2.66", "192.0.2.70")
        ),
        "show lldp neighbors": "% Unknown command: show lldp neighbors\n",
        "show running-config": "frr version 8.4.2\nhostname isp1\n!\nend\n",
    }


def edge_outputs(hostname: str, management_ip: str, link_ip: str) -> dict[str, str]:
    return {
        "show version": frr_version(hostname),
        "show interface": (
            _iface("eth0", f"{management_ip}/24")
            + _iface("eth1", f"{link_ip}/30")
        ),
        "show ip ospf neighbor": "% OSPF instance not found\n",
        "show ip route": "C>* 192.0.2.64/30 is directly connected, eth1, 01:02:03\n",
        "show bgp summary": "% BGP instance not found\n",
        "show lldp neighbors": "% Unknown command: show lldp neighbors\n",
        "show running-config": f"frr version 8.4.2\nhostname {hostname}\n!\nend\n",
    }


ISP_ADDRESSES = ("172.20.20.7", "172.20.20.8", "172.20.20.9")


def isp_lab() -> ScriptedNetwork:
    return ScriptedNetwork(
        {
            "172.20.20.7": isp1_outputs(),
            "172.20.20.8": edge_outputs("edge1", "172.20.20.8", "192.0.2.66"),
            "172.20.20.9": edge_outputs("edge2", "172.20.20.9", "192.0.2.70"),
        }
    )


def discover_isp_lab(workers: int = 4):
    return run_multihop_discovery(
        isp_lab().transport_factory,
        ISP_ADDRESSES[0],
        extra_seeds=ISP_ADDRESSES[1:],
        workers=workers,
        config=MultiHopConfig(max_depth=0, max_devices=64),
    )


# -- ownership (Parts 3 + 4) ------------------------------------------------------


class AddressOwnershipTests(unittest.TestCase):
    def test_every_address_kind_is_claimed_for_its_device(self) -> None:
        _report, graph, snapshot = discover_isp_lab()
        ownership = dict(snapshot.metadata["address_ownership"])
        cases = {
            "172.20.20.7": ("frr:isp1", "management"),
            "192.0.2.50": ("frr:isp1", "loopback"),
            "192.0.2.65": ("frr:isp1", "interface"),
            "192.0.2.69": ("frr:isp1", "interface"),
            "192.0.2.66": ("frr:edge1", "interface"),
            "192.0.2.70": ("frr:edge2", "interface"),
        }
        for address, (device_id, kind) in cases.items():
            claim = dict(ownership[address])
            self.assertEqual(device_id, claim["device_id"], address)
            self.assertEqual(kind, claim["kind"], address)

    def test_router_id_is_owned_via_bgp_identifier(self) -> None:
        # 192.0.2.50 is claimed both as isp1's loopback and its BGP router
        # identifier; one device, one canonical claim (strongest kind).
        index = build_ownership_index([
            {
                "device_id": "frr:r1", "management_ip": "10.0.0.1",
                "metadata": {"bgp_router_id": "10.255.0.1"},
                "interfaces": [],
            },
        ])
        claim = index.owner_of("10.255.0.1")
        self.assertIsNotNone(claim)
        self.assertEqual("frr:r1", claim.device_id)
        self.assertEqual("router-id", claim.kind)

    def test_secondary_ips_are_claimed(self) -> None:
        index = build_ownership_index([
            {
                "device_id": "frr:r1", "management_ip": "10.0.0.1",
                "metadata": {},
                "interfaces": [
                    {
                        "name": "eth0", "ip_address": "10.0.0.1",
                        "metadata": {"secondary_ips": ("10.0.99.1",)},
                    },
                ],
            },
        ])
        claim = index.owner_of("10.0.99.1")
        self.assertEqual("secondary", claim.kind)
        self.assertEqual("eth0", claim.interface)

    def test_conflicting_claims_are_reported_never_guessed(self) -> None:
        index = build_ownership_index([
            {
                "device_id": "frr:r1", "management_ip": "10.0.0.1",
                "metadata": {}, "interfaces": [
                    {"name": "eth1", "ip_address": "10.99.0.1", "metadata": {}},
                ],
            },
            {
                "device_id": "frr:r2", "management_ip": "10.0.0.2",
                "metadata": {}, "interfaces": [
                    {"name": "eth1", "ip_address": "10.99.0.1", "metadata": {}},
                ],
            },
        ])
        self.assertIsNone(index.owner_of("10.99.0.1"))  # no guessing
        self.assertEqual(1, len(index.conflicts))
        self.assertEqual("10.99.0.1", index.conflicts[0].address)


# -- correlation (Parts 5, 5A, 6) --------------------------------------------------


class IspLabCorrelationTests(unittest.TestCase):
    """Part 6's manual validation, automated end to end."""

    def test_isp1_connects_to_both_edges_with_no_duplicates(self) -> None:
        _report, graph, snapshot = discover_isp_lab()
        self.assertEqual(3, snapshot.device_count)  # never a duplicate
        relationships = [
            dict(item) for item in snapshot.metadata["correlated_relationships"]
        ]
        pairs = {
            (item["left_device_id"], item["right_device_id"])
            for item in relationships
        }
        self.assertEqual(
            {("frr:edge1", "frr:isp1"), ("frr:edge2", "frr:isp1")}, pairs
        )
        for item in relationships:
            self.assertEqual("verified-routed", item["relationship_type"])
            kinds = {dict(e)["kind"] for e in item["evidence"]}
            # interface ownership + /30 match + BGP peer + description.
            self.assertEqual(
                {
                    "interface-ownership", "p2p-subnet",
                    "bgp-peer", "config-reference",
                },
                kinds,
            )
        self.assertEqual(
            0, snapshot.metadata["correlation"]["unresolved_observations"]
        )

    def test_correlated_interfaces_are_the_link_interfaces(self) -> None:
        _report, _graph, snapshot = discover_isp_lab()
        by_pair = {
            (dict(item)["left_device_id"], dict(item)["right_device_id"]):
            dict(item)
            for item in snapshot.metadata["correlated_relationships"]
        }
        edge1 = by_pair[("frr:edge1", "frr:isp1")]
        self.assertEqual("eth1", edge1["left_interface"])   # edge1 side
        self.assertEqual("eth1", edge1["right_interface"])  # isp1 side
        edge2 = by_pair[("frr:edge2", "frr:isp1")]
        self.assertEqual("eth1", edge2["left_interface"])
        self.assertEqual("eth2", edge2["right_interface"])

    def test_provenance_names_devices_commands_and_drivers(self) -> None:
        """Part 8A: users can always inspect WHY a relationship exists."""

        _report, _graph, snapshot = discover_isp_lab()
        item = dict(snapshot.metadata["correlated_relationships"][0])
        self.assertIn("frr:isp1", item["contributing_devices"])
        self.assertIn("show bgp summary", item["contributing_commands"])
        self.assertIn("show interface", item["contributing_commands"])
        self.assertIn("frr", item["contributing_drivers"])
        for evidence in item["evidence"]:
            evidence = dict(evidence)
            self.assertTrue(evidence["detail"])          # WHY, in words
            self.assertIn("priority", evidence)          # deterministic rank


class EngineUnitTests(unittest.TestCase):
    def device(self, device_id: str, hostname: str, mgmt: str, ifaces):
        return {
            "device_id": device_id, "hostname": hostname,
            "management_ip": mgmt, "metadata": {},
            "interfaces": [
                {
                    "name": name, "ip_address": address,
                    "description": description,
                    "metadata": (
                        {"prefix_length": prefix} if prefix else {}
                    ),
                }
                for name, address, prefix, description in ifaces
            ],
        }

    def test_p2p_subnet_alone_is_layer3(self) -> None:
        result = EvidenceCorrelationEngine().correlate(
            [
                self.device("frr:a", "a", "10.0.0.1",
                            [("eth1", "192.0.2.1", 30, None)]),
                self.device("frr:b", "b", "10.0.0.2",
                            [("eth1", "192.0.2.2", 30, None)]),
            ],
            [],
        )
        self.assertEqual(1, len(result.relationships))
        relationship = result.relationships[0]
        self.assertEqual("layer-3", relationship.relationship_type)
        self.assertEqual(85, relationship.confidence)  # P2 base, no bonus

    def test_wide_subnets_never_produce_p2p_evidence(self) -> None:
        result = EvidenceCorrelationEngine().correlate(
            [
                self.device("frr:a", "a", "10.0.0.1",
                            [("eth1", "10.99.0.1", 24, None)]),
                self.device("frr:b", "b", "10.0.0.2",
                            [("eth1", "10.99.0.2", 24, None)]),
            ],
            [],
        )
        self.assertEqual((), result.relationships)  # a /24 proves nothing

    def test_description_reference_is_weak_inferred_evidence(self) -> None:
        result = EvidenceCorrelationEngine().correlate(
            [
                self.device("frr:a", "a", "10.0.0.1",
                            [("eth1", "10.1.0.1", 24, "LINK-TO-b-CORE")]),
                self.device("frr:b", "b", "10.0.0.2",
                            [("eth1", "10.2.0.1", 24, None)]),
            ],
            [],
        )
        self.assertEqual(1, len(result.relationships))
        relationship = result.relationships[0]
        self.assertEqual("inferred", relationship.relationship_type)
        self.assertEqual(45, relationship.confidence)  # P8 base

    def test_ospf_adjacency_resolves_through_ownership(self) -> None:
        result = EvidenceCorrelationEngine().correlate(
            [
                self.device("frr:a", "a", "10.0.0.1",
                            [("eth1", "10.99.0.1", 24, None)]),
                self.device("frr:b", "b", "10.0.0.2",
                            [("eth1", "10.99.0.2", 24, None)]),
            ],
            [
                {
                    "local_device_id": "frr:a", "local_interface": "eth1",
                    "remote_hostname": "10.255.0.2", "remote_interface": None,
                    "remote_management_ip": None, "protocol": "ospf",
                    "metadata": {
                        "observation": "routing-adjacency",
                        "router_id": "10.255.0.2",
                        "adjacency_address": "10.99.0.2",
                        "source_command": "show ip ospf neighbor",
                    },
                },
            ],
        )
        self.assertEqual(1, len(result.relationships))
        relationship = result.relationships[0]
        kinds = {item.kind for item in relationship.evidence}
        self.assertIn("ospf-neighbor", kinds)
        self.assertIn("interface-ownership", kinds)
        self.assertEqual((), result.unresolved)

    def test_confidence_grows_with_evidence_and_never_exceeds_cap(self) -> None:
        base = self.device("frr:a", "a", "10.0.0.1",
                           [("eth1", "192.0.2.1", 30, "LINK-TO-b")])
        peer = self.device("frr:b", "b", "10.0.0.2",
                           [("eth1", "192.0.2.2", 30, None)])
        bgp_edge = {
            "local_device_id": "frr:a", "local_interface": "bgp",
            "remote_hostname": "192.0.2.2", "remote_interface": None,
            "remote_management_ip": None, "protocol": "bgp",
            "metadata": {
                "observation": "protocol-peer", "peer_address": "192.0.2.2",
                "source_command": "show bgp summary",
            },
        }
        engine = EvidenceCorrelationEngine()
        few = engine.correlate([base, peer], []).relationships[0]
        many = engine.correlate([base, peer], [bgp_edge]).relationships[0]
        self.assertGreater(many.confidence, few.confidence)
        self.assertLessEqual(many.confidence, CONFIDENCE_CAP)  # never > 95

    def test_stronger_evidence_decides_type_weaker_strengthens(self) -> None:
        """Part 5A: a link-layer announcement outranks a BGP session —
        the pair is verified-physical even though BGP also saw it."""

        devices = [
            self.device("ios:a", "a", "10.0.0.1", [("gi0/1", "10.9.0.1", 30, None)]),
            self.device("ios:b", "b", "10.0.0.2", [("gi0/1", "10.9.0.2", 30, None)]),
        ]
        edges = [
            {
                "local_device_id": "ios:a", "local_interface": "Gi0/1",
                "remote_hostname": "b", "remote_interface": "Gi0/1",
                "remote_management_ip": "10.0.0.2", "protocol": "cdp",
                "metadata": {
                    "observation": "link-layer",
                    "source_command": "show cdp neighbors detail",
                },
            },
            {
                "local_device_id": "ios:a", "local_interface": "bgp",
                "remote_hostname": "10.9.0.2", "remote_interface": None,
                "remote_management_ip": None, "protocol": "bgp",
                "metadata": {
                    "observation": "protocol-peer",
                    "peer_address": "10.9.0.2",
                    "source_command": "show bgp summary",
                },
            },
        ]
        result = EvidenceCorrelationEngine().correlate(devices, edges)
        self.assertEqual(1, len(result.relationships))
        relationship = result.relationships[0]
        self.assertEqual("verified-physical", relationship.relationship_type)
        kinds = {item.kind for item in relationship.evidence}
        self.assertIn("link-layer", kinds)
        self.assertIn("bgp-peer", kinds)  # strengthens, never overrides

    def test_unknown_stays_unknown_when_nothing_owns_the_identity(self) -> None:
        result = EvidenceCorrelationEngine().correlate(
            [self.device("frr:a", "a", "10.0.0.1", [])],
            [
                {
                    "local_device_id": "frr:a", "local_interface": "eth1",
                    "remote_hostname": "10.255.0.9", "remote_interface": None,
                    "remote_management_ip": None, "protocol": "ospf",
                    "metadata": {
                        "observation": "routing-adjacency",
                        "adjacency_address": "10.77.0.9",
                        "source_command": "show ip ospf neighbor",
                    },
                },
            ],
        )
        self.assertEqual((), result.relationships)
        self.assertEqual(1, len(result.unresolved))
        self.assertIn("insufficient evidence", result.unresolved[0].reason)


# -- reconciliation without rediscovery (Part 7) -----------------------------------


class RepeatedReconciliationTests(unittest.TestCase):
    def test_new_evidence_resolves_provisional_peers_without_rediscovery(
        self,
    ) -> None:
        engine = EvidenceCorrelationEngine()
        isp1 = {
            "device_id": "frr:isp1", "hostname": "isp1",
            "management_ip": "172.20.20.7", "metadata": {},
            "interfaces": [
                {"name": "eth1", "ip_address": "192.0.2.65",
                 "description": None, "metadata": {"prefix_length": 30}},
            ],
        }
        bgp_edge = {
            "local_device_id": "frr:isp1", "local_interface": "bgp",
            "remote_hostname": "192.0.2.66", "remote_interface": None,
            "remote_management_ip": None, "protocol": "bgp",
            "metadata": {
                "observation": "protocol-peer", "peer_address": "192.0.2.66",
                "source_command": "show bgp summary",
            },
        }
        first = engine.correlate([isp1], [bgp_edge])
        self.assertEqual((), first.relationships)
        self.assertEqual(1, len(first.unresolved))  # provisional peer

        edge1 = {
            "device_id": "frr:edge1", "hostname": "edge1",
            "management_ip": "172.20.20.8", "metadata": {},
            "interfaces": [
                {"name": "eth1", "ip_address": "192.0.2.66",
                 "description": None, "metadata": {"prefix_length": 30}},
            ],
        }
        # Same observations, one new device — NO rediscovery of isp1.
        second = engine.correlate([isp1, edge1], [bgp_edge])
        self.assertEqual(1, len(second.relationships))
        self.assertEqual((), second.unresolved)
        self.assertEqual(
            "verified-routed", second.relationships[0].relationship_type
        )


# -- deterministic topology + parallel completion order ----------------------------


class DeterminismTests(unittest.TestCase):
    def test_topology_is_deterministic_across_runs_and_worker_counts(
        self,
    ) -> None:
        _r1, _g1, sequential = discover_isp_lab(workers=1)
        _r2, _g2, parallel = discover_isp_lab(workers=8)
        _r3, _g3, repeat = discover_isp_lab(workers=8)
        self.assertEqual(sequential.snapshot_id, parallel.snapshot_id)
        self.assertEqual(parallel.snapshot_id, repeat.snapshot_id)


# -- presentation (Part 9) ----------------------------------------------------------


class PresentationTests(unittest.TestCase):
    def test_fused_relationships_render_without_phantom_nodes(self) -> None:
        _report, _graph, snapshot = discover_isp_lab()
        renderer = TopologyRenderer(snapshot)
        elements = renderer.elements()
        kinds = {node["data"]["kind"] for node in elements["nodes"]}
        self.assertEqual({"discovered"}, kinds)  # no unresolved phantoms
        self.assertEqual(3, len(elements["nodes"]))
        self.assertEqual(2, len(elements["edges"]))
        for edge in elements["edges"]:
            data = edge["data"]
            self.assertEqual("verified-routed", data["relationship"])
            self.assertEqual("verified-routed", data["fused_type"])
            self.assertEqual(95, data["confidence"])
            self.assertGreaterEqual(len(data["evidence"]), 4)
            self.assertIn("show bgp summary", data["contributing_commands"])

    def test_viewer_explains_why_on_edge_click(self) -> None:
        _report, _graph, snapshot = discover_isp_lab()
        html = TopologyRenderer(snapshot).render()
        self.assertIn("Why this relationship exists", html)
        self.assertIn("edgeDetails", html)
        self.assertIn('edge[relationship = "verified-routed"]', html)
        summary = TopologyRenderer(snapshot).relationship_summary()
        self.assertEqual(2, summary["verified_routed"])
        self.assertEqual(0, summary["unresolved_peers"])

    def test_rendering_stays_deterministic(self) -> None:
        _report, _graph, snapshot = discover_isp_lab()
        first = TopologyRenderer(snapshot).elements()
        second = TopologyRenderer(snapshot).elements()
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )


# -- shared discovery pipeline (Parts 1 + 10) ---------------------------------------


class SharedPipelineTests(unittest.TestCase):
    def test_plan_execution_forwards_workers_and_reachability(self) -> None:
        source = inspect.getsource(run_discovery_plan)
        self.assertIn("workers=resolved_workers", source)
        self.assertIn("reachability=reachability", source)

    def test_cidr_and_seed_modes_produce_identical_devices(self) -> None:
        """Part 10: CIDR discovery uses the same worker pool,
        reachability gate, pipeline, normalization, and correlation as
        Seed discovery — same lab, same canonical result."""

        alive = set(ISP_ADDRESSES)

        class FakeReach:
            def is_reachable(self, host):
                return host in alive

        # Seed mode: the three lab addresses as explicit seeds.
        seed_plan = resolve_plan(
            "multiple-seeds",
            seed=ISP_ADDRESSES[0], seeds=ISP_ADDRESSES[1:],
            policy="fast",
        )
        dead = frozenset(
            f"172.20.20.{i}" for i in range(1, 15)
            if f"172.20.20.{i}" not in alive
        )

        def network():
            return ScriptedNetwork(
                {
                    "172.20.20.7": isp1_outputs(),
                    "172.20.20.8": edge_outputs(
                        "edge1", "172.20.20.8", "192.0.2.66"
                    ),
                    "172.20.20.9": edge_outputs(
                        "edge2", "172.20.20.9", "192.0.2.70"
                    ),
                },
                unreachable=dead,
            )

        _r, _g, seed_snapshot, _c, seed_summary = run_discovery_plan(
            seed_plan, network().transport_factory,
            reachability=FakeReach(),
        )

        # CIDR mode: the whole /28 management network; only the three
        # lab devices answer the reachability probe.
        cidr_plan = resolve_plan(
            "management-network", cidr="172.20.20.0/28", policy="fast",
        )
        cidr_net = network()
        _r2, _g2, cidr_snapshot, candidates, cidr_summary = run_discovery_plan(
            cidr_plan, cidr_net.transport_factory,
            reachability=FakeReach(),
        )

        self.assertEqual(3, seed_snapshot.device_count)
        self.assertEqual(3, cidr_snapshot.device_count)
        self.assertEqual(
            {d["hostname"] for d in seed_snapshot.devices},
            {d["hostname"] for d in cidr_snapshot.devices},
        )
        # Identical fused knowledge from both entry modes.
        self.assertEqual(
            seed_snapshot.metadata["correlated_relationships"],
            cidr_snapshot.metadata["correlated_relationships"],
        )
        # The reachability gate kept dead addresses away from SSH.
        for address in dead:
            self.assertNotIn(address, cidr_net.connect_attempts)
        self.assertEqual(3, cidr_summary["discovered"])
        self.assertEqual(11, cidr_summary["unreachable"])


if __name__ == "__main__":
    unittest.main()
