"""Structured configuration extraction (PR-044, Part 8).

Do not store only text — extract normalized knowledge so future
intelligence reasons over structured data, never raw configuration.

Everything here is a deterministic parse of already-collected text: no
inference, no guessing. A construct that is not present is simply absent
(never defaulted into existence). Secret-bearing values are NEVER
extracted — the AAA/SNMP/NTP facts record that a construct exists and its
non-sensitive identity (a server address, a group name), never a password,
key, or community string.

The extractor is rule-driven and vendor-extensible: Cisco IOS/IOS-XE and
FRRouting syntax are close enough that one rule set covers both; new
platforms extend the tables, not the algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from founderos_atlas.config_intelligence import is_dynamic_metadata


# -- normalized fact models --------------------------------------------------------


@dataclass(frozen=True)
class InterfaceFact:
    name: str
    description: str | None = None
    ip_address: str | None = None
    shutdown: bool = False
    vrf: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "ip_address": self.ip_address,
            "shutdown": self.shutdown,
            "vrf": self.vrf,
        }


@dataclass(frozen=True)
class BgpNeighborFact:
    neighbor: str
    remote_as: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "neighbor": self.neighbor,
            "remote_as": self.remote_as,
            "description": self.description,
        }


@dataclass(frozen=True)
class HsrpGroupFact:
    interface: str
    group: str
    priority: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "group": self.group,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class ConfigFacts:
    """Normalized configuration knowledge for one device version.

    Provenance-safe: no secrets, no raw configuration lines.
    """

    hostname: str | None = None
    router_id: str | None = None
    bgp_as: str | None = None
    bgp_neighbors: tuple[BgpNeighborFact, ...] = ()
    ospf_areas: tuple[str, ...] = ()
    ospf_process_ids: tuple[str, ...] = ()
    vlans: tuple[str, ...] = ()
    vrfs: tuple[str, ...] = ()
    acls: tuple[str, ...] = ()
    interfaces: tuple[InterfaceFact, ...] = ()
    hsrp_groups: tuple[HsrpGroupFact, ...] = ()
    ntp_servers: tuple[str, ...] = ()
    snmp_configured: bool = False
    logging_hosts: tuple[str, ...] = ()
    aaa_configured: bool = False
    static_routes: tuple[str, ...] = ()
    route_maps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "router_id": self.router_id,
            "bgp_as": self.bgp_as,
            "bgp_neighbors": [item.to_dict() for item in self.bgp_neighbors],
            "ospf_areas": list(self.ospf_areas),
            "ospf_process_ids": list(self.ospf_process_ids),
            "vlans": list(self.vlans),
            "vrfs": list(self.vrfs),
            "acls": list(self.acls),
            "interfaces": [item.to_dict() for item in self.interfaces],
            "hsrp_groups": [item.to_dict() for item in self.hsrp_groups],
            "ntp_servers": list(self.ntp_servers),
            "snmp_configured": self.snmp_configured,
            "logging_hosts": list(self.logging_hosts),
            "aaa_configured": self.aaa_configured,
            "static_routes": list(self.static_routes),
            "route_maps": list(self.route_maps),
            "warnings": list(self.warnings),
        }

    def view(self) -> dict[str, Any]:
        """Counts **and** the detail behind them, for the screen.

        ``summary()`` answers "how many BGP neighbours"; an operator opening
        a device during an incident is asking "which ones". Extraction
        already knows — this is the shape that does not throw it away.
        """

        return {**self.to_dict(), **self.summary()}

    def summary(self) -> dict[str, Any]:
        """Counts only — the shape a UI or future engine reasons over."""

        return {
            "hostname": self.hostname,
            "router_id": self.router_id,
            "bgp_as": self.bgp_as,
            "bgp_neighbor_count": len(self.bgp_neighbors),
            "ospf_area_count": len(self.ospf_areas),
            "vlan_count": len(self.vlans),
            "vrf_count": len(self.vrfs),
            "acl_count": len(self.acls),
            "interface_count": len(self.interfaces),
            "hsrp_group_count": len(self.hsrp_groups),
            "static_route_count": len(self.static_routes),
            "route_map_count": len(self.route_maps),
            "snmp_configured": self.snmp_configured,
            "aaa_configured": self.aaa_configured,
        }


# -- parsing rules -----------------------------------------------------------------

_HOSTNAME = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE)
_ROUTER_ID = re.compile(r"^\s*(?:bgp\s+)?router-id\s+(\S+)", re.IGNORECASE)
_ROUTER_BGP = re.compile(r"^router\s+bgp\s+(\S+)", re.IGNORECASE)
_ROUTER_OSPF = re.compile(r"^router\s+ospf\s*(\S+)?", re.IGNORECASE)
_INTERFACE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESCRIPTION = re.compile(r"^\s*description\s+(.+)$", re.IGNORECASE)
_IP_ADDRESS = re.compile(
    r"^\s*ip(?:v6)?\s+address\s+(\S+(?:\s+\S+)?)", re.IGNORECASE
)
_SHUTDOWN = re.compile(r"^\s*shutdown\s*$", re.IGNORECASE)
_VRF_MEMBER = re.compile(
    r"^\s*(?:vrf\s+forwarding|ip\s+vrf\s+forwarding|vrf)\s+(\S+)", re.IGNORECASE
)
_VRF_DEF = re.compile(
    r"^(?:vrf\s+definition|ip\s+vrf)\s+(\S+)", re.IGNORECASE
)
_VLAN = re.compile(r"^vlan\s+(\d[\d,\-]*)\s*$", re.IGNORECASE)
_ACL = re.compile(
    r"^(?:ip\s+access-list\s+(?:standard|extended)?\s*(\S+)|access-list\s+(\S+))",
    re.IGNORECASE,
)
_BGP_NEIGHBOR_AS = re.compile(
    r"^\s*neighbor\s+(\S+)\s+remote-as\s+(\S+)", re.IGNORECASE
)
_BGP_NEIGHBOR_DESC = re.compile(
    r"^\s*neighbor\s+(\S+)\s+description\s+(.+)$", re.IGNORECASE
)
_OSPF_AREA = re.compile(r"\barea\s+(\S+)", re.IGNORECASE)
_HSRP_GROUP = re.compile(r"^\s*standby\s+(\d+)\s+", re.IGNORECASE)
_HSRP_PRIORITY = re.compile(
    r"^\s*standby\s+(\d+)\s+priority\s+(\d+)", re.IGNORECASE
)
_NTP_SERVER = re.compile(r"^ntp\s+server\s+(\S+)", re.IGNORECASE)
_SNMP = re.compile(r"^snmp-server\b", re.IGNORECASE)
_LOGGING_HOST = re.compile(r"^logging\s+(?:host\s+)?(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)
_AAA = re.compile(r"^aaa\s+", re.IGNORECASE)
_STATIC_ROUTE = re.compile(r"^ip(?:v6)?\s+route\s+(.+)$", re.IGNORECASE)
_ROUTE_MAP = re.compile(r"^route-map\s+(\S+)", re.IGNORECASE)


def extract_facts(running_config: str) -> ConfigFacts:
    """Parse configuration text into normalized, secret-free facts.

    Deterministic and tolerant: unrecognized constructs are ignored rather
    than guessed at. Absent constructs stay absent — Atlas never invents a
    default.
    """

    if not isinstance(running_config, str):
        raise TypeError("running_config must be text")

    hostname: str | None = None
    router_id: str | None = None
    bgp_as: str | None = None
    neighbors: dict[str, dict[str, str | None]] = {}
    ospf_areas: set[str] = set()
    ospf_processes: list[str] = []
    vlans: list[str] = []
    vrfs: list[str] = []
    acls: list[str] = []
    interfaces: list[InterfaceFact] = []
    hsrp: dict[tuple[str, str], str | None] = {}
    ntp: list[str] = []
    snmp = False
    logging_hosts: list[str] = []
    aaa = False
    static_routes: list[str] = []
    route_maps: list[str] = []

    context: str | None = None       # "bgp" | "ospf" | "interface" | None
    current_interface: str | None = None
    iface_desc: str | None = None
    iface_ip: str | None = None
    iface_shut = False
    iface_vrf: str | None = None

    def flush_interface() -> None:
        nonlocal current_interface, iface_desc, iface_ip, iface_shut, iface_vrf
        if current_interface is not None:
            interfaces.append(
                InterfaceFact(
                    name=current_interface,
                    description=iface_desc,
                    ip_address=iface_ip,
                    shutdown=iface_shut,
                    vrf=iface_vrf,
                )
            )
        current_interface = None
        iface_desc = iface_ip = iface_vrf = None
        iface_shut = False

    for raw in running_config.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip() == "!" or is_dynamic_metadata(line):
            continue
        indented = line.startswith((" ", "\t"))

        if not indented:
            flush_interface()
            context = None

            match = _HOSTNAME.match(line)
            if match:
                hostname = match.group(1)
                continue
            match = _INTERFACE.match(line)
            if match:
                current_interface = match.group(1)
                context = "interface"
                continue
            match = _ROUTER_BGP.match(line)
            if match:
                bgp_as = match.group(1)
                context = "bgp"
                continue
            match = _ROUTER_OSPF.match(line)
            if match:
                if match.group(1):
                    ospf_processes.append(match.group(1))
                context = "ospf"
                continue
            match = _VRF_DEF.match(line)
            if match and match.group(1) not in vrfs:
                vrfs.append(match.group(1))
                continue
            match = _VLAN.match(line)
            if match:
                for part in match.group(1).split(","):
                    if part and part not in vlans:
                        vlans.append(part)
                continue
            match = _ACL.match(line)
            if match:
                name = match.group(1) or match.group(2)
                if name and name not in acls:
                    acls.append(name)
                continue
            match = _NTP_SERVER.match(line)
            if match and match.group(1) not in ntp:
                ntp.append(match.group(1))
                continue
            if _SNMP.match(line):
                snmp = True   # existence only — never the community string
                continue
            match = _LOGGING_HOST.match(line)
            if match and match.group(1) not in logging_hosts:
                logging_hosts.append(match.group(1))
                continue
            if _AAA.match(line):
                aaa = True    # existence only — never credentials
                continue
            match = _STATIC_ROUTE.match(line)
            if match:
                route = match.group(1).strip()
                if route not in static_routes:
                    static_routes.append(route)
                continue
            match = _ROUTE_MAP.match(line)
            if match and match.group(1) not in route_maps:
                route_maps.append(match.group(1))
                continue
            continue

        # Indented child lines belong to the current construct.
        if context == "interface" and current_interface is not None:
            match = _DESCRIPTION.match(line)
            if match:
                iface_desc = match.group(1).strip()
                continue
            match = _IP_ADDRESS.match(line)
            if match:
                iface_ip = match.group(1).strip()
                continue
            if _SHUTDOWN.match(line):
                iface_shut = True
                continue
            match = _VRF_MEMBER.match(line)
            if match:
                iface_vrf = match.group(1)
                if iface_vrf not in vrfs:
                    vrfs.append(iface_vrf)
                continue
            match = _HSRP_PRIORITY.match(line)
            if match:
                hsrp[(current_interface, match.group(1))] = match.group(2)
                continue
            match = _HSRP_GROUP.match(line)
            if match:
                hsrp.setdefault((current_interface, match.group(1)), None)
                continue
            continue

        if context == "bgp":
            match = _BGP_NEIGHBOR_AS.match(line)
            if match:
                entry = neighbors.setdefault(match.group(1), {})
                entry["remote_as"] = match.group(2)
                continue
            match = _BGP_NEIGHBOR_DESC.match(line)
            if match:
                entry = neighbors.setdefault(match.group(1), {})
                entry["description"] = match.group(2).strip()
                continue
            match = _ROUTER_ID.match(line)
            if match and router_id is None:
                router_id = match.group(1)
                continue
            continue

        if context == "ospf":
            for found in _OSPF_AREA.finditer(line):
                ospf_areas.add(found.group(1))
            match = _ROUTER_ID.match(line)
            if match and router_id is None:
                router_id = match.group(1)
            continue

    flush_interface()

    return ConfigFacts(
        hostname=hostname,
        router_id=router_id,
        bgp_as=bgp_as,
        bgp_neighbors=tuple(
            BgpNeighborFact(
                neighbor=key,
                remote_as=value.get("remote_as"),
                description=value.get("description"),
            )
            for key, value in sorted(neighbors.items())
        ),
        ospf_areas=tuple(sorted(ospf_areas)),
        ospf_process_ids=tuple(ospf_processes),
        vlans=tuple(vlans),
        vrfs=tuple(vrfs),
        acls=tuple(acls),
        interfaces=tuple(interfaces),
        hsrp_groups=tuple(
            HsrpGroupFact(interface=key[0], group=key[1], priority=value)
            for key, value in sorted(hsrp.items())
        ),
        ntp_servers=tuple(ntp),
        snmp_configured=snmp,
        logging_hosts=tuple(logging_hosts),
        aaa_configured=aaa,
        static_routes=tuple(static_routes),
        route_maps=tuple(route_maps),
    )
