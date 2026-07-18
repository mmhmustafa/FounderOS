"""VMware NSX collector (POLYGLOT Wave 2, Tier 2).

NSX is collected through its Policy/Manager REST API — there is no
device CLI dialect to drive. The NSX Manager normalizes into one
canonical ``NetworkDevice`` (role ``sdn-manager``); segments become
interfaces (their gateway CIDR in metadata), and tier-0/tier-1 gateway
inventory plus transport-node counts ride in
``metadata["nsx_evidence"]``. Raw API responses are preserved.

The fetcher is injected and already authenticated; Atlas ships no HTTP
client or credential handling here.

Maturity: TRANSCRIPT VALIDATED against sanitized captures of NSX 4.x
API response shapes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from founderos_atlas.discovery.models import NetworkInterface

from .cloud import CloudNetworkRecord, CollectedNetwork

Fetcher = Callable[[str], str]

NODE = "/api/v1/node"
TIER0S = "/policy/api/v1/infra/tier-0s"
TIER1S = "/policy/api/v1/infra/tier-1s"
SEGMENTS = "/policy/api/v1/infra/segments"
TRANSPORT_NODES = "/api/v1/transport-nodes"


class NsxCollection:
    def __init__(self, result: CollectedNetwork,
                 raw_outputs: dict[str, str]) -> None:
        self.result = result
        self.raw_outputs = raw_outputs


class NsxCollector:
    platform_id = "vmware-nsx"
    display_name = "VMware NSX"

    def collect(self, fetch: Fetcher, *,
                management_ip: str | None = None) -> NsxCollection:
        raw: dict[str, str] = {}
        payloads: dict[str, Any] = {}
        for path in (NODE, TIER0S, TIER1S, SEGMENTS, TRANSPORT_NODES):
            try:
                body = fetch(path)
            except Exception as error:  # noqa: BLE001 - recorded, not raised
                raw[f"api:{path}"] = f"<unavailable: {str(error)[:120]}>"
                continue
            raw[f"api:{path}"] = body
            try:
                payloads[path] = json.loads(body)
            except (ValueError, TypeError):
                continue

        node = payloads.get(NODE) or {}
        hostname = str(node.get("hostname") or "nsx-manager")
        segments = (payloads.get(SEGMENTS) or {}).get("results") or ()
        tier0s = (payloads.get(TIER0S) or {}).get("results") or ()
        tier1s = (payloads.get(TIER1S) or {}).get("results") or ()
        transport = (
            payloads.get(TRANSPORT_NODES) or {}
        ).get("results") or ()

        interfaces = tuple(
            NetworkInterface(
                name=str(segment.get("display_name") or segment.get("id")),
                ip_address=None,
                status="up",
                metadata={
                    "source_command": f"api:{SEGMENTS}",
                    "cidr": str(
                        next(
                            (
                                s.get("gateway_address")
                                for s in segment.get("subnets") or ()
                                if s.get("gateway_address")
                            ),
                            "",
                        )
                    ) or None,
                    "connectivity_path": segment.get("connectivity_path"),
                },
            )
            for segment in segments
        )
        device = CloudNetworkRecord(
            device_id=f"vmware-nsx:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor="vmware",
            platform="NSX Manager",
            os_name="NSX",
            os_version=str(node.get("node_version", "unknown")),
            serial_number=str(node.get("node_uuid", "")) or None,
            metadata={
                "device_role": "sdn-manager",
                "nsx_evidence": {
                    "schema_version": "1.0.0",
                    "tier0_gateways": [
                        {
                            "name": str(t.get("display_name")),
                            "ha_mode": t.get("ha_mode"),
                        }
                        for t in tier0s
                    ],
                    "tier1_gateways": [
                        {
                            "name": str(t.get("display_name")),
                            "tier0_path": t.get("tier0_path"),
                        }
                        for t in tier1s
                    ],
                    "segment_count": len(segments),
                    "transport_node_count": len(transport),
                },
            },
        )
        return NsxCollection(
            CollectedNetwork(device=device, interfaces=interfaces,
                             neighbors=()),
            raw,
        )
