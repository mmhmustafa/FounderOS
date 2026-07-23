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
    frr_pbr_is_readable,
    parse_fortios_policy_routes,
    parse_frr_pbr_interfaces,
    parse_frr_pbr_maps,
    parse_ip_policy_bindings,
    parse_iproute2_rule_commands,
    parse_iproute2_rules,
    parse_junos_filter_forwarding,
    parse_panos_pbf_rules,
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


RULE_COMMANDS = """
#!/bin/sh
# generated by scripts/generate-multicity.py
ip route add 10.9.0.0/16 via 10.0.0.2 table 200
ip rule add from 10.10.0.0/16 lookup 200 pref 100
ip rule add from 10.20.5.5 iif eth2 table vpn priority 110
ip rule add to 203.0.113.0/24 lookup 300      # egress steering
ip rule del from 10.30.0.0/16 lookup 400
ip rule add from all lookup main
iptables -A FORWARD -j ACCEPT
"""


class RuleCommandTests(unittest.TestCase):
    """Rules as CONFIGURED, for appliances that expose no `ip rule`.

    A fixed command allow-list is common on firewall CLIs — the lab's own
    rejects everything outside its list. The configuration the box booted
    with is already captured, and the rules written there are what it is
    running: reading them is evidence, where inventing a command the
    device would refuse is not.
    """

    def setUp(self) -> None:
        self.policies = parse_iproute2_rule_commands(RULE_COMMANDS)

    def test_rules_are_read_from_the_written_form(self) -> None:
        self.assertEqual(4, len(self.policies))
        first = next(p for p in self.policies if p.sequence == 100)
        self.assertEqual("10.10.0.0/16", first.source)
        self.assertEqual("200", first.table)

    def test_preference_is_read_however_it_is_spelled(self) -> None:
        # pref, priority — iproute2 accepts both for the same thing.
        self.assertEqual(
            "vpn", next(p for p in self.policies if p.sequence == 110).table
        )

    def test_a_rule_without_a_preference_gets_the_kernel_default(self) -> None:
        """Not zero. Collapsing an unnumbered rule to the front would make
        it win evaluations the kernel would give to something else."""

        catch_all = [p for p in self.policies if p.source is None
                     and p.table == "main"]
        self.assertEqual([32766], [p.sequence for p in catch_all])

    def test_a_deletion_is_not_read_as_a_rule(self) -> None:
        # The same line with one word changed means the opposite thing.
        self.assertNotIn("400", [p.table for p in self.policies])

    def test_route_and_firewall_lines_are_not_mistaken_for_rules(self) -> None:
        self.assertTrue(all(p.table is not None for p in self.policies))
        self.assertNotIn(None, [p.sequence for p in self.policies])

    def test_a_trailing_comment_is_not_read_into_the_rule(self) -> None:
        steered = next(p for p in self.policies if p.destination)
        self.assertEqual("203.0.113.0/24", steered.destination)
        self.assertEqual("300", steered.table)

    def test_a_config_with_no_rules_yields_none_rather_than_failing(self) -> None:
        self.assertEqual((), parse_iproute2_rule_commands(
            "#!/bin/sh\nip route add default via 10.0.0.1\n"
        ))


class LinuxFirewallCaptureTests(unittest.TestCase):
    """The lab firewall's CLI answers a FIXED list and rejects the rest.

    There is no `ip rule` to ask it for, so the rules are read from the
    configuration it already publishes. Asking a device a command it will
    refuse, and recording the refusal as "no policy routing", would be a
    guess wearing the clothes of evidence.
    """

    def _discover(self, running_config: str | None):
        from tests.test_polyglot_drivers import FakeTransport
        from founderos_atlas.platforms.drivers.atlaslab_firewall import (
            AtlasLabFirewallDriver,
        )

        outputs = {
            "show version": "AtlasLab firewall (chennai-fw) on Linux 6.1",
            "show interfaces": "eth0  UP  172.20.20.18/24\n",
            "show route": "default via 172.20.20.1 dev eth0\n",
            "show firewall rules": "",
            "show lldp neighbors": "",
            "show log": "",
        }
        if running_config is not None:
            outputs["show running-config"] = running_config
        transport = FakeTransport(outputs)
        return AtlasLabFirewallDriver().discover(
            transport, management_ip_hint="172.20.20.18",
            probe_output=outputs["show version"],
        )

    def test_rules_in_the_booted_config_are_captured(self) -> None:
        discovery = self._discover(
            "#!/bin/sh\n"
            "ip rule add from 10.10.0.0/16 lookup 200 pref 100\n"
            "ip route add default via 10.0.0.1 table 200\n"
        )
        metadata = discovery.result.device.metadata
        self.assertTrue(metadata["policy_routes_captured"])
        rule = metadata["policy_routes"][0]
        self.assertEqual("10.10.0.0/16", rule["source"])
        self.assertEqual("200", rule["table"])
        # A rule selects a TABLE; the routes in it choose the gateway.
        self.assertIsNone(rule["next_hop"])

    def test_a_firewall_with_no_rules_records_the_absence(self) -> None:
        discovery = self._discover("#!/bin/sh\niptables -P FORWARD DROP\n")
        metadata = discovery.result.device.metadata
        self.assertTrue(metadata["policy_routes_captured"])
        self.assertEqual((), tuple(metadata["policy_routes"]))


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


JUNOS_SET = """
set firewall family inet filter f1 term t1 from source-address 10.1.0.50/32
set firewall family inet filter f1 term t1 from protocol tcp
set firewall family inet filter f1 term t1 from destination-port 443
set firewall family inet filter f1 term t1 then routing-instance vrf01
set firewall family inet filter f1 term t2 then accept
set firewall family inet filter unused term t1 from source-address 10.9.0.0/16
set firewall family inet filter unused term t1 then routing-instance vrf99
set interfaces ge-0/0/0 unit 0 family inet filter input f1
set interfaces ge-0/0/3 unit 0 family inet filter input f1
"""

PANOS_PBF = """\
vsys1 {
  pbf-to-isp2 {
    id 1;
    from trust;
    source 10.10.0.0/16;
    destination any;
    user any;
    application/service any;
    action forward;
    symmetric-return no;
    forwarding-egress-IF/VSYS ethernet1/3;
    next-hop 192.0.2.9;
    terminal yes;
  }

  no-pbf-internal {
    id 2;
    from trust;
    source any;
    destination 10.0.0.0/8;
    action no-pbf;
    terminal yes;
  }
}
"""


class JunosFilterForwardingTests(unittest.TestCase):
    """Junos has no route-map: a firewall FILTER term sends traffic to a
    routing instance. The clauses live in the configuration, because
    `show firewall filter` reports counters, not rules."""

    def setUp(self) -> None:
        self.policies = parse_junos_filter_forwarding(JUNOS_SET)

    def test_a_term_is_emitted_per_interface_the_filter_is_applied_to(self) -> None:
        self.assertEqual(2, len(self.policies))
        self.assertEqual(
            ["ge-0/0/0.0", "ge-0/0/3.0"],
            sorted(p.ingress_interface for p in self.policies),
        )

    def test_the_match_and_the_instance_are_captured(self) -> None:
        rule = self.policies[0]
        self.assertEqual("10.1.0.50/32", rule.source)
        self.assertEqual("tcp", rule.protocol)
        self.assertEqual((443,), rule.destination_ports)
        self.assertEqual("vrf01", rule.table)

    def test_an_instance_names_a_table_and_no_next_hop(self) -> None:
        # The instance's own routes choose the gateway; claiming one here
        # would invent a hop the configuration never named.
        self.assertIsNone(self.policies[0].next_hop)
        self.assertFalse(self.policies[0].directs_traffic())

    def test_a_term_that_does_not_redirect_is_not_policy_routing(self) -> None:
        # `then accept` belongs to the firewall model, not this one.
        self.assertTrue(all(p.table for p in self.policies))

    def test_a_filter_applied_to_no_interface_forwards_nothing(self) -> None:
        """Same rule as an unbound route-map: configuration the device is
        not applying must not be reported as policy routing."""

        self.assertEqual(
            [], [p for p in self.policies if "unused" in (p.name or "")]
        )


class PanOsPbfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policies = parse_panos_pbf_rules(PANOS_PBF)

    def test_both_rules_are_read_in_order(self) -> None:
        self.assertEqual(2, len(self.policies))
        self.assertEqual(
            ["pbf-to-isp2", "no-pbf-internal"], [p.name for p in self.policies]
        )

    def test_the_forward_action_carries_its_hop_and_interface(self) -> None:
        rule = self.policies[0]
        self.assertEqual("10.10.0.0/16", rule.source)
        self.assertEqual("192.0.2.9", rule.next_hop)
        self.assertEqual("ethernet1/3", rule.egress_interface)
        self.assertTrue(rule.directs_traffic())

    def test_no_pbf_means_use_the_routing_table(self) -> None:
        # "no-pbf" is an explicit instruction NOT to policy-route, which
        # is the opposite of a redirect and must never read as one.
        self.assertTrue(self.policies[1].disabled)

    def test_a_source_zone_is_not_treated_as_an_interface(self) -> None:
        """Which interfaces are in a zone is knowable, but not from this
        command. Reading the zone name as an interface name would make the
        rule match on something it does not."""

        rule = self.policies[0]
        self.assertIsNone(rule.ingress_interface)
        self.assertIn("source zone trust", rule.unresolved_matches)
        # And so the rule can never be CONFIRMED from a path question.
        self.assertIsNone(rule.matches(
            source_address="10.10.1.1", protocol="tcp", destination_port=443,
            ingress_interface="ethernet1/1",
        ))

    def test_any_is_unconstrained_not_a_literal(self) -> None:
        self.assertIsNone(self.policies[0].destination)


# Captured verbatim from a real FRRouting 8.4 router in the lab.
FRR_PBR_MAP = """\
  pbr-map ATLAS-TEST valid: yes
    Seq: 10 rule: 309
        Installed: yes Reason: Valid
        SRC IP Match: 198.51.100.0/24
        DST IP Match: 203.0.113.0/24
        nexthop 172.30.12.2
          Installed: yes Tableid: 10000
    Seq: 20 rule: 319
        Installed: no Reason: Invalid Src or Dst
        IP Protocol Match: tcp
        DST Port Match: 443
        nexthop 172.30.12.3
          Installed: yes Tableid: 10001
"""

FRR_PBR_INTERFACE = "  eth2(736) with pbr-policy ATLAS-TEST\n"


class FrrPbrTests(unittest.TestCase):
    """FRR's own daemon, its own grammar — neither route-map nor iproute2.

    Every string here was observed on a real FRR 8.4 router, including the
    two failure shapes that no documentation would have shown.
    """

    def setUp(self) -> None:
        self.bindings = parse_frr_pbr_interfaces(FRR_PBR_INTERFACE)
        self.policies = parse_frr_pbr_maps(
            FRR_PBR_MAP, bindings=self.bindings
        )

    def test_the_binding_names_the_interface_without_its_index(self) -> None:
        self.assertEqual({"ATLAS-TEST": ["eth2"]}, self.bindings)

    def test_matches_and_the_next_hop_are_read(self) -> None:
        rule = next(p for p in self.policies if p.sequence == 10)
        self.assertEqual("198.51.100.0/24", rule.source)
        self.assertEqual("203.0.113.0/24", rule.destination)
        self.assertEqual("172.30.12.2", rule.next_hop)
        self.assertEqual("eth2", rule.ingress_interface)
        self.assertFalse(rule.disabled)

    def test_protocol_and_port_matches_are_read(self) -> None:
        rule = next(p for p in self.policies if p.sequence == 20)
        self.assertEqual("tcp", rule.protocol)
        self.assertEqual((443,), rule.destination_ports)

    def test_a_rule_not_installed_in_the_kernel_forwards_nothing(self) -> None:
        """FRR keeps a rule it could not install — "Installed: no Reason:
        Invalid Src or Dst". It is configured and NOT enforcing, so
        reading it as live would divert a flow the router does not."""

        self.assertTrue(next(p for p in self.policies if p.sequence == 20).disabled)

    def test_a_nexthop_installed_under_a_dead_rule_does_not_revive_it(self) -> None:
        # Seq 20's nexthop says "Installed: yes" on its own line while the
        # RULE says no. The first Installed line is the rule's.
        rule = next(p for p in self.policies if p.sequence == 20)
        self.assertTrue(rule.disabled)

    def test_a_map_bound_to_nothing_forwards_nothing(self) -> None:
        self.assertEqual((), parse_frr_pbr_maps(FRR_PBR_MAP))

    def test_a_router_with_pbrd_down_has_told_us_nothing(self) -> None:
        self.assertFalse(frr_pbr_is_readable("pbrd is not running"))
        self.assertEqual((), parse_frr_pbr_maps("pbrd is not running"))

    def test_an_empty_json_ruleset_IS_evidence_that_nobody_has_rules(self) -> None:
        """The text form is silent both when pbrd is down and when it is up
        with nothing configured, so it can never license "asked, and
        none". The json form prints "[ ]" for the second — positive
        evidence the daemon answered — and still prints its error for the
        first. Both observed on a real FRR 8.4 router."""

        self.assertTrue(frr_pbr_is_readable("[\n]"))
        self.assertFalse(frr_pbr_is_readable("pbrd is not running"))

    def test_empty_output_is_not_evidence_of_no_policy_routing(self) -> None:
        """The subtle half, and the one that nearly shipped wrong. On a
        real router "pbrd is not running" goes to STDERR and stdout comes
        back EMPTY — so a check that only looks for the message passes an
        empty string through and reports no policy routing on a router
        that never answered. A pbrd that IS up with no maps also prints
        nothing, so emptiness cannot tell the two apart."""

        self.assertFalse(frr_pbr_is_readable(""))
        self.assertFalse(frr_pbr_is_readable("   \n  "))


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
