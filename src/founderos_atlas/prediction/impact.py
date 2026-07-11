"""Blast radius: the domain model of downstream impact.

Deliberately richer than "a number of interfaces": the model carries
devices, interfaces, protocols, paths, services, applications, sites, and
a user estimate — most populated by future builders (service maps, site
catalogs) while today's estimator fills the topology-derived layers from
the dependency graph. Empty collections mean "none known", and anything
Atlas cannot see belongs in the prediction's ``unknowns``, never silently
zeroed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dependency import (
    DependencyGraph,
    KIND_APPLICATION,
    KIND_DEVICE,
    KIND_INTERFACE,
    KIND_SERVICE,
)
from .models import SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM


@dataclass(frozen=True)
class BlastRadius:
    affected_devices: tuple[str, ...] = ()
    affected_interfaces: tuple[str, ...] = ()
    affected_protocols: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    affected_services: tuple[str, ...] = ()
    affected_applications: tuple[str, ...] = ()
    affected_sites: tuple[str, ...] = ()
    estimated_users: int | None = None
    severity: str = SEVERITY_LOW
    summary: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def device_count(self) -> int:
        return len(self.affected_devices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_devices": list(self.affected_devices),
            "affected_interfaces": list(self.affected_interfaces),
            "affected_protocols": list(self.affected_protocols),
            "affected_paths": list(self.affected_paths),
            "affected_services": list(self.affected_services),
            "affected_applications": list(self.affected_applications),
            "affected_sites": list(self.affected_sites),
            "estimated_users": self.estimated_users,
            "severity": self.severity,
            "summary": self.summary,
            "attributes": dict(self.attributes),
        }


def estimate_blast_radius(
    graph: DependencyGraph,
    changed_node_id: str,
    *,
    target_label: str,
    anchor_node_id: str | None = None,
) -> BlastRadius:
    """Reachability-based impact: what LOSES connectivity, not what is near.

    A node of any kind (device, interface, service, application — future
    kinds included automatically) is affected when it is connected to the
    anchor today and disconnected once the changed node is removed. The
    anchor is the changed element's own device (or, when the device itself
    is the change, the first other device — deterministic). Richer graphs
    with service/application nodes therefore produce richer blast radii
    with zero changes here.
    """

    anchor = anchor_node_id
    if anchor is None or anchor == changed_node_id:
        others = [
            node
            for node in graph.nodes(KIND_DEVICE)
            if node.node_id != changed_node_id
        ]
        anchor = others[0].node_id if others else None
    removed = frozenset({changed_node_id})
    affected: list = []
    if anchor is not None:
        for node in graph.nodes():
            if node.node_id in (changed_node_id, anchor):
                continue
            if not graph.path_exists(anchor, node.node_id):
                continue  # never connected: not this change's impact
            if not graph.path_exists(anchor, node.node_id, without=removed):
                affected.append(node)
    devices = tuple(
        node.name for node in affected if node.kind == KIND_DEVICE
    )
    interfaces = tuple(
        f"{node.device} {node.name}" if node.device else node.name
        for node in affected
        if node.kind == KIND_INTERFACE
    )
    services = tuple(
        node.name for node in affected if node.kind == KIND_SERVICE
    )
    applications = tuple(
        node.name for node in affected if node.kind == KIND_APPLICATION
    )
    other_protocols = tuple(
        node.name
        for node in affected
        if node.kind not in (KIND_DEVICE, KIND_INTERFACE, KIND_SERVICE, KIND_APPLICATION)
    )
    if len(devices) >= 3 or applications:
        severity = SEVERITY_HIGH
    elif devices or services or other_protocols:
        severity = SEVERITY_MEDIUM
    else:
        severity = SEVERITY_LOW
    summary = (
        f"{target_label} affects {len(devices)} downstream device(s)"
        + (f", {len(services)} service(s)" if services else "")
        + (f", {len(applications)} application(s)" if applications else "")
        + "."
    )
    return BlastRadius(
        affected_devices=devices,
        affected_interfaces=interfaces,
        affected_protocols=other_protocols,
        affected_services=services,
        affected_applications=applications,
        severity=severity,
        summary=summary,
    )
