"""Correlation engine: link related evidence, never unrelated evidence.

Edges are drawn only along documented causal rules and only when the
observations share a device, an interface, or a real topology adjacency:

- configuration change -> interface/protocol change on the same device
  (stronger when the exact interface appears in the change lines);
- interface status change -> protocol change on the same interface;
- interface/protocol failure on D -> topology removal or discovery failure
  of a device that was adjacent to D in the previous topology;
- any failure chain -> incident evidence naming one of the same devices.

Evidence about unrelated devices is never connected.
"""

from __future__ import annotations

from .graph import CausalGraph
from .models import (
    CATEGORY_CONFIGURATION,
    CATEGORY_DISCOVERY,
    CATEGORY_INCIDENT,
    CATEGORY_INTERFACE,
    CATEGORY_PROTOCOL,
    CATEGORY_TOPOLOGY,
    EvidenceItem,
)


def previous_adjacency(previous_snapshot: dict | None) -> dict[str, set[str]]:
    """hostname -> neighbor hostnames (casefolded) from the prior topology."""

    if not isinstance(previous_snapshot, dict):
        return {}
    hostname_by_id = {
        str(device.get("device_id")): str(device.get("hostname"))
        for device in previous_snapshot.get("devices") or ()
        if isinstance(device, dict)
    }
    adjacency: dict[str, set[str]] = {}
    for edge in previous_snapshot.get("edges") or ():
        if not isinstance(edge, dict):
            continue
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        ).casefold()
        remote = str(edge.get("remote_hostname")).casefold()
        if local == remote:
            continue
        adjacency.setdefault(local, set()).add(remote)
        adjacency.setdefault(remote, set()).add(local)
    return adjacency


def hostname_for_ip(previous_snapshot: dict | None) -> dict[str, str]:
    """management IP -> hostname from the prior topology (for failed hosts)."""

    if not isinstance(previous_snapshot, dict):
        return {}
    return {
        str(device.get("management_ip")): str(device.get("hostname"))
        for device in previous_snapshot.get("devices") or ()
        if isinstance(device, dict) and device.get("management_ip")
    }


def correlate(
    evidence: tuple[EvidenceItem, ...],
    *,
    adjacency: dict[str, set[str]] | None = None,
    ip_hostnames: dict[str, str] | None = None,
) -> CausalGraph:
    graph = CausalGraph()
    adjacency = adjacency or {}
    ip_hostnames = ip_hostnames or {}
    by_category: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        by_category.setdefault(item.category, []).append(item)

    failures = [
        item
        for item in (
            list(by_category.get(CATEGORY_INTERFACE, []))
            + list(by_category.get(CATEGORY_PROTOCOL, []))
        )
        if item.attributes.get("event") in ("failure", "degradation")
    ]

    # configuration -> interface/protocol on the same device.
    for config in by_category.get(CATEGORY_CONFIGURATION, ()):
        for effect in failures:
            if not _same_device(config, effect):
                continue
            interface_match = any(
                effect.mentions_interface(interface)
                for interface in config.interfaces
            )
            graph.add_edge(
                config.evidence_id,
                effect.evidence_id,
                "interface named in the change" if interface_match
                else "same device, same interval",
            )

    # interface status -> protocol on the same interface of the same device.
    for status_item in by_category.get(CATEGORY_INTERFACE, ()):
        for protocol_item in by_category.get(CATEGORY_PROTOCOL, ()):
            if _same_device(status_item, protocol_item) and any(
                protocol_item.mentions_interface(interface)
                for interface in status_item.interfaces
            ):
                graph.add_edge(
                    status_item.evidence_id,
                    protocol_item.evidence_id,
                    "same interface",
                )

    # failure on D -> topology removal / discovery failure of a previous
    # neighbor of D. Real adjacency only — no cross-network guessing.
    downstream = list(by_category.get(CATEGORY_TOPOLOGY, ()))
    for item in by_category.get(CATEGORY_DISCOVERY, ()):
        downstream.append(item)
    for failure in failures:
        failure_device = _primary_device(failure)
        neighbors = adjacency.get(failure_device.casefold(), set())
        for effect in downstream:
            effect_device = _primary_device(effect)
            effect_hostname = ip_hostnames.get(effect_device, effect_device)
            if effect_hostname.casefold() in neighbors:
                graph.add_edge(
                    failure.evidence_id,
                    effect.evidence_id,
                    "adjacent in the previous topology",
                )

    # incident evidence attaches to chains naming the same devices.
    for incident in by_category.get(CATEGORY_INCIDENT, ()):
        incident_devices = {device.casefold() for device in incident.devices}
        if not incident_devices:
            continue
        for item in evidence:
            if item.category == CATEGORY_INCIDENT:
                continue
            if incident_devices & {device.casefold() for device in item.devices}:
                graph.add_edge(
                    item.evidence_id, incident.evidence_id, "same device in incident"
                )
    return graph


def _same_device(first: EvidenceItem, second: EvidenceItem) -> bool:
    return bool(
        {device.casefold() for device in first.devices}
        & {device.casefold() for device in second.devices}
    )


def _primary_device(item: EvidenceItem) -> str:
    return item.devices[0] if item.devices else ""
