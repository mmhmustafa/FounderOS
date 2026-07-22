"""The Arista EOS production driver (PR-049, POLYGLOT, Part 9).

CLI text first: eAPI is deliberately NOT required — it slots in later as an
alternative transport behind the same capability plan, no redesign. EOS looks
IOS-adjacent but is parsed on its own terms: `show version` carries no
hostname (identity needs `show hostname`), interface briefs carry CIDR
addresses, and MLAG — not vPC or stacking — is its multi-chassis story.

Maturity: **EXPERIMENTAL** — transcript-validated only; no live EOS device
was available in this environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address
import re

from founderos_atlas.discovery.adapter import DiscoveryAdapter
from founderos_atlas.discovery.exceptions import DiscoveryParseError
from founderos_atlas.discovery.models import (
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
)
from founderos_atlas.routing import (
    OspfAdjacencyObservation,
    bgp_sessions_from_summary,
    routing_metadata,
)
from founderos_atlas.routing.table import route_table_dicts

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


SHOW_VERSION = "show version"
SHOW_HOSTNAME = "show hostname"
SHOW_IP_INT_BRIEF = "show ip interface brief"
SHOW_LLDP = "show lldp neighbors"
SHOW_MLAG = "show mlag"
SHOW_ROUTES = "show ip route vrf all"
SHOW_BGP = "show ip bgp summary vrf all"
SHOW_OSPF = "show ip ospf neighbor"
SHOW_VLAN = "show vlan"
SHOW_VRF = "show vrf"
SHOW_MAC = "show mac address-table"
SHOW_INVENTORY = "show inventory"
SHOW_RUNNING = "show running-config"

ADAPTER_NAME = "AristaEOSAdapter"
UNKNOWN = "unknown"

_MODEL = re.compile(r"(?m)^Arista\s+(?P<model>\S+)")
_SERIAL = re.compile(r"(?mi)^Serial number:\s*(?P<serial>\S+)")
_SW_VERSION = re.compile(r"(?mi)^Software image version:\s*(?P<version>\S+)")
_HOSTNAME = re.compile(r"(?mi)^Hostname:\s*(?P<host>\S+)")
# `Ethernet1   10.10.30.1/31   up   up   9214`
_INT_ROW = re.compile(
    r"(?m)^(?P<name>[A-Za-z][\w./-]*)\s+(?P<addr>\d+\.\d+\.\d+\.\d+/\d+|unassigned)\s+"
    r"(?P<status>\S+)\s+(?P<proto>\S+)"
)
# `Et1   core-sw1   Gi1/0/1   120`
_LLDP_ROW = re.compile(
    r"(?m)^(?P<local>(?:Et|Ma|Po)\S*)\s+(?P<name>[\w.-]+)\s+(?P<port>\S+)\s+\d+\s*$"
)
# Horizontal whitespace only after the colon: \s would cross the newline
# and let a bare header line ("MLAG Configuration:") swallow the line below.
_MLAG_FIELD = re.compile(r"(?m)^(?P<key>[\w-]+(?:[ ][\w-]+)*)[ 	]*:[ 	]*(?P<value>\S.*?)[ 	]*$")
_BGP_PEER = re.compile(r"(?m)^\s*(?P<peer>\d+\.\d+\.\d+\.\d+)\s+4\s+(?P<asn>\d+)\s+")
_OSPF_ROW = re.compile(
    r"(?m)^\s*(?P<rid>\d+\.\d+\.\d+\.\d+)\s+"
    r"(?P<process>\S+)\s+(?P<vrf>\S+)\s+\d+\s+"
    r"(?P<state>\S+)\s+\S+\s+"
    r"(?P<address>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s*$"
)


class AristaEOSAdapter(DiscoveryAdapter):
    """Parse-only normalization of EOS CLI text output."""

    vendor = "arista"
    platform_family = "arista-eos"
    required_commands = (SHOW_VERSION, SHOW_HOSTNAME, SHOW_IP_INT_BRIEF)
    optional_commands = (
        SHOW_LLDP, SHOW_MLAG, SHOW_ROUTES, SHOW_BGP, SHOW_OSPF, SHOW_VLAN,
        SHOW_VRF, SHOW_MAC, SHOW_INVENTORY, SHOW_RUNNING,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        model = _MODEL.search(version_text)
        version = _SW_VERSION.search(version_text)
        host = _HOSTNAME.search(raw_outputs.get(SHOW_HOSTNAME, ""))
        if model is None or version is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established (EOS reports the "
                "hostname via 'show hostname', not 'show version')",
                adapter=ADAPTER_NAME, command=SHOW_VERSION, field="hostname",
            )
        hostname = host.group("host")
        serial = _SERIAL.search(version_text)
        management_ip, warnings = self._management_ip(
            raw_outputs.get(SHOW_IP_INT_BRIEF, ""), management_ip_hint
        )
        metadata: dict[str, object] = {"model": model.group("model")}
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return NetworkDevice(
            device_id=f"arista-eos:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model.group("model"),
            os_name="Arista EOS",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces = []
        for match in _INT_ROW.finditer(raw_outputs.get(SHOW_IP_INT_BRIEF, "")):
            addr = match.group("addr")
            ip, prefix = (None, None)
            if addr != "unassigned":
                ip, prefix = addr.split("/")
            metadata: dict[str, object] = {"source_command": SHOW_IP_INT_BRIEF}
            if prefix is not None:
                metadata["prefix_length"] = int(prefix)
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=ip,
                status=match.group("status"),
                protocol_status=match.group("proto"),
                metadata=metadata,
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        host = _HOSTNAME.search(raw_outputs.get(SHOW_HOSTNAME, ""))
        local_id = f"arista-eos:{host.group('host')}" if host else "arista-eos:unknown"
        neighbors = []
        for match in _LLDP_ROW.finditer(raw_outputs.get(SHOW_LLDP, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("local"),
                remote_hostname=match.group("name").split(".")[0],
                remote_interface=match.group("port"),
                remote_management_ip=None,   # EOS's tabular LLDP carries none
                protocol="lldp",
                metadata={"source_command": SHOW_LLDP},
            ))
        for match in _OSPF_ROW.finditer(raw_outputs.get(SHOW_OSPF, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("intf"),
                remote_hostname=match.group("rid"),
                remote_interface=None, remote_management_ip=None,
                protocol="ospf",
                metadata={
                    "observation": "routing-adjacency",
                    "router_id": match.group("rid"),
                    "adjacency_address": match.group("address"),
                    "ospf_state": match.group("state"),
                    "process_id": match.group("process"),
                    "area_id": None,
                    "vrf": match.group("vrf"),
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": SHOW_OSPF,
                },
            ))
        return tuple(neighbors)

    def _management_ip(self, brief: str, hint: str | None):
        warnings: list[str] = []
        rows = list(_INT_ROW.finditer(brief))
        wanted = str(hint).strip() if hint else None
        addresses = {
            m.group("name"): m.group("addr").split("/")[0]
            for m in rows if m.group("addr") != "unassigned"
        }
        if wanted and wanted in addresses.values():
            return wanted, warnings
        # Prefer the Management interface — that is what it is for.
        for name, ip in addresses.items():
            if name.lower().startswith("management"):
                return ip, warnings
        if addresses:
            return next(iter(addresses.values())), warnings
        if _valid_ip(hint):
            warnings.append(
                "management IP was not parsed from the interface brief; "
                "using the connection address as a deterministic fallback"
            )
            return str(hint).strip(), warnings
        raise DiscoveryParseError(
            "no management IP was parsed and no connection address was supplied",
            adapter=ADAPTER_NAME, command=SHOW_IP_INT_BRIEF, field="management_ip",
        )


class AristaEOSDriver(ProductionDriver):
    """Arista EOS, held to the production contract. CLI text; eAPI later."""

    platform_id = "arista-eos"
    display_name = "Arista EOS"
    vendor = "arista"
    probe_command = SHOW_VERSION
    netmiko_device_type = "arista_eos"
    session_setup = ("terminal length 0", "terminal width 32767")
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        text = probe_output or ""
        return bool(
            re.search(r"(?m)^Arista\s+\S+", text)
            and re.search(r"Software image version:", text, re.IGNORECASE)
        )

    @property
    def adapter(self) -> AristaEOSAdapter:
        return AristaEOSAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_VERSION,), required=True, tier=TIER_FAST),
            # EOS keeps its name out of `show version`; identity is two
            # commands, both required.
            CommandSpec("hostname", (SHOW_HOSTNAME,), required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES,
                        (SHOW_IP_INT_BRIEF, "show ip interface"),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.LLDP, (SHOW_LLDP,), tier=TIER_FAST),
            CommandSpec(caps.LAG, (SHOW_MLAG,),
                        limitation="MLAG only; port-channel detail is future work"),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES, "show ip route")),
            CommandSpec(caps.BGP, (SHOW_BGP, "show ip bgp summary")),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.VLAN, (SHOW_VLAN,)),
            CommandSpec(caps.VRF, (SHOW_VRF,)),
            CommandSpec(caps.INVENTORY, (SHOW_INVENTORY,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_RUNNING,)),
            CommandSpec(caps.MAC_TABLE, (SHOW_MAC,), tier=TIER_DEEP),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        mlag_text = raw.get(SHOW_MLAG, "")
        if "domain-id" in mlag_text:
            fields = {
                m.group("key").strip(): m.group("value")
                for m in _MLAG_FIELD.finditer(mlag_text)
            }
            metadata["mlag"] = {
                "domain_id": fields.get("domain-id", UNKNOWN),
                "peer_address": fields.get("peer-address", UNKNOWN),
                "peer_link": fields.get("peer-link", UNKNOWN),
                "state": fields.get("state", UNKNOWN),
            }
        sessions = bgp_sessions_from_summary(
            raw.get(SHOW_BGP, ""), source_command=SHOW_BGP
        )
        peers = [
            {"peer": item.peer_address, "remote_as": item.remote_as}
            for item in sessions
        ]
        if peers:
            metadata["bgp_peers"] = tuple(tuple(sorted(p.items())) for p in peers)
        # The real RIB: EOS speaks the shared `show ip route` grammar
        # (indented), so the canonical parser reads it.
        routing_table = route_table_dicts(raw.get(SHOW_ROUTES, ""))
        if routing_table:
            metadata["routing_table"] = routing_table
        ospf = tuple(
            OspfAdjacencyObservation(
                neighbor_router_id=str(item.metadata.get("router_id")),
                adjacency_address=item.metadata.get("adjacency_address"),
                local_interface=item.local_interface,
                state=str(item.metadata.get("ospf_state") or "unknown"),
                process_id=item.metadata.get("process_id"),
                area_id=item.metadata.get("area_id"),
                vrf=str(item.metadata.get("vrf") or "default"),
                address_family=str(item.metadata.get("address_family") or "ipv4"),
                source_command=SHOW_OSPF,
            ) for item in discovery.result.neighbors if item.protocol == "ospf"
        )
        metadata["routing_evidence"] = routing_metadata(ospf=ospf, bgp=sessions)
        bgp_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=discovery.result.device.device_id,
                local_interface="bgp", remote_hostname=item.peer_address,
                remote_interface=None, remote_management_ip=None,
                protocol="bgp",
                metadata={
                    "observation": "protocol-peer", **item.to_dict(),
                    "management_endpoint": False,
                },
            ) for item in sessions
        )
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
            neighbors=(*discovery.result.neighbors, *bgp_neighbors),
        )
        return replace(discovery, result=result)


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
