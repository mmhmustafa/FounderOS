"""Deterministic TopologySnapshot to interactive HTML rendering."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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

from .stencils import STENCILS
from .stencils import role_accent as _role_accent
from .stencils import stencil_data_uri


CYTOSCAPE_VERSION = "3.29.2"
# Kept as a compatibility/exported source identifier.  Rendered viewers do
# not depend on this URL: Atlas embeds the audited vendored copy below so a
# topology works without Internet access and under the application's CSP.
CYTOSCAPE_CDN = (
    f"https://unpkg.com/cytoscape@{CYTOSCAPE_VERSION}/dist/cytoscape.min.js"
)

_TOPOLOGY_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "topology.html"
_CYTOSCAPE_VENDOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "static"
    / "vendor"
    / "cytoscape.min.js"
)


def _visual_style_version() -> str:
    """Fingerprint every source that determines the rendered viewer's look.

    The version is content-derived so a future template or stencil change
    automatically makes current saved viewers stale after the process reloads.
    Snapshot data is deliberately excluded: it changes the graph, not the
    visual contract used to draw it.
    """

    digest = sha256(_TOPOLOGY_TEMPLATE_PATH.read_bytes())
    digest.update(b"\0cytoscape\0")
    digest.update(_CYTOSCAPE_VENDOR_PATH.read_bytes())
    for role in sorted(STENCILS):
        digest.update(b"\0role\0")
        digest.update(role.encode("utf-8"))
        digest.update(b"\0svg\0")
        digest.update(STENCILS[role].encode("utf-8"))
    return f"1-{digest.hexdigest()}"


TOPOLOGY_VISUAL_STYLE_VERSION = _visual_style_version()
TOPOLOGY_VISUAL_STYLE_MARKER = (
    f"<!-- TOPOLOGY_VISUAL_STYLE_VERSION={TOPOLOGY_VISUAL_STYLE_VERSION} -->"
)


def topology_visual_style_is_current(html: str) -> bool:
    """Whether rendered topology HTML carries this installation's style."""

    return isinstance(html, str) and TOPOLOGY_VISUAL_STYLE_MARKER in html[:512]

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
        site_catalog: Any | None = None,
        site_overrides: Any | None = None,
        identity_resolutions: Any | None = None,
    ) -> None:
        if not isinstance(snapshot, TopologySnapshot):
            raise TypeError("snapshot must be a TopologySnapshot")
        if viewer_context is not None and not isinstance(viewer_context, Mapping):
            raise TypeError("viewer_context must be a mapping or None")
        self._snapshot = snapshot
        self._change = _change_highlights(change_report)
        self._context = dict(viewer_context or {})
        # Injectable for tests and callers with their own catalog; None means
        # the operator's workspace catalog.
        self._site_catalog = site_catalog
        self._site_overrides = site_overrides
        # Operator peer-identity resolutions (identity/resolutions.py):
        # "this observed peer IS that discovered device". Applied when
        # resolving edge endpoints, with full provenance on the edge.
        self._identity_resolutions = identity_resolutions
        self._identity_loaded = identity_resolutions is not None

    def _identity_catalog(self):
        """The peer-resolution catalog: injected, else the workspace's."""

        if not self._identity_loaded:
            try:
                from founderos_atlas.identity import PeerResolutionRepository

                self._identity_resolutions = PeerResolutionRepository().load()
            except Exception:  # noqa: BLE001 - absent curation is a state
                self._identity_resolutions = None
            self._identity_loaded = True
        return self._identity_resolutions

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
        routing_facts = {
            str(name).casefold(): dict(value)
            for name, value in (self._context.get("routing_facts") or {}).items()
            if isinstance(value, Mapping)
        }
        nodes: dict[str, dict[str, Any]] = {}
        for device in self._snapshot.devices:
            device_id = str(device["device_id"])
            vendor = str(device["vendor"])
            hostname_key = str(device["hostname"]).casefold()
            depth = (device.get("metadata") or {}).get("discovery_depth")
            role, role_evidence = classify_role(device)
            hostname = str(device["hostname"])
            mgmt = str(device["management_ip"] or "").strip()
            routing = _device_routing_view(
                device,
                routing_facts.get(hostname_key, {}),
            )
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
                "serial_number": device.get("serial_number"),
                **routing,
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
                        # Same display rule as every node: no display_label,
                        # no nameplate.
                        "display_label": f"{hostname}\nno longer discovered",
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

        resolutions = self._identity_catalog()
        operator_resolved: dict[str, dict[str, str]] = {}

        def _resolve_target(edge: Mapping, edge_metadata: dict) -> str | None:
            """Remote endpoint via hostname/alias/management map, then the
            enterprise address ownership index (an owned interface,
            loopback, secondary, or router-id address resolves onto its
            owner — never onto a phantom node), then any operator
            peer-identity resolution (identity/resolutions.py) — a durable
            audited decision, never a guess of Atlas's own."""

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
            if resolutions is not None:
                for candidate in (
                    edge.get("remote_hostname"),
                    edge_metadata.get("adjacency_address"),
                    edge_metadata.get("peer_address"),
                    edge.get("remote_management_ip"),
                ):
                    label = str(candidate or "").strip()
                    if not label:
                        continue
                    resolution = resolutions.find(label)
                    if resolution is None:
                        continue
                    resolved = hostname_to_id.get(
                        resolution.resolved_hostname.casefold()
                    )
                    if resolved is not None:
                        operator_resolved[resolved] = {
                            "peer_label": resolution.peer_label,
                            "resolved_by": resolution.created_by,
                            "resolved_at": resolution.created_at,
                            "reason": resolution.reason or "",
                        }
                        return resolved
            return None

        logical_edges: dict[tuple, dict[str, Any]] = {}
        covered_pairs: set[tuple[str, str]] = set()
        for edge in self._snapshot.edges:
            remote_hostname = str(edge["remote_hostname"])
            edge_metadata = dict(edge.get("metadata") or {})
            relation = relationship_kind(str(edge["protocol"]), edge_metadata)
            operator_resolved.clear()
            target_id = _resolve_target(edge, edge_metadata)
            edge_resolution = (
                operator_resolved.get(target_id) if target_id else None
            )
            if edge_resolution is not None:
                edge_metadata["identity_resolution"] = edge_resolution
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
                            # The stylesheet renders display_label; without it
                            # an unresolved peer drew as a bare "?" with no
                            # name — indistinguishable from every other one.
                            # Say what was observed and how.
                            "display_label": (
                                f"{remote_hostname}\n"
                                f"{str(edge['protocol']).upper()} peer — unresolved"
                            ),
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
            if edge_resolution is not None:
                # Provenance: this endpoint was joined by an audited
                # operator decision, and the edge says so on click.
                logical_edges[key]["identity_resolution"] = dict(edge_resolution)

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
                # Which protocols' observations support this link. The
                # fused TYPE names only the strongest evidence, so a BGP
                # session on a link that is also verified-routed is
                # invisible in the type — and the per-protocol views ask
                # exactly that question. Falls back to the evidence's own
                # protocols for snapshots written before the field
                # existed.
                "protocols": sorted({
                    str(value).casefold()
                    for value in (
                        fused.get("contributing_protocols")
                        or [item.get("protocol") for item in evidence]
                    )
                    if value
                }),
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

    def relationship_summary(
        self,
        elements: dict | None = None,
        *,
        site_membership: Mapping[str, str] | None = None,
    ) -> dict[str, int]:
        """The canonical topology counts (see topology/vocabulary.py).

        Every surface showing a topology number counts through the one
        vocabulary module, so the viewer summary, Mission tiles, the
        topology page, exports, and APIs can never disagree. The legacy
        key names (``protocol_peers``, ``verified_routed``,
        ``unresolved_peers``) are kept alongside the canonical ones.
        """

        from founderos_atlas.topology.vocabulary import count_topology

        if elements is None:
            elements = self.elements()
        if site_membership is None:
            try:
                site_membership = self.site_view(elements).get("membership")
            except Exception:  # noqa: BLE001 - no site data is a state
                site_membership = None
        counts = count_topology(elements, site_membership=site_membership)
        return {
            **counts.to_dict(),
            # Long-standing aliases consumed by existing templates/tests.
            "protocol_peers": counts.bgp_peerings,
            "verified_routed": counts.verified_routed_links,
            "unresolved_peers": counts.unresolved_peer_identities,
        }


    def site_view(self, elements) -> dict:
        """Effective sites: inference underneath, durable overrides on top."""

        from founderos_atlas.sites import (
            SITE_TYPE_SITE,
            SiteCatalogRepository,
            SiteOverrideCatalog,
            SiteOverrideRepository,
        )
        from founderos_atlas.sites.inference import SiteInferenceEngine

        catalog = self._site_catalog
        if catalog is None:
            try:
                catalog = SiteCatalogRepository().load()
            except Exception:  # noqa: BLE001 - no catalog is a state, not an error
                catalog = None
        if catalog is None or not catalog.sites:
            return {
                "sites": [], "membership": {}, "aggregated_edges": [],
                "site_options": [], "override_revision": 0,
            }
        overrides = self._site_overrides
        if overrides is None:
            try:
                overrides = SiteOverrideRepository().load()
            except Exception:  # noqa: BLE001 - curation absence is a state
                overrides = SiteOverrideCatalog()
        engine = SiteInferenceEngine(catalog)
        names = {site.site_id: site.name for site in catalog.sites}
        types = {site.site_id: site.site_type for site in catalog.sites}

        membership: dict[str, str] = {}
        for node in elements["nodes"]:
            data = node["data"]
            if data.get("kind") == "observed":
                continue
            verdict = engine.assign(
                hostname=data.get("hostname"),
                management_ips=tuple(
                    ip for ip in (data.get("management_ip"),)
                    if ip and ip != "Unknown"
                ),
                device_ids=(data.get("id"),),
            )
            inferred = (
                verdict.site_id if verdict.status == "assigned" else None
            )
            override = overrides.find(
                device_id=data.get("id"),
                hostname=data.get("hostname"),
                management_ip=data.get("management_ip"),
                serial_number=data.get("serial_number"),
                vendor=data.get("vendor"),
            )
            # ``__none__`` is the explicit operator choice "site not
            # identified". It is a real curation state, not a catalog row,
            # and therefore must not be mistaken for an orphaned site.
            orphaned = bool(
                override
                and override.site_id != "__none__"
                and override.site_id not in names
            )
            effective = (
                override.site_id if override and not orphaned else inferred
            )
            membership[data["id"]] = effective or "__none__"
            conflict = bool(
                override
                and override.site_id != (inferred or "__none__")
            )
            data["site_assignment"] = {
                "source": "operator" if override and not orphaned else (
                    "inferred" if inferred else "unknown"
                ),
                "effective_site_id": effective,
                "effective_site_name": names.get(effective, "Site not identified"),
                "inferred_site_id": inferred,
                "inferred_site_name": names.get(inferred) if inferred else None,
                "subject_key": override.subject_key if override else None,
                "override_revision": overrides.revision,
                "override_reason": override.reason if override else None,
                "conflict": conflict,
                "orphaned": orphaned,
                "evidence": verdict.to_dict(),
            }
        # An unresolved peer: FIRST try assigning evidence about the far end
        # itself — the peer announced a name, and if that name matches a site
        # convention the link it carries is honestly inter-site. Only when no
        # far-end evidence exists does the peer stay drawn beside the first
        # discovered device that observed it. This is the fix for the old
        # contradiction where every WAN peer inherited its observer's site and
        # the site view therefore reported zero inter-site links while the
        # interface evidence plainly named the far city.
        observed_nodes = {
            node["data"]["id"]: node["data"]
            for node in elements["nodes"]
            if node["data"].get("kind") == "observed"
        }
        for observed_id, data in observed_nodes.items():
            if observed_id in membership:
                continue
            verdict = engine.assign(hostname=data.get("hostname"))
            if verdict.status == "assigned" and verdict.site_id:
                membership[observed_id] = verdict.site_id
                data["site_assignment"] = {
                    "source": "far-end-evidence",
                    "effective_site_id": verdict.site_id,
                    "effective_site_name": names.get(
                        verdict.site_id, verdict.site_id
                    ),
                    "confidence": verdict.confidence,
                    "evidence": verdict.to_dict(),
                }
        for edge in elements["edges"]:
            data = edge["data"]
            for observed, seen_by in ((data["target"], data["source"]),
                                      (data["source"], data["target"])):
                if observed.startswith("observed:") and observed not in membership:
                    owner = membership.get(seen_by)
                    if owner:
                        membership[observed] = owner
                        node = observed_nodes.get(observed)
                        if node is not None and "site_assignment" not in node:
                            node["site_assignment"] = {
                                "source": "observed-from",
                                "effective_site_id": owner,
                                "effective_site_name": names.get(owner, owner),
                                "confidence": None,
                                "evidence": {
                                    "detail": (
                                        "no far-end site evidence; drawn "
                                        "beside the device that observed it"
                                    )
                                },
                            }

        by_site: dict[str, list] = {}
        for node in elements["nodes"]:
            site_id = membership.get(node["data"]["id"])
            if site_id:
                by_site.setdefault(site_id, []).append(node["data"])
        if set(by_site) <= {"__none__"}:
            return {
                "sites": [], "membership": {}, "aggregated_edges": [],
                "site_options": [
                    {"site_id": site.site_id, "name": site.name,
                     "site_type": site.site_type}
                    for site in catalog.sites
                ],
                "override_revision": overrides.revision,
            }

        sites = []
        for site_id, members in sorted(by_site.items()):
            label = names.get(site_id, "Site not identified")
            site_type = types.get(site_id, SITE_TYPE_SITE)
            roles: dict[str, int] = {}
            for member in members:
                role = str(member.get("role") or "unknown")
                roles[role] = roles.get(role, 0) + 1
            sites.append({
                "id": "site:" + site_id,
                "site_id": site_id,
                "label": label,
                "display_label": label + chr(10) + str(len(members)) + " devices",
                "count": len(members),
                "roles": dict(sorted(roles.items())),
                "site_type": site_type,
                "stencil": stencil_data_uri(
                    "site" if site_type == SITE_TYPE_SITE
                    else "site-" + site_type
                ),
                "kind": "site",
                "evidence": (
                    "membership from the Site Catalog via multi-signal "
                    "inference (hostname convention, explicit assignment, "
                    "subnet corroboration)"
                    if site_id != "__none__" else
                    "no assigning site signal was observed for these devices"
                ),
            })

        strength = {"physical": 4, "verified-routed": 3,
                    "routing-adjacency": 2, "protocol-peer": 1, "unknown": 0}
        observed_at = str(self._context.get("last_discovered") or "") or str(
            getattr(self._snapshot, "created_at", "") or ""
        )
        aggregates: dict = {}
        inter_site_links: list[dict[str, Any]] = []
        node_labels = {
            node["data"]["id"]: str(node["data"].get("label") or node["data"]["id"])
            for node in elements["nodes"]
        }
        for edge in elements["edges"]:
            data = edge["data"]
            a = membership.get(data["source"])
            b = membership.get(data["target"])
            if not a or not b or a == b:
                continue
            # A link into the "no site evidence" cloud is drawn on the map
            # (aggregated below) but is NOT an inter-site link — the
            # canonical definition requires two KNOWN sites, and the page
            # table must agree with the counted tile to the row.
            crosses_known_sites = "__none__" not in (a, b)
            # Verified: both endpoints are discovered devices whose sites are
            # known. Observed: one endpoint is an unresolved peer whose site
            # comes from far-end evidence — real, but resting on the peer's
            # announced identity rather than a completed discovery.
            unresolved_end = (
                data["source"] if str(data["source"]).startswith("observed:")
                else data["target"] if str(data["target"]).startswith("observed:")
                else None
            )
            verification = "verified" if unresolved_end is None else "observed"
            key = tuple(sorted((a, b)))
            entry = aggregates.setdefault(key, {
                "id": "agg:" + key[0] + "~" + key[1],
                "source": "site:" + key[0], "target": "site:" + key[1],
                "count": 0, "relationship": "unknown", "members": [],
                "verification": "observed",
                "observed_at": observed_at or None,
            })
            entry["count"] += 1
            entry["members"].append(data["id"])
            if verification == "verified":
                entry["verification"] = "verified"
            kind = str(data.get("relationship") or "unknown")
            if strength.get(kind, 0) > strength.get(entry["relationship"], 0):
                entry["relationship"] = kind
            if not crosses_known_sites:
                continue
            inter_site_links.append({
                "sites": list(key),
                "edge_id": data["id"],
                "left": node_labels.get(str(data["source"]), str(data["source"])),
                "right": node_labels.get(str(data["target"]), str(data["target"])),
                "left_interface": data.get("source_interface"),
                "right_interface": data.get("target_interface"),
                "relationship": kind,
                "verification": verification,
                "confidence": data.get("confidence"),
                "evidence": [
                    str(item.get("detail") or "")
                    for item in (data.get("evidence") or ())
                ][:4] or [
                    f"observed via {str(data.get('protocol') or 'unknown').upper()}"
                ],
                "observed_at": observed_at or None,
            })
        for entry in aggregates.values():
            plural = "s" if entry["count"] != 1 else ""
            entry["display_label"] = str(entry["count"]) + " link" + plural
            entry["members"] = sorted(entry["members"])

        # WAN peers with NO far-end site evidence are candidate inter-site
        # links: shown as an explanation, never as a counted link — resolving
        # the peer's identity is what turns a candidate into a link.
        candidates = []
        for observed_id, data in observed_nodes.items():
            assignment = data.get("site_assignment") or {}
            if assignment.get("source") == "observed-from":
                candidates.append({
                    "peer": str(data.get("label") or observed_id),
                    "observed_from_site": assignment.get("effective_site_id"),
                    "detail": (
                        "far-end identity unresolved — resolve this peer to "
                        "a device to confirm or rule out an inter-site link"
                    ),
                })

        return {
            "sites": sites,
            "membership": membership,
            "aggregated_edges": [aggregates[k] for k in sorted(aggregates)],
            "inter_site_links": sorted(
                inter_site_links, key=lambda item: (item["sites"], item["edge_id"])
            ),
            "candidate_inter_site_peers": sorted(
                candidates, key=lambda item: item["peer"]
            ),
            "site_options": [
                {"site_id": site.site_id, "name": site.name,
                 "site_type": site.site_type}
                for site in catalog.sites
            ],
            "override_revision": overrides.revision,
        }

    def routing_view(self, elements: dict) -> dict:
        """Derived protocol domains for dedicated evidence-aware views."""

        nodes = {
            item["data"]["id"]: item["data"] for item in elements["nodes"]
            if item["data"].get("kind") not in ("observed", "removed")
        }
        ospf_members: dict[tuple[str, str, str], set[str]] = {}
        bgp_members: dict[tuple[str, str], set[str]] = {}
        for node_id, data in nodes.items():
            for item in data.get("ospf_memberships") or ():
                key = (
                    str(item.get("vrf") or "default"),
                    str(item.get("process_id") or "domain"),
                    str(item.get("area_id") or "unobserved"),
                )
                ospf_members.setdefault(key, set()).add(node_id)
            for item in data.get("bgp_memberships") or ():
                local_as = str(item.get("local_as") or "").strip()
                if local_as:
                    # Snapshots recorded before the VRF-parse fix carry a
                    # phantom "default)" VRF; punctuation is not identity,
                    # so normalize here too — old evidence renders one
                    # domain, not a duplicate empty box.
                    vrf = (
                        str(item.get("vrf") or "default").strip(") ")
                        or "default"
                    )
                    key = (vrf, local_as)
                    bgp_members.setdefault(key, set()).add(node_id)

        ospf_edge_ids = {
            item["data"]["id"] for item in elements["edges"]
            if _edge_is_protocol(item["data"], "ospf")
        }
        bgp_edge_ids = {
            item["data"]["id"] for item in elements["edges"]
            if _edge_is_protocol(item["data"], "bgp")
        }
        ospf_groups, ospf_assignment = _protocol_groups(
            protocol="ospf", members=ospf_members,
            elements=elements, relevant_edges=ospf_edge_ids,
        )
        bgp_groups, bgp_assignment = _protocol_groups(
            protocol="bgp", members=bgp_members,
            elements=elements, relevant_edges=bgp_edge_ids,
        )

        # Operational enrichment — everything below is read from observed
        # evidence on the member devices; nothing is inferred beyond it.
        for group in ospf_groups:
            vrf = str(group.get("vrf") or "default")
            states: set[str] = set()
            all_states: list[str] = []
            abrs: list[str] = []
            dual_speakers: list[str] = []
            for node_id in group["members"]:
                data = nodes.get(node_id) or {}
                for adjacency in data.get("ospf_adjacencies") or ():
                    if str(adjacency.get("vrf") or "default") == vrf:
                        state = str(adjacency.get("state") or "").strip()
                        if state:
                            states.add(state)
                        all_states.append(state)
                areas = {
                    str(item.get("area_id"))
                    for item in data.get("ospf_memberships") or ()
                    if str(item.get("vrf") or "default") == vrf
                    and str(item.get("area_id") or "") not in ("", "unobserved")
                }
                label = str(data.get("label") or node_id)
                if len(areas) > 1:
                    # Membership in two or more areas IS the ABR definition.
                    abrs.append(label)
                if data.get("bgp_memberships"):
                    # Honest wording: an OSPF router that also speaks BGP is
                    # an ASBR *candidate*; redistribution is not observed.
                    dual_speakers.append(label)
            group["states"] = sorted(states)
            simple = [_ospf_state_of(state) for state in all_states]
            group["adjacency_count"] = len(all_states)
            group["adjacencies_full"] = sum(
                1 for state in simple if state == _OSPF_FULL
            )
            # Named separately because it is NOT a fault: DROther pairs
            # rest here by design, and lumping it in with "not full"
            # would report a healthy segment as degraded.
            group["adjacencies_two_way"] = sum(
                1 for state in simple if state in _OSPF_BY_DESIGN
            )
            group["adjacencies_forming"] = sum(
                1 for state in simple if state in _OSPF_FORMING
            )
            group["health"] = _ospf_health(all_states)
            group["roles"] = (
                [f"ABR: {name}" for name in sorted(abrs)]
                + [f"ASBR candidate (also BGP): {name}"
                   for name in sorted(dual_speakers)]
            )
        for group in bgp_groups:
            vrf = str(group.get("vrf") or "default")
            local_as = str(group.get("local_as") or "")
            states = set()
            all_states: list[str] = []
            prefixes = 0
            prefixes_seen = False
            ebgp = ibgp = unknown_kind = 0
            for node_id in group["members"]:
                data = nodes.get(node_id) or {}
                for session in data.get("bgp_sessions") or ():
                    if str(session.get("vrf") or "default") != vrf:
                        continue
                    state = str(session.get("state") or "").strip()
                    if state:
                        states.add(state)
                    all_states.append(state)
                    accepted = session.get("accepted_prefixes")
                    if isinstance(accepted, int):
                        prefixes += accepted
                        prefixes_seen = True
                    remote = str(session.get("remote_as") or "").strip()
                    if not remote or not local_as:
                        unknown_kind += 1
                    elif remote == local_as:
                        ibgp += 1
                    else:
                        ebgp += 1
            group["states"] = sorted(states)
            group["session_count"] = len(all_states)
            group["sessions_established"] = sum(
                1 for state in all_states
                if state.strip().casefold() == HEALTH_ESTABLISHED
            )
            group["health"] = _session_health(all_states)
            # Reported only when a device actually gave a number: zero
            # prefixes and "not told" are different facts.
            group["prefixes_received"] = prefixes if prefixes_seen else None
            kinds = []
            if ebgp:
                kinds.append(f"{ebgp} eBGP")
            if ibgp:
                kinds.append(f"{ibgp} iBGP")
            if unknown_kind:
                kinds.append(f"{unknown_kind} unknown kind")
            group["session_kinds"] = kinds

        # Per-LINK health, so a failing peering does not draw identically
        # to a healthy one. A session names its peer by address; the
        # enterprise ownership index says which device owns it, which is
        # the same join the path engine and the live probe already make.
        ownership = dict(
            (self._snapshot.metadata or {}).get("address_ownership") or {}
        )
        def _peer_of(*candidates) -> str | None:
            for candidate in candidates:
                claim = ownership.get(str(candidate or "").strip())
                if claim:
                    return str(dict(claim).get("device_id") or "") or None
            return None

        pair_states: dict[tuple[str, str], list[str]] = {}
        pair_prefixes: dict[tuple[str, str], int] = {}
        ospf_pair_states: dict[tuple[str, str], list[str]] = {}
        for node_id, data in nodes.items():
            for session in data.get("bgp_sessions") or ():
                peer_id = _peer_of(session.get("peer_address"))
                if not peer_id or peer_id == node_id:
                    continue
                key = tuple(sorted((node_id, peer_id)))
                pair_states.setdefault(key, []).append(
                    str(session.get("state") or "")
                )
                accepted = session.get("accepted_prefixes")
                if isinstance(accepted, int):
                    pair_prefixes[key] = pair_prefixes.get(key, 0) + accepted
            for adjacency in data.get("ospf_adjacencies") or ():
                # The adjacency address is the neighbour's interface; the
                # router id identifies it when the address is not owned.
                peer_id = _peer_of(
                    adjacency.get("adjacency_address"),
                    adjacency.get("neighbor_router_id"),
                )
                if not peer_id or peer_id == node_id:
                    continue
                key = tuple(sorted((node_id, peer_id)))
                ospf_pair_states.setdefault(key, []).append(
                    str(adjacency.get("state") or "")
                )
        for item in elements["edges"]:
            data = item["data"]
            key = tuple(sorted((str(data["source"]), str(data["target"]))))
            if data["id"] in bgp_edge_ids:
                observed = pair_states.get(key)
                if observed is not None:
                    data["bgp_health"] = _session_health(observed)
                    data["bgp_sessions_observed"] = len(observed)
                    if key in pair_prefixes:
                        data["bgp_prefixes_received"] = pair_prefixes[key]
            if data["id"] in ospf_edge_ids:
                observed = ospf_pair_states.get(key)
                if observed is not None:
                    data["ospf_health"] = _ospf_health(observed)
                    data["ospf_adjacencies_observed"] = len(observed)
                    data["ospf_states"] = sorted(
                        {state for state in observed if state}
                    )

        return {
            "ospf": {
                "groups": ospf_groups,
                "membership": ospf_assignment,
                "edge_ids": sorted(ospf_edge_ids),
                "covered_devices": len(ospf_assignment),
                "total_devices": len(nodes),
                "adjacencies": sum(
                    int(group.get("adjacency_count") or 0)
                    for group in ospf_groups
                ),
                "adjacencies_full": sum(
                    int(group.get("adjacencies_full") or 0)
                    for group in ospf_groups
                ),
                "adjacencies_two_way": sum(
                    int(group.get("adjacencies_two_way") or 0)
                    for group in ospf_groups
                ),
                "health": _ospf_health(
                    state
                    for group in ospf_groups
                    for state in (group.get("states") or ())
                ),
            },
            "bgp": {
                "groups": bgp_groups,
                "membership": bgp_assignment,
                "edge_ids": sorted(bgp_edge_ids),
                "covered_devices": len(bgp_assignment),
                "total_devices": len(nodes),
                "sessions": sum(
                    int(group.get("session_count") or 0)
                    for group in bgp_groups
                ),
                "sessions_established": sum(
                    int(group.get("sessions_established") or 0)
                    for group in bgp_groups
                ),
                "health": _session_health(
                    state
                    for group in bgp_groups
                    for state in (group.get("states") or ())
                ),
            },
        }

    def render(self) -> str:
        template = _TOPOLOGY_TEMPLATE_PATH.read_text(encoding="utf-8")
        elements = self.elements()
        site_view = self.site_view(elements)
        routing_view = self.routing_view(elements)
        identity_catalog = self._identity_catalog()
        curation_marker = (
            "<!-- ATLAS_SITE_OVERRIDE_REVISION="
            + str(site_view.get("override_revision") or 0)
            + " -->\n<!-- ATLAS_IDENTITY_RESOLUTION_REVISION="
            + str(getattr(identity_catalog, "revision", 0) or 0)
            + " -->"
        )
        if template.startswith("<!doctype html>"):
            template = template.replace(
                "<!doctype html>",
                f"<!doctype html>\n{TOPOLOGY_VISUAL_STYLE_MARKER}"
                f"\n{curation_marker}",
                1,
            )
        else:
            template = (
                f"{TOPOLOGY_VISUAL_STYLE_MARKER}\n{curation_marker}\n{template}"
            )
        elements_json = _script_json(elements)
        summary_json = _script_json(
            {
                "snapshot_id": self._snapshot.snapshot_id,
                "device_count": self._snapshot.device_count,
                "edge_count": self._snapshot.edge_count,
                "warning_count": len(self._snapshot.warnings),
                **self.relationship_summary(
                    elements, site_membership=site_view.get("membership")
                ),
            }
        )
        site_json = _script_json(site_view)
        routing_json = _script_json(routing_view)
        # The viewer is both embedded by /topology and usable as a saved
        # standalone artifact.  Embedding the pinned local dependency avoids
        # an Internet/CDN requirement and ensures ``cytoscape`` exists before
        # the viewer's initialization script executes.
        cytoscape_source = _CYTOSCAPE_VENDOR_PATH.read_text(encoding="utf-8")
        return template.replace("__CYTOSCAPE_SOURCE__", cytoscape_source).replace(
            "__TOPOLOGY_ELEMENTS__", elements_json
        ).replace("__SNAPSHOT_SUMMARY__", summary_json).replace(
            "__SITE_VIEW__", site_json
        ).replace(
            "__ROUTING_VIEW__", routing_json
        )


def _device_routing_view(device: Mapping, configured: Mapping) -> dict[str, Any]:
    metadata = dict(device.get("metadata") or {})
    operational = dict(metadata.get("routing_evidence") or {})
    ospf_adjacencies = [
        dict(item) for item in operational.get("ospf_adjacencies") or ()
        if isinstance(item, Mapping)
    ]
    bgp_sessions = [
        dict(item) for item in operational.get("bgp_sessions") or ()
        if isinstance(item, Mapping)
    ]

    ospf_memberships: list[dict[str, Any]] = []
    areas = [str(value) for value in configured.get("ospf_areas") or ()]
    interface_areas = {
        str(item.get("interface")): str(item.get("area"))
        for item in configured.get("ospf_interfaces") or ()
        if isinstance(item, Mapping) and item.get("interface") and item.get("area")
    }
    processes = [
        str(value) for value in configured.get("ospf_process_ids") or ()
    ] or ["domain"]
    vrfs = [str(value) for value in configured.get("vrfs") or ()] or ["default"]
    for area in areas:
        for process in processes:
            item = {
                "area_id": area,
                "process_id": process,
                "vrf": "default" if "default" in vrfs else vrfs[0],
                "address_family": "ipv4",
                "evidence_state": "configured-only",
            }
            if item not in ospf_memberships:
                ospf_memberships.append(item)
    for adjacency in ospf_adjacencies:
        observed_area = adjacency.get("area_id")
        if not observed_area:
            observed_area = interface_areas.get(
                str(adjacency.get("local_interface") or "")
            )
        if not observed_area and len(areas) == 1:
            observed_area = areas[0]
        item = {
            "area_id": observed_area or "unobserved",
            "process_id": adjacency.get("process_id") or "domain",
            "vrf": adjacency.get("vrf") or "default",
            "address_family": adjacency.get("address_family") or "ipv4",
            "evidence_state": "observed",
        }
        # An operational adjacency with unknown area must not overwrite a
        # configured, more-specific area membership.
        if item["area_id"] != "unobserved" or not ospf_memberships:
            if item not in ospf_memberships:
                ospf_memberships.append(item)

    configured_as = str(configured.get("bgp_as") or "").strip() or None
    bgp_memberships: list[dict[str, Any]] = []
    if configured_as:
        bgp_memberships.append({
            "local_as": configured_as,
            "vrf": "default",
            "address_family": "ipv4-unicast",
            "evidence_state": "configured-only",
        })
    for session in bgp_sessions:
        local_as = str(session.get("local_as") or configured_as or "").strip()
        if not local_as:
            continue
        item = {
            "local_as": local_as,
            "vrf": session.get("vrf") or "default",
            "address_family": session.get("address_family") or "ipv4-unicast",
            "evidence_state": "observed",
        }
        existing = next(
            (
                value for value in bgp_memberships
                if value["local_as"] == item["local_as"]
                and value["vrf"] == item["vrf"]
            ),
            None,
        )
        if existing:
            existing["evidence_state"] = "observed"
        else:
            bgp_memberships.append(item)
    observed_peers = {
        str(item.get("peer_address")) for item in bgp_sessions
        if item.get("peer_address")
    }
    for neighbor in configured.get("bgp_neighbors") or ():
        if not isinstance(neighbor, Mapping):
            continue
        peer = str(neighbor.get("neighbor") or "").strip()
        if not peer or peer in observed_peers:
            continue
        bgp_sessions.append({
            "peer_address": peer,
            "remote_as": neighbor.get("remote_as"),
            "local_as": configured_as,
            "state": "configured",
            "vrf": "default",
            "address_family": "ipv4-unicast",
            "evidence_state": "configured-only",
            "source_command": "running configuration",
        })
    return {
        "ospf_memberships": ospf_memberships,
        "ospf_adjacencies": ospf_adjacencies,
        "bgp_memberships": bgp_memberships,
        "bgp_sessions": bgp_sessions,
        "routing_vrfs": vrfs,
    }


def _edge_is_protocol(data: Mapping, protocol: str) -> bool:
    values = {
        str(data.get("protocol") or "").casefold(),
        str(data.get("fused_type") or "").casefold(),
        str(data.get("link_tag") or "").casefold(),
    }
    # A fused link reports its STRONGEST evidence as its type, so a BGP
    # peering that also had routed evidence typed as "verified-routed"
    # and matched nothing here — the AS view drew zero links over a
    # fully-meshed estate. The contributing protocols answer the
    # question the view is actually asking.
    values |= {
        str(item).casefold() for item in (data.get("protocols") or ())
    }
    if protocol == "ospf":
        return bool(values & {"ospf", "ospf-neighbor"})
    return bool(values & {"bgp", "bgp-peer"})


HEALTH_ESTABLISHED = "established"
HEALTH_DEGRADED = "degraded"
HEALTH_DOWN = "down"
HEALTH_UNKNOWN = "unknown"


def _session_health(states: Iterable[str]) -> str:
    """A verdict over a set of observed session states.

    Four outcomes, because three of them are different kinds of bad and
    an operator needs to tell them apart: every session up, some up
    (a partial failure, which a single "down" would hide), none up, and
    no readable state at all. An unreadable state is never counted as
    healthy — that is how a parser fault becomes a green diagram.
    """

    known = [str(state).strip().casefold() for state in states if str(state).strip()]
    if not known:
        return HEALTH_UNKNOWN
    up = [state for state in known if state == HEALTH_ESTABLISHED]
    if len(up) == len(known):
        return HEALTH_ESTABLISHED
    if up:
        return HEALTH_DEGRADED
    # Every state was read, and none of them is established. If none is
    # a state Atlas recognises, say unknown rather than asserting down.
    recognised = {"active", "idle", "connect", "opensent", "openconfirm"}
    return HEALTH_DOWN if any(s in recognised for s in known) else HEALTH_UNKNOWN


# OSPF neighbour states, by what they mean for an operator. The state
# is reported as "State/Role" (Full/DR, 2-Way/DROther), so only the part
# before the slash is the state.
_OSPF_FULL = "full"
# 2-Way between two DROther routers on a multi-access segment is the
# DESIGNED resting state — they adjacency only with the DR and BDR.
# Calling it a fault would mark a correctly built broadcast segment
# degraded, which is the fastest way to make a health signal ignored.
_OSPF_BY_DESIGN = {"2-way"}
_OSPF_FORMING = {"init", "attempt", "exstart", "exchange", "loading"}
_OSPF_DOWN = {"down"}


def _ospf_state_of(value: str) -> str:
    return str(value or "").split("/")[0].strip().casefold()


def _ospf_health(states: Iterable[str]) -> str:
    """A verdict over observed OSPF neighbour states.

    Same four outcomes as BGP so the two views read alike, with OSPF's
    own definition of "up": Full, plus the 2-Way that DROther pairs are
    supposed to sit in. A state Atlas cannot place is never counted
    healthy.
    """

    known = [_ospf_state_of(state) for state in states]
    known = [state for state in known if state]
    if not known:
        return HEALTH_UNKNOWN
    up = [
        state for state in known
        if state == _OSPF_FULL or state in _OSPF_BY_DESIGN
    ]
    if len(up) == len(known):
        return HEALTH_ESTABLISHED
    if up:
        return HEALTH_DEGRADED
    recognised = _OSPF_FORMING | _OSPF_DOWN
    return (
        HEALTH_DOWN if any(state in recognised for state in known)
        else HEALTH_UNKNOWN
    )


def _protocol_groups(
    *, protocol: str,
    members: Mapping[tuple, set[str]],
    elements: Mapping,
    relevant_edges: set[str],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Split reused area/ASN identifiers into connected components."""

    edges = [
        item["data"] for item in elements["edges"]
        if item["data"]["id"] in relevant_edges
    ]
    # Name the VRF only when naming it says something. On the common
    # single-VRF estate every label read "BGP default · AS 65010", where
    # "default" is the same word on every domain and pushes the number
    # that actually identifies the domain to the end. It earns its place
    # when there is more than one VRF, or when the one in use is a
    # deliberate non-default.
    group_vrfs = {str(key[0]) for key in members if key}
    name_the_vrf = len(group_vrfs) > 1 or group_vrfs not in ((), {"default"})
    groups: list[dict[str, Any]] = []
    assignment: dict[str, list[str]] = {}
    for key in sorted(members, key=lambda value: tuple(map(str, value))):
        device_ids = set(members[key])
        adjacency = {node_id: set() for node_id in device_ids}
        for edge in edges:
            left, right = edge.get("source"), edge.get("target")
            if left in device_ids and right in device_ids:
                adjacency[left].add(right)
                adjacency[right].add(left)
        components: list[list[str]] = []
        remaining = set(device_ids)
        while remaining:
            seed = min(remaining)
            stack = [seed]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                stack.extend(adjacency.get(current, ()))
            remaining.difference_update(component)
            components.append(sorted(component))
        for index, component in enumerate(components, start=1):
            if protocol == "ospf":
                vrf, process, area = key
                base_label = (
                    f"OSPF {vrf} · Area {area}" if name_the_vrf
                    else f"OSPF Area {area}"
                )
                attributes = {
                    "vrf": vrf, "process_id": process, "area_id": area,
                }
            else:
                vrf, local_as = key
                base_label = (
                    f"BGP {vrf} · AS {local_as}" if name_the_vrf
                    else f"BGP AS {local_as}"
                )
                attributes = {"vrf": vrf, "local_as": local_as}
            suffix = f" · domain {index}" if len(components) > 1 else ""
            digest = sha256(
                (protocol + repr(key) + repr(component)).encode("utf-8")
            ).hexdigest()[:12]
            group_id = f"{protocol}-domain:{digest}"
            groups.append({
                "id": group_id,
                "label": base_label + suffix,
                "kind": "protocol-domain",
                "protocol": protocol,
                "count": len(component),
                "members": component,
                **attributes,
            })
            for node_id in component:
                assignment.setdefault(node_id, []).append(group_id)
    return groups, assignment


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
