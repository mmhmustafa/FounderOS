"""The Cisco NX-OS production driver (PR-049, POLYGLOT, Part 8).

NX-OS is not IOS with a different banner. The behaviours this driver owns:

- **feature gating** — protocols exist only when `feature <x>` is enabled; a
  disabled feature answers with an error or nothing, and both are honest
  platform facts, never failures;
- **the management VRF** — mgmt0 lives in VRF "management"; interface
  addressing must be read `vrf all` or the management endpoint disappears;
- **vPC** — domain, role and peer status are NX-OS's distinctive L2 evidence,
  summarized into canonical metadata the way the AtlasLab firewall summarizes
  its chain;
- **identity format** — hostname is `Device name:`, model and serial live in
  the Hardware block and `show inventory`.

Maturity: **EXPERIMENTAL** — transcript-validated only; no live NX-OS device
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
from founderos_atlas.routing.table import prefix_line_route_dicts
from founderos_atlas.routing.policy import (
    parse_ip_policy_bindings,
    parse_route_map_policy_routes,
    policy_route_dicts,
)

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


SHOW_VERSION = "show version"
SHOW_INVENTORY = "show inventory"
SHOW_IP_INT = "show ip interface vrf all"
SHOW_INT_BRIEF = "show interface brief"
SHOW_LLDP = "show lldp neighbors"
SHOW_CDP = "show cdp neighbors detail"
SHOW_VPC = "show vpc"
SHOW_PORT_CHANNEL = "show port-channel summary"
SHOW_ROUTES = "show ip route vrf all"
SHOW_BGP = "show ip bgp summary vrf all"
SHOW_OSPF = "show ip ospf neighbors"
SHOW_VLAN = "show vlan brief"
# NX-OS policy routing is route-maps bound to an interface with `ip policy
# route-map`, exactly as IOS does it — so it reads with the same parser and
# needs the same two halves. The binding is the load-bearing one: a
# route-map nothing references forwards nothing.
SHOW_IP_POLICY = "show ip policy"
SHOW_ROUTE_MAP = "show route-map"
SHOW_VRF = "show vrf"
SHOW_MAC = "show mac address-table"
SHOW_STP = "show spanning-tree"
SHOW_RUNNING = "show running-config"

ADAPTER_NAME = "CiscoNXOSAdapter"
UNKNOWN = "unknown"

_NXOS_VERSION = re.compile(r"(?mi)^\s*NXOS:\s*version\s+(?P<version>\S+)")
_DEVICE_NAME = re.compile(r"(?mi)^\s*Device name:\s*(?P<host>\S+)")
_CHASSIS = re.compile(r"(?mi)^\s*cisco\s+(?P<model>Nexus\S*\s+\S+)\s+chassis")
_BOARD_ID = re.compile(r"(?mi)^\s*Processor Board ID\s+(?P<serial>\S+)")
_INV_ITEM = re.compile(
    r'NAME:\s*"(?P<name>[^"]+)",\s*DESCR:\s*"(?P<descr>[^"]+)"\s*'
    r"PID:\s*(?P<pid>\S*?)\s*,\s*VID:\s*(?P<vid>\S*?)\s*,\s*SN:\s*(?P<sn>\S*)",
)
# `Lo0, Interface status: protocol-up/link-up/admin-up, iod: 4,`
_IPINT_HEAD = re.compile(
    r"(?m)^(?P<name>[A-Za-z][\w./-]*),\s*Interface status:\s*"
    r"protocol-(?P<proto>\w+)/link-(?P<link>\w+)/admin-(?P<admin>\w+)"
)
_IPINT_ADDR = re.compile(
    r"(?m)^\s*IP address:\s*(?P<ip>\d+\.\d+\.\d+\.\d+),\s*IP subnet:\s*\S+/(?P<prefix>\d+)"
)
_VRF_HEAD = re.compile(r'(?m)^IP Interface Status for VRF "(?P<vrf>[^"]+)"')
# LLDP tabular: `core-sw1  Eth1/49  120  BR  Gi1/0/3`
_LLDP_ROW = re.compile(
    r"(?m)^(?P<name>[\w.-]+)\s+(?P<local>(?:Eth|mgmt|Po)\S*)\s+\d+\s+\S*\s+(?P<port>\S+)\s*$"
)
_CDP_DEVICE = re.compile(r"(?m)^Device ID:\s*(?P<name>\S+)")
_CDP_IP = re.compile(r"(?m)^\s*IPv4 Address:\s*(?P<ip>\d+\.\d+\.\d+\.\d+)")
_CDP_INTF = re.compile(
    r"(?m)^Interface:\s*(?P<local>\S+?),\s*Port ID \(outgoing port\):\s*(?P<remote>\S+)"
)
_VPC_DOMAIN = re.compile(r"(?mi)^vPC domain id\s*:\s*(?P<domain>\S+)")
_VPC_ROLE = re.compile(r"(?mi)^vPC role\s*:\s*(?P<role>\S+)")
_VPC_PEER = re.compile(r"(?mi)^Peer status\s*:\s*(?P<status>.+?)\s*$")
_PC_ROW = re.compile(r"(?m)^(?P<group>\d+)\s+(?P<po>Po\d+)\(\S+\)\s+Eth\s+(?P<proto>\S+)\s+(?P<members>.+)$")
_BGP_PEER = re.compile(r"(?m)^(?P<peer>\d+\.\d+\.\d+\.\d+)\s+4\s+(?P<asn>\d+)\s+")
_OSPF_ROW = re.compile(
    r"(?m)^\s*(?P<rid>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<state>FULL\S*|TWO-WAY\S*)\s+\S+\s+"
    r"(?P<address>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s*$"
)


class CiscoNXOSAdapter(DiscoveryAdapter):
    """Parse-only normalization of NX-OS CLI output."""

    vendor = "cisco"
    platform_family = "cisco-nxos"
    required_commands = (SHOW_VERSION, SHOW_IP_INT)
    optional_commands = (
        SHOW_INVENTORY, SHOW_INT_BRIEF, SHOW_LLDP, SHOW_CDP, SHOW_VPC,
        SHOW_PORT_CHANNEL, SHOW_ROUTES, SHOW_BGP, SHOW_OSPF, SHOW_VLAN,
        SHOW_VRF, SHOW_MAC, SHOW_STP, SHOW_RUNNING,
        SHOW_IP_POLICY, SHOW_ROUTE_MAP,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        version = _NXOS_VERSION.search(version_text)
        host = _DEVICE_NAME.search(version_text)
        if version is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established from 'show version'",
                adapter=ADAPTER_NAME, command=SHOW_VERSION, field="hostname",
            )
        hostname = host.group("host")
        chassis = _CHASSIS.search(version_text)
        serial = _BOARD_ID.search(version_text)
        inventory = [
            {"name": m.group("name"), "description": m.group("descr"),
             "pid": m.group("pid"), "serial": m.group("sn")}
            for m in _INV_ITEM.finditer(raw_outputs.get(SHOW_INVENTORY, ""))
        ]
        model = (inventory[0]["pid"] if inventory else None) or (
            chassis.group("model") if chassis else None
        )
        management_ip, mgmt_vrf, warnings = self._management_ip(
            raw_outputs.get(SHOW_IP_INT, ""), management_ip_hint
        )
        metadata: dict[str, object] = {"model": model or UNKNOWN}
        if mgmt_vrf:
            metadata["management_vrf"] = mgmt_vrf
        if inventory:
            metadata["inventory"] = tuple(
                tuple(sorted(item.items())) for item in inventory
            )
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return NetworkDevice(
            device_id=f"cisco-nxos:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model or "Cisco NX-OS",
            os_name="Cisco NX-OS",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces: list[NetworkInterface] = []
        for vrf, name, proto, link, admin, ip, prefix in _iter_ip_interfaces(
            raw_outputs.get(SHOW_IP_INT, "")
        ):
            metadata: dict[str, object] = {
                "source_command": SHOW_IP_INT, "vrf": vrf,
            }
            if prefix is not None:
                metadata["prefix_length"] = prefix
            interfaces.append(NetworkInterface(
                name=name,
                ip_address=ip,
                status="up" if admin == "up" else "down",
                protocol_status=proto,
                metadata=metadata,
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        host = _DEVICE_NAME.search(raw_outputs.get(SHOW_VERSION, ""))
        local_id = f"cisco-nxos:{host.group('host')}" if host else "cisco-nxos:unknown"
        neighbors: list[NetworkNeighbor] = []
        for match in _LLDP_ROW.finditer(raw_outputs.get(SHOW_LLDP, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("local"),
                remote_hostname=match.group("name").split(".")[0],
                remote_interface=match.group("port"),
                remote_management_ip=None,   # the tabular form carries none
                protocol="lldp",
                metadata={"source_command": SHOW_LLDP},
            ))
        for block in re.split(r"(?m)^-{6,}\s*$", raw_outputs.get(SHOW_CDP, "")):
            device = _CDP_DEVICE.search(block)
            intf = _CDP_INTF.search(block)
            if not (device and intf):
                continue
            ip = _CDP_IP.search(block)
            hostname = re.sub(r"\(.*\)$", "", device.group("name")).split(".")[0]
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=intf.group("local"),
                remote_hostname=hostname,
                remote_interface=intf.group("remote"),
                remote_management_ip=ip.group("ip") if ip else None,
                protocol="cdp",
                metadata={"source_command": SHOW_CDP},
            ))
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

    def _management_ip(self, text: str, hint: str | None):
        warnings: list[str] = []
        entries = list(_iter_ip_interfaces(text))
        wanted = str(hint).strip() if hint else None
        mgmt_vrf = None
        chosen = None
        for vrf, name, _p, _l, _a, ip, _pre in entries:
            if ip and wanted and ip == wanted:
                chosen, mgmt_vrf = ip, vrf
                break
        if chosen is None:
            # Prefer the management VRF's address — that is what mgmt0 is for.
            for vrf, name, _p, _l, _a, ip, _pre in entries:
                if ip and vrf == "management":
                    chosen, mgmt_vrf = ip, vrf
                    break
        if chosen is None:
            for vrf, _n, _p, _l, _a, ip, _pre in entries:
                if ip:
                    chosen, mgmt_vrf = ip, vrf
                    break
        if chosen is None and _valid_ip(hint):
            warnings.append(
                "management IP was not parsed from interface addressing; "
                "using the connection address as a deterministic fallback"
            )
            return str(hint).strip(), None, warnings
        if chosen is None:
            raise DiscoveryParseError(
                "no management IP was parsed and no connection address was supplied",
                adapter=ADAPTER_NAME, command=SHOW_IP_INT, field="management_ip",
            )
        return chosen, mgmt_vrf, warnings


class CiscoNXOSDriver(ProductionDriver):
    """Cisco NX-OS, held to the production contract."""

    platform_id = "cisco-nxos"
    display_name = "Cisco NX-OS"
    vendor = "cisco"
    probe_command = SHOW_VERSION
    netmiko_device_type = "cisco_nxos"
    session_setup = ("terminal length 0",)
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(re.search(
            r"Cisco Nexus Operating System \(NX-OS\)", probe_output or "",
            re.IGNORECASE,
        ))

    @property
    def adapter(self) -> CiscoNXOSAdapter:
        return CiscoNXOSAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_VERSION,), required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES,
                        (SHOW_IP_INT, "show ip interface brief vrf all"),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.LLDP, (SHOW_LLDP,), tier=TIER_FAST),
            CommandSpec(caps.CDP, (SHOW_CDP,), tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (SHOW_INVENTORY,)),
            CommandSpec(caps.INTERFACES, (SHOW_INT_BRIEF,)),
            CommandSpec(caps.LAG, (SHOW_PORT_CHANNEL,)),
            # vPC exists only with `feature vpc`; a disabled feature answers
            # honestly and lands as unsupported/empty, never failed.
            CommandSpec(caps.FIRST_HOP_REDUNDANCY, ("show hsrp brief",),
                        tier=TIER_DEEP),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES,)),
            CommandSpec(caps.POLICY_ROUTES, (SHOW_IP_POLICY,)),
            CommandSpec("policy-route-maps", (SHOW_ROUTE_MAP,)),
            CommandSpec(caps.BGP, (SHOW_BGP,)),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.VLAN, (SHOW_VLAN,)),
            CommandSpec(caps.VRF, (SHOW_VRF,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_RUNNING,)),
            CommandSpec("vpc", (SHOW_VPC,)),
            CommandSpec(caps.MAC_TABLE, (SHOW_MAC,), tier=TIER_DEEP),
            CommandSpec(caps.STP, (SHOW_STP,), tier=TIER_DEEP),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        domain = _VPC_DOMAIN.search(raw.get(SHOW_VPC, ""))
        if domain:
            role = _VPC_ROLE.search(raw.get(SHOW_VPC, ""))
            peer = _VPC_PEER.search(raw.get(SHOW_VPC, ""))
            metadata["vpc"] = {
                "domain": domain.group("domain"),
                "role": role.group("role") if role else UNKNOWN,
                "peer_status": peer.group("status") if peer else UNKNOWN,
            }
        port_channels = [
            {"port_channel": m.group("po"), "protocol": m.group("proto"),
             "members": tuple(re.findall(r"(Eth\S+?)\(", m.group("members")))}
            for m in _PC_ROW.finditer(raw.get(SHOW_PORT_CHANNEL, ""))
        ]
        if port_channels:
            metadata["port_channels"] = tuple(
                tuple(sorted(item.items())) for item in port_channels
            )
        sessions = bgp_sessions_from_summary(
            raw.get(SHOW_BGP, ""), source_command=SHOW_BGP
        )
        peers = [
            {"peer": item.peer_address, "remote_as": item.remote_as}
            for item in sessions
        ]
        if peers:
            metadata["bgp_peers"] = tuple(tuple(sorted(p.items())) for p in peers)
        # The real RIB: NX-OS writes the prefix on its own line with the
        # next-hops indented beneath it — a different grammar, the same
        # canonical RouteEntry.
        routing_table = prefix_line_route_dicts(raw.get(SHOW_ROUTES, ""))
        if routing_table:
            metadata["routing_table"] = routing_table
        # Policy routing decides before that table does. Keyed on the
        # BINDING command answering: "asked, and this device policy-routes
        # nothing" is evidence, and must not look like "never asked".
        if SHOW_IP_POLICY in raw:
            metadata["policy_routes"] = policy_route_dicts(
                parse_route_map_policy_routes(
                    raw.get(SHOW_ROUTE_MAP, ""),
                    bindings=parse_ip_policy_bindings(raw.get(SHOW_IP_POLICY, "")),
                    source_command=SHOW_ROUTE_MAP,
                )
            )
            metadata["policy_routes_captured"] = True
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


def _iter_ip_interfaces(text: str):
    """(vrf, name, protocol, link, admin, ip, prefix) per addressed interface."""

    vrf = "default"
    pending = None
    for line in (text or "").splitlines():
        head_vrf = _VRF_HEAD.match(line)
        if head_vrf:
            vrf = head_vrf.group("vrf")
            continue
        head = _IPINT_HEAD.match(line)
        if head:
            if pending is not None:
                yield pending
            pending = (vrf, head.group("name"), head.group("proto"),
                       head.group("link"), head.group("admin"), None, None)
            continue
        addr = _IPINT_ADDR.match(line)
        if addr and pending is not None:
            pending = pending[:5] + (addr.group("ip"), int(addr.group("prefix")))
            yield pending
            pending = None
    if pending is not None:
        yield pending


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
