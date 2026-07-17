"""Semantic configuration difference (PR-044, Part 6).

Configuration differences become STRUCTURED EVENTS, not merely text:

    BGP Neighbor Added · BGP Neighbor Removed · OSPF Area Modified ·
    ACL Changed · Interface Shutdown · VLAN Added · VRF Removed ·
    HSRP Priority Changed · Route Map Updated · Policy Changed

Semantics are derived by comparing the NORMALIZED FACTS of two versions
(``extract.ConfigFacts``), not by pattern-matching diff text — so an event
means what it says regardless of formatting, line order, or vendor
whitespace. Text diffing remains available separately (``textual``) for the
side-by-side view.

Every event is deterministic and secret-free: facts never carry passwords,
keys, or community strings, so events built from them cannot leak one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .extract import ConfigFacts


# -- event kinds (extensible: data, not branches) ----------------------------------

BGP_NEIGHBOR_ADDED = "bgp-neighbor-added"
BGP_NEIGHBOR_REMOVED = "bgp-neighbor-removed"
BGP_NEIGHBOR_MODIFIED = "bgp-neighbor-modified"
BGP_AS_CHANGED = "bgp-as-changed"
ROUTER_ID_CHANGED = "router-id-changed"
OSPF_AREA_ADDED = "ospf-area-added"
OSPF_AREA_REMOVED = "ospf-area-removed"
INTERFACE_ADDED = "interface-added"
INTERFACE_REMOVED = "interface-removed"
INTERFACE_SHUTDOWN = "interface-shutdown"
INTERFACE_ENABLED = "interface-enabled"
INTERFACE_IP_CHANGED = "interface-ip-changed"
INTERFACE_DESCRIPTION_CHANGED = "interface-description-changed"
VLAN_ADDED = "vlan-added"
VLAN_REMOVED = "vlan-removed"
VRF_ADDED = "vrf-added"
VRF_REMOVED = "vrf-removed"
ACL_ADDED = "acl-added"
ACL_REMOVED = "acl-removed"
HSRP_PRIORITY_CHANGED = "hsrp-priority-changed"
HSRP_GROUP_ADDED = "hsrp-group-added"
HSRP_GROUP_REMOVED = "hsrp-group-removed"
ROUTE_MAP_ADDED = "route-map-added"
ROUTE_MAP_REMOVED = "route-map-removed"
STATIC_ROUTE_ADDED = "static-route-added"
STATIC_ROUTE_REMOVED = "static-route-removed"
HOSTNAME_CHANGED = "hostname-changed"
NTP_SERVER_ADDED = "ntp-server-added"
NTP_SERVER_REMOVED = "ntp-server-removed"
LOGGING_HOST_ADDED = "logging-host-added"
LOGGING_HOST_REMOVED = "logging-host-removed"
SNMP_ENABLED = "snmp-enabled"
SNMP_DISABLED = "snmp-disabled"
AAA_ENABLED = "aaa-enabled"
AAA_DISABLED = "aaa-disabled"

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
_SEVERITY_RANK = {SEVERITY_LOW: 0, SEVERITY_MEDIUM: 1, SEVERITY_HIGH: 2}

# Documented severity per event kind — a table, so new kinds extend it.
_EVENT_SEVERITY: dict[str, str] = {
    BGP_NEIGHBOR_ADDED: SEVERITY_HIGH,
    BGP_NEIGHBOR_REMOVED: SEVERITY_HIGH,
    BGP_NEIGHBOR_MODIFIED: SEVERITY_HIGH,
    BGP_AS_CHANGED: SEVERITY_HIGH,
    ROUTER_ID_CHANGED: SEVERITY_HIGH,
    ACL_ADDED: SEVERITY_HIGH,
    ACL_REMOVED: SEVERITY_HIGH,
    AAA_ENABLED: SEVERITY_HIGH,
    AAA_DISABLED: SEVERITY_HIGH,
    INTERFACE_SHUTDOWN: SEVERITY_HIGH,
    VRF_REMOVED: SEVERITY_HIGH,
    OSPF_AREA_ADDED: SEVERITY_MEDIUM,
    OSPF_AREA_REMOVED: SEVERITY_MEDIUM,
    INTERFACE_ADDED: SEVERITY_MEDIUM,
    INTERFACE_REMOVED: SEVERITY_MEDIUM,
    INTERFACE_ENABLED: SEVERITY_MEDIUM,
    INTERFACE_IP_CHANGED: SEVERITY_MEDIUM,
    VLAN_ADDED: SEVERITY_MEDIUM,
    VLAN_REMOVED: SEVERITY_MEDIUM,
    VRF_ADDED: SEVERITY_MEDIUM,
    HSRP_PRIORITY_CHANGED: SEVERITY_MEDIUM,
    HSRP_GROUP_ADDED: SEVERITY_MEDIUM,
    HSRP_GROUP_REMOVED: SEVERITY_MEDIUM,
    ROUTE_MAP_ADDED: SEVERITY_MEDIUM,
    ROUTE_MAP_REMOVED: SEVERITY_MEDIUM,
    STATIC_ROUTE_ADDED: SEVERITY_MEDIUM,
    STATIC_ROUTE_REMOVED: SEVERITY_MEDIUM,
    SNMP_ENABLED: SEVERITY_MEDIUM,
    SNMP_DISABLED: SEVERITY_MEDIUM,
    HOSTNAME_CHANGED: SEVERITY_LOW,
    INTERFACE_DESCRIPTION_CHANGED: SEVERITY_LOW,
    NTP_SERVER_ADDED: SEVERITY_LOW,
    NTP_SERVER_REMOVED: SEVERITY_LOW,
    LOGGING_HOST_ADDED: SEVERITY_LOW,
    LOGGING_HOST_REMOVED: SEVERITY_LOW,
}

# Which networking domain an event belongs to (for grouping/filtering).
_EVENT_CATEGORY: dict[str, str] = {}
for _kind in (BGP_NEIGHBOR_ADDED, BGP_NEIGHBOR_REMOVED, BGP_NEIGHBOR_MODIFIED,
              BGP_AS_CHANGED):
    _EVENT_CATEGORY[_kind] = "bgp"
for _kind in (OSPF_AREA_ADDED, OSPF_AREA_REMOVED):
    _EVENT_CATEGORY[_kind] = "ospf"
for _kind in (INTERFACE_ADDED, INTERFACE_REMOVED, INTERFACE_SHUTDOWN,
              INTERFACE_ENABLED, INTERFACE_IP_CHANGED,
              INTERFACE_DESCRIPTION_CHANGED):
    _EVENT_CATEGORY[_kind] = "interfaces"
for _kind in (VLAN_ADDED, VLAN_REMOVED):
    _EVENT_CATEGORY[_kind] = "vlans"
for _kind in (VRF_ADDED, VRF_REMOVED):
    _EVENT_CATEGORY[_kind] = "vrfs"
for _kind in (ACL_ADDED, ACL_REMOVED):
    _EVENT_CATEGORY[_kind] = "acls"
for _kind in (HSRP_PRIORITY_CHANGED, HSRP_GROUP_ADDED, HSRP_GROUP_REMOVED):
    _EVENT_CATEGORY[_kind] = "hsrp"
for _kind in (ROUTE_MAP_ADDED, ROUTE_MAP_REMOVED):
    _EVENT_CATEGORY[_kind] = "policy"
for _kind in (STATIC_ROUTE_ADDED, STATIC_ROUTE_REMOVED):
    _EVENT_CATEGORY[_kind] = "static-routes"
for _kind in (AAA_ENABLED, AAA_DISABLED):
    _EVENT_CATEGORY[_kind] = "aaa"
for _kind in (SNMP_ENABLED, SNMP_DISABLED):
    _EVENT_CATEGORY[_kind] = "snmp"
for _kind in (NTP_SERVER_ADDED, NTP_SERVER_REMOVED):
    _EVENT_CATEGORY[_kind] = "ntp"
for _kind in (LOGGING_HOST_ADDED, LOGGING_HOST_REMOVED):
    _EVENT_CATEGORY[_kind] = "logging"
_EVENT_CATEGORY[HOSTNAME_CHANGED] = "identity"
_EVENT_CATEGORY[ROUTER_ID_CHANGED] = "identity"


@dataclass(frozen=True)
class SemanticEvent:
    """One structured, human-readable configuration change."""

    kind: str
    subject: str          # what changed (a neighbor, interface, VLAN id …)
    summary: str
    severity: str
    category: str
    previous_value: str | None = None
    current_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "summary": self.summary,
            "severity": self.severity,
            "category": self.category,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
        }


def _event(
    kind: str,
    subject: str,
    summary: str,
    *,
    previous: str | None = None,
    current: str | None = None,
) -> SemanticEvent:
    return SemanticEvent(
        kind=kind,
        subject=subject,
        summary=summary,
        severity=_EVENT_SEVERITY.get(kind, SEVERITY_LOW),
        category=_EVENT_CATEGORY.get(kind, "other"),
        previous_value=previous,
        current_value=current,
    )


def semantic_diff(
    previous: ConfigFacts, current: ConfigFacts
) -> tuple[SemanticEvent, ...]:
    """Structured events describing what changed between two versions.

    Compares normalized facts, so the result reflects MEANING (a neighbor
    appeared) rather than text (a line moved). Deterministic ordering:
    severity first, then category, then subject.
    """

    if not isinstance(previous, ConfigFacts) or not isinstance(current, ConfigFacts):
        raise TypeError("semantic_diff compares ConfigFacts values")

    events: list[SemanticEvent] = []

    # -- identity ------------------------------------------------------------
    if previous.hostname != current.hostname and current.hostname:
        events.append(_event(
            HOSTNAME_CHANGED, current.hostname,
            f"Hostname changed from {previous.hostname or 'unset'} to "
            f"{current.hostname}",
            previous=previous.hostname, current=current.hostname,
        ))
    if previous.router_id != current.router_id and (previous.router_id or current.router_id):
        events.append(_event(
            ROUTER_ID_CHANGED, current.router_id or previous.router_id or "router-id",
            f"Router ID changed from {previous.router_id or 'unset'} to "
            f"{current.router_id or 'unset'}",
            previous=previous.router_id, current=current.router_id,
        ))

    # -- BGP -----------------------------------------------------------------
    if previous.bgp_as != current.bgp_as and (previous.bgp_as or current.bgp_as):
        events.append(_event(
            BGP_AS_CHANGED, current.bgp_as or previous.bgp_as or "bgp",
            f"BGP AS changed from {previous.bgp_as or 'none'} to "
            f"{current.bgp_as or 'none'}",
            previous=previous.bgp_as, current=current.bgp_as,
        ))
    before_neighbors = {item.neighbor: item for item in previous.bgp_neighbors}
    after_neighbors = {item.neighbor: item for item in current.bgp_neighbors}
    for neighbor in sorted(set(after_neighbors) - set(before_neighbors)):
        item = after_neighbors[neighbor]
        suffix = f" (remote-as {item.remote_as})" if item.remote_as else ""
        events.append(_event(
            BGP_NEIGHBOR_ADDED, neighbor,
            f"BGP neighbor {neighbor} added{suffix}",
            current=item.remote_as,
        ))
    for neighbor in sorted(set(before_neighbors) - set(after_neighbors)):
        item = before_neighbors[neighbor]
        suffix = f" (was remote-as {item.remote_as})" if item.remote_as else ""
        events.append(_event(
            BGP_NEIGHBOR_REMOVED, neighbor,
            f"BGP neighbor {neighbor} removed{suffix}",
            previous=item.remote_as,
        ))
    for neighbor in sorted(set(before_neighbors) & set(after_neighbors)):
        before, after = before_neighbors[neighbor], after_neighbors[neighbor]
        if before.remote_as != after.remote_as:
            events.append(_event(
                BGP_NEIGHBOR_MODIFIED, neighbor,
                f"BGP neighbor {neighbor} remote-as changed from "
                f"{before.remote_as or 'unset'} to {after.remote_as or 'unset'}",
                previous=before.remote_as, current=after.remote_as,
            ))

    # -- OSPF ----------------------------------------------------------------
    for area in sorted(set(current.ospf_areas) - set(previous.ospf_areas)):
        events.append(_event(OSPF_AREA_ADDED, area, f"OSPF area {area} added"))
    for area in sorted(set(previous.ospf_areas) - set(current.ospf_areas)):
        events.append(_event(OSPF_AREA_REMOVED, area, f"OSPF area {area} removed"))

    # -- interfaces ----------------------------------------------------------
    before_ifaces = {item.name: item for item in previous.interfaces}
    after_ifaces = {item.name: item for item in current.interfaces}
    for name in sorted(set(after_ifaces) - set(before_ifaces)):
        events.append(_event(INTERFACE_ADDED, name, f"Interface {name} added"))
    for name in sorted(set(before_ifaces) - set(after_ifaces)):
        events.append(_event(INTERFACE_REMOVED, name, f"Interface {name} removed"))
    for name in sorted(set(before_ifaces) & set(after_ifaces)):
        before, after = before_ifaces[name], after_ifaces[name]
        if not before.shutdown and after.shutdown:
            events.append(_event(
                INTERFACE_SHUTDOWN, name,
                f"Interface {name} was shut down",
                previous="no shutdown", current="shutdown",
            ))
        elif before.shutdown and not after.shutdown:
            events.append(_event(
                INTERFACE_ENABLED, name,
                f"Interface {name} was enabled (no shutdown)",
                previous="shutdown", current="no shutdown",
            ))
        if before.ip_address != after.ip_address:
            events.append(_event(
                INTERFACE_IP_CHANGED, name,
                f"Interface {name} address changed from "
                f"{before.ip_address or 'none'} to {after.ip_address or 'none'}",
                previous=before.ip_address, current=after.ip_address,
            ))
        if before.description != after.description:
            events.append(_event(
                INTERFACE_DESCRIPTION_CHANGED, name,
                f"Interface {name} description changed",
                previous=before.description, current=after.description,
            ))

    # -- VLANs / VRFs / ACLs / route-maps / static routes --------------------
    for kind_added, kind_removed, before_set, after_set, noun in (
        (VLAN_ADDED, VLAN_REMOVED, previous.vlans, current.vlans, "VLAN"),
        (VRF_ADDED, VRF_REMOVED, previous.vrfs, current.vrfs, "VRF"),
        (ACL_ADDED, ACL_REMOVED, previous.acls, current.acls, "Access list"),
        (ROUTE_MAP_ADDED, ROUTE_MAP_REMOVED, previous.route_maps,
         current.route_maps, "Route map"),
        (STATIC_ROUTE_ADDED, STATIC_ROUTE_REMOVED, previous.static_routes,
         current.static_routes, "Static route"),
        (NTP_SERVER_ADDED, NTP_SERVER_REMOVED, previous.ntp_servers,
         current.ntp_servers, "NTP server"),
        (LOGGING_HOST_ADDED, LOGGING_HOST_REMOVED, previous.logging_hosts,
         current.logging_hosts, "Logging host"),
    ):
        for value in sorted(set(after_set) - set(before_set)):
            events.append(_event(kind_added, value, f"{noun} {value} added"))
        for value in sorted(set(before_set) - set(after_set)):
            events.append(_event(kind_removed, value, f"{noun} {value} removed"))

    # -- HSRP ----------------------------------------------------------------
    before_hsrp = {(g.interface, g.group): g for g in previous.hsrp_groups}
    after_hsrp = {(g.interface, g.group): g for g in current.hsrp_groups}
    for key in sorted(set(after_hsrp) - set(before_hsrp)):
        events.append(_event(
            HSRP_GROUP_ADDED, f"{key[0]} group {key[1]}",
            f"HSRP group {key[1]} added on {key[0]}",
        ))
    for key in sorted(set(before_hsrp) - set(after_hsrp)):
        events.append(_event(
            HSRP_GROUP_REMOVED, f"{key[0]} group {key[1]}",
            f"HSRP group {key[1]} removed from {key[0]}",
        ))
    for key in sorted(set(before_hsrp) & set(after_hsrp)):
        before, after = before_hsrp[key], after_hsrp[key]
        if before.priority != after.priority:
            events.append(_event(
                HSRP_PRIORITY_CHANGED, f"{key[0]} group {key[1]}",
                f"HSRP priority on {key[0]} group {key[1]} changed from "
                f"{before.priority or 'default'} to {after.priority or 'default'}",
                previous=before.priority, current=after.priority,
            ))

    # -- service toggles (existence only — never their secrets) --------------
    if not previous.snmp_configured and current.snmp_configured:
        events.append(_event(SNMP_ENABLED, "snmp-server", "SNMP configuration added"))
    elif previous.snmp_configured and not current.snmp_configured:
        events.append(_event(SNMP_DISABLED, "snmp-server", "SNMP configuration removed"))
    if not previous.aaa_configured and current.aaa_configured:
        events.append(_event(AAA_ENABLED, "aaa", "AAA configuration added"))
    elif previous.aaa_configured and not current.aaa_configured:
        events.append(_event(AAA_DISABLED, "aaa", "AAA configuration removed"))

    events.sort(
        key=lambda item: (
            -_SEVERITY_RANK.get(item.severity, 0),
            item.category,
            item.subject.casefold(),
            item.kind,
        )
    )
    return tuple(events)


def semantic_diff_text(
    previous_config: str, current_config: str
) -> tuple[SemanticEvent, ...]:
    """Convenience: extract facts from both texts, then diff semantically."""

    from .extract import extract_facts

    return semantic_diff(extract_facts(previous_config), extract_facts(current_config))


def highest_severity(events: tuple[SemanticEvent, ...]) -> str:
    """The most severe event level present (low when there are none)."""

    if not events:
        return SEVERITY_LOW
    return max(events, key=lambda item: _SEVERITY_RANK.get(item.severity, 0)).severity


def summarize_events(events: tuple[SemanticEvent, ...]) -> str:
    """A one-line, human summary of a change set for the timeline."""

    if not events:
        return "Configuration changed (no semantic change detected)"
    if len(events) == 1:
        return events[0].summary
    lead = events[0].summary
    return f"{lead} (+{len(events) - 1} more change(s))"
