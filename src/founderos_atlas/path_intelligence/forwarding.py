"""Forwarding from the captured routing table.

The path engine finds a path from observed ADJACENCY — who is cabled or
adjacent to whom. That answers "is there a way through", not "would this
device actually forward the packet". A device can sit on a perfectly good
link and still drop traffic because nothing in its table matches the
destination.

This module answers the second question from evidence only: the RIB the
device itself reported (`show ip route`, captured per platform into the
canonical RouteEntry shape). Longest-prefix match is the rule every router
applies, so it is the rule applied here.

What it will NOT do is guess. A device with no captured table gets no
verdict — the caller reports the hop as unevaluated, exactly as it does
for a device with no captured ACL. The absence of a route is only ever
claimed when a table was actually captured to be absent FROM.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any


def routes_from_metadata(metadata: Any) -> tuple[dict, ...]:
    """The captured RIB out of a snapshot device's metadata, or empty.

    Accepts the list-of-dicts the drivers write and the ordered key/value
    pairs a snapshot serializer may produce, so this survives a change of
    serializer without inventing a migration — the same tolerance the
    firewall reader keeps.
    """

    if not isinstance(metadata, dict):
        return ()
    captured = metadata.get("routing_table")
    if not captured:
        return ()
    routes: list[dict] = []
    for entry in captured:
        if isinstance(entry, dict):
            fields = entry
        else:
            try:
                fields = dict(entry)
            except (TypeError, ValueError):
                continue
        prefix = str(fields.get("prefix") or "").strip()
        if not prefix:
            continue
        routes.append(fields)
    return tuple(routes)


def longest_prefix_match(routes, address: str) -> dict | None:
    """The route a router would choose for ``address``, or None.

    Longest prefix wins; among equal prefixes the lowest administrative
    distance wins, which is how a router breaks that tie. A malformed
    prefix is skipped rather than crashing a whole investigation.
    """

    try:
        target = ip_address(str(address))
    except ValueError:
        return None
    best: dict | None = None
    best_length = -1
    best_distance: int | None = None
    for route in routes:
        try:
            network = ip_network(str(route.get("prefix")), strict=False)
        except ValueError:
            continue
        if target not in network:
            continue
        distance = route.get("distance")
        distance = distance if isinstance(distance, int) else None
        if network.prefixlen > best_length:
            best, best_length, best_distance = route, network.prefixlen, distance
        elif network.prefixlen == best_length:
            if distance is not None and (
                best_distance is None or distance < best_distance
            ):
                best, best_distance = route, distance
    return best


def describe_route(route: dict) -> str:
    """A route as an operator reads it: where it sends the packet."""

    prefix = route.get("prefix")
    protocol = route.get("protocol") or "unknown"
    next_hop = route.get("next_hop")
    interface = route.get("interface")
    if next_hop:
        where = f"via {next_hop}"
        if interface:
            where += f" on {interface}"
    elif interface:
        where = f"directly connected on {interface}"
    else:
        where = "with no next-hop recorded"
    return f"{prefix} ({protocol}) {where}"
