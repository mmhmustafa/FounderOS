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
