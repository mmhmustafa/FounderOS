"""The AtlasLab switch platform driver (PR-048).

A layer-2 switch is a different shape of device, and this driver refuses to
pretend otherwise. It has:

- **no data-plane IP** — only a management address on eth0. Its own CLI says so
  ("this switch has no data-plane IP of its own");
- **no routing table**, no OSPF, no BGP.

So its picture is not interfaces-and-routes. It is **bridge ports, a MAC table,
and LLDP adjacency**: which physical ports are forwarding, which hardware
addresses were learned on each, and — since the lab images grew lldpd — which
device *names itself* on each port. Two independent witnesses to the same
physical link: the passive one (a learned source MAC) and the declarative one
(the peer's own LLDP advertisement). Where both speak, they can be
cross-checked; neither is inferred from the other.

The MAC table is collected and normalized here; turning it into links is
correlation across devices and belongs to the enterprise layer, not to a driver
that can only see one device. See ``enterprise/mac_correlation.py``. LLDP
neighbors, by contrast, ARE one device's own evidence — the peer named itself
to this switch — so they normalize right here into canonical adjacency.
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

from ..base import (
    CapabilitySpec,
    CapabilityStatus,
    DriverDiscovery,
    PlatformDriver,
)
from .lldpd import parse_lldp_neighbors


SHOW_VERSION = "show version"
SHOW_INTERFACES = "show interfaces"
SHOW_MAC_TABLE = "show mac-address-table"
SHOW_IP_INTERFACE = "show ip interface"
SHOW_LLDP = "show lldp neighbors"
SHOW_LOG = "show log"

ADAPTER_NAME = "AtlasLabSwitchAdapter"
UNKNOWN = "unknown"

_IDENTITY = re.compile(
    r"^AtlasLab switch\s*\((?P<hostname>[^)]+)\)\s*on\s+(?P<os>.+?)\s*$",
    re.MULTILINE,
)
_PRETTY_NAME = re.compile(r'PRETTY_NAME="(?P<name>[^"]+)"')

# `296: eth1@if297: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 9500 master br0
#  state forwarding priority 32 cost 2`   (`bridge link show`)
_BRIDGE_PORT = re.compile(
    r"^\d+:\s+(?P<name>[A-Za-z0-9._-]+)(?:@if\d+)?:\s+<(?P<flags>[^>]*)>"
    r"(?:.*?\bmtu\s+(?P<mtu>\d+))?"
    r"(?:.*?\bmaster\s+(?P<master>\S+))?"
    r"(?:.*?\bstate\s+(?P<state>\S+))?"
)
# `lo   UNKNOWN   127.0.0.1/8 ::1/128`   (`ip -br addr`, management only)
_ADDR = re.compile(
    r"^(?P<name>[A-Za-z0-9._-]+)(?:@if\d+)?\s+(?P<state>\S+)\s+(?P<addresses>.*)$"
)
_IPV4_CIDR = re.compile(r"\b(?P<ip>\d{1,3}(?:\.\d{1,3}){3})/(?P<prefix>\d{1,2})\b")
# `aa:c1:ab:2e:c9:0e dev eth1 master br0`   (`bridge fdb show`)
_FDB = re.compile(
    r"^(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})\s+dev\s+(?P<port>\S+)"
    r"(?P<flags>.*)$",
    re.IGNORECASE,
)

# Addresses that are never a device's identity: IPv6/IPv4 multicast mappings and
# the broadcast address. A bridge FDB is full of them, and correlating on one
# would "resolve" every device in the estate to the same link.
_MULTICAST_PREFIXES = ("33:33", "01:00:5e", "01:80:c2")
_BROADCAST = "ff:ff:ff:ff:ff:ff"


class AtlasLabSwitchAdapter(DiscoveryAdapter):
    """Parse-only normalization of the AtlasLab switch CLI."""

    vendor = "atlaslab"
    platform_family = "atlaslab-switch"
    required_commands = (SHOW_VERSION, SHOW_IP_INTERFACE)
    optional_commands = (SHOW_INTERFACES, SHOW_MAC_TABLE, SHOW_LLDP, SHOW_LOG)

    def parse_inventory(
        self,
        raw_outputs: Mapping[str, str],
        management_ip_hint: str | None = None,
    ) -> NetworkDevice:
        version_text = raw_outputs.get(SHOW_VERSION, "")
        identity = _IDENTITY.search(version_text)
        if identity is None:
            raise DiscoveryParseError(
                "device identity could not be established: "
                f"{SHOW_VERSION!r} did not report an AtlasLab switch identity",
                adapter=ADAPTER_NAME,
                command=SHOW_VERSION,
                field="hostname",
            )
        hostname = identity.group("hostname").strip()

        warnings: list[str] = []
        management_ip = self._management_ip(
            raw_outputs.get(SHOW_IP_INTERFACE, ""), management_ip_hint
        )
        if management_ip is None and _valid_ip(management_ip_hint):
            management_ip = str(management_ip_hint).strip()
            warnings.append(
                f"management IP was not parsed from '{SHOW_IP_INTERFACE}'; "
                "using the connection address as a deterministic fallback"
            )
        if management_ip is None:
            raise DiscoveryParseError(
                "device identity could not be established: no management IP "
                "was parsed and no connection address was supplied",
                adapter=ADAPTER_NAME,
                command=SHOW_IP_INTERFACE,
                field="management_ip",
            )

        pretty = _PRETTY_NAME.search(version_text)
        os_name, os_version = _split_os(pretty.group("name") if pretty else "")
        metadata: dict[str, object] = {
            "kernel": identity.group("os").strip() or UNKNOWN,
            "device_role": "switch",
            # Stated plainly so no consumer has to infer it from an absence.
            # This is why the switch has no routes and no routing peers: it is
            # not a router that failed to report them.
            "forwarding_plane": "layer-2-bridge",
            "has_data_plane_ip": False,
        }
        if warnings:
            metadata["warnings"] = tuple(warnings)

        return NetworkDevice(
            device_id=f"atlaslab-sw:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform="AtlasLab switch",
            os_name=os_name,
            os_version=os_version,
            metadata=metadata,
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        """Bridge ports first, then the management interface.

        A switch port has no IP, and that is not missing data — it is what a
        bridge port *is*. ``ip_address`` stays None and the port's real state
        (forwarding / disabled) travels in metadata, where it is the truth the
        operator wants.
        """

        interfaces: list[NetworkInterface] = []
        seen: set[str] = set()

        for line in (raw_outputs.get(SHOW_INTERFACES, "") or "").splitlines():
            match = _BRIDGE_PORT.match(line.strip())
            if match is None:
                continue
            name = match.group("name")
            flags = (match.group("flags") or "").upper()
            state = match.group("state") or UNKNOWN
            seen.add(name)
            interfaces.append(NetworkInterface(
                name=name,
                ip_address=None,
                status="up" if "UP" in flags.split(",") else "down",
                description=None,
                metadata={
                    "bridge_port": True,
                    "bridge_state": state,
                    "master": match.group("master") or UNKNOWN,
                    "mtu": int(match.group("mtu")) if match.group("mtu") else 0,
                },
            ))

        for line in (raw_outputs.get(SHOW_IP_INTERFACE, "") or "").splitlines():
            parsed = _parse_addr_line(line)
            if parsed is None or parsed.name in seen:
                continue
            interfaces.append(parsed)

        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        """LLDP adjacency — each attached device naming itself, per port.

        This is the one neighbor source a bridge has. The MAC table is NOT
        turned into neighbors here: a learned address identifies a device only
        against every other device's interface MACs, which one device's
        evidence cannot contain — that join stays in the enterprise layer
        (``enterprise/mac_correlation.py``), where both witnesses can also be
        cross-checked against each other.
        """

        text = raw_outputs.get(SHOW_LLDP, "")
        if not text.strip():
            return ()
        return parse_lldp_neighbors(
            text, local_device_id=self._safe_local_device_id(raw_outputs)
        )

    def _safe_local_device_id(self, raw_outputs: Mapping[str, str]) -> str:
        identity = _IDENTITY.search(raw_outputs.get(SHOW_VERSION, ""))
        if identity is not None:
            return f"atlaslab-sw:{identity.group('hostname').strip()}"
        return "atlaslab-sw:unknown"

    def _management_ip(self, text: str, hint: str | None) -> str | None:
        for line in (text or "").splitlines():
            parsed = _parse_addr_line(line)
            if parsed is None or parsed.ip_address is None or parsed.name == "lo":
                continue
            if hint and parsed.ip_address == str(hint).strip():
                return parsed.ip_address
        for line in (text or "").splitlines():
            parsed = _parse_addr_line(line)
            if parsed is not None and parsed.ip_address and parsed.name != "lo":
                return parsed.ip_address
        return None


class AtlasLabSwitchDriver(PlatformDriver):
    """AtlasLab layer-2 switch (Alpine + Linux bridge, AtlasLab CLI)."""

    platform_id = "atlaslab-switch"
    display_name = "AtlasLab switch"
    vendor = "atlaslab"
    probe_command = SHOW_VERSION

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(re.search(r"\bAtlasLab switch\b", probe_output or ""))

    @property
    def adapter(self) -> AtlasLabSwitchAdapter:
        return AtlasLabSwitchAdapter()

    def collection_plan(self) -> tuple[CapabilitySpec, ...]:
        return (
            CapabilitySpec("identity", SHOW_VERSION, required=True),
            CapabilitySpec("management-addressing", SHOW_IP_INTERFACE, required=True),
            CapabilitySpec("bridge-ports", SHOW_INTERFACES),
            CapabilitySpec("mac-table", SHOW_MAC_TABLE),
            CapabilitySpec("lldp-neighbors", SHOW_LLDP),
        )

    def classify_output(self, spec: CapabilitySpec, output: str) -> CapabilityStatus:
        stripped = (output or "").strip()
        folded = stripped.casefold()
        if "not found" in folded or folded.startswith("unknown command"):
            return CapabilityStatus(spec.name, "unavailable", "command not supported")
        return super().classify_output(spec, output)

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        """Carry the learned MAC table into canonical metadata.

        This is the switch's whole contribution to the enterprise graph, and it
        is inert until the correlation step reads it. Only *learned* addresses
        are kept: multicast and permanent self entries describe the bridge's own
        plumbing, not anything attached to it.
        """

        entries = parse_mac_table(discovery.raw_outputs.get(SHOW_MAC_TABLE, ""))
        metadata = dict(discovery.result.device.metadata)
        metadata["mac_table"] = entries
        metadata["learned_mac_count"] = len(entries)
        metadata["bridge_port_count"] = len(
            [i for i in discovery.result.interfaces if i.metadata.get("bridge_port")]
        )
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)


def is_learned_address(mac: str, flags: str = "") -> bool:
    """Is this a hardware address of something attached to the switch?

    A bridge FDB mixes three things: addresses *learned* from traffic (the only
    ones that identify an attached device), the bridge's own permanent `self`
    entries, and multicast/broadcast group mappings. Only the first kind can
    resolve a link. Correlating on `33:33:...` would match every device in the
    estate at once and "prove" a link between all of them.
    """

    lowered = (mac or "").strip().casefold()
    if not lowered or lowered == _BROADCAST:
        return False
    if lowered.startswith(_MULTICAST_PREFIXES):
        return False
    if "self" in (flags or "").casefold():
        return False
    if "permanent" in (flags or "").casefold():
        return False
    return True


def parse_mac_table(text: str) -> tuple[tuple[tuple[str, object], ...], ...]:
    """Learned MAC-to-port entries, as immutable canonical facts."""

    entries: list[tuple[tuple[str, object], ...]] = []
    for line in (text or "").splitlines():
        match = _FDB.match(line.strip())
        if match is None:
            continue
        mac = match.group("mac").casefold()
        flags = match.group("flags") or ""
        if not is_learned_address(mac, flags):
            continue
        entries.append(tuple(sorted({
            "mac": mac,
            "port": match.group("port"),
            "master": _master_of(flags),
        }.items(), key=lambda kv: kv[0])))
    return tuple(entries)


def _master_of(flags: str) -> str | None:
    match = re.search(r"\bmaster\s+(\S+)", flags or "")
    return match.group(1) if match else None


def _parse_addr_line(line: str) -> NetworkInterface | None:
    match = _ADDR.match((line or "").rstrip())
    if match is None:
        return None
    name = match.group("name")
    state = match.group("state").strip().casefold()
    if not name or state not in {"up", "down", "unknown", "lower_up"}:
        return None
    ipv4 = _IPV4_CIDR.search(match.group("addresses") or "")
    metadata: dict[str, object] = {"bridge_port": False}
    if ipv4:
        metadata["prefix_length"] = int(ipv4.group("prefix"))
        metadata["management"] = True
    return NetworkInterface(
        name=name,
        ip_address=ipv4.group("ip") if ipv4 else None,
        status=state,
        metadata=metadata,
    )


def _split_os(pretty: str) -> tuple[str, str]:
    parts = (pretty or "").strip().rsplit(" ", 1)
    if len(parts) == 2 and parts[1]:
        return parts[0], parts[1]
    return (pretty or UNKNOWN), UNKNOWN


def _valid_ip(value: str | None) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
