"""Deterministic Cisco IOS fixture parser with no transport behavior."""

from __future__ import annotations

from collections.abc import Mapping
import re

from ..adapter import DiscoveryAdapter
from ..exceptions import DiscoveryParseError
from ..models import NetworkDevice, NetworkInterface, NetworkNeighbor


SHOW_VERSION = "show version"
SHOW_INTERFACES = "show ip interface brief"
SHOW_NEIGHBORS = "show cdp neighbors detail"


class CiscoIOSAdapter(DiscoveryAdapter):
    vendor = "cisco"
    platform_family = "ios"
    required_commands = (SHOW_VERSION, SHOW_INTERFACES, SHOW_NEIGHBORS)

    def parse_inventory(self, raw_outputs: Mapping[str, str]) -> NetworkDevice:
        text = raw_outputs.get(SHOW_VERSION, "")
        hostname = _match(text, r"(?m)^([A-Za-z0-9._-]+) uptime is ", "hostname")
        version = _match(text, r"Cisco IOS Software.*?Version ([^,\s]+)", "IOS version")
        platform = _match(text, r"(?m)^cisco\s+(\S+)\s+\([^\n]+processor", "platform")
        serial = _match(text, r"(?m)^Processor board ID\s+(\S+)", "serial number")
        management_ip = self._management_ip(raw_outputs.get(SHOW_INTERFACES, ""))
        return NetworkDevice(
            device_id=f"cisco-ios:{hostname.casefold()}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=platform,
            os_name="Cisco IOS",
            os_version=version,
            serial_number=serial,
            metadata={"source_command": SHOW_VERSION},
        )

    def parse_interfaces(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkInterface, ...]:
        text = raw_outputs.get(SHOW_INTERFACES, "")
        interfaces: list[NetworkInterface] = []
        line_pattern = re.compile(
            r"^(?P<name>\S+)\s+(?P<ip>\S+)\s+\S+\s+\S+\s+"
            r"(?P<status>administratively down|up|down)\s+(?P<protocol>up|down)\s*$",
            re.IGNORECASE,
        )
        for line in text.splitlines():
            match = line_pattern.match(line.strip())
            if not match:
                continue
            ip_value = match.group("ip")
            interfaces.append(
                NetworkInterface(
                    name=match.group("name"),
                    ip_address=None if ip_value.lower() == "unassigned" else ip_value,
                    status=match.group("status").lower().replace(" ", "_"),
                    protocol_status=match.group("protocol").lower(),
                    metadata={"source_command": SHOW_INTERFACES},
                )
            )
        if not interfaces:
            raise DiscoveryParseError("show ip interface brief contained no parseable interfaces")
        return tuple(interfaces)

    def parse_neighbors(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkNeighbor, ...]:
        text = raw_outputs.get(SHOW_NEIGHBORS, "")
        local_device_id = self.parse_inventory(raw_outputs).device_id
        neighbors: list[NetworkNeighbor] = []
        blocks = re.split(r"(?m)^-{20,}\s*$", text)
        for block in blocks:
            if "Device ID:" not in block:
                continue
            remote_hostname = _match(block, r"(?m)^Device ID:\s*(\S+)", "CDP Device ID")
            local_interface = _match(
                block, r"(?m)^Interface:\s*([^,]+),", "CDP local interface"
            )
            remote_interface_match = re.search(
                r"Port ID \(outgoing port\):\s*([^\r\n]+)", block
            )
            remote_ip_match = re.search(r"(?m)^\s*IP address:\s*(\S+)", block)
            platform_match = re.search(r"(?m)^Platform:\s*([^,\r\n]+)", block)
            neighbors.append(
                NetworkNeighbor(
                    local_device_id=local_device_id,
                    local_interface=local_interface.strip(),
                    remote_hostname=remote_hostname,
                    remote_interface=(remote_interface_match.group(1).strip() if remote_interface_match else None),
                    remote_management_ip=(remote_ip_match.group(1) if remote_ip_match else None),
                    protocol="cdp",
                    metadata={
                        "remote_platform": platform_match.group(1).strip() if platform_match else "unknown",
                        "source_command": SHOW_NEIGHBORS,
                    },
                )
            )
        if not neighbors:
            raise DiscoveryParseError("show cdp neighbors detail contained no parseable neighbors")
        return tuple(neighbors)

    def _management_ip(self, text: str) -> str:
        interfaces = self.parse_interfaces({SHOW_INTERFACES: text})
        preferred = [
            item for item in interfaces
            if item.ip_address is not None and item.status == "up" and item.protocol_status == "up"
        ]
        if not preferred:
            raise DiscoveryParseError("no active management IP found in show ip interface brief")
        return preferred[0].ip_address or ""


def _match(text: str, pattern: str, field_name: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise DiscoveryParseError(f"show output is missing required {field_name}")
    return match.group(1).strip()
