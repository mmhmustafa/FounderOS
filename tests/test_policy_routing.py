"""Policy-based routing as canonical facts.

The RIB answers "where does this PREFIX go". Policy routing answers
"where does THIS FLOW go", and it answers FIRST. A path verdict built on
longest-prefix match alone is not merely incomplete on a device with PBR
— it can be confidently wrong. These tests pin the three grammars onto
one model, and pin the honesty rule that matters most: a rule Atlas
cannot decide must never be rounded down to "does not apply".
"""

from __future__ import annotations

import unittest

from founderos_atlas.routing.policy import (
    PolicyRoute,
    first_matching_policy,
    parse_fortios_policy_routes,
    parse_ip_policy_bindings,
    parse_iproute2_rules,
    parse_route_map_policy_routes,
    policy_route_dicts,
)

FORTIOS = """
config router policy
    edit 1
        set input-device "port3"
        set src "10.10.0.0 255.255.0.0"
        set dst "0.0.0.0 0.0.0.0"
        set protocol 6
        set start-port 443
        set end-port 443
        set gateway 192.0.2.1
        set output-device "port1"
    next
    edit 2
        set input-device "port3"
        set src "10.20.0.0 255.255.0.0"
        set gateway 192.0.2.9
        set output-device "port2"
        set status disable
    next
    edit 3
        set protocol 0
        set gateway 198.51.100.1
    next
end
"""

IPROUTE2 = """
0:\tfrom all lookup local
100:\tfrom 10.10.0.0/16 lookup 200
110:\tfrom 10.20.5.5 iif eth2 lookup vpn
120:\tfrom all to 203.0.113.0/24 lookup 300
32766:\tfrom all lookup main
32767:\tfrom all blackhole
"""

ROUTE_MAP = """
route-map PBR-BRANCH, permit, sequence 10
  Match clauses:
    ip address prefix-lists: BRANCH-USERS
  Set clauses:
    ip next-hop 192.0.2.5
  Policy routing matches: 0 packets, 0 bytes
route-map PBR-BRANCH, deny, sequence 20
  Match clauses:
  Set clauses:
  Policy routing matches: 0 packets, 0 bytes
route-map PBR-UNUSED, permit, sequence 10
  Match clauses:
  Set clauses:
    ip next-hop 198.51.100.9
  Policy routing matches: 0 packets, 0 bytes
"""

IP_POLICY = """
Interface      Route map
GigabitEthernet0/1 PBR-BRANCH
GigabitEthernet0/2 PBR-BRANCH
"""


class FortiOsPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policies = parse_fortios_policy_routes(FORTIOS)

    def test_every_entry_is_read(self) -> None:
        self.assertEqual((1, 2, 3), tuple(p.sequence for p in self.policies))

    def test_the_match_and_the_action_are_both_captured(self) -> None:
        first = self.policies[0]
        self.assertEqual("10.10.0.0/16", first.source)
        self.assertEqual("tcp", first.protocol)
        self.assertEqual((443,), first.destination_ports)
        self.assertEqual("port3", first.ingress_interface)
        self.assertEqual("192.0.2.1", first.next_hop)
        self.assertEqual("port1", first.egress_interface)

    def test_a_quad_zero_destination_is_not_a_constraint(self) -> None:
        """FortiOS writes "any destination" as 0.0.0.0/0. Kept as that
        prefix it still matches everything, which is correct — but it must
        not be mistaken for a rule that only matches the default route."""

        self.assertEqual("0.0.0.0/0", self.policies[0].destination)
        self.assertTrue(_address_matches(self.policies[0], "8.8.8.8"))

    def test_protocol_zero_means_any_protocol(self) -> None:
        # Not "protocol number 0" — reading it literally would make the
        # rule match nothing a real flow could declare.
        self.assertIsNone(self.policies[2].protocol)

    def test_a_disabled_entry_is_kept_and_marked(self) -> None:
        """Dropping it would lose the fact that the operator configured
        it; treating it as live would divert a flow the device does not."""

        self.assertTrue(self.policies[1].disabled)
        self.assertIs(False, self.policies[1].matches(
            source_address="10.20.0.5", ingress_interface="port3",
        ))

    def test_an_unnamed_protocol_number_keeps_its_number(self) -> None:
        parsed = parse_fortios_policy_routes(
            "config router policy\n edit 1\n set protocol 47\n next\nend"
        )
        self.assertEqual("47", parsed[0].protocol)


class IpRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policies = parse_iproute2_rules(IPROUTE2)

    def test_lookup_rules_are_read_in_priority_order(self) -> None:
        self.assertEqual(
            (0, 100, 110, 120, 32766),
            tuple(p.sequence for p in self.policies),
        )

    def test_from_all_is_unconstrained_not_a_prefix(self) -> None:
        """"from all" is iproute2 for "any source". Parsed as a prefix it
        would be nonsense, and parsed as a literal it would match nothing."""

        self.assertIsNone(self.policies[0].source)

    def test_a_bare_address_becomes_a_host_prefix(self) -> None:
        self.assertEqual("10.20.5.5/32", self.policies[2].source)
        self.assertEqual("eth2", self.policies[2].ingress_interface)

    def test_a_rule_selects_a_table_and_names_no_next_hop(self) -> None:
        """The rule picks a TABLE; the routes in it choose the gateway.
        Reporting a next hop here would invent one the rule never named."""

        rule = self.policies[1]
        self.assertEqual("200", rule.table)
        self.assertIsNone(rule.next_hop)
        self.assertFalse(rule.directs_traffic())

    def test_a_non_lookup_rule_is_skipped_rather_than_guessed(self) -> None:
        # The blackhole rule has no table to consult.
        self.assertNotIn(32767, [p.sequence for p in self.policies])


class RouteMapTests(unittest.TestCase):
    def test_bindings_are_read_without_the_header(self) -> None:
        bindings = parse_ip_policy_bindings(IP_POLICY)
        self.assertEqual(
            {"GigabitEthernet0/1": "PBR-BRANCH",
             "GigabitEthernet0/2": "PBR-BRANCH"},
            bindings,
        )

    def test_a_clause_is_emitted_per_interface_that_uses_it(self) -> None:
        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        seq10 = [p for p in policies if p.sequence == 10 and not p.disabled]
        self.assertEqual(2, len(seq10))
        self.assertEqual(
            ["GigabitEthernet0/1", "GigabitEthernet0/2"],
            sorted(p.ingress_interface for p in seq10),
        )
        self.assertEqual("192.0.2.5", seq10[0].next_hop)

    def test_an_unbound_route_map_forwards_nothing(self) -> None:
        """A route-map no interface references is configuration the device
        is not applying. Reporting it as policy routing would overstate
        what the device does to traffic."""

        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        self.assertEqual(
            [], [p for p in policies if "PBR-UNUSED" in (p.name or "")]
        )

    def test_with_no_bindings_at_all_nothing_is_claimed(self) -> None:
        self.assertEqual((), parse_route_map_policy_routes(ROUTE_MAP))

    def test_an_unreadable_match_makes_the_rule_undecidable(self) -> None:
        """The clause matches prefix-list BRANCH-USERS, whose CONTENTS
        Atlas never captured. Modelled as "no constraint" the rule would
        appear to match every flow and divert the lot — claiming the
        device does something it may not. It stays permanently
        unconfirmable instead."""

        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        clause = next(p for p in policies if p.sequence == 10)
        self.assertEqual(("ip address BRANCH-USERS",), clause.unresolved_matches)
        self.assertIsNone(clause.matches(
            source_address="10.10.1.1", destination_address="8.8.8.8",
            protocol="tcp", destination_port=443,
            ingress_interface="GigabitEthernet0/1",
        ))

    def test_an_unreadable_match_can_still_be_ruled_out(self) -> None:
        # Undecidable is not the same as unfalsifiable: a contradiction on
        # a criterion Atlas CAN read still rules the rule out.
        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        clause = next(p for p in policies if p.sequence == 10)
        self.assertIs(False, clause.matches(
            ingress_interface="GigabitEthernet0/9",
        ))

    def test_the_unreadable_criterion_is_named_in_the_description(self) -> None:
        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        text = next(p for p in policies if p.sequence == 10).describe()
        self.assertIn("BRANCH-USERS", text)
        self.assertIn("not captured", text)

    def test_a_deny_clause_means_use_the_routing_table(self) -> None:
        # In PBR, deny is "do not policy-route this" — NOT "drop it".
        policies = parse_route_map_policy_routes(
            ROUTE_MAP, bindings=parse_ip_policy_bindings(IP_POLICY)
        )
        denied = [p for p in policies if p.sequence == 20]
        self.assertTrue(denied)
        self.assertTrue(all(p.disabled for p in denied))


class MatchingTests(unittest.TestCase):
    """The honesty rule: undecidable is not "no"."""

    def setUp(self) -> None:
        self.rule = PolicyRoute(
            sequence=1, source="10.10.0.0/16", protocol="tcp",
            destination_ports=(443,), ingress_interface="port3",
            next_hop="192.0.2.1",
        )

    def test_a_fully_declared_flow_matches_definitely(self) -> None:
        self.assertIs(True, self.rule.matches(
            source_address="10.10.1.1", protocol="tcp",
            destination_port=443, ingress_interface="port3",
        ))

    def test_a_contradicted_flow_definitely_does_not_match(self) -> None:
        self.assertIs(False, self.rule.matches(
            source_address="192.168.1.1", protocol="tcp",
            destination_port=443, ingress_interface="port3",
        ))

    def test_an_undeclared_property_is_unknown_not_false(self) -> None:
        """The whole point. A trace that never said which source address
        it starts from cannot know whether a source-matched rule applies.
        Rounding that to "does not apply" is how a flow gets reported as
        following the RIB while the device diverts it elsewhere."""

        self.assertIsNone(self.rule.matches(
            protocol="tcp", destination_port=443, ingress_interface="port3",
        ))

    def test_a_contradiction_beats_an_unknown(self) -> None:
        # One field cannot be told, but another rules the flow out
        # outright — that is a definite no, not an unknown.
        self.assertIs(False, self.rule.matches(
            protocol="udp", ingress_interface="port3",
        ))

    def test_first_match_wins_and_unknowns_are_reported(self) -> None:
        rules = [
            PolicyRoute(sequence=10, source="10.10.0.0/16",
                        next_hop="192.0.2.1"),
            PolicyRoute(sequence=20, next_hop="198.51.100.1"),
        ]
        chosen, undetermined = first_matching_policy(rules)
        # Nothing declared: rule 10 cannot be decided, so rule 20 (which
        # constrains nothing) wins — but rule 10 is surfaced, because it
        # might have diverted the flow.
        self.assertEqual(20, chosen.sequence)
        self.assertEqual((10,), tuple(r.sequence for r in undetermined))

    def test_a_decided_match_short_circuits_later_rules(self) -> None:
        rules = [
            PolicyRoute(sequence=10, source="10.10.0.0/16",
                        next_hop="192.0.2.1"),
            PolicyRoute(sequence=20, next_hop="198.51.100.1"),
        ]
        chosen, undetermined = first_matching_policy(
            rules, source_address="10.10.9.9"
        )
        self.assertEqual(10, chosen.sequence)
        self.assertEqual((), undetermined)


class SerialisationTests(unittest.TestCase):
    def test_dicts_are_ordered_for_evaluation(self) -> None:
        dicts = policy_route_dicts([
            PolicyRoute(sequence=30), PolicyRoute(sequence=10),
        ])
        self.assertEqual([10, 30], [d["sequence"] for d in dicts])

    def test_a_description_reads_as_the_rule_does(self) -> None:
        rule = PolicyRoute(
            sequence=1, source="10.10.0.0/16", protocol="tcp",
            destination_ports=(443,), ingress_interface="port3",
            next_hop="192.0.2.1", egress_interface="port1",
        )
        text = rule.describe()
        self.assertIn("in port3", text)
        self.assertIn("from 10.10.0.0/16", text)
        self.assertIn("TCP/443", text)
        self.assertIn("via 192.0.2.1", text)

    def test_a_table_rule_says_so_rather_than_claiming_a_hop(self) -> None:
        rule = PolicyRoute(sequence=100, table="200")
        self.assertIn("table 200", rule.describe())


def _address_matches(rule: PolicyRoute, address: str) -> bool:
    return rule.matches(
        source_address="10.10.1.1", destination_address=address,
        protocol="tcp", destination_port=443, ingress_interface="port3",
    ) is True


if __name__ == "__main__":
    unittest.main()
