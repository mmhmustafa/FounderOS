"""The FRRouting platform driver (vtysh CLI).

Atlas connects directly to the FRRouting vtysh CLI — no Linux shell
handling. Identity, interfaces, and OSPF adjacencies normalize into the
same canonical models every other platform uses; routes and BGP peers
are summarized into canonical device metadata. Daemons that are not
configured (OSPF/BGP) and commands vtysh does not know (LLDP) are
recorded as capabilities, never failures: discovery succeeds whenever
meaningful evidence is collected.
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

from ..base import (
    CAP_COLLECTED,
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)


SHOW_VERSION = "show version"
SHOW_INTERFACES = "show interface"
SHOW_OSPF_NEIGHBORS = "show ip ospf neighbor"
SHOW_ROUTES = "show ip route"
SHOW_BGP_SUMMARY = "show bgp summary"
SHOW_LLDP = "show lldp neighbors"
SHOW_RUNNING = "show running-config"

ADAPTER_NAME = "FRRoutingAdapter"
UNKNOWN = "unknown"

# "FRRouting 8.4.2 (delhi-r1) on Linux(5.15.0-91-generic)."
_VERSION_PATTERN = r"FRRouting\s+([0-9][^\s(]*)"
_HOSTNAME_PATTERN = r"FRRouting\s+\S+\s+\(([^)\s]+)\)"
_CONFIG_HOSTNAME_PATTERN = r"(?m)^hostname\s+(\S+)"

_INTERFACE_HEAD = re.compile(
    r"(?m)^Interface\s+(?P<name>\S+)\s+is\s+(?P<status>up|down)"
    r"(?:,\s*line protocol is\s+(?P<protocol>up|down))?",
    re.IGNORECASE,
)
# PR-043.7 (FUSION): the prefix length and secondary flag are canonical
# observations — the correlation engine needs them for point-to-point
# subnet matching and secondary-address ownership. Normalization records
# them; it never infers relationships from them.
# "  HWaddr: aa:c1:ab:f5:49:b4"
_HWADDR_PATTERN = re.compile(
    r"(?mi)^\s*HWaddr:\s*(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})\s*$"
)
_INET_PATTERN = re.compile(
    r"(?m)^\s*inet\s+(?P<address>\d+\.\d+\.\d+\.\d+)"
    r"(?:/(?P<prefix>\d+))?(?P<secondary>\s+secondary)?"
)
_DESCRIPTION_PATTERN = re.compile(r"(?m)^\s*Description:\s*(?P<text>\S[^\r\n]*)")

# "10.0.0.2  1  Full/DR  1h02m03s  31.568s  10.30.0.2  eth0:10.30.0.1 ..."
_OSPF_ROW = re.compile(
    r"(?m)^(?P<neighbor_id>\d+\.\d+\.\d+\.\d+)\s+\S+\s+(?P<state>\S+)\s+"
    r"\S+\s+\S+\s+(?P<address>\d+\.\d+\.\d+\.\d+)\s+(?P<interface>\S+)"
)

_ROUTE_CODES = {
    "K": "kernel", "C": "connected", "S": "static", "R": "rip",
    "O": "ospf", "I": "isis", "B": "bgp", "E": "eigrp", "N": "nhrp",
    "T": "table", "A": "babel", "D": "sharp", "F": "pbr", "f": "openfabric",
}


class FRRoutingAdapter(DiscoveryAdapter):
    """Parse-only normalization of vtysh output into canonical models."""

    vendor = "frrouting"
    platform_family = "frr"
    required_commands = (SHOW_VERSION, SHOW_INTERFACES, SHOW_OSPF_NEIGHBORS)
    optional_commands = (SHOW_OSPF_NEIGHBORS,)

    def parse_inventory(
        self,
        raw_outputs: Mapping[str, str],
        management_ip_hint: str | None = None,
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        warnings: list[str] = []
        version = _search(version_text, _VERSION_PATTERN)
        hostname = _search(version_text, _HOSTNAME_PATTERN) or _search(
            raw_outputs.get(SHOW_RUNNING, ""), _CONFIG_HOSTNAME_PATTERN
        )
        management_ip = self._management_ip(raw_outputs.get(SHOW_INTERFACES, ""))
        if management_ip is None and _valid_ip(management_ip_hint):
            management_ip = str(management_ip_hint).strip()
            warnings.append(
                f"management IP was not parsed from '{SHOW_INTERFACES}'; "
                "using the connection address as a deterministic fallback"
            )
        if management_ip is None:
            raise DiscoveryParseError(
                "device identity could not be established: no management IP "
                "was parsed and no connection address was supplied",
                adapter=ADAPTER_NAME,
                command=SHOW_INTERFACES,
                field="management_ip",
                raw_output=raw_outputs.get(SHOW_INTERFACES, ""),
            )
        if hostname is None:
            warnings.append(
                f"hostname was not parsed from '{SHOW_VERSION}'; "
                "using the management IP as the device identity"
            )
        if version is None:
            warnings.append(
                f"os_version was not parsed from '{SHOW_VERSION}'; "
                f"recorded as '{UNKNOWN}'"
            )
        metadata: dict[str, object] = {"source_command": SHOW_VERSION}
        if warnings:
            metadata["parse_warnings"] = tuple(warnings)
        identity = hostname.casefold() if hostname is not None else management_ip
        return NetworkDevice(
            device_id=f"frr:{identity}",
            hostname=hostname or management_ip,
            management_ip=management_ip,
            vendor=self.vendor,
            platform="FRRouting",
            os_name="FRRouting",
            os_version=version or UNKNOWN,
            serial_number=None,  # software routers have no chassis serial
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        text = raw_outputs.get(SHOW_INTERFACES, "")
        interfaces: list[NetworkInterface] = []
        heads = list(_INTERFACE_HEAD.finditer(text))
        for index, match in enumerate(heads):
            block_end = (
                heads[index + 1].start() if index + 1 < len(heads) else len(text)
            )
            block = text[match.start():block_end]
            status = match.group("status").lower()
            protocol = (match.group("protocol") or status).lower()
            description_match = _DESCRIPTION_PATTERN.search(block)
            # The first non-secondary inet line is the primary address;
            # every other assignment is a secondary observation.
            primary: re.Match | None = None
            secondaries: list[str] = []
            for inet in _INET_PATTERN.finditer(block):
                if primary is None and not inet.group("secondary"):
                    primary = inet
                else:
                    secondaries.append(inet.group("address"))
            metadata: dict[str, object] = {"source_command": SHOW_INTERFACES}
            if primary is not None and primary.group("prefix"):
                metadata["prefix_length"] = int(primary.group("prefix"))
            if secondaries:
                metadata["secondary_ips"] = tuple(secondaries)
            # PR-048: the interface's hardware address, recorded exactly as
            # vtysh reports it. A layer-2 switch learns MACs, not identities,
            # so this is the only thing that can turn "something is on port
            # eth1" into "delhi-core:eth2 is on port eth1". Recorded here as a
            # plain observation; the correlation that uses it lives in the
            # enterprise layer, which can see more than one device at a time.
            hwaddr = _HWADDR_PATTERN.search(block)
            if hwaddr:
                metadata["hardware_address"] = hwaddr.group("mac").casefold()
            interfaces.append(
                NetworkInterface(
                    name=match.group("name"),
                    ip_address=primary.group("address") if primary else None,
                    status=status,
                    protocol_status=protocol,
                    description=(
                        description_match.group("text").strip()
                        if description_match else None
                    ),
                    metadata=metadata,
                )
            )
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        """OSPF adjacencies as ROUTING evidence — never management targets.

        The Neighbor ID column is the peer's OSPF **router ID** (an
        identifier, frequently a loopback, never proven manageable) and
        the Address column is the adjacency's **interface address** on
        the shared segment. Neither is a verified management endpoint,
        so ``remote_management_ip`` stays None (PR-043.1): the adjacency
        is preserved as evidence, and recursive discovery never SSHes a
        router ID or peer address on the strength of a routing table.
        """

        text = raw_outputs.get(SHOW_OSPF_NEIGHBORS, "")
        if not text.strip() or text.strip().startswith("%"):
            # OSPF not configured is valid evidence, never an error.
            return ()
        local_device_id = self._safe_local_device_id(raw_outputs)
        neighbors: list[NetworkNeighbor] = []
        for match in _OSPF_ROW.finditer(text):
            local_interface = match.group("interface").split(":", 1)[0]
            neighbors.append(
                NetworkNeighbor(
                    local_device_id=local_device_id,
                    local_interface=local_interface,
                    remote_hostname=match.group("neighbor_id"),
                    remote_interface=None,  # OSPF does not advertise it
                    remote_management_ip=None,  # router IDs are NOT endpoints
                    protocol="ospf",
                    metadata={
                        "observation": "routing-adjacency",
                        "router_id": match.group("neighbor_id"),
                        "adjacency_address": match.group("address"),
                        "management_endpoint": False,
                        "ospf_state": match.group("state"),
                        "process_id": None,
                        "area_id": None,
                        "vrf": "default",
                        "address_family": "ipv4",
                        "source_command": SHOW_OSPF_NEIGHBORS,
                    },
                )
            )
        return tuple(neighbors)

    def _safe_local_device_id(self, raw_outputs: Mapping[str, str]) -> str:
        try:
            return self.parse_inventory(raw_outputs).device_id
        except DiscoveryParseError:
            return f"frr:{UNKNOWN}"

    def _management_ip(self, text: str) -> str | None:
        interfaces = self.parse_interfaces({SHOW_INTERFACES: text})
        assigned = [item for item in interfaces if item.ip_address is not None]
        preferred = [
            item for item in assigned
            if item.status == "up" and item.protocol_status == "up"
        ]
        for candidates in (preferred, assigned):
            if candidates:
                return candidates[0].ip_address
        return None


class FRRoutingDriver(PlatformDriver):
    platform_id = "frr"
    display_name = "FRRouting"
    vendor = "frrouting"
    probe_command = SHOW_VERSION

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(re.search(r"\bFRRouting\b", probe_output))

    @property
    def adapter(self) -> FRRoutingAdapter:
        return FRRoutingAdapter()

    def collection_plan(self) -> tuple[CapabilitySpec, ...]:
        return (
            CapabilitySpec("identity", SHOW_VERSION, required=True),
            CapabilitySpec("interfaces", SHOW_INTERFACES, required=True),
            CapabilitySpec("ospf-neighbors", SHOW_OSPF_NEIGHBORS),
            CapabilitySpec("routes", SHOW_ROUTES),
            CapabilitySpec("bgp", SHOW_BGP_SUMMARY),
            CapabilitySpec("lldp-neighbors", SHOW_LLDP),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        """Summarize route and BGP evidence into canonical metadata.

        BGP peers additionally become PROTOCOL-PEER observations —
        visible relationships with no management endpoint: a peer
        address proves a TCP/179 session, never SSH manageability.
        """

        routes = _parse_route_summary(discovery.raw_outputs.get(SHOW_ROUTES, ""))
        bgp_peers = _parse_bgp_peers(
            discovery.raw_outputs.get(SHOW_BGP_SUMMARY, "")
        )
        sessions = bgp_sessions_from_summary(
            discovery.raw_outputs.get(SHOW_BGP_SUMMARY, ""),
            source_command=SHOW_BGP_SUMMARY,
        )
        result = discovery.result
        metadata = dict(result.device.metadata)
        if routes is not None:
            metadata["routes"] = routes
        if bgp_peers is not None:
            metadata["bgp_peers"] = bgp_peers
            if bgp_peers.get("router_id"):
                # An identity claim for the ownership index (PR-043.7).
                metadata["bgp_router_id"] = bgp_peers["router_id"]
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
                source_command=SHOW_OSPF_NEIGHBORS,
            ) for item in result.neighbors if item.protocol == "ospf"
        )
        metadata["routing_evidence"] = routing_metadata(ospf=ospf, bgp=sessions)
        peer_neighbors = tuple(
            NetworkNeighbor(
                local_device_id=result.device.device_id,
                local_interface="bgp",  # a session, not a physical port
                remote_hostname=session.peer_address,
                remote_interface=None,
                remote_management_ip=None,  # peer addresses are NOT endpoints
                protocol="bgp",
                metadata={
                    "observation": "protocol-peer",
                    **session.to_dict(),
                    "management_endpoint": False,
                },
            )
            for session in sessions
        )
        result = replace(
            result,
            device=replace(result.device, metadata=metadata),
            neighbors=(*result.neighbors, *peer_neighbors),
        )
        capabilities = list(discovery.capabilities)
        if routes is not None and routes["total"] > 0:
            capabilities = [
                CapabilityStatus(
                    "routes", CAP_COLLECTED, f"{routes['total']} route(s)"
                )
                if status.name == "routes"
                else status
                for status in capabilities
            ]
        return DriverDiscovery(
            result=result,
            capabilities=tuple(capabilities),
            raw_outputs=discovery.raw_outputs,
        )


def _parse_route_summary(text: str) -> dict | None:
    if not text.strip() or text.strip().startswith("%"):
        return None
    by_protocol: dict[str, int] = {}
    total = 0
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z])[\s>*]{1,4}\S+/\d+", line.strip())
        if not match:
            continue
        protocol = _ROUTE_CODES.get(match.group(1), match.group(1))
        by_protocol[protocol] = by_protocol.get(protocol, 0) + 1
        total += 1
    if total == 0:
        return None
    return {"total": total, "by_protocol": dict(sorted(by_protocol.items()))}


def _parse_bgp_peers(text: str) -> dict | None:
    if not text.strip() or text.strip().startswith("%"):
        return None
    peers = re.findall(r"(?m)^(\d+\.\d+\.\d+\.\d+)\s+4\s+\d+", text)
    if not peers:
        return None
    summary: dict = {"count": len(peers), "peers": sorted(peers)}
    # PR-043.7 (FUSION): the device's own BGP router identifier is an
    # identity observation — the ownership index claims it so peer
    # references to the router ID resolve onto this device.
    router_id = re.search(
        r"BGP router identifier\s+(\d+\.\d+\.\d+\.\d+)", text
    )
    if router_id:
        summary["router_id"] = router_id.group(1)
    return summary


def _search(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _valid_ip(value: str | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        ip_address(value.strip())
    except ValueError:
        return False
    return True
