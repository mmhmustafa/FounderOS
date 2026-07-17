"""Parsing lldpd's `show lldp neighbors` output (PR-048).

The AtlasLab switch and firewall images run lldpd and expose its neighbor
table through their CLI. Both platforms print the identical lldpd text format,
so the parser lives once, here, and each driver's adapter calls it.

LLDP is the strongest neighbor evidence Atlas collects on these platforms:

- ``SysName`` is the peer naming *itself* (not a routing identifier);
- ``MgmtIP`` is the peer advertising *its own management address* — the same
  class of evidence as CDP's management IP, which traversal already follows;
- ``PortDescr`` names the far interface, which no routing protocol reports.

The FRR routers do NOT expose this command (vtysh rejects it), so routers still
cannot see the switches beside them. LLDP flows one way in this estate: the L2
devices see everyone, nobody sees them. Finding a switch still takes a CIDR
sweep; explaining what it is plugged into no longer does.
"""

from __future__ import annotations

import re

from founderos_atlas.discovery.models import NetworkNeighbor


# lldpd separates neighbor blocks with dashed rules:
#
#   -----------------------------------------------------------------------
#   Interface:    eth1, via: LLDP, RID: 3, Time: 0 day, 00:08:17
#     Chassis:
#       ChassisID:    mac aa:c1:ab:54:1a:67
#       SysName:      mumbai-core
#       MgmtIP:       172.20.20.4
#       Capability:   Router, on
#     Port:
#       PortID:       mac aa:c1:ab:2e:14:18
#       PortDescr:    eth3
_BLOCK_SPLIT = re.compile(r"^-{10,}\s*$", re.MULTILINE)
_INTERFACE = re.compile(r"^Interface:\s*(?P<name>[^,\s]+)\s*,", re.MULTILINE)
_SYSNAME = re.compile(r"^\s*SysName:\s*(?P<name>\S+)\s*$", re.MULTILINE)
_CHASSIS_MAC = re.compile(
    r"^\s*ChassisID:\s*mac\s+(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})",
    re.MULTILINE | re.IGNORECASE,
)
_PORT_MAC = re.compile(
    r"^\s*PortID:\s*mac\s+(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})",
    re.MULTILINE | re.IGNORECASE,
)
_PORT_DESCR = re.compile(r"^\s*PortDescr:\s*(?P<port>\S+)\s*$", re.MULTILINE)
# The first IPv4 MgmtIP only: lldpd lists IPv4 and IPv6 management addresses,
# and Atlas's transport dials IPv4.
_MGMT_IPV4 = re.compile(
    r"^\s*MgmtIP:\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s*$", re.MULTILINE
)
_CAPABILITY_ON = re.compile(
    r"^\s*Capability:\s*(?P<name>\w+),\s*on\s*$", re.MULTILINE
)


def parse_lldp_neighbors(
    text: str, *, local_device_id: str
) -> tuple[NetworkNeighbor, ...]:
    """Every neighbor lldpd names, as canonical adjacency evidence.

    ``remote_management_ip`` is populated from ``MgmtIP`` because the peer is
    advertising its own management address — the CDP precedent traversal
    already trusts. A block missing a SysName is skipped, not guessed: a
    chassis MAC alone does not name a device.
    """

    neighbors: list[NetworkNeighbor] = []
    for block in _BLOCK_SPLIT.split(text or ""):
        interface = _INTERFACE.search(block)
        sysname = _SYSNAME.search(block)
        if interface is None or sysname is None:
            continue
        mgmt = _MGMT_IPV4.search(block)
        port = _PORT_DESCR.search(block)
        chassis = _CHASSIS_MAC.search(block)
        port_mac = _PORT_MAC.search(block)
        capabilities = tuple(
            m.group("name").casefold() for m in _CAPABILITY_ON.finditer(block)
        )
        metadata: dict[str, object] = {
            "source_command": "show lldp neighbors",
        }
        if chassis:
            metadata["remote_chassis_mac"] = chassis.group("mac").casefold()
        if port_mac:
            # The far interface's own hardware address — the same join key MAC
            # correlation uses, arriving from an independent witness.
            metadata["remote_port_mac"] = port_mac.group("mac").casefold()
        if capabilities:
            metadata["remote_capabilities"] = capabilities
        neighbors.append(NetworkNeighbor(
            local_device_id=local_device_id,
            local_interface=interface.group("name"),
            remote_hostname=sysname.group("name"),
            remote_interface=port.group("port") if port else None,
            remote_management_ip=mgmt.group("ip") if mgmt else None,
            protocol="lldp",
            metadata=metadata,
        ))
    neighbors.sort(key=lambda n: (n.local_interface, n.remote_hostname.casefold()))
    return tuple(neighbors)
