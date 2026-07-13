"""Deterministic Cisco IOS/IOS-XE parser tolerant of real-world CLI variation."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
import re

from ..adapter import DiscoveryAdapter
from ..exceptions import DiscoveryParseError
from ..models import NetworkDevice, NetworkInterface, NetworkNeighbor


SHOW_VERSION = "show version"
SHOW_INTERFACES = "show ip interface brief"
SHOW_NEIGHBORS = "show cdp neighbors detail"

ADAPTER_NAME = "CiscoIOSAdapter"
UNKNOWN = "unknown"

_HOSTNAME_PATTERN = r"(?m)^\s*([A-Za-z0-9._-]+) uptime is "
_VERSION_PATTERN = r"Cisco IOS(?:[ -]XE)? Software.*?Version ([^,\s]+)"
_SERIAL_PATTERN = r"(?m)^Processor board ID\s+(\S+)"
# Real devices report the platform in several shapes; try each in order.
_PLATFORM_PATTERNS = (
    # Classic hardware: "cisco WS-C2960X-48FPS-L (APM86XXX) processor ..."
    r"(?m)^cisco\s+(\S+)\s+\([^\n]+processor",
    # Virtual platforms: "Cisco IOSv (revision 1.0) with ... memory."
    r"(?m)^cisco\s+([A-Za-z0-9._/-]+)\s+\(revision",
    # Banner line: "Cisco IOS Software, IOSv Software (VIOS-...), Version ..."
    r"Cisco IOS(?:[ -]XE)? Software,\s*([A-Za-z0-9._/-]+)\s+Software",
)


class CiscoIOSAdapter(DiscoveryAdapter):
    vendor = "cisco"
    platform_family = "ios"
    required_commands = (SHOW_VERSION, SHOW_INTERFACES, SHOW_NEIGHBORS)
    optional_commands = (SHOW_INTERFACES, SHOW_NEIGHBORS)

    def parse_inventory(
        self,
        raw_outputs: Mapping[str, str],
        management_ip_hint: str | None = None,
    ) -> NetworkDevice:
        text = raw_outputs.get(SHOW_VERSION, "")
        warnings: list[str] = []

        hostname = _search(text, _HOSTNAME_PATTERN)
        version = _search(text, _VERSION_PATTERN)
        serial = _search(text, _SERIAL_PATTERN)
        platform = next(
            (found for pattern in _PLATFORM_PATTERNS if (found := _search(text, pattern))),
            None,
        )
        if re.search(r"Cisco IOS[ -]XE Software", text, re.IGNORECASE):
            os_name = "IOS-XE"
        elif re.search(r"Cisco IOS Software", text, re.IGNORECASE):
            os_name = "IOS"
        else:
            os_name = None

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
        for field_name, value in (
            ("platform", platform),
            ("os_name", os_name),
            ("os_version", version),
        ):
            if value is None:
                warnings.append(
                    f"{field_name} was not parsed from '{SHOW_VERSION}'; "
                    f"recorded as '{UNKNOWN}'"
                )
        if serial is None:
            warnings.append(f"serial number was not parsed from '{SHOW_VERSION}'")

        metadata: dict[str, object] = {"source_command": SHOW_VERSION}
        if warnings:
            metadata["parse_warnings"] = tuple(warnings)
        identity = hostname.casefold() if hostname is not None else management_ip
        return NetworkDevice(
            device_id=f"cisco-ios:{identity}",
            hostname=hostname or management_ip,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=platform or UNKNOWN,
            os_name=os_name or UNKNOWN,
            os_version=version or UNKNOWN,
            serial_number=serial,
            metadata=metadata,
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
        return tuple(interfaces)

    def parse_neighbors(self, raw_outputs: Mapping[str, str]) -> tuple[NetworkNeighbor, ...]:
        text = raw_outputs.get(SHOW_NEIGHBORS, "")
        blocks = [
            block
            for block in re.split(r"(?m)^-{20,}\s*$", text)
            if "Device ID:" in block
        ]
        if not blocks:
            # A device with CDP disabled or no neighbors is valid, not an error.
            return ()
        local_device_id = self._safe_local_device_id(raw_outputs)
        neighbors: list[NetworkNeighbor] = []
        for block in blocks:
            remote_hostname = _search(block, r"(?m)^Device ID:\s*(\S+)")
            local_interface = _search(block, r"(?m)^Interface:\s*([^,]+),")
            if remote_hostname is None or local_interface is None:
                # Skip malformed blocks rather than failing the whole discovery.
                continue
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
                        # PR-043.1: a CDP-advertised address is the device
                        # ANNOUNCING its own management entry — legitimate
                        # evidence for recursive discovery eligibility.
                        # (Asserted only when present: a CDP neighbor
                        # without an address stays eligible-by-protocol and
                        # is skipped for the missing address, not for
                        # eligibility.)
                        "observation": "link-layer",
                        **(
                            {"management_endpoint": True}
                            if remote_ip_match
                            else {}
                        ),
                        "source_command": SHOW_NEIGHBORS,
                    },
                )
            )
        return tuple(neighbors)

    def _safe_local_device_id(self, raw_outputs: Mapping[str, str]) -> str:
        try:
            return self.parse_inventory(raw_outputs).device_id
        except DiscoveryParseError:
            # The engine re-parents neighbors onto the resolved device identity.
            return f"cisco-ios:{UNKNOWN}"

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


def _search(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
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
