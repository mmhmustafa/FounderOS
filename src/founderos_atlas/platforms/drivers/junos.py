"""The Juniper Junos production driver (PR-049, POLYGLOT, Part 10).

Junos is not Cisco with different spellings, and this driver never pretends
otherwise:

- **identity** comes from `show version`'s own fields (Hostname/Model/Junos)
  and `show chassis hardware` — no uptime-line heuristics;
- **interfaces are hierarchical**: ge-0/0/0 is physical, ge-0/0/0.0 is a
  logical unit carrying an address family. Both are normalized, each knowing
  which physical interface and unit it is — the hierarchy is preserved, not
  flattened;
- **configuration** is collected as `| display set`: one deterministic line
  per statement, where the hierarchy survives as explicit paths — a stable
  representation for hashing, diffing and policy, chosen over curly-brace
  text whose formatting is not diff-stable;
- **refusal grammar is Junos's own** (`unknown command`, caret lines) — the
  Cisco `%` conventions do not apply;
- only safe read-only operational commands; configuration mode is never
  entered.

Maturity: **EXPERIMENTAL** — transcript-validated only; no live Junos device
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
from founderos_atlas.routing.table import junos_route_dicts

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


SHOW_VERSION = "show version"
SHOW_CHASSIS = "show chassis hardware"
SHOW_INT_TERSE = "show interfaces terse"
SHOW_LLDP = "show lldp neighbors"
SHOW_ROUTES = "show route"
SHOW_BGP = "show bgp summary"
SHOW_OSPF = "show ospf neighbor"
SHOW_CONFIG = "show configuration | display set"
SHOW_INSTANCES = "show route instance"
SHOW_ETHSW = "show ethernet-switching table"

ADAPTER_NAME = "JunosAdapter"
UNKNOWN = "unknown"

_HOSTNAME = re.compile(r"(?mi)^Hostname:\s*(?P<host>\S+)")
_MODEL = re.compile(r"(?mi)^Model:\s*(?P<model>\S+)")
_JUNOS = re.compile(r"(?mi)^Junos:\s*(?P<version>\S+)")
_CHASSIS_SERIAL = re.compile(r"(?m)^Chassis\s+(?P<serial>\S+)\s+")
# terse rows: physical (`ge-0/0/0  up  up`) and logical
# (`ge-0/0/0.0  up  up  inet  10.10.40.1/31`)
_TERSE_ROW = re.compile(
    r"(?m)^(?P<name>[a-z]{2,4}[-\d/:.]*\S*|lo0\S*|irb\S*|me0\S*)\s+"
    r"(?P<admin>up|down)\s+(?P<link>up|down)"
    r"(?:\s+(?P<family>inet6?|eth-switch)\s+(?P<addr>\S+))?\s*$"
)
_LLDP_ROW = re.compile(
    r"(?m)^(?P<local>\S+)\s+\S+\s+(?P<chassis>[0-9a-f:]{17})\s+"
    r"(?P<port>\S+)\s+(?P<name>[\w.-]+)\s*$",
    re.IGNORECASE,
)
_BGP_PEER = re.compile(
    r"(?m)^(?P<peer>\d+\.\d+\.\d+\.\d+)\s+(?P<asn>\d+)\s+\d+\s+\d+"
)
_OSPF_ROW = re.compile(
    r"(?m)^(?P<address>\d+\.\d+\.\d+\.\d+)\s+(?P<intf>\S+)\s+(?P<state>\S+)\s+"
    r"(?P<rid>\d+\.\d+\.\d+\.\d+)"
)


class JunosAdapter(DiscoveryAdapter):
    """Parse-only normalization of Junos operational-mode output."""

    vendor = "juniper"
    platform_family = "junos"
    required_commands = (SHOW_VERSION, SHOW_INT_TERSE)
    optional_commands = (
        SHOW_CHASSIS, SHOW_LLDP, SHOW_ROUTES, SHOW_BGP, SHOW_OSPF,
        SHOW_CONFIG, SHOW_INSTANCES, SHOW_ETHSW,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        host = _HOSTNAME.search(version_text)
        model = _MODEL.search(version_text)
        version = _JUNOS.search(version_text)
        if host is None or version is None:
            raise DiscoveryParseError(
                "device identity could not be established from 'show version'",
                adapter=ADAPTER_NAME, command=SHOW_VERSION, field="hostname",
            )
        hostname = host.group("host")
        serial = _CHASSIS_SERIAL.search(raw_outputs.get(SHOW_CHASSIS, ""))
        management_ip, warnings = self._management_ip(
            raw_outputs.get(SHOW_INT_TERSE, ""), management_ip_hint
        )
        metadata: dict[str, object] = {
            "model": model.group("model") if model else UNKNOWN,
        }
        if warnings:
            metadata["warnings"] = tuple(warnings)
        return NetworkDevice(
            device_id=f"junos:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model.group("model") if model else "Junos",
            os_name="Junos",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        """Physical interfaces and logical units, hierarchy intact.

        A logical unit (ge-0/0/0.0) records its physical parent, unit number
        and address family in metadata — the normalized identity Part 10
        requires — while remaining an ordinary canonical interface every
        downstream consumer already understands.
        """

        interfaces = []
        for match in _TERSE_ROW.finditer(raw_outputs.get(SHOW_INT_TERSE, "")):
            name = match.group("name")
            addr = match.group("addr")
            ip, prefix = (None, None)
            if addr and "/" in addr and _valid_ip(addr.split("/")[0]):
                ip, prefix = addr.split("/")
            metadata: dict[str, object] = {"source_command": SHOW_INT_TERSE}
            if "." in name:
                physical, unit = name.rsplit(".", 1)
                metadata.update({
                    "physical_interface": physical,
                    "logical_unit": int(unit) if unit.isdigit() else unit,
                })
            if match.group("family"):
                metadata["address_family"] = match.group("family")
            if prefix is not None:
                metadata["prefix_length"] = int(prefix)
            interfaces.append(NetworkInterface(
                name=name,
                ip_address=ip,
                status=match.group("admin"),
                protocol_status=match.group("link"),
                metadata=metadata,
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        host = _HOSTNAME.search(raw_outputs.get(SHOW_VERSION, ""))
        local_id = f"junos:{host.group('host')}" if host else "junos:unknown"
        neighbors = []
        for match in _LLDP_ROW.finditer(raw_outputs.get(SHOW_LLDP, "")):
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=match.group("local"),
                remote_hostname=match.group("name").split(".")[0],
                remote_interface=match.group("port"),
                remote_management_ip=None,
                protocol="lldp",
                metadata={
                    "source_command": SHOW_LLDP,
                    "remote_chassis_mac": match.group("chassis").casefold(),
                },
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
                    "process_id": None,
                    "area_id": None,
                    "vrf": "default",
                    "address_family": "ipv4",
                    "management_endpoint": False,
                    "source_command": SHOW_OSPF,
                },
            ))
        return tuple(neighbors)

    def _management_ip(self, terse: str, hint: str | None):
        warnings: list[str] = []
        addresses: dict[str, str] = {}
        for match in _TERSE_ROW.finditer(terse):
            addr = match.group("addr")
            if addr and "/" in addr and _valid_ip(addr.split("/")[0]):
                addresses[match.group("name")] = addr.split("/")[0]
        wanted = str(hint).strip() if hint else None
        if wanted and wanted in addresses.values():
            return wanted, warnings
        # me0/fxp0 are the out-of-band management ports — prefer them.
        for name, ip in addresses.items():
            if name.startswith(("me0", "fxp0", "em0")):
                return ip, warnings
        if addresses:
            return next(iter(addresses.values())), warnings
        if _valid_ip(hint):
            warnings.append(
                "management IP was not parsed from 'show interfaces terse'; "
                "using the connection address as a deterministic fallback"
            )
            return str(hint).strip(), warnings
        raise DiscoveryParseError(
            "no management IP was parsed and no connection address was supplied",
            adapter=ADAPTER_NAME, command=SHOW_INT_TERSE, field="management_ip",
        )


class JunosDriver(ProductionDriver):
    """Juniper Junos, held to the production contract."""

    platform_id = "junos"
    display_name = "Juniper Junos"
    vendor = "juniper"
    probe_command = SHOW_VERSION
    netmiko_device_type = "juniper_junos"
    session_setup = ("set cli screen-length 0", "set cli screen-width 0")
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(re.search(r"(?mi)^Junos:\s*\S+", probe_output or ""))

    @property
    def adapter(self) -> JunosAdapter:
        return JunosAdapter()

    def rejects(self, output: str) -> bool:
        """Junos's refusal grammar, not Cisco's."""

        folded = (output or "").strip().casefold()
        if not folded:
            return False
        return (
            "unknown command" in folded[:200]
            or folded.startswith("syntax error")
            or "error: unrecognized command" in folded[:200]
        )

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_VERSION,), required=True, tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (SHOW_INT_TERSE,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.LLDP, (SHOW_LLDP,), tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (SHOW_CHASSIS,)),
            CommandSpec(caps.ROUTES, (SHOW_ROUTES,)),
            CommandSpec(caps.BGP, (SHOW_BGP,)),
            CommandSpec(caps.OSPF, (SHOW_OSPF,)),
            CommandSpec(caps.VRF, (SHOW_INSTANCES,),
                        limitation="routing instances listed; per-instance "
                                   "detail is future work"),
            CommandSpec(caps.CONFIGURATION,
                        (SHOW_CONFIG, "show configuration")),
            CommandSpec(caps.MAC_TABLE, (SHOW_ETHSW,), tier=TIER_DEEP),
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
        tables = re.findall(r"(?m)^(\S+\.inet6?\.0):", raw.get(SHOW_ROUTES, ""))
        # The real RIB: Junos carries protocol and preference in brackets
        # on the prefix line, next-hops indented beneath it.
        routing_table = junos_route_dicts(raw.get(SHOW_ROUTES, ""))
        if routing_table:
            metadata["routing_table"] = routing_table
        if tables:
            metadata["routing_instances"] = tuple(sorted(set(tables)))
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
