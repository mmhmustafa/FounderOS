"""The Cisco IOS-XE production driver (PR-049, POLYGLOT, Part 7).

Explicitly separated from legacy IOS: the two share a command dialect where
behaviour is genuinely compatible (CDP detail, interface brief), but IOS-XE
gets the full production plan — inventory, LLDP *and* CDP, routing, VLANs,
port-channels, MAC table, STP, HSRP, running configuration — with fallbacks,
tiers and honest per-capability outcomes. The legacy ``CiscoIOSDriver`` stays
registered after this one, so classic IOS keeps its battle-tested minimal
path.

Maturity: **EXPERIMENTAL** — transcript-validated only. No live IOS-XE device
was available in this environment; every parser runs against sanitized
transcripts of realistic output. Live validation is required before BETA.
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

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST, TIER_STANDARD
from ..production import DriverDiscovery, ProductionDriver


SHOW_VERSION = "show version"
SHOW_INVENTORY = "show inventory"
SHOW_IP_INT_BRIEF = "show ip interface brief"
SHOW_INTERFACES = "show interfaces"
SHOW_LLDP = "show lldp neighbors detail"
SHOW_CDP = "show cdp neighbors detail"
SHOW_ROUTES = "show ip route"
SHOW_BGP = "show ip bgp summary"
SHOW_OSPF = "show ip ospf neighbor"
SHOW_VLAN = "show vlan brief"
SHOW_ETHERCHANNEL = "show etherchannel summary"
SHOW_MAC = "show mac address-table"
SHOW_STP = "show spanning-tree"
SHOW_STANDBY = "show standby brief"
SHOW_RUNNING = "show running-config"

ADAPTER_NAME = "CiscoIOSXEAdapter"
UNKNOWN = "unknown"

# `Cisco IOS XE Software, Version 17.09.04a`
_XE_VERSION = re.compile(
    r"Cisco IOS[ -]XE Software.*?Version\s+(?P<version>[\w.()]+)",
    re.IGNORECASE | re.DOTALL,
)
# `router-1 uptime is 2 weeks, 3 days`
_HOSTNAME_UPTIME = re.compile(r"(?m)^(?P<host>[\w.-]+)\s+uptime is\s")
# `cisco C9300-24T (X86) processor` / `Model Number : C9300-24T`
_MODEL = re.compile(r"(?mi)^(?:cisco\s+(?P<m1>[\w/+-]+)\s+\(|Model Number\s*:\s*(?P<m2>\S+))")
_SERIAL = re.compile(r"(?mi)^(?:Processor board ID|System Serial Number\s*:)\s*(?P<serial>\S+)")
# show inventory: NAME: "Chassis", DESCR ... / PID: C9300-24T , VID: V03, SN: FOC12345ABC
_INV_ITEM = re.compile(
    r'NAME:\s*"(?P<name>[^"]+)",\s*DESCR:\s*"(?P<descr>[^"]+)"\s*'
    r"PID:\s*(?P<pid>\S*?)\s*,\s*VID:\s*(?P<vid>\S*?)\s*,\s*SN:\s*(?P<sn>\S*)",
)
# `GigabitEthernet1/0/1   10.10.1.1   YES manual up   up`
_INT_BRIEF = re.compile(
    r"(?m)^(?P<name>[A-Za-z][\w./-]*)\s+(?P<ip>\d+\.\d+\.\d+\.\d+|unassigned)\s+"
    r"\w+\s+\S+\s+(?P<status>up|down|administratively down)\s+(?P<protocol>up|down)\s*$"
)
# LLDP detail blocks
_LLDP_SYSNAME = re.compile(r"(?m)^System Name:\s*(?P<name>\S+)")
_LLDP_LOCAL = re.compile(r"(?m)^Local Intf:\s*(?P<intf>\S+)")
_LLDP_PORT = re.compile(r"(?m)^Port id:\s*(?P<port>\S+)")
_LLDP_MGMT = re.compile(r"(?m)^\s*IP:\s*(?P<ip>\d+\.\d+\.\d+\.\d+)")
# CDP detail blocks (identical dialect to classic IOS)
_CDP_DEVICE = re.compile(r"(?m)^Device ID:\s*(?P<name>\S+)")
_CDP_IP = re.compile(r"(?m)^\s*IP(?:v4)? address:\s*(?P<ip>\d+\.\d+\.\d+\.\d+)")
_CDP_INTF = re.compile(
    r"(?m)^Interface:\s*(?P<local>\S+?),\s*Port ID \(outgoing port\):\s*(?P<remote>\S+)"
)
_BGP_PEER = re.compile(
    r"(?m)^(?P<peer>\d+\.\d+\.\d+\.\d+)\s+4\s+(?P<asn>\d+)\s+"
)
_OSPF_ROW = re.compile(
    r"(?m)^(?P<rid>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<state>\S+)\s+[\d:.]+\s+"
    r"(?P<address>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s*$"
)


class CiscoIOSXEAdapter(DiscoveryAdapter):
    """Parse-only normalization of IOS-XE CLI output."""

    vendor = "cisco"
    platform_family = "cisco-ios-xe"
    required_commands = (SHOW_VERSION, SHOW_IP_INT_BRIEF)
    optional_commands = (
        SHOW_INVENTORY, SHOW_INTERFACES, SHOW_LLDP, SHOW_CDP, SHOW_ROUTES,
        SHOW_BGP, SHOW_OSPF, SHOW_VLAN, SHOW_ETHERCHANNEL, SHOW_MAC, SHOW_STP,
        SHOW_STANDBY, SHOW_RUNNING,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        xe = _XE_VERSION.search(version_text)
        host = _HOSTNAME_UPTIME.search(version_text)
        if xe is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established from 'show version'",
                adapter=ADAPTER_NAME, command=SHOW_VERSION, field="hostname",
            )
        hostname = host.group("host")
        model = _first(_MODEL, version_text, "m1", "m2")
        serial = _first(_SERIAL, version_text, "serial")
        inventory = _parse_inventory_items(raw_outputs.get(SHOW_INVENTORY, ""))
        if inventory and not model:
            model = inventory[0].get("pid") or None
        if inventory and not serial:
            serial = inventory[0].get("serial") or None

        management_ip, warnings = self._management_ip(
            raw_outputs.get(SHOW_IP_INT_BRIEF, ""), management_ip_hint
        )
        metadata: dict[str, object] = {"model": model or UNKNOWN}
        if inventory:
            metadata["inventory"] = tuple(
                tuple(sorted(item.items())) for item in inventory
            )
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return NetworkDevice(
            device_id=f"cisco-ios-xe:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model or "Cisco IOS-XE",
            os_name="Cisco IOS-XE",
            os_version=xe.group("version"),
            serial_number=serial,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces = []
        for match in _INT_BRIEF.finditer(raw_outputs.get(SHOW_IP_INT_BRIEF, "")):
            ip = match.group("ip")
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=None if ip == "unassigned" else ip,
                status=(
                    "down" if "administratively" in match.group("status")
                    else match.group("status")
                ),
                protocol_status=match.group("protocol"),
                metadata={"source_command": SHOW_IP_INT_BRIEF},
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        local_id = self._local_id(raw_outputs)
        neighbors: list[NetworkNeighbor] = []
        neighbors.extend(_parse_lldp(raw_outputs.get(SHOW_LLDP, ""), local_id))
        neighbors.extend(_parse_cdp(raw_outputs.get(SHOW_CDP, ""), local_id))
        for match in _OSPF_ROW.finditer(raw_outputs.get(SHOW_OSPF, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("intf"),
                remote_hostname=match.group("rid"),
                remote_interface=None,
                remote_management_ip=None,
                protocol="ospf",
                metadata={
                    "observation": "routing-adjacency",
                    "router_id": match.group("rid"),
                    "adjacency_address": match.group("address"),
                    "ospf_state": match.group("state"),
                    "process_id": None,
                    "area_id": None,
                    "vrf": "default",
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": SHOW_OSPF,
                },
            ))
        return tuple(neighbors)

    def _local_id(self, raw_outputs: Mapping[str, str]) -> str:
        host = _HOSTNAME_UPTIME.search(raw_outputs.get(SHOW_VERSION, ""))
        return f"cisco-ios-xe:{host.group('host')}" if host else "cisco-ios-xe:unknown"

    def _management_ip(self, brief: str, hint: str | None):
        warnings: list[str] = []
        addresses = [
            m.group("ip") for m in _INT_BRIEF.finditer(brief)
            if m.group("ip") != "unassigned"
        ]
        if hint and str(hint).strip() in addresses:
            return str(hint).strip(), warnings
        if addresses:
            return addresses[0], warnings
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


class CiscoIOSXEDriver(ProductionDriver):
    """Cisco IOS-XE, held to the production contract."""

    platform_id = "cisco-ios-xe"
    display_name = "Cisco IOS-XE"
    vendor = "cisco"
    probe_command = SHOW_VERSION
    netmiko_device_type = "cisco_xe"
    session_setup = ("terminal length 0", "terminal width 511")
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        # IOS-XE names itself; classic IOS says "Cisco IOS Software" without
        # the XE. Registered before the legacy driver so XE devices get the
        # production plan and classic IOS keeps its proven minimal one.
        return bool(re.search(r"Cisco IOS[ -]XE Software", probe_output or "",
                              re.IGNORECASE))

    @property
    def adapter(self) -> CiscoIOSXEAdapter:
        return CiscoIOSXEAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_VERSION,), required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (SHOW_IP_INT_BRIEF,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.LLDP, (SHOW_LLDP, "show lldp neighbors"), tier=TIER_FAST),
            CommandSpec(caps.CDP, (SHOW_CDP,), tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (SHOW_INVENTORY,)),
            CommandSpec(caps.INTERFACES, (SHOW_INTERFACES,)),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES,)),
            CommandSpec(caps.BGP, (SHOW_BGP,)),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.VLAN, (SHOW_VLAN,)),
            CommandSpec(caps.LAG, (SHOW_ETHERCHANNEL,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_RUNNING,)),
            CommandSpec(caps.MAC_TABLE, (SHOW_MAC, "show mac-address-table"),
                        tier=TIER_DEEP),
            CommandSpec(caps.STP, (SHOW_STP,), tier=TIER_DEEP),
            CommandSpec(caps.FIRST_HOP_REDUNDANCY, (SHOW_STANDBY,), tier=TIER_DEEP),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        sessions = bgp_sessions_from_summary(
            raw.get(SHOW_BGP, ""), source_command=SHOW_BGP
        )
        peers = [
            {"peer": item.peer_address, "remote_as": item.remote_as}
            for item in sessions
        ]
        if peers:
            metadata["bgp_peers"] = tuple(tuple(sorted(p.items())) for p in peers)
        routes = [l for l in raw.get(SHOW_ROUTES, "").splitlines()
                  if re.match(r"^[A-Z*]", l.strip() or "-")]
        if routes:
            metadata["route_count"] = len(routes)
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
            )
            for item in discovery.result.neighbors if item.protocol == "ospf"
        )
        metadata["routing_evidence"] = routing_metadata(ospf=ospf, bgp=sessions)
        bgp_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=discovery.result.device.device_id,
                local_interface="bgp",
                remote_hostname=item.peer_address,
                remote_interface=None,
                remote_management_ip=None,
                protocol="bgp",
                metadata={
                    "observation": "protocol-peer",
                    **item.to_dict(),
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


def _parse_lldp(text: str, local_id: str) -> list[NetworkNeighbor]:
    neighbors = []
    for block in re.split(r"(?m)^-{6,}\s*$", text or ""):
        name = _LLDP_SYSNAME.search(block)
        local = _LLDP_LOCAL.search(block)
        if not (name and local):
            continue
        port = _LLDP_PORT.search(block)
        mgmt = _LLDP_MGMT.search(block)
        neighbors.append(NetworkNeighbor(
            local_device_id=local_id,
            local_interface=local.group("intf"),
            remote_hostname=name.group("name").split(".")[0],
            remote_interface=port.group("port") if port else None,
            remote_management_ip=mgmt.group("ip") if mgmt else None,
            protocol="lldp",
            metadata={"source_command": SHOW_LLDP},
        ))
    return neighbors


def _parse_cdp(text: str, local_id: str) -> list[NetworkNeighbor]:
    neighbors = []
    for block in re.split(r"(?m)^-{6,}\s*$", text or ""):
        name = _CDP_DEVICE.search(block)
        intf = _CDP_INTF.search(block)
        if not (name and intf):
            continue
        ip = _CDP_IP.search(block)
        # NX-OS appends its serial to the CDP Device ID -- "dist-nxos1(FDO...)".
        # The hostname is the identity; the serial is not part of it.
        hostname = re.sub(r"\(.*\)$", "", name.group("name")).split(".")[0]
        neighbors.append(NetworkNeighbor(
            local_device_id=local_id,
            local_interface=intf.group("local"),
            remote_hostname=hostname,
            remote_interface=intf.group("remote"),
            remote_management_ip=ip.group("ip") if ip else None,
            protocol="cdp",
            metadata={"source_command": SHOW_CDP},
        ))
    return neighbors


def _parse_inventory_items(text: str) -> list[dict]:
    return [
        {"name": m.group("name"), "description": m.group("descr"),
         "pid": m.group("pid"), "serial": m.group("sn")}
        for m in _INV_ITEM.finditer(text or "")
    ]


def _first(pattern: re.Pattern, text: str, *groups: str) -> str | None:
    match = pattern.search(text or "")
    if not match:
        return None
    for group in groups:
        value = match.groupdict().get(group)
        if value:
            return value
    return None


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
