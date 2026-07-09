"""Deterministic TopologySnapshot to interactive HTML rendering."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from founderos_atlas.topology import TopologySnapshot


CYTOSCAPE_CDN = "https://unpkg.com/cytoscape@3.29.2/dist/cytoscape.min.js"
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
            node_data = {
                "id": device_id,
                "label": str(device["hostname"]),
                "hostname": str(device["hostname"]),
                "aliases": list(_device_aliases(device)),
                "management_ip": str(device["management_ip"]),
                "vendor": vendor,
                "platform": str(device["platform"]),
                "os": f"{device['os_name']} {device['os_version']}",
                "interfaces": len(device["interfaces"]),
                "neighbors": neighbor_counts.get(hostname_key, 0),
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
                        "color": "#dc2626",
                    }
                }

        logical_edges: dict[tuple, dict[str, Any]] = {}
        for edge in self._snapshot.edges:
            remote_hostname = str(edge["remote_hostname"])
            target_id = hostname_to_id.get(remote_hostname.casefold())
            if target_id is None:
                target_id = f"observed:{remote_hostname.casefold()}"
                nodes.setdefault(
                    target_id,
                    {
                        "data": {
                            "id": target_id,
                            "label": remote_hostname,
                            "hostname": remote_hostname,
                            "aliases": [],
                            "management_ip": edge["remote_management_ip"] or "unknown",
                            "vendor": "unknown",
                            "platform": "observed neighbor",
                            "os": "unknown",
                            "interfaces": 0,
                            "kind": "observed",
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
                "observations": 1,
            }

        edges: list[dict[str, Any]] = []
        for edge_data in logical_edges.values():
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


def _script_json(value: Any) -> str:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
