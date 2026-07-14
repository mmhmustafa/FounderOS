"""Deterministic TopologySnapshot to interactive HTML rendering."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from founderos_atlas.platforms.classify import (
    ROLE_UNKNOWN,
    ROLE_UNRESOLVED,
    RELATION_PEER,
    RELATION_PHYSICAL,
    RELATION_ROUTING,
    classify_role,
    relationship_kind,
)
from founderos_atlas.topology import TopologySnapshot

from .stencils import role_accent as _role_accent
from .stencils import stencil_data_uri


CYTOSCAPE_CDN = "https://unpkg.com/cytoscape@3.29.2/dist/cytoscape.min.js"

# Fused relationship type -> displayed relationship class (PR-043.7).
# Solid = verified physical; dashed = verified routed; dotted = observed
# but unresolved (unresolved edges keep their observation classes).
_FUSED_RELATIONSHIP_CLASS = {
    "verified-physical": "physical",
    "verified-routed": "verified-routed",
    "ospf": "routing-adjacency",
    "bgp": "protocol-peer",
    "static": "routing-adjacency",
    "layer-3": "layer-3",
    "layer-2": "physical",
    "inferred": "inferred",
    "unknown": "unknown",
}

# Evidence kinds that ARE protocol observations of a link (as opposed
# to derived corroborations like ownership or subnet matches).
_OBSERVATION_EVIDENCE_KINDS = frozenset(
    {"link-layer", "ospf-neighbor", "bgp-peer", "static-route", "arp-mac"}
)

_VENDOR_COLORS = {
    "cisco": "#2563eb",
    "juniper": "#16a34a",
    "arista": "#7c3aed",
    "fortinet": "#dc2626",
    "palo alto": "#ea580c",
    "unknown": "#64748b",
}


class TopologyRenderer:
    def __init__(
        self,
        snapshot: TopologySnapshot,
        change_report: Any | None = None,
        viewer_context: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(snapshot, TopologySnapshot):
            raise TypeError("snapshot must be a TopologySnapshot")
        if viewer_context is not None and not isinstance(viewer_context, Mapping):
            raise TypeError("viewer_context must be a mapping or None")
        self._snapshot = snapshot
        self._change = _change_highlights(change_report)
        self._context = dict(viewer_context or {})

    def elements(self) -> dict[str, list[dict[str, Any]]]:
        """Return deterministic Cytoscape nodes and edges without rendering HTML.

        Directional neighbor observations of one physical link (``R1 -> SW1``
        and ``SW1 -> R1``) collapse into a single displayed connection; device
        identity aliases resolve to their canonical node.
        """

        hostname_to_id: dict[str, str] = {}
        for device in self._snapshot.devices:
            device_id = str(device["device_id"])
            hostname_to_id[str(device["hostname"]).casefold()] = device_id
            for alias in _device_aliases(device):
                hostname_to_id.setdefault(alias.casefold(), device_id)
            # PR-043.1: adjacencies naming a peer by an address that a
            # DISCOVERED device owns resolve onto that device (exact
            # address-identity evidence) instead of spawning a duplicate
            # unresolved node.
            management_ip = str(device.get("management_ip") or "").strip()
            if management_ip:
                hostname_to_id.setdefault(management_ip.casefold(), device_id)
        neighbor_counts = self._neighbor_counts()
        configured = {
            str(name).casefold() for name in self._context.get("configured_hostnames") or ()
        }
        config_changes = {
            str(name).casefold(): str(value)
            for name, value in (self._context.get("config_changes") or {}).items()
        }
        last_discovered = str(self._context.get("last_discovered") or "unrecorded")
        nodes: dict[str, dict[str, Any]] = {}
        for device in self._snapshot.devices:
            device_id = str(device["device_id"])
            vendor = str(device["vendor"])
            hostname_key = str(device["hostname"]).casefold()
            depth = (device.get("metadata") or {}).get("discovery_depth")
            role, role_evidence = classify_role(device)
            hostname = str(device["hostname"])
            mgmt = str(device["management_ip"] or "").strip()
            node_data = {
                "id": device_id,
                "label": hostname,
                # Two-line caption under the icon: name, then the endpoint an
                # engineer would actually reach it at.
                "display_label": f"{hostname}\n{mgmt}" if mgmt else hostname,
                "role_label": _role_label(role),
                "accent": _role_accent(role),
                "hostname": hostname,
                "aliases": list(_device_aliases(device)),
                "management_ip": str(device["management_ip"]),
                "vendor": vendor,
                "platform": str(device["platform"]),
                "os": f"{device['os_name']} {device['os_version']}",
                "interfaces": len(device["interfaces"]),
                "neighbors": neighbor_counts.get(hostname_key, 0),
                "role": role,
                "role_evidence": role_evidence,
                "stencil": stencil_data_uri(role),
                "discovery_status": "Managed device (discovered)",
                "observation": "direct discovery",
                "discovery_depth": "unknown" if depth is None else str(depth),
                "last_discovered": last_discovered,
                "config_collected": "Yes" if hostname_key in configured else "No",
                "last_config_change": config_changes.get(hostname_key, "None recorded"),
                "kind": "discovered",
                "color": _vendor_color(vendor),
            }
            if self._change is not None:
                node_data["change"] = self._change_status(str(device["hostname"]))
            nodes[device_id] = {"data": node_data}
        if self._change is not None:
            for hostname in self._change["removed"]:
                ghost_id = f"removed:{hostname.casefold()}"
                nodes[ghost_id] = {
                    "data": {
                        "id": ghost_id,
                        "label": hostname,
                        "hostname": hostname,
                        "aliases": [],
                        "management_ip": "unknown",
                        "vendor": "unknown",
                        "platform": "no longer discovered",
                        "os": "unknown",
                        "interfaces": 0,
                        "kind": "removed",
                        "change": "removed",
                        "role": ROLE_UNKNOWN,
                        "role_evidence": "device no longer discovered",
                        "stencil": stencil_data_uri(ROLE_UNKNOWN),
                        "discovery_status": "No longer discovered",
                        "observation": "previous discovery",
                        "color": "#dc2626",
                    }
                }

        # PR-043.7 (FUSION): topology is generated from Enterprise
        # Knowledge. When the snapshot carries correlated relationships,
        # each fused relationship renders as ONE edge with its type,
        # confidence, and evidence; raw observations only contribute the
        # honest unresolved (dotted) edges. Older snapshots without
        # correlation metadata keep the observation-based path unchanged.
        snapshot_metadata = dict(self._snapshot.metadata or {})
        fused_list = snapshot_metadata.get("correlated_relationships")
        ownership = {
            str(address): dict(claim)
            for address, claim in dict(
                snapshot_metadata.get("address_ownership") or {}
            ).items()
        }
        fused_pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for item in fused_list or ():
            fused = dict(item)
            pair = (str(fused["left_device_id"]), str(fused["right_device_id"]))
            fused_pairs[pair] = fused

        def _resolve_target(edge: Mapping, edge_metadata: dict) -> str | None:
            """Remote endpoint via hostname/alias/management map, then the
            enterprise address ownership index (an owned interface,
            loopback, secondary, or router-id address resolves onto its
            owner — never onto a phantom node)."""

            direct = hostname_to_id.get(str(edge["remote_hostname"]).casefold())
            if direct is not None:
                return direct
            for candidate in (
                edge_metadata.get("adjacency_address"),
                edge_metadata.get("peer_address"),
                edge.get("remote_management_ip"),
                edge.get("remote_hostname"),
            ):
                claim = ownership.get(str(candidate or "").strip())
                if claim is not None:
                    return str(claim["device_id"])
            return None

        logical_edges: dict[tuple, dict[str, Any]] = {}
        covered_pairs: set[tuple[str, str]] = set()
        for edge in self._snapshot.edges:
            remote_hostname = str(edge["remote_hostname"])
            edge_metadata = dict(edge.get("metadata") or {})
            relation = relationship_kind(str(edge["protocol"]), edge_metadata)
            target_id = _resolve_target(edge, edge_metadata)
            source_for_pair = str(edge["local_device_id"])
            if target_id is not None:
                pair = tuple(sorted((source_for_pair, target_id)))
                if pair in fused_pairs:
                    # The fused relationship renders this pair; the raw
                    # observation stays available as its evidence.
                    covered_pairs.add(pair)
                    continue
            if target_id is None:
                target_id = f"observed:{remote_hostname.casefold()}"
                # An observed-but-undiscovered peer: honest unresolved
                # semantics (PR-043.1) — never presented as a discovered
                # device, never given an invented management address.
                unresolved_label = (
                    "Unknown router"
                    if relation in (RELATION_ROUTING, RELATION_PEER)
                    else "Observed neighbor"
                )
                nodes.setdefault(
                    target_id,
                    {
                        "data": {
                            "id": target_id,
                            "label": remote_hostname,
                            "hostname": remote_hostname,
                            "aliases": [],
                            "management_ip": edge["remote_management_ip"]
                            or "Unknown",
                            "vendor": "unknown",
                            "platform": unresolved_label,
                            "os": "unknown",
                            "interfaces": 0,
                            "kind": "observed",
                            "role": ROLE_UNRESOLVED,
                            "role_evidence": (
                                f"observed via {str(edge['protocol']).upper()} "
                                "only — not discovered"
                            ),
                            "stencil": stencil_data_uri(ROLE_UNRESOLVED),
                            "observed_via": str(edge["protocol"]).upper(),
                            "router_id": str(
                                edge_metadata.get("router_id") or ""
                            ),
                            "observation": str(
                                edge_metadata.get("observation")
                                or "neighbor announcement"
                            ),
                            "discovery_status": (
                                "Not attempted — no verified management "
                                "endpoint"
                                if not edge["remote_management_ip"]
                                else "Not discovered yet"
                            ),
                            "color": _vendor_color("unknown"),
                        }
                    },
                )
            source_id = str(edge["local_device_id"])
            endpoints = sorted(
                (
                    (source_id, str(edge["local_interface"]).casefold()),
                    (target_id, str(edge["remote_interface"] or "unknown").casefold()),
                )
            )
            key = (*endpoints[0], *endpoints[1], str(edge["protocol"]))
            existing = logical_edges.get(key)
            if existing is not None:
                existing["observations"] = 2
                continue
            (end_a, iface_a), (end_b, iface_b) = endpoints
            logical_edges[key] = {
                "source": end_a,
                "target": end_b,
                "source_interface": iface_a,
                "target_interface": iface_b,
                "protocol": str(edge["protocol"]),
                "relationship": relation,
                "observations": 1,
            }

        # One edge per fused enterprise relationship (Part 9): the line
        # style is the relationship type, and the edge carries WHY it
        # exists (evidence details), WHICH commands produced it, and WHAT
        # confidence Atlas has — inspectable on click.
        for pair in sorted(fused_pairs):
            fused = fused_pairs[pair]
            left, right = pair
            if left not in nodes or right not in nodes:
                continue  # a fused pair must join two discovered devices
            evidence = [dict(item) for item in fused.get("evidence") or ()]
            # "observations" keeps its long-standing meaning: how many
            # protocol observations saw this link (2 = both directions).
            # Derived corroborations (ownership, subnets, descriptions)
            # are evidence, not observations.
            observation_count = sum(
                1 for item in evidence
                if item.get("kind") in _OBSERVATION_EVIDENCE_KINDS
            )
            logical_edges[("fused", left, right)] = {
                "source": left,
                "target": right,
                "source_interface": str(
                    fused.get("left_interface") or "unknown"
                ).casefold(),
                "target_interface": str(
                    fused.get("right_interface") or "unknown"
                ).casefold(),
                "protocol": str(
                    (min(evidence, key=lambda e: (e.get("priority", 9), e.get("kind", "")))
                     .get("kind"))
                    if evidence else "evidence"
                ),
                "relationship": _FUSED_RELATIONSHIP_CLASS.get(
                    str(fused.get("relationship_type")), "unknown"
                ),
                "fused_type": str(fused.get("relationship_type")),
                "confidence": int(fused.get("confidence") or 0),
                "evidence": [
                    {
                        "priority": item.get("priority"),
                        "kind": item.get("kind"),
                        "detail": item.get("detail"),
                        "source_command": item.get("source_command"),
                        "observed_by": item.get("observed_by"),
                    }
                    for item in evidence
                ],
                "contributing_commands": [
                    str(value) for value in fused.get("contributing_commands") or ()
                ],
                "conflicts": [str(value) for value in fused.get("conflicts") or ()],
                "observations": observation_count or len(evidence),
            }

        edges: list[dict[str, Any]] = []
        for edge_data in logical_edges.values():
            # Replace the raw evidence kind ("interface-ownership") that used
            # to be plastered on every line with a human tag; the interface
            # pair is carried for the hover tooltip and detail panel.
            edge_data["link_tag"] = _link_tag(
                edge_data.get("fused_type"),
                str(edge_data.get("relationship") or ""),
                str(edge_data.get("protocol") or ""),
            )
            digest = sha256(
                json.dumps(
                    {key: value for key, value in edge_data.items() if key != "observations"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
            edges.append({"data": {"id": f"edge:{digest}", **edge_data}})

        return {
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": sorted(edges, key=lambda item: item["data"]["id"]),
        }

    def _neighbor_counts(self) -> dict[str, int]:
        """Logical (undirected) neighbor count per discovered hostname."""

        hostname_by_id = {
            str(device["device_id"]): str(device["hostname"])
            for device in self._snapshot.devices
        }
        neighbors: dict[str, set[str]] = {}
        for edge in self._snapshot.edges:
            local = hostname_by_id.get(
                str(edge["local_device_id"]), str(edge["local_device_id"])
            )
            remote = str(edge["remote_hostname"])
            neighbors.setdefault(local.casefold(), set()).add(remote.casefold())
            neighbors.setdefault(remote.casefold(), set()).add(local.casefold())
        return {hostname: len(peers) for hostname, peers in neighbors.items()}

    def _change_status(self, hostname: str) -> str:
        assert self._change is not None
        key = hostname.casefold()
        if key in self._change["new"]:
            return "new"
        if key in self._change["changed"]:
            return "changed"
        return "none"

    def relationship_summary(self) -> dict[str, int]:
        """Honest relationship-type counts — never a bare "edges" number.

        Physical links are verified link-layer evidence; routing
        adjacencies and protocol peers are logical observations;
        unresolved peers are observed identities Atlas has not
        discovered (and never counts as devices).
        """

        elements = self.elements()
        counts = {
            "physical_links": 0,
            "routing_adjacencies": 0,
            "protocol_peers": 0,
            "verified_routed": 0,
            "unresolved_peers": 0,
        }
        for edge in elements["edges"]:
            relation = edge["data"].get("relationship")
            if relation == RELATION_PHYSICAL:
                counts["physical_links"] += 1
            elif relation == RELATION_ROUTING:
                counts["routing_adjacencies"] += 1
            elif relation == RELATION_PEER:
                counts["protocol_peers"] += 1
            elif relation == "verified-routed":
                counts["verified_routed"] += 1
        counts["unresolved_peers"] = sum(
            1
            for node in elements["nodes"]
            if node["data"].get("kind") == "observed"
        )
        return counts

    def render(self) -> str:
        template_path = Path(__file__).resolve().parent / "templates" / "topology.html"
        template = template_path.read_text(encoding="utf-8")
        elements_json = _script_json(self.elements())
        summary_json = _script_json(
            {
                "snapshot_id": self._snapshot.snapshot_id,
                "device_count": self._snapshot.device_count,
                "edge_count": self._snapshot.edge_count,
                "warning_count": len(self._snapshot.warnings),
                **self.relationship_summary(),
            }
        )
        return template.replace("__CYTOSCAPE_CDN__", CYTOSCAPE_CDN).replace(
            "__TOPOLOGY_ELEMENTS__", elements_json
        ).replace("__SNAPSHOT_SUMMARY__", summary_json)


def _change_highlights(change_report: Any | None) -> dict[str, Any] | None:
    """Normalize an optional ChangeReport (object or dict) into highlight sets."""

    if change_report is None:
        return None
    if hasattr(change_report, "to_dict"):
        change_report = change_report.to_dict()
    if not isinstance(change_report, Mapping):
        raise TypeError("change_report must be a ChangeReport, mapping, or None")
    return {
        "new": {str(name).casefold() for name in change_report.get("new_devices") or ()},
        "changed": {
            str(name).casefold() for name in change_report.get("changed_devices") or ()
        },
        "removed": tuple(
            sorted(
                {str(name) for name in change_report.get("removed_devices") or ()},
                key=str.casefold,
            )
        ),
    }


def _device_aliases(device: Any) -> tuple[str, ...]:
    metadata = device.get("metadata") or {}
    identity = metadata.get("identity") or {}
    aliases = identity.get("aliases") or ()
    return tuple(str(alias) for alias in aliases)


def _vendor_color(vendor: str) -> str:
    normalized = vendor.casefold()
    return _VENDOR_COLORS.get(normalized, _VENDOR_COLORS["unknown"])


# Friendly role captions for the node card and legend. Keyed by the actual
# classify_role constants (layer2_switch, wireless_access_point, …).
_ROLE_LABELS = {
    "router": "Router",
    "layer2_switch": "Switch",
    "layer3_switch": "L3 Switch",
    "firewall": "Firewall",
    "server": "Server",
    "linux_host": "Host",
    "wireless_access_point": "Access Point",
    "load_balancer": "Load Balancer",
    "cloud": "Cloud",
    "unknown": "Unknown device",
    "unresolved_peer": "Unresolved peer",
}


def _role_label(role: str) -> str:
    if role in _ROLE_LABELS:
        return _ROLE_LABELS[role]
    return role.replace("_", " ").replace("-", " ").title() if role else "Device"


# A short, human tag for a link — what an engineer calls it, not the internal
# evidence kind. This is what replaced "interface-ownership" plastered on
# every edge: the line style already shows physical-vs-routed, so the tag only
# names a routing protocol when that is the actual relationship.
_LINK_TAGS = {
    "verified-physical": "",
    "verified-routed": "routed",
    "physical": "",
    "layer-2": "",
    "layer-3": "L3",
    "ospf": "OSPF",
    "routing-adjacency": "OSPF",
    "bgp": "BGP",
    "protocol-peer": "BGP",
    "static": "static",
    "inferred": "inferred",
}


def _link_tag(fused_type: str | None, relationship: str, protocol: str) -> str:
    for key in (fused_type, relationship, protocol):
        if key and str(key).casefold() in _LINK_TAGS:
            return _LINK_TAGS[str(key).casefold()]
    # An observed protocol we did not map (cdp/lldp) reads fine upper-cased.
    proto = str(protocol or "").strip()
    if proto and proto not in ("interface-ownership", "evidence", "unknown"):
        return proto.upper() if len(proto) <= 5 else proto
    return ""


def _script_json(value: Any) -> str:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
