"""The Aruba CX production driver (POLYGLOT Wave 2, Tier 2).

ArubaOS-CX switches normalize into the same canonical models as every
other platform: identity from ``show system``, addressed interfaces
from ``show ip interface brief``, LLDP neighbors, VLANs and LACP
aggregates as metadata evidence, and OSPF/BGP through the shared
vendor-neutral routing channel.

Maturity: **EXPERIMENTAL** — TRANSCRIPT VALIDATED only (sanitized
ArubaOS-CX 10.11 transcripts; no live 6300M was available).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address

from founderos_atlas.discovery.adapter import DiscoveryAdapter
from founderos_atlas.discovery.exceptions import DiscoveryParseError
from founderos_atlas.discovery.models import (
    NetworkDevice,
    NetworkInterface,
    NetworkNeighbor,
)
from founderos_atlas.routing import (
    BgpSessionObservation,
    OspfAdjacencyObservation,
    routing_metadata,
)

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver

SHOW_VERSION = "show version"
SHOW_SYSTEM = "show system"
SHOW_IP_INTERFACES = "show ip interface brief"
SHOW_INTERFACES = "show interface brief"
SHOW_LLDP = "show lldp neighbor-info"
SHOW_VLAN = "show vlan"
SHOW_LACP = "show lacp aggregates"
SHOW_ROUTES = "show ip route"
SHOW_OSPF = "show ip ospf neighbors"
SHOW_BGP = "show bgp ipv4 unicast summary"
SHOW_CONFIG = "show running-config"

ADAPTER_NAME = "ArubaCXAdapter"

_VERSION = re.compile(r"(?m)^Version\s*:\s*(?P<version>\S+)")
_SYSTEM_KV = re.compile(r"(?m)^(?P<key>[A-Za-z. ()%-]+?)\s{2,}:\s*(?P<value>.*)$")
_IP_ROW = re.compile(
    r"(?m)^(?P<name>\S+)\s+(?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)\s+"
    r"(?P<link>up|down)/(?P<admin>up|down)\s*$"
)
_LLDP_ROW = re.compile(
    r"(?m)^(?P<local>\d+\S*)\s+\S+\s+(?P<port>\S+)\s+\S+\s+\d+\s+(?P<name>\S+)\s*$"
)
_VLAN_ROW = re.compile(
    r"(?m)^(?P<vid>\d+)\s+(?P<name>\S+)\s+(?P<status>up|down)\s+\S+\s+\S+\s+(?P<members>\S*)\s*$"
)
_LAG_NAME = re.compile(r"(?mi)^Aggregate name\s*:\s*(?P<name>\S+)")
_LAG_MEMBERS = re.compile(r"(?mi)^Interfaces\s*:\s*(?P<members>.+)$")
_OSPF_ROW = re.compile(
    r"(?m)^(?P<rid>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<state>\S+)\s+"
    r"(?P<addr>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s*$"
)
_BGP_LOCAL_AS = re.compile(r"(?mi)Local AS\s*:\s*(?P<las>\d+)")
_BGP_ROW = re.compile(
    r"(?m)^\s*(?P<peer>\d+\.\d+\.\d+\.\d+)\s+(?P<ras>\d+)\s+\d+\s+\d+\s+"
    r"\S+\s+(?P<state>\S+)\s+\S+\s*$"
)


class ArubaCXAdapter(DiscoveryAdapter):
    """Parse-only normalization of ArubaOS-CX CLI output."""

    vendor = "aruba"
    platform_family = "aruba-cx"
    required_commands = (SHOW_VERSION, SHOW_SYSTEM, SHOW_IP_INTERFACES)
    optional_commands = (
        SHOW_INTERFACES, SHOW_LLDP, SHOW_VLAN, SHOW_LACP, SHOW_ROUTES,
        SHOW_OSPF, SHOW_BGP, SHOW_CONFIG,
    )

    def _system(self, raw_outputs: Mapping[str, str]) -> dict[str, str]:
        return {
            match.group("key").strip(): match.group("value").strip()
            for match in _SYSTEM_KV.finditer(raw_outputs.get(SHOW_SYSTEM, ""))
        }

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        system = self._system(raw_outputs)
        hostname = system.get("Hostname")
        version = _VERSION.search(raw_outputs.get(SHOW_VERSION, ""))
        if not hostname or version is None:
            raise DiscoveryParseError(
                "device identity could not be established",
                adapter=ADAPTER_NAME, command=SHOW_SYSTEM, field="hostname",
            )
        addresses = [
            (m.group("name"), m.group("ip"))
            for m in _IP_ROW.finditer(raw_outputs.get(SHOW_IP_INTERFACES, ""))
        ]
        wanted = str(management_ip_hint).strip() if management_ip_hint else None
        management_ip = next(
            (ip for _n, ip in addresses if wanted and ip == wanted),
            addresses[0][1] if addresses else None,
        )
        if management_ip is None:
            if not _valid_ip(wanted):
                raise DiscoveryParseError(
                    "no management IP was parsed and no connection address "
                    "was supplied",
                    adapter=ADAPTER_NAME, command=SHOW_IP_INTERFACES,
                    field="management_ip",
                )
            management_ip = wanted
        return NetworkDevice(
            device_id=f"aruba-cx:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=system.get("Product Name", "ArubaOS-CX"),
            os_name="ArubaOS-CX",
            os_version=version.group("version"),
            serial_number=system.get("Chassis Serial Nbr"),
            metadata={
                "model": system.get("Product Name", "unknown"),
                "device_role": "switch",
                **(
                    {"location": system["System Location"]}
                    if system.get("System Location") else {}
                ),
            },
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces: list[NetworkInterface] = []
        for match in _IP_ROW.finditer(raw_outputs.get(SHOW_IP_INTERFACES, "")):
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=match.group("ip"),
                status="up" if match.group("link") == "up" else "down",
                metadata={
                    "source_command": SHOW_IP_INTERFACES,
                    "prefix_length": int(match.group("prefix")),
                    "vrf": "default",
                },
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        system = self._system(raw_outputs)
        local_id = f"aruba-cx:{system.get('Hostname', 'unknown')}"
        neighbors: list[NetworkNeighbor] = []
        for match in _LLDP_ROW.finditer(raw_outputs.get(SHOW_LLDP, "")):
            if match.group("name") in ("SYS-NAME",):
                continue
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("local"),
                remote_hostname=match.group("name"),
                remote_interface=match.group("port"),
                protocol="lldp",
                metadata={
                    "observation": "link-layer",
                    "management_endpoint": False,
                    "source_command": SHOW_LLDP,
                },
            ))
        for match in _OSPF_ROW.finditer(raw_outputs.get(SHOW_OSPF, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("intf"),
                remote_hostname=match.group("rid"),
                protocol="ospf",
                metadata={
                    "observation": "routing-adjacency",
                    "router_id": match.group("rid"),
                    "adjacency_address": match.group("addr"),
                    "ospf_state": match.group("state"),
                    "vrf": "default",
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": SHOW_OSPF,
                },
            ))
        return tuple(neighbors)


class ArubaCXDriver(ProductionDriver):
    """Aruba CX, held to the production contract."""

    platform_id = "aruba-cx"
    display_name = "Aruba CX"
    vendor = "aruba"
    probe_command = SHOW_VERSION
    banner_fingerprints = (r"arubaos-cx", r"hewlett packard")
    prompt_fingerprints = (r"[\w-]+# ?$",)
    netmiko_device_type = "aruba_aoscx"
    session_setup = ()
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return "ArubaOS-CX" in (probe_output or "")

    @property
    def adapter(self) -> ArubaCXAdapter:
        return ArubaCXAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.VERSION, (SHOW_VERSION,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.IDENTITY, (SHOW_SYSTEM,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (SHOW_IP_INTERFACES,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACES, (SHOW_INTERFACES,)),
            CommandSpec(caps.LLDP, (SHOW_LLDP,)),
            CommandSpec(caps.VLAN, (SHOW_VLAN,)),
            CommandSpec(caps.LAG, (SHOW_LACP,)),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES,)),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.BGP, (SHOW_BGP,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_CONFIG,), tier=TIER_DEEP),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        return folded.startswith("% unknown command") or (
            "% invalid input" in folded[:120]
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)

        vlans = tuple(
            {
                "vlan_id": m.group("vid"),
                "name": m.group("name"),
                "status": m.group("status"),
            }
            for m in _VLAN_ROW.finditer(raw.get(SHOW_VLAN, ""))
        )
        if vlans:
            metadata["vlans"] = vlans
        lag_name = _LAG_NAME.search(raw.get(SHOW_LACP, ""))
        lag_members = _LAG_MEMBERS.search(raw.get(SHOW_LACP, ""))
        if lag_name:
            metadata["port_channels"] = (
                {
                    "port_channel": lag_name.group("name"),
                    "members": tuple(
                        (lag_members.group("members") if lag_members else "")
                        .split()
                    ),
                },
            )

        local_as = _BGP_LOCAL_AS.search(raw.get(SHOW_BGP, ""))
        sessions = tuple(
            BgpSessionObservation(
                peer_address=m.group("peer"),
                remote_as=m.group("ras"),
                local_as=local_as.group("las") if local_as else None,
                state=m.group("state").casefold(),
                vrf="default",
                source_command=SHOW_BGP,
            )
            for m in _BGP_ROW.finditer(raw.get(SHOW_BGP, ""))
        )
        ospf = tuple(
            OspfAdjacencyObservation(
                neighbor_router_id=str(item.metadata.get("router_id")),
                adjacency_address=item.metadata.get("adjacency_address"),
                local_interface=item.local_interface,
                state=str(item.metadata.get("ospf_state") or "unknown"),
                vrf="default", address_family="ipv4",
                source_command=SHOW_OSPF,
            )
            for item in discovery.result.neighbors if item.protocol == "ospf"
        )
        if ospf or sessions:
            metadata["routing_evidence"] = routing_metadata(
                ospf=ospf, bgp=sessions
            )
        metadata["route_count"] = len(re.findall(
            r"(?m)^\d+\.\d+\.\d+\.\d+/\d+,", raw.get(SHOW_ROUTES, "")
        ))

        bgp_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=discovery.result.device.device_id,
                local_interface="bgp",
                remote_hostname=item.peer_address,
                protocol="bgp",
                metadata={
                    "observation": "protocol-peer", **item.to_dict(),
                    "management_endpoint": False,
                },
            )
            for item in sessions
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
