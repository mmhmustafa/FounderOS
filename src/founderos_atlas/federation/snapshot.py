"""Render the Enterprise Graph as a canonical ``TopologySnapshot``.

The federated snapshot uses the exact same contract as every per-profile
snapshot (content-addressed, deterministic), so every existing engine —
prediction, path intelligence, the interactive topology viewer, device
pickers — operates at enterprise scope without modification. Device ids
are enterprise ids; provenance (observed-by profiles, observation counts,
merge evidence) rides in metadata.
"""

from __future__ import annotations

from founderos_atlas.correlation import correlation_metadata
from founderos_atlas.topology import TopologySnapshot, content_address

from .models import FEDERATION_SCHEMA_VERSION, EnterpriseGraph


def build_enterprise_snapshot(graph: EnterpriseGraph) -> TopologySnapshot:
    """One deterministic snapshot spanning every contributing profile."""

    created_at = max(
        (
            contribution.observed_at
            for contribution in graph.contributions
            if contribution.observed_at
        ),
        default=None,
    )
    devices = tuple(
        _device_entry(graph, device) for device in graph.devices
    )
    edges = tuple(_edge_entry(link) for link in graph.links)
    metadata = {
        "schema_version": "1.0.0",
        "enterprise": True,
        "federation_schema_version": FEDERATION_SCHEMA_VERSION,
        "contributing_profiles": [
            {
                "profile_id": contribution.profile_id,
                "profile_name": contribution.profile_name,
                "run_id": contribution.run_id,
                "observed_at": contribution.observed_at,
            }
            for contribution in graph.contributions
        ],
        "observation_count": graph.observation_count,
        "merged_device_count": graph.merged_device_count,
        "deterministic": True,
        "in_memory_only": True,
        # Evidence Correlation runs over the FEDERATED devices and edges
        # so the enterprise snapshot carries the same knowledge keys as
        # every per-profile snapshot: address ownership spanning all
        # profiles, fused relationships (this is what resolves a peer
        # observed in one profile onto a device discovered in another),
        # honest unresolved observations, and fail-closed conflicts.
        **correlation_metadata(devices, edges, observed_at=created_at),
    }
    snapshot_id = content_address(
        created_at=created_at,
        devices=devices,
        edges=edges,
        warnings=(),
        metadata=metadata,
    )
    return TopologySnapshot(
        snapshot_id=snapshot_id,
        created_at=created_at,
        devices=devices,
        edges=edges,
        warnings=(),
        metadata=metadata,
    )


def _device_entry(graph: EnterpriseGraph, device) -> dict:
    decision = graph.decision_for(device.enterprise_id)
    interfaces = graph.interfaces.get(device.enterprise_id, ())
    return {
        "device_id": device.enterprise_id,
        "hostname": device.hostname,
        "management_ip": (
            device.management_ips[0] if device.management_ips else ""
        ),
        "vendor": device.vendor or "unknown",
        "platform": device.platform or "unknown",
        "os_name": "",
        "os_version": device.os_version or "",
        "serial_number": device.serial_number,
        "interfaces": tuple(
            {
                "name": interface.name,
                "ip_address": interface.ip_address,
                "status": interface.status,
                "protocol_status": interface.protocol_status,
                "description": interface.description,
                "metadata": {
                    **dict(interface.metadata),
                    "observed_by": list(interface.observed_by),
                },
            }
            for interface in interfaces
        ),
        "metadata": {
            **dict(
                (graph.attributes.get("device_metadata") or {}).get(
                    device.enterprise_id, {}
                )
            ),
            "enterprise_id": device.enterprise_id,
            "aliases": list(device.aliases),
            # The engine's hostname map reads identity.aliases — mirror
            # the canonical aliases there so observed names resolve.
            "identity": {"aliases": list(device.aliases)},
            "management_ips": list(device.management_ips),
            "site": device.site.label,
            "observed_by": list(device.profile_names),
            "observation_count": len(device.observations),
            "merge_confidence": (
                decision.confidence if decision is not None else None
            ),
        },
    }


def _edge_entry(link) -> dict:
    return {
        "local_device_id": link.local_enterprise_id,
        "local_interface": link.local_interface,
        "remote_hostname": link.remote_hostname,
        "remote_interface": link.remote_interface,
        "remote_management_ip": None,
        "protocol": link.protocol,
        "metadata": {
            **dict(link.metadata),
            "observed_by": list(link.observed_by),
            "cross_profile": link.cross_profile,
            "boundary": link.is_boundary,
            "observations": [item.to_dict() for item in link.observations],
        },
    }
