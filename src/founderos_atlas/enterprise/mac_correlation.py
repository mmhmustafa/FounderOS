"""Resolving a switch port to the device on the other end (PR-048).

A layer-2 switch is transparent. The routers either side of it are adjacent to
*each other*; neither can see the switch, and the switch cannot name either of
them. So no single device's evidence contains a physical link — the switch
knows "hardware address ``aa:c1:ab:2e:c9:0e`` is on port eth1", and delhi-core
knows "my eth2 is ``aa:c1:ab:2e:c9:0e``". Only the enterprise layer sees both.

This module joins those two observations and nothing else:

    switch MAC-to-port  ×  router interface hardware address
        -> "delhi-sw1:eth1 is physically connected to delhi-core:eth2"

That is a *derivation*, not an inference. Both halves are directly observed, the
join key is a globally unique hardware address, and the result is reported only
when exactly one device owns that address. Everything ambiguous is dropped and
counted, never guessed — a wrong physical link is worse than a missing one,
because an operator would plan a change around it.

Deterministic: same evidence in, same links out, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


# Why a candidate MAC was not turned into a link. Reported, never silent: a
# switch port that Atlas could not resolve is a gap the operator should see.
UNRESOLVED_UNKNOWN_MAC = "unknown-mac"
UNRESOLVED_AMBIGUOUS = "ambiguous-mac"
UNRESOLVED_SELF = "switch-own-address"


@dataclass(frozen=True)
class PhysicalLink:
    """One switch port resolved to the interface plugged into it."""

    switch_device_id: str
    switch_hostname: str
    switch_port: str
    peer_device_id: str
    peer_hostname: str
    peer_interface: str
    hardware_address: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "switch_device_id": self.switch_device_id,
            "switch_hostname": self.switch_hostname,
            "switch_port": self.switch_port,
            "peer_device_id": self.peer_device_id,
            "peer_hostname": self.peer_hostname,
            "peer_interface": self.peer_interface,
            "hardware_address": self.hardware_address,
            # The evidence, named, so a reader can go and check it.
            "evidence": (
                f"{self.switch_hostname} learned {self.hardware_address} on "
                f"port {self.switch_port}; {self.peer_hostname} reports "
                f"{self.hardware_address} on {self.peer_interface}"
            ),
        }


@dataclass(frozen=True)
class UnresolvedPort:
    """A learned address Atlas could not attribute to a known device."""

    switch_device_id: str
    switch_hostname: str
    switch_port: str
    hardware_address: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "switch_device_id": self.switch_device_id,
            "switch_hostname": self.switch_hostname,
            "switch_port": self.switch_port,
            "hardware_address": self.hardware_address,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MacCorrelation:
    """Every physical link derived, and every port that stayed unresolved."""

    links: tuple[PhysicalLink, ...] = ()
    unresolved: tuple[UnresolvedPort, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "links": [link.to_dict() for link in self.links],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "link_count": len(self.links),
            "unresolved_count": len(self.unresolved),
        }


def build_address_owners(
    devices: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, str, str]]:
    """Map every observed hardware address to the interface that owns it.

    An address claimed by two different devices is dropped from the index
    entirely rather than resolved to whichever was seen first. A duplicate MAC
    is a real (and serious) network condition; picking a winner would invent a
    link and hide the fault.
    """

    owners: dict[str, tuple[str, str, str]] = {}
    contested: set[str] = set()
    for device in devices:
        device_id = str(device.get("device_id") or "")
        hostname = str(device.get("hostname") or device_id)
        for interface in device.get("interfaces") or ():
            metadata = interface.get("metadata") or {}
            mac = str(metadata.get("hardware_address") or "").casefold()
            if not mac:
                continue
            name = str(interface.get("name") or "")
            existing = owners.get(mac)
            if existing is not None and existing[:2] != (device_id, hostname):
                contested.add(mac)
            owners[mac] = (device_id, hostname, name)
    for mac in contested:
        owners.pop(mac, None)
    return owners


def correlate(
    devices: Iterable[Mapping[str, Any]],
) -> MacCorrelation:
    """Derive physical links from switch MAC tables and interface addresses.

    ``devices`` are canonical device dicts (``device_id``, ``hostname``,
    ``interfaces``, ``metadata``) — the same shape every consumer already
    reads. Switches are recognised by carrying a ``mac_table``, not by their
    hostname or platform string: a platform that starts reporting one later
    correlates without a change here.
    """

    devices = list(devices)
    owners = build_address_owners(devices)
    contested = _contested_addresses(devices)

    links: list[PhysicalLink] = []
    unresolved: list[UnresolvedPort] = []

    for device in devices:
        metadata = device.get("metadata") or {}
        table = metadata.get("mac_table") or ()
        if not table:
            continue
        switch_id = str(device.get("device_id") or "")
        switch_host = str(device.get("hostname") or switch_id)
        own = _own_addresses(device)

        for entry in table:
            row = dict(entry)
            mac = str(row.get("mac") or "").casefold()
            port = str(row.get("port") or "")
            if not mac or not port:
                continue
            if mac in own:
                unresolved.append(UnresolvedPort(
                    switch_id, switch_host, port, mac, UNRESOLVED_SELF
                ))
                continue
            if mac in contested:
                unresolved.append(UnresolvedPort(
                    switch_id, switch_host, port, mac, UNRESOLVED_AMBIGUOUS
                ))
                continue
            owner = owners.get(mac)
            if owner is None:
                # Something is plugged in that Atlas has never authenticated
                # to. That is a real finding — an unmanaged device on a port —
                # not an error, and certainly not a link to nowhere.
                unresolved.append(UnresolvedPort(
                    switch_id, switch_host, port, mac, UNRESOLVED_UNKNOWN_MAC
                ))
                continue
            peer_id, peer_host, peer_iface = owner
            if peer_id == switch_id:
                unresolved.append(UnresolvedPort(
                    switch_id, switch_host, port, mac, UNRESOLVED_SELF
                ))
                continue
            links.append(PhysicalLink(
                switch_device_id=switch_id,
                switch_hostname=switch_host,
                switch_port=port,
                peer_device_id=peer_id,
                peer_hostname=peer_host,
                peer_interface=peer_iface,
                hardware_address=mac,
            ))

    links.sort(key=lambda l: (l.switch_hostname.casefold(), l.switch_port))
    unresolved.sort(key=lambda u: (u.switch_hostname.casefold(), u.switch_port))
    return MacCorrelation(links=tuple(links), unresolved=tuple(unresolved))


def _own_addresses(device: Mapping[str, Any]) -> set[str]:
    """The switch's own interface addresses.

    A bridge's FDB contains its own ports' addresses. Correlating one would
    conclude the switch is plugged into itself.
    """

    own: set[str] = set()
    for interface in device.get("interfaces") or ():
        metadata = interface.get("metadata") or {}
        mac = str(metadata.get("hardware_address") or "").casefold()
        if mac:
            own.add(mac)
    return own


def _contested_addresses(devices: Iterable[Mapping[str, Any]]) -> set[str]:
    seen: dict[str, str] = {}
    contested: set[str] = set()
    for device in devices:
        device_id = str(device.get("device_id") or "")
        for interface in device.get("interfaces") or ():
            metadata = interface.get("metadata") or {}
            mac = str(metadata.get("hardware_address") or "").casefold()
            if not mac:
                continue
            if mac in seen and seen[mac] != device_id:
                contested.add(mac)
            seen[mac] = device_id
    return contested
