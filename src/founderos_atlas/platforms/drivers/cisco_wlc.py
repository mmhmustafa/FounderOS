"""The Cisco Wireless LAN Controller (AireOS) driver (POLYGLOT Wave 2, Tier 2).

A WLC is a controller, not a router: its canonical identity and
interfaces normalize like any device, while its defining evidence —
joined access points, WLANs/SSIDs, redundancy state — rides in metadata
as ``wireless_evidence``. Access points appear as CDP-observed
neighbors THROUGH the controller (the AP name is the neighbor of the
wired switch it reports), so topology shows the wired attachment
without inventing wireless links.

Maturity: **EXPERIMENTAL** — TRANSCRIPT VALIDATED only (sanitized
AireOS 8.10 transcripts; no live controller was available).
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
from ..capabilities import CommandSpec, EXPERIMENTAL, TIER_DEEP, TIER_FAST
from ..production import DriverDiscovery, ProductionDriver

SHOW_SYSINFO = "show sysinfo"
SHOW_INVENTORY = "show inventory"
SHOW_INTERFACES = "show interface summary"
SHOW_APS = "show ap summary"
SHOW_WLANS = "show wlan summary"
SHOW_CDP = "show ap cdp neighbors all"
SHOW_REDUNDANCY = "show redundancy summary"
SHOW_CONFIG = "show run-config commands"

ADAPTER_NAME = "CiscoWlcAdapter"

_DOTTED_KV = re.compile(r"(?m)^(?P<key>[A-Za-z0-9 ()+./'-]+?)\.{2,}\s*(?P<value>.*)$")
_SERIAL = re.compile(r"PID:\s*(?P<pid>\S+?),\s*VID:\s*\S+,\s*SN:\s*(?P<serial>\S+)")
_IFACE_ROW = re.compile(
    r"(?m)^(?P<name>[a-z][\w-]*)\s+\S+\s+\S+\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s+\S+"
)
_AP_ROW = re.compile(
    r"(?m)^(?P<name>\S+)\s+\d+\s+(?P<model>AIR-\S+)\s+"
    r"(?P<mac>[0-9a-f:]{17})\s+(?P<location>\S+)\s+\S+\s+"
    r"(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<clients>\d+)"
)
_WLAN_ROW = re.compile(
    r"(?m)^(?P<wid>\d+)\s+(?P<profile>\S+)\s*/\s*(?P<ssid>\S+)\s+"
    r"(?P<status>Enabled|Disabled)\s+(?P<iface>\S+)"
)
_CDP_ROW = re.compile(
    r"(?m)^(?P<ap>\S+)\s+(?P<ap_ip>\d+\.\d+\.\d+\.\d+)\s+(?P<neighbor>\S+)\s+"
    r"(?P<n_ip>\d+\.\d+\.\d+\.\d+)\s+(?P<port>\S+)\s*$"
)
_REDUNDANCY_MODE = re.compile(r"(?mi)^Redundancy Mode\s*=\s*(?P<mode>.+?)\s*$")
_LOCAL_STATE = re.compile(r"(?mi)^\s*Local State\s*=\s*(?P<state>\S+)")
_PEER_STATE = re.compile(r"(?mi)^\s*Peer State\s*=\s*(?P<state>.+?)\s*$")


def _sysinfo(text: str) -> dict[str, str]:
    return {
        match.group("key").strip(): match.group("value").strip()
        for match in _DOTTED_KV.finditer(text or "")
    }


class CiscoWlcAdapter(DiscoveryAdapter):
    """Parse-only normalization of AireOS CLI output."""

    vendor = "cisco"
    platform_family = "cisco-wlc"
    required_commands = (SHOW_SYSINFO, SHOW_INTERFACES)
    optional_commands = (
        SHOW_INVENTORY, SHOW_APS, SHOW_WLANS, SHOW_CDP,
        SHOW_REDUNDANCY, SHOW_CONFIG,
    )

    def parse_inventory(
        self, raw_outputs: Mapping[str, str], management_ip_hint: str | None = None
    ) -> NetworkDevice:
        info = _sysinfo(raw_outputs.get(SHOW_SYSINFO, ""))
        hostname = info.get("System Name")
        if not hostname:
            raise DiscoveryParseError(
                "device identity could not be established from "
                f"{SHOW_SYSINFO!r}",
                adapter=ADAPTER_NAME, command=SHOW_SYSINFO, field="hostname",
            )
        serial = _SERIAL.search(raw_outputs.get(SHOW_INVENTORY, ""))
        management_ip = info.get("IP Address")
        if not _valid_ip(management_ip):
            if not _valid_ip(management_ip_hint):
                raise DiscoveryParseError(
                    "no management IP was parsed and no connection address "
                    "was supplied",
                    adapter=ADAPTER_NAME, command=SHOW_SYSINFO,
                    field="management_ip",
                )
            management_ip = str(management_ip_hint).strip()
        return NetworkDevice(
            device_id=f"cisco-wlc:{hostname}",
            hostname=hostname,
            management_ip=management_ip,
            vendor=self.vendor,
            platform=(
                serial.group("pid") if serial else
                info.get("Product Name", "Cisco Controller")
            ),
            os_name="AireOS",
            os_version=info.get("Product Version", "unknown"),
            serial_number=serial.group("serial") if serial else None,
            metadata={
                "model": serial.group("pid") if serial else "unknown",
                "device_role": "wireless-controller",
                **(
                    {"location": info["System Location"]}
                    if info.get("System Location") else {}
                ),
            },
        )

    def parse_interfaces(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkInterface, ...]:
        interfaces: list[NetworkInterface] = []
        for match in _IFACE_ROW.finditer(raw_outputs.get(SHOW_INTERFACES, "")):
            interfaces.append(NetworkInterface(
                name=match.group("name"),
                ip_address=match.group("ip"),
                status="up",
                metadata={"source_command": SHOW_INTERFACES},
            ))
        return tuple(interfaces)

    def parse_neighbors(
        self, raw_outputs: Mapping[str, str]
    ) -> tuple[NetworkNeighbor, ...]:
        info = _sysinfo(raw_outputs.get(SHOW_SYSINFO, ""))
        local_id = f"cisco-wlc:{info.get('System Name', 'unknown')}"
        neighbors: list[NetworkNeighbor] = []
        seen: set[tuple[str, str]] = set()
        for match in _CDP_ROW.finditer(raw_outputs.get(SHOW_CDP, "")):
            if match.group("neighbor") in ("Neighbor",):
                continue
            key = (match.group("neighbor"), match.group("port"))
            if key in seen:
                continue
            seen.add(key)
            # The WIRED switch each AP reports through — real link-layer
            # evidence observed by the AP, attributed via the controller.
            neighbors.append(NetworkNeighbor(
                local_device_id=local_id,
                local_interface=f"ap:{match.group('ap')}",
                remote_hostname=match.group("neighbor"),
                remote_interface=match.group("port"),
                remote_management_ip=match.group("n_ip"),
                protocol="cdp",
                metadata={
                    "observation": "link-layer",
                    "observed_via_ap": match.group("ap"),
                    "management_endpoint": False,
                    "source_command": SHOW_CDP,
                },
            ))
        return tuple(neighbors)


class CiscoWlcDriver(ProductionDriver):
    """Cisco WLC (AireOS), held to the production contract."""

    platform_id = "cisco-wlc"
    display_name = "Cisco Wireless LAN Controller"
    vendor = "cisco"
    probe_command = SHOW_SYSINFO
    banner_fingerprints = (r"cisco controller",)
    prompt_fingerprints = (r"\(Cisco Controller\) ?> ?$",)
    netmiko_device_type = "cisco_wlc"
    session_setup = ("config paging disable",)
    maturity = EXPERIMENTAL

    @classmethod
    def matches(cls, probe_output: str) -> bool:
        text = probe_output or ""
        return "Cisco Controller" in text and "Product Version" in text

    @property
    def adapter(self) -> CiscoWlcAdapter:
        return CiscoWlcAdapter()

    def command_plan(self) -> tuple[CommandSpec, ...]:
        return (
            CommandSpec(caps.IDENTITY, (SHOW_SYSINFO,),
                        required=True, tier=TIER_FAST),
            CommandSpec(caps.INVENTORY, (SHOW_INVENTORY,), tier=TIER_FAST),
            CommandSpec(caps.INTERFACE_ADDRESSES, (SHOW_INTERFACES,),
                        required=True, tier=TIER_FAST),
            CommandSpec("access-points", (SHOW_APS,)),
            CommandSpec("wlans", (SHOW_WLANS,)),
            CommandSpec(caps.CDP, (SHOW_CDP,)),
            CommandSpec("redundancy", (SHOW_REDUNDANCY,)),
            CommandSpec(caps.CONFIGURATION, (SHOW_CONFIG,), tier=TIER_DEEP),
        )

    def rejects(self, output: str) -> bool:
        folded = (output or "").strip().casefold()
        return folded.startswith("incorrect usage") or (
            "invalid command" in folded[:120]
        )

    def annotate(self, discovery: DriverDiscovery) -> DriverDiscovery:
        raw = discovery.raw_outputs
        metadata = dict(discovery.result.device.metadata)

        aps = tuple(
            {
                "name": m.group("name"),
                "model": m.group("model"),
                "location": m.group("location"),
                "ip_address": m.group("ip"),
                "clients": int(m.group("clients")),
            }
            for m in _AP_ROW.finditer(raw.get(SHOW_APS, ""))
        )
        wlans = tuple(
            {
                "wlan_id": m.group("wid"),
                "profile": m.group("profile"),
                "ssid": m.group("ssid"),
                "enabled": m.group("status") == "Enabled",
            }
            for m in _WLAN_ROW.finditer(raw.get(SHOW_WLANS, ""))
        )
        redundancy_text = raw.get(SHOW_REDUNDANCY, "")
        mode = _REDUNDANCY_MODE.search(redundancy_text)
        local_state = _LOCAL_STATE.search(redundancy_text)
        peer_state = _PEER_STATE.search(redundancy_text)
        if aps or wlans:
            metadata["wireless_evidence"] = {
                "schema_version": "1.0.0",
                "access_points": aps,
                "wlans": wlans,
                "access_point_count": len(aps),
                "client_count": sum(ap["clients"] for ap in aps),
                "redundancy": {
                    "mode": mode.group("mode") if mode else None,
                    "local_state": (
                        local_state.group("state") if local_state else None
                    ),
                    "peer_state": (
                        peer_state.group("state") if peer_state else None
                    ),
                },
            }
        result = replace(
            discovery.result,
            device=replace(discovery.result.device, metadata=metadata),
        )
        return replace(discovery, result=result)


def _valid_ip(value) -> bool:
    try:
        ip_address(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True
