"""Application-delivery platforms (POLYGLOT Wave 2, Tier 3):
F5 BIG-IP (tmsh), Citrix ADC (NetScaler CLI), A10 ACOS.

An ADC is a load balancer, not a router and not a firewall: identity and
addressed interfaces normalize into the same canonical models as every
platform, while the defining evidence — virtual servers and their
observed availability — rides in ``device.metadata["adc_evidence"]``.
Only summary facts are collected (name, address, protocol, state); no
pool member enumeration, no certificates, no persistence internals.

Maturity: **EXPERIMENTAL** — TRANSCRIPT VALIDATED only. No live BIG-IP,
NetScaler or Thunder was available; parsers are exercised against
sanitized transcripts of 17.1 / NS13.1 / ACOS 5.2 output.
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

from .. import capabilities as caps
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True


def _adc_metadata(virtual_servers: tuple[dict, ...]) -> dict:
    return {
        "schema_version": "1.0.0",
        "virtual_servers": virtual_servers,
        "virtual_server_count": len(virtual_servers),
        "virtual_servers_up": sum(
            1 for item in virtual_servers if item.get("state") == "up"
        ),
    }


# =============================================================================
# F5 BIG-IP (tmsh)
# =============================================================================

F5_VERSION = "show sys version"
F5_HARDWARE = "show sys hardware"
F5_HOSTNAME = "list sys global-settings hostname"
F5_MGMT_IP = "list sys management-ip"
F5_SELF = "list net self"
F5_INTERFACES = "show net interface"
F5_VIRTUAL = "show ltm virtual"
F5_DEVICES = "show cm device"

_F5_PRODUCT = re.compile(r"(?m)^\s*Product\s+(?P<product>\S+)")
_F5_VERSION_RE = re.compile(r"(?m)^\s*Version\s+(?P<version>[\d.]+)")
_F5_PLATFORM = re.compile(r"(?m)^\s*Model\s+(?P<model>.+?)\s*$")
_F5_SERIAL = re.compile(r"(?mi)^\s*(?:Appliance|Chassis) Serial\s+(?P<serial>\S+)")
_F5_HOSTNAME_RE = re.compile(r"(?m)^\s*hostname\s+(?P<host>\S+)")
_F5_MGMT_RE = re.compile(r"(?m)^sys management-ip (?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)")
_F5_SELF_RE = re.compile(
    r"(?ms)^net self (?P<name>\S+) \{.*?address (?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)"
    r".*?(?:vlan (?P<vlan>\S+))?\n\}"
)
_F5_IFACE_RE = re.compile(r"(?m)^(?P<name>[\w./]+)\s+(?P<status>up|down)\s+")
_F5_VS_RE = re.compile(
    r"(?ms)Ltm::Virtual Server: (?P<name>\S+).*?"
    r"Availability\s+:\s+(?P<avail>\S+).*?"
    r"Destination\s+:\s+(?P<dest>\S+)"
)
_F5_DEVICE_RE = re.compile(
    r"(?ms)CentMgmt::Device\s*\nName\s+(?P<name>\S+)\s*\n"
    r"Failover State\s+(?P<state>\S+)"
)


class F5BigIpAdapter(DiscoveryAdapter):
    vendor = "f5"
    platform_family = "f5-bigip"
    required_commands = (F5_VERSION, F5_HOSTNAME)
    optional_commands = (
        F5_HARDWARE, F5_MGMT_IP, F5_SELF, F5_INTERFACES, F5_VIRTUAL,
        F5_DEVICES,
    )

    def parse_inventory(self, raw_outputs, management_ip_hint=None):
        version = _F5_VERSION_RE.search(raw_outputs.get(F5_VERSION, ""))
        host = _F5_HOSTNAME_RE.search(raw_outputs.get(F5_HOSTNAME, ""))
        if version is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established",
                adapter="F5BigIpAdapter", command=F5_VERSION, field="hostname",
            )
        mgmt = _F5_MGMT_RE.search(raw_outputs.get(F5_MGMT_IP, ""))
        management_ip = mgmt.group("ip") if mgmt else (
            str(management_ip_hint).strip()
            if _valid_ip(management_ip_hint) else None
        )
        if management_ip is None:
            raise DiscoveryParseError(
                "no management IP was parsed and no connection address "
                "was supplied",
                adapter="F5BigIpAdapter", command=F5_MGMT_IP,
                field="management_ip",
            )
        model = _F5_PLATFORM.search(raw_outputs.get(F5_HARDWARE, ""))
        serial = _F5_SERIAL.search(raw_outputs.get(F5_HARDWARE, ""))
        return NetworkDevice(
            device_id=f"f5-bigip:{host.group('host')}",
            hostname=host.group("host"),
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model.group("model") if model else "BIG-IP",
            os_name="TMOS",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata={
                "model": model.group("model") if model else "unknown",
                "device_role": "load-balancer",
            },
        )

    def parse_interfaces(self, raw_outputs):
        interfaces: list[NetworkInterface] = []
        for match in _F5_SELF_RE.finditer(raw_outputs.get(F5_SELF, "")):
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=match.group("ip"),
                status="up",
                metadata={
                    "source_command": F5_SELF,
                    "prefix_length": int(match.group("prefix")),
                    **(
                        {"vlan": match.group("vlan")}
                        if match.group("vlan") else {}
                    ),
                },
            ))
        mgmt = _F5_MGMT_RE.search(raw_outputs.get(F5_MGMT_IP, ""))
        if mgmt:
            interfaces.append(NetworkInterface(
                name="mgmt",
                ip_address=mgmt.group("ip"),
                status="up",
                metadata={
                    "source_command": F5_MGMT_IP,
                    "prefix_length": int(mgmt.group("prefix")),
                },
            ))
        return tuple(interfaces)

    def parse_neighbors(self, raw_outputs):
        return ()


class F5BigIpDriver(ProductionDriver):
    platform_id = "f5-bigip"
    display_name = "F5 BIG-IP"
    vendor = "f5"
    probe_command = F5_VERSION
    banner_fingerprints = (r"big-?ip",)
    prompt_fingerprints = (r"\(tmos\)# ?$",)
    netmiko_device_type = "f5_tmsh"
    session_setup = ()
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return bool(_F5_PRODUCT.search(probe_output or "")) and (
            "BIG-IP" in (probe_output or "")
        )

    @property
    def adapter(self) -> F5BigIpAdapter:
        return F5BigIpAdapter()

    def command_plan(self):
        return (
            CommandSpec(caps.VERSION, (F5_VERSION,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.IDENTITY, (F5_HOSTNAME,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (F5_HARDWARE,), tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (F5_MGMT_IP,),
                        tier=TIER_FAST),
            CommandSpec("self-ips", (F5_SELF,)),
            CommandSpec(caps.INTERFACES, (F5_INTERFACES,)),
            CommandSpec("virtual-servers", (F5_VIRTUAL,)),
            CommandSpec("ha", (F5_DEVICES,)),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        return folded.startswith("syntax error")

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        virtual_servers = tuple(
            {
                "name": m.group("name"),
                "destination": m.group("dest"),
                "state": (
                    "up" if m.group("avail") == "available" else "down"
                ),
            }
            for m in _F5_VS_RE.finditer(raw.get(F5_VIRTUAL, ""))
        )
        if virtual_servers:
            metadata["adc_evidence"] = _adc_metadata(virtual_servers)
        devices = tuple(
            {"name": m.group("name"), "failover_state": m.group("state")}
            for m in _F5_DEVICE_RE.finditer(raw.get(F5_DEVICES, ""))
        )
        if len(devices) > 1:
            metadata["ha_devices"] = devices
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)


# =============================================================================
# Citrix ADC (NetScaler)
# =============================================================================

NS_VERSION = "show ns version"
NS_HOSTNAME = "show ns hostname"
NS_HARDWARE = "show ns hardware"
NS_IP = "show ns ip"
NS_VSERVER = "show lb vserver"
NS_HA = "show ha node"

_NS_VERSION_RE = re.compile(r"NetScaler NS(?P<version>[\d.]+): Build (?P<build>\S+?),")
_NS_HOSTNAME_RE = re.compile(r"(?mi)^\s*Hostname:\s*(?P<host>\S+)")
_NS_PLATFORM_RE = re.compile(r"(?mi)^\s*Platform:\s*(?P<platform>\S+)")
_NS_SERIAL_RE = re.compile(r"(?mi)^\s*Serial no:\s*(?P<serial>\S+)")
_NS_IP_RE = re.compile(
    r"(?m)^\d+\)\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<kind>NetScaler IP|SNIP|VIP)"
)
_NS_VS_RE = re.compile(
    r"(?ms)^\d+\)\s+(?P<name>\S+) \((?P<dest>[\d.:]+)\) - (?P<proto>\S+).*?"
    r"State: (?P<state>\S+)"
)
_NS_HA_RE = re.compile(
    r"(?ms)^\d+\)\s+Node ID:\s+\d+\s*\n\s+IP:\s+(?P<ip>\d+\.\d+\.\d+\.\d+).*?"
    r"Master State: (?P<role>\S+)"
)


class CitrixAdcAdapter(DiscoveryAdapter):
    vendor = "citrix"
    platform_family = "citrix-adc"
    required_commands = (NS_VERSION, NS_HOSTNAME, NS_IP)
    optional_commands = (NS_HARDWARE, NS_VSERVER, NS_HA)

    def parse_inventory(self, raw_outputs, management_ip_hint=None):
        version = _NS_VERSION_RE.search(raw_outputs.get(NS_VERSION, ""))
        host = _NS_HOSTNAME_RE.search(raw_outputs.get(NS_HOSTNAME, ""))
        if version is None or host is None:
            raise DiscoveryParseError(
                "device identity could not be established",
                adapter="CitrixAdcAdapter", command=NS_VERSION,
                field="hostname",
            )
        nsip = next(
            (m.group("ip") for m in _NS_IP_RE.finditer(
                raw_outputs.get(NS_IP, "")
            ) if m.group("kind") == "NetScaler IP"),
            None,
        )
        management_ip = nsip or (
            str(management_ip_hint).strip()
            if _valid_ip(management_ip_hint) else None
        )
        if management_ip is None:
            raise DiscoveryParseError(
                "no management IP was parsed and no connection address "
                "was supplied",
                adapter="CitrixAdcAdapter", command=NS_IP,
                field="management_ip",
            )
        platform = _NS_PLATFORM_RE.search(raw_outputs.get(NS_HARDWARE, ""))
        serial = _NS_SERIAL_RE.search(raw_outputs.get(NS_HARDWARE, ""))
        return NetworkDevice(
            device_id=f"citrix-adc:{host.group('host')}",
            hostname=host.group("host"),
            management_ip=management_ip,
            vendor=self.vendor,
            platform=platform.group("platform") if platform else "NetScaler",
            os_name="NetScaler",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata={
                "model": platform.group("platform") if platform else "unknown",
                "device_role": "load-balancer",
            },
        )

    def parse_interfaces(self, raw_outputs):
        interfaces: list[NetworkInterface] = []
        for match in _NS_IP_RE.finditer(raw_outputs.get(NS_IP, "")):
            kind = {
                "NetScaler IP": "nsip", "SNIP": "snip", "VIP": "vip",
            }[match.group("kind")]
            interfaces.append(NetworkInterface(
                name=f"{kind}-{match.group('ip')}",
                ip_address=match.group("ip"),
                status="up",
                metadata={"source_command": NS_IP, "address_kind": kind},
            ))
        return tuple(interfaces)

    def parse_neighbors(self, raw_outputs):
        return ()


class CitrixAdcDriver(ProductionDriver):
    platform_id = "citrix-adc"
    display_name = "Citrix ADC"
    vendor = "citrix"
    probe_command = NS_VERSION
    banner_fingerprints = (r"netscaler", r"citrix adc")
    prompt_fingerprints = (r"^> ?$",)
    netmiko_device_type = "netscaler"
    session_setup = ()
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return "NetScaler NS" in (probe_output or "")

    @property
    def adapter(self) -> CitrixAdcAdapter:
        return CitrixAdcAdapter()

    def command_plan(self):
        return (
            CommandSpec(caps.VERSION, (NS_VERSION,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.IDENTITY, (NS_HOSTNAME,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (NS_HARDWARE,), tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (NS_IP,),
                        required=True, tier=TIER_FAST),
            CommandSpec("virtual-servers", (NS_VSERVER,)),
            CommandSpec("ha", (NS_HA,)),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        return folded.startswith("error:")

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        virtual_servers = tuple(
            {
                "name": m.group("name"),
                "destination": m.group("dest"),
                "protocol": m.group("proto"),
                "state": "up" if m.group("state") == "UP" else "down",
            }
            for m in _NS_VS_RE.finditer(raw.get(NS_VSERVER, ""))
        )
        if virtual_servers:
            metadata["adc_evidence"] = _adc_metadata(virtual_servers)
        nodes = tuple(
            {"ip": m.group("ip"), "role": m.group("role").casefold()}
            for m in _NS_HA_RE.finditer(raw.get(NS_HA, ""))
        )
        if len(nodes) > 1:
            metadata["ha_devices"] = nodes
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)


# =============================================================================
# A10 ACOS
# =============================================================================

A10_VERSION = "show version"
A10_HOSTNAME = "show hostname"
A10_INTERFACES = "show interfaces brief"
A10_SLB = "show slb virtual-server"

_A10_VERSION_RE = re.compile(
    r"Advanced Core OS \(ACOS\) version (?P<version>\S+?),"
)
_A10_MODEL_RE = re.compile(r"(?m)Gateway (?P<model>TH\S+)\s*$")
_A10_SERIAL_RE = re.compile(r"(?mi)^\s*Serial Number:\s*(?P<serial>\S+)")
_A10_HOSTNAME_RE = re.compile(r"(?mi)^\s*Name:\s*(?P<host>\S+)")
_A10_IFACE_RE = re.compile(
    r"(?m)^(?P<name>\S+)\s+(?P<link>Up|Down)\s+\S+\s+\S+\s+\S+\s+\S+\s+"
    r"[0-9a-f.]+\s+(?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<prefix>\d+)"
)
_A10_VS_RE = re.compile(
    r"(?ms)^Virtual Server Name:\s+(?P<name>\S+)\s+IP:\s+(?P<ip>\d+\.\d+\.\d+\.\d+).*?"
    r"Port \d+\s+\S+?: (?P<state>UP|DOWN)"
)


class A10AcosAdapter(DiscoveryAdapter):
    vendor = "a10"
    platform_family = "a10-acos"
    required_commands = (A10_VERSION, A10_INTERFACES)
    optional_commands = (A10_HOSTNAME, A10_SLB)

    def parse_inventory(self, raw_outputs, management_ip_hint=None):
        version = _A10_VERSION_RE.search(raw_outputs.get(A10_VERSION, ""))
        host = _A10_HOSTNAME_RE.search(raw_outputs.get(A10_HOSTNAME, ""))
        if version is None:
            raise DiscoveryParseError(
                "device identity could not be established",
                adapter="A10AcosAdapter", command=A10_VERSION,
                field="version",
            )
        hostname = host.group("host") if host else "a10-unknown"
        entries = [
            (m.group("name"), m.group("ip"))
            for m in _A10_IFACE_RE.finditer(
                raw_outputs.get(A10_INTERFACES, "")
            )
            if m.group("ip") != "0.0.0.0"
        ]
        wanted = (
            str(management_ip_hint).strip()
            if _valid_ip(management_ip_hint) else None
        )
        management_ip = next(
            (ip for name, ip in entries if name == "mgmt"),
            next((ip for _n, ip in entries if wanted and ip == wanted),
                 entries[0][1] if entries else wanted),
        )
        if management_ip is None:
            raise DiscoveryParseError(
                "no management IP was parsed and no connection address "
                "was supplied",
                adapter="A10AcosAdapter", command=A10_INTERFACES,
                field="management_ip",
            )
        model = _A10_MODEL_RE.search(raw_outputs.get(A10_VERSION, ""))
        serial = _A10_SERIAL_RE.search(raw_outputs.get(A10_VERSION, ""))
        return NetworkDevice(
            device_id=f"a10-acos:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=model.group("model") if model else "A10 Thunder",
            os_name="ACOS",
            os_version=version.group("version"),
            serial_number=serial.group("serial") if serial else None,
            metadata={
                "model": model.group("model") if model else "unknown",
                "device_role": "load-balancer",
            },
        )

    def parse_interfaces(self, raw_outputs):
        interfaces: list[NetworkInterface] = []
        for match in _A10_IFACE_RE.finditer(
            raw_outputs.get(A10_INTERFACES, "")
        ):
            ip = match.group("ip")
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=None if ip == "0.0.0.0" else ip,
                status="up" if match.group("link") == "Up" else "down",
                metadata={
                    "source_command": A10_INTERFACES,
                    **(
                        {"prefix_length": int(match.group("prefix"))}
                        if ip != "0.0.0.0" else {}
                    ),
                },
            ))
        return tuple(interfaces)

    def parse_neighbors(self, raw_outputs):
        return ()


class A10AcosDriver(ProductionDriver):
    platform_id = "a10-acos"
    display_name = "A10 ACOS"
    vendor = "a10"
    probe_command = A10_VERSION
    banner_fingerprints = (r"a10 networks", r"thunder")
    prompt_fingerprints = (r"[\w-]+(?:-Active)?[#>] ?$",)
    netmiko_device_type = "a10"
    session_setup = ()
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        return "Advanced Core OS (ACOS)" in (probe_output or "")

    @property
    def adapter(self) -> A10AcosAdapter:
        return A10AcosAdapter()

    def command_plan(self):
        return (
            CommandSpec(caps.IDENTITY, (A10_VERSION,),
                        required=True, tier=TIER_FAST),
            CommandSpec("hostname", (A10_HOSTNAME,), tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (A10_INTERFACES,),
                        required=True, tier=TIER_FAST),
            CommandSpec("virtual-servers", (A10_SLB,)),
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)
        virtual_servers = tuple(
            {
                "name": m.group("name"),
                "destination": m.group("ip"),
                "state": "up" if m.group("state") == "UP" else "down",
            }
            for m in _A10_VS_RE.finditer(raw.get(A10_SLB, ""))
        )
        if virtual_servers:
            metadata["adc_evidence"] = _adc_metadata(virtual_servers)
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)
