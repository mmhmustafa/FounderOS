"""The canonical routing-table parser: one grammar, many platforms.

`show ip route` on Cisco IOS/IOS-XE, Arista EOS, and FRRouting shares a
grammar — a protocol code, a prefix, and either "directly connected,
<iface>" or "[AD/metric] via <next-hop>[, <iface>]". These pin that the
parser reads both dialects into the same RouteEntry, preserves ECMP,
ignores legend and header noise, and never invents a route.
"""

from __future__ import annotations

import unittest

from founderos_atlas.routing.table import (
    parse_columnar_route_table,
    parse_iproute2_route_table,
    parse_junos_route_table,
    parse_prefix_line_route_table,
    parse_route_table,
    route_table_dicts,
)


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


NXOS = """IP Route Table for VRF "default"
'*' denotes best ucast next-hop

10.10.10.0/24, ubest/mbest: 1/0, attached
    *via 10.10.10.3, Vlan10, [0/0], 12w3d, direct
192.0.2.11/32, ubest/mbest: 1/0
    *via 10.10.99.2, Eth1/49, [110/41], 12w3d, ospf-1, intra
"""

ARUBA = """Displaying ipv4 routes selected for forwarding

'[x/y]' denotes [distance/metric]

0.0.0.0/0, vrf default
    via  172.20.20.1,  [1/0],  static
10.255.0.60/32, vrf default
    via  loopback0,  [0/0],  connected
192.0.2.128/25, vrf default
    via  172.20.60.3,  [110/2],  ospf
"""


class PrefixLineGrammarTests(unittest.TestCase):
    """NX-OS and Aruba CX put the prefix on its own line and the next-hops
    beneath it. They differ in FIELD ORDER, so one field-agnostic reader
    serves both — and normalizes into the same RouteEntry as the Cisco
    grammar, which is the whole point of the canonical model.
    """

    def test_nxos_next_hop_interface_and_metric(self) -> None:
        routes = {r.prefix: r for r in parse_prefix_line_route_table(NXOS)}
        self.assertEqual(2, len(routes))
        ospf = routes["192.0.2.11/32"]
        self.assertEqual(("ospf", "10.10.99.2", "Eth1/49", 110, 41),
                         (ospf.protocol, ospf.next_hop, ospf.interface,
                          ospf.distance, ospf.metric))

    def test_nxos_direct_is_a_connected_route(self) -> None:
        """NX-OS words a connected route "direct" and lists the local
        address as its via — it is still a connected route, and the
        canonical flag must say so."""

        routes = {r.prefix: r for r in parse_prefix_line_route_table(NXOS)}
        direct = routes["10.10.10.0/24"]
        self.assertEqual("connected", direct.protocol)
        self.assertTrue(direct.connected)

    def test_aruba_reads_the_same_shape_with_a_different_field_order(self) -> None:
        routes = {r.prefix: r for r in parse_prefix_line_route_table(ARUBA)}
        self.assertEqual(3, len(routes))
        # Aruba names the interface after "via" for a connected route...
        local = routes["10.255.0.60/32"]
        self.assertEqual(("connected", None, "loopback0"),
                         (local.protocol, local.next_hop, local.interface))
        # ...and an address for a routed one.
        self.assertEqual(("static", "172.20.20.1"),
                         (routes["0.0.0.0/0"].protocol,
                          routes["0.0.0.0/0"].next_hop))

    def test_a_line_with_no_protocol_word_is_not_invented(self) -> None:
        self.assertEqual(
            (), parse_prefix_line_route_table(
                "10.0.0.0/8, vrf default\n    via  10.0.0.1,  [1/0]\n"
            )
        )


JUNOS = """inet.0: 12 destinations, 12 routes (12 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

0.0.0.0/0          *[Static/5] 12w3d 02:11:04
                    >  to 10.10.20.1 via me0.0
10.10.40.0/31      *[Direct/0] 12w3d 02:11:04
                    >  via ge-0/0/0.0
192.0.2.13/32      *[OSPF/10] 10w1d 11:22:33, metric 2
                    >  to 10.10.40.0 via ge-0/0/0.0
"""

PANOS = """flags: A:active, C:connect, S:static, O:ospf, B:bgp, Oi:ospf intra-area

VIRTUAL ROUTER: default (id 1)
destination            nexthop          metric flags   age  interface
0.0.0.0/0              203.0.113.1      10     A S          ethernet1/1
172.20.40.0/24         172.20.40.1      0      A C          ethernet1/2
192.0.2.128/25         172.20.40.3      110    A Oi     5d   ethernet1/2

VIRTUAL ROUTER: tenant-b (id 2)
destination            nexthop          metric flags   age  interface
172.20.50.0/24         172.20.50.1      0      A C          ethernet1/3

total routes shown: 4
"""


class JunosGrammarTests(unittest.TestCase):
    """Junos carries protocol and preference in brackets on the prefix line
    and puts each next-hop beneath it — "to <nh> via <iface>", or just
    "via <iface>" for a direct route, which has no next-hop at all."""

    def setUp(self) -> None:
        self.routes = {r.prefix: r for r in parse_junos_route_table(JUNOS)}

    def test_table_headers_carry_no_route(self) -> None:
        self.assertEqual(3, len(self.routes))

    def test_preference_is_the_administrative_distance(self) -> None:
        ospf = self.routes["192.0.2.13/32"]
        self.assertEqual(("ospf", "10.10.40.0", "ge-0/0/0.0", 10, 2),
                         (ospf.protocol, ospf.next_hop, ospf.interface,
                          ospf.distance, ospf.metric))

    def test_a_direct_route_has_an_interface_and_no_next_hop(self) -> None:
        direct = self.routes["10.10.40.0/31"]
        self.assertEqual(("connected", None, "ge-0/0/0.0", True),
                         (direct.protocol, direct.next_hop, direct.interface,
                          direct.connected))


class ColumnarGrammarTests(unittest.TestCase):
    """PAN-OS prints fixed columns and encodes the protocol as a FLAG
    letter, not a word — and spans every virtual router in one table."""

    def setUp(self) -> None:
        self.routes = {r.prefix: r for r in parse_columnar_route_table(PANOS)}

    def test_every_virtual_router_is_read(self) -> None:
        self.assertEqual(4, len(self.routes))
        self.assertIn("172.20.50.0/24", self.routes)   # the tenant-b VR

    def test_flag_letters_become_protocols(self) -> None:
        self.assertEqual("static", self.routes["0.0.0.0/0"].protocol)
        self.assertEqual("connected", self.routes["172.20.40.0/24"].protocol)
        # "Oi" (OSPF intra-area) is still OSPF.
        self.assertEqual("ospf", self.routes["192.0.2.128/25"].protocol)

    def test_the_interface_column_is_not_confused_with_the_age(self) -> None:
        ospf = self.routes["192.0.2.128/25"]
        self.assertEqual(("172.20.40.3", "ethernet1/2", 110),
                         (ospf.next_hop, ospf.interface, ospf.metric))


# Captured verbatim from an AtlasLab perimeter firewall (`show route`).
IPROUTE2 = """default via 10.90.1.1 dev eth1
10.90.1.0/30 dev eth1 proto kernel scope link src 10.90.1.2
10.90.1.4/30 dev eth2 proto kernel scope link src 10.90.1.5
10.251.1.0/24 via 10.90.1.6 dev eth2
172.20.20.0/24 dev eth0 proto kernel scope link src 172.20.20.12
172.30.4.0/22 via 10.90.1.6 dev eth2
"""


class Iproute2GrammarTests(unittest.TestCase):
    """Linux-based devices (the lab's perimeter firewalls) answer with
    iproute2: no protocol code, no columns — named fields in any order,
    and "default" for 0.0.0.0/0."""

    def setUp(self) -> None:
        self.routes = {r.prefix: r
                       for r in parse_iproute2_route_table(IPROUTE2)}

    def test_every_route_line_is_read(self) -> None:
        self.assertEqual(6, len(self.routes))

    def test_default_is_the_default_route(self) -> None:
        default = self.routes["0.0.0.0/0"]
        self.assertEqual(("static", "10.90.1.1", "eth1"),
                         (default.protocol, default.next_hop, default.interface))

    def test_proto_kernel_with_no_via_is_connected(self) -> None:
        link = self.routes["172.20.20.0/24"]
        self.assertEqual(("connected", None, "eth0", True),
                         (link.protocol, link.next_hop, link.interface,
                          link.connected))

    def test_a_via_route_keeps_its_next_hop_and_port(self) -> None:
        far = self.routes["172.30.4.0/22"]
        self.assertEqual(("10.90.1.6", "eth2"), (far.next_hop, far.interface))

    def test_ecmp_nexthop_continuations_are_read(self) -> None:
        routes = parse_iproute2_route_table(
            "default proto static\n"
            "\tnexthop via 10.0.0.1 dev eth0 weight 1\n"
            "\tnexthop via 10.0.0.2 dev eth1 weight 1\n"
        )
        self.assertEqual({"10.0.0.1", "10.0.0.2"},
                         {r.next_hop for r in routes})
        self.assertTrue(all(r.prefix == "0.0.0.0/0" for r in routes))

    def test_a_host_route_without_a_mask_becomes_a_32(self) -> None:
        routes = parse_iproute2_route_table("10.1.2.3 via 10.0.0.1 dev eth0\n")
        self.assertEqual("10.1.2.3/32", routes[0].prefix)


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
