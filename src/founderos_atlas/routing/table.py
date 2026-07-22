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
# very first letter is the protocol.
_LEADING_CODE = re.compile(r"^([A-Za-z])[A-Za-z*> ]*?\s")
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
            connected = "directly connected" in tail.lower()
            via = _VIA.search(line)
            next_hop = via.group(1) if via else None
            if next_hop in (None, "0.0.0.0") and connected:
                next_hop = None
            entries.append(RouteEntry(
                prefix=prefix, protocol=protocol,
                next_hop=next_hop,
                interface=_interface_token(tail),
                distance=distance, metric=metric,
                connected=connected or (next_hop is None and not via),
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


def route_table_dicts(text: str) -> list[dict]:
    """The parsed RIB as JSON-ready dicts for snapshot metadata."""

    return [entry.to_dict() for entry in parse_route_table(text)]
