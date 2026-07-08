"""Deterministic TopologySnapshot to interactive HTML rendering."""

from __future__ import annotations

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
    def __init__(self, snapshot: TopologySnapshot) -> None:
        if not isinstance(snapshot, TopologySnapshot):
            raise TypeError("snapshot must be a TopologySnapshot")
        self._snapshot = snapshot

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
        nodes: dict[str, dict[str, Any]] = {}
        for device in self._snapshot.devices:
            device_id = str(device["device_id"])
            vendor = str(device["vendor"])
            nodes[device_id] = {
                "data": {
                    "id": device_id,
                    "label": str(device["hostname"]),
                    "hostname": str(device["hostname"]),
                    "aliases": list(_device_aliases(device)),
                    "management_ip": str(device["management_ip"]),
                    "vendor": vendor,
                    "platform": str(device["platform"]),
                    "os": f"{device['os_name']} {device['os_version']}",
                    "interfaces": len(device["interfaces"]),
                    "kind": "discovered",
                    "color": _vendor_color(vendor),
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
