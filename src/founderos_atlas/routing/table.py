"""The captured routing table (RIB), as canonical, platform-neutral facts.

`show ip route` on the CLI platforms Atlas manages — Cisco IOS/IOS-XE,
Arista EOS, FRRouting — shares one grammar: a protocol code, a prefix, and
either "directly connected, <iface>" or "[AD/metric] via <next-hop>[,
<iface>]". `parse_route_table` reads that grammar into `RouteEntry`
records, so any driver on a device that speaks it gets a real forwarding
table for free, and a platform whose route output differs (a firewall API,
say) normalizes into the SAME `RouteEntry` model rather than a bespoke
shape. Nothing is guessed: a line that does not parse is skipped, not
invented, and a route with no captured next-hop keeps None.

This is evidence, not inference — the routes the device reported, cited to
`show ip route`. What forwards over them is decided elsewhere; here we only
record what the device said its table holds.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# The one-letter protocol codes the CLI families share. First letter of a
# route line; sub-codes (OSPF "IA"/"E2", BGP "i") and the FRR selection
# markers (">", "*") are consumed separately.
ROUTE_CODES = {
    "K": "kernel", "C": "connected", "L": "local", "S": "static",
    "R": "rip", "O": "ospf", "I": "isis", "i": "isis", "B": "bgp",
    "E": "eigrp", "D": "eigrp", "N": "nhrp", "M": "mobile", "P": "pim",
    "A": "babel", "F": "pbr", "f": "openfabric", "T": "table", "V": "vnc",
}

_PREFIX = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b")
_VIA = re.compile(r"\bvia\s+(\d{1,3}(?:\.\d{1,3}){3})\b")
_METRIC = re.compile(r"\[(\d+)/(\d+)\]")
# A leading protocol code: one code letter, then any run of sub-code
# letters and selection markers, then whitespace before the prefix. The
# very first letter is the protocol. Leading indentation is tolerated —
# Arista EOS indents every route line — and is unambiguous because a code
# line must also carry a prefix, while an ECMP continuation carries a
# "via" and no prefix.
_LEADING_CODE = re.compile(r"^\s*([A-Za-z])[A-Za-z*> ]*?\s")
# Header / legend / grouping lines that carry no route. Indented lines are
# NOT skipped here — an indented "via" is an ECMP continuation of the route
# above it; legend and header lines fall through harmlessly because they
# carry neither a code+prefix nor a "via".
_SKIP = re.compile(
    r"^(codes:|gateway of last resort|%|routing table|vrf )", re.IGNORECASE
)
_DURATION = re.compile(r"^(\d+:\d+:\d+|\d+[wdhms]\d+[wdhms]?|\d{2}:\d{2})$")


@dataclass(frozen=True)
class RouteEntry:
    """One route the device reported: cited to `show ip route`."""

    prefix: str
    protocol: str
    next_hop: str | None = None
    interface: str | None = None
    distance: int | None = None
    metric: int | None = None
    connected: bool = False

    def to_dict(self) -> dict:
        return {
            "prefix": self.prefix,
            "protocol": self.protocol,
            "next_hop": self.next_hop,
            "interface": self.interface,
            "distance": self.distance,
            "metric": self.metric,
            "connected": self.connected,
        }


def _interface_token(tail: str) -> str | None:
    """The interface name in a route's tail, or None.

    Interfaces are named tokens (eth1, Gi0/0, GigabitEthernet0/1, lo) —
    they start with a letter and are not a duration, a weight, or the
    'via'/'onlink'/'directly'/'connected' keywords the surrounding grammar
    already consumed.
    """

    skip = {
        "via", "onlink", "is", "directly", "connected", "weight",
        "inactive", "recursive",
    }
    for raw in re.split(r"[,\s]+", tail.strip()):
        token = raw.strip()
        if not token or token.lower() in skip:
            continue
        if token[0].isdigit() or ":" in token:
            continue
        if _DURATION.match(token):
            continue
        if token.lower().startswith("weight"):
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9._/\-]*$", token):
            return token
    return None


def parse_route_table(text: str) -> tuple[RouteEntry, ...]:
    """Read `show ip route` (Cisco / EOS / FRR grammar) into RouteEntry.

    ECMP is preserved as one entry per next-hop: a route with several
    next-hops — on the same line or on indented continuation lines —
    yields a RouteEntry for each, all sharing the prefix.
    """

    entries: list[RouteEntry] = []
    last: dict | None = None   # carries prefix/protocol/metric for ECMP lines
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip() or _SKIP.match(line):
            continue

        code_match = _LEADING_CODE.match(line)
        prefix_match = _PREFIX.search(line)
        if code_match and prefix_match:
            protocol = ROUTE_CODES.get(code_match.group(1))
            if protocol is None:
                continue
            prefix = prefix_match.group(1)
            tail = line[prefix_match.end():]
            metric_match = _METRIC.search(line)
            distance = int(metric_match.group(1)) if metric_match else None
            metric = int(metric_match.group(2)) if metric_match else None
            last = {
                "prefix": prefix, "protocol": protocol,
                "distance": distance, "metric": metric,
            }
            directly = "directly connected" in tail.lower()
            via = _VIA.search(line)
            next_hop = via.group(1) if via else None
            if next_hop in (None, "0.0.0.0") and directly:
                next_hop = None
            entries.append(RouteEntry(
                prefix=prefix, protocol=protocol,
                next_hop=next_hop,
                interface=_interface_token(tail),
                distance=distance, metric=metric,
                # The PROTOCOL is what makes a route connected, not the
                # phrasing: NX-OS writes "direct" and lists the local
                # interface address as the via, which is still a connected
                # route. Deriving the flag from the protocol keeps every
                # dialect agreeing on the same fact.
                connected=protocol in ("connected", "local"),
            ))
            continue

        # A continuation line: no code, but another next-hop for `last`.
        via = _VIA.search(line)
        if last is not None and via and not _PREFIX.search(line):
            entries.append(RouteEntry(
                prefix=last["prefix"], protocol=last["protocol"],
                next_hop=via.group(1),
                interface=_interface_token(line[via.end():]),
                distance=last["distance"], metric=last["metric"],
            ))
    return tuple(entries)


# -- the prefix-line dialect (Cisco NX-OS, Aruba CX) -------------------------
#
# A second grammar, normalizing into the SAME RouteEntry: the prefix sits on
# its own line and each next-hop follows on an indented "via" line.
#
#   NX-OS:  10.10.10.0/24, ubest/mbest: 1/0, attached
#               *via 10.10.10.3, Vlan10, [0/0], 12w3d, direct
#   ArubaCX: 172.20.60.0/24, vrf default
#               via  vlan10,  [0/0],  connected
#
# The two differ in field ORDER, so the via line is read field-agnostically:
# whichever comma-separated field looks like an address is the next-hop,
# whichever looks like a port is the interface, and the protocol is matched
# from a known vocabulary. That way neither platform needs its own parser,
# and a third vendor with the same shape gets it free.

_PREFIX_HEADER = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\s*,")
_VIA_LINE = re.compile(r"^\s+\*?via\s+(?P<rest>.+)$", re.IGNORECASE)
_ADDRESS = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
# NX-OS calls a connected route "direct"; everything else is already the
# canonical word, optionally suffixed with a process or AS ("ospf-1").
_PROTOCOL_WORDS = {
    "direct": "connected", "connected": "connected", "local": "local",
    "static": "static", "ospf": "ospf", "bgp": "bgp", "rip": "rip",
    "eigrp": "eigrp", "isis": "isis", "kernel": "kernel", "am": "local",
}


def _protocol_word(field: str) -> str | None:
    head = field.strip().lower().split("-", 1)[0]
    return _PROTOCOL_WORDS.get(head)


def parse_prefix_line_route_table(text: str) -> tuple[RouteEntry, ...]:
    """Read the NX-OS / Aruba CX route grammar into RouteEntry."""

    entries: list[RouteEntry] = []
    prefix: str | None = None
    for raw in (text or "").splitlines():
        header = _PREFIX_HEADER.match(raw.strip())
        if header and not raw[:1].isspace():
            prefix = header.group(1)
            continue
        via = _VIA_LINE.match(raw)
        if not (via and prefix):
            continue
        next_hop = interface = protocol = None
        distance = metric = None
        for field in via.group("rest").split(","):
            token = field.strip()
            if not token:
                continue
            bracket = _METRIC.search(token)
            if bracket:
                distance, metric = int(bracket.group(1)), int(bracket.group(2))
                continue
            if _ADDRESS.match(token):
                if next_hop is None:
                    next_hop = token
                continue
            word = _protocol_word(token)
            if word and protocol is None:
                protocol = word
                continue
            # Not an address, a metric, or a protocol: the first such token
            # that looks like a port is the interface. Later ones (NX-OS
            # writes "intra"/"external" after the protocol) are ignored.
            if interface is None and not _DURATION.match(token):
                if re.match(r"^[A-Za-z][A-Za-z0-9._/\-]*$", token):
                    interface = token
        if protocol is None:
            continue        # no protocol word: not a route line we understand
        entries.append(RouteEntry(
            prefix=prefix, protocol=protocol, next_hop=next_hop,
            interface=interface, distance=distance, metric=metric,
            connected=protocol in ("connected", "local"),
        ))
    return tuple(entries)


# -- the Junos dialect -------------------------------------------------------
#
#   0.0.0.0/0          *[Static/5] 12w3d 02:11:04
#                       >  to 10.10.20.1 via me0.0
#   10.10.40.0/31      *[Direct/0] 12w3d 02:11:04
#                       >  via ge-0/0/0.0
#
# The protocol and preference ride in brackets on the prefix line; each
# next-hop follows indented, as "to <nh> via <iface>" or — for a direct
# route, which has no next-hop — just "via <iface>".

_JUNOS_HEADER = re.compile(
    r"^(?P<prefix>\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\s+[*+-]*\["
    r"(?P<proto>[A-Za-z]+)/(?P<pref>\d+)\]"
)
_JUNOS_METRIC = re.compile(r"metric\s+(\d+)")
_JUNOS_HOP = re.compile(
    r"^\s+[>*+\s]*(?:to\s+(?P<nh>\d{1,3}(?:\.\d{1,3}){3})\s+)?via\s+(?P<iface>\S+)"
)
_JUNOS_PROTOCOLS = {
    "direct": "connected", "local": "local", "static": "static",
    "ospf": "ospf", "ospf3": "ospf", "bgp": "bgp", "rip": "rip",
    "isis": "isis", "access": "access", "aggregate": "aggregate",
}


def parse_junos_route_table(text: str) -> tuple[RouteEntry, ...]:
    """Read Junos `show route` into RouteEntry."""

    entries: list[RouteEntry] = []
    current: dict | None = None
    for raw in (text or "").splitlines():
        header = _JUNOS_HEADER.match(raw)
        if header:
            metric = _JUNOS_METRIC.search(raw)
            protocol = header.group("proto").lower()
            current = {
                "prefix": header.group("prefix"),
                "protocol": _JUNOS_PROTOCOLS.get(protocol, protocol),
                # Junos calls the administrative distance a "preference".
                "distance": int(header.group("pref")),
                "metric": int(metric.group(1)) if metric else None,
            }
            continue
        hop = _JUNOS_HOP.match(raw)
        if hop and current:
            entries.append(RouteEntry(
                prefix=current["prefix"], protocol=current["protocol"],
                next_hop=hop.group("nh"),
                interface=hop.group("iface").rstrip(","),
                distance=current["distance"], metric=current["metric"],
                connected=current["protocol"] in ("connected", "local"),
            ))
    return tuple(entries)


# -- the columnar dialect (Palo Alto PAN-OS) ---------------------------------
#
#   destination        nexthop        metric flags  age  interface
#   0.0.0.0/0          203.0.113.1    10     A S         ethernet1/1
#   192.0.2.128/25     172.20.40.3    110    A Oi   5d   ethernet1/2
#
# Fixed columns, and the protocol is a FLAG letter rather than a word.

_COLUMNAR_ROW = re.compile(
    r"^(?P<prefix>\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\s+"
    r"(?P<nh>\d{1,3}(?:\.\d{1,3}){3}|\S+)\s+(?P<metric>\d+)\s+(?P<rest>.+)$"
)
# PAN-OS flag letters: C connect, S static, B bgp, O/Oi/Oo/O1/O2 ospf,
# R rip, H host. "A" (active) is a state, not a protocol.
_COLUMNAR_FLAGS = {
    "C": "connected", "H": "local", "S": "static", "B": "bgp",
    "R": "rip", "O": "ospf", "Oi": "ospf", "Oo": "ospf",
    "O1": "ospf", "O2": "ospf",
}


def parse_columnar_route_table(text: str) -> tuple[RouteEntry, ...]:
    """Read the PAN-OS routing table into RouteEntry."""

    entries: list[RouteEntry] = []
    for raw in (text or "").splitlines():
        row = _COLUMNAR_ROW.match(raw.strip())
        if not row:
            continue
        protocol = interface = None
        for token in row.group("rest").split():
            if protocol is None and token in _COLUMNAR_FLAGS:
                protocol = _COLUMNAR_FLAGS[token]
                continue
            # The interface is the trailing named column; ages ("2d") and
            # the active flag are not it.
            if (len(token) > 1 and token[0].isalpha()
                    and not _DURATION.match(token)
                    and token not in _COLUMNAR_FLAGS
                    and re.match(r"^[A-Za-z][A-Za-z0-9._/\-]*$", token)):
                interface = token
        if protocol is None:
            continue        # no protocol flag: not a route row we understand
        next_hop = row.group("nh")
        if not _ADDRESS.match(next_hop):
            next_hop = None
        entries.append(RouteEntry(
            prefix=row.group("prefix"), protocol=protocol,
            next_hop=next_hop, interface=interface,
            metric=int(row.group("metric")),
            connected=protocol in ("connected", "local"),
        ))
    return tuple(entries)


# -- the iproute2 dialect (Linux-based firewalls and hosts) ------------------
#
#   default via 10.90.1.1 dev eth1
#   10.90.1.0/30 dev eth1 proto kernel scope link src 10.90.1.2
#   10.251.1.0/24 via 10.90.1.6 dev eth2
#
# No protocol code and no columns: the fields are named, in any order, and
# "default" is how this dialect writes 0.0.0.0/0. A route with no `via` is
# reachable on its link — connected — which is also what `proto kernel`
# means here. ECMP arrives as indented `nexthop via …` continuation lines.

_IPROUTE_HEAD = re.compile(
    r"^(?P<prefix>default|\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?)\b(?P<rest>.*)$"
)
_IPROUTE_NEXTHOP = re.compile(r"^nexthop\b(?P<rest>.*)$")
_IPROUTE_PROTOCOLS = {
    "kernel": "connected", "static": "static", "boot": "static",
    "dhcp": "dhcp", "ra": "ra", "ospf": "ospf", "bgp": "bgp",
    "rip": "rip", "isis": "isis", "babel": "babel",
    # FRR/Quagga and BIRD install with their own protocol ids; report the
    # daemon rather than guessing which protocol inside it chose the route.
    "zebra": "zebra", "bird": "bird",
}


def _iproute_field(rest: str, name: str) -> str | None:
    found = re.search(rf"\b{name}\s+(\S+)", rest)
    return found.group(1) if found else None


def _iproute_entry(prefix: str, rest: str) -> RouteEntry:
    next_hop = _iproute_field(rest, "via")
    interface = _iproute_field(rest, "dev")
    metric = _iproute_field(rest, "metric")
    proto = _iproute_field(rest, "proto")
    if proto:
        protocol = _IPROUTE_PROTOCOLS.get(proto, proto)
    else:
        # iproute2 omits `proto boot` for a route configured by hand. With
        # no next-hop the prefix is simply on this link.
        protocol = "connected" if not next_hop else "static"
    return RouteEntry(
        prefix=prefix, protocol=protocol, next_hop=next_hop,
        interface=interface,
        metric=int(metric) if metric and metric.isdigit() else None,
        connected=protocol in ("connected", "local"),
    )


def parse_iproute2_route_table(text: str) -> tuple[RouteEntry, ...]:
    """Read Linux `ip route` output into RouteEntry."""

    entries: list[RouteEntry] = []
    prefix: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hop = _IPROUTE_NEXTHOP.match(line)
        if hop and prefix:                      # an ECMP continuation
            entries.append(_iproute_entry(prefix, hop.group("rest")))
            continue
        head = _IPROUTE_HEAD.match(line)
        if not head:
            continue                            # blackhole/unreachable: not modelled
        prefix = head.group("prefix")
        if prefix == "default":
            prefix = "0.0.0.0/0"
        elif "/" not in prefix:
            prefix += "/32"
        rest = head.group("rest")
        if "via" in rest or "dev" in rest:
            entries.append(_iproute_entry(prefix, rest))
    return tuple(entries)


def route_dicts(entries) -> list[dict]:
    """Any parsed RouteEntry sequence as JSON-ready dicts."""

    return [entry.to_dict() for entry in entries]


def route_table_dicts(text: str) -> list[dict]:
    """The parsed RIB as JSON-ready dicts for snapshot metadata."""

    return route_dicts(parse_route_table(text))


def prefix_line_route_dicts(text: str) -> list[dict]:
    """The NX-OS / Aruba CX RIB as JSON-ready dicts."""

    return route_dicts(parse_prefix_line_route_table(text))


def junos_route_dicts(text: str) -> list[dict]:
    """The Junos RIB as JSON-ready dicts."""

    return route_dicts(parse_junos_route_table(text))


def columnar_route_dicts(text: str) -> list[dict]:
    """The PAN-OS RIB as JSON-ready dicts."""

    return route_dicts(parse_columnar_route_table(text))


def iproute2_route_dicts(text: str) -> list[dict]:
    """The Linux `ip route` RIB as JSON-ready dicts."""

    return route_dicts(parse_iproute2_route_table(text))
