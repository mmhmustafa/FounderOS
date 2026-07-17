"""Canonical topology vocabulary: one definition per counted thing.

Every surface that shows a topology number — Mission tiles, the topology
page header, the interactive viewer summary, inventory, exports, and
APIs — must count through this module. Two pages disagreeing about how
many "links" a network has is a trust defect, not a rounding error.

The canonical definitions
-------------------------

Relationship
    Any displayed connection between two endpoints, whatever the
    evidence. The superset: every other link count is a subset of the
    relationships. One relationship folds all directional observations
    of the same endpoint/interface pair.

Physical link
    A relationship verified by link-layer evidence (CDP/LLDP naming, or
    MAC-table correlation) between endpoints. The cable view.

Logical adjacency
    Any relationship that is not a physical link: a protocol session or
    derived association (routing adjacency, BGP peering, verified routed
    link, shared layer-3 subnet, inferred, unknown).

Routing adjacency
    A logical adjacency observed from an interior gateway protocol
    (OSPF) neighbor table. State comes from the observation; a
    configured neighbor is never counted as an adjacency.

BGP peering
    A logical adjacency observed from a BGP session table. eBGP/iBGP is
    derived only when both AS numbers are observed.

Inter-site link
    A relationship whose two endpoints belong to two *different* known
    sites — where each endpoint's site comes from the effective site
    assignment (operator override first, then multi-signal inference)
    or, for an unresolved peer, from assigning evidence about the far
    end (announced hostname matching a site convention, or an interface
    description naming a site). A peer with no far-end site evidence
    never creates an inter-site link.

Unresolved peer identity
    An endpoint observed through protocol evidence (a neighbor
    announcement, a BGP session, a routing adjacency) that Atlas has
    not resolved to a discovered device. Counted as identities, never
    as devices.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


RELATIONSHIP_PHYSICAL = "physical"
RELATIONSHIP_VERIFIED_ROUTED = "verified-routed"
RELATIONSHIP_ROUTING_ADJACENCY = "routing-adjacency"
RELATIONSHIP_BGP_PEERING = "protocol-peer"

DEFINITIONS: dict[str, str] = {
    "relationships": (
        "Every displayed connection between two endpoints, whatever the "
        "evidence. All directional observations of one endpoint/interface "
        "pair fold into a single relationship."
    ),
    "physical_links": (
        "Relationships verified by link-layer evidence (CDP/LLDP or MAC "
        "correlation). The cable view."
    ),
    "logical_adjacencies": (
        "Relationships that are not physical links: protocol sessions and "
        "derived associations (routing adjacencies, BGP peerings, verified "
        "routed links, shared subnets, inferred)."
    ),
    "routing_adjacencies": (
        "Logical adjacencies observed from an IGP (OSPF) neighbor table. "
        "Configured-but-unobserved neighbors are never counted."
    ),
    "bgp_peerings": (
        "Logical adjacencies observed from a BGP session table."
    ),
    "verified_routed_links": (
        "Logical adjacencies verified as routed forwarding paths by "
        "corroborating evidence."
    ),
    "inter_site_links": (
        "Relationships whose two endpoints belong to two different known "
        "sites, from effective site assignment or assigning far-end "
        "evidence. No far-end site evidence, no inter-site link."
    ),
    "unresolved_peer_identities": (
        "Endpoints observed through protocol evidence that are not "
        "resolved to a discovered device. Identities, never devices."
    ),
}


@dataclass(frozen=True)
class TopologyCounts:
    """The canonical counts, computed once from rendered elements."""

    relationships: int
    physical_links: int
    logical_adjacencies: int
    routing_adjacencies: int
    bgp_peerings: int
    verified_routed_links: int
    inter_site_links: int
    unresolved_peer_identities: int

    def to_dict(self) -> dict[str, int]:
        return {
            "relationships": self.relationships,
            "physical_links": self.physical_links,
            "logical_adjacencies": self.logical_adjacencies,
            "routing_adjacencies": self.routing_adjacencies,
            "bgp_peerings": self.bgp_peerings,
            "verified_routed_links": self.verified_routed_links,
            "inter_site_links": self.inter_site_links,
            "unresolved_peer_identities": self.unresolved_peer_identities,
        }


def count_topology(
    elements: Mapping[str, Any],
    *,
    site_membership: Mapping[str, str] | None = None,
) -> TopologyCounts:
    """Count rendered topology elements under the canonical definitions.

    ``elements`` is the renderer's ``{"nodes": [...], "edges": [...]}``
    shape. ``site_membership`` maps node id → effective site id (with
    ``"__none__"`` for "no site evidence"); when omitted, inter-site
    links honestly count as zero rather than being guessed.
    """

    edges = [dict(item.get("data") or {}) for item in elements.get("edges") or ()]
    nodes = [dict(item.get("data") or {}) for item in elements.get("nodes") or ()]

    physical = sum(
        1 for edge in edges if edge.get("relationship") == RELATIONSHIP_PHYSICAL
    )
    routing = sum(
        1
        for edge in edges
        if edge.get("relationship") == RELATIONSHIP_ROUTING_ADJACENCY
    )
    peering = sum(
        1 for edge in edges if edge.get("relationship") == RELATIONSHIP_BGP_PEERING
    )
    verified_routed = sum(
        1
        for edge in edges
        if edge.get("relationship") == RELATIONSHIP_VERIFIED_ROUTED
    )
    relationships = len(edges)

    inter_site = 0
    if site_membership:
        for edge in edges:
            left = site_membership.get(str(edge.get("source")))
            right = site_membership.get(str(edge.get("target")))
            if (
                left and right
                and left != "__none__" and right != "__none__"
                and left != right
            ):
                inter_site += 1

    unresolved = sum(1 for node in nodes if node.get("kind") == "observed")

    return TopologyCounts(
        relationships=relationships,
        physical_links=physical,
        logical_adjacencies=relationships - physical,
        routing_adjacencies=routing,
        bgp_peerings=peering,
        verified_routed_links=verified_routed,
        inter_site_links=inter_site,
        unresolved_peer_identities=unresolved,
    )
