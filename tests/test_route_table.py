"""The canonical routing-table parser: one grammar, many platforms.

`show ip route` on Cisco IOS/IOS-XE, Arista EOS, and FRRouting shares a
grammar — a protocol code, a prefix, and either "directly connected,
<iface>" or "[AD/metric] via <next-hop>[, <iface>]". These pin that the
parser reads both dialects into the same RouteEntry, preserves ECMP,
ignores legend and header noise, and never invents a route.
"""

from __future__ import annotations

import unittest

from founderos_atlas.routing.table import parse_route_table, route_table_dicts


FRR = """Codes: K - kernel route, C - connected, S - static, R - RIP,
       O - OSPF, I - IS-IS, B - BGP, E - EIGRP, N - NHRP,
       > - selected route, * - FIB route, q - queued, r - rejected

C>* 172.20.20.8/32 is directly connected, eth0, 00:34:12
O>* 10.251.3.2/32 [110/10] via 0.0.0.0, lo onlink, weight 1, 00:34:00
O>* 10.90.3.0/24 [110/20] via 10.90.3.5, eth1, weight 1, 00:33:45
B>* 10.2.0.0/16 [20/0] via 172.20.20.6, eth1, weight 1, 00:30:00
S>* 0.0.0.0/0 [1/0] via 172.20.20.1, eth0, weight 1, 00:34:12
"""

CISCO = """Codes: L - local, C - connected, S - static, O - OSPF, B - BGP
Gateway of last resort is 10.0.0.1 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 10.0.0.1
C        10.1.1.0/24 is directly connected, GigabitEthernet0/0
O        10.2.2.0/24 [110/20] via 192.168.1.2, 00:05:12, GigabitEthernet0/1
B        10.3.3.0/24 [200/0] via 172.16.0.5, 1d02h
O        10.4.4.0/24 [110/30] via 192.168.1.2, 00:05:12, GigabitEthernet0/1
                       via 192.168.1.6, 00:05:12, GigabitEthernet0/2
"""


class FrrGrammarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = parse_route_table(FRR)
        self.by_prefix = {r.prefix: r for r in self.routes}

    def test_every_route_line_becomes_a_route_and_legend_is_ignored(self) -> None:
        self.assertEqual(5, len(self.routes))

    def test_a_connected_route_keeps_its_interface_and_no_next_hop(self) -> None:
        c = self.by_prefix["172.20.20.8/32"]
        self.assertEqual(("connected", None, "eth0", True),
                         (c.protocol, c.next_hop, c.interface, c.connected))

    def test_a_routed_prefix_keeps_next_hop_interface_and_metric(self) -> None:
        o = self.by_prefix["10.90.3.0/24"]
        self.assertEqual(("ospf", "10.90.3.5", "eth1", 110, 20),
                         (o.protocol, o.next_hop, o.interface,
                          o.distance, o.metric))

    def test_the_default_route_is_captured(self) -> None:
        d = self.by_prefix["0.0.0.0/0"]
        self.assertEqual(("static", "172.20.20.1"), (d.protocol, d.next_hop))


class CiscoGrammarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = parse_route_table(CISCO)

    def test_headers_and_gateway_line_carry_no_route(self) -> None:
        # 5 distinct prefixes, but 10.4.4.0/24 is ECMP → 6 entries total.
        self.assertEqual(6, len(self.routes))

    def test_a_bgp_route_with_an_uptime_has_no_false_interface(self) -> None:
        b = next(r for r in self.routes if r.protocol == "bgp")
        # "1d02h" is an uptime, not an interface.
        self.assertEqual(("172.16.0.5", None), (b.next_hop, b.interface))

    def test_ecmp_is_one_entry_per_next_hop(self) -> None:
        ecmp = [r for r in self.routes if r.prefix == "10.4.4.0/24"]
        self.assertEqual(2, len(ecmp))
        self.assertEqual(
            {"192.168.1.2", "192.168.1.6"}, {r.next_hop for r in ecmp}
        )
        # Both carry the shared prefix's metric.
        self.assertTrue(all(r.metric == 30 for r in ecmp))


class RobustnessTests(unittest.TestCase):
    def test_empty_or_error_output_is_no_routes_not_a_crash(self) -> None:
        self.assertEqual((), parse_route_table(""))
        self.assertEqual((), parse_route_table("% no route output"))

    def test_an_unpar_seable_line_is_skipped_not_invented(self) -> None:
        routes = parse_route_table(
            "O   10.1.1.0/24 [110/20] via 10.0.0.1, eth0\n"
            "this is not a route line at all\n"
        )
        self.assertEqual(1, len(routes))

    def test_dicts_are_json_ready(self) -> None:
        dicts = route_table_dicts(FRR)
        self.assertTrue(all(isinstance(d, dict) for d in dicts))
        self.assertEqual(
            {"prefix", "protocol", "next_hop", "interface",
             "distance", "metric", "connected"},
            set(dicts[0]),
        )


if __name__ == "__main__":
    unittest.main()
