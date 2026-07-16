"""Deterministic, evidence-based classification: device roles and
relationship kinds.

Role classification never guesses from hostnames ("SW1" proves
nothing). Evidence, in fixed order: an explicit override → platform
model families → SVI/switching evidence → firewall/host platforms →
collected routing evidence → router image families → honest unknown.
Every classification returns the evidence sentence alongside the role.

Relationship kinds separate what discovery PROVED from what routing
protocols merely REPORT: link-layer announcements are physical links;
OSPF/IS-IS adjacencies are logical routed adjacencies; BGP peerings are
protocol relationships. A routing adjacency is not a physical edge.
"""

from __future__ import annotations

from collections.abc import Mapping
import re


ROLE_ROUTER = "router"
ROLE_L2_SWITCH = "layer2_switch"
ROLE_L3_SWITCH = "layer3_switch"
ROLE_FIREWALL = "firewall"
ROLE_ACCESS_POINT = "wireless_access_point"
ROLE_SERVER = "server"
ROLE_LINUX_HOST = "linux_host"
ROLE_LOAD_BALANCER = "load_balancer"
ROLE_CLOUD = "cloud"
ROLE_UNKNOWN = "unknown"
ROLE_UNRESOLVED = "unresolved_peer"

DEVICE_ROLES = (
    ROLE_ROUTER, ROLE_L2_SWITCH, ROLE_L3_SWITCH, ROLE_FIREWALL,
    ROLE_ACCESS_POINT, ROLE_SERVER, ROLE_LINUX_HOST, ROLE_LOAD_BALANCER,
    ROLE_CLOUD, ROLE_UNKNOWN, ROLE_UNRESOLVED,
)

RELATION_PHYSICAL = "physical"
RELATION_ROUTING = "routing-adjacency"
RELATION_PEER = "protocol-peer"
RELATION_UNKNOWN = "unknown"

_SWITCH_MODEL = re.compile(
    r"WS-C|C29\d\d|C3[56]\d\d|C9[2345]\d\d|IOSvL2|catalyst|nexus",
    re.IGNORECASE,
)
_ROUTER_MODEL = re.compile(
    r"\bIOSv\b|CSR\d|ISR\d?|ASR\d|C8[0-9]{3}|vios(?!.*l2)", re.IGNORECASE
)
_FIREWALL_MODEL = re.compile(
    r"ASA|Firepower|FortiGate|FortiOS|PAN-OS|palo\s*alto", re.IGNORECASE
)
_AP_MODEL = re.compile(r"\bAIR-|access\s*point|AP\d{3}", re.IGNORECASE)


def classify_role(device: Mapping) -> tuple[str, str]:
    """(role, evidence sentence) for one canonical device dict.

    Works on the snapshot device shape: hostname/vendor/platform/
    os_name/interfaces/metadata. Hostnames are never evidence.
    """

    metadata = dict(device.get("metadata") or {})
    override = metadata.get("role")
    if isinstance(override, str) and override in DEVICE_ROLES:
        return override, "explicit role override"

    platform = str(device.get("platform") or "")
    vendor = str(device.get("vendor") or "")
    os_name = str(device.get("os_name") or "")
    interfaces = [
        item for item in (device.get("interfaces") or ())
        if isinstance(item, Mapping)
    ]
    svis = [
        item for item in interfaces
        if re.match(r"vlan\d+$", str(item.get("name") or ""), re.IGNORECASE)
    ]
    routed_svis = [item for item in svis if item.get("ip_address")]

    # PR-048: role from what the device DOES, before any name pattern. A
    # collected, enforced filter chain is firewall evidence no matter what the
    # platform is called; a layer-2 forwarding plane the device itself declared
    # is switching evidence. Without these, the AtlasLab platforms fell through
    # every model regex to the generic "linux" check and rendered as Linux
    # hosts — the terminal icon on a firewall.
    if metadata.get("firewall"):
        chain = metadata.get("firewall") or {}
        policy = str(chain.get("default_policy", "") if isinstance(chain, Mapping) else "")
        return ROLE_FIREWALL, (
            f"enforced filter chain collected"
            + (f" (default policy {policy})" if policy else "")
        )
    if str(metadata.get("forwarding_plane") or "") == "layer-2-bridge":
        return ROLE_L2_SWITCH, "device declares a layer-2 bridge forwarding plane"
    # Platform self-description fallback, for snapshots that carry the
    # platform string but not the evidence metadata.
    if re.search(r"atlaslab firewall", platform, re.IGNORECASE):
        return ROLE_FIREWALL, f"firewall platform '{platform}'"
    if re.search(r"atlaslab switch", platform, re.IGNORECASE):
        return ROLE_L2_SWITCH, f"switch platform '{platform}'"

    if _SWITCH_MODEL.search(platform):
        if routed_svis:
            return ROLE_L3_SWITCH, (
                f"switch platform model '{platform}' with "
                f"{len(routed_svis)} routed SVI(s)"
            )
        return ROLE_L2_SWITCH, f"switch platform model '{platform}'"
    if _FIREWALL_MODEL.search(platform) or _FIREWALL_MODEL.search(os_name):
        return ROLE_FIREWALL, f"firewall platform '{platform or os_name}'"
    if _AP_MODEL.search(platform):
        return ROLE_ACCESS_POINT, f"access-point platform '{platform}'"
    if svis:
        # SVIs are switching evidence regardless of the image name.
        if routed_svis:
            return ROLE_L3_SWITCH, (
                f"{len(svis)} VLAN interface(s), {len(routed_svis)} routed"
            )
        return ROLE_L2_SWITCH, f"{len(svis)} VLAN interface(s) present"
    if "frrouting" in vendor.casefold() or "frrouting" in platform.casefold():
        return ROLE_ROUTER, "FRRouting routing platform"
    if metadata.get("routes") or metadata.get("bgp_peers"):
        return ROLE_ROUTER, "collected routing table / BGP peer evidence"
    if "linux" in platform.casefold() or "linux" in os_name.casefold():
        return ROLE_LINUX_HOST, f"Linux platform '{platform or os_name}'"
    if _ROUTER_MODEL.search(platform):
        return ROLE_ROUTER, f"router platform model '{platform}'"
    return ROLE_UNKNOWN, "no role evidence collected"


def relationship_counts(
    edges,
    *,
    hostname_by_device_id: Mapping[str, str] | None = None,
    discovered_hostnames: frozenset[str] | set[str] = frozenset(),
) -> dict[str, int]:
    """Honest relationship-type counts over neighbor observations.

    Directional observations of one link collapse into a single logical
    relationship (same endpoint/interface pair + protocol). Unresolved
    peers are observed remote identities that were never discovered —
    they are counted separately and NEVER as devices.
    """

    lookup = dict(hostname_by_device_id or {})
    discovered = {str(name).casefold() for name in discovered_hostnames}
    counts = {
        "physical_links": 0,
        "routing_adjacencies": 0,
        "protocol_peers": 0,
        "unresolved_peers": 0,
    }
    seen: set[tuple] = set()
    unresolved: set[str] = set()
    for edge in edges:
        local = str(
            lookup.get(edge.local_device_id, edge.local_device_id)
        ).casefold()
        remote = str(edge.remote_hostname).casefold()
        endpoints = tuple(
            sorted(
                (
                    (local, str(edge.local_interface or "").casefold()),
                    (remote, str(edge.remote_interface or "unknown").casefold()),
                )
            )
        )
        key = (endpoints, str(edge.protocol))
        if key in seen:
            continue
        seen.add(key)
        kind = relationship_kind(str(edge.protocol), dict(edge.metadata))
        if kind == RELATION_PHYSICAL:
            counts["physical_links"] += 1
        elif kind == RELATION_ROUTING:
            counts["routing_adjacencies"] += 1
        elif kind == RELATION_PEER:
            counts["protocol_peers"] += 1
        if remote not in discovered:
            unresolved.add(remote)
    counts["unresolved_peers"] = len(unresolved)
    return counts


def relationship_kind(protocol: str, metadata: Mapping | None = None) -> str:
    """The relationship class one adjacency observation proves."""

    observation = str((metadata or {}).get("observation") or "")
    if observation == "routing-adjacency":
        return RELATION_ROUTING
    if observation == "protocol-peer":
        return RELATION_PEER
    if observation == "link-layer":
        return RELATION_PHYSICAL
    folded = str(protocol or "").casefold()
    if folded in ("cdp", "lldp", "manual", "inferred"):
        return RELATION_PHYSICAL
    if folded in ("ospf", "isis"):
        return RELATION_ROUTING
    if folded == "bgp":
        return RELATION_PEER
    return RELATION_UNKNOWN
