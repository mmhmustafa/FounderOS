"""Forwarding from the captured routing table (PR-102).

Adjacency proves a way through exists. It does not prove the device would
USE it: a router on a perfectly good link still drops a packet its table
has nothing for. These pin that the engine now asks the second question —
and, just as importantly, that it only answers where it has evidence.

The rule is the one every router applies: longest-prefix match over the
RIB the device itself reported. A device with no captured table gets no
verdict, exactly as a device with no captured ACL gets none.
"""

from __future__ import annotations

import unittest

from founderos_atlas.path_intelligence import investigate_path
from founderos_atlas.path_intelligence.forwarding import (
    describe_route,
    longest_prefix_match,
    routes_from_metadata,
)
from founderos_atlas.path_intelligence.service import apply_route_whatif
from tests.test_prediction_architecture import NOW, chain


def route(prefix, protocol="ospf", next_hop=None, interface=None,
          distance=None, metric=None, connected=False) -> dict:
    return {
        "prefix": prefix, "protocol": protocol, "next_hop": next_hop,
        "interface": interface, "distance": distance, "metric": metric,
        "connected": connected,
    }


def snapshot_with_routes(hostname: str, routes) -> dict:
    snapshot = chain()
    for device in snapshot["devices"]:
        if device["hostname"] == hostname:
            device["metadata"] = {"routing_table": list(routes)}
    return snapshot


class LongestPrefixTests(unittest.TestCase):
    def test_the_most_specific_prefix_wins(self) -> None:
        routes = [
            route("0.0.0.0/0", "static", "10.0.0.254"),
            route("10.0.0.0/8", "ospf", "10.0.0.9"),
            route("10.0.0.0/24", "connected", interface="Gi0/2"),
        ]
        self.assertEqual(
            "10.0.0.0/24", longest_prefix_match(routes, "10.0.0.3")["prefix"]
        )

    def test_a_default_route_matches_when_nothing_else_does(self) -> None:
        routes = [route("0.0.0.0/0", "static", "10.0.0.254"),
                  route("192.168.0.0/16", "ospf", "10.0.0.9")]
        self.assertEqual(
            "0.0.0.0/0", longest_prefix_match(routes, "8.8.8.8")["prefix"]
        )

    def test_equal_prefixes_break_on_administrative_distance(self) -> None:
        """Two routes to the same prefix: the router installs the one with
        the lower distance, so that is the one reported."""

        routes = [route("10.0.0.0/24", "bgp", "10.9.9.9", distance=200),
                  route("10.0.0.0/24", "ospf", "10.0.0.9", distance=110)]
        self.assertEqual(
            "ospf", longest_prefix_match(routes, "10.0.0.3")["protocol"]
        )

    def test_no_match_is_none_not_a_guess(self) -> None:
        routes = [route("192.168.0.0/16", "ospf", "10.0.0.9")]
        self.assertIsNone(longest_prefix_match(routes, "10.0.0.3"))

    def test_a_malformed_prefix_is_skipped_not_fatal(self) -> None:
        routes = [route("not-a-prefix"), route("10.0.0.0/24", "connected")]
        self.assertEqual(
            "10.0.0.0/24", longest_prefix_match(routes, "10.0.0.3")["prefix"]
        )

    def test_metadata_reader_tolerates_serializer_shapes(self) -> None:
        as_pairs = tuple(sorted(route("10.0.0.0/24").items()))
        self.assertEqual(
            1, len(routes_from_metadata({"routing_table": [as_pairs]}))
        )

    def test_never_captured_is_distinct_from_captured_and_empty(self) -> None:
        """"We never looked" must stay unevaluated, while "we looked and the
        table holds nothing" is a real verdict. Conflating them made a
        what-if that withdraws every route read as silence instead of as the
        black hole it creates."""

        self.assertIsNone(routes_from_metadata({}))          # never captured
        self.assertIsNone(routes_from_metadata(None))
        self.assertIsNone(routes_from_metadata({"routing_table": None}))
        self.assertEqual((), routes_from_metadata({"routing_table": []}))

    def test_a_route_reads_as_an_operator_would_say_it(self) -> None:
        self.assertIn(
            "via 10.0.0.9 on Gi0/2",
            describe_route(route("10.0.0.0/24", "ospf", "10.0.0.9", "Gi0/2")),
        )
        self.assertIn(
            "directly connected on Gi0/2",
            describe_route(route("10.0.0.0/24", "connected",
                                 interface="Gi0/2", connected=True)),
        )


class EngineForwardingTests(unittest.TestCase):
    def test_a_hop_with_a_matching_route_forwards_and_cites_it(self) -> None:
        snapshot = snapshot_with_routes("SW1", [
            route("10.0.0.0/24", "connected", interface="Gi0/2",
                  connected=True),
        ])
        result = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual("connected", result.status)
        cited = " ".join(
            item for hop in result.hops for item in hop.evidence
        )
        self.assertIn("SW1 routes 10.0.0.3", cited)
        self.assertIn("captured routing table", cited)
        self.assertEqual(1, result.basis["routing"]["hops_evaluated"])

    def test_a_captured_table_with_no_matching_route_drops_the_packet(self) -> None:
        """The hop is up and permitted and still cannot forward: nothing in
        the table matches and there is no default. Saying so is honest
        because there WAS a table to be absent from."""

        snapshot = snapshot_with_routes("SW1", [
            route("192.168.0.0/16", "ospf", "10.9.9.9"),
        ])
        result = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual("failed", result.status)
        self.assertEqual("no-route", result.failure_type)
        blocked = next(h for h in result.hops if h.status == "failed")
        self.assertEqual("SW1", blocked.device)
        self.assertIn("no route to 10.0.0.3", blocked.explanation)
        self.assertIn("no default route", blocked.explanation)

    def test_a_default_route_carries_the_packet(self) -> None:
        snapshot = snapshot_with_routes("SW1", [
            route("0.0.0.0/0", "static", "10.0.0.254"),
        ])
        result = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual("connected", result.status)

    def test_a_device_with_no_captured_table_is_never_guessed(self) -> None:
        """The whole gate: no routing table means no forwarding verdict —
        the same treatment a device with no captured ACL gets. A trace over
        snapshots that predate route capture must be unchanged."""

        result = investigate_path("R1", "SW2", snapshot=chain(),
                                  generated_at=NOW)
        self.assertEqual("connected", result.status)
        self.assertEqual(0, result.basis["routing"]["hops_evaluated"])
        self.assertIn("SW1", result.basis["routing"]["hops_unevaluated"])
        self.assertTrue(
            any("No captured routing table" in item for item in result.unknowns)
        )

    def test_the_destination_itself_needs_no_route(self) -> None:
        """Once the packet has arrived there is no next hop to decide, so a
        destination whose own table lacks a route to itself is not a
        failure."""

        snapshot = snapshot_with_routes("SW2", [
            route("192.168.0.0/16", "ospf", "10.9.9.9"),
        ])
        result = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual("connected", result.status)


class PolicyRoutingTests(unittest.TestCase):
    """Policy routing decides a flow BEFORE the routing table does.

    A forwarding verdict that reports the RIB's next hop while the device
    diverts the flow elsewhere is not incomplete — it is wrong, and wrong
    with full confidence. These pin that the engine asks policy first, and
    that what it cannot decide is said rather than assumed away.
    """

    def _snapshot(self, policies, *, captured=True):
        snapshot = snapshot_with_routes("SW1", [
            route("0.0.0.0/0", "static", "10.0.0.254"),
        ])
        for device in snapshot["devices"]:
            if device["hostname"] == "SW1":
                metadata = dict(device["metadata"])
                if captured:
                    metadata["policy_routes_captured"] = True
                    metadata["policy_routes"] = list(policies)
                device["metadata"] = metadata
        return snapshot

    def _hop(self, result, device="SW1"):
        return next(h for h in result.hops if h.device == device)

    def test_a_matching_policy_route_overrides_the_table(self) -> None:
        snapshot = self._snapshot([{
            "sequence": 10, "source": "10.0.0.0/24",
            "next_hop": "192.0.2.1", "egress_interface": "Gi0/9",
            "source_command": "show router policy",
        }])
        result = investigate_path(
            "R1", "SW2", snapshot=snapshot, generated_at=NOW,
            intent={"protocol": "tcp", "port": "443",
                    "source_address": "10.0.0.7"},
        )
        evidence = " ".join(self._hop(result).evidence)
        self.assertIn("policy-routes this flow", evidence)
        self.assertIn("192.0.2.1", evidence)
        self.assertIn("overrides the routing table", evidence)
        # The RIB's own answer is NOT also reported: the device does not
        # use it for this flow, so quoting it would name a hop that is
        # simply not the one taken.
        self.assertNotIn("0.0.0.0/0", evidence)

    def test_a_policy_that_cannot_be_decided_is_said_out_loud(self) -> None:
        """The rule constrains a source the trace never declared. Silently
        falling through to the table would report a next hop that a policy
        rule may well override."""

        snapshot = self._snapshot([{
            "sequence": 10, "source": "10.99.0.0/16",
            "next_hop": "192.0.2.1",
        }])
        result = investigate_path(
            "R1", "SW2", snapshot=snapshot, generated_at=NOW,
            intent={"protocol": "tcp", "port": "443"},
        )
        self.assertTrue(any(
            "may divert this flow" in item for item in result.unknowns
        ))

    def test_a_contradicted_policy_leaves_the_table_in_charge(self) -> None:
        # The flow's source is ruled out by the rule, so the rule is not
        # in play at all and nothing uncertain needs saying.
        snapshot = self._snapshot([{
            "sequence": 10, "source": "10.99.0.0/16",
            "next_hop": "192.0.2.1",
        }])
        result = investigate_path(
            "R1", "SW2", snapshot=snapshot, generated_at=NOW,
            intent={"protocol": "tcp", "source_address": "10.0.0.7"},
        )
        evidence = " ".join(self._hop(result).evidence)
        self.assertIn("0.0.0.0/0", evidence)
        self.assertFalse(any(
            "may divert this flow" in item for item in result.unknowns
        ))

    def test_captured_and_empty_says_the_table_decides(self) -> None:
        """"Asked, and this device policy-routes nothing" is evidence, and
        it is what licenses trusting the routing table's answer."""

        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot([]), generated_at=NOW,
            intent={"protocol": "tcp"},
        )
        evidence = " ".join(self._hop(result).evidence)
        self.assertIn("no policy routing configured", evidence)
        self.assertIn("0.0.0.0/0", evidence)

    def test_a_table_selecting_rule_does_not_claim_a_next_hop(self) -> None:
        """A Linux rule picks a TABLE; the captured RIB is not that table,
        so the forwarding decision here is unevaluated rather than
        answered from the wrong table."""

        snapshot = self._snapshot([{
            "sequence": 100, "table": "200", "source": "10.0.0.0/24",
        }])
        result = investigate_path(
            "R1", "SW2", snapshot=snapshot, generated_at=NOW,
            intent={"protocol": "tcp", "source_address": "10.0.0.7"},
        )
        self.assertTrue(any(
            "table 200" in item and "not evaluated" in item
            for item in result.unknowns
        ))

    def test_uncaptured_policy_is_accounted_without_flooding_unknowns(self) -> None:
        """Almost no device has policy captured yet. A per-hop unknown for
        each would bury every trace in noise about a feature most devices
        do not use — so the coverage is stated once, in the basis."""

        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot([], captured=False),
            generated_at=NOW, intent={"protocol": "tcp"},
        )
        accounting = result.to_dict()["basis"]["policy_routing"]
        self.assertIn("SW1", accounting["hops_unevaluated"])
        self.assertEqual(0, accounting["hops_evaluated"])
        self.assertFalse(any(
            "policy" in item and "divert" in item for item in result.unknowns
        ))

    def test_policy_routing_is_inert_on_a_snapshot_without_it(self) -> None:
        # Every trace recorded before this existed must still read the
        # same way. No policy metadata at all changes no verdict.
        plain = investigate_path(
            "R1", "SW2", snapshot=snapshot_with_routes("SW1", [
                route("0.0.0.0/0", "static", "10.0.0.254")]),
            generated_at=NOW, intent={"protocol": "tcp"},
        )
        self.assertEqual("connected", plain.status)
        evidence = " ".join(self._hop(plain).evidence)
        self.assertIn("0.0.0.0/0", evidence)


class DeclaredDestinationTests(unittest.TestCase):
    """Which address the flow is FOR.

    A device owns several addresses — management, dataplane, loopback. With
    none declared, a route to ANY of them satisfies the check, so a trace
    could be reported as forwarding when the only route it found was to the
    management address. Declaring the destination narrows every check to the
    address actually being asked about.
    """

    def _snapshot(self):
        """SW2 reachable at two addresses; SW1 routes only one of them."""

        snapshot = snapshot_with_routes("SW1", [
            route("10.0.0.0/24", "ospf", "10.0.0.9", distance=110),
        ])
        for device in snapshot["devices"]:
            if device["hostname"] == "SW2":
                device["interfaces"] = [
                    {"name": "Gi0/1", "ip_address": "192.168.5.5",
                     "status": "up", "protocol_status": "up",
                     "description": None, "metadata": {}},
                ]
        return snapshot

    def test_without_a_declaration_any_address_satisfies_the_check(self) -> None:
        result = investigate_path("R1", "SW2", snapshot=self._snapshot(),
                                  generated_at=NOW)
        self.assertEqual("connected", result.status)
        self.assertEqual(
            "10.0.0.0/24",
            next(h for h in result.hops if h.device == "SW1").route["prefix"],
        )

    def test_a_declared_address_with_no_route_is_a_black_hole(self) -> None:
        """The correctness win: the device IS reachable at its management
        address, so the undeclared trace connects — but the flow being asked
        about targets an address nothing routes, and that must not be hidden
        behind a route to a different address."""

        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot(), generated_at=NOW,
            intent={"protocol": "tcp", "port": "443",
                    "destination_address": "192.168.5.5"},
        )
        self.assertEqual("failed", result.status)
        self.assertEqual("no-route", result.failure_type)
        blocked = next(h for h in result.hops if h.status == "failed")
        self.assertIn("no route to 192.168.5.5", blocked.explanation)

    def test_a_declared_address_that_is_routed_still_connects(self) -> None:
        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot(), generated_at=NOW,
            intent={"protocol": "tcp", "port": "443",
                    "destination_address": "10.0.0.3"},
        )
        self.assertEqual("connected", result.status)

    def test_the_verdict_names_the_address_it_judged(self) -> None:
        """A verdict that narrowed to one address must say so, or it reads
        as being about the device as a whole."""

        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot(), generated_at=NOW,
            intent={"protocol": "tcp", "port": "443",
                    "destination_address": "192.168.5.5"},
        )
        blocked = next(h for h in result.hops if h.status == "failed")
        self.assertIn("to 192.168.5.5", blocked.explanation)

    def test_a_malformed_address_is_ignored_and_said_out_loud(self) -> None:
        """Silently narrowing every match to an address that cannot exist
        would fail the whole trace for a typo."""

        result = investigate_path(
            "R1", "SW2", snapshot=self._snapshot(), generated_at=NOW,
            intent={"protocol": "tcp", "destination_address": "not-an-ip"},
        )
        self.assertEqual("connected", result.status)
        self.assertTrue(
            any("not a valid address" in item for item in result.unknowns)
        )


class WithdrawRouteWhatIfTests(unittest.TestCase):
    """"What breaks if this route goes away?" — asked by withdrawing the
    prefix from the captured table and re-running the same engine."""

    def _snapshot(self):
        return snapshot_with_routes("SW1", [
            route("10.0.0.0/24", "ospf", "10.0.0.9", distance=110),
            route("0.0.0.0/0", "static", "10.0.0.254", distance=1),
        ])

    def test_withdrawing_a_prefix_falls_back_to_the_less_specific_route(self) -> None:
        """The answer an operator actually wants: not "it breaks" but WHAT
        the device would then use. Withdrawing the /24 leaves the default,
        and the packet still gets through by it."""

        snapshot = self._snapshot()
        before = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual(
            "10.0.0.0/24",
            next(h for h in before.hops if h.device == "SW1").route["prefix"],
        )
        after = investigate_path(
            "R1", "SW2", generated_at=NOW,
            snapshot=apply_route_whatif(snapshot, [("SW1", "10.0.0.0/24")]),
        )
        self.assertEqual("connected", after.status)
        self.assertEqual(
            "0.0.0.0/0",
            next(h for h in after.hops if h.device == "SW1").route["prefix"],
        )

    def test_withdrawing_every_route_is_a_black_hole_not_silence(self) -> None:
        snapshot = apply_route_whatif(
            self._snapshot(), [("SW1", "10.0.0.0/24"), ("SW1", "0.0.0.0/0")]
        )
        result = investigate_path("R1", "SW2", snapshot=snapshot,
                                  generated_at=NOW)
        self.assertEqual("failed", result.status)
        self.assertEqual("no-route", result.failure_type)

    def test_the_real_snapshot_is_never_mutated(self) -> None:
        """A what-if is a question, not an edit: the caller's snapshot
        belongs to the real investigation."""

        snapshot = self._snapshot()
        apply_route_whatif(snapshot, [("SW1", "10.0.0.0/24")])
        table = next(d for d in snapshot["devices"]
                     if d["hostname"] == "SW1")["metadata"]["routing_table"]
        self.assertEqual(2, len(table))

    def test_withdrawing_a_route_another_device_holds_changes_nothing(self) -> None:
        # The pair is (device, prefix): a prefix is only withdrawn from the
        # device that was named, never wherever it happens to appear.
        snapshot = apply_route_whatif(
            self._snapshot(), [("SW2", "10.0.0.0/24")]
        )
        table = next(d for d in snapshot["devices"]
                     if d["hostname"] == "SW1")["metadata"]["routing_table"]
        self.assertEqual(2, len(table))


if __name__ == "__main__":
    unittest.main()
