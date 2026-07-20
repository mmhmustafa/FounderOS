"""BGP evidence: reading the state, and keeping it through fusion.

Two defects kept the BGP autonomous-systems view empty over a fully
meshed estate, both found by looking at the real lab:

1. FRR's `show bgp summary` appends a Desc column, so taking the last
   token read the neighbor DESCRIPTION as the session state — every
   session recorded as "ebgp-mumbai-edge", none ever "established",
   and the prefix count thrown away.
2. Fusion reports a relationship's STRONGEST evidence as its type. A
   BGP peering that also had routed evidence became "verified-routed",
   and the per-protocol views — which select on type — matched nothing.
"""

from __future__ import annotations

import unittest

from founderos_atlas.correlation.engine import EvidenceCorrelationEngine
from founderos_atlas.correlation.models import (
    CorrelatedRelationship,
    RelationshipEvidence,
)
from founderos_atlas.routing.evidence import bgp_sessions_from_summary
from founderos_atlas.visualization.renderer import (
    _edge_is_protocol,
    _protocol_groups,
)


# Real output from the lab's chennai-edge, Desc column and all.
FRR_SUMMARY = """IPv4 Unicast Summary (VRF default):
BGP router identifier 10.250.3.1, local AS number 65040 vrf-id 0
Peers 3, using 2151 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
192.168.100.9   4      65010      1190      1189        0    0    0 19:41:08            9       12 EBGP-mumbai-edge
192.168.100.17  4      65020      1188      1189        0    0    0 19:41:33            9       12 EBGP-delhi-edge
"""

IOS_SUMMARY = """BGP router identifier 10.0.0.1, local AS number 65001
Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.0.2        4        65002     120     118        5    0    0 00:50:12        3
10.0.0.3        4        65003      12      11        0    0    0 00:00:22  Active
"""

EOS_SUMMARY = """BGP summary information for VRF default
Router identifier 10.1.1.1, local AS number 65100
Neighbor  V AS   MsgRcvd MsgSent InQ OutQ Up/Down  State  PfxRcd PfxAcc
10.1.1.2  4 65200   500     499    0    0 01:02:03 Estab   7      7
"""


class SummaryParsingTests(unittest.TestCase):
    def test_the_description_column_is_not_the_state(self) -> None:
        sessions = bgp_sessions_from_summary(
            FRR_SUMMARY, source_command="show bgp summary"
        )
        self.assertEqual(2, len(sessions))
        for session in sessions:
            self.assertEqual("established", session.state)
            self.assertEqual(9, session.accepted_prefixes)
        self.assertEqual(
            ["65010", "65020"], [s.remote_as for s in sessions]
        )

    def test_a_state_word_is_read_as_that_state(self) -> None:
        sessions = bgp_sessions_from_summary(
            IOS_SUMMARY, source_command="show ip bgp summary"
        )
        self.assertEqual(("established", 3), (sessions[0].state,
                                              sessions[0].accepted_prefixes))
        self.assertEqual("active", sessions[1].state)
        self.assertIsNone(sessions[1].accepted_prefixes)

    def test_a_separate_prefix_column_is_still_read(self) -> None:
        """EOS prints State and PfxRcd as different columns."""

        sessions = bgp_sessions_from_summary(
            EOS_SUMMARY, source_command="show ip bgp summary"
        )
        self.assertEqual("established", sessions[0].state)
        self.assertEqual(7, sessions[0].accepted_prefixes)

    def test_output_without_a_header_still_parses(self) -> None:
        sessions = bgp_sessions_from_summary(
            "  10.9.9.9 4 65999 10 10 0 0 0 00:01:00 4\n",
            source_command="show bgp summary",
        )
        self.assertEqual(("established", 4), (sessions[0].state,
                                              sessions[0].accepted_prefixes))

    def test_an_unreadable_state_is_never_called_established(self) -> None:
        sessions = bgp_sessions_from_summary(
            "Neighbor V AS Up/Down State/PfxRcd\n"
            "10.0.0.9 4 65001 00:01:00 whatever\n",
            source_command="show bgp summary",
        )
        self.assertNotEqual("established", sessions[0].state)
        self.assertIsNone(sessions[0].accepted_prefixes)


class ContributingProtocolTests(unittest.TestCase):
    def test_protocols_are_derived_from_the_evidence(self) -> None:
        relationship = CorrelatedRelationship(
            left_device_id="a", right_device_id="b",
            left_interface="bgp", right_interface="eth4",
            relationship_type="verified-routed",
            confidence=95,
            evidence=(
                RelationshipEvidence(
                    priority=1, kind="interface-ownership",
                    detail="owned", observed_by="a", protocol="bgp",
                ),
            ),
        )
        self.assertEqual(("bgp",), relationship.contributing_protocols)
        self.assertIn("contributing_protocols", relationship.to_dict())

    def test_evidence_without_a_protocol_contributes_none(self) -> None:
        relationship = CorrelatedRelationship(
            left_device_id="a", right_device_id="b",
            left_interface=None, right_interface=None,
            relationship_type="verified-physical",
            confidence=95,
            evidence=(
                RelationshipEvidence(
                    priority=1, kind="interface-ownership",
                    detail="subnet", observed_by="a",
                ),
            ),
        )
        self.assertEqual((), relationship.contributing_protocols)

    def test_the_engine_records_the_observing_protocol(self) -> None:
        devices = [
            {"device_id": "d1", "hostname": "edge-a", "interfaces": [
                {"name": "eth4", "ip_address": "10.0.0.1"}]},
            {"device_id": "d2", "hostname": "edge-b", "interfaces": [
                {"name": "eth4", "ip_address": "10.0.0.2"}]},
        ]
        edges = [{
            "local_device_id": "d1", "local_interface": "bgp",
            "remote_hostname": "10.0.0.2", "remote_interface": None,
            "protocol": "bgp",
            "metadata": {"observation": "protocol-peer",
                         "peer_address": "10.0.0.2",
                         "source_command": "show bgp summary"},
        }]
        result = EvidenceCorrelationEngine().correlate(devices, edges)
        self.assertTrue(result.relationships)
        self.assertIn(
            "bgp", result.relationships[0].contributing_protocols,
        )


class ProtocolViewSelectionTests(unittest.TestCase):
    def test_a_bgp_link_survives_being_typed_by_stronger_evidence(self) -> None:
        """The regression: fused to verified-routed, the BGP peering
        matched nothing and the AS view drew zero links across a fully
        meshed estate."""

        data = {
            "protocol": "interface-ownership",
            "fused_type": "verified-routed",
            "link_tag": "routed",
            "protocols": ["bgp"],
        }
        self.assertTrue(_edge_is_protocol(data, "bgp"))
        self.assertFalse(_edge_is_protocol(data, "ospf"))

    def test_ospf_selection_is_unchanged(self) -> None:
        data = {"protocol": "interface-ownership", "fused_type": "ospf",
                "link_tag": "OSPF", "protocols": ["ospf"]}
        self.assertTrue(_edge_is_protocol(data, "ospf"))
        self.assertFalse(_edge_is_protocol(data, "bgp"))

    def test_a_link_with_no_protocol_evidence_matches_neither(self) -> None:
        data = {"protocol": "link-layer", "fused_type": "verified-physical",
                "link_tag": "", "protocols": []}
        self.assertFalse(_edge_is_protocol(data, "bgp"))
        self.assertFalse(_edge_is_protocol(data, "ospf"))

    def test_older_snapshots_without_the_field_still_work(self) -> None:
        data = {"protocol": "bgp", "fused_type": "verified-routed",
                "link_tag": "routed"}
        self.assertTrue(_edge_is_protocol(data, "bgp"))


class DomainLabelTests(unittest.TestCase):
    """The VRF earns its place in the label only when it says something.

    On a single-VRF estate every domain read "BGP default · AS 65010" —
    the same word on each, pushing the number that actually identifies
    the domain to the end.
    """

    EMPTY = {"nodes": [], "edges": []}

    def labels(self, protocol, members):
        groups, _ = _protocol_groups(
            protocol=protocol, members=members,
            elements=self.EMPTY, relevant_edges=set(),
        )
        return sorted(group["label"] for group in groups)

    def test_a_single_default_vrf_is_not_named(self) -> None:
        self.assertEqual(
            ["BGP AS 65010", "BGP AS 65020"],
            self.labels("bgp", {("default", "65010"): {"a"},
                                ("default", "65020"): {"b"}}),
        )

    def test_more_than_one_vrf_is_named_because_it_identifies(self) -> None:
        self.assertEqual(
            ["BGP CORP · AS 65020", "BGP default · AS 65010"],
            self.labels("bgp", {("default", "65010"): {"a"},
                                ("CORP", "65020"): {"b"}}),
        )

    def test_a_single_non_default_vrf_is_named(self) -> None:
        """Everything living in one named VRF is a deliberate choice,
        not a default worth hiding."""

        self.assertEqual(
            ["BGP CORP · AS 65010"],
            self.labels("bgp", {("CORP", "65010"): {"a"}}),
        )

    def test_ospf_areas_follow_the_same_rule(self) -> None:
        self.assertEqual(
            ["OSPF Area 0.0.0.0"],
            self.labels("ospf", {("default", "1", "0.0.0.0"): {"a"}}),
        )
        self.assertEqual(
            ["OSPF CORP · Area 0.0.0.1", "OSPF default · Area 0.0.0.0"],
            self.labels("ospf", {("default", "1", "0.0.0.0"): {"a"},
                                 ("CORP", "1", "0.0.0.1"): {"b"}}),
        )

    def test_the_vrf_is_still_carried_in_the_data(self) -> None:
        """Only the label changes — anything reading the attribute (the
        details panel, exports) still gets the VRF."""

        groups, _ = _protocol_groups(
            protocol="bgp", members={("default", "65010"): {"a"}},
            elements=self.EMPTY, relevant_edges=set(),
        )
        self.assertEqual("default", groups[0]["vrf"])
        self.assertEqual("65010", groups[0]["local_as"])


if __name__ == "__main__":
    unittest.main()
